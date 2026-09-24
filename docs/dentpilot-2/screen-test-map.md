# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **191** · наборов **51** · мест вызова `res.ok`/`res.check` в исходниках — **3630**.


⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть
вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок
на самом деле, говорит сам прогон (`.\dev test`).


⛔ Адресов, которые сборщик не смог разобрать: **0** — маршрут, объявленный через константу, раньше выпадал из карты
ЦЕЛИКОМ и молча: число маршрутов не менялось, жалобы не было.


## Маршруты без единой проверки


| Маршрут | Тип | стр | Замечание |
|---|---|---|---|
| `POST /admin/lan/firewall` | 303 | 9 | правило брандмауэра, ⚠️ зовёт netsh через runas |
| `GET /admin/logout` | 303 | 6 | выход из журнала |
| `POST /admin/telegram/save` | HTML | 26 | сохранение токена бота (заморожен, но маршрут жив) |
| `POST /admin/update/check` | 303 | 7 | проверка обновлений |
| `POST /admin/update/run` | HTML | 21 | **самообновление** — спусковой крючок не проверен ничем |

⭐ Находка **не про миграцию**: дыры есть уже сейчас. `POST /admin/update/run` запускает подмену exe у клиники и не покрыт ничем.


## Настройки — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, pin, privacy, settings_api | 534 | — |
| `POST /admin/lan/firewall` | 303 | 9 | **—** | — | — |
| `POST /admin/lan/save` | HTML | 11 | admin, settings_api | 671 | — |
| `GET /admin/settings` | HTML | 19 | admin, api, pin, settings_api, theme | 928 | settings_hub |
| `GET /admin/settings/backup` | HTML | 20 | settings_api | 243 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 27 | admin, api, doctors, react_default, settings_api | 873 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 14 | settings_api | 243 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 10 | dbcrypt, settings_api | 320 | — |
| `POST /admin/settings/crypt/off` | 303 | 6 | settings_api | 243 | — |
| `POST /admin/settings/crypt/prepare` | 303 | 6 | dbcrypt | 77 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 61 | dbcrypt, settings_api | 320 | — |
| `GET /admin/settings/faq` | HTML | 9 | admin, dbcrypt, pin, settings_api | 851 | settings_faq |
| `GET /admin/settings/hours` | HTML | 63 | admin, settings_api | 671 | settings_hours |
| `GET /admin/settings/lan` | HTML | 9 | admin, settings_api | 671 | settings_lan |
| `POST /admin/settings/save` | 303 | 38 | admin, api, license_page, pin, review2, settings_api, theme | 986 | — |
| `GET /admin/settings/security` | HTML | 18 | pin, review2, settings_api | 365 | settings_security |
| `GET /admin/settings/services` | HTML | 118 | admin, review2, settings_api | 690 | settings_services |
| `GET /admin/settings/system` | HTML | 7 | admin, pin, settings_api | 774 | settings_system |
| `GET /admin/settings/telegram` | HTML | 19 | admin, settings_api | 671 | — |
| `GET /admin/settings/theme` | HTML | 138 | settings_api, theme | 318 | settings_theme |
| `POST /admin/settings/theme/logo` | 303 | 15 | privacy, theme | 186 | — |
| `GET /admin/settings/theme/palette` | JSON | 11 | theme | 75 | — |
| `POST /admin/telegram/save` | HTML | 26 | **—** | — | — |
| `POST /admin/update/check` | 303 | 7 | **—** | — | — |
| `POST /admin/update/run` | HTML | 21 | **—** | — | — |
| `POST /admin/users/delete` | other | 5 | pin | 103 | — |
| `POST /admin/users/save` | other | 8 | api, doctors, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1060 | — |
| `GET /api/settings/backup` | JSON | 9 | settings_api | 243 | — |
| `GET /api/settings/clinic` | JSON | 4 | api | 79 | — |
| `POST /api/settings/clinic` | JSON | 25 | api | 79 | — |
| `GET /api/settings/crypt` | JSON | 4 | settings_api | 243 | — |
| `POST /api/settings/crypt/off` | JSON | 14 | settings_api | 243 | — |
| `POST /api/settings/crypt/prepare` | JSON | 15 | settings_api | 243 | — |
| `GET /api/settings/faq` | JSON | 4 | settings_api | 243 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 671 | — |
| `POST /api/settings/hours` | JSON | 16 | admin, settings_api | 671 | — |
| `GET /api/settings/hub` | JSON | 6 | settings_api | 243 | — |
| `GET /api/settings/lan` | JSON | 6 | settings_api | 243 | — |
| `POST /api/settings/lan` | JSON | 21 | settings_api | 243 | — |
| `POST /api/settings/lan/firewall` | JSON | 8 | settings_api | 243 | — |
| `POST /api/settings/pin` | JSON | 14 | settings_api | 243 | — |
| `GET /api/settings/security` | JSON | 7 | settings_api | 243 | — |
| `GET /api/settings/services` | JSON | 4 | settings_api | 243 | — |
| `POST /api/settings/services` | JSON | 27 | settings_api | 243 | — |
| `GET /api/settings/system` | JSON | 4 | privileged, settings_api | 310 | — |
| `POST /api/settings/system/check` | JSON | 14 | settings_api | 243 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 67 | — |
| `GET /api/settings/theme` | JSON | 4 | settings_api | 243 | — |
| `POST /api/settings/theme` | JSON | 21 | settings_api | 243 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | settings_api | 243 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api | 243 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api | 243 | — |
| `POST /api/settings/users` | JSON | 14 | settings_api | 243 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | doctors, license_gate, odontogram_api, patient_card, perio_api, pin, settings_api | 785 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 154 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1007 | doctor_card |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1007 | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1007 | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 14 | admin, admin_canvas, anamneza, api, day_actions, day_forms, doctors, license_page, migrate, patient_card, patients_api, perio_api, pin, plan_acord, privacy, review2, review3, review3_auth, settings_api, stats_api, theme, visit, visit_api | 2263 | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review2, review3, settings_api | 1269 | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 114 | — |
| `GET /admin/medici` | HTML | 48 | admin, doctors, pin, settings_api | 888 | doctors_list |
| `POST /admin/medici/add` | 303 | 7 | doctors | 114 | — |
| `POST /admin/medici/colors` | 303 | 4 | doctors | 114 | — |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors | 220 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 648 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 648 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 114 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin_canvas, day_forms, doctors, react_default | 309 | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin_canvas, day_forms, doctors, react_default | 309 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin_canvas, day_forms, doctors, react_default | 309 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin_canvas, day_forms, doctors, react_default | 309 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_forms, doctors, react_default, review2, review3, settings_api | 1035 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, pin, stats_api, theme | 654 | — |
| `GET /admin/stats` | HTML | 26 | admin, booking, patients_api, pin, review3, stats_api | 777 | stats |
| `GET /api/stats` | JSON | 21 | stats_api | 48 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 428 | — |
| `GET /demo` | HTML | 14 | admin | 428 | — |
| `GET /qr` | other | 5 | settings_api | 243 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy | 331 | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 5 | hardening, license_gate, patient_card, privacy | 347 | — |
| `GET /admin/patient/{pid}` | HTML | 834 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/alert` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 10 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2027 | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 17 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/doc` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/erase` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, settings_api, teeth, visit, visit_api | 2331 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 28 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 35 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 47 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/pay` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `GET /admin/patient/{pid}/peek` | HTML | 11 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/perio` | 303 | 29 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/plan` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 24 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, schedule_api, teeth, visit, visit_api | 2123 | — |
| `POST /admin/patient/{pid}/save` | 303 | 8 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_actions, day_forms, doctors, hardening, license_page, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3_auth, settings_api, stats_api, teeth, theme, visit, visit_api | 2674 | — |
| `GET /admin/patient/{pid}/slots` | JSON | 6 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 54 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2011 | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 447 | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin, patients_api | 504 | — |
| `POST /admin/patients/new` | 303 | 16 | admin, anamneza, dbcrypt, doctors, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, review2, teeth, visit | 1534 | — |
| `GET /admin/search` | HTML | 322 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3, teeth, visit, visit_api | 1862 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 19 | day_forms, patient_card, plan_acord, visit, visit_api | 392 | visit |
| `POST /admin/visit/{appt_id}` | 303 | 13 | day_forms, patient_card, plan_acord, visit, visit_api | 392 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card | 236 | — |
| `GET /api/patients` | JSON | 34 | license_gate, license_page, patients_api, react_default | 140 | — |
| `POST /api/patients` | JSON | 18 | license_gate, license_page, patients_api, react_default | 140 | — |
| `GET /api/patients/summary` | JSON | 31 | patients_api | 76 | — |
| `GET /api/patients/{pid}` | JSON | 8 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 8 | doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 861 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | anamneza, license_gate, odontogram_api, patient_card, patients_api, perio_api, privacy | 589 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | admin, booking, license_gate, odontogram_api, patient_card, patients_api, perio_api | 915 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | admin, license_gate, odontogram_api, patient_card, patients_api, perio_api | 829 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 861 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 8 | doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 861 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | anamneza, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api, privacy, teeth, visit | 846 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 861 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | admin, license_gate, odontogram_api, patient_card, patients_api, perio_api, review2 | 848 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | license_gate, odontogram_api, patient_card, patients_api, perio, perio_api | 428 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 861 | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, review2, teeth, visit, visit_api | 1303 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 861 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, doctors, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, review2, schedule_api, visit, visit_api | 1357 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 27 | license_gate, odontogram_api, patient_card, patients_api, perio_api | 401 | — |
| `GET /api/visits/{aid}` | JSON | 9 | visit_api | 55 | — |
| `POST /api/visits/{aid}` | JSON | 23 | visit_api | 55 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 182 | admin, admin_canvas, api, booking, day_forms, dbcrypt, doctors, hardening, license_gate, license_page, migrate, panel_model, patient_card, patients_api, pin, react_default, review3_auth, schedule_api, settings_api, split, stats_api, structure, theme, visit_api | 2291 | schedule_dash |
| `POST /admin/add` | other | 14 | activity, admin, admin_canvas, booking, bot, day_actions, day_forms, doctor_windows, doctors, hardening, migrate, patient_card, patients_api, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 1878 | — |
| `GET /admin/all` | HTML | 63 | activity, admin, admin_canvas, api, booking, bot, day_actions, day_forms, doctor_windows, doctors, hardening, migrate, panel_model, patient_card, patients_api, pin, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 2129 | schedule_all |
| `POST /admin/comment/{appt_id}` | other | 5 | day_actions, day_forms, privacy, visit_api | 290 | — |
| `GET /admin/doctor/{dk}` | HTML | 56 | admin, admin_canvas, api, day_forms, doctor_windows, grid, pin, review3, schedule_api | 1010 | schedule_doctor |
| `GET /admin/export` | FILE | 35 | admin | 428 | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin, day_forms | 508 | — |
| `POST /admin/move/{appt_id}` | other | 9 | booking, day_actions, day_forms, doctor_windows | 240 | — |
| `POST /admin/note` | other | 9 | admin, admin_canvas, booking, day_actions, day_forms, schedule_api | 856 | — |
| `POST /admin/status/{appt_id}` | 303 | 11 | activity, admin, admin_canvas, booking, day_forms, doctor_windows, panel_model, patient_card, plan_acord, privacy, review3, schedule_api, visit, visit_api | 1376 | — |
| `GET /admin/week` | HTML | 40 | admin, schedule_api | 540 | schedule_week |
| `POST /api/schedule/appointments` | JSON | 22 | day_actions | 44 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 16 | day_actions, doctors, schedule_api | 270 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 18 | booking, day_actions, doctor_windows, doctors, schedule_api | 386 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 18 | activity, admin, day_actions, doctors, patient_card, patients_api, plan_acord, privacy, review2, schedule_api, visit, visit_api | 1222 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas | 106 | — |
| `GET /api/schedule/day` | JSON | 17 | day_actions, schedule_api | 156 | — |
| `GET /api/schedule/live` | JSON | 36 | panel_model, schedule_api | 181 | — |
| `POST /api/schedule/notes` | JSON | 19 | day_actions | 44 | — |
| `GET /api/schedule/week` | JSON | 14 | schedule_api | 112 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_forms, dbcrypt, doctor_windows, doctors, grid, guards, hardening, installer, launcher, legacy, license_format, license_gate, license_page, license_state, license_verify, migrate, odontogram_api, panel_model, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, privileged, react_default, relocate, restart, review2, review3, review3_auth, review3_bot, schedule_api, settings_api, split, srcpin, structure, teeth, theme, visit, visit_api | 3538 | — |
| `GET /admin/license` | HTML | 9 | license_page | 39 | — |
| `POST /admin/license` | 303 | 14 | license_page | 39 | — |
| `GET /admin/login` | HTML | 34 | admin, api, doctors, hardening, license_gate, license_page, migrate, patient_card, patients_api, pin, review3_auth, settings_api, stats_api, theme, visit_api | 1673 | — |
| `POST /admin/login` | 303 | 66 | admin, api, doctors, hardening, license_gate, license_page, migrate, patient_card, patients_api, pin, review3_auth, settings_api, stats_api, theme, visit_api | 1673 | — |
| `GET /admin/logout` | 303 | 6 | **—** | — | — |
| `POST /admin/pin/change` | 303 | 8 | pin, review3_auth, settings_api | 375 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 151 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 151 | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 103 | — |
| `GET /admin/setup` | HTML | 12 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1134 | — |
| `POST /admin/setup` | HTML | 17 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1134 | — |
| `GET /api/license` | JSON | 6 | license_page | 39 | — |
| `POST /chat` | other | 13 | admin, bot, hardening, license_gate, review3_bot | 557 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 318 | — |
| `GET /favicon.ico` | other | 5 | admin | 428 | — |
| `GET /health` | other | 4 | admin, hardening | 502 | — |
| `GET /icon-{px}.png` | other | 11 | admin | 428 | — |
| `GET /manifest.webmanifest` | other | 31 | admin | 428 | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, visit_api | 1416 | — |

## Прочее — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/migration` | HTML | 45 | guards, split | 66 | — |
| `POST /admin/migration/confirm` | 303 | 32 | split | 44 | — |

## Колонки-состояния


`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности. С 21.09 она отдаётся ПО УМОЛЧАНИЮ: `ui.react` в профиле стал аварийным выключателем, а не рубильником выката (`?ui=legacy` по-прежнему возвращает старую страницу на один запрос). `—` значит «страница серверная по замыслу» — печать и аварийные экраны.


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 834 | `GET /admin/patient/{pid}` | 21 |
| 322 | `GET /admin/search` | 21 |
| 182 | `GET /admin` | 24 |
| 154 | `GET /admin/doctor-card/{dk}` | 8 |
| 138 | `GET /admin/settings/theme` | 2 |
| 118 | `GET /admin/settings/services` | 3 |
| 66 | `POST /admin/login` | 15 |
| 63 | `GET /admin/all` | 26 |
| 63 | `GET /admin/settings/hours` | 2 |
| 61 | `GET /admin/settings/crypt/sheet` | 2 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
