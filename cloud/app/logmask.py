"""Секрет уведомлений sms.md — мимо журнала доступа (16.10, проверка живого сервера).

sms.md не подписывает уведомление о доставке и не умеет слать свой заголовок,
поэтому секрет живёт в ПУТИ: `/v1/smsmd/dlr/<секрет>` (sms.md › «Сервер»). А
журнал доступа uvicorn печатает путь каждого запроса целиком — после первого же
уведомления секрет лежал в `docker compose logs` открытым текстом.

Фильтр на логгере `uvicorn.access` заменяет секрет меткой до того, как строка
попадёт в любой обработчик. Ставится при импорте `app.main`: uvicorn настраивает
логирование раньше, чем импортирует приложение, поэтому фильтр переживает его
настройку. Caddy пути не пишет (в `Caddyfile` нет `log`).
"""
from __future__ import annotations

import logging
import re

ACCESS = "uvicorn.access"
LABEL = "<секрет>"
# всё до следующего «/», «?», пробела или кавычки — путь в строке журнала стоит в кавычках
_DLR = re.compile(r"(/v1/smsmd/dlr/)[^/?\s\"]+")


def mask(text: str) -> str:
    return _DLR.sub(r"\g<1>" + LABEL, text)


class AccessMask(logging.Filter):
    """Правит запись, а не отбрасывает: строка доступа нужна, секрет в ней — нет.
    uvicorn кладёт путь в `record.args` (формат `%s - "%s %s HTTP/%s" %d`), поэтому
    маскируются и аргументы, и само сообщение."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(mask(a) if isinstance(a, str) else a for a in record.args)
        return True


def install() -> None:
    lg = logging.getLogger(ACCESS)
    if not any(isinstance(f, AccessMask) for f in lg.filters):
        lg.addFilter(AccessMask())
