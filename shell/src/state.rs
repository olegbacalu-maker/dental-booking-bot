// Своё состояние оболочки — `shell.json` по учётке Windows (контракт § 1):
// место и размер окна, масштаб, цвет клиники для заставки до первого слова
// движка, «подсказка про часы уже была», показанные уведомления.
//
// ⚠️ Сервер не помнит, что показано (контракт § 4) — помнит этот файл; потеря
// файла = каждое действующее уведомление покажется ещё раз, не больше.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, Window};

use crate::paths::log;

/// Сколько id показанных уведомлений держать (старые события не вернутся:
/// id меняется вместе с событием — `update:<версия>` и т. п.).
const NOTICES_KEPT: usize = 200;

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct Saved {
    #[serde(default)]
    pub window: Option<Place>,
    #[serde(default)]
    pub zoom: Option<f64>,
    #[serde(default)]
    pub color: Option<String>,
    #[serde(default)]
    pub tray_hint: bool,
    #[serde(default)]
    pub notices: Vec<String>,
}

/// Окно в «обычном» виде (не развёрнутое) — как его хранит сама Windows
/// (`WINDOWPLACEMENT.rcNormalPosition`): внешняя рамка, физические пиксели,
/// координаты рабочего стола (от рабочей области главного монитора).
#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq)]
pub struct Place {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    #[serde(default)]
    pub max: bool,
}

pub struct Store {
    path: PathBuf,
    pub data: Mutex<Saved>,
    pending: AtomicBool,
}

impl Store {
    pub fn load(dir: &Path) -> Store {
        let path = dir.join("shell.json");
        let data = fs::read(&path)
            .ok()
            .and_then(|b| serde_json::from_slice::<Saved>(&b).ok())
            .unwrap_or_default();
        Store { path, data: Mutex::new(data), pending: AtomicBool::new(false) }
    }

    pub fn get(&self) -> Saved {
        self.data.lock().map(|d| d.clone()).unwrap_or_default()
    }

    pub fn edit(&self, f: impl FnOnce(&mut Saved)) {
        if let Ok(mut d) = self.data.lock() {
            f(&mut d);
        }
    }

    /// Записать сейчас (выход, прятание к часам). Через временный файл:
    /// оборванная запись не оставит полфайла.
    pub fn save(&self) {
        let Ok(bytes) = self.data.lock().map(|d| serde_json::to_vec_pretty(&*d)) else { return };
        let Ok(bytes) = bytes else { return };
        if let Some(dir) = self.path.parent() {
            let _ = fs::create_dir_all(dir);
        }
        let tmp = self.path.with_extension("json.tmp");
        if fs::write(&tmp, bytes).is_ok() {
            if let Err(e) = fs::rename(&tmp, &self.path) {
                log(&format!("shell.json not written: {e}"));
            }
        }
    }

    /// Записать чуть позже (окно двигают — сотня событий в секунду).
    pub fn save_soon(app: &AppHandle) {
        let Some(st) = app.try_state::<crate::Shell>() else { return };
        if st.store.pending.swap(true, Ordering::SeqCst) {
            return;
        }
        let app = app.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(2));
            if let Some(st) = app.try_state::<crate::Shell>() {
                st.store.pending.store(false, Ordering::SeqCst);
                st.store.save();
            }
        });
    }

    pub fn notice_seen(&self, id: &str) -> bool {
        self.data.lock().map(|d| d.notices.iter().any(|n| n == id)).unwrap_or(false)
    }

    pub fn mark_notice(&self, id: &str) {
        self.edit(|d| {
            d.notices.push(id.to_string());
            let extra = d.notices.len().saturating_sub(NOTICES_KEPT);
            d.notices.drain(..extra);
        });
    }
}

// ---- память окна --------------------------------------------------------------
// ⭐ Через WINDOWPLACEMENT, а не по событиям «сдвинули/растянули»: Windows
// сама держит «обычное» место отдельно от развёрнутого. Найдено опытом 18.10:
// по событиям первое «растянули» при разворачивании приходит, пока окно ещё
// не считается развёрнутым, и обычным местом записывался весь экран — после
// «Восстановить» окно так и оставалось во весь экран.

use windows_sys::Win32::Foundation::{HWND, RECT};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetWindowPlacement, SetWindowPlacement, SystemParametersInfoW, SPI_GETWORKAREA,
    SW_HIDE, SW_SHOWMAXIMIZED, SW_SHOWMINIMIZED, WINDOWPLACEMENT, WPF_RESTORETOMAXIMIZED,
};

fn hwnd(window: &Window) -> Option<HWND> {
    window.hwnd().ok().map(|h| h.0 as HWND)
}

fn placement(h: HWND) -> Option<WINDOWPLACEMENT> {
    let mut wp: WINDOWPLACEMENT = unsafe { std::mem::zeroed() };
    wp.length = std::mem::size_of::<WINDOWPLACEMENT>() as u32;
    (unsafe { GetWindowPlacement(h, &mut wp) } != 0).then_some(wp)
}

/// Начало рабочей области главного монитора: координаты WINDOWPLACEMENT
/// отсчитываются от неё (панель задач слева или сверху их сдвигает).
fn workspace_origin() -> (i32, i32) {
    let mut r = RECT { left: 0, top: 0, right: 0, bottom: 0 };
    unsafe { SystemParametersInfoW(SPI_GETWORKAREA, 0, &mut r as *mut _ as *mut _, 0) };
    (r.left, r.top)
}

/// Запомнить, где окно (зовётся на каждом «сдвинули/растянули»).
/// Во весь экран (F11) — не место: пропускаем.
pub fn track(window: &Window) {
    let app = window.app_handle();
    let Some(st) = app.try_state::<crate::Shell>() else { return };
    if !window.is_visible().unwrap_or(false) || window.is_fullscreen().unwrap_or(false) {
        return;
    }
    let Some(wp) = hwnd(window).and_then(placement) else { return };
    let cmd = wp.showCmd as i32;
    let max = cmd == SW_SHOWMAXIMIZED
        || (cmd == SW_SHOWMINIMIZED && wp.flags & WPF_RESTORETOMAXIMIZED != 0);
    let r = wp.rcNormalPosition;
    let place = Place { x: r.left, y: r.top, w: r.right - r.left, h: r.bottom - r.top, max };
    if st.store.get().window != Some(place) {
        st.store.edit(|d| d.window = Some(place));
        Store::save_soon(app);
    }
}

/// Поставить окно туда, где его оставили, — если оно там целиком на каком-то
/// экране (монитор отключили, сменили разрешение — иначе посередине, как
/// новое). Окно ещё спрятано: место ставится без показа. Возвращает «показать
/// развёрнутым».
pub fn restore(window: &Window, place: Option<Place>) -> bool {
    let Some(p) = place else {
        let _ = window.center();
        return false;
    };
    let fits = fits(window, &p);
    match hwnd(window).and_then(|h| placement(h).map(|wp| (h, wp))) {
        Some((h, mut wp)) if fits && p.w > 0 && p.h > 0 => {
            wp.flags = 0;
            wp.showCmd = SW_HIDE as u32;
            wp.rcNormalPosition = RECT { left: p.x, top: p.y, right: p.x + p.w, bottom: p.y + p.h };
            unsafe { SetWindowPlacement(h, &wp) };
        }
        _ => {
            log(&format!("window does not fit any screen ({p:?}) - centred"));
            let _ = window.center();
        }
    }
    p.max
}

fn fits(window: &Window, p: &Place) -> bool {
    let Ok(monitors) = window.available_monitors() else { return false };
    let (ox, oy) = workspace_origin();
    let (x, y) = ((p.x + ox) as i64, (p.y + oy) as i64);
    let (w, h) = (p.w as i64, p.h as i64);
    monitors.iter().any(|m| {
        let wa = m.work_area();
        // невидимая рамка Windows 10/11 выходит за край окна на ~7 px при 100 %:
        // окно, прижатое к краю, не должно считаться «вылезшим»
        let tol = (16.0 * m.scale_factor()).round() as i64;
        let (ax, ay) = (wa.position.x as i64, wa.position.y as i64);
        let (aw, ah) = (wa.size.width as i64, wa.size.height as i64);
        x >= ax - tol && y >= ay - tol && x + w <= ax + aw + tol && y + h <= ay + ah + tol
    })
}
