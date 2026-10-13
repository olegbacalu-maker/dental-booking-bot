"""«Consultație» — дневник визита (дневниковая часть формы 043/e): графы,
шаблоны и подписи для JSON API (`GET/POST /api/visits/{aid}`, экран React).

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
нём было бы ошибкой данных): POST отвечает bad_vst, экран показывает
запись только для чтения, если она успела появиться до отмены.

Без маршрутов и без ЗАПРОСОВ к db: маршруты и правило сохранения живут в
`routes.py`/`api.py` (`_visit_ctx`, `_save_visit`). Список полей обязан
совпадать с db.VISIT_FIELDS — запись собирается по нему. Старая страница с
формой снята 13.10 (снятие старого интерфейса, шаг 4).
"""
from __future__ import annotations

# статусы визита, которым консультацию НЕ пишут
NO_FORM_STATUSES = ("cancelled", "noshow")

# что говорит экран вместо формы у отменённого/неявившегося визита
READONLY_NOTE = ("Vizita este anulată sau marcată «neprezentare» — "
                 "consultația nu se completează.")

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


def fields() -> list[dict]:
    """Графы дневника данными — для JSON API (DentPilot 2.0): подписи,
    высота и подсказки; порядок — порядок бланка."""
    return [{"id": k, "label": lab, "rows": rows, "placeholder": ph}
            for k, lab, rows, ph in _FIELDS]


def templates() -> list[dict]:
    """Шаблоны-заготовки данными: клиент заполняет ими ТОЛЬКО пустые поля
    (клик не должен стереть вписанное руками); тексты живут здесь, у клиента
    копии нет."""
    return [{"id": k, "label": t["label"], "values": {f: t[f] for f, *_ in _FIELDS}}
            for k, t in _TEMPLATES.items()]


def item_text(it: dict) -> str:
    """Позиция плана словами: «dinte 26 · Obturație 26 · 500 MDL» — сырой
    текст, экранирует тот, кто рисует (клиент — React)."""
    parts = []
    if it.get("tooth"):
        parts.append(f"dinte {it['tooth']}")
    parts.append(it["procedure"])
    if it.get("price_mdl"):
        parts.append(f"{it['price_mdl']} MDL")
    return " · ".join(parts)

