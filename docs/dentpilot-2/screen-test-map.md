# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **109** · наборов **24** · мест вызова `res.ok`/`res.check` в исходниках — **1656**.


⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть
вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок
на самом деле, говорит сам прогон (`.\dev test`).


## Маршруты без единой проверки


| Маршрут | Тип | стр | Замечание |
|---|---|---|---|
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | отдача фото врача |
| `POST /admin/lan/firewall` | 303 | 9 | правило брандмауэра, ⚠️ зовёт netsh через runas |
| `GET /admin/logout` | 303 | 6 | выход из журнала |
| `POST /admin/medici/add` | 303 | 23 | добавление врача |
| `POST /admin/medici/colors` | 303 | 8 | цвета врачей |
| `POST /admin/relink` | 303 | 12 | перепривязка врача |
| `GET /admin/settings/backup` | HTML | 17 | страница бэкапа (экспорт проверен отдельно) |
| `GET /admin/settings/crypt` | HTML | 66 | ⚠️ действия (`prepare`/`sheet`/`confirm`) проверены, САМА СТРАНИЦА не открывается ни разу |
| `POST /admin/settings/crypt/off` | 303 | 8 | выключение шифрования картотеки |
| `POST /admin/telegram/save` | HTML | 26 | сохранение токена бота (заморожен, но маршрут жив) |
| `POST /admin/update/check` | 303 | 7 | проверка обновлений |
| `POST /admin/update/run` | HTML | 21 | **самообновление** — спусковой крючок не проверен ничем |
| `GET /qr` | other | 5 | печатная страница QR |

⭐ Находка **не про миграцию**: дыры есть уже сейчас. `POST /admin/update/run` запускает подмену exe у клиники и не покрыт ничем.


## Настройки — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, pin, privacy | 280 | — | — |
| `POST /admin/lan/firewall` | 303 | 9 | **—** | — | — | — |
| `POST /admin/lan/save` | HTML | 21 | admin | 376 | — | — |
| `GET /admin/settings` | HTML | 86 | admin, pin, theme | 554 | — | — |
| `GET /admin/settings/backup` | HTML | 17 | **—** | — | — | — |
| `GET /admin/settings/clinic` | HTML | 21 | admin | 376 | — | — |
| `GET /admin/settings/crypt` | HTML | 66 | **—** | — | — | — |
| `POST /admin/settings/crypt/confirm` | 303 | 22 | dbcrypt | 77 | — | — |
| `POST /admin/settings/crypt/off` | 303 | 8 | **—** | — | — | — |
| `POST /admin/settings/crypt/prepare` | 303 | 20 | dbcrypt | 77 | — | — |
| `GET /admin/settings/crypt/sheet` | HTML | 66 | dbcrypt | 77 | — | — |
| `GET /admin/settings/faq` | HTML | 6 | admin, dbcrypt, pin | 556 | — | — |
| `GET /admin/settings/hours` | HTML | 60 | admin | 376 | — | — |
| `GET /admin/settings/lan` | HTML | 6 | admin | 376 | — | — |
| `POST /admin/settings/save` | 303 | 38 | admin, pin, review2, theme | 573 | — | — |
| `GET /admin/settings/security` | HTML | 26 | pin, review2 | 122 | — | — |
| `GET /admin/settings/services` | HTML | 115 | admin, review2 | 395 | — | — |
| `GET /admin/settings/system` | HTML | 80 | admin, pin | 479 | — | — |
| `GET /admin/settings/telegram` | HTML | 19 | admin | 376 | — | — |
| `GET /admin/settings/theme` | HTML | 135 | theme | 75 | — | — |
| `POST /admin/settings/theme/logo` | 303 | 32 | theme | 75 | — | — |
| `GET /admin/settings/theme/palette` | JSON | 11 | theme | 75 | — | — |
| `POST /admin/telegram/save` | HTML | 26 | **—** | — | — | — |
| `POST /admin/update/check` | 303 | 7 | **—** | — | — | — |
| `POST /admin/update/run` | HTML | 21 | **—** | — | — | — |
| `POST /admin/users/delete` | other | 11 | pin | 103 | — | — |
| `POST /admin/users/save` | other | 28 | migrate, pin, review2, review3_auth | 299 | — | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 182 | admin, pin, review3 | 515 | — | — |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 29 | admin, pin, review3 | 515 | — | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 11 | admin, pin, review3 | 515 | — | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 36 | admin, anamneza, migrate, pin, plan_acord, privacy, review2, review3, review3_auth, theme, visit | 1074 | — | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 44 | admin, pin, review2, review3 | 534 | — | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | **—** | — | — | — |
| `GET /admin/medici` | HTML | 46 | admin, pin | 479 | — | — |
| `POST /admin/medici/add` | 303 | 23 | **—** | — | — | — |
| `POST /admin/medici/colors` | 303 | 8 | **—** | — | — | — |
| `POST /admin/relink` | 303 | 12 | **—** | — | — | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, pin, theme | 554 | — | — |
| `GET /admin/stats` | HTML | 291 | admin, booking, pin, review3 | 601 | — | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 376 | — | — |
| `GET /demo` | HTML | 14 | admin | 376 | — | — |
| `GET /qr` | other | 5 | **—** | — | — | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, privacy | 174 | — | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 25 | hardening, privacy | 174 | — | — |
| `GET /admin/patient/{pid}` | HTML | 909 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/alert` | 303 | 10 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 5 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 21 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 10 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 35 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 28 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 9 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/doc` | 303 | 35 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 9 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/erase` | 303 | 31 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, dbcrypt, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1391 | — | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 28 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 27 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 36 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/pay` | 303 | 16 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/peek` | HTML | 106 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/perio` | 303 | 32 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 9 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/plan` | 303 | 23 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 24 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 16 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 18 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/save` | 303 | 56 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, review3_auth, teeth, theme, visit | 1418 | — | — |
| `GET /admin/patient/{pid}/slots` | JSON | 18 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 77 | activity, admin, anamneza, booking, bot, hardening, migrate, perio, pin, plan_acord, privacy, review2, teeth, visit | 1314 | — | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 395 | — | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin | 376 | — | — |
| `POST /admin/patients/new` | 303 | 48 | admin, anamneza, dbcrypt, hardening, perio, pin, review2, teeth, visit | 983 | — | — |
| `GET /admin/search` | HTML | 308 | activity, admin, anamneza, booking, bot, dbcrypt, hardening, perio, pin, plan_acord, privacy, review2, review3, teeth, visit | 1279 | — | — |
| `GET /admin/visit/{appt_id}` | HTML | 15 | plan_acord, visit | 111 | — | — |
| `POST /admin/visit/{appt_id}` | 303 | 33 | plan_acord, visit | 111 | — | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin` | HTML | 162 | admin, booking, dbcrypt, hardening, migrate, pin, review3_auth, theme | 968 | — | — |
| `POST /admin/add` | other | 104 | activity, admin, booking, bot, doctor_windows, hardening, migrate, plan_acord, privacy, review2, review3, review3_bot, visit | 1025 | — | — |
| `GET /admin/all` | HTML | 49 | activity, admin, booking, bot, doctor_windows, hardening, migrate, pin, plan_acord, privacy, review2, review3, review3_bot, visit | 1128 | — | — |
| `POST /admin/comment/{appt_id}` | other | 6 | privacy | 100 | — | — |
| `GET /admin/doctor/{dk}` | HTML | 50 | admin, doctor_windows, pin, review3 | 545 | — | — |
| `GET /admin/export` | FILE | 35 | admin | 376 | — | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin | 376 | — | — |
| `POST /admin/move/{appt_id}` | other | 42 | booking, doctor_windows | 116 | — | — |
| `POST /admin/note` | other | 35 | booking | 86 | — | — |
| `POST /admin/status/{appt_id}` | 303 | 16 | activity, admin, booking, doctor_windows, plan_acord, privacy, review3, visit | 745 | — | — |
| `GET /admin/week` | HTML | 56 | admin | 376 | — | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, anamneza, booking, bot, dbcrypt, doctor_windows, guards, hardening, launcher, migrate, perio, pin, plan_acord, privacy, restart, review2, review3, review3_auth, review3_bot, structure, teeth, theme, visit | 1656 | — | — |
| `GET /admin/login` | HTML | 34 | admin, hardening, migrate, pin, review3_auth, theme | 805 | — | — |
| `POST /admin/login` | 303 | 66 | admin, hardening, migrate, pin, review3_auth, theme | 805 | — | — |
| `GET /admin/logout` | 303 | 6 | **—** | — | — | — |
| `POST /admin/pin/change` | 303 | 33 | pin, review3_auth | 132 | — | — |
| `GET /admin/recover` | HTML | 6 | dbcrypt, hardening | 151 | — | — |
| `POST /admin/recover` | HTML | 17 | dbcrypt, hardening | 151 | — | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 103 | — | — |
| `GET /admin/setup` | HTML | 12 | hardening, migrate, pin, review2, review3_auth | 373 | — | — |
| `POST /admin/setup` | HTML | 17 | hardening, migrate, pin, review2, review3_auth | 373 | — | — |
| `POST /chat` | other | 13 | admin, bot, hardening, review3_bot | 489 | — | — |
| `GET /clinic-logo` | other | 20 | theme | 75 | — | — |
| `GET /favicon.ico` | other | 5 | admin | 376 | — | — |
| `GET /health` | other | 4 | admin, hardening | 450 | — | — |
| `GET /icon-{px}.png` | other | 11 | admin | 376 | — | — |
| `GET /manifest.webmanifest` | other | 31 | admin | 376 | — | — |
| `GET /static/{kind}/{name}` | other | 28 | admin | 376 | — | — |

## Колонки-состояния


`Флаг` — ключ в `clinic.json`, включающий React-экран (§29).
`Пилот` — `off` / `on` / `откат`. Заполняются по ходу; `—` значит «ещё не начат».


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 909 | `GET /admin/patient/{pid}` | 14 |
| 308 | `GET /admin/search` | 15 |
| 291 | `GET /admin/stats` | 4 |
| 182 | `GET /admin/doctor-card/{dk}` | 3 |
| 162 | `GET /admin` | 8 |
| 135 | `GET /admin/settings/theme` | 1 |
| 115 | `GET /admin/settings/services` | 2 |
| 106 | `GET /admin/patient/{pid}/peek` | 14 |
| 104 | `POST /admin/add` | 13 |
| 86 | `GET /admin/settings` | 3 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
