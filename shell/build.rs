// Сборка оболочки: сперва страницы и значок (shell/assets.py → shell/gen/),
// потом обычная сборка Tauri.
//
// ⚠️ Заставка и значок рисуются из bot/app/brand.py — той же фигурой, что
// шапка программы и прежний DentPilot.exe. Поэтому сборке нужен Python
// программы (.venv-desktop, в нём PIL); готовой оболочке — нет.
// ⭐ Версия DentPilot.exe — APP_VERSION из bot/app/engine.py: у выпуска одна
// версия, её видят «Свойства» файла и «Despre DentPilot».
use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let shell = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let app = shell.parent().expect("shell/ лежит в app/").to_path_buf();
    for p in [
        shell.join("assets.py"),
        shell.join("ui").join("menubar.html"),
        app.join("bot").join("app").join("brand.py"),
        app.join("bot").join("app").join("splash.py"),
        app.join("bot").join("app").join("engine.py"),
        app.join("bot").join("app").join("static").join("css").join("fonts.css"),
        app.join("scripts").join("make_icon.py"),
    ] {
        println!("cargo:rerun-if-changed={}", p.display());
    }
    println!("cargo:rerun-if-env-changed=DENTPILOT_PYTHON");

    let gen = shell.join("gen");
    let python = env::var_os("DENTPILOT_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| app.join(".venv-desktop").join("Scripts").join("python.exe"));
    let have = ["icon.ico", "ui/splash.html", "ui/menubar.html"]
        .iter()
        .all(|f| gen.join(f).exists());
    if python.exists() {
        let ok = Command::new(&python)
            .arg(shell.join("assets.py"))
            .arg(&gen)
            .env("PYTHONUTF8", "1")
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if !ok {
            panic!("shell/assets.py nu a reușit ({})", python.display());
        }
    } else if have {
        println!(
            "cargo:warning=nu găsesc {} - folosesc shell/gen/ de la sursa precedentă",
            python.display()
        );
    } else {
        panic!(
            "nu găsesc {}: pagina de pornire și pictograma se fac cu Python-ul programului \
             (.venv-desktop sau DENTPILOT_PYTHON)",
            python.display()
        );
    }

    let engine = std::fs::read_to_string(app.join("bot").join("app").join("engine.py"))
        .expect("bot/app/engine.py");
    let version = engine
        .lines()
        .find_map(|l| {
            let rest = l.trim_start().strip_prefix("APP_VERSION")?;
            let rest = rest.trim_start().strip_prefix('=')?.trim().strip_prefix('"')?;
            Some(rest.split('"').next()?.to_string())
        })
        .filter(|v| v.split('.').count() == 3 && v.split('.').all(|n| n.parse::<u32>().is_ok()))
        .expect("APP_VERSION din bot/app/engine.py: trei numere");
    let merge = format!(r#"{{"version":"{version}"}}"#);
    // tauri-build читает TAURI_CONFIG из своего процесса (ресурс exe),
    // generate_context! — из окружения rustc (cargo:rustc-env)
    env::set_var("TAURI_CONFIG", &merge);
    println!("cargo:rustc-env=TAURI_CONFIG={merge}");
    println!("cargo:rustc-env=DP_SHELL_VERSION={version}");

    tauri_build::build();
}
