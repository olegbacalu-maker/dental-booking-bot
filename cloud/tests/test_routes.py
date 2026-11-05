"""Маршруты облака (03.11, разнос main.py на роутеры): набор адресов — тот же, что до разноса.

Снимок (метод, путь, имя) снят с app `2d1a5eb`, когда все маршруты жили в main.py. Новый
маршрут = строка здесь; пропавший или переименованный — красный: роутер, не подключённый в
main.py, теряет свои адреса без единой ошибки. Сервер не поднимается: `app.routes` читается
импортом, правила раскладки — разбором исходников `ast`.
"""
import ast
import copy
import re
import sys

from starlette.routing import compile_path

from harness import CLOUD, Result

SNAPSHOT = [
    ("GET", "/openapi.json", "openapi"),
    ("HEAD", "/openapi.json", "openapi"),
    ("GET", "/health", "health"),
    ("GET", "/robots.txt", "robots_txt"),
    ("GET", "/v1/license", "license_renew"),
    ("GET", "/v1/update", "update_api"),
    ("POST", "/v1/pay-link", "pay_link_api"),
    ("POST", "/v1/cont-link", "cont_link_api"),
    ("GET", "/v1/sms/account", "sms_account"),
    ("POST", "/v1/sms/send", "sms_send"),
    ("POST", "/v1/sms/status", "sms_status"),
    ("POST", "/v1/sms/sender", "sms_sender"),
    ("POST", "/v1/sms/order", "sms_order"),
    ("POST", "/v1/smsmd/dlr/{secret}", "smsmd_dlr"),
    ("GET", "/plata/{pid}", "pay_link_page"),
    ("POST", "/plata/{pid}", "pay_link_submit"),
    ("GET", "/", "root"),
    ("GET", "/admin/login", "login_page"),
    ("POST", "/admin/login", "login"),
    ("POST", "/admin/logout", "logout"),
    ("GET", "/admin", "clinics"),
    ("GET", "/proba", "trial_form"),
    ("POST", "/proba", "trial_submit"),
    ("POST", "/v1/trial", "trial_api"),
    ("POST", "/v1/verify", "trial_verify"),
    ("POST", "/v1/email/code", "email_code_api"),
    ("POST", "/v1/email/change", "email_change_api"),
    ("POST", "/v1/email/confirm", "email_confirm_api"),
    ("GET", "/confirma/{key}", "email_confirm_page"),
    ("POST", "/confirma/{key}", "email_confirm_submit"),
    ("POST", "/admin/clinics/{cid}/decline", "trial_decline"),
    ("POST", "/admin/clinics", "clinic_new"),
    ("GET", "/admin/clinics/{cid}", "clinic_card"),
    ("POST", "/admin/clinics/{cid}/sibling", "clinic_sibling"),
    ("GET", "/admin/fleet", "fleet_page"),
    ("GET", "/admin/api/fleet", "fleet_api"),
    ("GET", "/admin/sms", "sms_admin"),
    ("GET", "/admin/api/sms", "sms_api"),
    ("GET", "/admin/sms/export.xlsx", "sms_export"),
    ("POST", "/admin/sms/sync", "sms_sync"),
    ("POST", "/admin/sms/test", "sms_test"),
    ("POST", "/admin/clinics/{cid}/sms", "clinic_sms_action"),
    ("GET", "/admin/clinics/{cid}/sms/cerere.pdf", "clinic_sms_paper"),
    ("GET", "/admin/clinics/{cid}/documente/{rid}.pdf", "clinic_document_file"),
    ("POST", "/admin/jobs/daily", "daily_job"),
    ("GET", "/admin/audit", "audit_log"),
    ("GET", "/admin/payments", "payments_pending"),
    ("POST", "/admin/clinics/{cid}/payments", "payment_new"),
    ("POST", "/admin/payments/{pid}/check", "payment_check"),
    ("POST", "/admin/payments/{pid}/link", "payment_link"),
    ("POST", "/v1/maib/callback", "maib_callback"),
    ("GET", "/pay/ok", "pay_ok"),
    ("GET", "/pay/fail", "pay_fail"),
    ("GET", "/admin/payments/{pid}/cont.pdf", "payment_receipt"),
    ("POST", "/admin/payments/{pid}/confirm", "payment_confirm"),
    ("POST", "/admin/payments/{pid}/repeat", "payment_repeat"),
    ("POST", "/admin/payments/{pid}/mail", "payment_mail"),
    ("POST", "/admin/payments/{pid}/reject", "payment_reject"),
    ("POST", "/admin/clinics/{cid}/edit", "clinic_edit"),
    ("POST", "/admin/clinics/{cid}/issue", "clinic_issue"),
    ("POST", "/admin/clinics/{cid}/tier", "clinic_tier"),
    ("GET", "/admin/clinics/{cid}/issues/{seq}/license.json", "issue_file"),
    ("POST", "/admin/clinics/{cid}/email", "clinic_email"),
    ("POST", "/admin/accounts/{aid}/detach", "account_detach"),
    ("GET", "/cont", "cont_home"),
    ("GET", "/cont/intra/{lid}", "cont_from_program_page"),
    ("POST", "/cont/intra/{lid}", "cont_from_program"),
    ("GET", "/cont/login", "cont_login"),
    ("POST", "/cont/login/email", "cont_login_email"),
    ("POST", "/cont/login/cod", "cont_login_code"),
    ("GET", "/auth/google", "google_start"),
    ("GET", "/auth/google/callback", "google_callback"),
    ("POST", "/cont/iesire", "cont_logout"),
    ("GET", "/cont/inregistrare", "cont_register"),
    ("POST", "/cont/inregistrare", "cont_register_submit"),
    ("POST", "/cont/inregistrare/cod", "cont_register_code"),
    ("POST", "/cont/date", "cont_edit"),
    ("POST", "/cont/nota", "cont_note"),
    ("GET", "/cont/plati/{number}.pdf", "cont_receipt"),
    ("POST", "/cont/sms/nota", "cont_sms_note"),
    ("POST", "/cont/sms/nume", "cont_sms_name"),
    ("POST", "/cont/sms/cerere.pdf", "cont_sms_form"),
    ("POST", "/cont/sms/cerere", "cont_sms_upload"),
    ("GET", "/cont/documente", "cont_documents"),
    ("GET", "/cont/documente/{doc}.pdf", "cont_document_pdf"),
    ("GET", "/cont/modele/{key}", "cont_model"),
    ("GET", "/cont/documente/{rid}/clinica.pdf", "cont_document_mine"),
    ("POST", "/cont/documente/incarca", "cont_document_upload"),
    ("GET", "/cont/clinica-noua", "cont_add_form"),
    ("POST", "/cont/clinica-noua", "cont_add_submit"),
    ("POST", "/cont/cod", "cont_code_new"),
    ("GET", "/cont/nota-comuna", "cont_group"),
    ("POST", "/cont/nota-comuna", "cont_group_submit"),
    ("POST", "/cont/nota-comuna/anuleaza", "cont_group_cancel"),
    ("GET", "/descarca", "descarca"),
    ("POST", "/v1/terms/accept", "terms_accept_api"),
    ("GET", "/cont/acceptari", "cont_terms_list"),
    ("GET", "/cont/acceptari/{aid}", "cont_terms_act"),
]


def _app():
    sys.path.insert(0, str(CLOUD))
    from app.main import app  # noqa: E402
    return app


def _routes() -> list:
    """Маршруты app, роутеры раскрыты: FastAPI 0.141 кладёт в `app.routes` подключённый роутер
    одним узлом (`_IncludedRouter`), а не копии маршрутов; обход — тот же, что у openapi."""
    from fastapi.routing import iter_route_contexts
    return [r for r in iter_route_contexts(_app().routes) if r.methods]


def _got() -> list:
    return sorted((m, r.path, r.name) for r in _routes() for m in r.methods)


def _sample(path: str) -> str:
    """Конкретный адрес по шаблону: `{x}` → `x1` (`{doc}.pdf` → `x1.pdf`)."""
    return re.sub(r"\{[^}]+\}", "x1", path)


def suite_snapshot(res: Result) -> None:
    """Тот же набор (метод, путь, имя), и ни один адрес не ловят два маршрута одного метода —
    тогда порядок подключения роутеров не меняет, кто ответит."""
    got = _got()
    want = sorted(SNAPSHOT)
    res.ok("исходники нашлись: маршрутов облака больше девяноста", len(got) > 90, repr(len(got)))
    res.check("маршрутов не стало меньше: каждый из снимка на месте", sorted(set(want) - set(got)), [])
    res.check("маршрутов не прибавилось мимо снимка", sorted(set(got) - set(want)), [])
    res.check("пара: снимок без одной строки — сторож видит пропажу",
              sorted(set(want) - set(want[1:])), [want[0]])
    routes = [(r.path, r.methods, compile_path(r.path)[0]) for r in _routes()]
    twice = []
    for path, methods, _ in routes:
        url = _sample(path)
        for m in methods:
            hit = [p for p, ms, rx in routes if m in ms and rx.match(url)]
            if hit != [path]:
                twice.append((m, url, hit))
    res.check("ни один адрес не ловят два маршрута одного метода (порядок роутеров не важен)", twice, [])


# ---------- раскладка: роутеры не знают про main ----------


def _imports_main(tree: ast.Module) -> list[int]:
    """Строки, где модуль пакета `app` импортирует `main` (любой формой)."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in ("main", "app.main") or mod.endswith(".main") \
                    or (mod in ("", "app") and any(a.name == "main" for a in node.names)):
                out.append(node.lineno)
        elif isinstance(node, ast.Import) and any(a.name in ("app.main", "main") for a in node.names):
            out.append(node.lineno)
    return out


def _trees() -> dict[str, ast.Module]:
    return {f.name: ast.parse(f.read_text(encoding="utf-8")) for f in sorted((CLOUD / "app").glob("*.py"))}


def main_importers(trees: dict[str, ast.Module]) -> list[str]:
    return [f"{name}:{line}" for name, tree in trees.items() if name != "main.py" for line in _imports_main(tree)]


def suite_layout(res: Result) -> None:
    """Ни один модуль не импортирует main: main подключает роутеры, обратный импорт замкнул бы круг."""
    trees = _trees()
    res.ok("исходники нашлись: main.py и ещё двадцать модулей", "main.py" in trees and len(trees) > 20,
           sorted(trees))
    res.check("ни один модуль cloud/app не импортирует main", main_importers(trees), [])
    for src in ("from . import main", "from .main import app", "from app import main", "import app.main"):
        bad = copy.deepcopy(trees)
        bad["views.py"].body.insert(0, ast.parse(src).body[0])
        res.ok(f"пара: «{src}» в модуле — красный", main_importers(bad) == ["views.py:1"], repr(main_importers(bad)))


_VERBS = ("get", "post", "put", "patch", "delete", "api_route")


def layout_faults(trees: dict[str, ast.Module]) -> list[str]:
    """Нарушения раскладки: маршрут в main.py (кроме /health), роутер без `router = APIRouter()`
    или не подключённый в main, роутер, импортирующий другой роутер, web.py, знающий роутеры."""
    out = []
    routers = sorted(n[:-3] for n in trees if n.startswith("routes_"))
    for node in ast.walk(trees["main.py"]):
        for d in getattr(node, "decorator_list", []):
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _VERBS
                    and not (d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value == "/health")):
                out.append(f"main.py:{d.lineno} маршрут {node.name} вне роутера")
    included = {c.args[0].value.id for c in ast.walk(trees["main.py"])
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "include_router"
                and c.args and isinstance(c.args[0], ast.Attribute) and isinstance(c.args[0].value, ast.Name)}
    for r in routers:
        if r not in included:
            out.append(f"{r}.py не подключён в main.py")
        if not any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "router" for t in n.targets)
                   for n in trees[f"{r}.py"].body):
            out.append(f"{r}.py без router = APIRouter()")
    for name, tree in trees.items():
        if not (name.startswith("routes_") or name == "web.py"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                mods = [node.module] if node.module else [a.name for a in node.names]
                bad = [m for m in mods if m.startswith("routes_")]
                if bad:
                    out.append(f"{name}:{node.lineno} импортирует {', '.join(bad)}")
    return out


def suite_routers(res: Result) -> None:
    """main.py — только сборка; каждый роутер подключён; роутеры знают web, не друг друга."""
    trees = _trees()
    routers = sorted(n for n in trees if n.startswith("routes_"))
    res.ok("исходники нашлись: шесть роутеров routes_*.py и web.py", len(routers) >= 6 and "web.py" in trees,
           repr(routers))
    res.check("main.py — только сборка; роутеры подключены и не импортируют друг друга", layout_faults(trees), [])
    bad = copy.deepcopy(trees)
    bad["main.py"].body.append(ast.parse("@app.get('/x')\ndef x():\n    pass").body[0])
    res.ok("пара: маршрут в main.py — красный", any("маршрут x" in f for f in layout_faults(bad)),
           repr(layout_faults(bad)))
    bad = copy.deepcopy(trees)
    bad["main.py"].body = [n for n in bad["main.py"].body
                           if "routes_pay.router" not in ast.unparse(n)]
    res.ok("пара: роутер не подключён — красный", "routes_pay.py не подключён в main.py" in layout_faults(bad),
           repr(layout_faults(bad)))
    bad = copy.deepcopy(trees)
    bad["routes_pay.py"].body.insert(0, ast.parse("from . import routes_cont").body[0])
    res.ok("пара: роутер импортирует роутер — красный",
           any(f.startswith("routes_pay.py:1 ") for f in layout_faults(bad)), repr(layout_faults(bad)))
