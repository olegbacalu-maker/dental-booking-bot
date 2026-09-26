# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **196** · наборов **56** · мест вызова `res.ok`/`res.check` в исходниках — **3964**.


⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть
вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок
на самом деле, говорит сам прогон (`.\dev test`).


⛔ Адресов, которые сборщик не смог разобрать: **0** — маршрут, объявленный через константу, раньше выпадал из карты
ЦЕЛИКОМ и молча: число маршрутов не менялось, жалобы не было.


## Маршруты без единой проверки


| Маршрут | Тип | стр | Замечание |
|---|---|---|---|
| `GET /admin/cabinet` | HTML | 17 | — |
| `POST /admin/lan/firewall` | 303 | 10 | правило брандмауэра, ⚠️ зовёт netsh через runas |
| `GET /admin/logout` | 303 | 6 | выход из журнала |
| `POST /admin/telegram/save` | HTML | 26 | сохранение токена бота (заморожен, но маршрут жив) |
| `POST /admin/update/check` | 303 | 7 | проверка обновлений |
| `POST /admin/update/run` | HTML | 21 | **самообновление** — спусковой крючок не проверен ничем |

⭐ Находка **не про миграцию**: дыры есть уже сейчас. `POST /admin/update/run` запускает подмену exe у клиники и не покрыт ничем.


## Настройки — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `POST /admin/backup/export` | FILE | 40 | dbcrypt, license_existing, pin, privacy, settings_api | 574 | — |
| `POST /admin/lan/firewall` | 303 | 10 | **—** | — | — |
| `POST /admin/lan/save` | HTML | 11 | admin, settings_api | 686 | — |
| `GET /admin/settings` | HTML | 23 | admin, api, pin, settings_api, theme | 965 | settings_hub |
| `GET /admin/settings/backup` | HTML | 20 | settings_api | 258 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 27 | admin, api, doctors, react_default, settings_api | 891 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 14 | settings_api | 258 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 10 | dbcrypt, settings_api | 335 | — |
| `POST /admin/settings/crypt/off` | 303 | 6 | settings_api | 258 | — |
| `POST /admin/settings/crypt/prepare` | 303 | 6 | dbcrypt | 77 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 61 | dbcrypt, settings_api | 335 | — |
| `GET /admin/settings/faq` | HTML | 9 | admin, dbcrypt, pin, settings_api | 866 | settings_faq |
| `GET /admin/settings/hours` | HTML | 63 | admin, settings_api | 686 | settings_hours |
| `GET /admin/settings/lan` | HTML | 12 | admin, settings_api | 686 | settings_lan |
| `POST /admin/settings/save` | 303 | 40 | admin, api, license_page, pin, review2, settings_api, theme | 1028 | — |
| `GET /admin/settings/security` | HTML | 18 | pin, review2, settings_api | 380 | settings_security |
| `GET /admin/settings/services` | HTML | 118 | admin, review2, settings_api | 705 | settings_services |
| `GET /admin/settings/system` | HTML | 7 | admin, pin, settings_api | 789 | settings_system |
| `GET /admin/settings/telegram` | HTML | 19 | admin, settings_api | 686 | — |
| `GET /admin/settings/theme` | HTML | 169 | settings_api, theme | 354 | settings_theme |
| `POST /admin/settings/theme/logo` | 303 | 15 | privacy, theme | 209 | — |
| `GET /admin/settings/theme/palette` | JSON | 11 | theme | 96 | — |
| `POST /admin/telegram/save` | HTML | 26 | **—** | — | — |
| `POST /admin/update/check` | 303 | 7 | **—** | — | — |
| `POST /admin/update/run` | HTML | 21 | **—** | — | — |
| `POST /admin/users/delete` | other | 5 | pin | 103 | — |
| `POST /admin/users/save` | other | 8 | api, doctors, license_renew, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1195 | — |
| `GET /api/settings/backup` | JSON | 9 | settings_api | 258 | — |
| `GET /api/settings/clinic` | JSON | 4 | api | 80 | — |
| `POST /api/settings/clinic` | JSON | 25 | api | 80 | — |
| `GET /api/settings/crypt` | JSON | 4 | settings_api | 258 | — |
| `POST /api/settings/crypt/off` | JSON | 14 | settings_api | 258 | — |
| `POST /api/settings/crypt/prepare` | JSON | 15 | settings_api | 258 | — |
| `GET /api/settings/faq` | JSON | 4 | settings_api | 258 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 686 | — |
| `POST /api/settings/hours` | JSON | 16 | admin, settings_api | 686 | — |
| `GET /api/settings/hub` | JSON | 8 | settings_api | 258 | — |
| `GET /api/settings/lan` | JSON | 8 | settings_api | 258 | — |
| `POST /api/settings/lan` | JSON | 21 | settings_api | 258 | — |
| `POST /api/settings/lan/firewall` | JSON | 9 | settings_api | 258 | — |
| `POST /api/settings/pin` | JSON | 14 | settings_api | 258 | — |
| `GET /api/settings/security` | JSON | 7 | settings_api | 258 | — |
| `GET /api/settings/services` | JSON | 4 | settings_api | 258 | — |
| `POST /api/settings/services` | JSON | 27 | settings_api | 258 | — |
| `GET /api/settings/system` | JSON | 4 | privileged, settings_api | 325 | — |
| `POST /api/settings/system/check` | JSON | 14 | settings_api | 258 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 67 | — |
| `GET /api/settings/theme` | JSON | 4 | settings_api | 258 | — |
| `POST /api/settings/theme` | JSON | 22 | settings_api | 258 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | settings_api | 258 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api | 258 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api | 258 | — |
| `POST /api/settings/users` | JSON | 14 | settings_api | 258 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 7 | doctors, license_gate, odontogram_api, patient_card, perio_api, pin, settings_api | 824 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 157 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1011 | doctor_card |
| `POST /admin/doctor-card/{dk}/photo` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1011 | — |
| `POST /admin/doctor-card/{dk}/photo/del` | 303 | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 1011 | — |
| `POST /admin/doctor-card/{dk}/save` | 303 | 14 | admin, admin_canvas, anamneza, api, day_actions, day_forms, doctors, license_page, license_renew, migrate, patient_card, patients_api, perio_api, pin, plan_acord, privacy, review2, review3, review3_auth, settings_api, stats_api, theme, visit, visit_api | 2428 | — |
| `POST /admin/doctor-card/{dk}/services` | 303 | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review2, review3, settings_api | 1288 | — |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 116 | — |
| `GET /admin/medici` | HTML | 53 | admin, doctors, pin, settings_api | 905 | doctors_list |
| `POST /admin/medici/add` | 303 | 7 | doctors | 116 | — |
| `POST /admin/medici/colors` | 303 | 4 | doctors | 116 | — |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors | 222 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 650 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 650 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 116 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin_canvas, day_forms, doctors, react_default | 311 | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin_canvas, day_forms, doctors, react_default | 311 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin_canvas, day_forms, doctors, react_default | 311 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin_canvas, day_forms, doctors, react_default | 311 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_forms, doctors, react_default, review2, review3, settings_api | 1052 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, pin, stats_api, theme | 675 | — |
| `GET /admin/stats` | HTML | 27 | admin, booking, patients_api, pin, review3, stats_api | 779 | stats |
| `GET /api/stats` | JSON | 21 | stats_api | 48 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/qr-print` | HTML | 54 | admin | 428 | — |
| `GET /demo` | HTML | 14 | admin | 428 | — |
| `GET /qr` | other | 5 | settings_api | 258 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | hardening, patient_card, privacy | 349 | — |
| `POST /admin/doc/{doc_id}/open` | JSON | 5 | hardening, license_gate, patient_card, privacy | 365 | — |
| `GET /admin/patient/{pid}` | HTML | 836 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/alert` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/alert/{aid}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/anamneza` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 10 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/appoint` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/archive` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, license_gate, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2100 | — |
| `POST /admin/patient/{pid}/bridge` | 303 | 17 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/bridge/{bid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/doc` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/doc/{doc_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/erase` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, doctors, guards, hardening, license_existing, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, settings_api, teeth, visit, visit_api | 2442 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 28 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 38 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 49 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/pay` | 303 | 7 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/pay/{pay_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `GET /admin/patient/{pid}/peek` | HTML | 11 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/perio` | 303 | 29 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/perio/new` | 303 | 9 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/perio/{eid}/del` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/plan` | 303 | 8 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 24 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/del` | other | 4 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/plan/{item_id}/status` | other | 5 | activity, admin, anamneza, booking, bot, chair, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, schedule_api, teeth, visit, visit_api | 2242 | — |
| `POST /admin/patient/{pid}/save` | 303 | 8 | activity, admin, admin_canvas, anamneza, api, booking, bot, day_actions, day_forms, doctors, guards, hardening, license_page, license_renew, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3_auth, settings_api, stats_api, teeth, theme, visit, visit_api | 2888 | — |
| `GET /admin/patient/{pid}/slots` | JSON | 6 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `POST /admin/patient/{pid}/tooth` | 303 | 54 | activity, admin, anamneza, booking, bot, day_forms, doctors, guards, hardening, migrate, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, teeth, visit, visit_api | 2084 | — |
| `GET /admin/patients.csv` | FILE | 34 | admin, review2 | 447 | — |
| `GET /admin/patients.xlsx` | FILE | 48 | admin, patients_api | 506 | — |
| `POST /admin/patients/new` | 303 | 16 | admin, anamneza, dbcrypt, doctors, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, review2, teeth, visit | 1569 | — |
| `GET /admin/search` | HTML | 323 | activity, admin, anamneza, booking, bot, day_forms, dbcrypt, hardening, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, review2, review3, teeth, visit, visit_api | 1897 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 20 | day_forms, patient_card, plan_acord, visit, visit_api | 408 | visit |
| `POST /admin/visit/{appt_id}` | 303 | 13 | day_forms, patient_card, plan_acord, visit, visit_api | 408 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card | 252 | — |
| `GET /api/patients` | JSON | 34 | license_existing, license_gate, license_page, license_renew, patients_api, react_default | 269 | — |
| `POST /api/patients` | JSON | 18 | license_existing, license_gate, license_page, license_renew, patients_api, react_default | 269 | — |
| `GET /api/patients/summary` | JSON | 31 | patients_api | 78 | — |
| `GET /api/patients/{pid}` | JSON | 8 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 7 | doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 925 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | anamneza, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, privacy | 638 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 13 | admin, booking, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 962 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | admin, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 876 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 925 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 7 | doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 925 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | anamneza, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api, privacy, teeth, visit | 904 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 925 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | admin, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, review2 | 895 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio, perio_api | 475 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 925 | — |
| `POST /api/patients/{pid}/plan` | JSON | 11 | activity, admin, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, review2, teeth, visit, visit_api | 1361 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, pin, settings_api | 925 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, chair, doctors, license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api, plan_acord, privacy, review2, schedule_api, visit, visit_api | 1454 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 36 | license_existing, license_gate, odontogram_api, patient_card, patients_api, perio_api | 448 | — |
| `GET /api/visits/{aid}` | JSON | 9 | visit_api | 55 | — |
| `POST /api/visits/{aid}` | JSON | 23 | visit_api | 55 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 187 | admin, admin_canvas, api, booking, day_forms, dbcrypt, doctors, hardening, license_existing, license_gate, license_page, license_renew, migrate, panel_model, patient_card, patients_api, pin, react_default, review3_auth, schedule_api, settings_api, split, stats_api, structure, theme, visit_api | 2492 | schedule_dash |
| `POST /admin/add` | other | 14 | activity, admin, admin_canvas, booking, bot, chair, day_actions, day_forms, doctor_windows, doctors, hardening, migrate, patient_card, patients_api, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 1946 | — |
| `GET /admin/all` | HTML | 64 | activity, admin, admin_canvas, api, booking, bot, day_actions, day_forms, doctor_windows, doctors, hardening, migrate, panel_model, patient_card, patients_api, pin, plan_acord, privacy, react_default, review2, review3, review3_bot, schedule_api, stats_api, visit, visit_api | 2158 | schedule_all |
| `GET /admin/cabinet` | HTML | 17 | **—** | — | chair |
| `POST /admin/comment/{appt_id}` | other | 5 | day_actions, day_forms, privacy, visit_api | 292 | — |
| `GET /admin/doctor/{dk}` | HTML | 56 | admin, admin_canvas, api, day_forms, doctor_windows, grid, pin, review3, schedule_api | 1017 | schedule_doctor |
| `GET /admin/export` | FILE | 35 | admin | 428 | — |
| `GET /admin/export.xlsx` | FILE | 39 | admin, day_forms | 508 | — |
| `POST /admin/move/{appt_id}` | other | 9 | booking, day_actions, day_forms, doctor_windows | 240 | — |
| `POST /admin/note` | other | 9 | admin, admin_canvas, booking, chair, day_actions, day_forms, schedule_api | 902 | — |
| `POST /admin/status/{appt_id}` | 303 | 11 | activity, admin, admin_canvas, booking, day_forms, doctor_windows, panel_model, patient_card, plan_acord, privacy, review3, schedule_api, visit, visit_api | 1400 | — |
| `GET /admin/week` | HTML | 41 | admin, schedule_api | 546 | schedule_week |
| `GET /api/chair` | JSON | 29 | chair | 40 | — |
| `POST /api/schedule/appointments` | JSON | 22 | day_actions | 44 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 16 | chair, day_actions, doctors, schedule_api | 318 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 18 | booking, chair, day_actions, doctor_windows, doctors, schedule_api | 434 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 18 | activity, admin, chair, day_actions, doctors, patient_card, patients_api, plan_acord, privacy, review2, schedule_api, visit, visit_api | 1290 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas, schedule_api | 224 | — |
| `GET /api/schedule/day` | JSON | 17 | day_actions, schedule_api | 162 | — |
| `GET /api/schedule/live` | JSON | 36 | panel_model, schedule_api | 187 | — |
| `POST /api/schedule/notes` | JSON | 19 | day_actions | 44 | — |
| `GET /api/schedule/week` | JSON | 14 | schedule_api | 118 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /` | HTML | 6 | activity, admin, admin_canvas, anamneza, api, booking, bot, chair, day_forms, dbcrypt, doctor_windows, doctors, grid, guards, hardening, harness_tmp, installer, launcher, legacy, license_existing, license_format, license_gate, license_page, license_renew, license_state, license_verify, migrate, netcheck, odontogram_api, panel_model, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, privileged, react_default, relocate, restart, review2, review3, review3_auth, review3_bot, schedule_api, settings_api, split, srcpin, structure, teeth, theme, visit, visit_api | 3872 | — |
| `GET /admin/license` | HTML | 9 | license_existing, license_page, license_renew | 166 | — |
| `POST /admin/license` | 303 | 22 | license_existing, license_page, license_renew | 166 | — |
| `POST /admin/license/renew` | 303 | 10 | license_renew | 99 | — |
| `POST /admin/license/request` | 303 | 19 | license_renew | 99 | — |
| `POST /admin/license/verify` | 303 | 12 | license_renew | 99 | — |
| `GET /admin/login` | HTML | 34 | admin, api, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, pin, review3_auth, settings_api, stats_api, theme, visit_api | 1875 | — |
| `POST /admin/login` | 303 | 66 | admin, api, doctors, hardening, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, pin, review3_auth, settings_api, stats_api, theme, visit_api | 1875 | — |
| `GET /admin/logout` | 303 | 6 | **—** | — | — |
| `POST /admin/pin/change` | 303 | 8 | pin, review3_auth, settings_api | 390 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 151 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 151 | — |
| `POST /admin/security/ack` | 303 | 8 | pin | 103 | — |
| `GET /admin/setup` | HTML | 12 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1170 | — |
| `POST /admin/setup` | HTML | 17 | api, doctors, hardening, migrate, patient_card, patients_api, pin, review2, review3_auth, settings_api, stats_api, visit_api | 1170 | — |
| `GET /api/license` | JSON | 6 | license_existing, license_page, license_renew | 166 | — |
| `POST /chat` | other | 13 | admin, bot, hardening, license_gate, review3_bot | 557 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 354 | — |
| `GET /favicon.ico` | other | 5 | admin | 428 | — |
| `GET /health` | other | 4 | admin, hardening, license_renew, netcheck | 642 | — |
| `GET /icon-{px}.png` | other | 11 | admin | 428 | — |
| `GET /manifest.webmanifest` | other | 31 | admin | 428 | — |
| `GET /static/{kind}/{name}` | other | 28 | admin, api, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, structure, visit_api | 1510 | — |

## Прочее — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/migration` | HTML | 45 | guards, split | 80 | — |
| `POST /admin/migration/confirm` | 303 | 32 | split | 44 | — |

## Колонки-состояния


`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности. С 21.09 она отдаётся ПО УМОЛЧАНИЮ: `ui.react` в профиле стал аварийным выключателем, а не рубильником выката (`?ui=legacy` по-прежнему возвращает старую страницу на один запрос). `—` значит «страница серверная по замыслу» — печать и аварийные экраны.


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 836 | `GET /admin/patient/{pid}` | 22 |
| 323 | `GET /admin/search` | 21 |
| 187 | `GET /admin` | 26 |
| 169 | `GET /admin/settings/theme` | 2 |
| 157 | `GET /admin/doctor-card/{dk}` | 8 |
| 118 | `GET /admin/settings/services` | 3 |
| 66 | `POST /admin/login` | 17 |
| 64 | `GET /admin/all` | 26 |
| 63 | `GET /admin/settings/hours` | 2 |
| 61 | `GET /admin/settings/crypt/sheet` | 2 |

⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует разделить его логически; арифметика внутри сегодня проверяется только через готовую страницу.
