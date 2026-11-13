"""Гид кабинета «Cum cereți numele clinicii în SMS»: страница за входом, ссылка — в карточке имени
вкладки SMS.

Названия кнопок, шагов и вкладок гид берёт из тех же констант `views`, что рисуют карточку: правка
слова в кабинете меняет и гид. Цена года имени — прайс сервера, как в форме оплаты; без цены имя
не продаётся, и гид о плате молчит так же, как карточка. Данных клиники на странице нет.

Кадры кабинета лежат в репозитории (`assets/ghid-sms/`), как образцы закона 195: едут с кодом, и
тест видит те же байты, что сервер. На кадрах выдуманная клиника и нет цены числом: цены в
репозитории не хранятся, а картинка с суммой разошлась бы с прайсом сервера.
"""
from __future__ import annotations

import html
import pathlib

from . import config, sms

PATH = "/cont/sms/ghid"
LINK = "Ghid: cum cereți numele"
TITLE = "Cum cereți numele clinicii în SMS"
FRAME_PATH = PATH + "/cadru"
ASSETS = pathlib.Path(__file__).resolve().parent / "assets" / "ghid-sms"
# ключ адреса → (файл, ширина, высота, подпись); файл берётся только из этого словаря, не из адреса
FRAMES = {
    "cere": ("cere-numele.webp", 1500, 480, "Fila «SMS»: câmpul pentru nume și butonul de cerere."),
    "pasi": ("pasi.webp", 1500, 739, "Pașii din cartelă, după cerere (date de exemplu)."),
    "operatori": ("la-operatori.webp", 1500, 362, "Cererea este depusă la operatori."),
    "aprobat": ("aprobat.webp", 1500, 335, "Numele este aprobat și plătit: SMS-urile pleacă de la el."),
}
esc = html.escape


def frame(key: str) -> bytes | None:
    """Байты кадра; None — нет такого ключа или файла."""
    f = FRAMES.get(key)
    if f is None:
        return None
    try:
        return (ASSETS / f[0]).read_bytes()
    except OSError:
        return None


def _fig(key: str) -> str:
    _file, w, h, caption = FRAMES[key]
    src = f"{FRAME_PATH}/{key}"
    # на телефоне кадр мелкий: по нажатию открывается в полный размер
    return (f"<figure class='cadru'><a href='{src}' target='_blank' rel='noopener'><img src='{src}' width='{w}' "
            f"height='{h}' loading='lazy' alt='{esc(caption)}'></a><figcaption>{esc(caption)}</figcaption></figure>")


def _q(word: str) -> str:
    return f"«{esc(word)}»"


def _ul(items: list[str]) -> str:
    return "<ul class='ghid'>" + "".join(f"<li>{x}</li>" for x in items if x) + "</ul>"


_CSS = ("<style>.ghid-page .card{max-width:860px}.ghid-page .card p{margin:0 0 10px;line-height:1.55}"
        ".ghid-page .card p:last-child{margin-bottom:0}"
        ".ghid{margin:0;padding:0 0 0 20px;line-height:1.55}.ghid li{margin:0 0 8px}.ghid li:last-child{margin:0}"
        "ol.ghid li{margin:0 0 16px;padding-left:4px}ol.ghid li p{margin:6px 0 0}"
        ".cadru{margin:14px 0 0}.cadru img{display:block;max-width:100%;height:auto;border:1px solid var(--line);"
        "border-radius:12px}.cadru figcaption{font-size:13px;color:var(--muted);margin:6px 0 0}</style>")


def page(acc, price: int, q: str = "") -> str:
    """Страница гида. `price` — цена года имени из прайса сервера (0 — не продаётся); `q` — `?c=`
    открытой клиники у кабинета с несколькими: с ним ссылки ведут обратно в её вкладки."""
    from . import views   # разметка кабинета; на уровне модуля views сам импортирует гид ради ссылки

    tab = {k: t for k, _, t in views.CONT_TABS}
    steps = views.NAME_STEPS
    card_btn = views._online(True)[0][1]
    at_ops, approved = views.SENDER_RO["submitted"][1], views.SENDER_RO["active"][1]
    cost = views.name_price(price) if price else ""
    back = f"/cont{q}#sms"

    def step(key: str, more: str) -> str:
        return f"<li><b>{steps[key][0]}</b>: {steps[key][1]}<p>{more}</p></li>"

    intro = ("Acum pacienții primesc memento-urile de la expeditorul comun «DentPilot», cu denumirea clinicii în "
             "text. Clinica poate cere ca SMS-urile să vină de la numele ei — de exemplu «LuminaDent». Numele îl "
             "aprobă operatorii de telefonie, prin furnizorul nostru SMS.MD, pe baza unei cereri semnate de "
             "clinică. Mai jos sunt pașii, cu butoanele exact cum sunt scrise în acest cont.")
    prepare = _ul([
        "<b>Abonamentul DentPilot Plus</b> — numele propriu ține de modulul SMS.",
        f"<b>Datele clinicii, complete</b>: IDNO, adresa juridică, telefonul și e-mailul. Ele apar în cerere. Dacă "
        f"lipsește ceva, contul scrie «{views.NAME_MISSING}…»: le completați în fila "
        f"<a href='/cont{q}#clinica'>{tab['clinica']}</a> ({_q(views.DATA_CARD)}, butonul {_q(views.DATA_SAVE)}) "
        f"și abia apoi apar pașii.",
        "<b>Cine semnează</b>: reprezentantul legal al clinicii (administratorul).",
        f"<b>Numele</b>: denumirea juridică sau marca clinicii. {views.NAME_RULE}; cel puțin o literă și fără "
        f"diacritice (ă, â, î, ș, ț). Exemple: «LuminaDent», «Lumina Dent», «Lumina-Dent».",
        f"<b>Plata</b>: {cost}" if cost else "",
    ])
    first = (f"<p>Deschideți fila <a href='{back}'>{tab['sms']}</a> a acestui cont. În cartela "
             f"{_q(views.NAME_CARD)} scrieți numele în câmpul {_q(views.NAME_FIELD)} și apăsați "
             f"{_q(views.NAME_ASK)}. Contul propune un nume după denumirea clinicii — îl puteți schimba. Dacă numele "
             f"este deja folosit sau cerut de altă clinică, contul vă spune și alegeți altul.</p>"
             f"<p>În cont se intră la cloud.dentpilot.md/cont, cu Google sau cu codul primit pe e-mail; din program — "
             f"cu butonul «Deschide contul clinicii», pe pagina «Licență».</p>{_fig('cere')}")
    pay = step("pay", f"Prețul — {views._mdl(price)} MDL pe an. Sub pași, în aceeași cartelă, bifați «Am citit și accept Termenii și condițiile "
                      f"DentPilot», apoi alegeți {_q(card_btn)} sau {_q(views.NAME_TRANSFER)} (nota vine și pe "
                      f"e-mail). Anul se numără din ziua în care operatorii aprobă numele, nu din ziua plății. După "
                      f"confirmarea plății, la acest pas scrie {_q(views.NAME_PAID)} și "
                      f"{_q(views.NAME_PAID_WAIT)}, iar formularul de plată dispare: anul nu se poate plăti a doua "
                      f"oară din greșeală.") if price else ""
    path = ("<ol class='ghid'>"
            + step("download", f"În câmpul {_q(views.NAME_REP)} scrieți persoana care va semna și apăsați "
                               f"{_q(views.NAME_DOWNLOAD)}. Cererea este formularul SMS.MD, deja completat cu "
                               f"datele clinicii și cu numele cerut — verificați-le înainte de semnare (sunt scrise "
                               f"îngroșat).")
            + step("sign", "Semnează reprezentantul legal. Ambele feluri sunt primite — cum anume, scrie mai "
                           "jos, la semnarea cererii.")
            + step("upload", f"Alegeți fișierul și apăsați {_q(views.NAME_UPLOAD)}. Se primește doar PDF; o "
                             f"fotografie (JPG) nu este primită. Sub buton apar data și mărimea fișierului primit. "
                             f"Dacă ați încărcat alt fișier din greșeală, încărcați-l pe cel corect — îl "
                             f"înlocuiește pe primul.")
            + pay
            + step("submit", f"Acest pas îl facem noi. În cont, lângă nume scrie {_q(at_ops)}, apoi "
                             f"{_q(approved)} și data până la care este plătit. Nu trebuie să faceți nimic în "
                             f"program: din ziua aprobării memento-urile pleacă de la numele clinicii.")
            + "</ol>" + _fig("pasi") + _fig("operatori") + _fig("aprobat"))
    sign = _ul([
        "<b>De mână</b>: tipăriți cererea, o semnează reprezentantul legal, apoi o scanați ca PDF (o fotografie "
        "JPG nu este primită).",
        "<b>Cu semnătura electronică</b> (MSign): semnați fișierul PDF descărcat și încărcați fișierul semnat, "
        "tot ca PDF.",
        f"Dacă în cerere ceva este greșit, corectați datele clinicii în fila {_q(tab['clinica'])} și descărcați "
        f"cererea din nou.",
    ])
    letters = _ul([
        f"<b>Nota de plată</b> — dacă alegeți {_q(views.NAME_TRANSFER)}; apoi <b>confirmarea plății</b>." if price
        else "",
        "<b>Numele a fost aprobat</b> — din acea zi SMS-urile pleacă de la numele clinicii"
        + (" (dacă anul este plătit; altfel scrisoarea spune că mai rămâne plata)." if price else "."),
        "<b>Cererea a fost respinsă</b> — cu motivul; el apare și în cont, unde puteți cere imediat alt nume."
        + (" Anul deja plătit rămâne valabil pentru numele următor." if price else ""),
        (f"<b>Anul se încheie</b> — cu {sms.NAME_SOON_DAYS} zile înainte de sfârșitul anului plătit, și încă o dată "
         f"când anul s-a încheiat.") if price else "",
        "Scrisorile vin pe e-mailul clinicii din acest cont. Starea cererii o vedeți oricând aici, în fila "
        f"{_q(tab['sms'])}.",
    ])
    good = _ul([
        "Până la aprobare nu se oprește nimic: memento-urile pleacă de la «DentPilot», ca și până acum.",
        f"Numele se poate cere și din program: Setări › SMS, {_q(views.NAME_FIELD)}, butonul "
        f"{_q(views.NAME_ASK)}. Cererea se descarcă și se încarcă însă doar în contul clinicii.",
        (f"Numele este pe un an. Îl prelungiți în același loc, în fila {_q(tab['sms'])} "
         f"({_q(views.NAME_RENEW)}); anul nou se adaugă la sfârșitul celui plătit. Dacă anul se încheie fără "
         f"prelungire, SMS-urile revin la «DentPilot» — fără blocare; numele rămâne aprobat și îl reporniți cu "
         f"plata.") if price else "",
        (f"{views.NAME_UNPAID}" if price else ""),
        "Dacă aveți filiale în același cont, numele este comun: cererea"
        + (" și plata se fac" if price else " se face") + " o singură dată, la clinica principală.",
        f"Alt nume înseamnă o cerere nouă ({_q(views.NAME_OTHER)}); numele aprobat rămâne până la aprobarea "
        f"celui nou.",
        "La un SMS trimis de la un nume pacientul nu poate răspunde — de aceea textul poate conține telefonul "
        "clinicii (Setări › SMS).",
    ])
    mailto = esc(config.SUPPORT_EMAIL)
    inner = (f"{_CSS}<div class='ghid-page'>"
             f"<div class='card'>{views._chead('file', 'Ce pregătiți')}{prepare}</div>"
             f"<div class='card'>{views._chead('message', 'Mai întâi: cereți numele')}{first}</div>"
             f"<div class='card'>{views._chead('list', 'Pașii din cont', 'ultimul pas este al nostru, ceilalți — ai clinicii')}{path}</div>"
             f"<div class='card'>{views._chead('file', 'Cum semnați cererea', 'de mână sau cu semnătura electronică')}{sign}</div>"
             f"<div class='card'>{views._chead('inbox', 'Ce scrisori primiți')}{letters}</div>"
             f"<div class='card'>{views._chead('shield', 'Bine de știut')}{good}"
             f"<p style='margin:14px 0 0'>Întrebări: <a href='mailto:{mailto}'>{mailto}</a>.</p></div>"
             f"<p><a class='btn second' href='{back}'>Înapoi la fila {esc(tab['sms'])}</a></p></div>")
    return views._cont_shell(TITLE, inner, acc, eyebrow="Contul clinicii · SMS", lead=esc(intro))
