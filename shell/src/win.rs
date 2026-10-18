// Что принадлежит окну, а не странице: значок у часов, «крестик прячет»,
// выход с вопросом, масштаб, полный экран, папка данных, почта, сохранение
// файла, раскладка двух WebView.
//
// Решения Олега 18.10 (разбор § 11): крестик → к часам, программа работает
// дальше; выход — из меню значка или «Fișier › Închide», с вопросом; в
// первый раз — подсказка «я у часов».

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{App, AppHandle, LogicalPosition, LogicalSize, Manager};
use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::Controls::Dialogs::{
    GetSaveFileNameW, OFN_EXPLORER, OFN_NOCHANGEDIR, OFN_OVERWRITEPROMPT, OFN_PATHMUSTEXIST,
    OPENFILENAMEW,
};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_CONTROL,
};
use windows_sys::Win32::UI::Shell::ShellExecuteW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    MessageBoxW, IDYES, MB_ICONERROR, MB_ICONINFORMATION, MB_ICONQUESTION, MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST, MB_YESNO,
    SW_SHOWNORMAL,
};

use crate::paths::log;
use crate::{shell, state, webview, TITLE};

/// Высота полосы меню, логические пиксели.
pub const BAR: f64 = 32.0;
const ZOOM: [f64; 9] = [0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75];

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}

fn hwnd(app: &AppHandle) -> HWND {
    app.get_window("main")
        .and_then(|w| w.hwnd().ok())
        .map(|h| h.0 as HWND)
        .unwrap_or(std::ptr::null_mut())
}

/// Значок у часов: клик — окно; правая кнопка — «Deschide» / «Ieșire».
pub fn tray(app: &App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "tray:open", "Deschide DentPilot", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "tray:quit", "Ieșire din DentPilot", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &sep, &quit])?;
    let mut b = TrayIconBuilder::with_id("dentpilot")
        .tooltip("DentPilot")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        b = b.icon(icon.clone());
    }
    b.build(app)?;
    Ok(())
}

pub fn show_main(app: &AppHandle) {
    // второй запуск может постучаться, пока первый ещё до `manage` (setup):
    // `shell()` тогда паниковала бы — показывать ещё нечего
    if app.try_state::<crate::Shell>().is_none() {
        return;
    }
    if let Some(w) = app.get_window("main") {
        if std::mem::take(&mut shell(app).boot.lock().unwrap().maximize) {
            let _ = w.maximize();
        }
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
    if let Some(p) = app.get_webview("app") {
        let _ = p.set_focus();
    }
    let warns = std::mem::take(&mut shell(app).boot.lock().unwrap().warns);
    for w in warns {
        warn(&w);
    }
}

/// Слово движка `warn`: человеку надо знать, запуск идёт дальше (в окне
/// pywebview это было окно Windows — им и осталось, без хозяина: не держит окно).
pub fn warn(text: &str) {
    if text.trim().is_empty() {
        return;
    }
    let text = text.to_string();
    std::thread::spawn(move || message(&text, MB_ICONWARNING));
}

/// Крестик окна. Есть свой живой движок — окно к часам, программа работает
/// дальше (телефоны, копии, уведомления). Движка нет (беда на заставке,
/// чужой экземпляр — `busy`) — работать у часов нечему: выход.
pub fn close_requested(app: &AppHandle) {
    let keep = {
        let st = shell(app);
        let b = st.boot.lock().unwrap();
        b.alive && !b.busy && b.fail.is_none()
    };
    if keep {
        hide_to_tray(app);
    } else {
        app.exit(0);
    }
}

pub fn hide_to_tray(app: &AppHandle) {
    let st = shell(app);
    if let Some(w) = app.get_window("main") {
        state::track(&w);
        if w.is_fullscreen().unwrap_or(false) {
            let _ = w.set_fullscreen(false);
        }
        let _ = w.hide();
    }
    log("window hidden to the tray");
    // ⛔ Общий ПК: вход снимается и при прятании, а не только при выходе —
    // иначе следующий человек откроет программу кликом по значку от чужого имени.
    let (clear, url) = {
        let b = st.boot.lock().unwrap();
        (b.ready.as_ref().is_some_and(|r| r.session == "clear"), b.url.clone())
    };
    if clear {
        if let Some(p) = app.get_webview("app") {
            webview::clear_cookies(&p);
        }
        if let Some(url) = url.and_then(|u| u.parse().ok()) {
            crate::later(app, 200, move |app| {
                if let Some(p) = app.get_webview("app") {
                    let _ = p.navigate(url);
                }
            });
        }
    }
    let first = !st.store.get().tray_hint;
    if first {
        st.store.edit(|d| d.tray_hint = true);
        crate::notices::tray_hint(app);
    }
    st.store.save();
}

static ASKING: AtomicBool = AtomicBool::new(false);

/// Выход совсем — только с вопросом; движок гасится при выходе (main.rs).
pub fn quit_confirm(app: &AppHandle) {
    if ASKING.swap(true, Ordering::SeqCst) {
        return;
    }
    let lan = shell(app).boot.lock().unwrap().ready.as_ref().is_some_and(|r| r.lan);
    let owner = if app.get_window("main").and_then(|w| w.is_visible().ok()).unwrap_or(false) {
        hwnd(app) as usize
    } else {
        0
    };
    let app = app.clone();
    std::thread::spawn(move || {
        let mut text = String::from("Închideți DentPilot complet?\n\nProgramul se oprește până la următoarea pornire");
        text.push_str(if lan {
            "; telefoanele și al doilea calculator nu vor mai deschide registrul."
        } else {
            "."
        });
        let r = message_owned(owner as HWND, &text, MB_YESNO | MB_ICONQUESTION);
        ASKING.store(false, Ordering::SeqCst);
        if r == IDYES {
            app.exit(0);
        }
    });
}

/// Команда страницы `dpShell.send(path)`.
pub fn send(app: &AppHandle, path: &str) {
    if path == "ctx" {
        if let Some(p) = app.get_webview("app") {
            crate::menus::read_ctx(app, &p);
        }
    } else if let Some(cmd) = path.strip_prefix("win/") {
        window_command(app, cmd);
    } else if let Some(k) = path.strip_prefix("key/") {
        key(app, k);
    }
}

/// Пункт `win:*` (контракт § 3) — его исполняет оболочка.
pub fn window_command(app: &AppHandle, cmd: &str) {
    match cmd {
        "zoomin" | "zoomout" | "zoom0" => zoom(app, cmd),
        "fullscreen" => {
            if let Some(w) = app.get_window("main") {
                let on = w.is_fullscreen().unwrap_or(false);
                let _ = w.set_fullscreen(!on);
            }
        }
        "quit" => quit_confirm(app),
        "datafolder" => {
            let data = shell(app).boot.lock().unwrap().ready.as_ref().map(|r| r.data.clone());
            if let Some(d) = data.filter(|d| !d.is_empty()) {
                let _ = std::process::Command::new("explorer.exe").arg(d).spawn();
            }
        }
        "mail" => open_external("mailto:contact@dentpilot.md?subject=DentPilot"),
        _ => log(&format!("unknown window command: {cmd}")),
    }
}

/// Пункт `key:*`: родное нажатие Ctrl+… в поле, где стоит курсор (страница
/// сама буфер обмена прочитать не может, а нажатие клавиш — может всё).
pub fn key(app: &AppHandle, k: &str) {
    let mut ch = k.chars();
    let (Some(c), None) = (ch.next(), ch.next()) else { return };
    if !"zyxcva".contains(c) {
        return;
    }
    if let Some(p) = app.get_webview("app") {
        let _ = p.set_focus();
    }
    let vk = c.to_ascii_uppercase() as u16;
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(80)); // меню закрылось, фокус вернулся
        let key = |vk: u16, up: bool| INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT { wVk: vk, wScan: 0, dwFlags: if up { KEYEVENTF_KEYUP } else { 0 }, time: 0, dwExtraInfo: 0 },
            },
        };
        let seq = [key(VK_CONTROL, false), key(vk, false), key(vk, true), key(VK_CONTROL, true)];
        unsafe { SendInput(seq.len() as u32, seq.as_ptr(), std::mem::size_of::<INPUT>() as i32) };
    });
}

fn zoom(app: &AppHandle, cmd: &str) {
    let st = shell(app);
    let z = {
        let mut z = st.zoom.lock().unwrap();
        let pos = ZOOM
            .iter()
            .position(|v| (*v - *z).abs() < 0.01)
            .unwrap_or_else(|| ZOOM.iter().position(|v| *v >= *z).unwrap_or(4));
        *z = match cmd {
            "zoomin" => ZOOM[(pos + 1).min(ZOOM.len() - 1)],
            "zoomout" => ZOOM[pos.saturating_sub(1)],
            _ => 1.0,
        };
        *z
    };
    if let Some(p) = app.get_webview("app") {
        let _ = p.set_zoom(z);
    }
    st.store.edit(|d| d.zoom = Some(z));
    state::Store::save_soon(app);
}

/// Заголовок окна; у нестандартного порта — с портом, как у прежнего окна
/// (две программы на одной машине — клиника и стенд — не путаются).
pub fn title(app: &AppHandle, port: u16) {
    if let Some(w) = app.get_window("main") {
        let t = if port == 8088 { TITLE.to_string() } else { format!("{TITLE} · :{port}") };
        let _ = w.set_title(&t);
    }
}

/// Цвет клиники — полосе меню и заставке (синяя клиника получит синюю полосу).
pub fn paint(app: &AppHandle, color: &str) {
    if !crate::valid_color(color) {
        return;
    }
    if let Some(bar) = app.get_webview("bar") {
        let _ = bar.eval(format!("dpColor('{color}')"));
    }
    let st = shell(app);
    let changed = st.store.get().color.as_deref() != Some(color);
    if changed {
        st.store.edit(|d| d.color = Some(color.to_string()));
        state::Store::save_soon(app);
    }
    st.boot.lock().unwrap().color = Some(color.to_string());
}

/// Внешний адрес — программе Windows по умолчанию (браузер, почта).
pub fn open_external(url: &str) {
    let ok = ["http://", "https://", "mailto:", "tel:"].iter().any(|p| url.starts_with(p));
    if !ok {
        log(&format!("external address refused: {url}"));
        return;
    }
    log(&format!("open outside: {url}"));
    let (verb, target) = (wide("open"), wide(url));
    unsafe {
        ShellExecuteW(std::ptr::null_mut(), verb.as_ptr(), target.as_ptr(), std::ptr::null(), std::ptr::null(), SW_SHOWNORMAL);
    }
}

/// Скачивание: родное окно «Сохранить как». `dest` — куда положил бы сам
/// WebView2 (папка «Загрузки» + имя от сервера); выбор человека пишется туда же.
/// ⚠️ Модально внутри события WebView2 — так же, как это годами делает
/// pywebview нынешней программы (`ALLOW_DOWNLOADS`).
pub fn save_as(app: &AppHandle, dest: &mut PathBuf) -> bool {
    let name = dest.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let dir = dest.parent().map(|d| d.display().to_string()).unwrap_or_default();
    let ext = dest.extension().map(|e| e.to_string_lossy().into_owned()).unwrap_or_default();
    let mut file = vec![0u16; 1024];
    for (i, c) in name.encode_utf16().take(1000).enumerate() {
        file[i] = c;
    }
    let filter: Vec<u16> = "Toate fișierele (*.*)\0*.*\0\0".encode_utf16().collect();
    let (wdir, wext, wtitle) = (wide(&dir), wide(&ext), wide("Salvează fișierul"));
    let mut ofn: OPENFILENAMEW = unsafe { std::mem::zeroed() };
    ofn.lStructSize = std::mem::size_of::<OPENFILENAMEW>() as u32;
    ofn.hwndOwner = hwnd(app);
    ofn.lpstrFilter = filter.as_ptr();
    ofn.lpstrFile = file.as_mut_ptr();
    ofn.nMaxFile = file.len() as u32;
    ofn.lpstrInitialDir = if dir.is_empty() { std::ptr::null() } else { wdir.as_ptr() };
    ofn.lpstrDefExt = if ext.is_empty() { std::ptr::null() } else { wext.as_ptr() };
    ofn.lpstrTitle = wtitle.as_ptr();
    ofn.Flags = OFN_EXPLORER | OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    if unsafe { GetSaveFileNameW(&mut ofn) } == 0 {
        return false;
    }
    let len = file.iter().position(|c| *c == 0).unwrap_or(file.len());
    *dest = PathBuf::from(String::from_utf16_lossy(&file[..len]));
    true
}

/// Полоса меню сверху, программа под ней — по размеру окна.
pub fn layout(app: &AppHandle) {
    let Some(w) = app.get_window("main") else { return };
    let (Ok(sz), Ok(sf)) = (w.inner_size(), w.scale_factor()) else { return };
    let l = sz.to_logical::<f64>(sf);
    if let Some(b) = app.get_webview("bar") {
        let _ = b.set_position(LogicalPosition::new(0.0, 0.0));
        let _ = b.set_size(LogicalSize::new(l.width, BAR));
    }
    if let Some(p) = app.get_webview("app") {
        let _ = p.set_position(LogicalPosition::new(0.0, BAR));
        let _ = p.set_size(LogicalSize::new(l.width, (l.height - BAR).max(0.0)));
    }
}

pub fn message(text: &str, style: u32) -> i32 {
    message_owned(std::ptr::null_mut(), text, style)
}

fn message_owned(owner: HWND, text: &str, style: u32) -> i32 {
    let (t, c) = (wide(text), wide("DentPilot"));
    unsafe { MessageBoxW(owner, t.as_ptr(), c.as_ptr(), style | MB_TOPMOST | MB_SETFOREGROUND) }
}

pub const INFO: u32 = MB_ICONINFORMATION;
pub const ERROR: u32 = MB_ICONERROR;
