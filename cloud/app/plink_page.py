"""Страница пациента `v.dentpilot.md/КОД` (Premium волна 2а): «Vin» / «Nu pot veni» по ссылке из SMS.

Кадры и слова — `design\\premium-w2\\patient\\` (сессия w2-look, Олег 27.11 «Да, A и умолчания»): семь состояний,
RO и RU, без JavaScript и без cookie; галочка «Vin» рисуется чистым CSS и стоит готовой при «уменьшить движение».
Политика страницы — `default-src 'none'`: внешних шрифтов, картинок и скриптов нет, значки — встроенный SVG.

⛔ GET ничего не пишет: превью Google Messages и мессенджеров открывает ссылку раньше человека. Ответ — POST формы с
подписью `t` (код + сутки, auth.form_mark), которую отдаёт только GET, и `auth.same_origin_post`.

⛔ Мета-теги (`<title>`, описание, og:*) одни на ВСЕ состояния живого кода и без названия клиники, времени, имени:
карточка превью видна в переписке, и разные теги выдали бы, ответил ли человек. Код, которого нет, стёрт или чей
визит прошёл, — одна безликая страница 404 без og:* («нет такого» и «был, да сплыл» не различаются).

Перебор кодов (в памяти процесса, как trial.limited): с адреса (IPv6 — сеть /64) не больше MISS_PER_HOUR промахов
в час — дальше промахи получают 429 (та же безликая страница), а живой код с того же адреса отвечает как обычно.
Робот превью (`PREVIEW_BOTS` по User-Agent) приходит с общих адресов Google/Meta и открывает и старые ссылки: его
промахи считаются отдельно, со своим пределом. Со всех адресов больше MISS_TOTAL_PER_HOUR — 429 на промахи всем.
POST — не больше POST_PER_HOUR в час с адреса.
"""
from __future__ import annotations

import hmac
import html
import logging
import time
from datetime import datetime, timedelta, timezone

from . import auth, config, db, plink, sms, trial

log = logging.getLogger("cloud")
UTC = timezone.utc
PATH = "/r"                      # запасной адрес: cloud.dentpilot.md/r/КОД; короткий хост Caddy переписывает сюда
OG_PATH = "/og/confirm.png"
MARK = "plink"
MISS_PER_HOUR = 10
BOT_MISS_PER_HOUR = 120
MISS_TOTAL_PER_HOUR = 300
POST_PER_HOUR = 30
# роботы карточек превью: открывают ссылку сами, кнопок не нажимают (подстрока User-Agent, без регистра)
PREVIEW_BOTS = ("googlebot", "google-pagerenderer", "googleother", "google-read-aloud", "googleimageproxy",
                "facebookexternalhit", "facebot", "meta-externalagent", "whatsapp", "telegrambot", "twitterbot",
                "slackbot", "discordbot", "linkedinbot", "skypeuripreview", "viber", "applebot", "bingbot",
                "bingpreview", "vkshare", "pinterest", "embedly", "iframely", "redditbot")
HEADERS = {"Cache-Control": "no-store",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
                                      "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"}

_miss: dict[str, list[float]] = {}
_bot_miss: dict[str, list[float]] = {}
_posts: dict[str, list[float]] = {}
_all_miss: list[float] = []
_swept = [0.0]
_loud = [0.0]


# ---------- перебор ----------


def is_bot(ua: str) -> bool:
    low = (ua or "").lower()
    return any(b in low for b in PREVIEW_BOTS)


def _fresh(hits: dict[str, list[float]], key: str, now: float) -> int:
    stamps = [t for t in hits.get(key, []) if now - t < 3600]
    if stamps:
        hits[key] = stamps
    else:
        hits.pop(key, None)
    return len(stamps)


def _sweep(now: float) -> None:
    if now - _swept[0] < 60:
        return
    for hits in (_miss, _bot_miss, _posts):
        for k in [k for k, v in hits.items() if not v or now - v[-1] >= 3600]:
            del hits[k]
    _all_miss[:] = [t for t in _all_miss if now - t < 3600]
    _swept[0] = now


def miss_limited(ip: str, ua: str) -> bool:
    """Промах (кода нет) с этого адреса сверх предела часа — 429. Робот превью — своим пределом."""
    now = time.time()
    _sweep(now)
    key = trial.bucket(ip)
    over = (_fresh(_bot_miss, key, now) >= BOT_MISS_PER_HOUR if is_bot(ua)
            else _fresh(_miss, key, now) >= MISS_PER_HOUR)
    _all_miss[:] = [t for t in _all_miss if now - t < 3600]
    if len(_all_miss) >= MISS_TOTAL_PER_HOUR:
        if now - _loud[0] > 3600:
            log.warning("страница ответа: больше %d промахов кода в час со всех адресов — промахи получают 429",
                        MISS_TOTAL_PER_HOUR)
            _loud[0] = now
        return True
    return over


def note_miss(ip: str, ua: str) -> None:
    now = time.time()
    (_bot_miss if is_bot(ua) else _miss).setdefault(trial.bucket(ip), []).append(now)
    _all_miss.append(now)


def post_limited(ip: str) -> bool:
    now = time.time()
    _sweep(now)
    key = trial.bucket(ip)
    if _fresh(_posts, key, now) >= POST_PER_HOUR:
        return True
    _posts.setdefault(key, []).append(now)
    return False


# ---------- подпись формы ----------


def _day(now: datetime) -> int:
    return int(now.timestamp() // 86400)


def mark(code: str, now: datetime) -> str:
    return auth.form_mark(MARK, code, _day(now))


def mark_ok(code: str, t: str, now: datetime) -> bool:
    """Подпись этих суток или прошлых (страницу открыли до полуночи, нажали после)."""
    t = t or ""
    return any(hmac.compare_digest(t, mark(code, now - timedelta(days=d))) for d in (0, 1))


# ---------- разметка ----------

SVG = {
    "check": "<path d='M20 6 9 17l-5-5'/>",
    "tick": "<path d='M4.5 12.5 9.5 17.5 20 6.5'/>",
    "phone": ("<path d='M6.5 3.5h3l1.5 4-2 1.2a12 12 0 0 0 5.3 5.3l1.2-2 4 1.5v3a1.5 1.5 0 0 1-1.7 1.5"
              "C10.6 17.4 6.6 13.4 5 5.2A1.5 1.5 0 0 1 6.5 3.5z'/>"),
    "info": "<circle cx='12' cy='12' r='9'/><path d='M12 11v5.5'/><path d='M12 7.8h.01'/>",
    "clinic": ("<path d='M4 20.5V9l8-5 8 5v11.5'/><path d='M3 20.5h18'/><path d='M12 8.5v4M10 10.5h4'/>"
               "<path d='M9.5 20.5v-4.5h5v4.5'/>"),
}


def _ic(name: str) -> str:
    return ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            f"stroke-linejoin='round' aria-hidden='true'>{SVG[name]}</svg>")


CSS = """
:root{--bg:#F4F6F7;--card:#FFFFFF;--text:#16232B;--text2:#4A5A63;--text3:#6B7A83;--line:#DCE3E6;
 --brand:#0B7F6F;--on-brand:#FFFFFF;--brand-soft:#E3F4F1;--warn-soft:#FFF4DC;--warn-t:#8A5A00;
 --focus:#0B7F6F;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0F1719;--card:#182326;--text:#E8EEF0;--text2:#B5C2C7;--text3:#8C9BA1;
 --line:#2C3A3E;--brand:#2BB39E;--on-brand:#06201C;--brand-soft:#173A35;--warn-soft:#3A2F14;
 --warn-t:#F2C66B;--focus:#3CC4AE}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);
 font:17px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
 display:flex;flex-direction:column;align-items:center;padding:12px 16px 20px}
.top{width:100%;max-width:440px;display:flex;justify-content:space-between;align-items:center;
 font-size:14px;color:var(--text3);min-height:32px}
.lang{display:flex;gap:2px}
.lang a,.lang b{padding:6px 10px;border-radius:8px;text-decoration:none;color:var(--text2)}
.lang b{color:var(--text);background:var(--card);border:1px solid var(--line)}
main{width:100%;max-width:440px;margin-top:10px;background:var(--card);border:1px solid var(--line);
 border-radius:18px;padding:24px 20px 22px;text-align:center}
.cl{display:flex;flex-direction:column;align-items:center;gap:8px;margin-bottom:18px}
.cl .mk{width:44px;height:44px;border-radius:50%;background:var(--brand-soft);color:var(--brand);
 display:flex;align-items:center;justify-content:center}
.cl .mk svg{width:24px;height:24px}
.cl .nm{font-size:20px;font-weight:700;letter-spacing:-.01em;overflow-wrap:anywhere}
h1{font-size:24px;line-height:1.25;margin:4px 0 6px;letter-spacing:-.01em}
p{margin:0 0 6px}
.sub{color:var(--text2);font-size:16px}
form{margin:0}
.inl{display:inline}
.acts{display:flex;flex-direction:column;gap:12px;margin-top:20px}
.btn{appearance:none;width:100%;min-height:58px;border-radius:14px;font:inherit;font-size:19px;font-weight:650;
 display:flex;align-items:center;justify-content:center;gap:10px;cursor:pointer;text-decoration:none;
 border:2px solid var(--brand);padding:10px 16px}
.btn svg{width:22px;height:22px;flex:none}
.btn.yes{background:var(--brand);color:var(--on-brand)}
.btn.no{background:transparent;color:var(--text);border-color:var(--line)}
.btn.tel{background:transparent;color:var(--brand);min-height:52px;font-size:17px;font-weight:600}
.btn.tel b{font-weight:700}
.nw{white-space:nowrap}
.btn:focus-visible,.link:focus-visible{outline:3px solid var(--focus);outline-offset:3px}
.note{margin-top:16px;color:var(--text3);font-size:14px}
.change{margin-top:22px;padding-top:16px;border-top:1px solid var(--line);color:var(--text2);font-size:15px}
.link{appearance:none;background:none;border:0;padding:8px 6px;font:inherit;font-size:16px;font-weight:600;
 color:var(--brand);text-decoration:underline;text-underline-offset:3px;cursor:pointer}
.when{display:inline-block;margin-top:6px;padding:4px 10px;border-radius:999px;background:var(--bg);
 color:var(--text2);font-size:14px}
.st{width:84px;height:84px;margin:6px auto 14px;border-radius:50%;display:flex;align-items:center;justify-content:center}
.st svg{width:44px;height:44px}
.st.ok{background:var(--brand);color:var(--on-brand)}
.st.no{background:var(--warn-soft);color:var(--warn-t)}
.st.no svg,.st.inf svg{width:38px;height:38px}
.st.inf{background:var(--bg);color:var(--text2)}
footer{margin-top:auto;padding-top:22px;color:var(--text3);font-size:12px;text-align:center}
@media (max-width:340px){body{padding:10px 10px 16px}main{padding:20px 14px 18px}h1{font-size:22px}
 .btn{font-size:18px;min-height:56px}}
.anim .st.ok{animation:pop 380ms cubic-bezier(.2,.9,.3,1.3) both}
.anim .st.ok path{stroke-dasharray:24;animation:draw 340ms ease-out 220ms both}
.anim .rise{animation:rise 320ms ease-out 400ms both}
.anim .rise2{animation:rise 320ms ease-out 700ms both}
@keyframes pop{0%{transform:scale(.4);opacity:0}60%{transform:scale(1.08);opacity:1}100%{transform:scale(1);opacity:1}}
@keyframes draw{from{stroke-dashoffset:24}to{stroke-dashoffset:0}}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.anim *{animation:none!important}}
"""

W = {
    "ro": dict(
        top="Programare", by="prin DentPilot", lang_label="Limba",
        q="Veniți la programare?", qsub="Data și ora sunt în SMS-ul primit de la clinică.",
        yes="Vin", no="Nu pot veni", qnote="Răspunsul ajunge la recepția clinicii.",
        y_h="Mulțumim! Vă așteptăm.", y_sub="Clinica a primit confirmarea.",
        y_change="Planurile s-au schimbat?", y_change_b="Nu mai pot veni",
        n_h="Am anunțat clinica", n_sub="Clinica vă va suna.", n_tel="Sunați:",
        n_change="Ați apăsat din greșeală?", n_change_b="Totuși vin",
        dy_h="Ați confirmat deja", dy_sub="Clinica vă așteaptă.", when="Răspunsul dvs.: {a} · {t}",
        dn_h="Ați anunțat că nu puteți veni", dn_sub="Clinica vă va suna.",
        c_h="Linkul nu mai este valabil", c_sub="Programarea a fost modificată sau anulată de clinică. "
        "Pentru întrebări, sunați la clinică.",
        x_h="Linkul nu mai este valabil", x_sub="Programarea a trecut sau linkul nu este complet. "
        "Pentru întrebări, sunați la clinica dvs.",
        lim_sub="Prea multe încercări. Încercați din nou peste o oră.",
        og_title="Confirmați programarea", og_desc="Apăsați pentru a răspunde: Vin sau Nu pot veni",
        og_locale="ro_RO",
    ),
    "ru": dict(
        top="Programare", by="через DentPilot", lang_label="Язык",
        q="Вы придёте на приём?", qsub="Дата и время — в SMS от клиники.",
        yes="Приду", no="Не смогу прийти", qnote="Ответ получит регистратура клиники.",
        y_h="Спасибо! Ждём вас.", y_sub="Клиника получила подтверждение.",
        y_change="Планы изменились?", y_change_b="Не смогу прийти",
        n_h="Мы сообщили клинике", n_sub="Клиника вам перезвонит.", n_tel="Позвонить:",
        n_change="Нажали по ошибке?", n_change_b="Всё-таки приду",
        dy_h="Вы уже подтвердили", dy_sub="Клиника ждёт вас.", when="Ваш ответ: {a} · {t}",
        dn_h="Вы сообщили, что не придёте", dn_sub="Клиника вам перезвонит.",
        c_h="Ссылка больше не действует", c_sub="Клиника изменила или отменила запись. "
        "Если есть вопросы, позвоните в клинику.",
        x_h="Ссылка больше не действует", x_sub="Приём уже прошёл или ссылка неполная. "
        "Если есть вопросы, позвоните в свою клинику.",
        lim_sub="Слишком много попыток. Попробуйте через час.",
        og_title="Подтвердите запись", og_desc="Нажмите, чтобы ответить: приду или не смогу прийти",
        og_locale="ru_RU",
    ),
}
E = html.escape


def lang_of(asked: str, row) -> str:
    """Язык страницы: переключатель (?l= / поле формы), иначе язык кода (его назвала программа)."""
    if asked in W:
        return asked
    return row["lang"] if row is not None and row["lang"] in W else "ro"


def og_url() -> str:
    return f"https://{config.LINK_HOST}{OG_PATH}"


def meta(meta_lang: str) -> str:
    """Мета-теги живого кода: одни на все состояния, язык — кода, без клиники, времени и самого кода."""
    w = W[meta_lang]
    return (f"<title>{w['og_title']}</title>"
            f"<meta name='description' content='{w['og_desc']}'>"
            "<meta property='og:type' content='website'>"
            f"<meta property='og:title' content='{w['og_title']}'>"
            f"<meta property='og:description' content='{w['og_desc']}'>"
            f"<meta property='og:image' content='{og_url()}'>"
            "<meta property='og:image:width' content='1200'><meta property='og:image:height' content='630'>"
            "<meta property='og:image:alt' content=''>"
            f"<meta property='og:locale' content='{w['og_locale']}'>"
            "<meta name='twitter:card' content='summary_large_image'>")


def _page(lang: str, body: str, *, head: str, clinic: str = "", anim: bool = False) -> str:
    w = W[lang]
    other = "ru" if lang == "ro" else "ro"
    sw = (f"<b>{lang.upper()}</b><a href='?l={other}'>{other.upper()}</a>" if lang == "ro"
          else f"<a href='?l={other}'>{other.upper()}</a><b>{lang.upper()}</b>")
    cl = (f"<div class='cl'><span class='mk'>{_ic('clinic')}</span><span class='nm'>{E(clinic)}</span></div>"
          if clinic else "")
    return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta name='robots' content='noindex, nofollow'>{head}<style>{CSS}</style></head>"
            f"<body class='{'anim' if anim else ''}'><div class='top'><span>{w['top']}</span>"
            f"<nav class='lang' aria-label='{w['lang_label']}'>{sw}</nav></div>"
            f"<main>{cl}{body}</main><footer>{w['by']}</footer></body></html>")


def _form(code: str, lang: str, a: str, inner: str, now: datetime, cls: str = "") -> str:
    # без action: форма уходит на адрес страницы — короткий хост или /r/КОД, как открыли
    return (f"<form method='post' class='{cls}'><input type='hidden' name='t' value='{mark(code, now)}'>"
            f"<input type='hidden' name='l' value='{lang}'><input type='hidden' name='a' value='{a}'>{inner}</form>")


def _tel(lang: str, phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not digits:
        return ""
    return (f"<div class='acts'><a class='btn tel' href='tel:{E(digits)}'>{_ic('phone')}"
            f"<span>{W[lang]['n_tel']} <b class='nw'>{E(phone)}</b></span></a></div>")


def _when(lang: str, row) -> str:
    at = sms.local(db.parse_ts(row["answered_at"]))
    w = W[lang]
    return f"<span class='when'>{w['when'].format(a=w['yes'] if row['state'] == plink.YES else w['no'], t=f'{at:%d.%m, %H:%M}')}</span>"


def render(row, lang: str, now: datetime, just: bool = False) -> str:
    """Страница живого кода: вопрос (open), «Vin» (yes; сразу после нажатия — с анимацией), «Nu pot veni» (no),
    «изменено» (closed). `just` — ответ только что дан этим POST."""
    w, code, phone = W[lang], row["code"], row["phone"]
    st = row["state"]
    if st == plink.OPEN:
        body = (f"<h1>{w['q']}</h1><p class='sub'>{w['qsub']}</p><div class='acts'>"
                + _form(code, lang, plink.YES, f"<button class='btn yes'>{_ic('check')}{w['yes']}</button>", now)
                + _form(code, lang, plink.NO, f"<button class='btn no'>{w['no']}</button>", now)
                + f"</div><p class='note'>{w['qnote']}</p>")
    elif st == plink.YES and just:
        body = (f"<div class='st ok' role='img' aria-label='OK'>{_ic('tick')}</div>"
                f"<div class='rise'><h1>{w['y_h']}</h1><p class='sub'>{w['y_sub']}</p></div>"
                f"<div class='change rise2'>{w['y_change']} "
                + _form(code, lang, plink.NO, f"<button class='link'>{w['y_change_b']}</button>", now, "inl") + "</div>")
    elif st == plink.YES:
        body = (f"<div class='st ok'>{_ic('check')}</div><h1>{w['dy_h']}</h1><p class='sub'>{w['dy_sub']}</p>"
                f"{_when(lang, row)}<div class='change'>{w['y_change']} "
                + _form(code, lang, plink.NO, f"<button class='link'>{w['y_change_b']}</button>", now, "inl") + "</div>")
    elif st == plink.NO:
        top = (f"<h1>{w['n_h']}</h1><p class='sub'>{w['n_sub']}</p>" if just else
               f"<h1>{w['dn_h']}</h1><p class='sub'>{w['dn_sub']}</p>{_when(lang, row)}")
        body = (f"<div class='st no'>{_ic('phone')}</div>{top}{_tel(lang, phone)}<div class='change'>{w['n_change']} "
                + _form(code, lang, plink.YES, f"<button class='link'>{w['n_change_b']}</button>", now, "inl") + "</div>")
    else:
        body = f"<div class='st inf'>{_ic('info')}</div><h1>{w['c_h']}</h1><p class='sub'>{w['c_sub']}</p>{_tel(lang, phone)}"
    meta_lang = row["lang"] if row["lang"] in W else "ro"
    return _page(lang, body, head=meta(meta_lang), clinic=row["label"], anim=st == plink.YES and just)


def dead(lang: str, limited: bool = False) -> str:
    """Безликая страница: кода нет, стёрт, визит прошёл; `limited` — перебор (429). Без клиники и без og:* —
    карточку превью не рисовать."""
    lang = lang if lang in W else "ro"
    w = W[lang]
    return _page(lang, f"<div class='st inf'>{_ic('info')}</div><h1>{w['x_h']}</h1>"
                       f"<p class='sub'>{w['lim_sub'] if limited else w['x_sub']}</p>",
                 head=f"<title>{w['top']}</title>")
