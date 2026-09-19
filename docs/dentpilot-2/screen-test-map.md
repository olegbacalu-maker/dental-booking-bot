# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **178** · наборов **37** · мест вызова `res.ok`/`res.check` в исходниках — **2837**.


⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть
вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок
на самом деле, говорит сам прогон (`.\dev test`).


## Маршруты без единой проверки


| Маршрут | Тип | стр | Замечание |
|---|---|---|---|
| `POST /admin/lan/firewall` | 303 | 9 | правило брандмауэра, ⚠️ зовёт netsh через runas |
| `GET /admin/logout` | 303 | 6 | выход из журнала |
| `POST /admin/settings/crypt/off` | 303 | 8 | выключение шифрования картотеки |
| `POST /admin/telegram/save` | HTML | 26 | сохранение токена бота (заморожен, но маршрут жив) |
| `POST /admin/update/check` | 303 | 7 | проверка обновлений |
| `POST /admin/update/run` | HTML | 21 | **самообновление** — спусковой крючок не проверен ничем |

⭐ Находка **не про миграцию**: дыры есть уже сейчас. `POST /admin/update/run` запускает подмену exe у клиники и не покрыт ничем.


## Настройки — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, pin, privacy, settings_api | 460 | — | — |
| `POST /admin/lan/firewall` | 303 | 9 | **—** | — | — | — |
| `POST /admin/lan/save` | HTML | 11 | admin, settings_api | 601 | — | — |
| `GET /admin/settings` | HTML | 19 | admin, api, pin, settings_api, theme | 854 | settings_hub | off |
| `GET /admin/settings/backup` | HTML | 20 | settings_api | 180 | settings_backup | off |
| `GET /admin/settings/clinic` | HTML | 27 | admin, api, doctors, settings_api | 784 | settings_clinic | off |
| `GET /admin/settings/crypt` | HTML | 66 | settings_api | 180 | — | — |
| `POST /admin/settings/crypt/confirm` | 303 | 22 | dbcrypt | 77 | — | — |
| `POST /admin/settings/crypt/off` | 303 | 8 | **—** | — | — | — |
| `POST /admin/settings/crypt/prepare` | 303 | 20 | dbcrypt | 77 | — | — |
| `GET /admin/settings/crypt/sheet` | HTML | 66 | dbcrypt | 77 | — | — |
| `GET /admin/settings/faq` | HTML | 9 | admin, dbcrypt, pin, settings_api | 781 | settings_faq | off |
| `GET /admin/settings/hours` | HTML | 63 | admin, settings_api | 601 | settings_hours | off |
| `GET /admin/settings/lan` | HTML | 9 | admin, settings_api | 601 | settings_lan | off |
| `POST /admin/settings/save` | 303 | 38 | admin, api, pin, review2, settings_api, theme | 873 | — | — |
| `GET /admin/settings/security` | HTML | 18 | pin, review2, settings_api | 302 | settings_security | off |
| `GET /admin/settings/services` | HTML | 118 | admin, review2, settings_api | 620 | settings_services | off |
| `GET /admin/settings/system` | HTML | 80 | admin, pin, settings_api | 704 | — | — |
| `GET /admin/settings/telegram` | HTML | 19 | admin, settings_api | 601 | — | — |
| `GET /admin/settings/theme` | HTML | 138 | settings_api, theme | 255 | settings_theme | off |
| `POST /admin/settings/theme/logo` | 303 | 15 | theme | 75 | — | — |
| `GET /admin/settings/theme/palette` | JSON | 11 | theme | 75 | — | — |
| `POST /admin/telegram/save` | HTML | 26 | **—** | — | — | — |
| `POST /admin/update/check` | 303 | 7 | **—** | — | — | — |
| `POST /admin/update/run` | HTML | 21 | **—** | — | — | — |
| `POST /admin/users/delete` | other | 5 | pin | 103 | — | — |
| `POST /admin/users/save` | other | 8 | api, doctors, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, visit_api | 939 | — | — |
| `GET /api/settings/backup` | JSON | 9 | settings_api | 180 | — | — |
| `GET /api/settings/clinic` | JSON | 4 | api | 75 | — | — |
| `POST /api/settings/clinic` | JSON | 25 | api | 75 | — | — |
| `GET /api/settings/faq` | JSON | 4 | settings_api | 180 | — | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 601 | — | — |
| `POST /api/settings/hours` | JSON | 16 | admin, settings_api | 601 | — | — |
| `GET /api/settings/hub` | JSON | 6 | settings_api | 180 | — | — |
| `GET /api/settings/lan` | JSON | 6 | settings_api | 180 | — | — |
| `POST /api/settings/lan` | JSON | 21 | settings_api | 180 | — | — |
| `POST /api/settings/lan/firewall` | JSON | 8 | settings_api | 180 | — | — |
| `POST /api/settings/pin` | JSON | 14 | settings_api | 180 | — | — |
| `GET /api/settings/security` | JSON | 7 | settings_api | 180 | — | — |
| `GET /api/settings/services` | JSON | 4 | settings_api | 180 | — | — |
| `POST /api/settings/services` | JSON | 27 | settings_api | 180 | — | — |
| `GET /api/settings/theme` | JSON | 4 | settings_api | 180 | — | — |
| `POST /api/settings/theme` | JSON | 21 | settings_api | 180 | — | — |
| `POST /api/settings/theme/logo` | JSON | 9 | settings_api | 180 | — | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api | 180 | — | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api | 180 | — | — |
| `POST /api/settings/users` | JSON | 14 | settings_api | 180 | — | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | doctors, odontogram_api, patient_card, perio_api, pin, settings_api | 700 | — | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 154 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 992 | doctor_card | off |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 992 | — | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 992 | — | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 14 | admin, admin_canvas, anamneza, api, day_actions, day_forms, doctors, migrate, patient_card, patients_api, perio_api, pin, plan_acord, privacy, review2, review3, review3_auth, settings_api, theme, visit, visit_api | 2083 | — | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review2, review3, settings_api | 1191 | — | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 108 | — | — |
| `GET /admin/medici` | HTML | 48 | admin, doctors, pin, settings_api | 812 | doctors_list | off |
| `POST /admin/medici/add` | 303 | 7 | doctors | 108 | — | — |
| `POST /admin/medici/colors` | 303 | 4 | doctors | 108 | — | — |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors | 213 | — | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 634 | — | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 634 | — | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 108 | — | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin_canvas, day_forms, doctors | 293 | — | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin_canvas, day_forms, doctors | 293 | — | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin_canvas, day_forms, doctors | 293 | — | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin_canvas, day_forms, doctors | 293 | — | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_forms, doctors, review2, review3, settings_api | 949 | — | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, pin, theme | 599 | — | — |
| `GET /admin/stats` | HTML | 291 | admin, booking, patients_api, pin, review3 | 722 | — | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 421 | — | — |
| `GET /demo` | HTML | 14 | admin | 421 | — | — |
| `GET /qr` | other | 5 | settings_api | 180 | — | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy | 320 | — | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 5 | hardening, patient_card, privacy | 320 | — | — |
| `GET /admin/patient/{pid}` | HTML | 834 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | patient_card | off |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/alert` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 10 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 17 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/doc` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/erase` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, settings_api, teeth, visit, visit_api | 2244 | — | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 28 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 35 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | odontogram | off |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 47 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/pay` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patient/{pid}/peek` | HTML | 11 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/perio` | 303 | 29 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/plan` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 24 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 5 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/save` | 303 | 8 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_actions, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3_auth, settings_api, teeth, theme, visit, visit_api | 2494 | — | — |
| `GET /admin/patient/{pid}/slots` | JSON | 6 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 54 | activity, admin, anamneza, booking, bot, day_forms, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1987 | — | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 440 | — | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin, patients_api | 497 | — | — |
| `POST /admin/patients/new` | 303 | 16 | admin, anamneza, dbcrypt, doctors, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, review2, teeth, visit | 1521 | — | — |
| `GET /admin/search` | HTML | 322 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3, teeth, visit, visit_api | 1844 | patients_search | off |
| `GET /admin/visit/{appt_id}` | HTML | 19 | day_forms, patient_card, plan_acord, visit, visit_api | 392 | visit | off |
| `POST /admin/visit/{appt_id}` | 303 | 13 | day_forms, patient_card, plan_acord, visit, visit_api | 392 | visit | off |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, patient_card | 220 | — | — |
| `GET /api/patients` | JSON | 34 | patients_api | 76 | — | — |
| `POST /api/patients` | JSON | 18 | patients_api | 76 | — | — |
| `GET /api/patients/summary` | JSON | 31 | patients_api | 76 | — | — |
| `GET /api/patients/{pid}` | JSON | 8 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 8 | doctors, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 776 | — | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | anamneza, odontogram_api, patient_card, patients_api, perio_api, privacy | 562 | — | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | admin, booking, odontogram_api, patient_card, patients_api, perio_api | 892 | — | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | admin, odontogram_api, patient_card, patients_api, perio_api | 806 | — | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | doctors, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 776 | — | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 8 | doctors, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 776 | — | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | anamneza, odontogram_api, patient_card, patients_api, perio, perio_api, privacy, teeth, visit | 819 | — | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | doctors, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 776 | — | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | admin, odontogram_api, patient_card, patients_api, perio_api, review2 | 825 | — | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | odontogram_api, patient_card, patients_api, perio, perio_api | 412 | — | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | doctors, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 776 | — | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, review2, teeth, visit, visit_api | 1269 | — | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | doctors, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 776 | — | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, review2, visit, visit_api | 1097 | — | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 27 | odontogram_api, patient_card, patients_api, perio_api | 385 | — | — |
| `GET /api/visits/{aid}` | JSON | 9 | visit_api | 55 | — | — |
| `POST /api/visits/{aid}` | JSON | 23 | visit_api | 55 | — | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin` | HTML | 162 | admin, admin_canvas, api, booking, day_forms, dbcrypt, doctors, hardening, migrate, patient_card, patients_api, pin, review3_auth, schedule_api, settings_api, theme, visit_api | 1899 | — | — |
| `POST /admin/add` | other | 14 | activity, admin, admin_canvas, booking, bot, day_actions, day_forms, doctor_windows, hardening, migrate, patient_card, patients_api, plan_acord, privacy, review2, review3, review3_bot, schedule_api, visit, visit_api | 1636 | — | — |
| `GET /admin/all` | HTML | 61 | activity, admin, admin_canvas, api, booking, bot, day_actions, day_forms, doctor_windows, doctors, hardening, migrate, patient_card, patients_api, pin, plan_acord, privacy, review2, review3, review3_bot, schedule_api, visit, visit_api | 1922 | — | — |
| `POST /admin/comment/{appt_id}` | other | 5 | day_actions, day_forms, privacy, visit_api | 278 | — | — |
| `GET /admin/doctor/{dk}` | HTML | 54 | admin, admin_canvas, api, day_forms, doctor_windows, grid, pin, review3, schedule_api | 947 | — | — |
| `GET /admin/export` | FILE | 35 | admin | 421 | — | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin, day_forms | 501 | — | — |
| `POST /admin/move/{appt_id}` | other | 9 | booking, day_actions, day_forms, doctor_windows | 239 | — | — |
| `POST /admin/note` | other | 9 | admin, admin_canvas, booking, day_actions, day_forms, schedule_api | 796 | — | — |
| `POST /admin/status/{appt_id}` | 303 | 11 | activity, admin, admin_canvas, booking, day_forms, doctor_windows, patient_card, plan_acord, privacy, review3, schedule_api, visit, visit_api | 1237 | — | — |
| `GET /admin/week` | HTML | 38 | admin, schedule_api | 482 | — | — |
| `POST /api/schedule/appointments` | JSON | 16 | day_actions | 43 | — | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 11 | day_actions | 43 | — | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 17 | booking, day_actions, doctor_windows | 159 | — | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 17 | activity, admin, day_actions, patient_card, patients_api, plan_acord, privacy, review2, visit, visit_api | 977 | — | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas | 105 | — | — |
| `GET /api/schedule/day` | JSON | 17 | day_actions, schedule_api | 104 | — | — |
| `POST /api/schedule/notes` | JSON | 17 | day_actions | 43 | — | — |
| `GET /api/schedule/week` | JSON | 14 | schedule_api | 61 | — | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_forms, dbcrypt, doctor_windows, doctors, grid, guards, hardening, launcher, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, restart, review2, review3, review3_auth, review3_bot, schedule_api, settings_api, structure, teeth, theme, visit, visit_api | 2794 | — | — |
| `GET /admin/login` | HTML | 34 | admin, api, doctors, hardening, migrate, patient_card, patients_api, pin, review3_auth, settings_api, theme, visit_api | 1490 | — | — |
| `POST /admin/login` | 303 | 66 | admin, api, doctors, hardening, migrate, patient_card, patients_api, pin, review3_auth, settings_api, theme, visit_api | 1490 | — | — |
| `GET /admin/logout` | 303 | 6 | **—** | — | — | — |
| `POST /admin/pin/change` | 303 | 8 | pin, review3_auth, settings_api | 312 | — | — |
| `GET /admin/recover` | HTML | 6 | dbcrypt, hardening | 151 | — | — |
| `POST /admin/recover` | HTML | 17 | dbcrypt, hardening | 151 | — | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 103 | — | — |
| `GET /admin/setup` | HTML | 12 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, visit_api | 1013 | — | — |
| `POST /admin/setup` | HTML | 17 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, visit_api | 1013 | — | — |
| `POST /chat` | other | 13 | admin, bot, hardening, review3_bot | 534 | — | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 255 | — | — |
| `GET /favicon.ico` | other | 5 | admin | 421 | — | — |
| `GET /health` | other | 4 | admin, hardening | 495 | — | — |
| `GET /icon-{px}.png` | other | 11 | admin | 421 | — | — |
| `GET /manifest.webmanifest` | other | 31 | admin | 421 | — | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, visit_api | 1285 | — | — |

## Колонки-состояния


`Флаг` — имя экрана в `clinic.json` → `ui.react` (включает React-экран; `?ui=legacy` возвращает старый на один запрос).
`Пилот` — `off` / `on` / `откат`. `—` значит «ещё не начат».


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 834 | `GET /admin/patient/{pid}` | 21 |
| 322 | `GET /admin/search` | 21 |
| 291 | `GET /admin/stats` | 5 |
| 162 | `GET /admin` | 17 |
| 154 | `GET /admin/doctor-card/{dk}` | 8 |
| 138 | `GET /admin/settings/theme` | 2 |
| 118 | `GET /admin/settings/services` | 3 |
| 80 | `GET /admin/settings/system` | 3 |
| 66 | `POST /admin/login` | 12 |
| 66 | `GET /admin/settings/crypt` | 1 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
