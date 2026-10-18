// Движок — Python-программа DentPilot отдельным процессом (контракт § 1–2).
//
// Где он: собранный `engine\DentPilot-Engine.exe` рядом с DentPilot.exe; в
// разработке — Python из venv `DENTPILOT_DEV_APP` и `bot\desktop.py`.
// Говорит строками `DP1 <json>` в stdout; слушает stdin (`stop`).
//
// ⛔ Движок держится в «задании» Windows (Job Object) с KILL_ON_JOB_CLOSE:
// оболочка упала или её сняли — Windows закрывает ручку задания и гасит ВСЁ
// дерево. Дерево настоящее даже в разработке: python.exe из venv — лишь
// пускач, интерпретатор — его ребёнок, и простой kill() оставил бы его
// сиротой с портом и базой. Процесс стартует ПРИОСТАНОВЛЕННЫМ и входит в
// задание ДО первой своей инструкции — иначе ребёнок успел бы родиться вне.
// ⭐ Честная остановка — словом `stop` и закрытым stdin (движок закрывает
// базу); задание снимается, только если за 10 с он не вышел.
// ⛔ В задании оказывается и процесс ЗА UAC: служба создаёт его «от имени»
// движка, и он наследует задание родителя. Что должно пережить оболочку
// (мастер обновления), выходит из задания по просьбе — `JOB_LIMITS`.

use std::ffi::{c_void, OsString};
use std::io::{BufRead, BufReader, Read, Write};
use std::mem::{size_of, zeroed};
use std::net::TcpStream;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::Sender;
use std::sync::Mutex;
use std::time::Duration;

use serde_json::Value;
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE, WAIT_OBJECT_0};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{
    GetExitCodeProcess, OpenProcess, OpenThread, ResumeThread, WaitForSingleObject,
    CREATE_NO_WINDOW, CREATE_SUSPENDED, INFINITE, PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_SYNCHRONIZE, THREAD_SUSPEND_RESUME,
};

use crate::paths::log;

pub const STOP_WAIT: Duration = Duration::from_secs(10);

/// Пределы «задания» движка.
/// ⛔ KILL_ON_JOB_CLOSE: оболочка вышла или упала — Windows гасит всё дерево.
/// ⭐ BREAKAWAY_OK (18.10, 2.0.2): выйти может только тот, кто ПОПРОСИЛ
/// (`CREATE_BREAKAWAY_FROM_JOB`), — мастер обновления
/// (`privileged._spawn_setup`). Без права выхода живой проход 2.0.0 → 2.0.1
/// встал: процесс за UAC наследует это задание, по «started» оболочка
/// закрылась, и Windows погасила его до запуска мастера.
/// ⛔ Не SILENT_BREAKAWAY_OK: тогда выходили бы ВСЕ дети молча — первым
/// интерпретатор venv в разработке (ребёнок пускача), и движок пережил бы
/// оболочку с портом и базой. Держат `cargo test` и стенд
/// `test_privileged.suite_setup_outlives_shell` (читает эту строку).
pub const JOB_LIMITS: u32 = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;

/// Пустое задание с `JOB_LIMITS`.
fn new_job() -> std::io::Result<HANDLE> {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err(std::io::Error::last_os_error());
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_LIMITS;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const c_void,
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            let e = std::io::Error::last_os_error();
            CloseHandle(job);
            return Err(e);
        }
        Ok(job)
    }
}

/// Слова движка (контракт § 2, версия 1) и его выход.
#[derive(Debug, Clone)]
pub enum Event {
    Hello { version: String, color: String },
    Stage { text: String, pct: f64, upto: f64 },
    Ready(Ready),
    Busy { url: String },
    Warn { text: String },
    Fatal { text: String, log: String },
    Quit { reason: String },
    Exited(Option<u32>),
}

#[derive(Debug, Clone)]
pub struct Ready {
    pub url: String,
    pub port: u16,
    pub session: String,
    pub data: String,
    pub lan: bool,
}

/// Чем запускать движок.
pub struct Launch {
    program: PathBuf,
    args: Vec<OsString>,
    cwd: PathBuf,
    pub what: String,
}

fn env_path(name: &str) -> Option<PathBuf> {
    let raw = std::env::var(name).ok()?;
    let p = PathBuf::from(raw.trim().trim_matches(|c| c == '"' || c == '\''));
    (!p.as_os_str().is_empty()).then_some(p)
}

impl Launch {
    /// ⭐ Собранный движок рядом важнее переменной разработки (контракт § 1):
    /// установленная программа не должна уйти в исходники из-за чужого
    /// окружения.
    pub fn find(base: &Path) -> Result<Launch, String> {
        let built = base.join("engine").join("DentPilot-Engine.exe");
        if built.exists() {
            return Ok(Launch {
                what: built.display().to_string(),
                program: built,
                args: Vec::new(),
                cwd: base.join("engine"),
            });
        }
        if let Some(app) = env_path("DENTPILOT_DEV_APP") {
            let python = app.join(".venv-desktop").join("Scripts").join("python.exe");
            if !python.exists() {
                return Err(format!("Nu găsesc {}.", python.display()));
            }
            // Только разработка: подставной движок оболочки (shell/dev/), а не
            // лаунчер программы — для опыта с этапами, `fatal`, `busy`, `quit`.
            let script = env_path("DENTPILOT_DEV_ENGINE")
                .unwrap_or_else(|| app.join("bot").join("desktop.py"));
            return Ok(Launch {
                what: format!("{} {}", python.display(), script.display()),
                program: python,
                args: vec![script.into_os_string()],
                cwd: app.join("bot"),
            });
        }
        Err(format!(
            "Nu găsesc motorul programului: {}.\nReinstalați DentPilot.",
            built.display()
        ))
    }
}

pub struct Engine {
    job: HANDLE,
    process: HANDLE,
    pub pid: u32,
    stdin: Mutex<Option<ChildStdin>>,
    _child: Child,
}

// Ручки живут в состоянии приложения и нужны в потоке выхода.
unsafe impl Send for Engine {}
unsafe impl Sync for Engine {}

impl Engine {
    /// Запустить движок; его слова и выход уходят в `tx`.
    pub fn start(launch: &Launch, token: &str, tx: Sender<Event>) -> std::io::Result<Engine> {
        let mut cmd = Command::new(&launch.program);
        cmd.args(&launch.args)
            .current_dir(&launch.cwd)
            .env("DENTART_SHELL", "tauri")
            .env("DENTART_SHELL_TOKEN", token)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
        let mut child = cmd.spawn()?;
        let pid = child.id();

        let job = match new_job() {
            Ok(job) => job,
            Err(e) => {
                let _ = child.kill();
                return Err(e);
            }
        };
        unsafe {
            if AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) == 0 {
                let e = std::io::Error::last_os_error();
                // приостановленный движок вне задания — снять самим
                let _ = child.kill();
                CloseHandle(job);
                return Err(e);
            }
        }
        // своя ручка процесса: ждать выхода в потоке, не трогая `Child`
        let process =
            unsafe { OpenProcess(PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };

        let stdout = child.stdout.take().expect("stdout");
        let stderr = child.stderr.take().expect("stderr");
        let stdin = child.stdin.take();
        let tx_out = tx.clone();
        std::thread::spawn(move || read_stdout(stdout, tx_out));
        std::thread::spawn(move || read_stderr(stderr));
        unsafe { resume_threads(pid) };
        if !process.is_null() {
            let watch = process as usize;
            std::thread::spawn(move || {
                let h = watch as HANDLE;
                let code = unsafe {
                    WaitForSingleObject(h, INFINITE);
                    let mut c = 0u32;
                    (GetExitCodeProcess(h, &mut c) != 0).then_some(c)
                };
                let _ = tx.send(Event::Exited(code));
            });
        }
        log(&format!("engine started pid={pid}: {}", launch.what));
        Ok(Engine { job, process, pid, stdin: Mutex::new(stdin), _child: child })
    }

    /// Честная остановка: слово `stop` и закрытый stdin; не вышел за `wait` —
    /// снять задание. Возвращает код выхода, если он известен.
    pub fn stop(&self, wait: Duration) -> Option<u32> {
        if let Some(mut stdin) = self.stdin.lock().ok().and_then(|mut s| s.take()) {
            let _ = stdin.write_all(b"{\"v\":1,\"cmd\":\"stop\"}\n");
            let _ = stdin.flush();
        } // ← stdin закрыт здесь
        if self.process.is_null() {
            unsafe { TerminateJobObject(self.job, 1) };
            return None;
        }
        unsafe {
            if WaitForSingleObject(self.process, wait.as_millis() as u32) != WAIT_OBJECT_0 {
                log("engine did not stop in time - job terminated");
                TerminateJobObject(self.job, 1);
                WaitForSingleObject(self.process, 3000);
            }
            let mut c = 0u32;
            (GetExitCodeProcess(self.process, &mut c) != 0).then_some(c)
        }
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        // ручка задания закрыта = всё, что ещё живо в задании, гасит Windows
        unsafe {
            CloseHandle(self.job);
            if !self.process.is_null() {
                CloseHandle(self.process);
            }
        }
    }
}

fn read_stdout(out: impl Read, tx: Sender<Event>) {
    let mut r = BufReader::new(out);
    let mut buf = Vec::new();
    loop {
        buf.clear();
        match r.read_until(b'\n', &mut buf) {
            Ok(0) | Err(_) => break,
            Ok(_) => {}
        }
        let line = String::from_utf8_lossy(&buf);
        let line = line.trim_end();
        match parse(line) {
            Some(ev) => {
                log(&format!("engine: {}", short(line)));
                if tx.send(ev).is_err() {
                    break;
                }
            }
            None if !line.is_empty() => log(&format!("engine> {line}")),
            None => {}
        }
    }
}

fn read_stderr(err: impl Read) {
    let mut r = BufReader::new(err);
    let mut buf = Vec::new();
    loop {
        buf.clear();
        match r.read_until(b'\n', &mut buf) {
            Ok(0) | Err(_) => break,
            Ok(_) => log(&format!("engine! {}", String::from_utf8_lossy(&buf).trim_end())),
        }
    }
}

fn short(s: &str) -> String {
    s.chars().take(300).collect()
}

/// Строка `DP1 <json>` → слово. Чужие строки и другая версия — мимо.
pub fn parse(line: &str) -> Option<Event> {
    let rest = line.strip_prefix("DP1 ")?;
    let v: Value = serde_json::from_str(rest).ok()?;
    if v["v"].as_i64() != Some(1) {
        return None;
    }
    let s = |k: &str| v[k].as_str().unwrap_or("").to_string();
    Some(match v["event"].as_str()? {
        "hello" => Event::Hello { version: s("version"), color: s("color") },
        "stage" => Event::Stage {
            text: s("text"),
            pct: v["pct"].as_f64().unwrap_or(0.0),
            upto: v["upto"].as_f64().unwrap_or(0.0),
        },
        "ready" => Event::Ready(Ready {
            url: s("url"),
            port: v["port"].as_u64().and_then(|p| u16::try_from(p).ok())?,
            session: s("session"),
            data: s("data"),
            lan: v["lan"].as_bool().unwrap_or(false),
        }),
        "busy" => Event::Busy { url: s("url") },
        "warn" => Event::Warn { text: s("text") },
        "fatal" => Event::Fatal { text: s("text"), log: s("log") },
        "quit" => Event::Quit { reason: s("reason") },
        _ => return None,
    })
}

/// Отпустить приостановленный процесс: все его потоки (на старте — один).
unsafe fn resume_threads(pid: u32) {
    let snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if snap == INVALID_HANDLE_VALUE {
        return;
    }
    let mut te: THREADENTRY32 = zeroed();
    te.dwSize = size_of::<THREADENTRY32>() as u32;
    if Thread32First(snap, &mut te) != 0 {
        loop {
            if te.th32OwnerProcessID == pid {
                let th = OpenThread(THREAD_SUSPEND_RESUME, 0, te.th32ThreadID);
                if !th.is_null() {
                    ResumeThread(th);
                    CloseHandle(th);
                }
            }
            if Thread32Next(snap, &mut te) == 0 {
                break;
            }
        }
    }
    CloseHandle(snap);
}

/// Токен оболочки для `/shell/notices` (контракт § 4): 32 случайных hex на запуск.
pub fn new_token() -> String {
    use windows_sys::Win32::Security::Cryptography::{
        BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
    };
    let mut b = [0u8; 16];
    let st = unsafe {
        BCryptGenRandom(std::ptr::null_mut(), b.as_mut_ptr(), b.len() as u32, BCRYPT_USE_SYSTEM_PREFERRED_RNG)
    };
    assert!(st == 0, "BCryptGenRandom");
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// GET к движку по 127.0.0.1 (без сторонних библиотек: запрос один и свой).
/// Возвращает (код, тело).
pub fn http_get(port: u16, path: &str, headers: &[(&str, &str)]) -> Option<(u16, String)> {
    let addr = format!("127.0.0.1:{port}");
    let mut s = TcpStream::connect_timeout(&addr.parse().ok()?, Duration::from_millis(800)).ok()?;
    let _ = s.set_read_timeout(Some(Duration::from_secs(5)));
    let mut req = format!("GET {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\n");
    for (k, v) in headers {
        req.push_str(&format!("{k}: {v}\r\n"));
    }
    req.push_str("\r\n");
    s.write_all(req.as_bytes()).ok()?;
    let mut raw = Vec::new();
    let _ = s.read_to_end(&mut raw);
    let text = String::from_utf8_lossy(&raw).into_owned();
    let (head, body) = text.split_once("\r\n\r\n")?;
    let code = head.split_whitespace().nth(1)?.parse().ok()?;
    Some((code, body.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_contract_lines() {
        let r = parse(r#"DP1 {"v":1,"event":"ready","url":"http://127.0.0.1:8094/admin","port":8094,"session":"clear","data":"D:\\x","lan":true}"#);
        match r {
            Some(Event::Ready(r)) => {
                assert_eq!(r.port, 8094);
                assert_eq!(r.session, "clear");
                assert!(r.lan);
            }
            other => panic!("{other:?}"),
        }
        assert!(parse(r#"DP1 {"v":2,"event":"hello"}"#).is_none());
        assert!(parse("INFO: uvicorn running").is_none());
        assert!(parse(r#"DP1 {"v":1,"event":"ready","url":"x","port":70000}"#).is_none());
        assert!(matches!(parse(r#"DP1 {"v":1,"event":"quit","reason":"update"}"#), Some(Event::Quit { .. })));
    }

    #[test]
    fn job_lets_out_only_who_asks() {
        use windows_sys::Win32::System::JobObjects::{
            QueryInformationJobObject, JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK,
        };
        let job = new_job().expect("job");
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        let ok = unsafe {
            QueryInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &mut info as *mut _ as *mut c_void,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        unsafe { CloseHandle(job) };
        assert!(ok != 0);
        let f = info.BasicLimitInformation.LimitFlags;
        assert_eq!(f, JOB_LIMITS);
        assert!(f & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE != 0, "движок пережил бы оболочку");
        assert!(f & JOB_OBJECT_LIMIT_BREAKAWAY_OK != 0, "мастер обновления погиб бы с оболочкой");
        assert!(f & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK == 0, "дети выходили бы молча");
    }
}
