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
from ...core.layout import _ic, _shell, msg_banner

router = APIRouter()

PAGE = "/admin/migration"

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
    cells = "".join(
        f"<tr><td style='padding:3px 12px 3px 0;color:var(--muted)'>{k}</td>"
        f"<td style='padding:3px 0'><b>{v}</b></td></tr>" for k, v in rows)
    return f"<table style='border-collapse:collapse;font-size:14px'>{cells}</table>"


def _card(title: str, note: str, root: pathlib.Path, fp: dict, form: str) -> str:
    return (f"<div class='card' style='flex:1 1 320px;min-width:300px'>"
            f"<h3 style='margin:0 0 4px'>{_ic('folder')} {title}</h3>"
            f"<div style='color:var(--muted);font-size:13px;margin-bottom:10px'>"
            f"{note}</div>{_facts(root, fp)}{form}</div>")


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
        f"<form method='post' action='{PAGE}/confirm' style='margin-top:14px'>"
        f"<input type='hidden' name='choice' value='{migstate.CHOICE_OLD}'>"
        f"<label style='display:block;font-size:13px;margin-bottom:4px'>"
        f"PIN-ul fișei alese</label>"
        f"<input name='pin' type='password' inputmode='numeric' autocomplete='off'"
        f" style='width:140px' {'disabled' if left else ''}>"
        f"<button class='btn' type='submit' {'disabled' if left else ''}"
        f" style='margin-left:8px'>Aceasta este fișa reală</button>"
        f"{left}</form>")
    keep_form = (
        f"<form method='post' action='{PAGE}/confirm' style='margin-top:14px'>"
        f"<input type='hidden' name='choice' value='{migstate.CHOICE_NEW}'>"
        f"<button class='btn ghost' type='submit'>Rămân cu aceasta</button>"
        f"<div style='color:var(--muted);font-size:13px;margin-top:6px'>"
        f"Se cere dreptul de director al acestei fișe.</div></form>")

    body = f"""{msg_banner(msg)}
<div class='card' style='margin-bottom:14px'>
<p style='margin:0 0 8px'>Pe acest calculator sunt <b>două fișe de pacienți</b>.
Programul lucrează acum în cea de jos, iar lângă ea a fost găsită încă una.
Care dintre ele este cea reală decide un om — programul nu alege singur, nici
după dată, nici după mărime.</p>
<p style='margin:0;color:var(--muted);font-size:14px'>{_ic('info')} Nicio fișă
nu este ștearsă și niciuna nu este redenumită. Numărul de pacienți nu este
afișat: pentru a-l afla ar trebui deschisă baza, iar până la alegere baza nu se
deschide.</p></div>
<div style='display:flex;gap:14px;flex-wrap:wrap'>
{_card("Instalarea găsită", "Fișa de lângă program", src, src_fp, pin_form)}
{_card("Aici lucrați acum", "Fișa deschisă de program", dst, dst_fp, keep_form)}
</div>"""
    return _shell(body, "Două fișe de pacienți", active="migration")


def _closed_note() -> str:
    """Сколько секунд подтверждение закрыто. ⭐ Показывается ФАКТОМ на странице,
    а не текстом баннера: у баннеров текст постоянный, а число тут меняется."""
    left = source_pin_closed_for()
    if not left:
        return ""
    return (f"<div style='color:var(--red);font-size:13px;margin-top:6px'>"
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
