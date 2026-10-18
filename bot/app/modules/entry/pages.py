"""Страницы входа: PIN, первая установка, восстановление ключа, битый профиль.

Все они — со своей вёрсткой: panel.css не подключают и не будут, цвет клиники и
шрифт приезжают готовыми значениями через `layout.standalone()` (почему так —
комментарий над `LICENSE_TMPL` в `core/layout.py`). Исключение одно —
`CONFIG_BROKEN_TMPL`, он нарочно мимо `standalone()` (см. у него).

Шаблоны — строки Python, а не файлы: правило «интерфейс не просит знаки у
Windows» читает строковые литералы исходников, и страница в `.html` выпала бы
из его поля зрения молча; а экран битого профиля обязан открыться именно
тогда, когда что-то уже сломано, — лишнее чтение с диска было бы ему ещё
одной точкой отказа.
"""
from __future__ import annotations

from ...core.auth import PIN_MAX
from ...core.layout import _ic

# Логин НЕОБЯЗАТЕЛЕН: пароль у каждого свой (это стережёт pin_free), и
# заставлять регистратуру набирать ещё и id — трение десятки раз в день. Поле
# всё же есть: врачу с телефона вход по одному паролю неочевиден, а в клинике
# с одинаковыми привычками кто-нибудь однажды захочет войти именно «как я».
PIN_INPUT = ("<input type='text' name='uid' placeholder='ID (opțional)' "
             "autocomplete='username' maxlength='20' "
             "style='text-align:center;font-size:15px'>"
             "<input type='password' name='password' placeholder='PIN' autofocus required "
             f"inputmode='numeric' pattern='[0-9]*' maxlength='{PIN_MAX}' "
             "style='text-align:center;font-size:28px;letter-spacing:12px'>")
PASS_INPUT = "<input type='password' name='password' placeholder='Parola' autofocus required>"

# ⛔ На входе НЕ пишем, как сбросить забытый PIN (было до 08-11: «закройте
# программу и удалите data\\auth.json»). Совет расходился с FAQ, и расходился в
# опасную сторону: FAQ отвечает «пусть второй директор задаст новый пароль, а
# если директор один — напишите нам», а удаление файла сносит ВСЕ учётки и роли
# разом и вдобавок поднимает сигнализацию подмены auth.json — директор получает
# баннер о взломе за то, что выполнил инструкцию с нашего же экрана. Ответ
# живёт в одном месте: Setări → FAQ, «Am uitat PIN-ul de intrare».
#
# Заголовок входа — имя клиники и больше ничего. «— registrul clinicii» было
# третьим повтором одного и того же: то же слово стоит в заголовке окна, а над
# формой уже висит знак. Ровно от этого повтора избавились в шапке журнала (см.
# комментарий у топбара в core/layout.py), здесь он просто дожил дольше.

LOGIN_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — acces</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__BG__;display:flex;
      align-items:center;justify-content:center;min-height:100vh;margin:0;color:#162033;
      padding:16px;box-sizing:border-box}
 form{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      /* двухслойная, как --sh3 в panel.css: экран входа — первое, что видит
         клиника, а своей таблицы стилей у него нет (он обязан открываться,
         даже если статика не отдалась) */
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10);
      display:flex;flex-direction:column;gap:12px;width:min(340px,100%)}
 /* ВАЖНО: цвет заголовка — __ACCENT_D__, не __ACCENT__: чистый фирменный даёт на
    белой карточке 3.3:1 даже у зелёного по умолчанию, а при светлом выборе
    клиники (жёлтый, голубой) заголовок пропал бы вовсе. Тёмный оттенок
    дотемняется циклом до 4.5 к фону страницы, а карточка ещё светлее фона —
    значит порог выдержан тем более. */
 /* по центру, как логотип над ним: имя шло влево при центрованном знаке,
    и карточка читалась кривой (просьба Олега 08-21) */
 h1{font-size:19px;color:__ACCENT_D__;margin:0 0 4px;font-weight:600;letter-spacing:-.02em;
    text-align:center}
 /* логотип клиники — только если она его загрузила; высота ограничена здесь,
    потому что разбирать картинку нечем (Pillow в сборку не едет) */
 .clogo{align-self:center;max-height:64px;max-width:220px;object-fit:contain;margin-bottom:4px}
 /* 16px — не «дизайн», а защита: поле мельче 16px iOS зумит при фокусе */
 input{height:44px;padding:0 14px;border:1px solid #E7EDF5;border-radius:12px;font-size:16px;
       outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:__ACCENT_D__}
 .err{color:#B91C1C;font-size:13px}
</style></head><body>
<form method="post" action="/admin/login">
  __LOGO__
  <h1>__CLINIC__</h1>
  __ERR__
  <input type="hidden" name="next" value="__NEXT__">
  __INPUT__
  <button>Intră</button>
</form></body></html>"""


SETUP_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — PIN</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__ACCENT__;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;padding:30px 32px;border-radius:18px;
      box-shadow:0 4px 8px rgba(15,23,42,.12),0 22px 50px rgba(15,23,42,.26);
      display:flex;flex-direction:column;gap:12px;width:min(340px,100%)}
 /* центр — тем же правилом, что на входе: эти два экрана делят карточку
    «логотип + имя», и расходиться им нельзя */
 h1{font-size:19px;color:#162033;margin:0;font-weight:600;letter-spacing:-.02em;
    text-align:center}
 p{color:#7E8B9C;font-size:13px;margin:0;line-height:1.5}
 .clogo{align-self:center;max-height:64px;max-width:220px;object-fit:contain}
 input{padding:12px;border:1px solid #E7EDF5;border-radius:12px;font-size:26px;
       text-align:center;letter-spacing:12px;outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:48px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:__ACCENT_D__}
 .err{color:#B91C1C;font-size:13px}
</style></head><body>
<form method="post" action="/admin/setup">
  __LOGO__
  <h1>__CLINIC__</h1>
  <p>Prima pornire: setați un PIN pentru registrul clinicii (__PIN_RANGE__).</p>
  __ERR__
  <input type="password" name="pin1" placeholder="PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="8" autofocus required>
  <input type="password" name="pin2" placeholder="repetați PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="8" required>
  <button>Setează PIN</button>
</form></body></html>"""


# Пока PIN не установлен, журнал не защищён НИЧЕМ — и первичную установку
# обязан делать тот, кто сидит за самим компьютером клиники. Из сети (второе
# рабочее место, телефон) экран установки закрыт: при включённом «Acces din
# rețea» любой в Wi-Fi клиники иначе назначил бы себе первый PIN и стал бы
# единственным директором. После установки обычный вход из сети работает.
SETUP_LOCAL_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>__CLINIC__ — configurare</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__ACCENT__;
      color:__ON__;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;text-align:center;padding:16px}
 p{max-width:520px;line-height:1.55}
</style></head><body>
<h1>Prima configurare se face la calculatorul clinicii</h1>
<p>Programul nu are încă un PIN. Din motive de siguranță, primul PIN se
stabilește doar pe calculatorul pe care este instalat DentPilot — deschideți
programul acolo și setați PIN-ul. După aceea, intrarea din rețea va funcționa
ca de obicei, cu parola fiecărui utilizator.</p>
</body></html>"""


# auth.json исчез, а база его помнит (17.10): это сброс, не первая установка.
# Папка данных открыта всем учёткам машины намеренно (вторая смена), поэтому
# «удалить файл и назначить себе PIN» мог любой, кто сел за компьютер; теперь
# новый первый PIN — только с подтверждением администратора Windows
# (`privileged._auth_reset`). Для забывшего PIN директора путь тот же, что в
# FAQ: написать нам; ему и так понадобится эта кнопка.
SETUP_ADMIN_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>__CLINIC__ — configurare</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__ACCENT__;
      color:__ON__;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;text-align:center;padding:16px}
 p{max-width:560px;line-height:1.55}
 button{background:#fff;color:#162033;border:none;border-radius:12px;height:46px;
        padding:0 22px;font-size:15px;font-weight:600;cursor:pointer;font-family:inherit}
 .note{font-size:13.5px;opacity:.9}
</style></head><body>
<h1>Fișierul de acces lipsește</h1>
<p>Programul a avut un PIN, dar fișierul de acces (data\\auth.json) nu mai
există. Ca să nu-și poată seta oricine de la acest calculator un PIN nou și
să devină director, un PIN nou se stabilește doar cu <b>confirmarea unui
administrator Windows</b>. Vechile conturi ale clinicii nu se mai pot
recupera din acest fișier; datele clinicii nu sunt afectate.</p>
<form method="post" action="/admin/setup/ask">
  <button>Confirmă ca administrator Windows</button>
</form>
<p class="note">__NOTE__</p>
</body></html>"""

RECOVER_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — recuperare</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__BG__;display:flex;
      align-items:center;justify-content:center;min-height:100vh;margin:0;color:#162033;
      padding:16px;box-sizing:border-box}
 form{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10);
      display:flex;flex-direction:column;gap:12px;width:min(560px,100%)}
 h1{font-size:19px;margin:0;font-weight:600;letter-spacing:-.02em}
 p{color:#5A6875;font-size:13.5px;margin:0;line-height:1.55}
 /* моноширинный и крупный: код переписывают с бумаги, и группы должны
    читаться так же, как они там напечатаны */
 input{font-family:ui-monospace,Consolas,monospace;font-size:16px;letter-spacing:.06em;
       padding:12px 14px;border:1px solid #E7EDF5;border-radius:12px;outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer}
 .err{color:#B91C1C;font-size:13px}
 .warn{background:#FFFBEB;color:#B45309;font-size:13px;padding:10px 12px;border-radius:10px}
</style></head><body>
<form method="post" action="/admin/recover">
  <h1>__ICON__ Recuperarea evidenței</h1>
  <p>Baza de date a clinicii este criptată, iar cheia de pe acest calculator nu
  poate fi citită. Se întâmplă după reinstalarea Windows, la schimbarea
  calculatorului sau când programul este pornit de pe alt cont Windows.</p>
  <p><b>Introduceți codul de pe foaia de recuperare</b> — cea tipărită la
  activarea criptării (o găsiți în mapa „Legea 195” a clinicii, lângă cheia de recuperare BitLocker).</p>
  __ERR__
  <input name="code" placeholder="XXXXXX-XXXXXX-XXXXXX-…" autofocus required
         autocomplete="off" spellcheck="false">
  <button>Deblochează evidența</button>
  <div class="warn">Datele nu au fost modificate. Fără acest cod evidența nu
  poate fi deschisă de nimeni — nici de noi.</div>
</form></body></html>"""
# Иконка подставляется ЗДЕСЬ, а не в шаблоне: у страницы своя вёрстка, поэтому
# шаблон — обычная строка с __ЗАПОЛНИТЕЛЯМИ__, и f-строкой её не сделать (в CSS
# выше фигурных скобок больше, чем текста). `standalone` для этого не годится:
# он общий на все такие страницы, а ключ нужен одной.
RECOVER_TMPL = RECOVER_TMPL.replace("__ICON__", _ic("key"))


RECOVER_DONE = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>__CLINIC__ — recuperare</title><style>__FONTS__
 body{font-family:__FAMILY__;background:__ACCENT__;
      color:__ON__;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;text-align:center;padding:16px}
 p{max-width:520px;line-height:1.55}
</style></head><body>
<h1>Cheia a fost restabilită</h1>
<p>Închideți programul și porniți-l din nou — evidența se va deschide normal.
Cheia a fost legată din nou de acest calculator, așa că data viitoare codul nu
va mai fi necesar. Păstrați foaia de recuperare mai departe.</p>
</body></html>"""


# ⛔ НЕ через standalone(): тот подставил бы имя и цвет клиники, а они в этом
# состоянии пришли бы из демо-каркаса («DentPilot Demo» в PWA-теге) — страница
# существует ровно затем, чтобы демо не показывалось как своё. Экран нарочно
# нейтральный, без фирменного цвета.
# Host не наш (`auth.host_allowed`, 17.10): запрос пришёл по чужому DNS-имени.
# Та же нейтральная страница, что у битого профиля: имени клиники здесь нет
# намеренно — отвечаем до того, как кому-либо что-либо показали.
BAD_HOST_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>DentPilot — adresă neacceptată</title><style>__FONTS__
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#f5f6f7;
      color:#20262b;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;text-align:center;padding:16px}
 p{max-width:560px;line-height:1.55}
</style></head><body>
<h1>Adresă neacceptată</h1>
<p>Programul răspunde doar la adresa lui reală. Pe acest calculator deschideți
<b>http://127.0.0.1:__PORT__/admin</b>; de pe alt dispozitiv din rețeaua clinicii
folosiți adresa cu cifre afișată în <b>Setări › Acces din rețea</b>.</p>
</body></html>"""

def bad_host_page(request) -> str:
    """Страница 421 для `main._own_host`. Порт — у СОКЕТА сервера (`scope.server`),
    не из чужого Host: тот и есть то, чему мы не верим."""
    from ...core.layout import fonts_css
    server = request.scope.get("server") or ("", 0)
    return (BAD_HOST_TMPL.replace("__PORT__", str(server[1] or 8088))
            .replace("__FONTS__", fonts_css()))


CONFIG_BROKEN_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>DentPilot — eroare</title><style>__FONTS__
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#f5f6f7;
      color:#20262b;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;text-align:center;padding:16px}
 p{max-width:560px;line-height:1.55}
 code{font-size:13px;opacity:.85;word-break:break-all}
</style></head><body>
<h1>Profilul clinicii nu poate fi citit</h1>
<p>Fișierul cu profilul clinicii (<b>clinic.json</b>) este deteriorat, iar
copia de rezervă (clinic.json.bak) nu a putut fi folosită. Programul s-a oprit
aici ca să nu amestece evidența dvs. cu date demonstrative.</p>
<p><b>Ce e de făcut:</b> restaurați fișierul clinic.json dintr-o copie de
rezervă a clinicii sau contactați suportul, apoi reporniți programul.
Evidența pacienților (baza de date) nu este afectată.</p>
<p><code>__PATH__</code></p>
</body></html>"""
