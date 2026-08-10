"""Страница «Consultație» — дневник визита (дневниковая часть будущей 043/e).

Одна запись 1:1 к визиту: acuze / examen obiectiv / diagnostic / tratament /
recomandari — ровно графы дневника «Fișa medicală a bolnavului stomatologic».
Заполняет врач или рецепция после приёма; повторное сохранение редактирует
запись (updated_at и автор видны под формой, оба события — в летописи).
Кнопки удаления нет намеренно: медицинская запись правится, но не исчезает.

Шаблоны-заготовки — встроенный словарь _TEMPLATES (паттерн MSG_BANNER: текст
версионируется кодом, клиника его пока не правит). Шаблон заполняет ТОЛЬКО
пустые поля: клик не должен стереть вписанное руками. Национальных протоколов
по терапевтической стоматологии в РМ нет (PCN — только кровотечение,
остеомиелит, детская травма), поэтому это именно заготовки текста, и слово
«protocol» в интерфейсе не используется.

Из формы можно отметить позиции плана «выполнено на этом визите»: позиция
финализируется из ЛЮБОГО нефинального статуса (минуя церемонию in_lucru —
дневник фиксирует свершившийся факт) и получает привязку appointment_id;
«Redeschide» в фише снимает привязку вместе с done_at (db.set_plan_status).

Визиты cancelled/noshow записи не принимают (приёма не было — «лечение» на
нём было бы ошибкой данных): POST отвечает bad_vst, страница показывает
запись только для чтения, если она успела появиться до отмены.

Рендер без db: данные приносит маршрут (паттерн acord.py). Список полей
обязан совпадать с db.VISIT_FIELDS — POST собирает форму по нему.
"""
from __future__ import annotations

import html
import json

from ... import engine as eng
from ...core.layout import MSG_BANNER, STATUS_LABEL, _shell, js_json

# статусы визита, которым консультацию НЕ пишут
NO_FORM_STATUSES = ("cancelled", "noshow")

# (name, подпись, строк textarea, placeholder)
_FIELDS = (
    ("acuze", "Acuze / motivul prezentării", 2, "Ce acuză pacientul…"),
    ("examen", "Examen obiectiv", 3, "Statusul local, rezultatul examinării…"),
    ("diagnostic", "Diagnostic", 2, "Diagnosticul stabilit…"),
    ("tratament", "Tratament efectuat", 3, "Ce s-a efectuat la această vizită…"),
    ("recomandari", "Recomandări", 2, "Recomandări pentru pacient…"),
)

# «__» в текстах — место для номера зуба: видно, что вписать
_TEMPLATES = {
    "consult": {
        "label": "Consultație",
        "acuze": "Prezentare pentru consultație / control profilactic.",
        "examen": "Mucoasa orală roz, umedă, fără leziuni. Starea dinților — "
                  "vezi formula dentară din fișă.",
        "diagnostic": "",
        "tratament": "Examen clinic complet. Starea dentară și planul de "
                     "tratament discutate cu pacientul.",
        "recomandari": "Igienă orală de două ori pe zi, control profilactic "
                       "peste 6 luni.",
    },
    "obturatie": {
        "label": "Obturație",
        "acuze": "Sensibilitate la rece și dulce la dintele __.",
        "examen": "Cavitate carioasă la dintele __, sondare sensibilă, "
                  "percuție indoloră, proba la rece pozitivă, scurtă.",
        "diagnostic": "Carie dentară, dintele __.",
        "tratament": "Anestezie locală. Prepararea cavității, prelucrare "
                     "medicamentoasă, obturație fotopolimerizabilă, șlefuire "
                     "și lustruire. Verificarea ocluziei.",
        "recomandari": "Evitați masticația pe partea tratată timp de 2 ore.",
    },
    "canal": {
        "label": "Tratament de canal",
        "acuze": "Durere spontană, pulsatilă la dintele __.",
        "examen": "Cavitate carioasă profundă la dintele __, comunicantă cu "
                  "camera pulpară, percuție sensibilă.",
        "diagnostic": "Pulpită acută, dintele __.",
        "tratament": "Anestezie locală. Deschiderea camerei pulpare, "
                     "extirparea pulpei, prelucrarea mecanică și "
                     "medicamentoasă a canalelor, obturație de canal / "
                     "pansament provizoriu.",
        "recomandari": "Posibilă sensibilitate 2–3 zile; analgezic la nevoie. "
                       "Prezentare la vizita următoare conform programării.",
    },
    "extractie": {
        "label": "Extracție",
        "acuze": "Durere la dintele __.",
        "examen": "Dintele __ compromis, imposibil de restaurat.",
        "diagnostic": "Parodontită apicală cronică, dintele __ irecuperabil.",
        "tratament": "Anestezie locală. Extracția dintelui __, chiuretaj "
                     "alveolar, hemostază. Recomandările post-extracționale "
                     "explicate pacientului.",
        "recomandari": "Nu clătiți gura 24 de ore, aplicați rece local, "
                       "analgezic la nevoie. Control la necesitate.",
    },
    "detartraj": {
        "label": "Detartraj / igienizare",
        "acuze": "Prezentare pentru igienizare profesională.",
        "examen": "Depuneri dentare supra- și subgingivale, gingie ușor "
                  "congestionată la sondare.",
        "diagnostic": "Depozite dentare. Gingivită catarală cronică.",
        "tratament": "Detartraj cu ultrasunete, periaj profesional, air-flow. "
                     "Instruire privind igiena orală.",
        "recomandari": "Periaj de două ori pe zi, ață dentară zilnic, "
                       "igienizare profesională peste 6 luni.",
    },
    "control": {
        "label": "Control",
        "acuze": "Prezentare la control programat.",
        "examen": "Starea post-tratament satisfăcătoare, fără acuze.",
        "diagnostic": "",
        "tratament": "Examen de control, verificarea zonei tratate.",
        "recomandari": "Continuarea igienei obișnuite; prezentare la "
                       "următorul control planificat.",
    },
}

# чекбоксы живут внутри .fform, где input растянут на 100% и h-ctl —
# возвращаем им естественные размеры
_CSS = """
<style>
 /* overflow-wrap: неразрывный токен в клиническом тексте (URL, «====»)
    иначе распирает mobile viewport — грабля из CLAUDE.md про таблицы */
 .vwrap{max-width:820px;display:flex;flex-direction:column;gap:14px;
   overflow-wrap:anywhere}
 .tplrow{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 4px}
 .tplrow button{background:var(--bg);border:1px solid var(--line);border-radius:9px;
   padding:6px 12px;cursor:pointer;font-size:12.5px;color:var(--text2)}
 .tplrow button:hover{border-color:var(--teal);color:var(--teal-d)}
 .vchk{display:flex;flex-direction:column;gap:6px;margin:2px 0 6px}
 .vchk label{display:flex;gap:8px;align-items:baseline;font-size:13.5px;cursor:pointer}
 .vchk input{width:auto;height:auto;accent-color:var(--teal)}
 .vdone{font-size:13px;color:var(--text2);margin:2px 0}
 .vmeta{color:var(--text3);font-size:12px;margin-top:6px}
 .vsec{margin:6px 0 0;font-size:13.5px}
</style>"""

_SCRIPT = """
<script>
const TPL = __TPL__;
function applyTpl(k){
  const t = TPL[k]; if (!t) return;
  for (const f of ["acuze","examen","diagnostic","tratament","recomandari"]){
    const el = document.getElementById('vf_' + f);
    if (el && !el.value.trim() && t[f]) el.value = t[f];
  }
}
</script>"""


def _fmt(dt) -> str:
    return dt.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M")


def _item_label(it: dict) -> str:
    parts = []
    if it.get("tooth"):
        parts.append(f"dinte {it['tooth']}")
    parts.append(html.escape(it["procedure"]))
    if it.get("price_mdl"):
        parts.append(f"{it['price_mdl']} MDL")
    return " · ".join(parts)


def page(appt: dict, rec: dict | None, items: list, back: str,
         msg: str = "") -> str:
    e = html.escape
    pid = appt["patient_id"]
    dt = appt["starts_at"].astimezone(eng.TZ)
    status = appt.get("status") or ""
    vals = {k: (rec.get(k) if rec else "") or "" for k, *_ in _FIELDS}

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    comment_row = ""
    if appt.get("comment"):
        comment_row = (f"<div class='frow'><span>Comentariu recepție</span>"
                       f"<span class='v'>💬 {e(appt['comment'])}</span></div>")
    head = f"""
<div class='fcard'>
  <h3>Consultație <small>· {dt.strftime("%d.%m.%Y %H:%M")} · vizita #{appt["id"]}</small></h3>
  <div class='frow'><span>Pacient</span><span class='v'>
    <a href='/admin/patient/{pid}'>{e(appt.get("name") or "—")}</a></span></div>
  <div class='frow'><span>Serviciu</span><span class='v'>{e(appt["service"])}</span></div>
  <div class='frow'><span>Medic</span><span class='v'>{e(appt["doctor"])}</span></div>
  <div class='frow'><span>Status</span><span class='v'>{e(STATUS_LABEL.get(status, status))}</span></div>
  {comment_row}
</div>"""

    meta = ""
    if rec:
        meta = f"Înregistrat: {_fmt(rec['created_at'])}"
        if rec.get("updated_at"):
            meta += f" · actualizat: {_fmt(rec['updated_at'])}"
        meta += f" · de {e(rec['author'] or '—')}"

    if status in NO_FORM_STATUSES:
        # приёма не было: запись (если успела появиться) — только для чтения
        rows = "".join(
            f"<p class='vsec'><b>{lab}:</b><br>{e(vals[k]).replace(chr(10), '<br>')}</p>"
            for k, lab, *_ in _FIELDS if vals[k]
        )
        note = ("Vizita este anulată sau marcată «neprezentare» — "
                "consultația nu se completează.")
        body_card = (f"<div class='fcard'><h3>Jurnalul consultației</h3>"
                     f"<div class='banner warn'>{note}</div>{rows}"
                     + (f"<div class='vmeta'>{meta}</div>" if rec else "")
                     + "</div>")
    else:
        tpl_btns = "".join(
            f"<button type='button' onclick=\"applyTpl('{k}')\">{e(t['label'])}</button>"
            for k, t in _TEMPLATES.items())
        fields_html = "".join(
            f"<label class='dlab' for='vf_{k}'>{lab}</label>"
            f"<textarea id='vf_{k}' name='{k}' rows='{rows}' maxlength='2000' "
            f"placeholder='{ph}'>{e(vals[k])}</textarea>"
            for k, lab, rows, ph in _FIELDS)

        open_items = [it for it in items if it["status"] != "finalizat"]
        linked = [it for it in items if it.get("appointment_id") == appt["id"]]
        plan_html = ""
        if linked:
            plan_html += ("<div class='vsec'><b>Efectuate la această vizită</b></div>"
                          + "".join(f"<div class='vdone'>✔ {_item_label(it)}</div>"
                                    for it in linked))
        if open_items:
            boxes = "".join(
                f"<label><input type='checkbox' name='done' value='{it['id']}'>"
                f"<span>{_item_label(it)}"
                + (" <small>— în lucru</small>" if it["status"] == "in_lucru" else "")
                + "</span></label>"
                for it in open_items)
            plan_html += (
                "<div class='vsec'><b>Proceduri din plan efectuate la această "
                "vizită</b> <small class='hint' style='margin:0'>— bifate devin "
                "«Finalizat» în plan și se leagă de vizită</small></div>"
                f"<div class='vchk'>{boxes}</div>")

        body_card = f"""
<div class='fcard'>
  <h3>Jurnalul consultației <small>· partea de jurnal a fișei 043/e</small></h3>
  <div class='tplrow'>{tpl_btns}</div>
  <small class='hint' style='margin:0 0 8px'>Șablonul completează doar câmpurile goale</small>
  <form method='post' action='/admin/visit/{appt["id"]}' class='fform'>
    <input type='hidden' name='back' value='{e(back)}'>
    {fields_html}
    {plan_html}
    <button class='savebtn'>💾 Salvează consultația</button>
    {f"<div class='vmeta'>{meta}</div>" if meta else ""}
  </form>
</div>"""

    tpl_json = js_json({k: {f: t[f] for f, *_ in _FIELDS} for k, t in _TEMPLATES.items()})
    body = (
        _CSS + banner
        + f"<p style='margin:0 0 12px'><a href='{e(back)}'>← Înapoi</a>"
          f" &nbsp;·&nbsp; <a href='/admin/patient/{pid}'>📇 Fișa pacientului</a></p>"
        + f"<div class='vwrap'>{head}{body_card}</div>"
        + _SCRIPT.replace("__TPL__", tpl_json)
    )
    return _shell(body, f"consultație · vizita #{appt['id']}", active="pat")
