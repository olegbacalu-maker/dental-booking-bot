# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **166** · наборов **31** · мест вызова `res.ok`/`res.check` в исходниках — **2355**.


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
| `POST /admin/lan/save` | HTML | 11 | admin, settings_api | 556 | — | — |
| `GET /admin/settings` | HTML | 19 | admin, api, pin, settings_api, theme | 803 | settings_hub | off |
| `GET /admin/settings/backup` | HTML | 20 | settings_api | 180 | settings_backup | off |
| `GET /admin/settings/clinic` | HTML | 27 | admin, api, doctors, settings_api | 733 | settings_clinic | off |
| `GET /admin/settings/crypt` | HTML | 66 | settings_api | 180 | — | — |
| `POST /admin/settings/crypt/confirm` | 303 | 22 | dbcrypt | 77 | — | — |
| `POST /admin/settings/crypt/off` | 303 | 8 | **—** | — | — | — |
| `POST /admin/settings/crypt/prepare` | 303 | 20 | dbcrypt | 77 | — | — |
| `GET /admin/settings/crypt/sheet` | HTML | 66 | dbcrypt | 77 | — | — |
| `GET /admin/settings/faq` | HTML | 9 | admin, dbcrypt, pin, settings_api | 736 | settings_faq | off |
| `GET /admin/settings/hours` | HTML | 63 | admin, settings_api | 556 | settings_hours | off |
| `GET /admin/settings/lan` | HTML | 9 | admin, settings_api | 556 | settings_lan | off |
| `POST /admin/settings/save` | 303 | 38 | admin, api, pin, review2, settings_api, theme | 822 | — | — |
| `GET /admin/settings/security` | HTML | 18 | pin, review2, settings_api | 302 | settings_security | off |
| `GET /admin/settings/services` | HTML | 118 | admin, review2, settings_api | 575 | settings_services | off |
| `GET /admin/settings/system` | HTML | 80 | admin, pin, settings_api | 659 | — | — |
| `GET /admin/settings/telegram` | HTML | 19 | admin, settings_api | 556 | — | — |
| `GET /admin/settings/theme` | HTML | 138 | settings_api, theme | 255 | settings_theme | off |
| `POST /admin/settings/theme/logo` | 303 | 15 | theme | 75 | — | — |
| `GET /admin/settings/theme/palette` | JSON | 11 | theme | 75 | — | — |
| `POST /admin/telegram/save` | HTML | 26 | **—** | — | — | — |
| `POST /admin/update/check` | 303 | 7 | **—** | — | — | — |
| `POST /admin/update/run` | HTML | 21 | **—** | — | — | — |
| `POST /admin/users/delete` | other | 5 | pin | 103 | — | — |
| `POST /admin/users/save` | other | 8 | api, doctors, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, visit_api | 933 | — | — |
| `GET /api/settings/backup` | JSON | 9 | settings_api | 180 | — | — |
| `GET /api/settings/clinic` | JSON | 4 | api | 69 | — | — |
| `POST /api/settings/clinic` | JSON | 25 | api | 69 | — | — |
| `GET /api/settings/faq` | JSON | 4 | settings_api | 180 | — | — |
| `GET /api/settings/hours` | JSON | 4 | settings_api | 180 | — | — |
| `POST /api/settings/hours` | JSON | 16 | settings_api | 180 | — | — |
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
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | doctors, odontogram_api, patient_card, pin, settings_api | 600 | — | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 154 | admin, doctors, pin, review3 | 623 | doctor_card | off |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 7 | admin, doctors, pin, review3 | 623 | — | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 6 | admin, doctors, pin, review3 | 623 | — | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 14 | admin, anamneza, api, doctors, migrate, patient_card, patients_api, pin, plan_acord, privacy, review2, review3, review3_auth, settings_api, theme, visit, visit_api | 1708 | — | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 7 | admin, doctors, pin, review2, review3, settings_api | 822 | — | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 108 | — | — |
| `GET /admin/medici` | HTML | 48 | admin, doctors, pin, settings_api | 767 | doctors_list | off |
| `POST /admin/medici/add` | 303 | 7 | doctors | 108 | — | — |
| `POST /admin/medici/colors` | 303 | 4 | doctors | 108 | — | — |
| `POST /admin/relink` | 303 | 12 | doctors | 108 | — | — |
| `GET /api/doctors` | JSON | 9 | doctors | 108 | — | — |
| `POST /api/doctors` | JSON | 10 | doctors | 108 | — | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 108 | — | — |
| `GET /api/doctors/{dk}` | JSON | 6 | doctors | 108 | — | — |
| `POST /api/doctors/{dk}` | JSON | 19 | doctors | 108 | — | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | doctors | 108 | — | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | doctors | 108 | — | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, doctors, review2, review3, settings_api | 719 | — | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, pin, theme | 554 | — | — |
| `GET /admin/stats` | HTML | 291 | admin, booking, patients_api, pin, review3 | 677 | — | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 376 | — | — |
| `GET /demo` | HTML | 14 | admin | 376 | — | — |
| `GET /qr` | other | 5 | settings_api | 180 | — | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy | 320 | — | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 5 | hardening, patient_card, privacy | 320 | — | — |
| `GET /admin/patient/{pid}` | HTML | 834 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | patient_card | off |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/alert` | 303 | 7 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 5 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 9 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 10 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 8 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 17 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/doc` | 303 | 7 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/erase` | 303 | 9 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, dbcrypt, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, settings_api, teeth, visit, visit_api | 2019 | — | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 28 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 35 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | odontogram | off |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 36 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/pay` | 303 | 7 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 5 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patient/{pid}/peek` | HTML | 11 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/perio` | 303 | 32 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 9 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/plan` | 303 | 8 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 24 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 5 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/save` | 303 | 8 | activity, admin, anamneza, api, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, review3_auth, settings_api, teeth, theme, visit, visit_api | 2115 | — | — |
| `GET /admin/patient/{pid}/slots` | JSON | 6 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 54 | activity, admin, anamneza, booking, bot, doctors, hardening, migrate, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 1762 | — | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 395 | — | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin, patients_api | 452 | — | — |
| `POST /admin/patients/new` | 303 | 16 | admin, anamneza, dbcrypt, doctors, hardening, odontogram_api, patient_card, patients_api, perio, pin, review2, teeth, visit | 1376 | — | — |
| `GET /admin/search` | HTML | 322 | activity, admin, anamneza, booking, bot, dbcrypt, hardening, odontogram_api, patient_card, patients_api, perio, pin, plan_acord, privacy, review2, review3, teeth, visit, visit_api | 1619 | patients_search | off |
| `GET /admin/visit/{appt_id}` | HTML | 19 | patient_card, plan_acord, visit, visit_api | 312 | visit | off |
| `POST /admin/visit/{appt_id}` | 303 | 13 | patient_card, plan_acord, visit, visit_api | 312 | visit | off |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, patient_card | 220 | — | — |
| `GET /api/patients` | JSON | 34 | patients_api | 76 | — | — |
| `POST /api/patients` | JSON | 18 | patients_api | 76 | — | — |
| `GET /api/patients/summary` | JSON | 31 | patients_api | 76 | — | — |
| `GET /api/patients/{pid}` | JSON | 8 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 8 | doctors, odontogram_api, patient_card, patients_api, pin, settings_api | 676 | — | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | anamneza, odontogram_api, patient_card, patients_api, privacy | 462 | — | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | admin, booking, odontogram_api, patient_card, patients_api | 747 | — | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | admin, odontogram_api, patient_card, patients_api | 661 | — | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | doctors, odontogram_api, patient_card, patients_api, pin, settings_api | 676 | — | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 8 | doctors, odontogram_api, patient_card, patients_api, pin, settings_api | 676 | — | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | anamneza, odontogram_api, patient_card, patients_api, perio, privacy, teeth, visit | 719 | — | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | doctors, odontogram_api, patient_card, patients_api, pin, settings_api | 676 | — | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | admin, odontogram_api, patient_card, patients_api, review2 | 680 | — | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, odontogram_api, patient_card, patients_api, plan_acord, privacy, review2, teeth, visit, visit_api | 1124 | — | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | doctors, odontogram_api, patient_card, patients_api, pin, settings_api | 676 | — | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, odontogram_api, patient_card, patients_api, plan_acord, privacy, review2, visit, visit_api | 952 | — | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 27 | odontogram_api, patient_card, patients_api | 285 | — | — |
| `GET /api/visits/{aid}` | JSON | 9 | visit_api | 55 | — | — |
| `POST /api/visits/{aid}` | JSON | 23 | visit_api | 55 | — | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /admin` | HTML | 162 | admin, api, booking, dbcrypt, doctors, hardening, migrate, patient_card, patients_api, pin, review3_auth, settings_api, theme, visit_api | 1602 | — | — |
| `POST /admin/add` | other | 104 | activity, admin, booking, bot, doctor_windows, hardening, migrate, patient_card, patients_api, plan_acord, privacy, review2, review3, review3_bot, visit, visit_api | 1302 | — | — |
| `GET /admin/all` | HTML | 49 | activity, admin, booking, bot, doctor_windows, doctors, hardening, migrate, patient_card, patients_api, pin, plan_acord, privacy, review2, review3, review3_bot, visit, visit_api | 1513 | — | — |
| `POST /admin/comment/{appt_id}` | other | 6 | privacy, visit_api | 155 | — | — |
| `GET /admin/doctor/{dk}` | HTML | 50 | admin, doctor_windows, pin, review3 | 545 | — | — |
| `GET /admin/export` | FILE | 35 | admin | 376 | — | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin | 376 | — | — |
| `POST /admin/move/{appt_id}` | other | 42 | booking, doctor_windows | 116 | — | — |
| `POST /admin/note` | other | 35 | booking | 86 | — | — |
| `POST /admin/status/{appt_id}` | 303 | 16 | activity, admin, booking, doctor_windows, patient_card, plan_acord, privacy, review3, visit, visit_api | 946 | — | — |
| `GET /admin/week` | HTML | 56 | admin | 376 | — | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |
|---|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, anamneza, booking, bot, dbcrypt, doctor_windows, doctors, guards, hardening, launcher, migrate, patient_card, patients_api, perio, pin, plan_acord, privacy, restart, review2, review3, review3_auth, review3_bot, settings_api, structure, teeth, theme, visit, visit_api | 2223 | — | — |
| `GET /admin/login` | HTML | 34 | admin, api, doctors, hardening, migrate, patient_card, patients_api, pin, review3_auth, settings_api, theme, visit_api | 1439 | — | — |
| `POST /admin/login` | 303 | 66 | admin, api, doctors, hardening, migrate, patient_card, patients_api, pin, review3_auth, settings_api, theme, visit_api | 1439 | — | — |
| `GET /admin/logout` | 303 | 6 | **—** | — | — | — |
| `POST /admin/pin/change` | 303 | 8 | pin, review3_auth, settings_api | 312 | — | — |
| `GET /admin/recover` | HTML | 6 | dbcrypt, hardening | 151 | — | — |
| `POST /admin/recover` | HTML | 17 | dbcrypt, hardening | 151 | — | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 103 | — | — |
| `GET /admin/setup` | HTML | 12 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, visit_api | 1007 | — | — |
| `POST /admin/setup` | HTML | 17 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, visit_api | 1007 | — | — |
| `POST /chat` | other | 13 | admin, bot, hardening, review3_bot | 489 | — | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 255 | — | — |
| `GET /favicon.ico` | other | 5 | admin | 376 | — | — |
| `GET /health` | other | 4 | admin, hardening | 450 | — | — |
| `GET /icon-{px}.png` | other | 11 | admin | 376 | — | — |
| `GET /manifest.webmanifest` | other | 31 | admin | 376 | — | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, doctors, odontogram_api, patient_card, patients_api, settings_api, visit_api | 1073 | — | — |

## Колонки-состояния


`Флаг` — имя экрана в `clinic.json` → `ui.react` (включает React-экран; `?ui=legacy` возвращает старый на один запрос).
`Пилот` — `off` / `on` / `откат`. `—` значит «ещё не начат».


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 834 | `GET /admin/patient/{pid}` | 19 |
| 322 | `GET /admin/search` | 19 |
| 291 | `GET /admin/stats` | 5 |
| 162 | `GET /admin` | 14 |
| 154 | `GET /admin/doctor-card/{dk}` | 4 |
| 138 | `GET /admin/settings/theme` | 2 |
| 118 | `GET /admin/settings/services` | 3 |
| 104 | `POST /admin/add` | 16 |
| 80 | `GET /admin/settings/system` | 3 |
| 66 | `POST /admin/login` | 12 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
