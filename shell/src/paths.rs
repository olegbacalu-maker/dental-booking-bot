// Где что лежит у оболочки (контракт § 1).
//
// ⭐ BASE — папка DentPilot.exe: там `engine\`, `install.json`, `portable.flag`.
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
        // флешка (`portable.flag` — всё в одной папке), иначе профиль учётки.
        // ⛔ Не папка клиники: `ProgramData` общая на всех учёток, и кука
        // входа одного человека досталась бы другому.
        let (profile, stand) = match env_abs("DENTART_PROFILE_DIR") {
            Some(p) => (p, true),
            None if base.join("portable.flag").exists() => (base.join("webview"), false),
            None => (mine.join("webview"), false),
        };
        // shell.json — по учётке Windows всегда (и с флешки: место окна у
        // каждого ПК своё); у стенда — рядом с его профилем, а не у Олега.
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
