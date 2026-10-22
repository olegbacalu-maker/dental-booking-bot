"""Сторож перезапуска: план и аргументы `--watch` (11.10.2026; с 22.10 — только
договор с оболочкой).

До 11.10 перезапуск после обновления и после «применить настройки» делал
bat-файл, который планировщик Windows запускал в сеансе пользователя: чёрное
окно cmd висело на экране всё время тихой установки (слово Олега: «появляется
чёрное окошко и пару секунд ничего не происходит»). С тех пор планировщик
запускает ПРОГРАММУ в режиме `--watch`: она показывает заставку
«Se instalează actualizarea…», ждёт итога установщика и выхода прежней
программы и поднимает её снова.

⭐ Сторож — копия оболочки `DentPilot.exe --watch …` (`shell/src/watch.rs`,
Т10, 18.10). Python-сторож окна pywebview (`desktop._watch_mode`) снят
22.10.2026 вместе с окном: в движке pywebview нет. Здесь осталось то, что
движок отдаёт сторожу: план (`Plan`) и его аргументы (`argv_for`, их зовёт
`update._spawn_watch`), а также слова заставки и потолки ожидания — ⛔ в
константах, и `test_restart` сверяет их с `watch.rs`: разошедшийся текст не
краснеет ничем другим.

⛔ Сторож — ДРУГОЙ файл, чем программа в `Program Files`. Установщик закрывает
всё, что держит заменяемые файлы (`/CLOSEAPPLICATIONS`), а запущенный exe
держит собственный образ: сторож из `Program Files\\DentPilot.exe` установщик
убил бы вместе с программой, и перезапускать её стало бы некому. Поэтому
`update._watch_command` запускает КОПИЮ оболочки из папки клиники.

Итог установщика в файле (`privileged.RESULT_NAME`): «started» пишет
операция за UAC, когда установщик уже запущен (с 2.0.2), «ok»/«fail …» — сам
установщик (`/RESULT=`), «cancelled» — программа, когда отказалась от
обновления сама. «ok» без перевода строки — тоже «ok» (канарейка 03.10).
`pid` в плане — оболочка (родитель движка): она гасит движок сама и выходит
последней.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

FLAG = "--watch"
# Сколько ждать итога установщика: задача планировщика живёт не больше 10 минут
WAIT_S = 9 * 60
# После «ok»/«fail» — пока ПРЕЖНЯЯ оболочка не выйдет: иначе новая застанет
# «первый экземпляр» и отдаст запуск ему
EXIT_WAIT_S = 60.0
NO_RESULT = "-"

# Слова заставки сторожа — те же в `shell/src/watch.rs` (сверяет test_restart)
TEXT_INSTALL = "Se instalează actualizarea…"
TEXT_RESTART = "Se repornește DentPilot…"
TEXT_CLOSING = "Se închide versiunea curentă…"
TEXT_NEW = "Se pornește versiunea nouă…"
TEXT_ROLLBACK = "Actualizarea nu s-a instalat — se pornește versiunea curentă…"


@dataclass
class Plan:
    """Что сторожу делать. Все пути АБСОЛЮТНЫЕ: задача планировщика стартует
    в system32, окружения лаунчера у неё нет."""
    proof: pathlib.Path          # метка «сторож пошёл» — её ждёт `update._spawn_watch`
    task: str                    # имя задачи планировщика — снять за собой
    result: pathlib.Path | None  # итог установщика; None — простой перезапуск
    pid: int                     # прежний процесс, чей выход ждём (0 — не ждать)
    label: str                   # что написать на заставке: «1.40.2 › 1.40.3»
    primary: str                 # цвет темы клиники (#RRGGBB) — фон заставки
    profile: pathlib.Path        # свой профиль WebView2: профиль программы занят ею же
    launch: list[str] = field(default_factory=list)   # команда запуска программы


def argv_for(plan: Plan) -> list[str]:
    """Аргументы `--watch …` из плана; разбирает их `watch.rs` (`parse`)."""
    return [FLAG, str(plan.proof), plan.task, str(plan.result) if plan.result else NO_RESULT,
            str(plan.pid), plan.label, plan.primary, str(plan.profile), *plan.launch]
