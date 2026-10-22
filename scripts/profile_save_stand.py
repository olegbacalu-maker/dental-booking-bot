# -*- coding: utf-8 -*-
"""«Salvează profilul» не прыгает — стенд фиши › Date pacient (22.10).

    python scripts\\profile_save_stand.py          оба окна, оба пути к форме
    python scripts\\profile_save_stand.py --pair   и пара: тот же прогон с
                                                  выключенным window.scrollBy
                                                  обязан краснеть

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. Кнопка «Salvează profilul» стоит внизу длинной формы, человек к ней
прокручен. Удача схлопывает форму — и всё, что ПОД формой (кнопки архива,
выгрузки, стирания), уезжает вверх на её высоту, а низ карточки пустеет
(Олег 22.10: «когда нажимаешь после изменений на сохранение, страница
прыгает»). Замер до правки (main f384785): верх карточки почти не двигается
(1920×1000: −196→−181 px, 1366×768: −446→−446), документ короче на 252 и
625 px — прыжок не в прокрутке, а в содержимом под взглядом. jsdom
прямоугольников не знает, поэтому сам сдвиг видит только браузер: здесь —
настоящая форма, настоящая прокрутка, настоящий щелчок через CDP.

Правило (как якорь прокрутки браузера): после удачи НИЗ карточки профиля
стоит там же, где стоял до схлопывания, — строки с результатом занимают
место формы, «Editează profilul» встаёт туда, где была «Salvează». Прокрутка
уменьшается на высоту формы; когда наверху нечего открыть (прокрутка
упёрлась в 0), остаток сдвига неизбежен. И это один кадр, без
промежуточного (компенсация — в useLayoutEffect, не в useEffect).

Утверждения на каждое окно (1920×1000 — у Олега; 1366×768 — тесный ноутбук,
одна колонка) и каждый путь к форме («Editează profilul» на вкладке,
«Salvează» едва показалась снизу; `?edit=1` из предпросмотра списка,
«Salvează» посреди окна):
  1. сервер принял: плашка «Fișa pacientului a fost actualizată», форма
     скрыта, в карточке — новое значение;
  2. низ карточки после удачи — на месте (±1 px);
  3. ни одного кадра, где форма уже скрыта, а низ карточки ещё не на месте.
Повторный щелчок по «Editează profilul» (закрыть форму без записи) только
печатается: компенсации там нет намеренно — человек смотрит на эту кнопку, и
сдвиг её вниз на высоту формы был бы хуже.

⛔ Зелёный стенд сам по себе ничего не доказывает. Доказательство — ПАРА
(`--pair`): тот же прогон с `window.scrollBy = () => {}` в браузере обязан
дать красное по утверждению 2, иначе стенд не видит того, ради чего написан.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import Client, Server, new_patient  # noqa: E402
from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402

# ⛔ Свой порт отладки: 9337–9347, 9352/9353, 9355, 9360/9361 заняты соседними
# стендами, и запуск на занятом МОЛЧА подключается к чужому браузеру.
PORT = 9349
PROFILE_NAME = "dp-edge-profile-save"
SIZES = ((1920, 1000), (1366, 768))
NAME = "Proba Salvare Profil"
PHONE = "069555123"
# Длинный профиль: заметка в четыре строки, адрес на всю ширину — карточка
# высокая, форма под ней длиннее окна на любом из двух размеров.
PROFILE = {
    "name": NAME, "phone": PHONE, "birth_date": "1984-05-17", "gender": "f",
    "idnp": "2004005006007", "email": "proba.salvare@example.md",
    "address": "mun. Chișinău, bd. Ștefan cel Mare și Sfânt 124, bl. 3, ap. 57",
    "insurance": "CNAM activă, polița 0123456789", "primary_doctor": "Dr. Activ Doi",
    "file_no": "D-2026-117",
    "notes": ("Pacientă anxioasă, preferă programări dimineața. Alergie la latex "
              "(mănuși fără latex). Plătește cu cardul, cere bon fiscal. "
              "Fiul ei este pacient la Dr. Activ Trei. Vorbește română și rusă."),
    "lang": "ro",
}
TOAST = "Fișa pacientului a fost actualizată"

MEASURE = r"""(() => {
  const r = (el) => el ? el.getBoundingClientRect() : null;
  const card = document.querySelector('.pv2-main .fcard');
  const form = document.querySelector('.dp-pedit');
  const bar = document.querySelector('.main .top');
  const hero = document.querySelector('.hero');
  const btns = [...document.querySelectorAll('.dp-pedit button')];
  const save = btns.length ? btns[btns.length - 1] : null;
  const after = document.querySelector('.pv2-main .fcard .dp-pc-sec');
  const texts = [...document.querySelectorAll('.pv2-main .fcard .frow .v, .pv2-main .fcard .dp-notes')]
    .map((e) => e.textContent.trim());
  return JSON.stringify({
    y: Math.round(window.scrollY), innerH: window.innerHeight,
    docH: document.documentElement.scrollHeight,
    bar: bar ? Math.round(r(bar).bottom) : 0,
    heroH: hero ? Math.round(r(hero).height) : 0,
    cardTop: card ? Math.round(r(card).top) : null,
    cardBottom: card ? Math.round(r(card).bottom) : null,
    cardH: card ? Math.round(r(card).height) : null,
    afterTop: after ? Math.round(r(after).top) : null,
    formOpen: !!form && getComputedStyle(form).display !== 'none',
    formH: form && getComputedStyle(form).display !== 'none' ? Math.round(r(form).height) : 0,
    saveTop: save ? Math.round(r(save).top) : null,
    toast: (document.querySelector('.toastbox') || {}).textContent || '',
    texts,
  });
})()"""

# Кадры от щелчка до покоя: прокрутка, высота документа, низ карточки, форма.
FRAMES_START = r"""(() => {
  window.__fr = [];
  const t0 = performance.now();
  (function step() {
    const c = document.querySelector('.pv2-main .fcard'), f = document.querySelector('.dp-pedit');
    window.__fr.push([Math.round(performance.now() - t0), Math.round(window.scrollY),
      document.documentElement.scrollHeight, c ? Math.round(c.getBoundingClientRect().bottom) : null,
      f ? (getComputedStyle(f).display !== 'none' ? 'open' : 'closed') : null]);
    if (window.__fr.length < 600) requestAnimationFrame(step);
  })();
  return 1;
})()"""

BY_TEXT = ("[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === %s && !b.disabled)")
FORM_IS = "(() => { const f = document.querySelector('.dp-pedit'); return !!f && getComputedStyle(f).display === %s })()"


class CardPage(Page):
    """Та же страница, но исключение JS называет себя (у `Page.js` — одно «Uncaught»)."""

    def js(self, expr):
        r = self.cdp.cmd("Runtime.evaluate", returnByValue=True, expression=expr)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError(d.get("exception", {}).get("description") or d.get("text"))
        return r["result"].get("value")


def port_is_free() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
    except Exception:
        return True
    return False


def kill_profile() -> None:
    """Гасит ВЕСЬ свой Edge по имени профиля: `proc.kill()` снимает только
    родителя, дети остаются на порту, и следующий запуск цепляется к ним."""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                    f"Where-Object {{ $_.CommandLine -like '*{PROFILE_NAME}*' }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                   capture_output=True)


def prepare(dir_: pathlib.Path) -> None:
    """Профиль клиники как у клиники по умолчанию (пин наборов снимается)."""
    p = dir_ / "clinic.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def seed(c: Client) -> int:
    pid = new_patient(c, NAME, PHONE)
    r = c.post_json(f"/api/patients/{pid}/profile", PROFILE)
    if r.msg != "ok_card":
        raise SystemExit(f"профиль не засеялся: {r.msg} {r.body[:200]}")
    return pid


def wait_js(page: Page, expr: str, what: str, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if page.js(expr):
            return
        time.sleep(0.1)
    m = measure(page)
    shot = pathlib.Path(os.environ["TEMP"]) / "dp-profile-save-timeout.png"
    page.png(str(shot), full=False)
    raise SystemExit(f"не дождался: {what}\n  состояние: форма {'раскрыта' if m['formOpen'] else 'скрыта'}, "
                     f"«Salvează» top={m['saveTop']}, плашка {m['toast']!r}, кадр — {shot}")


def measure(page: Page) -> dict:
    return json.loads(page.js(MEASURE))


def open_card(page: Page, pid: int, query: str) -> None:
    page.go(f"/admin/patient/{pid}{query}")
    wait_js(page, f"!!document.querySelector('h2') && document.querySelector('h2').textContent.includes({json.dumps(NAME)})"
                  " && !!document.querySelector('.pv2-main .fcard')", "фиша на вкладке Date pacient")
    time.sleep(0.3)


def click_text(page: Page, text: str) -> None:
    finder = BY_TEXT % json.dumps(text)
    page.js(f"(() => {{ const b = {finder}; if (!b) throw new Error('нет кнопки {text}');"
            " b.scrollIntoView({block: 'center'}); return 1 })()")
    time.sleep(0.2)
    page.click(finder)


def type_into(page: Page, label: str, text: str) -> None:
    sel = f'.dp-pedit [aria-label="{label}"]'   # кодируется ОДИН раз, ниже json.dumps
    page.js(f"(() => {{ const el = document.querySelector({json.dumps(sel)}); el.focus({{preventScroll: true}});"
            " el.setSelectionRange(el.value.length, el.value.length); return 1 })()")
    page.cdp.cmd("Input.insertText", text=text)
    time.sleep(0.2)


def expected_bottom(before: dict, after: dict) -> int:
    """Где обязан стоять низ карточки после удачи: там же, где был; если для
    этого прокрутке пришлось бы уйти выше 0 — на своём месте в документе при
    прокрутке 0 (наверху открывать больше нечего)."""
    doc_bottom = after["cardBottom"] + after["y"]
    return before["cardBottom"] if doc_bottom >= before["cardBottom"] else doc_bottom


def save_and_measure(page: Page, label: str, field: str, text: str, scroll: str) -> tuple[dict, dict, list]:
    """Форма уже раскрыта. Прокрутка к кнопке, правка поля, щелчок, замер."""
    page.js(scroll)
    time.sleep(0.3)
    type_into(page, field, text)
    before = measure(page)
    if not before["formOpen"]:
        raise SystemExit(f"{label}: форма не раскрыта — стенд мерил не то")
    if before["saveTop"] is None or not (0 <= before["saveTop"] < before["innerH"] - 20):
        raise SystemExit(f"{label}: «Salvează» вне окна (top={before['saveTop']}) — щелчок не дойдёт")
    page.js(FRAMES_START)
    page.click(BY_TEXT % json.dumps("Salvează profilul"))
    wait_js(page, FORM_IS % "'none'", f"{label}: форма скрылась после удачи", timeout=8)
    time.sleep(0.8)
    after = measure(page)
    frames = json.loads(page.js("JSON.stringify(window.__fr)"))
    return before, after, frames


def verdict(before: dict, after: dict, frames: list, value: str) -> list[str]:
    bad = []
    if TOAST not in after["toast"]:
        bad.append(f"плашки «{TOAST}» нет: {after['toast']!r}")
    if after["formOpen"]:
        bad.append("форма осталась раскрытой")
    if not any(value in v for v in after["texts"]):
        bad.append(f"в карточке нет нового значения {value!r}")
    want = expected_bottom(before, after)
    if after["cardBottom"] is None or abs(after["cardBottom"] - want) > 1:
        bad.append(f"низ карточки после удачи {after['cardBottom']}, а должен {want} "
                   f"(до: {before['cardBottom']}; прокрутка {before['y']}→{after['y']}, "
                   f"документ {before['docH']}→{after['docH']}, форма {before['formH']} px)")
    # кадры после схлопывания: первый же обязан стоять на месте
    closed = [f for f in frames if f[4] == "closed"]
    if not closed:
        bad.append("кадры: схлопывания формы не увидел")
    else:
        off = [f for f in closed if f[3] is None or abs(f[3] - want) > 1]
        if off:
            bad.append(f"кадры: {len(off)} из {len(closed)} после схлопывания не на месте, первый — "
                       f"t={off[0][0]} мс, низ карточки {off[0][3]}, прокрутка {off[0][1]}")
    return bad


def line(ok: bool, label: str, size: tuple[int, int], path: str, b: dict, a: dict) -> str:
    return (f"{'OK ' if ok else 'RED'} {label} {size[0]}×{size[1]} {path:<10} низ карточки {b['cardBottom']}→{a['cardBottom']}, "
            f"верх {b['cardTop']}→{a['cardTop']}, прокрутка {b['y']}→{a['y']}, документ {b['docH']}→{a['docH']}, "
            f"форма {b['formH']} px, шапка {b['heroH']}→{a['heroH']}")


def toggle_info(page: Page, pid: int, size: tuple[int, int]) -> str:
    """Повторный щелчок «Editează profilul» — только цифры, без вердикта."""
    open_card(page, pid, "?tab=date")
    click_text(page, "Editează profilul")
    wait_js(page, FORM_IS % "'flex'", "форма раскрылась")
    page.js("window.scrollBy(0, 240); 1")
    time.sleep(0.3)
    before = measure(page)
    page.click(BY_TEXT % json.dumps("Editează profilul"))
    time.sleep(0.6)
    after = measure(page)
    return (f"info {size[0]}×{size[1]} повторный «Editează» (закрыть): низ карточки {before['cardBottom']}→{after['cardBottom']}, "
            f"верх {before['cardTop']}→{after['cardTop']}, прокрутка {before['y']}→{after['y']}, "
            f"документ {before['docH']}→{after['docH']}")


def run(label: str, pair: bool) -> list[str]:
    if not port_is_free():
        raise SystemExit(f"порт {PORT} занят чужим браузером — стенд не запускается")
    s1 = Server(keep_dir=True)
    prepare(s1.dir)
    profile = os.path.join(os.environ["TEMP"], PROFILE_NAME)
    problems: list[str] = []
    proc = None
    try:
        with s1:
            c = Client(s1.url).login()
            pid = seed(c)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
            cdp.cmd("Network.setCookie", name="admin_auth", value=login_cookie(s1.url), url=s1.url + "/")
            if pair:
                cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source="window.scrollBy = () => {};")
            page = CardPage(cdp, s1.url)
            n = 0
            for size in SIZES:
                page.size(*size)
                # путь 1: «Editează profilul» на вкладке; «Salvează» едва показалась снизу
                n += 1
                open_card(page, pid, "?tab=date")
                click_text(page, "Editează profilul")
                wait_js(page, FORM_IS % "'flex'", "форма раскрылась")
                value = f" bis {n}"
                b, a, fr = save_and_measure(
                    page, f"{size} editează", "Adresă", value,
                    "(() => { const s = [...document.querySelectorAll('.dp-pedit button')].pop();"
                    " window.scrollTo(0, s.getBoundingClientRect().bottom + window.scrollY - window.innerHeight + 24); return 1 })()")
                bad = verdict(b, a, fr, value.strip())
                print(line(not bad, label, size, "«Editează»", b, a))
                for x in bad:
                    print(f"    ✗ {x}")
                problems += [f"{size[0]}×{size[1]} editează: {x}" for x in bad]
                # путь 2: ?edit=1 из предпросмотра списка; «Salvează» посреди окна
                n += 1
                open_card(page, pid, "?tab=date&edit=1")
                value = f" bis {n}"
                b, a, fr = save_and_measure(
                    page, f"{size} edit=1", "Notițe interne", value,
                    "(() => { [...document.querySelectorAll('.dp-pedit button')].pop().scrollIntoView({block: 'center'}); return 1 })()")
                bad = verdict(b, a, fr, value.strip())
                print(line(not bad, label, size, "?edit=1", b, a))
                for x in bad:
                    print(f"    ✗ {x}")
                problems += [f"{size[0]}×{size[1]} edit=1: {x}" for x in bad]
                if not pair:
                    print("    " + toggle_info(page, pid, size))
    finally:
        if proc:
            proc.kill()
        kill_profile()
        time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)
        s1.drop()
    return problems


def main(argv: list[str]) -> int:
    problems = run("дерево", pair=False)
    print(f"\n{'0 расхождений' if not problems else f'{len(problems)} расхождений'}: "
          f"после «Salvează profilul» низ карточки стоит на месте" + ("" if not problems else " — НЕТ"))
    if "--pair" not in argv:
        return 1 if problems else 0
    broken = run("пара", pair=True)
    seen = bool(broken)
    print(f"пара: без scrollBy прыжок {'виден (красное)' if seen else 'НЕ ВИДЕН — стенд слеп'}")
    return 1 if problems or not seen else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
