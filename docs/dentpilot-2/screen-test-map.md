# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **153** · наборов **64** · мест вызова `res.ok`/`res.check` в исходниках — **3888**.


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
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, demo, license_existing, pin, privacy, settings_api | 608 | — |
| `GET /admin/settings` | HTML | 7 | admin, api, demo, pin, settings_api | 810 | settings_hub |
| `GET /admin/settings/backup` | HTML | 7 | demo, settings_api | 286 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 6 | admin, api, demo, settings_api | 706 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 12 | demo, settings_api | 286 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 10 | dbcrypt, demo, settings_api | 363 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 61 | dbcrypt, settings_api | 318 | — |
| `GET /admin/settings/faq` | HTML | 7 | admin, demo, paylink, pin, settings_api | 776 | settings_faq |
| `GET /admin/settings/hours` | HTML | 5 | admin, demo, settings_api | 634 | settings_hours |
| `GET /admin/settings/lan` | HTML | 7 | admin, demo, settings_api | 634 | settings_lan |
| `GET /admin/settings/security` | HTML | 7 | demo, pin, settings_api | 390 | settings_security |
| `GET /admin/settings/services` | HTML | 5 | admin, demo, settings_api | 634 | settings_services |
| `GET /admin/settings/system` | HTML | 5 | admin, demo, pin, settings_api, update_server | 757 | settings_system |
| `GET /admin/settings/telegram` | HTML | 19 | admin, demo, settings_api | 634 | — |
| `GET /admin/settings/theme` | HTML | 13 | demo, settings_api, theme | 389 | settings_theme |
| `POST /admin/telegram/save` | HTML | 26 | demo | 45 | — |
| `POST /admin/update/run` | HTML | 21 | demo | 45 | — |
| `GET /api/settings/backup` | JSON | 9 | demo, settings_api | 286 | — |
| `GET /api/settings/clinic` | JSON | 4 | admin, api, pin, privacy | 642 | — |
| `POST /api/settings/clinic` | JSON | 26 | admin, api, pin, privacy | 642 | — |
| `GET /api/settings/crypt` | JSON | 4 | demo, settings_api | 286 | — |
| `POST /api/settings/crypt/off` | JSON | 14 | settings_api | 241 | — |
| `POST /api/settings/crypt/prepare` | JSON | 15 | dbcrypt, settings_api | 318 | — |
| `GET /api/settings/faq` | JSON | 4 | admin, dbcrypt, paylink, settings_api | 704 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 589 | — |
| `POST /api/settings/hours` | JSON | 16 | admin, settings_api | 589 | — |
| `GET /api/settings/hub` | JSON | 8 | admin, api, demo, paylink, settings_api, theme, update_server | 866 | — |
| `GET /api/settings/lan` | JSON | 8 | admin, settings_api | 589 | — |
| `POST /api/settings/lan` | JSON | 21 | admin, settings_api | 589 | — |
| `POST /api/settings/lan/firewall` | JSON | 9 | settings_api | 241 | — |
| `POST /api/settings/pin` | JSON | 14 | demo, pin, review3_auth, settings_api | 419 | — |
| `GET /api/settings/security` | JSON | 7 | demo, pin, settings_api | 390 | — |
| `GET /api/settings/services` | JSON | 4 | admin, review2, settings_api | 605 | — |
| `POST /api/settings/services` | JSON | 27 | admin, review2, settings_api | 605 | — |
| `GET /api/settings/system` | JSON | 4 | admin, demo, privileged, settings_api | 720 | — |
| `POST /api/settings/system/check` | JSON | 14 | settings_api | 241 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 86 | — |
| `GET /api/settings/theme` | JSON | 4 | admin, settings_api, theme | 692 | — |
| `POST /api/settings/theme` | JSON | 23 | admin, settings_api, theme | 692 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | privacy, settings_api, theme | 462 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api, theme | 344 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api, theme | 344 | — |
| `POST /api/settings/users` | JSON | 14 | api, demo, desk, doctors, license_renew, migrate, patient_card, patients_api, paylink, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1207 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | activity, admin, doctors, hardening, license_gate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, settings_api, teeth, theme | 1536 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 11 | doctors, pin | 218 | doctor_card |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 114 | — |
| `GET /admin/medici` | HTML | 10 | admin, demo, doctors, pin, settings_api | 852 | doctors_list |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors, license_page | 243 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 547 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 547 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 114 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 858 | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 858 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 858 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 858 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_actions, day_forms, demo, doctors, perio_api, pin, review2, review3, settings_api | 1160 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, desk, pin, stats_api, theme | 635 | — |
| `GET /admin/stats` | HTML | 21 | admin, demo, patients_api, pin, review3, stats_api | 641 | stats |
| `GET /api/stats` | JSON | 21 | admin, demo, pin, stats_api | 552 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin, api, review3 | 453 | — |
| `GET /demo` | HTML | 14 | admin | 348 | — |
| `GET /qr` | other | 5 | settings_api | 241 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy, scan | 342 | — |
| `GET /admin/patient/{pid}` | HTML | 17 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 14 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, dbcrypt, demo, guards, license_existing, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, settings_api, teeth, visit, visit_api | 1911 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 29 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 24 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 24 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 25 | activity, anamneza, demo, guards, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, teeth, visit, visit_api | 1118 | — |
| `GET /admin/patients.xlsx` | FILE | 50 | admin, patients_api | 404 | — |
| `GET /admin/search` | HTML | 21 | admin, anamneza, demo, patient_card, patients_api, pin | 757 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 19 | patient_card, visit, visit_api | 220 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card | 215 | — |
| `GET /api/patients` | JSON | 27 | admin, anamneza, booking, bot, dbcrypt, demo, license_existing, license_gate, license_page, license_renew, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth | 1779 | — |
| `POST /api/patients` | JSON | 18 | admin, anamneza, booking, bot, dbcrypt, demo, license_existing, license_gate, license_page, license_renew, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth | 1779 | — |
| `GET /api/patients/summary` | JSON | 34 | admin, bot, patients_api | 419 | — |
| `GET /api/patients/{pid}` | JSON | 10 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, settings_api, stats_api, teeth, theme, visit, visit_api | 2380 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, settings_api, stats_api, teeth, theme, visit, visit_api | 2380 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, settings_api, stats_api, teeth, theme, visit, visit_api | 2380 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, settings_api, stats_api, teeth, theme, visit, visit_api | 2380 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, settings_api, stats_api, teeth, theme, visit, visit_api | 2380 | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, settings_api, stats_api, teeth, theme, visit, visit_api | 2380 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, admin_canvas, anamneza, booking, bot, chair, day_forms, demo, desk, doctors, hardening, license_existing, license_gate, migrate, odontogram_api, panel_model, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, schedule_api, stats_api, teeth, visit, visit_api | 2300 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/scan/cancel` | JSON | 5 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/scan/finish` | JSON | 25 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/scan/page` | JSON | 15 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 36 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, hardening, license_existing, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, stats_api, teeth, visit, visit_api | 1922 | — |
| `GET /api/scan/status` | JSON | 6 | scan | 25 | — |
| `GET /api/visits/{aid}` | JSON | 9 | chair, day_forms, patient_card, plan_acord, visit, visit_api | 373 | — |
| `POST /api/visits/{aid}` | JSON | 23 | chair, day_forms, patient_card, plan_acord, visit, visit_api | 373 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 28 | admin, admin_canvas, api, dbcrypt, demo, desk, doctors, hardening, license_existing, license_gate, license_page, license_renew, migrate, patient_card, patients_api, paylink, pin, react_default, review3_auth, schedule_api, settings_api, split, stats_api, structure, theme, update_server, visit_api | 2167 | schedule_dash |
| `GET /admin/all` | HTML | 17 | admin, admin_canvas, demo, doctors, pin, schedule_api, visit_api | 823 | schedule_all |
| `GET /admin/cabinet` | HTML | 10 | chair | 45 | chair |
| `GET /admin/doctor/{dk}` | HTML | 12 | admin, pin, schedule_api | 541 | schedule_doctor |
| `GET /admin/export.xlsx` | FILE | 39 | admin | 348 | — |
| `GET /admin/week` | HTML | 13 | admin, demo, schedule_api | 482 | schedule_week |
| `GET /api/chair` | JSON | 29 | admin, chair | 393 | — |
| `POST /api/schedule/appointments` | JSON | 22 | activity, admin, admin_canvas, bot, chair, day_actions, day_forms, desk, doctor_windows, doctors, hardening, patient_card, patients_api, plan_acord, privacy, react_default, review3_bot, schedule_api, stats_api, visit, visit_api | 1463 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 16 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_windows, doctors, panel_model, patient_card, privacy, schedule_api, visit, visit_api | 1306 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 18 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_windows, doctors, panel_model, patient_card, privacy, schedule_api, visit, visit_api | 1306 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 18 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_windows, doctors, panel_model, patient_card, patients_api, plan_acord, privacy, review2, scan, schedule_api, visit, visit_api | 1456 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas, harness_clock, schedule_api | 188 | — |
| `GET /api/schedule/day` | JSON | 17 | admin, day_actions, desk, pin, schedule_api | 609 | — |
| `POST /api/schedule/desk/call/{aid}` | JSON | 25 | admin_canvas, desk | 110 | — |
| `GET /api/schedule/live` | JSON | 30 | admin, demo, desk, schedule_api | 507 | — |
| `POST /api/schedule/notes` | JSON | 19 | admin, admin_canvas, booking, chair, day_actions, day_forms, schedule_api | 747 | — |
| `GET /api/schedule/week` | JSON | 14 | admin, schedule_api | 437 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /` | HTML | 6 | admin, admin_canvas, anamneza, api, booking, bot, chair, dbcrypt, demo, desk, dev, doctor_windows, doctors, guards, hardening, harness_clock, harness_tmp, installer, launcher, legacy, license_existing, license_format, license_gate, license_page, license_renew, license_state, license_verify, migrate, netcheck, odontogram_api, panel_model, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, privileged, react_default, relocate, restart, review2, review3, review3_auth, review3_bot, scan, schedule_api, settings_api, split, srcpin, structure, teeth, theme, update_server, update_setup, visit_api | 3666 | — |
| `GET /admin/license` | HTML | 9 | demo, license_existing, license_page, license_renew, paylink | 251 | — |
| `POST /admin/license` | 303 | 22 | demo, license_existing, license_page, license_renew, paylink | 251 | — |
| `POST /admin/license/renew` | 303 | 10 | license_renew, paylink | 139 | — |
| `POST /admin/license/request` | 303 | 19 | license_page, license_renew | 145 | — |
| `POST /admin/license/verify` | 303 | 12 | license_renew | 101 | — |
| `GET /admin/login` | HTML | 34 | admin, api, chair, demo, desk, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, review3_auth, settings_api, stats_api, theme, visit_api | 1862 | — |
| `POST /admin/login` | 303 | 66 | admin, api, chair, demo, desk, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, review3_auth, settings_api, stats_api, theme, visit_api | 1862 | — |
| `GET /admin/logout` | 303 | 6 | demo | 45 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 151 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 151 | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 104 | — |
| `GET /admin/setup` | HTML | 12 | api, desk, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1097 | — |
| `POST /admin/setup` | HTML | 17 | api, desk, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1097 | — |
| `GET /api/license` | JSON | 6 | demo, license_existing, license_page, license_renew | 213 | — |
| `POST /chat` | other | 13 | admin, bot, hardening, license_gate, review3_bot | 477 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 344 | — |
| `GET /favicon.ico` | other | 5 | admin, demo | 393 | — |
| `GET /health` | other | 4 | admin, demo, hardening, license_renew, netcheck | 609 | — |
| `GET /icon-{px}.png` | other | 11 | admin, demo | 393 | — |
| `GET /manifest.webmanifest` | other | 31 | admin, demo | 393 | — |
| `GET /plata/{ticket}` | HTML | 16 | paylink | 38 | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, demo, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, structure, visit_api | 1316 | — |

## Прочее — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/migration` | HTML | 43 | guards, split | 85 | — |
| `POST /admin/migration/confirm` | 303 | 32 | split | 44 | — |

## Колонки-состояния


`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности; старой страницы у неё нет (сняты по разделам 12–13.10, `legacy-removal.md`; ключ `ui.react` и `?ui=legacy` сняты там же). `—` значит «страница серверная по замыслу» — печать и аварийные экраны.


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 66 | `POST /admin/login` | 21 |
| 61 | `GET /admin/settings/crypt/sheet` | 2 |
| 54 | `GET /admin/qr-print` | 3 |
| 50 | `GET /admin/patients.xlsx` | 2 |
| 43 | `GET /admin/migration` | 2 |
| 40 | `POST /admin/backup/export` | 6 |
| 39 | `GET /admin/export.xlsx` | 1 |
| 36 | `POST /api/patients/{pid}/teeth/{tooth}` | 27 |
| 34 | `GET /admin/login` | 21 |
| 34 | `GET /api/patients/summary` | 3 |
