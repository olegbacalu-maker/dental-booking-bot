// Меню окна Fișier · Editare · Vizualizare · Mergi la · Ajutor (контракт § 3).
//
// Заголовки — статичная полоса (`ui/menubar.html`), списки под ними — родные
// меню Windows. ⭐ Что в списке, решает ПРОГРАММА: при каждом открытии
// оболочка спрашивает страницу `dpMenu(id)` (права вошедшего, «Mergi la» из
// `nav.items`, «Tipărește» серый на экране без печати) — у оболочки своих
// подписей нет, кроме заголовков, меню значка и запасного списка ниже.
// Исполняет пункт тот, чей префикс: `act:`/`go:` — страница (`dpRun`),
// `win:`/`key:` — оболочка.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::webview::Webview;
use tauri::{AppHandle, LogicalPosition, Manager, Wry};

use crate::paths::log;
use crate::{shell, win};

const TITLES: [&str; 5] = ["file", "edit", "view", "go", "help"];
const MAX_ITEMS: usize = 60;
/// Страница не ответила (занята, зависла) — показать запасное меню, а не ничего.
const ASK_WAIT: Duration = Duration::from_millis(700);

#[derive(Debug, Clone, PartialEq)]
pub enum Item {
    Entry { id: String, label: String, accel: Option<String>, enabled: bool },
    Sep,
}

fn entry(id: &str, label: &str, accel: Option<&str>) -> Item {
    Item::Entry { id: id.into(), label: label.into(), accel: accel.map(Into::into), enabled: true }
}

/// Запасное меню — пока у страницы нет `dpMenu` (экран без слоя команд,
/// заставка, программа ещё не загрузилась): только то, что исполняет сама
/// оболочка — правка, масштаб, весь экран, выход.
pub fn fallback(id: &str) -> Vec<Item> {
    match id {
        "file" => vec![entry("win:quit", "Închide DentPilot…", None)],
        "edit" => vec![
            entry("key:z", "Anulează", Some("Ctrl+Z")),
            entry("key:y", "Refă", Some("Ctrl+Y")),
            Item::Sep,
            entry("key:x", "Decupează", Some("Ctrl+X")),
            entry("key:c", "Copiază", Some("Ctrl+C")),
            entry("key:v", "Lipește", Some("Ctrl+V")),
            entry("key:a", "Selectează tot", Some("Ctrl+A")),
        ],
        "view" => vec![
            entry("win:zoomin", "Mărește", Some("Ctrl+=")),
            entry("win:zoomout", "Micșorează", Some("Ctrl+-")),
            entry("win:zoom0", "Mărime normală", Some("Ctrl+0")),
            Item::Sep,
            entry("win:fullscreen", "Ecran complet", Some("F11")),
        ],
        _ => Vec::new(),
    }
}

fn known_prefix(id: &str) -> bool {
    ["act:", "go:", "win:", "key:"].iter().any(|p| id.starts_with(p) && id.len() > p.len())
}

/// Ответ `dpMenu` → пункты. Чужое и битое отбрасывается поштучно; `None` —
/// ответа нет вовсе (функции нет, исключение, другая версия).
pub fn parse(raw: &str) -> Option<Vec<Item>> {
    // eval_with_callback отдаёт JSON значения; страница отдаёт JSON-строку
    let v: Value = serde_json::from_str(raw).ok()?;
    let v: Value = match v {
        Value::String(s) => serde_json::from_str(&s).ok()?,
        other => other,
    };
    if v["v"].as_i64() != Some(1) {
        return None;
    }
    let mut out = Vec::new();
    for it in v["items"].as_array()?.iter().take(MAX_ITEMS) {
        if it["sep"].as_bool() == Some(true) {
            out.push(Item::Sep);
            continue;
        }
        let (Some(id), Some(label)) = (it["id"].as_str(), it["label"].as_str()) else { continue };
        if !known_prefix(id) || id.len() > 200 || label.trim().is_empty() {
            continue;
        }
        let accel = it["accel"].as_str().filter(|a| !a.is_empty() && a.len() <= 24).map(String::from);
        out.push(Item::Entry {
            id: id.to_string(),
            label: label.chars().take(80).collect(),
            accel,
            enabled: it["enabled"].as_bool().unwrap_or(true),
        });
    }
    Some(tidy(out))
}

/// Без разделителей в начале, в конце и подряд.
fn tidy(v: Vec<Item>) -> Vec<Item> {
    let mut out: Vec<Item> = Vec::new();
    for e in v {
        if e == Item::Sep && matches!(out.last(), None | Some(Item::Sep)) {
            continue;
        }
        out.push(e);
    }
    if out.last() == Some(&Item::Sep) {
        out.pop();
    }
    out
}

/// Подпись для родного меню: `&` у Windows — подчёркнутая буква, клавиша —
/// после табуляции (так её ставит в правый столбец сама Windows).
fn native_text(label: &str, accel: Option<&str>) -> String {
    let l = label.replace('\t', " ").replace('&', "&&");
    match accel {
        Some(a) => format!("{l}\t{}", a.replace('&', "&&")),
        None => l,
    }
}

fn build(app: &AppHandle, items: &[Item]) -> tauri::Result<Menu<Wry>> {
    let menu = Menu::new(app)?;
    for e in items {
        match e {
            // ⚠️ Клавиша — текстом, а не «ускорителем» Tauri: ловит её страница
            // (контракт § 3), а разбор чужой строки ускорителя мог бы упасть.
            Item::Entry { id, label, accel, enabled } => menu.append(&MenuItem::with_id(
                app,
                id.as_str(),
                native_text(label, accel.as_deref()),
                *enabled,
                None::<&str>,
            )?)?,
            Item::Sep => menu.append(&PredefinedMenuItem::separator(app)?)?,
        }
    }
    Ok(menu)
}

fn popup(app: &AppHandle, items: Vec<Item>, x: f64, y: f64) {
    if !items.is_empty() {
        match (app.get_window("main"), build(app, &items)) {
            (Some(w), Ok(menu)) => {
                let _ = w.popup_menu_at(&menu, LogicalPosition::new(x, y));
            }
            (_, Err(e)) => log(&format!("menu not built: {e}")),
            _ => {}
        }
    }
    if let Some(bar) = app.get_webview("bar") {
        let _ = bar.eval("window.dpClear && dpClear()");
    }
}

/// Нажат заголовок полосы: свежий список со страницы — и родное меню под ним.
pub fn open(app: &AppHandle, id: &str, x: f64, y: f64) {
    if !TITLES.contains(&id) {
        return;
    }
    let id = id.to_string();
    let entered = shell(app).boot.lock().unwrap().entered;
    let page = app.get_webview("app").filter(|p| {
        entered && p.url().ok().is_some_and(|u| crate::is_engine_url(app, u.as_str()))
    });
    let Some(page) = page else {
        popup(app, fallback(&id), x, y);
        return;
    };
    let answered = Arc::new(AtomicBool::new(false));
    let js = format!(
        "(function(){{try{{return window.dpMenu?JSON.stringify(window.dpMenu({})):null}}catch(e){{return null}}}})()",
        serde_json::to_string(&id).unwrap()
    );
    let (a1, h1, id1) = (answered.clone(), app.clone(), id.clone());
    let asked = page.eval_with_callback(js, move |raw| {
        if a1.swap(true, Ordering::SeqCst) {
            return;
        }
        let items = parse(&raw).unwrap_or_else(|| fallback(&id1));
        let h = h1.clone();
        let _ = h1.run_on_main_thread(move || popup(&h, items, x, y));
    });
    if asked.is_err() {
        answered.store(true, Ordering::SeqCst);
        popup(app, fallback(&id), x, y);
        return;
    }
    let h2 = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(ASK_WAIT);
        if !answered.swap(true, Ordering::SeqCst) {
            log("dpMenu did not answer in time - fallback menu");
            let h = h2.clone();
            let _ = h2.run_on_main_thread(move || popup(&h, fallback(&id), x, y));
        }
    });
}

/// Выбран пункт (меню окна или меню значка у часов).
pub fn on_event(app: &AppHandle, id: &str) {
    if let Some(t) = id.strip_prefix("tray:") {
        match t {
            "open" => win::show_main(app),
            "quit" => win::quit_confirm(app),
            _ => {}
        }
    } else if id.starts_with("act:") || id.starts_with("go:") {
        run_page(app, id);
    } else if let Some(w) = id.strip_prefix("win:") {
        win::window_command(app, w);
    } else if let Some(k) = id.strip_prefix("key:") {
        win::key(app, k);
    }
}

/// `act:*` / `go:*` — странице. Нет `dpRun` (экран без слоя команд) — `go:`
/// всё равно уводит по адресу (уведомление, «Mergi la»), `act:` молчит.
pub fn run_page(app: &AppHandle, id: &str) {
    let Some(p) = app.get_webview("app") else { return };
    let arg = serde_json::to_string(id).unwrap();
    let fallback = match id.strip_prefix("go:") {
        Some(path) if path.starts_with('/') && !path.starts_with("//") => {
            format!("location.assign({})", serde_json::to_string(path).unwrap())
        }
        _ => "0".to_string(),
    };
    let _ = p.eval(format!("window.dpRun ? window.dpRun({arg}) : {fallback}"));
    let _ = p.set_focus();
}

/// Контекст страницы (`dpCtx`): цвет клиники — полосе меню. Без `dpCtx` —
/// фирменная переменная темы `--teal` самой программы.
const CTX_JS: &str = r#"(function(){try{
  if(window.dpCtx)return JSON.stringify(window.dpCtx());
  return JSON.stringify({v:1,color:getComputedStyle(document.documentElement).getPropertyValue('--teal').trim()});
}catch(e){return null}})()"#;

pub fn read_ctx(app: &AppHandle, wv: &Webview<Wry>) {
    let app = app.clone();
    let _ = wv.eval_with_callback(CTX_JS, move |raw| {
        let v: Value = match serde_json::from_str::<Value>(&raw) {
            Ok(Value::String(s)) => serde_json::from_str(&s).unwrap_or(Value::Null),
            _ => return,
        };
        let color = v["color"].as_str().unwrap_or("").to_uppercase();
        if crate::valid_color(&color) {
            let h = app.clone();
            let _ = app.run_on_main_thread(move || win::paint(&h, &color));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_menu_is_filtered() {
        let raw = serde_json::to_string(
            r#"{"v":1,"items":[{"sep":true},{"id":"act:newAppt","label":"Programare nouă…","accel":"Ctrl+N","enabled":true},
            {"sep":true},{"sep":true},{"id":"evil","label":"x"},{"id":"go:/admin/all","label":"Ziua","enabled":false},{"sep":true}]}"#,
        )
        .unwrap();
        let items = parse(&raw).unwrap();
        assert_eq!(items.len(), 3);
        assert!(matches!(&items[0], Item::Entry { id, accel: Some(a), .. } if id == "act:newAppt" && a == "Ctrl+N"));
        assert_eq!(items[1], Item::Sep);
        assert!(matches!(&items[2], Item::Entry { enabled: false, .. }));
        assert!(parse("null").is_none());
        assert!(parse(&serde_json::to_string(r#"{"v":2,"items":[]}"#).unwrap()).is_none());
    }

    #[test]
    fn native_text_escapes_mnemonics() {
        assert_eq!(native_text("Copii & arhive", Some("Ctrl+S")), "Copii && arhive\tCtrl+S");
    }

    #[test]
    fn fallback_is_shell_only() {
        for t in TITLES {
            for e in fallback(t) {
                if let Item::Entry { id, .. } = e {
                    assert!(id.starts_with("win:") || id.starts_with("key:"), "{id}");
                }
            }
        }
    }
}
