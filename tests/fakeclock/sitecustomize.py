"""Поддельные часы для СЕРВЕРА прогона — половина `harness.Clock`.

Харнесс кладёт эту папку в PYTHONPATH сервера и называет файл сдвига в
FAKECLOCK_FILE; `site` сам импортирует `sitecustomize` при старте
интерпретатора — до первой строки uvicorn и программы. Без FAKECLOCK_FILE
модуль не делает НИЧЕГО. Больше в этой папке ничего лежать не должно: она
целиком оказывается на пути импорта сервера.

Что двигается. Модули `app` и `app.*`: после исполнения тела модуля имена в
его глобалах, указывающие на `datetime.datetime` / `datetime.date` (стиль
проекта — `from datetime import date, datetime`), подменяются подклассами, у
которых now()/today()/utcnow() прибавляют сдвиг. Сдвиг (секунды) читается из
файла на КАЖДОМ вызове — часы живого сервера переставляются переписыванием
файла (`Clock.set`), а сами идут вперёд, как настоящие.

⛔ Глобально `datetime.datetime` НЕ подменяется: pydantic.v1 наследует `date`
своим метаклассом, и сервер падал на старте с пустым логом («metaclass
conflict», 24.09). Библиотеки живут по настоящим часам, двигается программа.
⭐ Сдвиг прибавляется к UTC, и только потом `astimezone(tz)`. У aware-даты
сложение идёт по СТЕННЫМ часам: `now(tz) + сдвиг` через переход на зимнее
время ошибся бы ровно на час. Та же формула — у прогона (`harness.Clock.now`);
что они сходятся через переход, держит «Харнесс: поддельные часы».
⚠️ Конструкторы возвращают НАСТОЯЩИЕ datetime/date (`__new__`), isinstance
отвечает за базовый тип через метакласс. `type(x) is datetime` в программе
ответил бы False — таких мест в ней нет.
⚠️ Чего часы НЕ достают — имя берётся у модуля `datetime` в момент вызова, а
не из глобалов: `import datetime as dt` + `dt.datetime.now()`
(modules/migration/routes.py) и `from datetime import datetime` ВНУТРИ функции
(modules/patients/anamneza.render_form — дата на бумажном бланке). Мимо часов
идут и `time.time()`/`time.monotonic()`: это длительности (TTL сессии,
счётчик попыток), а сдвиг постоянен — они и так правы.

Строка `[fakeclock]` в stderr — отметка для харнесса: без неё сервер, у
которого часы не встали (PYTHONPATH не дошёл, модуль упал), жил бы по
настоящему времени молча. Только ASCII: stderr сервера пишется в кодировке
консоли, а харнесс читает лог как UTF-8.
"""
import datetime as _dt
import os
import sys

_FILE = os.environ.get("FAKECLOCK_FILE", "")
_last = [_dt.timedelta(0)]


def _shift() -> _dt.timedelta:
    """Сдвиг из файла. Нечитаемый или пустой — ПРЕЖНИЙ, а не ноль: харнесс
    переписывает файл заменой, и чтение в это мгновение иначе на один
    вызов вернуло бы сервер в настоящее время."""
    try:
        with open(_FILE, encoding="utf-8") as f:
            _last[0] = _dt.timedelta(seconds=float(f.read()))
    except (OSError, ValueError):
        pass
    return _last[0]


class _Meta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, cls._real)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, cls._real)


class FakeDatetime(_dt.datetime, metaclass=_Meta):
    _real = _dt.datetime

    def __new__(cls, *a, **kw):
        return _dt.datetime(*a, **kw)

    @classmethod
    def now(cls, tz=None):
        t = _dt.datetime.now(_dt.timezone.utc) + _shift()
        return t.astimezone(tz) if tz is not None else t.astimezone().replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()

    @classmethod
    def utcnow(cls):
        return (_dt.datetime.now(_dt.timezone.utc) + _shift()).replace(tzinfo=None)


class FakeDate(_dt.date, metaclass=_Meta):
    _real = _dt.date

    def __new__(cls, *a, **kw):
        return _dt.date(*a, **kw)

    @classmethod
    def today(cls):
        return FakeDatetime.now().date()


def _patch(module) -> None:
    g = module.__dict__
    for key, val in list(g.items()):
        if val is _dt.datetime:
            g[key] = FakeDatetime
        elif val is _dt.date:
            g[key] = FakeDate


class _Finder:
    """Искатель на `sys.meta_path` только для программы: спеку находит
    следующий по списку искатель, здесь к загрузчику приделывается подмена
    ПОСЛЕ исполнения тела модуля."""

    def find_spec(self, name, path, target=None):
        if name != "app" and not name.startswith("app."):
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                break
        else:
            return None
        loader = spec.loader
        if loader is not None and hasattr(loader, "exec_module"):
            run = loader.exec_module

            def exec_module(module, _run=run):
                _run(module)
                _patch(module)

            loader.exec_module = exec_module
        return spec


if _FILE:
    sys.meta_path.insert(0, _Finder())
    sys.stderr.write(f"[fakeclock] pid {os.getpid()}: shift {_shift().total_seconds():+.0f} s,"
                     f" now {FakeDatetime.now(_dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n")
    sys.stderr.flush()
