// Свои обработчики WebView2 поверх Tauri (то, чего у Tauri 2.12 нет в API).
//
// ⭐ Канал `dpShell.send` — `chrome.webview.postMessage`. Почему не переход на
// служебный адрес (как в песочнице): переход будит `beforeunload` страницы —
// экран с несохранённой формой спросил бы «покинуть страницу?» на каждое
// «Mărește». Сообщение страницу не трогает вовсе.
// ⚠️ Форма сообщения — СТРОКА вида запроса IPC Tauri с чужим ключом
// (`__TAURI_INVOKE_KEY__: "dpShell"`). Проверено опытом 18.10: обработчик
// Tauri стоит в цепочке WebView2 первым; объект он не читает, падает — и
// WebView2 дальше по цепочке (до нас) сообщение НЕ несёт. Строку, не
// похожую на запрос, Tauri разбирает с ошибкой и пишет её в консоль
// страницы; запрос с чужим ключом отбрасывает молча (`Webview::on_message`).
// Нужно только строке быть таким запросом — права IPC это не даёт никакие.
// ⛔ Чьё сообщение — проверяется по адресу ДОКУМЕНТА, приславшего его
// (`Source`), а не по содержимому: программа — только с адреса движка,
// полоса меню — только со своей страницы оболочки.

use serde_json::Value;
use tauri::webview::Webview;
use tauri::{AppHandle, Manager, Wry};
use webview2_com::Microsoft::Web::WebView2::Win32::{
    ICoreWebView2, ICoreWebView2ContextMenuRequestedEventArgs, ICoreWebView2Settings3,
    ICoreWebView2_11, ICoreWebView2_2, COREWEBVIEW2_PERMISSION_KIND,
    COREWEBVIEW2_PERMISSION_KIND_MULTIPLE_AUTOMATIC_DOWNLOADS, COREWEBVIEW2_PERMISSION_STATE_ALLOW,
};
use webview2_com::{
    ContextMenuRequestedEventHandler, PermissionRequestedEventHandler, WebMessageReceivedEventHandler,
};
use windows::core::{Interface, PWSTR};
use windows::Win32::System::Com::CoTaskMemFree;

use crate::paths::log;

/// Кто прислал сообщение.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Who {
    Bar,
    Page,
}

fn take(p: PWSTR) -> String {
    if p.is_null() {
        return String::new();
    }
    let s = unsafe { p.to_string() }.unwrap_or_default();
    unsafe { CoTaskMemFree(Some(p.0 as *const _)) };
    s
}

fn core(pw: &tauri::webview::PlatformWebview) -> Option<ICoreWebView2> {
    unsafe { pw.controller().CoreWebView2().ok() }
}

/// Подключить свои обработчики к WebView (зовётся сразу после создания).
pub fn attach(wv: &Webview<Wry>, who: Who) {
    let app = wv.app_handle().clone();
    let app2 = app.clone();
    let _ = wv.with_webview(move |pw| {
        let Some(core) = core(&pw) else {
            log("WebView2: no ICoreWebView2");
            return;
        };
        unsafe {
            if let Ok(s) = core.Settings() {
                // ⭐ Клавиши браузера (F5, Ctrl+P, Ctrl+F, Ctrl+N, Ctrl+плюс…) — у
                // страницы: она ловит их по ОДНОМУ списку команд (контракт § 3) и
                // уводит `win:*` сюда. Включённые здесь, они срабатывали бы
                // вдобавок: Ctrl+F открыл бы поиск Edge поверх «Caută pacient».
                // Правка в поле (Ctrl+C/V/X/A/Z/Y) от этого не зависит.
                if let Ok(s3) = s.cast::<ICoreWebView2Settings3>() {
                    let _ = s3.SetAreBrowserAcceleratorKeysEnabled(false);
                }
                let _ = s.SetIsStatusBarEnabled(false);
            }
            let handler = WebMessageReceivedEventHandler::create(Box::new(move |_, args| {
                let Some(args) = args else { return Ok(()) };
                let mut src = PWSTR::null();
                args.Source(&mut src)?;
                let src = take(src);
                let mut text = PWSTR::null();
                if args.TryGetWebMessageAsString(&mut text).is_err() {
                    return Ok(()); // не строка — не наше
                }
                let json = take(text);
                let app = app.clone();
                // не внутри события WebView2: меню и eval — уже после него
                let _ = app.clone().run_on_main_thread(move || on_message(&app, who, &src, &json));
                Ok(())
            }));
            let mut token = 0i64;
            match core.add_WebMessageReceived(&handler, &mut token) {
                Ok(()) => log(&format!("WebView2 {who:?}: message channel attached")),
                Err(e) => log(&format!("WebView2 {who:?}: message channel NOT attached: {e}")),
            }
            if who == Who::Page {
                context_menu(&core);
                permissions(&core, app2);
            }
        }
    });
}

/// Ключ, по которому Tauri отбрасывает наши сообщения, а мы их узнаём.
pub const KEY: &str = "dpShell";

fn on_message(app: &AppHandle, who: Who, src: &str, json: &str) {
    let Ok(m) = serde_json::from_str::<Value>(json) else { return };
    if m["__TAURI_INVOKE_KEY__"].as_str() != Some(KEY) || m["cmd"].as_str() != Some(KEY) {
        return;
    }
    let v = &m["payload"];
    match who {
        Who::Bar => {
            if !src.starts_with(crate::SHELL_PAGES) {
                return;
            }
            let Some(id) = v["menu"].as_str() else { return };
            let (x, y) = (v["x"].as_f64().unwrap_or(0.0), v["y"].as_f64().unwrap_or(0.0));
            crate::menus::open(app, id, x, y);
        }
        Who::Page => {
            if !crate::is_engine_url(app, src) {
                log(&format!("dpShell message from a foreign address ignored: {src}"));
                return;
            }
            let Some(path) = v["path"].as_str() else { return };
            crate::win::send(app, path);
        }
    }
}

/// Правая кнопка (разбор 18.10: «в поле нельзя Вставить мышью»): родное меню
/// WebView2 — только про ПРАВКУ. В поле — отменить/вырезать/копировать/
/// вставить/выделить всё; на выделенном тексте — копировать; на остальной
/// странице меню нет вовсе: «Назад», «Сохранить как», «Печать» страницы и
/// «Найти в интернете» окну программы ни к чему.
/// ⚠️ Подписи — на языке Windows (их рисует Edge), как кнопки окон Windows.
unsafe fn context_menu(core: &ICoreWebView2) {
    let Ok(c11) = core.cast::<ICoreWebView2_11>() else { return };
    let handler = ContextMenuRequestedEventHandler::create(Box::new(|_, args| {
        let Some(args) = args else { return Ok(()) };
        filter_menu(&args);
        Ok(())
    }));
    let mut token = 0i64;
    let _ = c11.add_ContextMenuRequested(&handler, &mut token);
}

/// Второе и следующие скачивания одной страницы Edge держит вопросом «сайт
/// хочет загрузить несколько файлов» (найдено опытом 18.10: копия базы,
/// «Exportă», документ подряд). С адреса движка — разрешено: каждое
/// скачивание и так идёт через окно «Сохранить как», молча файлов не будет.
unsafe fn permissions(core: &ICoreWebView2, app: AppHandle) {
    let handler = PermissionRequestedEventHandler::create(Box::new(move |_, args| {
        let Some(args) = args else { return Ok(()) };
        let mut kind = COREWEBVIEW2_PERMISSION_KIND::default();
        args.PermissionKind(&mut kind)?;
        if kind == COREWEBVIEW2_PERMISSION_KIND_MULTIPLE_AUTOMATIC_DOWNLOADS {
            let mut uri = PWSTR::null();
            args.Uri(&mut uri)?;
            if crate::is_engine_url(&app, &take(uri)) {
                args.SetState(COREWEBVIEW2_PERMISSION_STATE_ALLOW)?;
            }
        }
        Ok(())
    }));
    let mut token = 0i64;
    let _ = core.add_PermissionRequested(&handler, &mut token);
}

// ⛔ без «Эмодзи»: знаки вне Inter уходят в системный шрифт (CLAUDE.md)
const EDIT_ITEMS: [&str; 7] = ["undo", "redo", "cut", "copy", "paste", "pasteAndMatchStyle", "selectAll"];

unsafe fn filter_menu(args: &ICoreWebView2ContextMenuRequestedEventArgs) {
    let Ok(target) = args.ContextMenuTarget() else { return };
    let mut editable = windows_core::BOOL(0);
    let _ = target.IsEditable(&mut editable);
    let mut selection = windows_core::BOOL(0);
    let _ = target.HasSelection(&mut selection);
    let keep: &[&str] = if editable.as_bool() {
        &EDIT_ITEMS
    } else if selection.as_bool() {
        &["copy"]
    } else {
        &[]
    };
    let Ok(items) = args.MenuItems() else { return };
    let mut n = 0u32;
    let _ = items.Count(&mut n);
    let mut left = 0u32;
    for i in (0..n).rev() {
        let Ok(item) = items.GetValueAtIndex(i) else { continue };
        let mut name = PWSTR::null();
        let _ = item.Name(&mut name);
        let name = take(name);
        if keep.contains(&name.as_str()) {
            left += 1;
        } else {
            let _ = items.RemoveValueAtIndex(i);
        }
    }
    // разделители сами по себе тоже «пункты»: пусто без них — меню не нужно
    if left == 0 {
        let _ = args.SetHandled(true);
    } else {
        tidy_separators(args);
    }
}

/// Разделители в начале, в конце и подряд после чистки — убрать.
unsafe fn tidy_separators(args: &ICoreWebView2ContextMenuRequestedEventArgs) {
    use webview2_com::Microsoft::Web::WebView2::Win32::COREWEBVIEW2_CONTEXT_MENU_ITEM_KIND_SEPARATOR;
    let Ok(items) = args.MenuItems() else { return };
    let mut n = 0u32;
    let _ = items.Count(&mut n);
    let mut prev_sep = true; // в начале разделитель не нужен
    let mut i = 0u32;
    while i < n {
        let Ok(item) = items.GetValueAtIndex(i) else { break };
        let mut kind = Default::default();
        let _ = item.Kind(&mut kind);
        let sep = kind == COREWEBVIEW2_CONTEXT_MENU_ITEM_KIND_SEPARATOR;
        if sep && prev_sep {
            let _ = items.RemoveValueAtIndex(i);
            n -= 1;
            continue;
        }
        prev_sep = sep;
        i += 1;
    }
    if n > 0 && prev_sep {
        let _ = items.RemoveValueAtIndex(n - 1);
    }
}

/// Снять вход (общий ПК, `session == "clear"`): все куки профиля. Кэш и
/// настройки экранов остаются — постоянный профиль ≠ постоянный вход.
pub fn clear_cookies(wv: &Webview<Wry>) {
    let _ = wv.with_webview(|pw| unsafe {
        if let Some(core) = core(&pw) {
            if let Ok(c2) = core.cast::<ICoreWebView2_2>() {
                if let Ok(cm) = c2.CookieManager() {
                    match cm.DeleteAllCookies() {
                        Ok(()) => log("session: cookies deleted"),
                        Err(e) => log(&format!("session: cookies NOT deleted: {e}")),
                    }
                }
            }
        }
    });
}
