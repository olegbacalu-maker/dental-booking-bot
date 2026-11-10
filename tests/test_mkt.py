"""Согласие на маркетинг в фише (10.11.2026): `patients.mkt_ok / mkt_at / mkt_src`.

Ответ пациента на «acorduri opționale › marketing» листа 195. Ставят его ДВА
пути, и оба проверяются здесь:
- подпись листа 195 на экране (`POST …/forms/acord195/sign`, `consents.mkt`):
  true → DA, false → NU, без ответа — отметка прежняя (`mkt_src = ecran`);
- регистратура по бумажному листу (`POST /api/patients/{pid}/mkt {ok}`,
  `mkt_src = manual`); не bool — 422, ничего не пишется (прайор 08-16).
Летопись — строка на ПЕРЕМЕНЕ ответа; обезличивание — NULL; выгрузка по
195-му — строка «Acord marketing» в читаемой копии и поля в машинной.
⚠️ `mkt_at` — колонка-дата (`db._DT_COLS`): без неё фиша падала бы на
`astimezone` строки — набор это видит ответом фиши, а не только базой.
"""
from __future__ import annotations

import io
import json
import zipfile

from harness import Client, Result, Server, clinic_today, new_patient
from test_sign import SIG, _card, _j, _patient


def _mkt(c: Client, pid: int) -> dict:
    return _card(c, pid)["profile"]["mkt"]


def _mkt_lines(card: dict) -> list[str]:
    return [a["text"] for a in card["activity"]["items"] if a["kind"] == "mkt"]


def suite_mkt_manual(res: Result) -> None:
    """Ручная отметка по бумажному листу, обезличивание, выгрузка 195."""
    today = clinic_today().strftime("%d.%m.%Y")
    with Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Mkt Hartie", "069555201")
        res.check("новая фиша — «nu s-a întrebat»", _mkt(c, pid), {"ok": None, "at": "", "src": ""})

        for body in ({}, {"ok": "da"}, {"ok": 1}, {"ok": None}):
            r = c.post_json(f"/api/patients/{pid}/mkt", body)
            res.check(f"не bool {body} — 422 bad_card, поле mkt", (r.status, r.msg, _j(r).get("field")),
                      (422, "bad_card", "mkt"))
        res.check("после отказов отметки нет", _mkt(c, pid)["ok"], None)

        r = c.post_json(f"/api/patients/{pid}/mkt", {"ok": True})
        j = _j(r)
        res.check("DA по бумаге — ok_card, DA, сегодня, manual",
                  (r.msg, j["data"]["profile"]["mkt"]), ("ok_card", {"ok": True, "at": today, "src": "manual"}))
        res.check("летопись — одна строка DA (marcat manual)", _mkt_lines(j["data"]),
                  ["Acord marketing: DA (marcat manual, foaie pe hârtie)"])
        j = _j(c.post_json(f"/api/patients/{pid}/mkt", {"ok": True}))
        res.check("тот же ответ ещё раз — строки летописи не прибавилось", len(_mkt_lines(j["data"])), 1)
        j = _j(c.post_json(f"/api/patients/{pid}/mkt", {"ok": False}))
        res.check("NU (отзыв согласия) — NU, manual, вторая строка летописи",
                  (j["data"]["profile"]["mkt"]["ok"], j["data"]["profile"]["mkt"]["src"], _mkt_lines(j["data"])[0]),
                  (False, "manual", "Acord marketing: NU (marcat manual, foaie pe hârtie)"))
        res.check("пересохранение профиля без правки ответа не трогает",
                  (c.post_json(f"/api/patients/{pid}/profile", {"name": "Mkt Hartie", "phone": "069555201"}).msg,
                   _mkt(c, pid)["ok"]), ("ok_card", False))

        # выгрузка по 195-му: читаемая копия словом, машинная — полями
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        html = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("читаемая копия: строка «Acord marketing» — NU, дата, бумага",
               f"<td>Acord marketing</td><td>NU, {today} (marcat manual, foaie pe hârtie)</td>" in html,
               html[html.find("Acord marketing") - 20:html.find("Acord marketing") + 120])
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("машинная копия: mkt_ok 0, mkt_src manual, дата есть",
                  (data["pacient"]["mkt_ok"], data["pacient"]["mkt_src"], bool(data["pacient"]["mkt_at"])),
                  (0, "manual", True))
        other = new_patient(c, "Mkt Nimic", "069555202")
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{other}/export").raw))
        res.ok("без ответа — «nu s-a întrebat»",
               "<td>Acord marketing</td><td>nu s-a întrebat</td>" in z.read("fisa-pacient.html").decode("utf-8"),
               "строки нет")

        # обезличивание: ответ — личность фиши, уходит вместе с телефоном
        c.post_json(f"/api/patients/{pid}/anamneza", {"flags": ["cardio"]})
        res.check("обезличивание проходит",
                  c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"}).msg, "ok_anon")
        res.check("после обезличивания — NULL («nu s-a întrebat»)", _mkt(c, pid),
                  {"ok": None, "at": "", "src": ""})


def suite_mkt_sign(res: Result) -> None:
    """Подпись листа 195 на экране ставит ответ сама; без ответа — не трогает."""
    today = clinic_today().strftime("%d.%m.%Y")

    def sign(c: Client, pid: int, key: str = "acord195", **cons) -> dict:
        body = {"signer": "pacient", "sig_patient": SIG}
        if cons:
            body["consents"] = cons
        if key == "acord_plan":
            body["sig_doctor"] = SIG
        r = c.post_json(f"/api/patients/{pid}/forms/{key}/sign", body)
        return {"code": r.msg, **(_j(r).get("data") or {})}

    with Server() as s:
        c = Client(s.url).login()
        pid = _patient(c, "069555203")
        d = sign(c, pid, mkt=True, photo=False)
        res.check("195 с DA — ok_sign, DA, сегодня, ecran",
                  (d["code"], d["profile"]["mkt"]), ("ok_sign", {"ok": True, "at": today, "src": "ecran"}))
        res.check("летопись — строка DA (semnată pe ecran)", _mkt_lines(d),
                  ["Acord marketing: DA (foaia Legea 195 semnată pe ecran)"])
        d = sign(c, pid, mkt=True)
        res.check("тот же ответ на новом листе — строки летописи не прибавилось", len(_mkt_lines(d)), 1)
        d = sign(c, pid, photo=True)
        res.check("лист без ответа о маркетинге — отметка прежняя (DA)", d["profile"]["mkt"]["ok"], True)
        d = sign(c, pid)
        res.check("лист без согласий вовсе — отметка прежняя (DA)", d["profile"]["mkt"]["ok"], True)
        d = sign(c, pid, "acord_plan", mkt=False)
        res.check("согласие к плану с «mkt» в теле — отметку не трогает",
                  (d["code"], d["profile"]["mkt"]["ok"]), ("ok_sign", True))
        d = sign(c, pid, mkt=False)
        res.check("195 с NU — NU, ecran, вторая строка летописи",
                  (d["profile"]["mkt"]["ok"], d["profile"]["mkt"]["src"], _mkt_lines(d)),
                  (False, "ecran", ["Acord marketing: NU (foaia Legea 195 semnată pe ecran)",
                                    "Acord marketing: DA (foaia Legea 195 semnată pe ecran)"]))

        # бумага после экрана и экран после бумаги — источник меняется, это перемена
        j = _j(c.post_json(f"/api/patients/{pid}/mkt", {"ok": False}))
        res.check("NU по бумаге после NU с экрана — источник manual, строка летописи",
                  (j["data"]["profile"]["mkt"]["src"], _mkt_lines(j["data"])[0]),
                  ("manual", "Acord marketing: NU (marcat manual, foaie pe hârtie)"))
        d = sign(c, pid, mkt=True)
        res.check("снова экран с DA — DA, ecran", (d["profile"]["mkt"]["ok"], d["profile"]["mkt"]["src"]),
                  (True, "ecran"))

        # отказ подписи — ни документа, ни отметки
        p2 = _patient(c, "069555204")
        r = c.post_json(f"/api/patients/{p2}/forms/acord195/sign",
                        {"signer": "pacient", "sig_patient": "data:image/png;base64,AAAA",
                         "consents": {"mkt": True}})
        res.check("кривая подпись — отказ, отметки нет", (r.status, _mkt(c, p2)["ok"]), (422, None))
