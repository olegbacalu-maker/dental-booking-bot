# Архитектура DentPilot 2.0

Один продукт, две половины: **новый клиент** и **прежний движок**. Движок —
источник истины; клиент — только интерфейс.

```
                    DentPilot 2.0
                          │
              ┌───────────┴───────────┐
              │                       │
        React + TypeScript      Python / FastAPI
              │                       │
           Tauri                 Бизнес-правила
              │                       │
        Windows EXE                Вход и права
                                      │
                                   SQLite
                                      │
                                  data\files\
```

Поток запроса:

```
компонент → services/api.ts → /api/* → FastAPI → db.py → SQLite
```

Доставка обновлений:

```
git tag → GitHub Actions → GitHub Release
                                │
                     существующий update.py
                                │
                  проверка → подмена exe → перезапуск
```

## Граница

| Слой | Владеет | Файлы |
|---|---|---|
| Клиент | отрисовка, ввод, состояние экрана | `frontend/` |
| API | конверт ответа, коды, права | `/api/*` — ⏳ не построен |
| Движок | данные, расчёты, вход, печать, обновления | `bot/` — не трогается |

⛔ React не выполняет SQL, не читает файлы базы, не повторяет серверные расчёты
и не меняет данные клиники мимо API.

## Что остаётся серверным навсегда

**Печать** — 043/e, acord, plan-acord, пародонтограмма, анамнеза, касса, лист
восстановления. У каждого свой `<!doctype>` и свой инлайновый CSS; они
печатаются, даже если бандл не загрузился. Приказ МЗ 828/2011, хранение 5 лет.

**Аварийные экраны** — вход, установка PIN, восстановление, `CONFIG_BROKEN`,
обновление, перезапуск. Экран, который обязан открыться, когда бандл не
поднялся, не может жить в бандле.

**Общие контракты** — тема, иконки, тексты ответов. Подробности —
[design-system.md](design-system.md).

## Origin — почему один

Страницу и API отдаёт **один и тот же** FastAPI на `http://127.0.0.1:<порт>`.
На этом держатся три механизма движка:

- кука `admin_auth` с `samesite=lax` — на чужой origin она не уйдёт;
- `same_origin_post()` сверяет `Origin` с `Host` и иначе отвечает 403;
- `client_is_local()` отличает рабочее место от телефона в LAN.

⛔ Окно на `tauri.localhost` сломало бы все три сразу: вход отвечал бы 403 ещё
до ввода пароля. Поэтому `index.html` отдаёт FastAPI, а Tauri открывает окно
на его адрес.

## Читать дальше

[api.md](api.md) · [frontend.md](frontend.md) · [design-system.md](design-system.md)
· [features.md](features.md) · [screen-test-map.md](screen-test-map.md)
· [tauri.md](tauri.md) · [sidecar.md](sidecar.md) · [installer.md](installer.md)
· [updates.md](updates.md) · [release.md](release.md) · [migration.md](migration.md)

Аудит, с которого всё началось — [../migration-audit.md](../migration-audit.md).
