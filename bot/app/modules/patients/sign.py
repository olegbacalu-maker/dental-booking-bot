"""Подпись бланка на экране (09.11.2026, просьба клиники; план —
`review\\semnare-pe-ecran-2026-11-09.md`, контракт —
`side-session-notes\\2026-11-09\\sign-contract.md`).

Три бланка «Documente» (`SIGNABLE`) можно подписать пальцем, стилусом или
мышью вместо «Tipărește» + «Încarcă semnat» (бумажный путь остаётся рядом).
Правовую силу подписи на экране решает клиника (Олег 09.11), мы её не
описываем.

⭐ Результат подписи — PDF-ДОКУМЕНТ в категории бланка, тем же путём, что
загрузка скана (`routes._store_bytes`). Флага «подписан» в базе нет и не
заводится (принцип `acord.py`): статус «semnat», «stale» согласия к плану и
полоса в плане считаются от последнего документа категории
(`card.forms_view`) — так же, как от скана.

⛔ Подпись — только КАРТИНКА. Нажим, скорость, время штрихов не принимаются
и не хранятся: это биометрия по закону 195. Тело разбирается по белому
списку полей; PNG перекодируется сервером (чужие куски файла не доезжают до
листа), ⛔ SVG не принимается никогда (XML со скриптами — прайор логотипа).

Подписанный файл не меняется: изменился план — подписывается новый лист, как
и с бумагой. Отпечаток SHA-256 файла пишется в летопись фиши (она же журнал
доступа: кто вошёл — подпись строки, кто подписал — в тексте).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import re
import struct
from datetime import datetime

from ... import db
from ... import engine as eng
from ...core import pdf, theme
from . import acord as pacord
from . import anamneza as panam
from . import card as pcard
from . import plan_acord as pplan

SIGNABLE = pcard.SIGNABLE
# у согласия к плану расписываются ОБА: пациент «понял», врач «объяснил»
# (ст. 13(2) Legea 263/2005, см. plan_acord.py)
NEEDS_DOCTOR = frozenset({"acord_plan"})
SIGNERS = ("pacient", "reprezentant")

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
# потолки картинки подписи: холст планшета 1280 px с ретиной — до ~2600 px;
# больше — не подпись. Размер — до разбора Pillow (бомба распаковки).
_SIG_MAX_BYTES = 600 * 1024
_SIG_MAX_W, _SIG_MAX_H = 4000, 2000
_SIG_MIN_W, _SIG_MIN_H = 60, 30
# «пустой холст»: чернила должны занять хотя бы столько пикселей по большей
# стороне — точка от случайного касания подписью не считается
_INK_MIN_SPAN = 12
_NAME_MAX = 80


def _form(key: str) -> tuple | None:
    return next((f for f in pcard.FORMS if f[0] == key), None)


def png_clean(uri) -> str | None:
    """data:image/png;base64 → тот же рисунок, перекодированный сервером, или
    None (не PNG, не тот размер, пустой холст). Перекодировка снимает всё,
    кроме пикселей: текстовые куски PNG до листа не доезжают."""
    if not isinstance(uri, str):
        return None
    m = re.fullmatch(r"data:image/png;base64,([A-Za-z0-9+/=\s]+)", uri.strip())
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(1), validate=False)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > _SIG_MAX_BYTES or not raw.startswith(_PNG_SIG) or raw[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", raw[16:24])
    if not (_SIG_MIN_W <= w <= _SIG_MAX_W and _SIG_MIN_H <= h <= _SIG_MAX_H):
        return None
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        im = im.convert("RGBA")
    except Exception:                                   # noqa: BLE001 — битый PNG
        return None
    # чернила = непрозрачное и не белое: холст бывает и прозрачным, и белым
    white = Image.new("RGBA", im.size, (255, 255, 255, 255))
    ink = Image.alpha_composite(white, im).convert("L").point(lambda v: 255 if v < 200 else 0)
    box = ink.getbbox()
    if not box or max(box[2] - box[0], box[3] - box[1]) < _INK_MIN_SPAN:
        return None
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def parse(key: str, body: dict | None) -> tuple[str, str, dict | None]:
    """Тело запроса → (код отказа, поле, sign). Белый список полей: всё
    прочее (нажим, штрихи, время) не читается вовсе."""
    body = body or {}
    signer = str(body.get("signer") or "")
    if signer not in SIGNERS:
        return "bad_sign", "signer", None
    name = re.sub(r"\s+", " ", str(body.get("signer_name") or "")).strip()[:_NAME_MAX]
    if signer == "reprezentant" and len(name) < 2:
        return "bad_sign_name", "signer_name", None
    patient = png_clean(body.get("sig_patient"))
    if patient is None:
        return "bad_sign", "sig_patient", None
    doctor = None
    if key in NEEDS_DOCTOR:
        doctor = png_clean(body.get("sig_doctor"))
        if doctor is None:
            return "bad_sign", "sig_doctor", None
    cons = {}
    if key == "acord195":
        raw = body.get("consents") if isinstance(body.get("consents"), dict) else {}
        # True/False — ответ на экране; всё прочее (нет, null) — не отвечено
        cons = {k: raw.get(k) if isinstance(raw.get(k), bool) else None
                for k in ("mkt", "photo")}
    return "", "", {"signer": signer, "name": name if signer == "reprezentant" else "",
                    "patient": patient, "doctor": doctor, "consents": cons}


def precheck(key: str, plan: list, anam: dict | None) -> str:
    """Код отказа «нечего подписывать» или пусто."""
    if pcard.can_sign(key, plan, anam):
        return ""
    return "bad_sign_plan" if key == "acord_plan" else "bad_sign_anam"


async def sheet(p: dict, key: str, lang: str, sign: dict) -> str:
    """Лист бланка в режиме подписи. `sign={}` — предпросмотр окна подписи
    (ответы анкеты на месте, мест подписи ещё нет)."""
    pid = p["id"]
    if key == "acord195":
        return pacord.render(p, lang, "", sign=sign)
    if key == "acord_plan":
        plan = await db.plan_items(pid)
        recs = await db.patient_visit_records(pid)
        diag = next((r["diagnostic"].strip() for r in recs
                     if (r.get("diagnostic") or "").strip()), "")
        return pplan.render(p, plan, diag, lang, "", sign=sign)
    return panam.render_form(p, lang, "", sign=sign, anam=await db.anamneza(pid))


def _inline_logo(page: str) -> str:
    """Логотип клиники — внутрь листа: Edge печатает file:// и в движок не
    ходит. Файл логотипа принимается только PNG/JPEG по сигнатуре (theme)."""
    url, path = theme.logo_url(), theme.logo_path()
    if not url or path is None:
        return page
    try:
        data = path.read_bytes()
    except OSError:
        return page.replace(f"src='{url}'", "src=''")
    uri = f"data:{theme.logo_mime(path.name)};base64,{base64.b64encode(data).decode('ascii')}"
    return page.replace(f"src='{url}'", f"src='{uri}'")


def file_name(key: str, p: dict) -> str:
    title = (_form(key) or (key, key))[1]
    stamp = datetime.now(eng.TZ).strftime("%d.%m.%Y")
    base = re.sub(r'[\\/:*?"<>|]+', " ", f"{title} - {p.get('name') or p['id']} - {stamp}").strip()
    return f"{base[:100]} - semnat.pdf"


def event_text(key: str, sign: dict, sha: str) -> str:
    """Строка летописи: что подписано, кем (пациент / представитель с именем)
    и отпечаток файла. Вошедший — подпись строки (`log_event` › actor).
    ⚠️ Потолок строки 200 (`EVENT_TEXT_MAX`): имя режется до 40."""
    who = ("pacientul" if sign["signer"] == "pacient"
           else f"reprezentant {sign['name'][:40]}")
    title = (_form(key) or (key, key))[1]
    return f"Semnat pe ecran: {title} · {who} · SHA-256 {sha}"


async def make_pdf(p: dict, key: str, lang: str, sign: dict) -> bytes:
    page = _inline_logo(await sheet(p, key, lang, sign))
    return await asyncio.to_thread(pdf.html_to_pdf, page)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
