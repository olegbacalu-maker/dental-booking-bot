// Уведомления Windows (контракт § 4; Олег 18.10: вышло обновление, лицензия
// кончается, SMS осталось мало — про пациентов ничего).
//
// ЧТО сказать — решает движок (`GET /shell/notices` с токеном оболочки);
// оболочка спрашивает после `ready` и раз в 30 минут, показывает новое и
// помнит показанное в shell.json (сервер не помнит). Клик — окно на экран и
// экран программы (`go:<open>`).
//
// ⚠️ Windows показывает уведомление только программе, которую знает по
// паспорту (AppUserModelID `md.dentpilot.app`) — по ЯРЛЫКУ в «Пуске» с этим
// паспортом; его ставит установщик (Т9). Проверено опытом 18.10: с ярлыком —
// баннер у часов (подпись — имя ярлыка, значок — его); без ярлыка Windows
// отвечает на вопрос `Setting` ошибкой 0x80070490, а показанное молча уходит
// в историю без баннера — даже с записью паспорта в
// `HKCU\Software\Classes\AppUserModelId` (её поэтому и нет). Значит, в
// разработке и с флешки уведомлений нет: подсказка «я у часов» — окном.

use std::sync::atomic::Ordering;
use std::sync::Mutex;
use std::time::Duration;

use serde_json::Value;
use tauri::AppHandle;
use windows::core::HSTRING;
use windows::Data::Xml::Dom::XmlDocument;
use windows::Foundation::TypedEventHandler;
use windows::UI::Notifications::{NotificationSetting, ToastNotification, ToastNotificationManager};

use crate::paths::log;
use crate::{menus, shell, win, AUMID};

const EVERY: Duration = Duration::from_secs(30 * 60);

/// Живые уведомления: без ссылки на объект Windows не донесёт клик до нас.
static ALIVE: Mutex<Vec<ToastNotification>> = Mutex::new(Vec::new());

/// Паспорт процесса — тот же, что у ярлыка: панель задач собирает окно под
/// ярлык, Windows узнаёт отправителя уведомлений.
pub fn set_process_aumid() {
    use windows_sys::Win32::UI::Shell::SetCurrentProcessExplicitAppUserModelID;
    let id: Vec<u16> = AUMID.encode_utf16().chain(Some(0)).collect();
    unsafe { SetCurrentProcessExplicitAppUserModelID(id.as_ptr()) };
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

/// Чем кончился показ уведомления.
#[derive(Debug, PartialEq)]
enum Shown {
    Yes,
    /// уведомления DentPilot выключены человеком (или политикой) — его выбор
    Off,
    /// Windows программу не знает (нет ярлыка с паспортом: разработка,
    /// флешка) — показанное ушло бы в историю без баннера
    NoPassport,
    /// сбой Windows — попробовать снова при следующем опросе
    Failed,
}

/// Показать уведомление (главный поток: WinRT нужен готовый апартамент).
/// Клик — окно на экран и экран `open` программы.
fn toast(app: &AppHandle, title: &str, body: &str, open: Option<String>) -> Shown {
    let xml = format!(
        "<toast><visual><binding template=\"ToastGeneric\"><text>{}</text><text>{}</text></binding></visual></toast>",
        xml_escape(title),
        xml_escape(body)
    );
    let run = || -> windows::core::Result<Shown> {
        let notifier = ToastNotificationManager::CreateToastNotifierWithId(&HSTRING::from(AUMID))?;
        match notifier.Setting() {
            Ok(NotificationSetting::Enabled) => {}
            Ok(other) => {
                log(&format!("notifications are off for {AUMID}: {other:?}"));
                return Ok(Shown::Off);
            }
            Err(e) => {
                log(&format!("Windows does not know {AUMID} (no Start menu shortcut): {e}"));
                return Ok(Shown::NoPassport);
            }
        }
        let doc = XmlDocument::new()?;
        doc.LoadXml(&HSTRING::from(xml.as_str()))?;
        let t = ToastNotification::CreateToastNotification(&doc)?;
        let app = app.clone();
        t.Activated(&TypedEventHandler::new(move |_, _| {
            let open = open.clone();
            let h = app.clone();
            let _ = app.run_on_main_thread(move || {
                win::show_main(&h);
                if let Some(path) = open {
                    menus::run_page(&h, &format!("go:{path}"));
                }
            });
            Ok(())
        }))?;
        notifier.Show(&t)?;
        if let Ok(mut alive) = ALIVE.lock() {
            alive.push(t);
            let extra = alive.len().saturating_sub(20);
            alive.drain(..extra);
        }
        Ok(Shown::Yes)
    };
    run().unwrap_or_else(|e| {
        log(&format!("notification not shown: {e}"));
        Shown::Failed
    })
}

/// Первое прятание к часам: «я работаю дальше». Уведомления выключены — то
/// же самое окном, один раз: без подсказки люди думают, что закрыли.
pub fn tray_hint(app: &AppHandle) {
    let title = "DentPilot lucrează în continuare";
    let body = "Programul e lângă ceas. Clic pe pictograma DentPilot îl deschide; \
                ieșirea completă — clic dreapta pe pictogramă, «Ieșire din DentPilot».";
    if toast(app, title, body, None) != Shown::Yes {
        let text = format!("{title}.\n\n{body}");
        std::thread::spawn(move || win::message(&text, win::INFO));
    }
}

/// Опрос движка: после `ready` и раз в 30 минут, пока программа работает.
pub fn start(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || loop {
        let st = shell(&app);
        if st.quitting.load(Ordering::SeqCst) {
            return;
        }
        let port = st.boot.lock().unwrap().ready.as_ref().map(|r| r.port);
        let Some(port) = port else { return };
        let token = st.token.clone();
        drop(st);
        if let Some(items) = fetch(port, &token) {
            let h = app.clone();
            let _ = app.run_on_main_thread(move || show_new(&h, items));
        }
        let mut slept = Duration::ZERO;
        while slept < EVERY {
            std::thread::sleep(Duration::from_secs(5));
            slept += Duration::from_secs(5);
            if shell(&app).quitting.load(Ordering::SeqCst) {
                return;
            }
        }
    });
}

#[derive(Debug, Clone, PartialEq)]
pub struct Notice {
    pub id: String,
    pub title: String,
    pub body: String,
    pub open: Option<String>,
}

fn fetch(port: u16, token: &str) -> Option<Vec<Notice>> {
    let (code, body) = crate::engine::http_get(port, "/shell/notices", &[("X-DentPilot-Shell", token)])?;
    if code != 200 {
        // 404 — движок без уведомлений (ещё не Т8, другой экземпляр): молча
        if code != 404 {
            log(&format!("/shell/notices: {code}"));
        }
        return None;
    }
    parse(&body)
}

pub fn parse(body: &str) -> Option<Vec<Notice>> {
    let v: Value = serde_json::from_str(body).ok()?;
    if v["v"].as_i64() != Some(1) {
        return None;
    }
    let mut out = Vec::new();
    for it in v["items"].as_array()?.iter().take(10) {
        let s = |k: &str| it[k].as_str().unwrap_or("").trim().to_string();
        let (id, title) = (s("id"), s("title"));
        if id.is_empty() || id.len() > 200 || title.is_empty() {
            continue;
        }
        // только путь экрана программы — не адрес и не «//чужой»
        let open = Some(s("open")).filter(|p| p.starts_with('/') && !p.starts_with("//") && p.len() < 300);
        out.push(Notice { id, title: title.chars().take(120).collect(), body: s("body").chars().take(400).collect(), open });
    }
    Some(out)
}

fn show_new(app: &AppHandle, items: Vec<Notice>) {
    let st = shell(app);
    let mut changed = false;
    for n in items {
        if st.store.notice_seen(&n.id) {
            continue;
        }
        let shown = toast(app, &n.title, &n.body, n.open.clone());
        log(&format!("notice {}: {shown:?}", n.id));
        // ⚠️ Выключенные человеком — тоже «показано»: это его выбор, а не повод
        // повторять каждые полчаса; без паспорта показать нечем и позже (то же
        // скажет баннер внутри программы). Сбой Windows — нет: спросим снова.
        if shown != Shown::Failed {
            st.store.mark_notice(&n.id);
            changed = true;
        }
    }
    if changed {
        st.store.save();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn notices_are_checked() {
        let body = r#"{"v":1,"items":[
          {"id":"update:1.47.0","title":"DentPilot 1.47.0 este gata","body":"Actualizați în Setări › Sistem","open":"/admin/settings/system"},
          {"id":"","title":"fără id"},
          {"id":"license:x","title":"Licența","open":"https://evil.example"},
          {"id":"sms:x","title":"SMS","open":"//evil.example/x"}]}"#;
        let n = parse(body).unwrap();
        assert_eq!(n.len(), 3);
        assert_eq!(n[0].open.as_deref(), Some("/admin/settings/system"));
        assert_eq!(n[1].open, None);
        assert_eq!(n[2].open, None);
        assert!(parse(r#"{"v":2,"items":[]}"#).is_none());
    }

    #[test]
    fn xml_is_escaped() {
        assert_eq!(xml_escape(r#"<a & "b">"#), "&lt;a &amp; &quot;b&quot;&gt;");
    }
}
