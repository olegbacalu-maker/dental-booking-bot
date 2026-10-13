"""Экран раздвоения: на машине ДВЕ картотеки, и какая настоящая — решает человек.

Контракт — `docs/dentpilot-2/split-contract.md`. ⭐ Экран здесь только ПОКАЗЫВАЕТ
и СПРАШИВАЕТ: проверку PIN делает `core.auth.verify_source_pin`, запись ответа —
`migstate`, а решение о раздвоении принял `relocate` ещё в лаунчере. Логики
переезда в этом модуле нет ни строки, и это не аккуратность: страница, знающая,
как устроен `auth.json`, станет вторым местом, где живёт правда о PIN.

⛔ **Это НЕ стена.** Экран восстановления перекрывает весь `/admin`, потому что
показывать нечего — база не открывается. Здесь показывать ЕСТЬ что: в назначении
лежит рабочая картотека, клиника в ней уже принимает. Стена закрыла бы клинику
на день ради конфликта, который терпит до вечера. Отсюда форма: баннер директору
(`layout._split_banner`) + вот эта отдельная страница.

⛔ **Ни один корень не удаляется и не переименовывается** — ни до выбора, ни
после него, ни «подчистить за собой». Это не работа P2 вовсе.

⭐ **Кто чем подтверждает — по тому, чем в выбранном корне можно подтвердить.**
Вопрос один и тот же обоим ответам: «докажи, что ты из той клиники, чью картотеку
берёшь». Механизмы разные, потому что разное доступно:

| Ответ | Чем подтверждается | Почему так |
|---|---|---|
| старый корень | PIN САМОГО старого корня | в него нельзя войти — программа идёт не там; остаётся чтение его `auth.json` |
| тот, в котором работаю | обычное право директора | в нём человек уже вошёл, и второй раз спрашивать тот же PIN — трение без смысла |

⛔ Спросить тем же способом про НАЗНАЧЕНИЕ нельзя, и отказ там не случайный:
счётчик попыток живёт в назначении, то есть внутри проверяемого корня, и оракул
отвергает такой вызов нарочно. Это не обход правила, а признак того, что вопрос
к своему корню задаётся другим способом.

⚠️ Отсюда же узкий импорт: страница зовёт `confirm_source` и
`source_pin_closed_for` — и не знает ни про `auth.json`, ни про хеши, ни про
счётчик и его лестницу. Страница, повторившая любую из этих деталей, стала бы
вторым местом, где живёт правда о PIN, и разошлась бы с первым молча.
"""
from __future__ import annotations

import datetime as dt
import html
import pathlib

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import engine as eng
from ... import install_info, migstate, paths, relocate
from ...core.auth import (PERM_SETTINGS, SRC_OK, confirm_source, require,
                          same_origin_post, source_pin_closed_for)
from ...core.layout import _ic, msg_state, standalone

router = APIRouter()

PAGE = "/admin/migration"

# ⭐ Своя вёрстка на `standalone()`, без каркаса журнала (шаг 6 снятия старого
# интерфейса, 13.10, решение Олега 12.10): экран спрашивает БЕЗ входа и до
# выбора, а React-оболочке здесь рисовать нечего. ⚠️ panel.css не
# подключается, как у входа и лицензии: цвет и шрифт клиники приезжают
# заполнителями `standalone()` (`__ACCENT__`, `__FONTS__`, `__FAMILY__`).
# Ответ на отказ — строкой состояния `.state` (`layout.msg_state`): плавающей
# плашке каркаса нужны его стили и скрипт.
TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — două fișe de pacienți</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__BG__;margin:0;color:#162033;
      padding:28px 16px;box-sizing:border-box;min-height:100vh}
 .wrap{max-width:980px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
 h1{font-size:21px;margin:0;font-weight:600;letter-spacing:-.02em;color:__ACCENT_D__;
    display:flex;align-items:center;gap:8px}
 .box{background:#fff;padding:20px 22px;border-radius:16px;border:1px solid #E7EDF5;
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10)}
 .pair{display:flex;gap:14px;flex-wrap:wrap}
 .pair .box{flex:1 1 320px;min-width:280px}
 h3{font-size:16px;margin:0 0 4px;font-weight:600;display:flex;align-items:center;gap:6px}
 p{margin:0;line-height:1.55;font-size:14.5px}
 .muted{color:#5A6875;font-size:13.5px}
 .lead{margin-bottom:8px}
 table{border-collapse:collapse;font-size:14px}
 td{padding:3px 12px 3px 0;vertical-align:top}
 td.k{color:#5A6875}
 form{margin-top:14px}
 label{display:block;font-size:13px;margin-bottom:4px;color:#5A6875}
 input{font-family:inherit;font-size:14px;padding:9px 12px;border:1px solid #E7EDF5;
       border-radius:10px;width:140px;outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{font-family:inherit;background:__ACCENT__;color:__ON__;border:none;border-radius:10px;
        height:40px;padding:0 16px;font-size:14px;font-weight:600;cursor:pointer;margin-left:8px}
 button.ghost{background:#fff;color:__ACCENT_D__;border:1px solid #E7EDF5;margin-left:0}
 button:disabled{opacity:.5;cursor:default}
 .state{padding:10px 12px;border-radius:10px;font-size:14px;line-height:1.5}
 .state.ok{background:#ECFDF5;color:#065F46}.state.warn{background:#FFFBEB;color:#B45309}
 .state.err{background:#FEF2F2;color:#B91C1C}
 .late{color:#B91C1C;font-size:13px;margin-top:6px}
 a{color:__ACCENT_D__}
</style></head><body>
<div class="wrap">
<h1>__ICON__ Două fișe de pacienți</h1>
__MSG__
__BODY__
<p class="muted"><a href="/admin">Înapoi la registru</a></p>
</div></body></html>"""

# Исход оракула → код баннера. ⛔ Таблицей, а не цепочкой `if` по месту: трём
# остановкам контракт велит звучать ПО-РАЗНОМУ («PIN не ставили» и «файл
# повреждён» ведут человека в разные стороны), и цепочка сравнений однажды
# сведёт их к общему «не удалось» — ровно тот тупик, который уже чинили на
# экране восстановления.
OUTCOME_MSG = {
    "ok": "mig_ok",
    "bad": "mig_bad",
    "locked": "mig_lock",
    "no-auth": "mig_noauth",
    "broken": "mig_broken",
    "no-users": "mig_nousers",
}


def _mb(n: int) -> str:
    """Размер человеку. ⚠️ Знака «≈» здесь быть не может: он вне вшитого
    подмножества Inter и ушёл бы в системный шрифт (прайор карты про знаки)."""
    if n <= 0:
        return "0 MB"
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def _when(ts: float | None) -> str:
    """Дата правки по КИШИНЁВУ. Наивное значение показало бы час машины, а
    директор сверяет его с рабочим днём клиники."""
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(ts, eng.TZ).strftime("%d.%m.%Y %H:%M")


def _install_line(root: pathlib.Path) -> str:
    """Кто назван в `install.json` этого корня.

    ⚠️ Три исхода, и «битый» не равен «нет файла»: отсутствие законно (запуск
    из исходников, песочница), а битый файл означает, что установщик работал, а
    что он решил — неизвестно. Показать второе как первое значит соврать про
    режим и канал.
    """
    try:
        info = install_info.read(root)
    except install_info.InstallInfoError:
        return "deteriorat"
    if info is None:
        return "nu este"
    return f"{info['mode']} · {info['channel']}"


def _facts(root: pathlib.Path, fp: dict) -> str:
    """Карточка одного корня. ⛔ Числа пациентов здесь НЕТ и быть не может:
    счёт живёт внутри базы, а базу этот слой не открывает никаким драйвером.
    ⚠️ И формулировки опираются только на показанное: «тут больше данных» по
    размеру файла — ложь, пустая база с горячим `-wal` бывает крупнее живой.
    """
    if fp["encrypted"] is None:
        crypt = "nu există"
    elif fp["encrypted"]:
        crypt = "criptată"
    else:
        crypt = "necriptată"
    rows = [
        ("Locul", html.escape(str(root))),
        ("Fișa de pacienți", _mb(fp["db_size"]) if fp["has_db"] else "lipsește"),
        ("Ultima modificare", _when(fp["db_mtime"])),
        ("Starea criptării", crypt),
        ("Jurnal nescris (-wal)", _mb(fp["wal"]) if fp["wal"] else "gol"),
        ("Semne găsite", html.escape(", ".join(fp["markers"]) or "niciunul")),
        ("Instalare (install.json)", html.escape(_install_line(root))),
    ]
    cells = "".join(f"<tr><td class='k'>{k}</td><td><b>{v}</b></td></tr>"
                    for k, v in rows)
    return f"<table>{cells}</table>"


def _card(title: str, note: str, root: pathlib.Path, fp: dict, form: str) -> str:
    return (f"<div class='box'><h3>{_ic('folder')} {title}</h3>"
            f"<p class='muted' style='margin-bottom:10px'>{note}</p>"
            f"{_facts(root, fp)}{form}</div>")


@router.get(PAGE, response_class=HTMLResponse)
async def migration_page(request: Request, msg: str = ""):
    """Две картотеки рядом, фактами. Вход не требуется — до выбора не нужно ни
    секретов, ни открытия базы, и спросить человека можно без них. Секрет
    спрашивается ровно там, где решение начинает что-то менять."""
    src = relocate.split_pending()
    if src is None:
        # ⚠️ Отвечено или раздвоения нет — страницы не существует. Не 404:
        # ссылка могла остаться в открытой вкладке у того, кто уже ответил.
        return RedirectResponse("/admin", 303)
    dst = paths.data_root()
    src_fp, dst_fp = relocate.fingerprint(src), relocate.fingerprint(dst)
    left = _closed_note()

    pin_form = (
        f"<form method='post' action='{PAGE}/confirm'>"
        f"<input type='hidden' name='choice' value='{migstate.CHOICE_OLD}'>"
        f"<label for='m-pin'>PIN-ul fișei alese</label>"
        f"<input id='m-pin' name='pin' type='password' inputmode='numeric' autocomplete='off'"
        f" {'disabled' if left else ''}>"
        f"<button type='submit' {'disabled' if left else ''}>Aceasta este fișa reală</button>"
        f"{left}</form>")
    keep_form = (
        f"<form method='post' action='{PAGE}/confirm'>"
        f"<input type='hidden' name='choice' value='{migstate.CHOICE_NEW}'>"
        f"<button class='ghost' type='submit'>Rămân cu aceasta</button>"
        f"<p class='muted' style='margin-top:6px'>"
        f"Se cere dreptul de director al acestei fișe.</p></form>")

    body = f"""<div class='box'>
<p class='lead'>Pe acest calculator sunt <b>două fișe de pacienți</b>.
Programul lucrează acum în cea de jos, iar lângă ea a fost găsită încă una.
Care dintre ele este cea reală decide un om — programul nu alege singur, nici
după dată, nici după mărime.</p>
<p class='muted'>{_ic('info')} Nicio fișă
nu este ștearsă și niciuna nu este redenumită. Numărul de pacienți nu este
afișat: pentru a-l afla ar trebui deschisă baza, iar până la alegere baza nu se
deschide.</p></div>
<div class='pair'>
{_card("Instalarea găsită", "Fișa de lângă program", src, src_fp, pin_form)}
{_card("Aici lucrați acum", "Fișa deschisă de program", dst, dst_fp, keep_form)}
</div>"""
    return (standalone(TMPL).replace("__ICON__", _ic("folder"))
            .replace("__MSG__", msg_state(msg)).replace("__BODY__", body))


def _closed_note() -> str:
    """Сколько секунд подтверждение закрыто. ⭐ Показывается ФАКТОМ на странице,
    а не текстом баннера: у баннеров текст постоянный, а число тут меняется."""
    left = source_pin_closed_for()
    if not left:
        return ""
    return (f"<div class='late'>"
            f"Prea multe încercări. Mai așteptați {left} s.</div>")


@router.post(PAGE + "/confirm")
async def migration_confirm(request: Request, choice: str = Form(""),
                            pin: str = Form("")):
    """Ответ человека. ⛔ Пишет ровно одно: `migration.json`. Ни одного байта в
    источник, ни одного скопированного файла — копирование это следующий шаг."""
    # ⚠️ Форма живёт ДО куки (страница открыта без входа), поэтому SameSite её
    # не закрывает и Origin проверяется явно — как у setup, login и recover.
    if not same_origin_post(request):
        return Response(status_code=403)
    src = relocate.split_pending()
    if src is None:
        return RedirectResponse("/admin", 303)
    dst = paths.data_root()
    at = dt.datetime.now(eng.TZ).isoformat(timespec="seconds")

    if choice == migstate.CHOICE_NEW:
        # Свой корень подтверждается своим же правом: человек в нём уже вошёл.
        if (deny := require(request, PERM_SETTINGS)) is not None:
            return deny
        migstate.record_choice(dst, old=str(src), new=str(dst),
                               choice=migstate.CHOICE_NEW, at=at)
        return RedirectResponse("/admin?msg=mig_kept", 303)

    if choice != migstate.CHOICE_OLD:
        return RedirectResponse(f"{PAGE}?msg=mig_bad", 303)

    verdict = await confirm_source(src, pin)
    code = OUTCOME_MSG.get(verdict["outcome"], "mig_bad")
    if verdict["outcome"] != SRC_OK:
        return RedirectResponse(f"{PAGE}?msg={code}", 303)
    migstate.record_choice(dst, old=str(src), new=str(dst),
                           choice=migstate.CHOICE_OLD, at=at)
    return RedirectResponse(f"/admin?msg={code}", 303)
