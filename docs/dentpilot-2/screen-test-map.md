# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **209** · наборов **79** · мест вызова `res.ok`/`res.check` в исходниках — **5611**.


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
| `POST /admin/backup/export` | FILE | 42 | backup, dbcrypt, demo, license_existing, pin, privacy, settings_api | 902 | — |
| `GET /admin/settings` | HTML | 7 | admin, api, demo, pin, settings_api | 955 | settings_hub |
| `GET /admin/settings/backup` | HTML | 7 | backup, demo, settings_api | 458 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 6 | admin, api, demo, settings_api | 728 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 12 | demo, restart, settings_api | 367 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 12 | dbcrypt, demo, settings_api | 408 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 64 | dbcrypt, pin, settings_api | 585 | — |
| `GET /admin/settings/faq` | HTML | 7 | admin, demo, paylink, pin, settings_api | 925 | settings_faq |
| `GET /admin/settings/hours` | HTML | 5 | admin, demo, settings_api | 660 | settings_hours |
| `GET /admin/settings/lan` | HTML | 7 | admin, demo, settings_api | 660 | settings_lan |
| `GET /admin/settings/security` | HTML | 7 | demo, pin, settings_api | 558 | settings_security |
| `GET /admin/settings/services` | HTML | 5 | admin, demo, settings_api | 660 | settings_services |
| `GET /admin/settings/sms` | HTML | 13 | doctor_rights, notices, sms | 342 | settings_sms |
| `GET /admin/settings/system` | HTML | 5 | admin, backup, demo, notices, pin, settings_api, update_server | 1115 | settings_system |
| `GET /admin/settings/templates` | HTML | 5 | visit_tpl | 40 | settings_templates |
| `GET /admin/settings/theme` | HTML | 13 | demo, settings_api, theme | 441 | settings_theme |
| `POST /admin/update/run` | HTML | 34 | demo | 50 | — |
| `POST /api/settings/autostart` | JSON | 17 | notices | 81 | — |
| `GET /api/settings/backup` | JSON | 9 | backup, demo, pin, settings_api | 685 | — |
| `POST /api/settings/backup/auto` | JSON | 47 | backup, settings_api | 408 | — |
| `POST /api/settings/backup/auto/run` | JSON | 12 | backup | 127 | — |
| `POST /api/settings/backup/restore/cancel` | JSON | 7 | backup | 127 | — |
| `POST /api/settings/backup/restore/confirm` | JSON | 19 | backup | 127 | — |
| `POST /api/settings/backup/restore/stage` | JSON | 44 | backup, pin | 354 | — |
| `GET /api/settings/clinic` | JSON | 4 | admin, api, pin, privacy | 741 | — |
| `POST /api/settings/clinic` | JSON | 25 | admin, api, pin, privacy | 741 | — |
| `GET /api/settings/crypt` | JSON | 4 | demo, pin, settings_api | 558 | — |
| `POST /api/settings/crypt/off` | JSON | 16 | settings_api | 281 | — |
| `POST /api/settings/crypt/prepare` | JSON | 17 | dbcrypt, settings_api | 358 | — |
| `GET /api/settings/faq` | JSON | 4 | admin, cont_link, dbcrypt, paylink, settings_api | 744 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, settings_api | 610 | — |
| `POST /api/settings/hours` | JSON | 15 | admin, settings_api | 610 | — |
| `GET /api/settings/hub` | JSON | 8 | admin, api, backup, demo, paylink, settings_api, sms, theme, update_server, visit_tpl | 1252 | — |
| `GET /api/settings/lan` | JSON | 8 | admin, pin, settings_api | 837 | — |
| `POST /api/settings/lan` | JSON | 22 | admin, pin, settings_api | 837 | — |
| `POST /api/settings/lan/firewall` | JSON | 9 | settings_api | 281 | — |
| `POST /api/settings/pin` | JSON | 15 | demo, pin, review3_auth, settings_api | 588 | — |
| `GET /api/settings/security` | JSON | 7 | demo, pin, settings_api | 558 | — |
| `GET /api/settings/services` | JSON | 4 | admin, recall, review2, settings_api, visit_tpl | 833 | — |
| `POST /api/settings/services` | JSON | 26 | admin, recall, review2, settings_api, visit_tpl | 833 | — |
| `GET /api/settings/sms` | JSON | 6 | doctor_rights, notices, recall, sms | 508 | — |
| `POST /api/settings/sms` | JSON | 17 | doctor_rights, notices, recall, sms | 508 | — |
| `POST /api/settings/sms/order` | JSON | 21 | sms | 189 | — |
| `POST /api/settings/sms/refresh` | JSON | 11 | doctor_rights, notices, recall, sms | 508 | — |
| `POST /api/settings/sms/sender` | JSON | 12 | sms | 189 | — |
| `POST /api/settings/sms/test` | JSON | 13 | sms | 189 | — |
| `GET /api/settings/system` | JSON | 4 | admin, backup, demo, notices, privileged, settings_api | 980 | — |
| `POST /api/settings/system/check` | JSON | 14 | notices, settings_api | 362 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 112 | — |
| `GET /api/settings/templates` | JSON | 4 | visit_tpl | 40 | — |
| `POST /api/settings/templates` | JSON | 28 | visit_tpl | 40 | — |
| `GET /api/settings/theme` | JSON | 4 | admin, settings_api, theme | 720 | — |
| `POST /api/settings/theme` | JSON | 23 | admin, settings_api, theme | 720 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | backup, privacy, settings_api, theme | 635 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | settings_api, theme | 391 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api, theme | 391 | — |
| `POST /api/settings/users` | JSON | 18 | api, backup, cont_link, demo, desk, doctor_rights, doctors, license_email, license_renew, migrate, patient_card, patients_api, paylink, pin, recall, registre, review2, review3_auth, settings_api, sms, stats_api, visit_api, visit_tpl | 2161 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 9 | activity, admin, doctors, hardening, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, registre, settings_api, teeth, theme | 2093 | — |
| `GET /shell/notices` | JSON | 8 | launcher, notices | 186 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 11 | doctors, pin | 341 | doctor_card |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 114 | — |
| `GET /admin/medici` | HTML | 10 | admin, demo, doctors, pin, settings_api | 1001 | doctors_list |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors, license_page | 249 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors | 530 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors | 530 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors | 114 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 963 | — |
| `POST /api/doctors/{dk}` | JSON | 19 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 963 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 963 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, review3 | 963 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_actions, day_forms, demo, doctors, perio_api, pin, recall, review2, review3, settings_api, visit_tpl | 1517 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, desk, pin, stats_api, theme | 745 | — |
| `GET /admin/stats` | HTML | 21 | admin, anamneza, demo, patients_api, pin, review3, stats_api | 854 | stats |
| `GET /api/stats` | JSON | 23 | admin, backup, demo, hardening, orders, pin, schedule_api, stats_api | 1104 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /qr` | other | 5 | admin, settings_api | 610 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | backup, hardening, patient_card, privacy, scan, sign | 519 | — |
| `GET /admin/patient/{pid}` | HTML | 17 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 14 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, backup, dbcrypt, demo, guards, license_existing, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, recall, review2, settings_api, sign, sms, teeth, visit, visit_api | 2908 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 30 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 24 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 24 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 25 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | — |
| `GET /admin/patient/{pid}/sign/{key}` | HTML | 15 | activity, anamneza, demo, guards, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, sign, sms, teeth, visit, visit_api | 1844 | — |
| `GET /admin/patients.xlsx` | FILE | 53 | admin, patients_api, pin | 613 | — |
| `GET /admin/search` | HTML | 21 | admin, anamneza, demo, patient_card, patients_api, pin | 910 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 19 | patient_card, visit, visit_api | 239 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card | 234 | — |
| `GET /api/patients` | JSON | 29 | admin, anamneza, backup, booking, dbcrypt, demo, license_email, license_existing, license_gate, license_page, license_renew, license_terms, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, sign, stats_api, teeth | 2327 | — |
| `POST /api/patients` | JSON | 18 | admin, anamneza, backup, booking, dbcrypt, demo, license_email, license_existing, license_gate, license_page, license_renew, license_terms, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pin, plan_acord, privacy, react_default, review2, scan, sign, stats_api, teeth | 2327 | — |
| `GET /api/patients/summary` | JSON | 34 | admin, patients_api | 386 | — |
| `GET /api/patients/{pid}` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 7 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, registre, review2, scan, schedule_api, settings_api, sign, sms, stats_api, teeth, theme, visit, visit_api, visit_tpl | 3753 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 17 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, registre, review2, scan, schedule_api, settings_api, sign, sms, stats_api, teeth, theme, visit, visit_api, visit_tpl | 3753 | — |
| `POST /api/patients/{pid}/doctor` | JSON | 13 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 7 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, registre, review2, scan, schedule_api, settings_api, sign, sms, stats_api, teeth, theme, visit, visit_api, visit_tpl | 3753 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/forms/{key}/sign` | JSON | 43 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/mkt` | JSON | 16 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/ocluzie` | JSON | 20 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `GET /api/patients/{pid}/odontogram/compare` | JSON | 33 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/odontogram/preview` | JSON | 19 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, registre, review2, scan, schedule_api, settings_api, sign, sms, stats_api, teeth, theme, visit, visit_api, visit_tpl | 3753 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, registre, review2, scan, schedule_api, settings_api, sign, sms, stats_api, teeth, theme, visit, visit_api, visit_tpl | 3753 | — |
| `POST /api/patients/{pid}/plan` | JSON | 21 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, registre, review2, scan, schedule_api, settings_api, sign, sms, stats_api, teeth, theme, visit, visit_api, visit_tpl | 3753 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, admin_canvas, anamneza, backup, booking, chair, day_actions, day_forms, demo, desk, doctor_rights, doctors, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, panel_model, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3467 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/scan/cancel` | JSON | 5 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/scan/finish` | JSON | 25 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/scan/page` | JSON | 15 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/sms-off` | JSON | 15 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/teeth` | JSON | 25 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 26 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, hardening, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, react_default, recall, review2, scan, schedule_api, sign, sms, stats_api, teeth, visit, visit_api, visit_tpl | 3176 | — |
| `GET /api/scan/status` | JSON | 6 | scan | 25 | — |
| `GET /api/visits/{aid}` | JSON | 9 | chair, day_forms, patient_card, plan_acord, schedule_api, visit, visit_api, visit_tpl | 615 | — |
| `POST /api/visits/{aid}` | JSON | 23 | chair, day_forms, patient_card, plan_acord, schedule_api, visit, visit_api, visit_tpl | 615 | — |
| `GET /api/visits/{aid}/template` | JSON | 16 | chair, day_forms, patient_card, plan_acord, schedule_api, visit, visit_api, visit_tpl | 615 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 28 | admin, admin_canvas, api, backup, cont_link, dbcrypt, demo, desk, doctor_rights, doctors, hardening, license_email, license_existing, license_gate, license_page, license_renew, license_terms, migrate, notices, orders, patient_card, patients_api, paylink, pin, react_default, recall, registre, review3_auth, schedule_api, settings_api, sms, split, stats_api, structure, theme, update_server, visit_api, visit_tpl | 3425 | schedule_dash |
| `GET /admin/all` | HTML | 17 | admin, admin_canvas, demo, doctor_rights, doctors, pin, schedule_api, visit_api | 1100 | schedule_all |
| `GET /admin/cabinet` | HTML | 10 | chair, doctor_rights | 117 | chair |
| `GET /admin/doctor/{dk}` | HTML | 16 | admin, doctor_rights, pin, schedule_api | 811 | schedule_doctor |
| `GET /admin/export.xlsx` | FILE | 43 | admin, doctor_rights, pin | 628 | — |
| `GET /admin/week` | HTML | 13 | admin, demo, schedule_api | 562 | schedule_week |
| `GET /api/chair` | JSON | 34 | admin, chair, doctor_rights | 446 | — |
| `POST /api/schedule/appointments` | JSON | 32 | activity, admin, admin_canvas, chair, day_actions, day_forms, desk, doctor_windows, doctors, hardening, patient_card, patients_api, plan_acord, privacy, react_default, schedule_api, stats_api, visit, visit_api, visit_tpl | 1556 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 18 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, schedule_api, sms, structure, visit, visit_api | 2072 | — |
| `POST /api/schedule/appointments/{appt_id}/duration` | JSON | 19 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, schedule_api, sms, structure, visit, visit_api | 2072 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 23 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, schedule_api, sms, structure, visit, visit_api | 2072 | — |
| `GET /api/schedule/appointments/{appt_id}/service` | JSON | 23 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, schedule_api, sms, structure, visit, visit_api | 2072 | — |
| `POST /api/schedule/appointments/{appt_id}/service` | JSON | 20 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, schedule_api, sms, structure, visit, visit_api | 2072 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 20 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, patients_api, plan_acord, privacy, recall, review2, scan, schedule_api, sms, structure, visit, visit_api, visit_tpl | 2264 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas, doctor_rights, harness_clock, schedule_api | 356 | — |
| `GET /api/schedule/day` | JSON | 23 | admin, day_actions, desk, doctor_rights, pin, recall, schedule_api | 1047 | — |
| `POST /api/schedule/desk/call/{aid}` | JSON | 27 | admin_canvas, desk, doctor_rights, structure | 253 | — |
| `GET /api/schedule/live` | JSON | 34 | admin, demo, desk, doctor_rights, recall, schedule_api | 825 | — |
| `POST /api/schedule/notes` | JSON | 21 | admin, admin_canvas, booking, chair, day_actions, day_forms, doctor_rights, schedule_api | 899 | — |
| `POST /api/schedule/sms-of` | JSON | 16 | sms | 189 | — |
| `GET /api/schedule/week` | JSON | 14 | admin, doctor_rights, schedule_api | 584 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/license` | HTML | 9 | cont_link, demo, license_email, license_existing, license_page, license_renew, license_terms, notices, paylink | 461 | — |
| `POST /admin/license` | 303 | 22 | cont_link, demo, license_email, license_existing, license_page, license_renew, license_terms, notices, paylink | 461 | — |
| `POST /admin/license/email/change` | other | 4 | license_email | 39 | — |
| `POST /admin/license/email/code` | other | 4 | license_email | 39 | — |
| `POST /admin/license/email/confirm` | other | 3 | license_email | 39 | — |
| `POST /admin/license/email/later` | 303 | 7 | license_email | 39 | — |
| `POST /admin/license/renew` | 303 | 10 | license_email, license_renew, license_terms, paylink | 240 | — |
| `POST /admin/license/request` | 303 | 19 | license_page, license_renew, license_terms | 211 | — |
| `POST /admin/license/terms` | 303 | 13 | license_terms | 46 | — |
| `POST /admin/license/verify` | 303 | 12 | license_renew | 117 | — |
| `GET /admin/login` | HTML | 42 | admin, api, backup, chair, cont_link, demo, desk, doctor_rights, doctors, hardening, license_email, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, recall, registre, review3_auth, settings_api, sms, stats_api, theme, visit_api, visit_tpl | 2824 | — |
| `POST /admin/login` | 303 | 27 | admin, api, backup, chair, cont_link, demo, desk, doctor_rights, doctors, hardening, license_email, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pin, recall, registre, review3_auth, settings_api, sms, stats_api, theme, visit_api, visit_tpl | 2824 | — |
| `GET /admin/logout` | 303 | 8 | demo, pin | 277 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 149 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 149 | — |
| `POST /admin/security/ack` | 303 | 8 | orders, pin | 289 | — |
| `GET /admin/setup` | HTML | 16 | api, backup, desk, doctor_rights, doctors, hardening, migrate, patient_card, patients_api, pin, recall, registre, review2, review3_auth, settings_api, sms, stats_api, visit_api, visit_tpl | 1970 | — |
| `POST /admin/setup` | HTML | 29 | api, backup, desk, doctor_rights, doctors, hardening, migrate, patient_card, patients_api, pin, recall, registre, review2, review3_auth, settings_api, sms, stats_api, visit_api, visit_tpl | 1970 | — |
| `POST /admin/setup/ask` | 303 | 13 | pin | 227 | — |
| `POST /api/auth/login` | JSON | 36 | hardening, license_gate, pin, structure | 390 | — |
| `POST /api/auth/logout` | JSON | 11 | license_gate, pin | 249 | — |
| `GET /api/license` | JSON | 6 | demo, license_existing, license_page, license_renew | 238 | — |
| `POST /api/license/terms` | JSON | 11 | license_terms | 46 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 391 | — |
| `GET /cont/{ticket}` | HTML | 14 | cont_link | 19 | — |
| `GET /favicon.ico` | other | 5 | admin, demo | 379 | — |
| `GET /health` | other | 4 | admin, demo, guards, hardening, harness_client, license_renew, netcheck, pin | 917 | — |
| `GET /icon-{px}.png` | other | 11 | admin, demo | 379 | — |
| `GET /manifest.webmanifest` | other | 31 | admin, demo | 379 | — |
| `GET /plata/{ticket}` | HTML | 16 | cont_link, paylink, sms | 246 | — |
| `GET /static/{kind}/{name}` | other | 37 | admin, api, demo, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, split, structure, theme, visit_api | 1735 | — |

## Прочее — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/migration` | HTML | 43 | guards, split | 102 | — |
| `POST /admin/migration/confirm` | 303 | 32 | split | 45 | — |
| `GET /admin/rechemari` | HTML | 5 | recall | 166 | recall |
| `GET /admin/registre` | HTML | 5 | registre | 72 | registre |
| `GET /admin/registre/excel/{form}` | FILE | 11 | registre | 72 | — |
| `GET /admin/registre/tipar/{form}` | HTML | 20 | registre | 72 | — |
| `GET /admin/settings/registre` | HTML | 4 | registre, settings_api | 353 | settings_registre |
| `GET /api/recall` | JSON | 21 | demo, migrate, recall | 397 | — |
| `POST /api/recall/mark` | JSON | 32 | recall | 166 | — |
| `POST /api/recall/sms` | JSON | 32 | recall | 166 | — |
| `GET /api/registre` | JSON | 5 | registre | 72 | — |
| `POST /api/registre/257` | other | 4 | registre | 72 | — |
| `POST /api/registre/257/{row_id}/bio` | other | 4 | registre | 72 | — |
| `POST /api/registre/257/{row_id}/finish` | other | 5 | registre, scan | 97 | — |
| `POST /api/registre/501` | other | 4 | registre | 72 | — |
| `POST /api/registre/501/{row_id}/off` | other | 4 | registre, settings_api | 353 | — |
| `POST /api/registre/502` | other | 4 | registre | 72 | — |
| `POST /api/registre/502/{row_id}/sup` | other | 4 | registre | 72 | — |
| `POST /api/registre/{form}/{row_id}/delete` | JSON | 11 | activity, admin, doctors, hardening, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, registre, settings_api, teeth, theme | 2093 | — |
| `POST /api/registre/{form}/{row_id}/fix` | other | 4 | registre | 72 | — |
| `GET /api/settings/registre` | JSON | 4 | registre | 72 | — |
| `POST /api/settings/registre/item` | JSON | 21 | registre | 72 | — |
| `POST /api/settings/registre/lamp/{lamp_id}/new` | other | 4 | registre | 72 | — |

## Колонки-состояния


`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности; старой страницы у неё нет (сняты по разделам 12–13.10, `legacy-removal.md`; ключ `ui.react` и `?ui=legacy` сняты там же). `—` значит «страница серверная по замыслу» — печать и аварийные экраны.


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 64 | `GET /admin/settings/crypt/sheet` | 3 |
| 53 | `GET /admin/patients.xlsx` | 3 |
| 47 | `POST /api/settings/backup/auto` | 2 |
| 44 | `POST /api/settings/backup/restore/stage` | 2 |
| 43 | `GET /admin/migration` | 2 |
| 43 | `POST /api/patients/{pid}/forms/{key}/sign` | 36 |
| 43 | `GET /admin/export.xlsx` | 3 |
| 42 | `GET /admin/login` | 29 |
| 42 | `POST /admin/backup/export` | 7 |
| 37 | `GET /static/{kind}/{name}` | 14 |
