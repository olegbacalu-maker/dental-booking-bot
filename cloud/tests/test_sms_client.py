"""Провод программы (bot/app/core/sms.py) против ЭТОГО сервера — как test_renew у лицензии.

Клиент программы грузится по пути (у него нет импортов проекта) и ходит в
живой сервер с токеном клиники: так доказывается, что ЭТОТ провод понимает
ЭТОТ сервер — коды отказа (sms.CODES), повтор без дубля, своё/чужое, личный
текст клиники в счёте. Стенд движка (tests/test_sms.py) те же ответы только
изображает.
"""
from harness import ROOT, Client, Result, Server, load_by_path
from test_sms import PHONE, TEXT, FakeSmsMd, _bal, _clinic_with_license

wire = load_by_path("sms_wire", ROOT / "bot" / "app" / "core" / "sms.py")


def suite_client(res: Result) -> None:
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env(DP_SMS_OFFERED="")) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s)
            base = wire.base_of(s.url + "/v1/license")
            res.check("база провода — /v1/sms/ того же сервера", base, s.url + "/v1/sms/")
            res.check("чужой токен — REFUSED", wire.account(base, "x" * 43, timeout=5), (wire.REFUSED, {}))
            out, body = wire.account(base, token, timeout=5)
            res.ok("пакет не предложен (ни DP_SMS_OFFERED, ни пилот): счёт OK с offered=false и причиной",
                   out == wire.OK and body.get("offered") is False and body.get("blocked") == "sms_not_offered",
                   repr((out, body)))
            out, body = wire.send(base, token, PHONE, TEXT, "day_before", "appt:1:day_before:x", timeout=5)
            res.check("отправка без пакета — DENIED sms_not_offered", (out, body.get("code")), (wire.DENIED, "sms_not_offered"))
            admin.post(f"/admin/clinics/{cid}/sms", action="pilot_on")
            admin.post(f"/admin/clinics/{cid}/sms", action="credit", reason="bonus", value="5", note="test")
            out, body = wire.account(base, token, timeout=5)
            res.ok("пилот и начисление: offered, enabled, остаток 5, от DentPilot, пакеты из cloud.env",
                   out == wire.OK and body["offered"] and body["enabled"] and body["balance"] == 5
                   and body["from"] == "DentPilot" and [p["units"] for p in body["packs"]] == [100, 500]
                   and body["custom"] == {}, repr(body))
            out, body = wire.send(base, token, PHONE, TEXT, "day_before", "appt:1:day_before:x", timeout=5)
            res.ok("send: OK, id сервера, остаток 4", out == wire.OK and body.get("id") and body.get("balance") == 4
                   and body.get("segments") == 1, repr(body))
            mid = body.get("id")
            out, again = wire.send(base, token, PHONE, TEXT, "day_before", "appt:1:day_before:x", timeout=5)
            res.ok("повтор ключа — тот же id, без второго списания",
                   out == wire.OK and again.get("id") == mid and again.get("balance") == 4 and _bal(s, cid) == 4, repr(again))
            out, body = wire.status(base, token, [mid, 999], timeout=5)
            res.ok("status: своё сообщение с состоянием, чужого нет",
                   out == wire.OK and [i["id"] for i in body["items"]] == [mid] and body["items"][0]["state"], repr(body))
            out, body = wire.send(base, token, "022123456", TEXT, "day_before", "appt:2:day_before:x", timeout=5)
            res.check("стационарный номер — DENIED sms_phone", (out, body.get("code")), (wire.DENIED, "sms_phone"))
            out, body = wire.send(base, token, PHONE, "", "day_before", "appt:3:day_before:x", timeout=5)
            res.check("пустой текст — DENIED sms_text", (out, body.get("code")), (wire.DENIED, "sms_text"))
            out, body = wire.send(base, token, PHONE, TEXT, "zzz", "appt:4:day_before:x", timeout=5)
            res.check("чужой вид — DENIED sms_kind", (out, body.get("code")), (wire.DENIED, "sms_kind"))
            out, body = wire.sender(base, token, "Clinica Tst", timeout=5)
            res.ok("заявка на имя — OK, счёт с requested", out == wire.OK and body.get("sender_state") == "requested", repr(body))
            out, body = wire.order(base, token, pack=100, timeout=5)
            res.ok("нота за пакет — OK с референсом и суммой", out == wire.OK and body.get("reference", "").startswith("DP-")
                   and body.get("units") == 100, repr(body))
            # личный текст клиники — в счёте, когда включён и годен
            admin.post(f"/admin/clinics/{cid}/sms", action="custom", custom_ro="{clinica}: {ziua} {data} la {ora}",
                       custom_ru="", custom_on="1")
            out, body = wire.account(base, token, timeout=5)
            res.check("личный текст в счёте", body.get("custom"), {"ro": "{clinica}: {ziua} {data} la {ora}"})
    finally:
        fake.close()
