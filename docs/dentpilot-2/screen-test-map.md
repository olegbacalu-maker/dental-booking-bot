# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **191** · наборов **65** · мест вызова `res.ok`/`res.check` в исходниках — **4309**.


⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть
вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок
на самом деле, говорит сам прогон (`.\dev test`).


⛔ Адресов, которые сборщик не смог разобрать: **0** — маршрут, объявленный через константу, раньше выпадал из карты
ЦЕЛИКОМ и молча: число маршрутов не менялось, жалобы не было.


## Маршруты без единой проверки


| Маршрут | Тип | стр | Замечание |
|---|---|---|---|

⭐ Находка **не про миграцию**: `POST /admin/update/run` запускает подмену exe у клиники, а наборы называют его только отказом в демо (`test_demo`) — сам запуск не покрыт ничем. Счёт выше лексический: упоминание адреса ещё не проверка.


## Настройки — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, demo, license_existing, pin, privacy, settings_api | 615 | — |
| `GET /admin/settings` | HTML | 7 | admin, api, demo, pin, settings_api | 908 | settings_hub |
| `GET /admin/settings/backup` | HTML | 7 | demo, settings_api | 292 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 6 | admin, api, demo, doctors, settings_api | 920 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 12 | demo, settings_api | 292 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 10 | dbcrypt, demo, settings_api | 369 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 61 | dbcrypt, settings_api | 324 | — |
| `GET /admin/settings/faq` | HTML | 7 | admin, demo, paylink, pin, settings_api | 865 | settings_faq |
| `GET /admin/settings/hours` | HTML | 5 | admin, demo, settings_api | 723 | settings_hours |
| `GET /admin/settings/lan` | HTML | 7 | admin, demo, settings_api | 723 | settings_lan |
| `GET /admin/settings/security` | HTML | 7 | demo, pin, settings_api | 396 | settings_security |
| `GET /admin/settings/services` | HTML | 5 | admin, demo, settings_api | 723 | settings_services |
| `GET /admin/settings/system` | HTML | 5 | admin, demo, pin, settings_api, update_server | 846 | settings_system |
| `GET /admin/settings/telegram` | HTML | 19 | admin, demo, settings_api | 723 | — |
| `GET /admin/settings/theme` | HTML | 13 | demo, settings_api, theme | 395 | settings_theme |
| `POST /admin/telegram/save` | HTML | 26 | demo | 45 | — |
| `POST /admin/update/run` | HTML | 21 | demo | 45 | — |
| `GET /api/settings/backup` | JSON | 9 | demo, settings_api | 292 | — |
| `GET /api/settings/clinic` | JSON | 4 | admin, api, pin, privacy | 735 | — |
| `POST /api/settings/clinic` | JSON | 26 | admin, api, pin, privacy | 735 | — |
| `GET /api/settings/crypt` | JSON | 4 | demo, settings_api | 292 | — |
| `POST /api/settings/crypt/off` | JSON | 14 | settings_api | 247 | — |
| `POST /api/settings/crypt/prepare` | JSON | 15 | dbcrypt, settings_api | 324 | — |
| `GET /api/settings/faq` | JSON | 4 | admin, dbcrypt, paylink, settings_api | 793 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 678 | — |
| `POST /api/settings/hours` | JSON | 16 | admin, settings_api | 678 | — |
| `GET /api/settings/hub` | JSON | 8 | admin, api, demo, paylink, settings_api, theme, update_server | 964 | — |
| `GET /api/settings/lan` | JSON | 8 | admin, settings_api | 678 | — |
| `POST /api/settings/lan` | JSON | 21 | admin, settings_api | 678 | — |
| `POST /api/settings/lan/firewall` | JSON | 9 | settings_api | 247 | — |
| `POST /api/settings/pin` | JSON | 14 | demo, pin, review3_auth, settings_api | 425 | — |
| `GET /api/settings/security` | JSON | 7 | demo, pin, settings_api | 396 | — |
| `GET /api/settings/services` | JSON | 4 | admin, review2, settings_api | 694 | — |
| `POST /api/settings/services` | JSON | 27 | admin, review2, settings_api | 694 | — |
| `GET /api/settings/system` | JSON | 4 | admin, demo, privileged, settings_api | 808 | — |
| `POST /api/settings/system/check` | JSON | 14 | settings_api | 247 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 85 | — |
| `GET /api/settings/theme` | JSON | 4 | admin, settings_api, theme | 781 | — |
| `POST /api/settings/theme` | JSON | 23 | admin, settings_api, theme | 781 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | privacy, settings_api, theme | 469 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api, theme | 350 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api, theme | 350 | — |
| `POST /api/settings/users` | JSON | 14 | api, demo, desk, doctors, license_renew, migrate, patient_card, patients_api, paylink, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1323 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | doctors, license_gate, odontogram_api, patient_card, perio_api, pin, settings_api, theme | 931 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 157 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1021 | doctor_card |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1021 | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1021 | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 14 | admin, admin_canvas, anamneza, api, day_actions, day_forms, demo, doctors, patient_card, patients_api, perio_api, pin, plan_acord, privacy, restart, review2, review3, settings_api, visit | 1999 | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, demo, doctors, perio_api, pin, review2, review3, settings_api | 1329 | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 116 | — |
| `GET /admin/medici` | HTML | 52 | admin, demo, doctors, pin, settings_api | 943 | doctors_list |
| `POST /admin/medici/add` | 303 | 7 | doctors | 116 | — |
| `POST /admin/medici/colors` | 303 | 4 | doctors | 116 | — |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors, license_page | 270 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 657 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 657 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 116 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin_canvas, day_forms, doctors | 306 | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin_canvas, day_forms, doctors | 306 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin_canvas, day_forms, doctors | 306 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin_canvas, day_forms, doctors | 306 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_forms, demo, doctors, review2, review3, settings_api | 1081 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, desk, pin, stats_api, theme | 736 | — |
| `GET /admin/stats` | HTML | 26 | admin, api, booking, demo, patients_api, pin, review3, stats_api | 935 | stats |
| `GET /api/stats` | JSON | 21 | demo, stats_api | 118 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 431 | — |
| `GET /demo` | HTML | 14 | admin | 431 | — |
| `GET /qr` | other | 5 | settings_api | 247 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy, scan | 385 | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 5 | hardening, license_gate, patient_card, privacy, scan | 401 | — |
| `GET /admin/patient/{pid}` | HTML | 837 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/alert` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 14 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2291 | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 17 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/doc` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/erase` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, demo, desk, doctors, guards, hardening, license_existing, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, settings_api, stats_api, teeth, visit, visit_api | 2622 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 29 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 38 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 49 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/pay` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `GET /admin/patient/{pid}/peek` | HTML | 11 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/perio` | 303 | 29 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/plan` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 25 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 5 | activity, admin, anamneza, booking, bot, chair, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, scan, schedule_api, stats_api, teeth, visit, visit_api | 2472 | — |
| `POST /admin/patient/{pid}/save` | 303 | 8 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_actions, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, restart, review2, settings_api, stats_api, teeth, visit, visit_api | 2790 | — |
| `GET /admin/patient/{pid}/slots` | JSON | 6 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 54 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2275 | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 447 | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin, patients_api | 509 | — |
| `POST /admin/patients/new` | 303 | 16 | admin, anamneza, dbcrypt, doctors, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, review2, scan, teeth, visit | 1630 | — |
| `GET /admin/search` | HTML | 323 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, demo, desk, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3, scan, teeth, visit, visit_api | 2035 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 21 | day_forms, patient_card, plan_acord, visit, visit_api | 413 | visit |
| `POST /admin/visit/{appt_id}` | 303 | 13 | day_forms, patient_card, plan_acord, visit, visit_api | 413 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card | 257 | — |
| `GET /api/patients` | JSON | 34 | demo, license_existing, license_gate, license_page, license_renew, patients_api, paylink, react_default, stats_api | 429 | — |
| `POST /api/patients` | JSON | 18 | demo, license_existing, license_gate, license_page, license_renew, patients_api, paylink, react_default, stats_api | 429 | — |
| `GET /api/patients/summary` | JSON | 31 | patients_api | 78 | — |
| `GET /api/patients/{pid}` | JSON | 8 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 7 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api, theme | 1138 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | anamneza, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, privacy, react_default, scan | 769 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | admin, booking, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 1086 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | admin, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 999 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api, theme | 1138 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 7 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api, theme | 1138 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | anamneza, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api, privacy, react_default, scan, teeth, visit | 1051 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api, theme | 1138 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | admin, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, review2, scan | 1015 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api, react_default, scan | 595 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api, theme | 1138 | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, react_default, review2, scan, teeth, visit, visit_api | 1503 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api, theme | 1138 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, chair, demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, react_default, review2, scan, schedule_api, visit, visit_api | 1594 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/scan/cancel` | JSON | 5 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/scan/finish` | JSON | 25 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/scan/page` | JSON | 15 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 36 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 568 | — |
| `GET /api/scan/status` | JSON | 6 | scan | 25 | — |
| `GET /api/visits/{aid}` | JSON | 9 | chair, visit_api | 102 | — |
| `POST /api/visits/{aid}` | JSON | 23 | chair, visit_api | 102 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 190 | admin, admin_canvas, api, booking, chair, day_forms, dbcrypt, demo, desk, doctors, hardening, license_existing, license_gate, license_page, license_renew, migrate, panel_model, patient_card, patients_api, paylink, pin, react_default, review3_auth, schedule_api, settings_api, split, stats_api, structure, theme, update_server, visit_api | 2723 | schedule_dash |
| `POST /admin/add` | other | 14 | activity, admin, admin_canvas, booking, bot, chair, day_actions, day_forms, desk, doctor_windows, doctors, hardening, migrate, patient_card, patients_api, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 2029 | — |
| `GET /admin/all` | HTML | 65 | activity, admin, admin_canvas, api, booking, bot, day_actions, day_forms, demo, desk, doctor_windows, doctors, hardening, migrate, panel_model, patient_card, patients_api, pin, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 2289 | schedule_all |
| `GET /admin/cabinet` | HTML | 17 | chair | 47 | chair |
| `POST /admin/comment/{appt_id}` | other | 5 | day_actions, day_forms, privacy, visit_api | 299 | — |
| `GET /admin/doctor/{dk}` | HTML | 57 | admin, admin_canvas, api, chair, day_forms, doctor_windows, grid, pin, review3, schedule_api | 1080 | schedule_doctor |
| `GET /admin/export` | FILE | 35 | admin | 431 | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin, day_forms | 511 | — |
| `POST /admin/move/{appt_id}` | other | 9 | booking, day_actions, day_forms, doctor_windows | 242 | — |
| `POST /admin/note` | other | 9 | admin, admin_canvas, booking, chair, day_actions, day_forms, schedule_api | 925 | — |
| `POST /admin/status/{appt_id}` | 303 | 11 | activity, admin, admin_canvas, booking, day_forms, doctor_windows, panel_model, patient_card, plan_acord, privacy, review3, schedule_api, visit, visit_api | 1434 | — |
| `GET /admin/week` | HTML | 43 | admin, demo, react_default, schedule_api | 612 | schedule_week |
| `GET /api/chair` | JSON | 29 | chair | 47 | — |
| `POST /api/schedule/appointments` | JSON | 22 | day_actions | 45 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 16 | chair, day_actions, desk, doctors, schedule_api | 358 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 18 | booking, chair, day_actions, desk, doctor_windows, doctors, schedule_api | 475 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 18 | activity, admin, chair, day_actions, desk, doctors, patient_card, patients_api, plan_acord, privacy, review2, scan, schedule_api, visit, visit_api | 1366 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas, harness_clock, schedule_api | 249 | — |
| `GET /api/schedule/day` | JSON | 17 | day_actions, desk, schedule_api | 195 | — |
| `POST /api/schedule/desk/call/{aid}` | JSON | 25 | admin_canvas, desk | 135 | — |
| `GET /api/schedule/live` | JSON | 36 | demo, desk, panel_model, schedule_api | 272 | — |
| `POST /api/schedule/notes` | JSON | 19 | day_actions | 45 | — |
| `GET /api/schedule/week` | JSON | 14 | schedule_api | 125 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, admin_canvas, anamneza, api, booking, bot, chair, day_forms, dbcrypt, demo, desk, dev, doctor_windows, doctors, grid, guards, hardening, harness_clock, harness_tmp, installer, launcher, legacy, license_existing, license_format, license_gate, license_page, license_renew, license_state, license_verify, migrate, netcheck, odontogram_api, panel_model, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, privileged, react_default, relocate, restart, review2, review3, review3_auth, review3_bot, scan, schedule_api, settings_api, split, srcpin, structure, teeth, theme, update_server, update_setup, visit, visit_api | 4185 | — |
| `GET /admin/license` | HTML | 9 | demo, license_existing, license_page, license_renew, paylink | 251 | — |
| `POST /admin/license` | 303 | 22 | demo, license_existing, license_page, license_renew, paylink | 251 | — |
| `POST /admin/license/renew` | 303 | 10 | license_renew, paylink | 139 | — |
| `POST /admin/license/request` | 303 | 19 | license_page, license_renew | 145 | — |
| `POST /admin/license/verify` | 303 | 12 | license_renew | 101 | — |
| `GET /admin/login` | HTML | 34 | admin, api, chair, demo, desk, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, review3_auth, settings_api, stats_api, theme, visit_api | 2063 | — |
| `POST /admin/login` | 303 | 66 | admin, api, chair, demo, desk, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, review3_auth, settings_api, stats_api, theme, visit_api | 2063 | — |
| `GET /admin/logout` | 303 | 6 | demo | 45 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 151 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 151 | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 104 | — |
| `GET /admin/setup` | HTML | 12 | api, desk, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1213 | — |
| `POST /admin/setup` | HTML | 17 | api, desk, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1213 | — |
| `GET /api/license` | JSON | 6 | demo, license_existing, license_page, license_renew | 213 | — |
| `POST /chat` | other | 13 | admin, bot, hardening, license_gate, review3_bot | 560 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 350 | — |
| `GET /favicon.ico` | other | 5 | admin, demo | 476 | — |
| `GET /health` | other | 4 | admin, demo, hardening, license_renew, netcheck | 692 | — |
| `GET /icon-{px}.png` | other | 11 | admin, demo | 476 | — |
| `GET /manifest.webmanifest` | other | 31 | admin, demo | 476 | — |
| `GET /plata/{ticket}` | HTML | 16 | paylink | 38 | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, demo, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, structure, visit_api | 1571 | — |

## Прочее — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/migration` | HTML | 45 | guards, split | 85 | — |
| `POST /admin/migration/confirm` | 303 | 32 | split | 44 | — |

## Колонки-состояния


`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности. С 21.09 она отдаётся ПО УМОЛЧАНИЮ: `ui.react` в профиле стал аварийным выключателем, а не рубильником выката (`?ui=legacy` по-прежнему возвращает старую страницу на один запрос). `—` значит «страница серверная по замыслу» — печать и аварийные экраны.


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 837 | `GET /admin/patient/{pid}` | 25 |
| 323 | `GET /admin/search` | 24 |
| 190 | `GET /admin` | 31 |
| 157 | `GET /admin/doctor-card/{dk}` | 8 |
| 66 | `POST /admin/login` | 21 |
| 65 | `GET /admin/all` | 28 |
| 61 | `GET /admin/settings/crypt/sheet` | 2 |
| 57 | `GET /admin/doctor/{dk}` | 10 |
| 54 | `POST /admin/patient/{pid}/tooth` | 25 |
| 54 | `GET /admin/qr-print` | 1 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
