// DentPilot.exe — оболочка программы на Tauri 2.
//
// Окно = два WebView: сверху полоса меню (своя страница `gen/ui/menubar.html`,
// цвет клиники), под ней программа — сначала заставка оболочки, потом
// `http://127.0.0.1:<порт>` движка. Движок — отдельный процесс (engine.rs),
// говорит строками DP1. Контракт частей — docs/dentpilot-2/tauri-contract.md;
// устройство и как собрать — docs/dentpilot-2/tauri.md.
//
// ⛔ Окно открывает адрес движка, не `tauri.localhost` (кука samesite=lax,
// same_origin_post, client_is_local). ⛔ Обновлятор Tauri не включён:
// обновление — наше (updates.md). ⛔ Странице программы прав IPC Tauri не
// выдано (capabilities нет): у оболочки она зовёт только `dpShell.send`.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
#![allow(non_snake_case)] // имя exe — DentPilot

mod engine;
mod menus;
mod notices;
mod paths;
mod state;
mod watch;
mod webview;
mod win;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::webview::{DownloadEvent, NewWindowResponse, PageLoadEvent, WebviewBuilder};
use tauri::window::Color;
use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, RunEvent, Url, WebviewUrl, WindowEvent};

use engine::{Engine, Event, Launch, Ready};
use paths::{log, Paths};
use state::Store;

pub const TITLE: &str = "DentPilot — registrul clinicii";
/// Паспорт программы (AppUserModelID): тот же у ярлыков установщика —
/// без совпадения Windows не покажет уведомления (контракт § 0).
pub const AUMID: &str = "md.dentpilot.app";
/// Свои страницы оболочки (заставка, полоса меню) — так их адресует Tauri на Windows.
pub const SHELL_PAGES: &str = "http://tauri.localhost/";
pub const VERSION: &str = env!("DP_SHELL_VERSION");
const W: f64 = 1280.0;
const H: f64 = 860.0;
/// Заставка видна не меньше — иначе это вспышка (как SPLASH_MIN_S лаунчера).
const SPLASH_MIN: Duration = Duration::from_millis(900);
const TEAL: &str = "#0E9F8A";

/// Что известно о запуске: заставка, движок, адрес программы.
#[derive(Default)]
pub struct Boot {
    pub color: Option<String>,
    pub version: Option<String>,
    pub stage: Option<(String, f64, f64)>,
    pub fail: Option<(String, String)>,
    pub ready: Option<Ready>,
    /// `http://127.0.0.1:<порт>` — единственный адрес, которому положен dpShell
    pub origin: Option<String>,
    pub url: Option<String>,
    pub busy: bool,
    pub alive: bool,
    pub splash_at: Option<Instant>,
    pub entered: bool,
    /// `warn` движка, пришедшие, пока окна не видно (запуск к часам)
    pub warns: Vec<String>,
    /// окно оставили развёрнутым, а запуск был к часам: развернуть при показе
    pub maximize: bool,
}

pub struct Shell {
    pub paths: Paths,
    pub token: String,
    pub store: Store,
    pub boot: Mutex<Boot>,
    pub engine: Mutex<Option<Arc<Engine>>>,
    pub quitting: AtomicBool,
    pub zoom: Mutex<f64>,
}

pub fn shell(app: &AppHandle) -> tauri::State<'_, Shell> {
    app.state::<Shell>()
}

pub fn valid_color(c: &str) -> bool {
    c.len() == 7 && c.starts_with('#') && c[1..].chars().all(|ch| ch.is_ascii_hexdigit())
}

/// Адрес — программа нашего движка (тот же origin, что прислал `ready`/`busy`).
pub fn is_engine_url(app: &AppHandle, url: &str) -> bool {
    let Ok(u) = Url::parse(url) else { return false };
    let o = u.origin().ascii_serialization();
    shell(app).boot.lock().map(|b| b.origin.as_deref() == Some(o.as_str())).unwrap_or(false)
}

fn splash_url(color: Option<&str>) -> String {
    let c = color.filter(|c| valid_color(c)).unwrap_or(TEAL);
    format!("splash.html?c=%23{}", &c[1..])
}

fn tint(c: &str, a: f64) -> Color {
    let c = if valid_color(c) { c } else { TEAL };
    let v = |i: usize| u8::from_str_radix(&c[i..i + 2], 16).unwrap_or(0) as f64;
    let mix = |x: f64| (255.0 - (255.0 - x) * a).round() as u8;
    Color(mix(v(1)), mix(v(3)), mix(v(5)), 255)
}

fn js_str(s: &str) -> String {
    serde_json::to_string(s).unwrap_or_else(|_| "\"\"".into())
}

/// Отложить дело на главный поток через `ms` миллисекунд.
pub fn later(app: &AppHandle, ms: u64, f: impl FnOnce(&AppHandle) + Send + 'static) {
    let app = app.clone();
    std::thread::spawn(move || {
        if ms > 0 {
            std::thread::sleep(Duration::from_millis(ms));
        }
        let h = app.clone();
        let _ = app.run_on_main_thread(move || f(&h));
    });
}

fn page(app: &AppHandle) -> Option<tauri::webview::Webview> {
    app.get_webview("app")
}

fn on_splash(app: &AppHandle) -> bool {
    page(app)
        .and_then(|p| p.url().ok())
        .is_some_and(|u| u.as_str().starts_with(SHELL_PAGES))
}

/// Догнать заставку тем, что уже известно (страница могла загрузиться позже слов).
fn push_splash(app: &AppHandle) {
    let Some(p) = page(app) else { return };
    let b = shell(app);
    let b = b.boot.lock().unwrap();
    if let Some(c) = &b.color {
        let v = b.version.clone().unwrap_or_default();
        let _ = p.eval(format!("dpHello({},{})", js_str(c), js_str(&v)));
    }
    if let Some((t, log)) = &b.fail {
        let _ = p.eval(format!("dpFail({},{})", js_str(t), js_str(log)));
    } else if let Some((t, pct, upto)) = &b.stage {
        let _ = p.eval(format!("dpStage({},{},{})", js_str(t), pct, upto));
    }
}

fn on_engine(app: &AppHandle, ev: Event) {
    let st = shell(app);
    match ev {
        Event::Hello { version, color } => {
            {
                let mut b = st.boot.lock().unwrap();
                if valid_color(&color) {
                    b.color = Some(color.clone());
                }
                b.version = Some(version);
            }
            if valid_color(&color) {
                win::paint(app, &color);
            }
            if on_splash(app) {
                push_splash(app);
            }
        }
        Event::Stage { text, pct, upto } => {
            st.boot.lock().unwrap().stage = Some((text, pct, upto));
            if on_splash(app) {
                push_splash(app);
            }
        }
        Event::Ready(r) => {
            let origin = format!("http://127.0.0.1:{}", r.port);
            let url = if r.url.starts_with(&format!("{origin}/")) { r.url.clone() } else { format!("{origin}/admin") };
            {
                let mut b = st.boot.lock().unwrap();
                if b.busy || b.fail.is_some() || b.ready.is_some() {
                    return;
                }
                b.origin = Some(origin);
                b.url = Some(url.clone());
                b.ready = Some(r.clone());
            }
            log(&format!("ready: {url} session={} lan={} data={}", r.session, r.lan, r.data));
            win::title(app, r.port);
            enter(app, url, r.session == "clear");
            notices::start(app);
        }
        Event::Busy { url } => {
            let Ok(u) = Url::parse(&url) else { return };
            if u.scheme() != "http" || u.host_str() != Some("127.0.0.1") {
                log(&format!("busy: foreign address ignored: {url}"));
                return;
            }
            {
                let mut b = st.boot.lock().unwrap();
                if b.ready.is_some() || b.fail.is_some() {
                    return;
                }
                b.busy = true;
                b.origin = Some(u.origin().ascii_serialization());
                b.url = Some(url.clone());
            }
            log(&format!("busy: showing {url} without an engine of our own"));
            win::title(app, u.port().unwrap_or(80));
            enter(app, url, false);
        }
        Event::Warn { text } => {
            // показать, не останавливая запуск; окна не видно (`--tray`) —
            // когда оно впервые покажется (win::show_main)
            let visible = app.get_window("main").and_then(|w| w.is_visible().ok()).unwrap_or(false);
            if visible {
                win::warn(&text);
            } else if !text.trim().is_empty() {
                st.boot.lock().unwrap().warns.push(text);
            }
        }
        Event::Fatal { text, log: path } => {
            st.boot.lock().unwrap().fail = Some((text, path));
            fail_screen(app);
        }
        Event::Quit { reason } => {
            log(&format!("engine asks to close: {reason}"));
            st.quitting.store(true, Ordering::SeqCst);
            app.exit(0);
        }
        Event::Exited(code) => {
            let quitting = st.quitting.load(Ordering::SeqCst);
            let mut b = st.boot.lock().unwrap();
            b.alive = false;
            log(&format!("engine exited: code {code:?}"));
            if quitting || b.busy || b.fail.is_some() {
                return;
            }
            let (text, path) = match &b.ready {
                Some(r) => (
                    "DentPilot s-a oprit neașteptat.\nPorniți programul din nou.".to_string(),
                    std::path::Path::new(&r.data).join("data").join("dentpilot.log").display().to_string(),
                ),
                None => (
                    "DentPilot nu a putut porni.".to_string(),
                    st.paths.log_file().display().to_string(),
                ),
            };
            b.fail = Some((text, path));
            drop(b);
            fail_screen(app);
        }
    }
}

/// Беда — на заставку (и окно на экран: у часов её никто не увидит).
fn fail_screen(app: &AppHandle) {
    if on_splash(app) {
        push_splash(app);
    } else if let Some(p) = page(app) {
        let color = shell(app).boot.lock().unwrap().color.clone();
        if let Ok(u) = Url::parse(&format!("{SHELL_PAGES}{}", splash_url(color.as_deref()))) {
            let _ = p.navigate(u); // заставка сама догонит текстом беды при загрузке
        }
    }
    win::show_main(app);
}

/// Из заставки — в программу: полоска дошла, заставка погасла, тот же WebView
/// уходит на адрес движка (экран входа встаёт на том же фоне).
fn enter(app: &AppHandle, url: String, clear: bool) {
    let visible = app.get_window("main").and_then(|w| w.is_visible().ok()).unwrap_or(false);
    let shown = shell(app).boot.lock().unwrap().splash_at;
    // ⚠️ Движок бывает готов раньше, чем WebView2 покажет заставку: тогда она
    // мелькнула бы долей секунды. Минимум показа — только в этом случае.
    let wait = match (visible, shown) {
        (true, Some(t)) => SPLASH_MIN.saturating_sub(t.elapsed()).as_millis() as u64,
        (true, None) => SPLASH_MIN.as_millis() as u64,
        _ => 0,
    };
    let fade = if visible { 450 } else { 0 };
    later(app, wait, move |app| {
        if let Some(p) = page(app) {
            let _ = p.eval("window.dpDone && dpDone()");
        }
        later(app, fade, move |app| {
            if clear {
                // общий ПК: каждый запуск — с экрана входа
                if let Some(p) = page(app) {
                    webview::clear_cookies(&p);
                }
            }
            later(app, if clear { 200 } else { 0 }, move |app| {
                if let (Some(p), Ok(u)) = (page(app), Url::parse(&url)) {
                    shell(app).boot.lock().unwrap().entered = true;
                    let _ = p.navigate(u);
                }
            });
        });
    });
}

/// Переход WebView программы: свои страницы и адрес движка — внутри окна;
/// чужое — в браузер Windows (сайт, оплата), в окне программы ему не место:
/// кнопки «назад» здесь нет.
fn allow_navigation(app: &AppHandle, url: &Url) -> bool {
    if url.as_str().starts_with(SHELL_PAGES) || url.as_str() == "about:blank" {
        return true;
    }
    if is_engine_url(app, url.as_str()) {
        return true;
    }
    if url.scheme() == "blob" {
        // выгрузка, собранная страницей: blob:http://127.0.0.1:<порт>/…
        return is_engine_url(app, url.path());
    }
    win::open_external(url.as_str());
    false
}

fn dev_identifier(paths: &Paths) -> Option<String> {
    // Стенд (`DENTART_PROFILE_DIR`) — отдельный экземпляр со своим замком
    // «один экземпляр»: иначе он показал бы окно установленной программы.
    paths.stand.then(|| {
        let s = paths.profile.display().to_string().to_lowercase();
        let h = s.bytes().fold(0xcbf29ce484222325u64, |h, b| (h ^ b as u64).wrapping_mul(0x100000001b3));
        format!("{AUMID}.stand{:08x}", h as u32)
    })
}

fn main() {
    // ⭐ Один `generate_context!` на exe: страницы оболочки вшиваются им, и второй
    // вызов (у сторожа) вшил бы их второй раз.
    let mut context = tauri::generate_context!();
    // Сторож обновления и перезапуска (Т10, watch.rs): копия этого exe с
    // `--watch …` — раньше всего: ни замка «один экземпляр» (запускаемая им
    // программа нашла бы «первый экземпляр» в нём), ни журнала, ни движка.
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();
    if watch::is_watch(&args) {
        std::process::exit(watch::main(&args, context));
    }
    notices::set_process_aumid();
    let tray_start = std::env::args().any(|a| a == "--tray");
    let paths = Paths::find();
    let store = Store::load(&paths.state);
    let saved = store.get();
    let token = engine::new_token();

    if let Some(id) = dev_identifier(&paths) {
        context.config_mut().identifier = id;
    }

    let app = tauri::Builder::default()
        // Второй запуск ярлыка: окно первого — на экран (даже спрятанное у часов).
        // `--tray` (автозапуск, а программа уже работает) окна не показывает.
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if !argv.iter().any(|a| a == "--tray") {
                log("second start: showing the window");
                win::show_main(app);
            }
        }))
        .on_menu_event(|app, ev| menus::on_event(app, ev.id().as_ref()))
        .on_window_event(|window, event| match event {
            WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                win::close_requested(window.app_handle());
            }
            WindowEvent::Resized(_) | WindowEvent::ScaleFactorChanged { .. } => {
                win::layout(window.app_handle());
                state::track(window);
            }
            WindowEvent::Moved(_) => state::track(window),
            _ => {}
        })
        .setup(move |app| {
            // ⚠️ Журнал — только у ПЕРВОГО экземпляра: сюда второй запуск не
            // доходит (его закрыл замок «один экземпляр» выше), а открой он
            // журнал раньше — перекрутил бы `shell.log` работающей программы.
            paths::open_log(&paths.log_file());
            log(&format!(
                "DentPilot shell {VERSION} start pid={} base={} profile={} tray={tray_start}",
                std::process::id(),
                paths.base.display(),
                paths.profile.display()
            ));
            let h = app.handle().clone();
            let color = saved.color.clone().filter(|c| valid_color(c));
            app.manage(Shell {
                paths,
                token,
                store,
                boot: Mutex::new(Boot { color: color.clone(), ..Default::default() }),
                engine: Mutex::new(None),
                quitting: AtomicBool::new(false),
                zoom: Mutex::new(saved.zoom.unwrap_or(1.0)),
            });
            let st = shell(&h);
            if let Err(e) = std::fs::create_dir_all(&st.paths.profile) {
                log(&format!("WebView2 profile not created: {e}"));
            }
            let bg = tint(color.as_deref().unwrap_or(TEAL), 0.06);

            let window = tauri::window::WindowBuilder::new(app, "main")
                .title(TITLE)
                .inner_size(W, H)
                .min_inner_size(960.0, 640.0)
                .background_color(bg)
                .visible(false)
                .build()?;
            let maximized = state::restore(&window, saved.window);

            let bar_url = format!("menubar.html?c=%23{}", &color.as_deref().unwrap_or(TEAL)[1..]);
            let bar = window.add_child(
                WebviewBuilder::new("bar", WebviewUrl::App(bar_url.into()))
                    .data_directory(st.paths.profile.clone())
                    .background_color(tint(color.as_deref().unwrap_or(TEAL), 0.07))
                    .devtools(false)
                    .on_navigation(|u| u.as_str().starts_with(SHELL_PAGES)),
                LogicalPosition::new(0.0, 0.0),
                LogicalSize::new(W, win::BAR),
            )?;
            webview::attach(&bar, webview::Who::Bar);

            let (h1, h2, h3, h4) = (h.clone(), h.clone(), h.clone(), h.clone());
            let script = include_str!("page.js").replace("__DP_SHELL_VERSION__", VERSION);
            let page = window.add_child(
                WebviewBuilder::new("app", WebviewUrl::App(splash_url(color.as_deref()).into()))
                    .data_directory(st.paths.profile.clone())
                    .background_color(bg)
                    .devtools(cfg!(debug_assertions))
                    .initialization_script(script)
                    .on_navigation(move |u| allow_navigation(&h1, u))
                    .on_new_window(move |u, _| {
                        // target=_blank: своё — в этом же окне, чужое — в браузер
                        if is_engine_url(&h2, u.as_str()) {
                            if let Some(p) = page(&h2) {
                                let _ = p.navigate(u);
                            }
                        } else {
                            win::open_external(u.as_str());
                        }
                        NewWindowResponse::Deny
                    })
                    .on_download(move |_wv, ev| match ev {
                        DownloadEvent::Requested { url, destination } => {
                            let ok = win::save_as(&h3, destination);
                            log(&format!("download {url}: {}", if ok { destination.display().to_string() } else { "cancelled".into() }));
                            ok
                        }
                        DownloadEvent::Finished { url, path, success } => {
                            log(&format!("download done {url}: {success} {path:?}"));
                            true
                        }
                        _ => true,
                    })
                    .on_page_load(move |wv, p| {
                        if p.event() != PageLoadEvent::Finished {
                            return;
                        }
                        if p.url().as_str().starts_with(SHELL_PAGES) {
                            {
                                let st = shell(&h4);
                                let mut b = st.boot.lock().unwrap();
                                b.splash_at.get_or_insert_with(Instant::now);
                            }
                            push_splash(&h4);
                        } else if is_engine_url(&h4, p.url().as_str()) {
                            menus::read_ctx(&h4, &wv);
                        }
                    }),
                LogicalPosition::new(0.0, win::BAR),
                LogicalSize::new(W, H - win::BAR),
            )?;
            webview::attach(&page, webview::Who::Page);
            let z = *st.zoom.lock().unwrap();
            if (z - 1.0).abs() > 0.01 {
                let _ = page.set_zoom(z);
            }
            win::layout(&h);
            win::tray(app)?;
            if tray_start {
                // к часам: развернуть — при первом показе (win::show_main)
                st.boot.lock().unwrap().maximize = maximized;
            } else {
                if maximized {
                    let _ = window.maximize();
                }
                let _ = window.show();
                let _ = page.set_focus();
            }

            // движок — после окна: заставка уже на экране, пока он поднимается
            let (tx, rx) = mpsc::channel::<Event>();
            match Launch::find(&st.paths.base).and_then(|l| Engine::start(&l, &st.token, tx).map_err(|e| e.to_string())) {
                Ok(e) => {
                    st.boot.lock().unwrap().alive = true;
                    *st.engine.lock().unwrap() = Some(Arc::new(e));
                }
                Err(e) => {
                    log(&format!("engine not started: {e}"));
                    st.boot.lock().unwrap().fail = Some((
                        format!("DentPilot nu a putut porni.\n{e}"),
                        st.paths.log_file().display().to_string(),
                    ));
                    fail_screen(&h);
                }
            }
            let hp = h.clone();
            std::thread::spawn(move || {
                for ev in rx {
                    let a = hp.clone();
                    let _ = hp.run_on_main_thread(move || on_engine(&a, ev));
                }
            });
            Ok(())
        })
        .build(context)
        .expect("Tauri nu a pornit");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            shutdown(handle);
        }
    });
}

/// Выход: окно и значок — сразу, движок — честно (не дольше 10 с).
fn shutdown(app: &AppHandle) {
    let st = shell(app);
    st.quitting.store(true, Ordering::SeqCst);
    if let Some(w) = app.get_window("main") {
        state::track(&w);
        let _ = w.hide();
    }
    st.store.save();
    let _ = app.remove_tray_by_id("dentpilot");
    let engine = st.engine.lock().unwrap().take();
    if let Some(e) = engine {
        let t = Instant::now();
        let code = e.stop(engine::STOP_WAIT);
        log(&format!("exit: engine stopped in {:.1} s, code {code:?}", t.elapsed().as_secs_f64()));
    }
    log("exit");
}
