# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **202** · наборов **61** · мест вызова `res.ok`/`res.check` в исходниках — **4162**.


⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть
вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок
на самом деле, говорит сам прогон (`.\dev test`).


⛔ Адресов, которые сборщик не смог разобрать: **0** — маршрут, объявленный через константу, раньше выпадал из карты
ЦЕЛИКОМ и молча: число маршрутов не менялось, жалобы не было.


## Маршруты без единой проверки


| Маршрут | Тип | стр | Замечание |
|---|---|---|---|
| `POST /admin/lan/firewall` | 303 | 10 | правило брандмауэра, ⚠️ зовёт netsh через runas |
| `GET /admin/logout` | 303 | 6 | выход из журнала |
| `POST /admin/update/run` | HTML | 21 | **самообновление** — спусковой крючок не проверен ничем |

⭐ Находка **не про миграцию**: дыры есть уже сейчас. `POST /admin/update/run` запускает подмену exe у клиники и не покрыт ничем.


## Настройки — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, demo, license_existing, pin, privacy, settings_api | 613 | — |
| `POST /admin/lan/firewall` | 303 | 10 | **—** | — | — |
| `POST /admin/lan/save` | HTML | 11 | admin, settings_api | 686 | — |
| `GET /admin/settings` | HTML | 23 | admin, api, demo, pin, settings_api, theme | 1001 | settings_hub |
| `GET /admin/settings/backup` | HTML | 20 | demo, settings_api | 291 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 31 | admin, api, demo, doctors, react_default, settings_api | 929 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 14 | demo, settings_api | 291 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 10 | dbcrypt, settings_api | 335 | — |
| `POST /admin/settings/crypt/off` | 303 | 6 | settings_api | 258 | — |
| `POST /admin/settings/crypt/prepare` | 303 | 6 | dbcrypt, demo | 110 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 61 | dbcrypt, settings_api | 335 | — |
| `GET /admin/settings/faq` | HTML | 9 | admin, dbcrypt, demo, paylink, pin, settings_api | 937 | settings_faq |
| `GET /admin/settings/hours` | HTML | 63 | admin, demo, settings_api | 719 | settings_hours |
| `GET /admin/settings/lan` | HTML | 12 | admin, demo, settings_api | 719 | settings_lan |
| `POST /admin/settings/save` | 303 | 42 | admin, api, license_page, pin, review2, settings_api, theme | 1031 | — |
| `GET /admin/settings/security` | HTML | 18 | demo, pin, review2, settings_api | 413 | settings_security |
| `GET /admin/settings/services` | HTML | 118 | admin, demo, review2, settings_api | 738 | settings_services |
| `GET /admin/settings/system` | HTML | 7 | admin, demo, pin, settings_api | 822 | settings_system |
| `GET /admin/settings/telegram` | HTML | 19 | admin, demo, settings_api | 719 | — |
| `GET /admin/settings/theme` | HTML | 169 | demo, settings_api, theme | 387 | settings_theme |
| `POST /admin/settings/theme/logo` | 303 | 15 | privacy, theme | 215 | — |
| `GET /admin/settings/theme/palette` | JSON | 11 | theme | 96 | — |
| `POST /admin/telegram/save` | HTML | 26 | demo | 33 | — |
| `POST /admin/update/check` | 303 | 7 | demo | 33 | — |
| `POST /admin/update/run` | HTML | 21 | **—** | — | — |
| `POST /admin/users/delete` | other | 5 | pin | 103 | — |
| `POST /admin/users/save` | other | 8 | api, demo, desk, doctors, license_renew, migrate, patient_card, patients_api, paylink, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1318 | — |
| `GET /api/settings/backup` | JSON | 9 | demo, settings_api | 291 | — |
| `GET /api/settings/clinic` | JSON | 4 | api, privacy | 202 | — |
| `POST /api/settings/clinic` | JSON | 27 | api, privacy | 202 | — |
| `GET /api/settings/crypt` | JSON | 4 | demo, settings_api | 291 | — |
| `POST /api/settings/crypt/off` | JSON | 14 | settings_api | 258 | — |
| `POST /api/settings/crypt/prepare` | JSON | 15 | settings_api | 258 | — |
| `GET /api/settings/faq` | JSON | 4 | settings_api | 258 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 686 | — |
| `POST /api/settings/hours` | JSON | 16 | admin, settings_api | 686 | — |
| `GET /api/settings/hub` | JSON | 8 | demo, paylink, settings_api | 329 | — |
| `GET /api/settings/lan` | JSON | 8 | settings_api | 258 | — |
| `POST /api/settings/lan` | JSON | 21 | settings_api | 258 | — |
| `POST /api/settings/lan/firewall` | JSON | 9 | settings_api | 258 | — |
| `POST /api/settings/pin` | JSON | 14 | settings_api | 258 | — |
| `GET /api/settings/security` | JSON | 7 | demo, settings_api | 291 | — |
| `GET /api/settings/services` | JSON | 4 | settings_api | 258 | — |
| `POST /api/settings/services` | JSON | 27 | settings_api | 258 | — |
| `GET /api/settings/system` | JSON | 4 | demo, privileged, settings_api | 358 | — |
| `POST /api/settings/system/check` | JSON | 14 | settings_api | 258 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 67 | — |
| `GET /api/settings/theme` | JSON | 4 | settings_api | 258 | — |
| `POST /api/settings/theme` | JSON | 22 | settings_api | 258 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | settings_api | 258 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api | 258 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api | 258 | — |
| `POST /api/settings/users` | JSON | 14 | demo, settings_api | 291 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | doctors, license_gate, odontogram_api, patient_card, perio_api, pin, settings_api | 829 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 157 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1011 | doctor_card |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1011 | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1011 | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 14 | admin, admin_canvas, anamneza, api, day_actions, day_forms, demo, desk, doctors, license_page, license_renew, migrate, patient_card, patients_api, paylink, perio_api, pin, plan_acord, privacy, review2, review3, review3_auth, settings_api, stats_api, theme, visit, visit_api | 2562 | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, demo, doctors, perio_api, pin, review2, review3, settings_api | 1321 | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 116 | — |
| `GET /admin/medici` | HTML | 53 | admin, demo, doctors, pin, settings_api | 938 | doctors_list |
| `POST /admin/medici/add` | 303 | 7 | doctors | 116 | — |
| `POST /admin/medici/colors` | 303 | 4 | doctors | 116 | — |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors | 222 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 650 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 650 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 116 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin_canvas, day_forms, doctors | 302 | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin_canvas, day_forms, doctors | 302 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin_canvas, day_forms, doctors | 302 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin_canvas, day_forms, doctors | 302 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_forms, demo, doctors, review2, review3, settings_api | 1076 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, desk, pin, stats_api, theme | 717 | — |
| `GET /admin/stats` | HTML | 27 | admin, booking, demo, patients_api, pin, review3, stats_api | 837 | stats |
| `GET /api/stats` | JSON | 21 | demo, stats_api | 106 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 428 | — |
| `GET /demo` | HTML | 14 | admin | 428 | — |
| `GET /qr` | other | 5 | settings_api | 258 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy, scan | 375 | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 5 | hardening, license_gate, patient_card, privacy, scan | 391 | — |
| `GET /admin/patient/{pid}` | HTML | 836 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/alert` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 14 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2260 | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 17 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/doc` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/erase` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, demo, desk, doctors, guards, hardening, license_existing, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, settings_api, stats_api, teeth, visit, visit_api | 2602 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 29 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 38 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 49 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/pay` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `GET /admin/patient/{pid}/peek` | HTML | 11 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/perio` | 303 | 29 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/plan` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 25 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 5 | activity, admin, anamneza, booking, bot, chair, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, scan, schedule_api, stats_api, teeth, visit, visit_api | 2424 | — |
| `POST /admin/patient/{pid}/save` | 303 | 8 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_actions, day_forms, demo, desk, doctors, guards, hardening, license_page, license_renew, migrate, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, review2, review3_auth, settings_api, stats_api, teeth, theme, visit, visit_api | 3043 | — |
| `GET /admin/patient/{pid}/slots` | JSON | 6 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 54 | activity, admin, anamneza, booking, bot, day_forms, demo, desk, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, stats_api, teeth, visit, visit_api | 2244 | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 447 | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin, patients_api | 506 | — |
| `POST /admin/patients/new` | 303 | 16 | admin, anamneza, dbcrypt, doctors, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, review2, scan, teeth, visit | 1610 | — |
| `GET /admin/search` | HTML | 323 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, demo, desk, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3, scan, teeth, visit, visit_api | 1994 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 20 | day_forms, patient_card, plan_acord, visit, visit_api | 413 | visit |
| `POST /admin/visit/{appt_id}` | 303 | 13 | day_forms, patient_card, plan_acord, visit, visit_api | 413 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card | 257 | — |
| `GET /api/patients` | JSON | 34 | demo, license_existing, license_gate, license_page, license_renew, patients_api, paylink, react_default, stats_api | 417 | — |
| `POST /api/patients` | JSON | 18 | demo, license_existing, license_gate, license_page, license_renew, patients_api, paylink, react_default, stats_api | 417 | — |
| `GET /api/patients/summary` | JSON | 31 | patients_api | 78 | — |
| `GET /api/patients/{pid}` | JSON | 8 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 7 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api | 1006 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | anamneza, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, privacy, react_default, scan | 730 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | admin, booking, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 1043 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | admin, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 957 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api | 1006 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 7 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api | 1006 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | anamneza, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api, privacy, react_default, scan, teeth, visit | 1012 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api | 1006 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | admin, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, review2, scan | 976 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api, react_default, scan | 556 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api | 1006 | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, react_default, review2, scan, teeth, visit, visit_api | 1464 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, react_default, scan, settings_api | 1006 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, chair, demo, desk, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, react_default, review2, scan, schedule_api, visit, visit_api | 1548 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/scan/cancel` | JSON | 5 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/scan/finish` | JSON | 25 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/scan/page` | JSON | 15 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 36 | demo, desk, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, react_default, scan | 529 | — |
| `GET /api/scan/status` | JSON | 6 | scan | 15 | — |
| `GET /api/visits/{aid}` | JSON | 9 | chair, visit_api | 102 | — |
| `POST /api/visits/{aid}` | JSON | 23 | chair, visit_api | 102 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 187 | admin, admin_canvas, api, booking, chair, day_forms, dbcrypt, demo, desk, doctors, hardening, license_existing, license_gate, license_page, license_renew, migrate, panel_model, patient_card, patients_api, paylink, pin, react_default, review3_auth, schedule_api, settings_api, split, stats_api, structure, theme, visit_api | 2666 | schedule_dash |
| `POST /admin/add` | other | 14 | activity, admin, admin_canvas, booking, bot, chair, day_actions, day_forms, desk, doctor_windows, doctors, hardening, migrate, patient_card, patients_api, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 2008 | — |
| `GET /admin/all` | HTML | 64 | activity, admin, admin_canvas, api, booking, bot, day_actions, day_forms, demo, desk, doctor_windows, doctors, hardening, migrate, panel_model, patient_card, patients_api, pin, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 2249 | schedule_all |
| `GET /admin/cabinet` | HTML | 17 | chair | 47 | chair |
| `POST /admin/comment/{appt_id}` | other | 5 | day_actions, day_forms, privacy, visit_api | 298 | — |
| `GET /admin/doctor/{dk}` | HTML | 56 | admin, admin_canvas, api, chair, day_forms, doctor_windows, grid, pin, review3, schedule_api | 1067 | schedule_doctor |
| `GET /admin/export` | FILE | 35 | admin | 428 | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin, day_forms | 508 | — |
| `POST /admin/move/{appt_id}` | other | 9 | booking, day_actions, day_forms, doctor_windows | 240 | — |
| `POST /admin/note` | other | 9 | admin, admin_canvas, booking, chair, day_actions, day_forms, schedule_api | 909 | — |
| `POST /admin/status/{appt_id}` | 303 | 11 | activity, admin, admin_canvas, booking, day_forms, doctor_windows, panel_model, patient_card, plan_acord, privacy, review3, schedule_api, visit, visit_api | 1411 | — |
| `GET /admin/week` | HTML | 41 | admin, demo, schedule_api | 579 | schedule_week |
| `GET /api/chair` | JSON | 29 | chair | 47 | — |
| `POST /api/schedule/appointments` | JSON | 22 | day_actions | 44 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 16 | chair, day_actions, doctors, schedule_api | 325 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 18 | booking, chair, day_actions, doctor_windows, doctors, schedule_api | 441 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 18 | activity, admin, chair, day_actions, desk, doctors, patient_card, patients_api, plan_acord, privacy, review2, scan, schedule_api, visit, visit_api | 1340 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas, harness_clock, schedule_api | 238 | — |
| `GET /api/schedule/day` | JSON | 17 | day_actions, schedule_api | 162 | — |
| `POST /api/schedule/desk/call/{aid}` | JSON | 21 | desk | 17 | — |
| `GET /api/schedule/live` | JSON | 36 | demo, desk, panel_model, schedule_api | 237 | — |
| `POST /api/schedule/notes` | JSON | 19 | day_actions | 44 | — |
| `GET /api/schedule/week` | JSON | 14 | schedule_api | 118 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, admin_canvas, anamneza, api, booking, bot, chair, day_forms, dbcrypt, demo, desk, doctor_windows, doctors, grid, guards, hardening, harness_clock, harness_tmp, installer, launcher, legacy, license_existing, license_format, license_gate, license_page, license_renew, license_state, license_verify, migrate, netcheck, odontogram_api, panel_model, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, privileged, react_default, relocate, restart, review2, review3, review3_auth, review3_bot, schedule_api, settings_api, split, srcpin, structure, teeth, theme, visit, visit_api | 4030 | — |
| `GET /admin/license` | HTML | 9 | demo, license_existing, license_page, license_renew, paylink | 239 | — |
| `POST /admin/license` | 303 | 22 | demo, license_existing, license_page, license_renew, paylink | 239 | — |
| `POST /admin/license/renew` | 303 | 10 | license_renew, paylink | 139 | — |
| `POST /admin/license/request` | 303 | 19 | license_page, license_renew | 145 | — |
| `POST /admin/license/verify` | 303 | 12 | license_renew | 101 | — |
| `GET /admin/login` | HTML | 34 | admin, api, chair, demo, desk, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, review3_auth, settings_api, stats_api, theme, visit_api | 2045 | — |
| `POST /admin/login` | 303 | 66 | admin, api, chair, demo, desk, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, review3_auth, settings_api, stats_api, theme, visit_api | 2045 | — |
| `GET /admin/logout` | 303 | 6 | **—** | — | — |
| `POST /admin/pin/change` | 303 | 8 | demo, pin, review3_auth, settings_api | 423 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 151 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 151 | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 103 | — |
| `GET /admin/setup` | HTML | 12 | api, desk, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1220 | — |
| `POST /admin/setup` | HTML | 17 | api, desk, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1220 | — |
| `GET /api/license` | JSON | 6 | demo, license_existing, license_page, license_renew | 201 | — |
| `POST /chat` | other | 13 | admin, bot, hardening, license_gate, review3_bot | 557 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 354 | — |
| `GET /favicon.ico` | other | 5 | admin | 428 | — |
| `GET /health` | other | 4 | admin, hardening, license_renew, netcheck | 644 | — |
| `GET /icon-{px}.png` | other | 11 | admin | 428 | — |
| `GET /manifest.webmanifest` | other | 31 | admin | 428 | — |
| `GET /plata/{ticket}` | HTML | 16 | paylink | 38 | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, structure, visit_api | 1520 | — |

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
| 836 | `GET /admin/patient/{pid}` | 25 |
| 323 | `GET /admin/search` | 24 |
| 187 | `GET /admin` | 30 |
| 169 | `GET /admin/settings/theme` | 3 |
| 157 | `GET /admin/doctor-card/{dk}` | 8 |
| 118 | `GET /admin/settings/services` | 4 |
| 66 | `POST /admin/login` | 21 |
| 64 | `GET /admin/all` | 28 |
| 63 | `GET /admin/settings/hours` | 3 |
| 61 | `GET /admin/settings/crypt/sheet` | 2 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
