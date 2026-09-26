"""Ворота записи (L4): в `readonly` отказывает всякая запись, кроме белого списка.

Табличный тест: маршруты берутся из карты экранов (`scripts/screen_map.py`,
разбор ast), а не списком в тесте — новый пишущий маршрут попадает в таблицу
сам и обязан либо лечь в `READONLY_ALLOW`, либо отказывать. Отказ смотрится на
живом сервере с ПРОСРОЧЕННЫМ файлом: страницам 303 на `/admin?msg=…`, JSON —
423 с кодом; разрешённым — что угодно, кроме этого отказа. Те же маршруты на
ДЕЙСТВУЮЩЕМ файле обязаны отказа лицензии не получать.

⭐ Ворота стоят в шлюзе до маршрутизации, поэтому тело запроса здесь пустое
намеренно: 422 разбора формы не должен опережать отказ, и таблица это
проверяет заодно.
"""
import importlib.util
import json
import pathlib
import re
import shutil
import sys
import tempfile

from harness import BOT, ROOT, Client, Result, Server, _rmtree_settled

sys.path.insert(0, str(ROOT / "scripts"))
import screen_map  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "license"
CODE = "license_readonly"
KEY_ENV = {"DENTART_LICENSE_KEYS": str(FIX / "test-key.json")}


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lst = _load("license_state", BOT / "app" / "core" / "license_state.py")


def _routes() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(пишущие, читающие) как (метод, шаблон); неразобранные — громко."""
    rs, unresolved = screen_map.routes()
    assert not unresolved, unresolved
    write = sorted({(r["method"], r["path"]) for r in rs if r["method"] != "GET"})
    read = sorted({(r["method"], r["path"]) for r in rs if r["method"] == "GET"})
    return write, read


def _concrete(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", template)


def _refused(r) -> bool:
    if r.status == 423:
        try:
            return json.loads(r.body).get("code") == CODE
        except ValueError:
            return False
    return r.status == 303 and r.location == f"/admin?msg={CODE}"


def _send(c: Client, method: str, path: str):
    if path.startswith("/api/"):
        return c.post_json(path, {})
    return c.post(path)


def suite_matcher(res: Result) -> None:
    """Сопоставление шаблонов и честность белого списка."""
    for path, want in (("/api/patients/7/archive", True), ("/api/patients/7/archive/x", False),
                       ("/admin/login", True), ("/admin/login2", False),
                       ("/api/settings/users/ab-c/delete", True),
                       ("/api/settings/users//delete", False),
                       ("/api/patients/7/profile", False), ("/api/documents/12/open", True)):
        res.check(f"allowed({path})", lst.allowed(path), want)
    res.ok("ворота: POST под /api/ и /admin, не GET и не /chat",
           lst.gated("/api/x", "POST") and lst.gated("/admin", "DELETE")
           and not lst.gated("/api/x", "GET") and not lst.gated("/chat", "POST"))
    write, _ = _routes()
    templates = {t for _, t in write}
    stale = sorted(t for t in lst.READONLY_ALLOW if t not in templates)
    res.check("в белом списке нет шаблона без маршрута", stale, [])
    res.ok("белый список — только под /admin и /api/",
           all(t.startswith(("/admin", "/api/")) for t in lst.READONLY_ALLOW))
    outside = sorted(t for _, t in write if not t.startswith(("/admin", "/api/")))
    res.check("вне ворот только канал записи /chat", outside, ["/chat"])


def suite_readonly(res: Result) -> None:
    """Просроченный файл: таблица по всем пишущим маршрутам, чтение открыто."""
    write, read = _routes()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_gate_ro_"))
    try:
        shutil.copy(FIX / "expired.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            res.ok("сервер в readonly", "license: state=readonly" in
                   s._log_path.read_text(encoding="utf-8", errors="replace"))
            c = Client(s.url).login()
            res.check("вход в readonly разрешён: журнал открывается", c.get("/admin").status, 200)
            for method, template in write:
                if not template.startswith(("/admin", "/api/")):
                    continue
                r = _send(c, method, _concrete(template))
                if template in lst.READONLY_ALLOW:
                    res.ok(f"разрешён: {method} {template}", not _refused(r),
                           f"код {r.status}, location {r.location!r}")
                elif template.startswith("/api/"):
                    res.ok(f"отказ 423: {method} {template}",
                           r.status == 423 and _refused(r), f"код {r.status}")
                else:
                    res.ok(f"отказ 303: {method} {template}",
                           r.status == 303 and _refused(r),
                           f"код {r.status}, location {r.location!r}")
            r = c.post_json("/api/patients", {})
            body = json.loads(r.body)
            res.ok("JSON-отказ несёт текст для человека и tone err",
                   body.get("tone") == "err" and "regim de citire" in body.get("text", ""),
                   repr(body)[:160])
            page = c.get(f"/admin?msg={CODE}").body
            res.ok("страница показывает баннер отказа", "regim de citire" in page)
            for method, template in read:
                if "{" in template or not template.startswith("/api/"):
                    continue
                r = c.get(template)
                res.ok(f"чтение открыто: GET {template}", not _refused(r), f"код {r.status}")
            for method, template in read:
                if "{" in template or not template.startswith("/admin"):
                    continue
                res.ok(f"чтение открыто: GET {template}", not _refused(c.get(template)))
    finally:
        _rmtree_settled(d)


def suite_active(res: Result) -> None:
    """Действующий файл: те же маршруты отказа лицензии не получают."""
    write, _ = _routes()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_gate_ok_"))
    try:
        shutil.copy(FIX / "valid.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            res.check("вход при действующем файле", c.get("/admin").status, 200)
            for method, template in write:
                if not template.startswith(("/admin", "/api/")):
                    continue
                r = _send(c, method, _concrete(template))
                res.ok(f"без отказа лицензии: {method} {template}", not _refused(r),
                       f"код {r.status}, location {r.location!r}")
    finally:
        _rmtree_settled(d)
