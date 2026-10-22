// Где что лежит у оболочки (контракт § 1).
//
// ⭐ BASE — папка DentPilot.exe: там `engine\`, `install.json`, `demo.flag`.
// Папку ДАННЫХ клиники оболочка не знает и не угадывает: её считает движок и
// сообщает словом `ready` (поле `data`).

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

pub struct Paths {
    /// Папка DentPilot.exe.
    pub base: PathBuf,
    /// Профиль WebView2 (куки входа, кэш) — ПОСТОЯННЫЙ, свой у учётки Windows.
    pub profile: PathBuf,
    /// Своё состояние оболочки: shell.json, shell.log, значок для уведомлений.
    pub state: PathBuf,
    /// Профиль задан стендом (`DENTART_PROFILE_DIR`): отдельный экземпляр.
    pub stand: bool,
}

fn env_abs(name: &str) -> Option<PathBuf> {
    let raw = std::env::var(name).ok()?;
    let p = PathBuf::from(raw.trim().trim_matches(|c| c == '"' || c == '\''));
    p.is_absolute().then_some(p)
}

fn local_app_data() -> PathBuf {
    env_abs("LOCALAPPDATA").unwrap_or_else(|| {
        let home = env_abs("USERPROFILE").unwrap_or_else(|| PathBuf::from(r"C:\Users\Default"));
        home.join("AppData").join("Local")
    })
}

impl Paths {
    pub fn find() -> Paths {
        let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("DentPilot.exe"));
        let base = exe.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
        let mine = local_app_data().join("DentPilot");
        // Те же пути, что `desktop.profile_dir()`: стенд (`DENTART_PROFILE_DIR`),
        // иначе профиль учётки. (Режим флешки `portable.flag` снят 22.10.2026:
        // никакая сборка его не ставила, а программа-папка в нём не обновлялась.)
        // ⛔ Не папка клиники: `ProgramData` общая на всех учёток, и кука
        // входа одного человека досталась бы другому.
        let (profile, stand) = match env_abs("DENTART_PROFILE_DIR") {
            Some(p) => (p, true),
            None => (mine.join("webview"), false),
        };
        // shell.json — по учётке Windows всегда; у стенда — рядом с его
        // профилем, а не у Олега.
        let state = if stand {
            profile.parent().map(Path::to_path_buf).unwrap_or_else(|| profile.clone())
        } else {
            mine
        };
        Paths { base, profile, state, stand }
    }

    pub fn log_file(&self) -> PathBuf {
        self.state.join("shell.log")
    }
}

// ---- журнал оболочки --------------------------------------------------------
// Свои события и всё, что движок пишет мимо строк DP1 (stderr — трассы его
// падений: в noconsole-сборке они ушли бы в никуда). Прошлый запуск —
// `shell.log.1`; больше двух файлов не держим.

static LOG: OnceLock<Mutex<Option<File>>> = OnceLock::new();
/// Куда дописать аварию, пока журнал не открыт (паника до `setup`).
static PANIC_TO: OnceLock<PathBuf> = OnceLock::new();

pub fn open_log(path: &Path) {
    if let Some(dir) = path.parent() {
        let _ = fs::create_dir_all(dir);
    }
    if path.exists() {
        let _ = fs::rename(path, path.with_extension("log.1"));
    }
    let file = OpenOptions::new().create(true).append(true).open(path).ok();
    let _ = LOG.set(Mutex::new(file));
}

pub fn log(msg: &str) {
    let Some(slot) = LOG.get() else { return };
    let Ok(mut guard) = slot.lock() else { return };
    if let Some(f) = guard.as_mut() {
        let _ = writeln!(f, "{} {}", now(), msg);
        let _ = f.flush();
    }
}

// ---- авария -----------------------------------------------------------------
// panic="abort": после хука процесс уходит сразу (c0000409, данные 7), движок
// гасит задание, а окна с текстом нет — без этой строки от паники не осталось
// бы ничего, кроме записи Windows со смещением в exe без символов.
// ⛔ Сам хук не паникует и не ждёт: ни unwrap, ни `thread::current()` (она
// паникует после разрушения TLS потока), замок журнала — только `try_lock`;
// не вышло записать — молча дальше.

/// `PANIC <сообщение> at <файл:строка> thread=<имя> tid=<n>` — в журнал
/// оболочки (у сторожа — его `watch.log`). Ставится первым делом в `main()`.
pub fn panic_hook() {
    let prev = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let msg = info.payload_as_str().unwrap_or("(no message)");
        let at = match info.location() {
            Some(l) => format!("{}:{}", l.file(), l.line()),
            None => "?".into(),
        };
        log_always(&panic_line(msg, &at, &thread_name()));
        prev(info); // в сборке разработки — ещё и в консоль
    }));
}

/// Журнал ещё не открыт — авария дописывается в этот файл.
pub fn panic_fallback(path: PathBuf) {
    let _ = PANIC_TO.set(path);
}

fn panic_line(msg: &str, at: &str, thread: &str) -> String {
    // одна строка журнала: переводы строк сообщения (Debug ошибки) — в « | »
    let flat: String = msg
        .split(['\r', '\n'])
        .filter(|s| !s.trim().is_empty())
        .collect::<Vec<_>>()
        .join(" | ")
        .chars()
        .take(2000)
        .collect();
    format!("PANIC {flat} at {at} thread={thread}")
}

/// Имя потока — у Windows (`GetThreadDescription`: std называет им свои
/// потоки), не у `thread::current()`.
fn thread_name() -> String {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::System::Threading::{GetCurrentThread, GetCurrentThreadId, GetThreadDescription};
    let mut name = String::new();
    unsafe {
        let mut p: *mut u16 = std::ptr::null_mut();
        if GetThreadDescription(GetCurrentThread(), &mut p) >= 0 && !p.is_null() {
            let mut n = 0;
            while n < 256 && *p.add(n) != 0 {
                n += 1;
            }
            name = String::from_utf16_lossy(std::slice::from_raw_parts(p, n));
            LocalFree(p as _);
        }
    }
    let name = if name.is_empty() { "<unnamed>" } else { name.as_str() };
    format!("{name} tid={}", unsafe { GetCurrentThreadId() })
}

/// В журнал, даже когда он ещё не открыт (тогда — дописью в `panic_fallback`);
/// замок — только `try_lock`: так пишут хук паники и «запуск не удался».
pub fn log_always(line: &str) {
    let text = format!("{} {}\n", now(), line);
    if let Some(slot) = LOG.get() {
        // замок может держать другой поток посреди записи — подождать чуть-чуть
        for _ in 0..50 {
            let guard = match slot.try_lock() {
                Ok(g) => Some(g),
                Err(std::sync::TryLockError::Poisoned(p)) => Some(p.into_inner()),
                Err(std::sync::TryLockError::WouldBlock) => None,
            };
            match guard {
                Some(mut g) => {
                    if let Some(f) = g.as_mut() {
                        let _ = f.write_all(text.as_bytes());
                        let _ = f.flush();
                        return;
                    }
                    break; // журнал не открылся — дописью ниже
                }
                None => std::thread::sleep(std::time::Duration::from_millis(2)),
            }
        }
    }
    if let Some(path) = PANIC_TO.get() {
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = f.write_all(text.as_bytes());
        }
    }
}

fn now() -> String {
    use windows_sys::Win32::System::SystemInformation::GetLocalTime;
    let t = unsafe {
        let mut t = std::mem::zeroed();
        GetLocalTime(&mut t);
        t
    };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}.{:03}",
        t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn panic_line_is_one_line() {
        let l = panic_line("called `Result::unwrap()` on an `Err` value: x\r\n  y\n", r"src\main.rs:42", "main tid=7");
        assert_eq!(l, r"PANIC called `Result::unwrap()` on an `Err` value: x |   y at src\main.rs:42 thread=main tid=7");
        assert_eq!(panic_line(&"z".repeat(5000), "?", "t").len(), "PANIC  at ? thread=t".len() + 2000);
    }

    #[test]
    fn panic_goes_to_the_log() {
        // журнал процесса прогона — свой файл; хук ставится как в main()
        let dir = std::env::temp_dir().join(format!("dp-shell-panic-{}", std::process::id()));
        let file = dir.join("shell.log");
        open_log(&file);
        panic_hook();
        let r = std::thread::Builder::new()
            .name("dp-panic-probe".into())
            .spawn(|| panic!("probe {}\nsecond", 1 + 1))
            .unwrap()
            .join();
        assert!(r.is_err());
        let _ = std::panic::take_hook();
        let text = std::fs::read_to_string(&file).unwrap();
        let _ = fs::remove_dir_all(&dir);
        let line = text.lines().find(|l| l.contains(" PANIC ")).unwrap_or_else(|| panic!("{text:?}"));
        assert!(line.contains(" PANIC probe 2 | second at src") && line.contains("paths.rs:"), "{line}");
        assert!(line.contains(" thread=dp-panic-probe tid="), "{line}");
    }
}
