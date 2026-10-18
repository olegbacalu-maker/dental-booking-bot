r"""Публикация релиза БЕЗ веб-формы — у неё нашлись три ловушки за два дня.

    python scripts/release.py status              # все релизы с флагами
    python scripts/release.py prerelease 1.14.1   # pre-release с ОДНИМ ассетом (zip мастера)
    python scripts/release.py check 1.14.1        # смотрит глазами клиники
    python scripts/release.py publish 1.14.1      # снять метку → latest

Лестница целиком: bump → push → Build-Installer.ps1 → git tag vX.Y.Z + push →
`prerelease` → канарейка руками → `publish` → `check`.

Почему не форма GitHub (все три случились с нами, 08-06…08-07):
  1) «create tag on publish» завела тег без «v» на чужом коммите со старыми
     ассетами — ловушка вечного цикла обновления;
  2) галочка pre-release + незаметная «Update release» — правки молча
     не сохранялись;
  3) Publish существующего релиза создавал ЧЕРНОВИК-ДВОЙНИК с тем же тегом
     (публикация двойника даёт 422: тег занят настоящим), и latest не двигался.
Скрипт работает с релизом по id, найденному через GraphQL, — двойника не
создаёт, а чужого не трогает.

Токен: DENTART_UPDATE_TOKEN / GITHUB_TOKEN из окружения → git credential
(тот же, которым идёт push) → dental.env установленной программы. Лимит API
для токена — 5000/час; анонимные 60/час здесь не участвуют. Токен в вывод
не попадает никогда.

⚠️ Тег создаёт git, НЕ этот скрипт: `prerelease` требует уже запушенный
vX.Y.Z — иначе релиз описал бы не тот код, из которого собран бинарник.
⚠️ Ассет ОДИН (Tauri, Т9, 18.10.2026): dist\DentPilot-Setup-X.Y.Z.zip, внутри
ровно один подписанный DentPilot-Setup-X.Y.Z.exe. Программа теперь — две
части (оболочка DentPilot.exe + папка движка engine\), подменой одного файла
её не обновить: клиника обновляется мастером из этого zip (update.py, режим
установщика). Отдельный DentPilot.exe больше не выкладывается — это оболочка
без движка. ⛔ Ни одного .exe в релизе: клиника старой сборки выбирала ассет
по имени и скачала бы не то, затерев себя (сторож — здесь и в check_release).
⛔ Мастер на диске проверяется ДО заливки тем же, чем его проверит программа
клиники (`setup_problems`): ровно один exe с именем версии в zip, подпись
НАШИМ сертификатом (`privileged.SIGNERS`), версия файла = версия выпуска.
Пробная сборка `Build-Installer.ps1 -NoSign` здесь останавливается.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from bot.app import authenticode, privileged  # noqa: E402 — те же проверки, что у клиники
from bot.app.repo import REPO  # noqa: E402 — один адрес на весь проект

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = f"https://api.github.com/repos/{REPO}"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def setup_zip(ver: str) -> str:
    """Имя единственного ассета выпуска — его ищет обновлятор (update._SETUP_ZIP)."""
    return f"DentPilot-Setup-{ver}.zip"


def setup_exe(ver: str) -> str:
    return f"DentPilot-Setup-{ver}.exe"

_ENV_DIRS = [
    pathlib.Path(r"C:\Users\Public\DentPilot"),
    pathlib.Path(r"C:\DentPilot"),
    pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DentPilot",
]


def find_token() -> str:
    for var in ("DENTART_UPDATE_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        v = (os.environ.get(var) or "").strip().strip("\"'")
        if v:
            return v
    # тот же токен, которым git пушит с этой машины (Credential Manager)
    try:
        out = subprocess.run(["git", "credential", "fill"],
                             input="protocol=https\nhost=github.com\n\n",
                             capture_output=True, text=True, timeout=30)
        for line in out.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1]
    except Exception:  # noqa: BLE001 — нет git в PATH и т.п.
        pass
    for d in _ENV_DIRS:
        f = d / "dental.env"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("DENTART_UPDATE_TOKEN=") and not s.startswith("#"):
                v = s.split("=", 1)[1].strip().strip("\"'")
                if v:
                    return v
    return ""


# Ищется в main(), а не при импорте: прогон берёт отсюда `setup_problems`, и
# импорт не должен ходить в git credential.
TOKEN = ""


def setup_problems(ver: str, dist: pathlib.Path = DIST) -> list[str]:
    """Что не так с мастером выпуска на диске — словами; пусто = можно лить.

    Ровно то, что проверит перед обновлением программа клиники
    (`update._update_by_setup` → `privileged` install-setup): в zip один .exe
    с именем версии, подпись Authenticode НАШИМ сертификатом. Плюс версия
    файла: мастер, собранный не из того кода, назвался бы чужим номером.
    Неподписанный мастер (пробная сборка `-NoSign`) клиника отвергнет —
    значит, и выпуск тоже."""
    zpath = dist / setup_zip(ver)
    if not zpath.exists():
        return [f"нет файла {zpath} — сначала соберите: .\\Build-Installer.ps1"]
    want = setup_exe(ver)
    try:
        with zipfile.ZipFile(zpath) as z:
            names = [i.filename for i in z.infolist()]
            if names != [want]:
                return [f"в {zpath.name} лежит {names}, а должен ровно один {want} — "
                        "обновление клиники такой архив отвергнет"]
            with tempfile.TemporaryDirectory(prefix="dp_release_") as tmp:
                exe = pathlib.Path(tmp) / want
                with z.open(want) as src, open(exe, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                thumb = authenticode.signer_thumbprint(exe)
                fver = authenticode.file_version(exe)
    except (zipfile.BadZipFile, OSError) as e:
        return [f"{zpath.name} не открывается: {e}"]
    bad = []
    if thumb is None:
        bad.append("мастер НЕ подписан (или подпись недействительна) — пробная сборка "
                   "-NoSign? В выпуск идёт только подписанная: войти в SimplySign Desktop "
                   "и .\\Build-Installer.ps1 без ключей")
    elif thumb not in privileged.SIGNERS:
        bad.append(f"мастер подписан чужим сертификатом {thumb} — программа клиники его "
                   "отвергнет (privileged.SIGNERS)")
    got = ".".join(str(n) for n in fver[:3]) if fver else ""
    if got != ver:
        bad.append(f"версия файла мастера {got or 'не читается'}, а выпуск {ver}")
    return bad


def scrub(text: str) -> str:
    return text.replace(TOKEN, "***") if TOKEN else text


def call(url: str, method: str = "GET", body: bytes | None = None,
         ctype: str = "application/json"):
    req = urllib.request.Request(url, data=body, method=method, headers={
        "User-Agent": "dentpilot-release",
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
    })
    if body is not None:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=600) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def nodes_by_tag() -> list[dict]:
    """Все релизы через GraphQL: REST-список черновики показывает не всегда,
    а /releases/tags/ при двойниках отдаёт не тот узел."""
    q = ('{ repository(owner:"%s", name:"%s") { releases(first:50, '
         'orderBy:{field:CREATED_AT, direction:DESC}) { nodes '
         '{ databaseId tagName isDraft isPrerelease isLatest } } } }'
         % tuple(REPO.split("/")))
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": q}).encode(),
        headers={"User-Agent": "dentpilot-release",
                 "Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        raise RuntimeError(scrub(str(data["errors"])[:300]))
    return data["data"]["repository"]["releases"]["nodes"]


def cmd_status() -> int:
    for n in nodes_by_tag():
        flags = ([] + (["DRAFT"] if n["isDraft"] else [])
                 + (["prerelease"] if n["isPrerelease"] else [])
                 + (["LATEST"] if n["isLatest"] else []))
        print(f"{n['tagName']:12} id={n['databaseId']}  "
              f"{' '.join(flags) or 'published'}")
    return 0


def cmd_prerelease(ver: str) -> int:
    tag = f"v{ver}"
    bad = setup_problems(ver)
    if bad:
        print("✗ мастер выпуска не годится:")
        for b in bad:
            print(f"  - {b}")
        return 1
    assets = [DIST / setup_zip(ver)]
    try:
        call(f"{API}/git/ref/tags/{tag}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"✗ тега {tag} нет на GitHub. Тег создаёт git:\n"
                  f"  git tag -a {tag} -m \"DentPilot {ver}\" && "
                  f"git push origin {tag}")
            return 1
        raise

    mine = [n for n in nodes_by_tag() if n["tagName"] == tag]
    real = next((n for n in mine if not n["isDraft"]), None)
    if real and not real["isPrerelease"]:
        print(f"✗ {tag} уже ОПУБЛИКОВАН (id {real['databaseId']}). Релизы "
              f"только вперёд: правится выпуском следующей версии.")
        return 1
    if real:
        rel = call(f"{API}/releases/{real['databaseId']}")
        print(f"Pre-release {tag} уже есть (id {rel['id']}) — дополняю его.")
    else:
        print(f"Создаю pre-release {tag} …")
        # name/body пустые — как у всех релизов проекта: клиника видит ассеты
        rel = call(f"{API}/releases", "POST", json.dumps({
            "tag_name": tag, "name": "", "body": "",
            "draft": False, "prerelease": True,
        }).encode())
        print(f"  создан, id {rel['id']}")

    have = {a["name"].lower(): a for a in rel.get("assets", [])}
    # Лишнее у pre-release (DentPilot.exe прежней лестницы, чужой файл) —
    # убрать: клиникам pre-release не виден, а publish такой узел не пропустит.
    keep = {f.name.lower() for f in assets}
    for name, a in list(have.items()):
        if name not in keep:
            print(f"  убираю лишний ассет {a['name']} — в выпуске только {assets[0].name}")
            call(f"{API}/releases/assets/{a['id']}", "DELETE")
            del have[name]
    for f in assets:
        a = have.get(f.name.lower())
        if a:
            if a.get("state") == "uploaded" and a.get("size") == f.stat().st_size:
                print(f"  {f.name} уже залит и совпадает по размеру — пропускаю")
                continue
            print(f"  удаляю прошлый {a['name']} (state={a.get('state')})")
            call(f"{API}/releases/assets/{a['id']}", "DELETE")
        print(f"Заливаю {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB) …")
        r = call(rel["upload_url"].split("{")[0] + f"?name={f.name}",
                 "POST", f.read_bytes(), "application/octet-stream")
        print(f"  залит: {r.get('name')} state={r.get('state')}")

    got = call(f"{API}/releases/{rel['id']}")
    names = [(a["name"], a.get("size"), a.get("state")) for a in got["assets"]]
    ok = (got["prerelease"] and not got["draft"]
          and [n for n, _s, _st in names] == [setup_zip(ver)]
          and all(st == "uploaded" for _n, _s, st in names))
    print(f"\n{'✓' if ok else '✗'} {tag}: prerelease={got['prerelease']} "
          f"draft={got['draft']}, файлы:")
    for n, s, st in names:
        print(f"   {n}  {s} б  {st}")
    print(f"   {got['html_url']}")
    if ok:
        # pre-release безопасен по построению (`latest` не двигается), поэтому
        # проверка GitHub здесь только называется; остановит она publish
        verdict, _lines = ci_state(tag)
        print(f"\nПроверка GitHub у {tag}: {verdict}"
              + ("" if verdict == "green" else " — publish её дождётся"))
        print(f"Дальше: канарейка руками → python scripts/release.py publish {ver}")
    return 0 if ok else 1


def ci_verdict(check_runs: list[dict]) -> tuple[str, list[str]]:
    """Что сказала автоматическая проверка (GitHub Actions) о коммите:
    `green` — все работы завершились успехом; `red` — хоть одна упала;
    `pending` — ещё идёт или отменена (то есть коммит НЕ проверен);
    `none` — работ нет. Второе — строки для человека."""
    lines, verdict = [], "none"
    for r in check_runs:
        st, concl = r.get("status"), (r.get("conclusion") or "")
        lines.append(f"   {r.get('name')}: {concl or st}")
        if st != "completed" or concl in ("cancelled", "timed_out", "action_required",
                                          "stale", ""):
            verdict = "pending" if verdict != "red" else verdict
        elif concl in ("failure", "startup_failure"):
            verdict = "red"
        elif verdict == "none":
            verdict = "green"
    return verdict, lines


def ci_state(ref: str) -> tuple[str, list[str]]:
    """Проверка коммита `ref` (тег или SHA) по check-runs GitHub."""
    data = call(f"{API}/commits/{ref}/check-runs?per_page=50")
    return ci_verdict(data.get("check_runs", []))


def cmd_publish(ver: str, allow_red: bool = False) -> int:
    tag = f"v{ver}"
    # ⛔ Publish двигает `latest` ВСЕМ клиникам, и откатить его нельзя. С 7 по
    # 14.10 проверка на GitHub не была зелёной ни разу, а клиникам ушли девять
    # выпусков — лестница её не спрашивала (посторонний разбор 17.10). Теперь
    # спрашивает: красный или непроверенный (отменённый, идущий) коммит тега
    # не публикуется. `--allow-red` — осознанное «принимаем», словами в выводе.
    verdict, lines = ci_state(tag)
    print(f"Проверка GitHub у {tag}: {verdict}")
    for ln in lines:
        print(ln)
    if verdict != "green" and not allow_red:
        why = {"red": "проверка КРАСНАЯ", "pending": "проверка не завершена или отменена",
               "none": "проверок у коммита нет"}[verdict]
        print(f"✗ не публикую: {why}. Дождитесь зелёного (или перезапустите: "
              f"gh workflow run tests.yml --ref {tag}); осознанно мимо — "
              f"python scripts/release.py publish {ver} --allow-red")
        return 1
    if verdict != "green":
        print("⚠️ публикую МИМО проверки по явному --allow-red")
    mine = [n for n in nodes_by_tag() if n["tagName"] == tag]
    if not mine:
        print(f"✗ релиза {tag} нет — сначала: python scripts/release.py prerelease {ver}")
        return 1
    drafts = [n for n in mine if n["isDraft"]]
    real = next((n for n in mine if not n["isDraft"]), None)
    if drafts:
        ids = ", ".join(str(n["databaseId"]) for n in drafts)
        print(f"⚠️ у {tag} есть черновик-двойник (id {ids}) — так делает "
              f"веб-форма. Публикую настоящий узел; двойник удалите в вебе "
              f"(Delete draft), клиникам он не виден.")
    if real is None:
        print(f"✗ {tag} существует только черновиком. Черновик формы не "
              f"содержит проверенных ассетов — залейте настоящий: "
              f"python scripts/release.py prerelease {ver}")
        return 1
    rel = call(f"{API}/releases/{real['databaseId']}")
    if not rel["prerelease"]:
        print(f"✓ {tag} уже опубликован — ничего не делаю.")
        return 0
    names = [(a["name"], a.get("state")) for a in rel.get("assets", [])]
    if ([n for n, _st in names] != [setup_zip(ver)]
            or any(st != "uploaded" for _n, st in names)):
        print(f"✗ не публикую: у {tag} файлы {names} — а нужен ровно один "
              f"{setup_zip(ver)} и ни одного .exe. Почините pre-release сначала: "
              f"python scripts/release.py prerelease {ver}")
        return 1
    rel = call(f"{API}/releases/{real['databaseId']}", "PATCH", json.dumps({
        "prerelease": False, "make_latest": "true",
    }).encode())
    latest = call(f"{API}/releases/latest")
    ok = not rel["prerelease"] and latest.get("tag_name") == tag
    print(f"{'✓' if ok else '✗'} {tag} опубликован; latest = "
          f"{latest.get('tag_name')}")
    print(f"Контроль: python scripts/release.py check {ver}")
    return 0 if ok else 1


def cmd_check(ver: str) -> int:
    """check_release.py и так есть — сюда он позван с токеном, чтобы не
    упираться в анонимные 60/час и видеть черновики."""
    env = dict(os.environ, GITHUB_TOKEN=TOKEN)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_release.py"), ver],
        env=env).returncode


def main() -> int:
    global TOKEN
    TOKEN = find_token()
    if not TOKEN:
        print("✗ Токен не найден (env / git credential / dental.env).")
        return 1
    args = sys.argv[1:]
    allow_red = "--allow-red" in args
    args = [a for a in args if a != "--allow-red"]
    if args[:1] == ["status"]:
        return cmd_status()
    if len(args) == 2 and args[0] in ("prerelease", "publish", "check"):
        ver = args[1].lstrip("vV")
        if not all(p.isdigit() for p in ver.split(".")) or ver.count(".") != 2:
            print(f"✗ версия {args[1]!r} — нужно ровно X.Y.Z")
            return 1
        if args[0] == "publish":
            return cmd_publish(ver, allow_red)
        return {"prerelease": cmd_prerelease, "check": cmd_check}[args[0]](ver)
    print(__doc__.split("\n\n")[0])
    print("Команды: status | prerelease X.Y.Z | check X.Y.Z | publish X.Y.Z [--allow-red]")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = scrub(e.read().decode("utf-8", "replace"))[:400]
        except Exception:  # noqa: BLE001
            pass
        print(f"\n✗ GitHub отказал: HTTP {e.code}\n{detail}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ Не получилось: {scrub(repr(e))}")
        sys.exit(1)
