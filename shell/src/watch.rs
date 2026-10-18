// Сторож обновления и перезапуска (Т10, 18.10.2026): `DentPilot.exe --watch …`.
//
// Движок перед установкой обновления (и перед перезапуском) заводит задачу
// планировщика от обычного пользователя, и та запускает КОПИЮ оболочки
// (`<данные>\updates\DentPilot-watch.exe`; для перезапуска — саму
// `DentPilot.exe`) в этом режиме: окно с заставкой «Se instalează
// actualizarea…», ожидание итога мастера (`/RESULT=`), ожидание выхода старой
// оболочки и запуск `{app}\DentPilot.exe`. Python-сторож окна pywebview
// (`bot/app/restartwatch.py`, `desktop._watch_mode`) делает то же самое: у
// движка pywebview нет, поэтому здесь — свой.
//
// ⛔ Аргументы, слова итога и тексты заставки — те же, что у Python-сторожа
// (`restartwatch.argv_for`, `decide`, константы `TEXT_*`); тексты сверяет
// `tests/test_restart.py`. ⛔ Копия, а не `{app}\DentPilot.exe`, когда ставится
// обновление: мастер заменяет файлы программы, и сторож из `{app}` он закрыл бы
// вместе с ней. ⛔ Ни плагина «один экземпляр», ни значка, ни журнала оболочки:
// сторож — другой процесс, и запускаемая им программа не должна найти «первый
// экземпляр» в нём. ⛔ Задача планировщика запускает сторожа вне «задания»
// оболочки; программу он запускает отдельной группой, без окна консоли — так же,
// как Python-сторож, проверенный живыми обновлениями с 11.10.

use std::ffi::OsString;
use std::io::Read;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE, WAIT_TIMEOUT};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows_sys::Win32::System::RemoteDesktop::ProcessIdToSessionId;
use windows_sys::Win32::System::Threading::{
    GetCurrentProcessId, OpenProcess, QueryFullProcessImageNameW, WaitForSingleObject,
    CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, DETACHED_PROCESS, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE,
};

use crate::paths::log;

pub const FLAG: &str = "--watch";
/// Итог мастера ждём не дольше — задача планировщика живёт 10 минут.
const WAIT: Duration = Duration::from_secs(9 * 60);
/// После итога — пока старая оболочка не выйдет: при живой новая отдала бы
/// запуск ей (один экземпляр) и закрылась.
const EXIT_WAIT: Duration = Duration::from_secs(60);
const STEP: Duration = Duration::from_millis(500);
const NO_RESULT: &str = "-";
const STARTED: &str = "started";

/// Мастер — процессы с этими именами: копия `privileged.SETUP_NAME`, которую
/// запускает операция за UAC, и её распаковка Inno
/// (`%TEMP%\is-XXXXX.tmp\DentPilot-Setup.tmp`). Сверяет `test_restart`.
const SETUP_NAMES: [&str; 2] = ["DentPilot-Setup.exe", "DentPilot-Setup.tmp"];
/// Журнал мастера (`privileged.SETUP_LOG`) — рядом с файлом итога; только для строки журнала.
const SETUP_LOG: &str = "setup.log";
/// «started» стоит, а мастера нет столько подряд — итог писать некому.
const SETUP_GONE: Duration = Duration::from_secs(20);

// Тексты заставки — те же константы, что `restartwatch.TEXT_*`.
const TEXT_INSTALL: &str = "Se instalează actualizarea…";
const TEXT_RESTART: &str = "Se repornește DentPilot…";
const TEXT_CLOSING: &str = "Se închide versiunea curentă…";
const TEXT_NEW: &str = "Se pornește versiunea nouă…";
const TEXT_ROLLBACK: &str = "Actualizarea nu s-a instalat — se pornește versiunea curentă…";

/// Что сторожу делать (`restartwatch.Plan`). Пути абсолютные: задача
/// планировщика стартует в system32, окружения движка у неё нет.
#[derive(Debug, Clone, PartialEq)]
pub struct Plan {
    pub proof: PathBuf,
    pub task: String,
    pub result: Option<PathBuf>,
    pub pid: u32,
    pub label: String,
    pub primary: String,
    pub profile: PathBuf,
    pub launch: Vec<OsString>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Verdict {
    /// запускать программу: «ok» — новая версия, «fail…» — откатившаяся старая
    Start,
    /// «cancelled» — программа жива сама (обновление не пошло)
    Done,
    Wait,
}

pub fn is_watch(args: &[OsString]) -> bool {
    args.first().is_some_and(|a| a == FLAG)
}

/// `--watch proof task result pid label primary profile launch…` — разбор
/// (`restartwatch.parse`).
pub fn parse(args: &[OsString]) -> Result<Plan, String> {
    if !is_watch(args) {
        return Err("nu este --watch".into());
    }
    if args.len() < 9 {
        return Err(format!("{FLAG}: 8 argumente și comanda de pornire, primite {}", args.len() - 1));
    }
    let s = |i: usize| args[i].to_string_lossy().into_owned();
    let pid = s(4).trim().parse::<u32>().map_err(|_| format!("{FLAG}: pid nu e număr: {:?}", s(4)))?;
    Ok(Plan {
        proof: PathBuf::from(&args[1]),
        task: s(2),
        result: (args[3] != NO_RESULT).then(|| PathBuf::from(&args[3])),
        pid,
        label: s(5),
        primary: s(6),
        profile: PathBuf::from(&args[7]),
        launch: args[8..].to_vec(),
    })
}

/// Что говорит файл итога (`restartwatch.decide`). ⚠️ «ok» без перевода
/// строки и с ним — одно (канарейка 03.10); «fail» с причиной второй строкой.
pub fn decide(text: Option<&str>) -> Verdict {
    let Some(t) = text else { return Verdict::Wait };
    let t = t.trim();
    if t == "cancelled" {
        Verdict::Done
    } else if t == "ok" || t.starts_with("fail") {
        Verdict::Start
    } else {
        Verdict::Wait
    }
}

fn read_result(plan: &Plan) -> Option<String> {
    let Some(p) = &plan.result else { return Some("ok".into()) }; // простой перезапуск
    let mut raw = Vec::new();
    std::fs::File::open(p).ok()?.read_to_end(&mut raw).ok()?;
    Some(String::from_utf8_lossy(&raw).into_owned())
}

pub fn outcome_text(text: Option<&str>) -> &'static str {
    if text.unwrap_or("").trim().starts_with("fail") {
        TEXT_ROLLBACK
    } else {
        TEXT_NEW
    }
}

fn pid_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    unsafe {
        let h = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
        if h.is_null() {
            return false;
        }
        let alive = WaitForSingleObject(h, 0) == WAIT_TIMEOUT;
        CloseHandle(h);
        alive
    }
}

fn norm(p: &Path) -> String {
    let p = std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
    let s = p.display().to_string().to_lowercase();
    s.strip_prefix(r"\\?\").map(str::to_string).unwrap_or(s)
}

fn image_path(pid: u32) -> Option<PathBuf> {
    unsafe {
        let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if h.is_null() {
            return None;
        }
        let mut buf = vec![0u16; 1024];
        let mut n = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(h, PROCESS_NAME_WIN32, buf.as_mut_ptr(), &mut n) != 0;
        CloseHandle(h);
        ok.then(|| PathBuf::from(String::from_utf16_lossy(&buf[..n as usize])))
    }
}

/// Жив ли в ЭТОМ сеансе Windows другой процесс того же файла, что запускаем
/// (`{app}\DentPilot.exe`). ⭐ Страховка к `pid`: pid — родитель движка, и
/// если движок запустил кто-то другой (стенд), старая оболочка всё равно
/// найдётся. Чужие сеансы (вторая учётка) не ждём — их программу закроет мастер.
fn same_exe_alive(exe: &Path) -> Option<u32> {
    let name = exe.file_name()?.to_string_lossy().to_lowercase();
    let want = norm(exe);
    unsafe {
        let me = GetCurrentProcessId();
        let mut my_session = 0u32;
        ProcessIdToSessionId(me, &mut my_session);
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snap == INVALID_HANDLE_VALUE {
            return None;
        }
        let mut pe: PROCESSENTRY32W = std::mem::zeroed();
        pe.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        let mut found = None;
        let mut more = Process32FirstW(snap, &mut pe) != 0;
        while more {
            let len = pe.szExeFile.iter().position(|&c| c == 0).unwrap_or(pe.szExeFile.len());
            let pid = pe.th32ProcessID;
            if pid != me && String::from_utf16_lossy(&pe.szExeFile[..len]).to_lowercase() == name {
                let mut session = u32::MAX;
                ProcessIdToSessionId(pid, &mut session);
                if session == my_session && image_path(pid).is_some_and(|p| norm(&p) == want) {
                    found = Some(pid);
                    break;
                }
            }
            more = Process32NextW(snap, &mut pe) != 0;
        }
        CloseHandle(snap);
        found
    }
}

/// Мастер после «started» (18.10, 2.0.2). Операция за UAC пишет «started»
/// ПОСЛЕДНИМ, когда мастер уже запущен, а он жив непрерывно до своего итога
/// (загрузчик ждёт распаковку). Нет его `SETUP_GONE` подряд — итога не будет:
/// он не пошёл или погиб (живой проход 2.0.0 → 2.0.1: задание оболочки
/// погасило операцию до запуска мастера, и заставка висела бы 9 минут).
/// ⭐ До «started» не считается ничего: человек думает над окном UAC сколько хочет.
#[derive(Default)]
struct SetupWatch {
    since: Option<Instant>,
}

impl SetupWatch {
    /// `true` — мастера нет и не будет. `running` спрашивается только при «started».
    fn gone(&mut self, text: Option<&str>, running: impl FnOnce() -> bool, now: Instant) -> bool {
        if text.map(str::trim) != Some(STARTED) || running() {
            self.since = None;
            return false;
        }
        now.duration_since(*self.since.get_or_insert(now)) >= SETUP_GONE
    }
}

/// Жив ли в системе (в любом сеансе) процесс с одним из имён. Снимок не
/// снялся — «жив»: не знаем, значит ждём, как раньше.
fn any_process_named(names: &[&str]) -> bool {
    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snap == INVALID_HANDLE_VALUE {
            return true;
        }
        let mut pe: PROCESSENTRY32W = std::mem::zeroed();
        pe.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        let mut found = false;
        let mut more = Process32FirstW(snap, &mut pe) != 0;
        while more && !found {
            let len = pe.szExeFile.iter().position(|&c| c == 0).unwrap_or(pe.szExeFile.len());
            let name = String::from_utf16_lossy(&pe.szExeFile[..len]);
            found = names.iter().any(|n| name.eq_ignore_ascii_case(n));
            more = Process32NextW(snap, &mut pe) != 0;
        }
        CloseHandle(snap);
        found
    }
}

/// Дождаться итога и выхода старой оболочки (`restartwatch.wait_for`).
/// ⚠️ Итога нет за 9 минут — всё равно «запускать»: лучше программа, чем
/// пустой экран (так вёл себя и bat). Мастер пропал при «started» — то же,
/// но сразу и со словами «не установилось» (`SetupWatch`).
fn wait(plan: &Plan, say: &dyn Fn(&str, f64, f64)) -> (Verdict, Option<String>) {
    say(if plan.result.is_some() { TEXT_INSTALL } else { TEXT_RESTART }, 12.0, 70.0);
    let t0 = Instant::now();
    let mut text = read_result(plan);
    let mut verdict = decide(text.as_deref());
    let mut setup = SetupWatch::default();
    while verdict == Verdict::Wait {
        if t0.elapsed() >= WAIT {
            log("watch: no installer result in time - starting the program anyway");
            verdict = Verdict::Start;
            break;
        }
        if setup.gone(text.as_deref(), || any_process_named(&SETUP_NAMES), Instant::now()) {
            let journal = plan.result.as_deref().and_then(Path::parent).map(|d| d.join(SETUP_LOG).exists());
            log(&format!(
                "watch: \"started\", but no installer process for {} s (setup.log: {journal:?}) - starting the current program",
                SETUP_GONE.as_secs()
            ));
            text = Some("fail\ninstaller not running".into()); // → TEXT_ROLLBACK
            verdict = Verdict::Start;
            break;
        }
        std::thread::sleep(STEP);
        text = read_result(plan);
        verdict = decide(text.as_deref());
    }
    log(&format!("watch: result {:?} after {:.1} s", text.as_deref().map(str::trim), t0.elapsed().as_secs_f64()));
    if verdict == Verdict::Done {
        return (verdict, text);
    }
    let exe = plan.launch.first().map(PathBuf::from).unwrap_or_default();
    let t1 = Instant::now();
    let mut said = false;
    loop {
        let other = same_exe_alive(&exe);
        if !pid_alive(plan.pid) && other.is_none() {
            break;
        }
        if t1.elapsed() >= EXIT_WAIT {
            log(&format!("watch: old program still alive (pid {} / {other:?}) - starting anyway", plan.pid));
            break;
        }
        if !said {
            say(TEXT_CLOSING, 80.0, 92.0);
            said = true;
        }
        std::thread::sleep(STEP);
    }
    log(&format!("watch: old program gone after {:.1} s", t1.elapsed().as_secs_f64()));
    (Verdict::Start, text)
}

fn launch(plan: &Plan) {
    let Some(exe) = plan.launch.first() else { return };
    let exe = PathBuf::from(exe);
    let dir = exe.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
    let r = Command::new(&exe)
        .args(&plan.launch[1..])
        .current_dir(&dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        .spawn();
    match r {
        Ok(c) => log(&format!("watch: started {} pid={}", exe.display(), c.id())),
        Err(e) => log(&format!("watch: program not started {}: {e}", exe.display())),
    }
}

/// Задачу планировщика сторож снимает за собой — так делал и bat.
fn finish(plan: &Plan) {
    let r = Command::new("schtasks")
        .args(["/delete", "/tn", &plan.task, "/f"])
        .creation_flags(CREATE_NO_WINDOW)
        .output();
    log(&format!("watch: task {} removed: {}", plan.task, r.map(|o| o.status.success()).unwrap_or(false)));
}

/// Вся работа сторожа; `say` — этап на заставку, `done` — заставке погаснуть.
fn work(plan: &Plan, say: &dyn Fn(&str, f64, f64), done: &dyn Fn()) {
    let (verdict, text) = wait(plan, say);
    if verdict == Verdict::Start {
        say(outcome_text(text.as_deref()), 96.0, 0.0);
        launch(plan);
        // новое окно успело появиться — без пустого экрана между ними
        std::thread::sleep(Duration::from_millis(1500));
    }
    done();
    std::thread::sleep(Duration::from_millis(400));
    finish(plan);
}

/// Заставка: последний этап ждёт загрузки страницы (как `push_splash`).
#[derive(Default)]
struct View {
    loaded: bool,
    stage: Option<(String, f64, f64)>,
}

fn js(win: &tauri::WebviewWindow, code: String) {
    let _ = win.eval(code);
}

fn push(win: &tauri::WebviewWindow, plan: &Plan, view: &View) {
    js(win, format!("dpHello({},{})", crate::js_str(&plan.primary), crate::js_str(&plan.label)));
    if let Some((t, p, u)) = &view.stage {
        js(win, format!("dpStage({},{},{})", crate::js_str(t), p, u));
    }
}

/// Режим сторожа целиком; число — код выхода процесса.
pub fn main(args: &[OsString], context: tauri::Context<tauri::Wry>) -> i32 {
    let mut plan = match parse(args) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("supraveghetorul nu a pornit: {e}");
            return 2;
        }
    };
    // «пошёл» — это ждёт движок (`update._schtasks_run`), первым делом
    let _ = std::fs::write(&plan.proof, ".");
    if !crate::valid_color(&plan.primary) {
        plan.primary = crate::TEAL.into();
    }
    if let Some(dir) = plan.proof.parent() {
        crate::paths::open_log(&dir.join("watch.log"));
    }
    log(&format!(
        "DentPilot watch {} pid={} task={} result={:?} wait-pid={} launch={:?}",
        crate::VERSION,
        std::process::id(),
        plan.task,
        plan.result,
        plan.pid,
        plan.launch
    ));
    crate::notices::set_process_aumid();
    let plan = Arc::new(plan);
    let view = Arc::new(Mutex::new(View::default()));

    let (p1, v1) = (plan.clone(), view.clone());
    let built = tauri::Builder::default()
        // ⛔ Крестик не закрывает: мастер идёт, и закрытый сторож — это
        // программа, которую больше некому запустить.
        .on_window_event(|_w, ev| {
            if let WindowEvent::CloseRequested { api, .. } = ev {
                api.prevent_close();
            }
        })
        .setup(move |app| {
            let plan = p1.clone();
            if let Err(e) = std::fs::create_dir_all(&plan.profile) {
                log(&format!("watch: WebView2 profile not created: {e}"));
            }
            let url = format!("splash.html?c=%23{}", &plan.primary[1..]);
            let (p2, v2) = (plan.clone(), v1.clone());
            // ⛔ Свой профиль WebView2: профиль программы занят ею самой (она
            // ещё закрывается), второе окно на нём не открылось бы.
            // ⛔ Окно не открылось — сторож работает без экрана, а не `?`: ошибку
            // setup Tauri делает паникой, и программу больше некому запустить.
            let window = WebviewWindowBuilder::new(app, "watch", WebviewUrl::App(url.into()))
                .title("DentPilot")
                .inner_size(1280.0, 860.0)
                .min_inner_size(960.0, 640.0)
                .center()
                .background_color(crate::tint(&plan.primary, 0.06))
                .data_directory(plan.profile.clone())
                .devtools(false)
                .on_navigation(|u| u.as_str().starts_with(crate::SHELL_PAGES))
                .on_page_load(move |win, p| {
                    if p.event() != tauri::webview::PageLoadEvent::Finished {
                        return;
                    }
                    let mut v = v2.lock().unwrap();
                    v.loaded = true;
                    push(&win, &p2, &v);
                })
                .build();
            if let Err(e) = window {
                log(&format!("watch: no window ({e}) - watching without a screen"));
            }
            let h = app.handle().clone();
            let (p3, v3) = (plan.clone(), v1.clone());
            std::thread::spawn(move || {
                let hs = h.clone();
                let say = move |t: &str, p: f64, u: f64| {
                    let mut v = v3.lock().unwrap();
                    v.stage = Some((t.to_string(), p, u));
                    if v.loaded {
                        if let Some(w) = hs.get_webview_window("watch") {
                            js(&w, format!("dpStage({},{},{})", crate::js_str(t), p, u));
                        }
                    }
                };
                let hd = h.clone();
                let done = move || {
                    if let Some(w) = hd.get_webview_window("watch") {
                        js(&w, "window.dpDone && dpDone()".into());
                    }
                };
                work(&p3, &say, &done);
                h.exit(0);
            });
            Ok(())
        })
        .build(context);
    match built {
        Ok(app) => app.run_return(|_, _| {}),
        Err(e) => {
            // без окна (WebView2 нет) сторож всё равно обязан перезапустить
            log(&format!("watch: no window ({e}) - watching without a screen"));
            work(&plan, &|_, _, _| {}, &|| {});
            0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(v: &[&str]) -> Vec<OsString> {
        v.iter().map(OsString::from).collect()
    }

    #[test]
    fn parses_python_argv() {
        // restartwatch.argv_for: --watch proof task result pid label primary profile launch…
        let a = args(&[
            "--watch",
            r"C:\d\updates\DentPilotUpdate.run",
            "DentPilotUpdate",
            r"C:\d\updates\install.result",
            "4242",
            "1.46.1 › 1.47.0",
            "#0E9F8A",
            r"C:\u\DentPilot\webview-watch",
            r"C:\Program Files\DentPilot\DentPilot.exe",
        ]);
        let p = parse(&a).unwrap();
        assert_eq!(p.pid, 4242);
        assert_eq!(p.result, Some(PathBuf::from(r"C:\d\updates\install.result")));
        assert_eq!(p.label, "1.46.1 › 1.47.0");
        assert_eq!(p.launch, args(&[r"C:\Program Files\DentPilot\DentPilot.exe"]));
        let mut b = a.clone();
        b[3] = NO_RESULT.into();
        assert_eq!(parse(&b).unwrap().result, None);
        assert!(parse(&a[..8]).is_err());
        b[4] = "x".into();
        assert!(parse(&b).is_err());
        assert!(!is_watch(&args(&[r"C:\pacient.pdf"])));
        assert!(!is_watch(&args(&["--tray"])));
    }

    #[test]
    fn decides_like_restartwatch() {
        // те же случаи, что test_update_setup (`rw.decide`)
        let cases = [
            (Some("ok"), Verdict::Start),
            (Some("ok\r\n"), Verdict::Start),
            (Some("fail"), Verdict::Start),
            (Some("fail\r\nmotiv"), Verdict::Start),
            (Some("cancelled"), Verdict::Done),
            (Some("cancelled\r\n"), Verdict::Done),
            (Some("okay"), Verdict::Wait),
            (Some(""), Verdict::Wait),
            (Some("started"), Verdict::Wait),
            (None, Verdict::Wait),
        ];
        for (t, v) in cases {
            assert_eq!(decide(t), v, "{t:?}");
        }
        assert_eq!(outcome_text(Some("fail motiv")), TEXT_ROLLBACK);
        assert_eq!(outcome_text(Some("ok")), TEXT_NEW);
    }

    #[test]
    fn gives_up_only_when_installer_is_gone_after_started() {
        let t = Instant::now();
        let at = |s: u64| t + Duration::from_secs(s);
        let mut w = SetupWatch::default();
        // ждём ответа в окне UAC — сколько угодно, процессы не спрашиваются
        assert!(!w.gone(None, || panic!("спросили до «started»"), at(0)));
        assert!(!w.gone(Some(""), || panic!("спросили до «started»"), at(300)));
        // мастер идёт — ждём итога
        assert!(!w.gone(Some("started"), || true, at(301)));
        assert!(!w.gone(Some("started"), || true, at(500)));
        // мастера нет: отсчёт с первого «нет», и только подряд
        assert!(!w.gone(Some("started\r\n"), || false, at(501)));
        assert!(!w.gone(Some("started"), || false, at(520)));
        assert!(w.gone(Some("started"), || false, at(521)));
        let mut w = SetupWatch::default();
        assert!(!w.gone(Some("started"), || false, at(0)));
        assert!(!w.gone(Some("started"), || true, at(19)));
        assert!(!w.gone(Some("started"), || false, at(30)));
        assert!(!w.gone(Some("started"), || false, at(49)));
        assert!(w.gone(Some("started"), || false, at(50)));
        // итог пришёл — решает он, а не процессы
        let mut w = SetupWatch::default();
        assert!(!w.gone(Some("started"), || false, at(0)));
        assert!(!w.gone(Some("ok"), || false, at(60)));
    }

    #[test]
    fn finds_processes_by_name() {
        let me = std::env::current_exe().unwrap();
        let name = me.file_name().unwrap().to_string_lossy().to_uppercase();
        assert!(any_process_named(&[&name]), "свой процесс не нашёлся: {name}");
        assert!(!any_process_named(&["net-takogo-dentpilot-processa.exe"]));
    }

    #[test]
    fn own_process_is_not_the_old_one() {
        let me = std::env::current_exe().unwrap();
        assert_eq!(same_exe_alive(&me), None);
        assert!(pid_alive(std::process::id()));
        assert!(!pid_alive(0));
    }
}
