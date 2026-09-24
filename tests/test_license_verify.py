"""Проверка подписи файла лицензии (L2): четыре отказа и один приём.

Модуль `app/core/rsa_verify.py` грузится по пути, как `gen_icons` в
test_structure: он обязан жить без импортов проекта, и голая загрузка это
проверяет заодно. Генератор фикстур `scripts/license_fixtures.py` грузится
так же — им подписываются НЕПРАВИЛЬНЫЕ claim'ы для шага 6: второй подписи в
тестах нет, есть одна, та же, что собрала фикстуры и сверена с openssl.

⭐ Чужой ключ — это `n + 2`, а не второй сгенерированный: нечётное число той
же длины, под которым подпись обязана НЕ сходиться, и пары простых для него
не нужно. ⚠️ Все проверки здесь про подпись и схему; время и состояния — L3.
"""
import ast
import hashlib
import importlib.util
import json
import sys
import time

from harness import BOT, ROOT, Result

FIX = ROOT / "tests" / "fixtures" / "license"
MODULE = BOT / "app" / "core" / "rsa_verify.py"
ALLOWED_IMPORTS = {"__future__", "base64", "binascii", "hashlib", "hmac", "json",
                   "re", "collections.abc", "dataclasses", "datetime"}


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # ⚠️ Регистрация ДО исполнения — рецепт из документации importlib, а не
    # украшение: `dataclass` при отложенных аннотациях ищет модуль класса в
    # sys.modules и без записи падает ещё на определении Claim.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rv = _load("rsa_verify", MODULE)
gen = _load("license_fixtures", ROOT / "scripts" / "license_fixtures.py")


def _key() -> dict:
    return gen.load_key()


def _fixture(name: str) -> tuple[str, bytes, bytes]:
    text = (FIX / f"{name}.json").read_text(encoding="utf-8")
    env = json.loads(text)
    return text, gen.unb64u(env["payload"]), gen.unb64u(env["sig"])


def _signed(claim: dict, k: dict, *, payload: bytes | None = None, kid: str = "test") -> str:
    """Конверт с ПРАВИЛЬНОЙ подписью над данным claim (или над готовыми байтами)."""
    payload = gen.claim_bytes(claim) if payload is None else payload
    return gen.envelope(payload, gen.sign(payload, k), kid=kid)


def suite_math(res: Result) -> None:
    """`verify`: pow, построенный блок, compare_digest."""
    k = _key()
    n, e = k["n"], k["e"]
    for name in ("valid", "expired", "trial", "unknown-kid"):
        _, payload, sig = _fixture(name)
        res.ok(f"{name}: подпись сходится", rv.verify(n, e, sig, payload))
    for name in ("bad-sig", "tampered"):
        _, payload, sig = _fixture(name)
        res.ok(f"{name}: подпись не сходится", not rv.verify(n, e, sig, payload))
    _, payload, sig = _fixture("valid")
    res.ok("чужой ключ (n+2): не сходится", not rv.verify(n + 2, e, sig, payload))
    res.ok("чужая экспонента: не сходится", not rv.verify(n, 3, sig, payload))
    res.ok("s = n: отказ без исключения", not rv.verify(n, e, n.to_bytes(384, "big"), payload))
    res.ok("подпись короче ключа: отказ", not rv.verify(n, e, sig[:-1], payload))
    res.ok("подпись длиннее ключа: отказ", not rv.verify(n, e, sig + b"\x00", payload))
    res.ok("другие данные под той же подписью: отказ", not rv.verify(n, e, sig, payload + b" "))
    res.ok("пустые данные: отказ", not rv.verify(n, e, sig, b""))

    fresh = b'{"anything": "signed here, not in fixtures"}'
    res.ok("подпись, сделанная сейчас, сходится", rv.verify(n, e, gen.sign(fresh, k), fresh))

    block = rv.emsa_pkcs1_v15_sha256(payload, 384)
    res.check("блок EMSA: тот же, что строит генератор",
              block, gen.emsa_pkcs1_v15(hashlib.sha256(payload).digest(), 384))
    res.ok("блок EMSA: 00 01, 330 байт FF, 00, DigestInfo, хеш",
           block[:2] == b"\x00\x01" and block[2:332] == b"\xff" * 330
           and block[332:333] == b"\x00" and block[333:352] == rv.DIGESTINFO_SHA256
           and block[352:] == hashlib.sha256(payload).digest() and len(block) == 384)

    t0 = time.perf_counter()
    for _ in range(1000):
        rv.verify(n, e, sig, payload)
    dt = time.perf_counter() - t0
    res.ok("1000 проверок — секунды, не минуты", dt < 5.0, f"{dt:.2f} с")


def suite_envelope(res: Result) -> None:
    """`open_envelope`: четыре отказа, порядок шагов, приём."""
    k = _key()
    keys = {"test": (k["n"], k["e"])}
    valid_text, valid_payload, valid_sig = _fixture("valid")

    code, claim = rv.open_envelope(valid_text, keys)
    res.check("valid: принят", code, "")
    res.ok("valid: claim собран", claim is not None and claim.clinic_id == "c_0123456789ab"
           and claim.seq == 3 and claim.plan == "standard" and claim.idno == "1234567890123")
    res.ok("valid: даты aware UTC",
           claim is not None and claim.valid_until.tzinfo is not None
           and claim.valid_until.isoformat() == "2099-01-01T00:00:00+00:00")
    res.check("valid: renew нет — None", getattr(claim, "renew", "?"), None)
    for name in ("expired", "trial"):
        res.check(f"{name}: принят (время — не дело проверки)",
                  rv.open_envelope(_fixture(name)[0], keys)[0], "")

    four = {"bad-sig": rv.BAD_SIGNATURE, "tampered": rv.BAD_SIGNATURE,
            "unknown-kid": rv.KEY_UNKNOWN}
    for name, want in four.items():
        code, claim = rv.open_envelope(_fixture(name)[0], keys)
        res.check(f"{name}: код {want}", code, want)
        res.check(f"{name}: claim нет", claim, None)
    code, claim = rv.open_envelope(valid_text, {"test": (k["n"] + 2, k["e"])})
    res.check("чужой ключ под тем же kid: bad_signature", code, rv.BAD_SIGNATURE)
    res.check("пустая таблица ключей: key_unknown", rv.open_envelope(valid_text, {})[0],
              rv.KEY_UNKNOWN)

    env = json.loads(valid_text)

    def with_env(**changes) -> str:
        e2 = dict(env)
        e2.update(changes)
        return json.dumps(e2)

    malformed = {
        "не JSON": "{",
        "JSON, но список": "[]",
        "без полей": "{}",
        "v = 2": with_env(v=2),
        "v = true": with_env(v=True),
        "v = \"1\"": with_env(v="1"),
        "kid в другом регистре": with_env(kid="Test"),
        "kid числом": with_env(kid=7),
        "kid длиннее 16": with_env(kid="a" * 17),
        "payload с «=»": with_env(payload=env["payload"] + "=="),
        "payload с чужим знаком": with_env(payload=env["payload"][:-1] + "*"),
        # ⚠️ Не «+ одна буква»: длина фикстуры не обязана делиться на 4, и одна
        # буква могла бы дать РАЗБОРЧИВУЮ строку — тогда отказ был бы за подпись
        "payload длиной 4n+1": with_env(
            payload=env["payload"] + "A" * ((1 - len(env["payload"])) % 4 or 4)),
        "sig 383 байта": with_env(sig=gen.b64u(valid_sig[:-1])),
        "sig 385 байт": with_env(sig=gen.b64u(valid_sig + b"\x00")),
        "sig числом": with_env(sig=1),
    }
    for label, text in malformed.items():
        code, claim = rv.open_envelope(text, keys)
        res.check(f"конверт — {label}: malformed", code, rv.MALFORMED)
    res.check("kid не по регулярке — malformed, а не key_unknown",
              rv.open_envelope(with_env(kid="Test"), {"Test": keys["test"]})[0], rv.MALFORMED)
    res.check("s = n: bad_signature, не исключение",
              rv.open_envelope(with_env(sig=gen.b64u(k["n"].to_bytes(384, "big"))), keys)[0],
              rv.BAD_SIGNATURE)
    res.check("лишнее поле конверта не мешает",
              rv.open_envelope(with_env(comment="issued by hand"), keys)[0], "")
    res.check("неизвестный kid проверяется ДО подписи: битая подпись под чужим kid — key_unknown",
              rv.open_envelope(json.dumps(dict(json.loads(_fixture("bad-sig")[0]), kid="nope")),
                               keys)[0], rv.KEY_UNKNOWN)


def suite_claim(res: Result) -> None:
    """Шаг 6: claim по таблице схемы. Подписи здесь правильные — отказывает схема."""
    k = _key()
    keys = {"test": (k["n"], k["e"])}
    base = dict(gen.CLAIMS["valid"])

    pretty = json.dumps(base, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    res.ok("не канонический, но верно подписанный payload — принят",
           pretty != gen.claim_bytes(base)
           and rv.open_envelope(_signed(base, k, payload=pretty), keys)[0] == "")
    res.check("неизвестное поле claim — принят (совместимость вперёд)",
              rv.open_envelope(_signed(dict(base, extra="ignored"), k), keys)[0], "")
    res.check("trial без IDNO — принят",
              rv.open_envelope(_signed(dict(base, plan="trial", idno=""), k), keys)[0], "")
    ok_renew = dict(base, renew={"url": "https://cloud.dentpilot.md/v1/license", "token": "t" * 32})
    code, claim = rv.open_envelope(_signed(ok_renew, k), keys)
    res.ok("renew по форме — принят и виден в Claim",
           code == "" and claim is not None and claim.renew == ok_renew["renew"])
    res.check("renew: null — как отсутствие",
              rv.open_envelope(_signed(dict(base, renew=None), k), keys)[0], "")

    bad = {
        "seq = 0": dict(base, seq=0),
        "seq = true": dict(base, seq=True),
        "seq строкой": dict(base, seq="3"),
        "clinic пустой": dict(base, clinic=""),
        "clinic 121 знак": dict(base, clinic="x" * 121),
        "clinic_id не по регулярке": dict(base, clinic_id="c_XYZ"),
        "idno 5 цифр": dict(base, idno="12345"),
        "idno с буквой": dict(base, idno="123456789012a"),
        "standard без idno": dict(base, idno=""),
        "plan gold": dict(base, plan="gold"),
        "country строчными": dict(base, country="md"),
        "дата с пробелом": dict(base, issued_at="2026-09-24 12:00:00Z"),
        "дата без Z": dict(base, issued_at="2026-09-24T12:00:00"),
        "дата с зоной": dict(base, issued_at="2026-09-24T12:00:00+00:00"),
        "valid_until = issued_at": dict(base, valid_until=base["issued_at"]),
        "grace_until < valid_until": dict(base, grace_until="2098-12-31T00:00:00Z"),
        "renew строкой": dict(base, renew="x"),
        "renew по http": dict(base, renew={"url": "http://cloud.dentpilot.md/", "token": "t" * 32}),
        "renew с коротким токеном": dict(base, renew={"url": "https://x/", "token": "t" * 31}),
        "без grace_until": {f: v for f, v in base.items() if f != "grace_until"},
    }
    for label, claim in bad.items():
        code, got = rv.open_envelope(_signed(claim, k), keys)
        res.check(f"claim — {label}: malformed", code, rv.MALFORMED)
        if got is not None:
            res.ok(f"claim — {label}: claim нет", False, repr(got))
    for label, payload in {"payload не JSON": b"{", "payload — список": b"[1]",
                           "payload не UTF-8": b"\xff\xfe"}.items():
        res.check(f"{label}: malformed", rv.open_envelope(_signed({}, k, payload=payload), keys)[0],
                  rv.MALFORMED)


def suite_pure(res: Result) -> None:
    """Модуль проверки: только стандартная библиотека, ни диска, ни окружения."""
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    res.check("импорты — только из разрешённого списка", sorted(imported - ALLOWED_IMPORTS), [])
    res.ok("нет относительных импортов проекта",
           not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    res.ok("ни open, ни __file__, ни environ", not ({"open", "__file__"} & names or "environ" in attrs))
    res.ok("сравнение блока — hmac.compare_digest", "compare_digest" in attrs)
    res.ok("подпись считается через pow", "pow" in names)
    res.ok("часы модулю не нужны", "now" not in attrs and "utcnow" not in attrs)
    res.check("KEYS: тестового ключа в программе нет", [k for k in rv.KEYS if k == "test"], [])
    res.ok("KEYS: пока пусто — первый боевой ключ ложится с L7", rv.KEYS == {})
