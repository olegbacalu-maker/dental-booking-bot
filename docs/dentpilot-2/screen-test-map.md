# Карта экранов DentPilot 2.0

Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом
наборов). ⚠️ Файл **производный**: правится не он, а генератор.
Пересобрать — `python scripts/screen_map.py`.


Маршрутов **291** · наборов **91** · мест вызова `res.ok`/`res.check` в исходниках — **7099**.


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
| `POST /admin/backup/export` | FILE | 42 | backup, dbcrypt, demo, license_existing, pin, privacy, settings_api | 929 | — |
| `GET /admin/settings` | HTML | 8 | admin, api, demo, pimport, pin, plan_tpl, settings_api | 1207 | settings_hub |
| `GET /admin/settings/backup` | HTML | 7 | backup, demo, plan_tpl, settings_api | 526 | settings_backup |
| `GET /admin/settings/clinic` | HTML | 6 | admin, api, demo, plan_tpl, settings_api | 796 | settings_clinic |
| `GET /admin/settings/crypt` | HTML | 12 | demo, plan_tpl, restart, settings_api | 435 | settings_crypt |
| `POST /admin/settings/crypt/confirm` | 303 | 12 | dbcrypt, demo, settings_api | 420 | — |
| `GET /admin/settings/crypt/sheet` | HTML | 64 | dbcrypt, pin, settings_api | 590 | — |
| `GET /admin/settings/faq` | HTML | 7 | admin, demo, paylink, pin, plan_tpl, settings_api | 993 | settings_faq |
| `GET /admin/settings/hours` | HTML | 5 | admin, demo, plan_tpl, settings_api | 728 | settings_hours |
| `GET /admin/settings/lan` | HTML | 7 | admin, demo, settings_api | 672 | settings_lan |
| `GET /admin/settings/security` | HTML | 7 | demo, pin, plan_tpl, settings_api | 626 | settings_security |
| `GET /admin/settings/services` | HTML | 5 | admin, demo, plan_tpl, settings_api | 728 | settings_services |
| `GET /admin/settings/sms` | HTML | 13 | doctor_rights, notices, sms | 342 | settings_sms |
| `GET /admin/settings/system` | HTML | 5 | admin, backup, demo, notices, pin, plan_tpl, settings_api, update_server | 1183 | settings_system |
| `GET /admin/settings/templates` | HTML | 5 | plan_tpl, settings_api, visit_tpl | 383 | settings_templates |
| `GET /admin/settings/theme` | HTML | 13 | demo, plan_tpl, settings_api, theme | 523 | settings_theme |
| `POST /admin/update/run` | HTML | 34 | demo | 57 | — |
| `POST /api/settings/autostart` | JSON | 17 | notices | 81 | — |
| `GET /api/settings/backup` | JSON | 9 | backup, demo, pin, plan_tpl, settings_api | 753 | — |
| `POST /api/settings/backup/auto` | JSON | 47 | backup, plan_tpl, settings_api | 469 | — |
| `POST /api/settings/backup/auto/run` | JSON | 12 | backup | 127 | — |
| `POST /api/settings/backup/restore/cancel` | JSON | 7 | backup | 127 | — |
| `POST /api/settings/backup/restore/confirm` | JSON | 19 | backup | 127 | — |
| `POST /api/settings/backup/restore/stage` | JSON | 44 | backup, pin | 354 | — |
| `GET /api/settings/clinic` | JSON | 4 | admin, api, pin, plan_tpl, privacy | 812 | — |
| `POST /api/settings/clinic` | JSON | 25 | admin, api, pin, plan_tpl, privacy | 812 | — |
| `GET /api/settings/crypt` | JSON | 4 | demo, pin, plan_tpl, settings_api | 626 | — |
| `POST /api/settings/crypt/off` | JSON | 16 | settings_api | 286 | — |
| `POST /api/settings/crypt/prepare` | JSON | 17 | dbcrypt, settings_api | 363 | — |
| `GET /api/settings/faq` | JSON | 4 | admin, cont_link, dbcrypt, paylink, plan_tpl, settings_api | 805 | — |
| `GET /api/settings/hours` | JSON | 4 | admin, plan_tpl, settings_api | 671 | — |
| `POST /api/settings/hours` | JSON | 15 | admin, plan_tpl, settings_api | 671 | — |
| `GET /api/settings/hub` | JSON | 8 | admin, api, backup, demo, gcal, lab_pages, paylink, pimport, plan_tpl, settings_api, sms, theme, update_server, visit_tpl | 1680 | — |
| `GET /api/settings/lan` | JSON | 8 | admin, pin, settings_api | 842 | — |
| `POST /api/settings/lan` | JSON | 22 | admin, pin, settings_api | 842 | — |
| `POST /api/settings/lan/firewall` | JSON | 9 | settings_api | 286 | — |
| `POST /api/settings/pin` | JSON | 15 | demo, pin, review3_auth, settings_api | 600 | — |
| `GET /api/settings/plan-templates` | JSON | 4 | plan_insert, plan_tpl | 112 | — |
| `POST /api/settings/plan-templates` | JSON | 21 | plan_insert, plan_tpl | 112 | — |
| `GET /api/settings/security` | JSON | 7 | demo, pin, plan_tpl, settings_api | 626 | — |
| `GET /api/settings/services` | JSON | 4 | admin, plan_tpl, recall, review2, settings_api, visit_tpl | 895 | — |
| `POST /api/settings/services` | JSON | 28 | admin, plan_tpl, recall, review2, settings_api, visit_tpl | 895 | — |
| `GET /api/settings/sms` | JSON | 6 | doctor_rights, notices, plan_tpl, recall, sms | 564 | — |
| `POST /api/settings/sms` | JSON | 17 | doctor_rights, notices, plan_tpl, recall, sms | 564 | — |
| `POST /api/settings/sms/order` | JSON | 21 | sms | 189 | — |
| `POST /api/settings/sms/refresh` | JSON | 11 | doctor_rights, notices, recall, sms | 508 | — |
| `POST /api/settings/sms/sender` | JSON | 12 | sms | 189 | — |
| `POST /api/settings/sms/test` | JSON | 13 | sms | 189 | — |
| `GET /api/settings/system` | JSON | 4 | admin, backup, demo, notices, plan_tpl, privileged, settings_api | 1048 | — |
| `POST /api/settings/system/check` | JSON | 14 | notices, settings_api | 367 | — |
| `POST /api/settings/system/uninstall-sync` | JSON | 21 | privileged | 112 | — |
| `GET /api/settings/templates` | JSON | 4 | plan_tpl, visit_tpl | 97 | — |
| `POST /api/settings/templates` | JSON | 28 | plan_tpl, visit_tpl | 97 | — |
| `GET /api/settings/theme` | JSON | 4 | admin, plan_tpl, settings_api, theme | 795 | — |
| `POST /api/settings/theme` | JSON | 24 | admin, plan_tpl, settings_api, theme | 795 | — |
| `POST /api/settings/theme/logo` | JSON | 9 | backup, plan_tpl, privacy, settings_api, theme | 725 | — |
| `POST /api/settings/theme/logo/delete` | JSON | 7 | plan_tpl, settings_api, theme | 466 | — |
| `GET /api/settings/theme/palette` | JSON | 10 | settings_api, theme | 410 | — |
| `POST /api/settings/users` | JSON | 18 | api, backup, cont_link, demo, desk, doctor_rights, doctors, gcal, lab, lab_pages, license_email, license_renew, migrate, patient_card, patients_api, paylink, pimport, pin, plan_tpl, recall, registre, review2, review3_auth, settings_api, sms, stats_api, stock, stock_tc, visit_api, visit_tpl | 3073 | — |
| `POST /api/settings/users/{uid}/delete` | JSON | 9 | activity, admin, doctors, hardening, lab, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, plan_tpl, registre, settings_api, stock, teeth, theme | 2580 | — |
| `GET /shell/notices` | JSON | 8 | launcher, notices | 186 | — |

## Врачи — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doctor-card/{dk}` | HTML | 11 | doctors, pin | 341 | doctor_card |
| `GET /admin/doctor-photo/{dk}` | FILE | 9 | doctors | 114 | — |
| `GET /admin/medici` | HTML | 10 | admin, demo, doctors, pin, settings_api | 1013 | doctors_list |
| `POST /admin/relink` | 303 | 12 | admin_canvas, doctors, license_page | 254 | — |
| `GET /api/doctors` | JSON | 9 | admin, admin_canvas, doctors, plan_tpl, rooms | 750 | — |
| `POST /api/doctors` | JSON | 10 | admin, admin_canvas, doctors, plan_tpl, rooms | 750 | — |
| `POST /api/doctors/colors` | JSON | 4 | doctors, plan_tpl | 170 | — |
| `GET /api/doctors/{dk}` | JSON | 6 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, plan_tpl, review3, rooms | 1185 | — |
| `POST /api/doctors/{dk}` | JSON | 29 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, plan_tpl, review3, rooms | 1185 | — |
| `POST /api/doctors/{dk}/parallel` | JSON | 15 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, plan_tpl, review3, rooms | 1185 | — |
| `POST /api/doctors/{dk}/photo` | JSON | 8 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, plan_tpl, review3, rooms | 1185 | — |
| `POST /api/doctors/{dk}/photo/delete` | JSON | 7 | admin, admin_canvas, day_actions, day_forms, doctors, perio_api, pin, plan_tpl, review3, rooms | 1185 | — |
| `POST /api/doctors/{dk}/services` | JSON | 11 | admin, admin_canvas, day_actions, day_forms, demo, doctors, perio_api, pin, plan_tpl, recall, review2, review3, rooms, settings_api, visit_tpl | 1752 | — |

## Статистика — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/casa` | HTML | 13 | admin, desk, pin, stats_api, theme | 800 | — |
| `GET /admin/stats` | HTML | 18 | admin, anamneza, demo, patients_api, pin, review3, stats_api | 892 | stats |
| `GET /api/stats` | JSON | 22 | admin, backup, demo, hardening, orders, pimport, pin, rooms, schedule_api, stats_api | 1493 | — |

## QR — группа 1


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /qr` | other | 5 | admin, settings_api | 615 | — |

## Пациенты — группа 2


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/doc/{doc_id}` | FILE | 25 | backup, hardening, patient_card, privacy, scan, sign | 585 | — |
| `GET /admin/patient/{pid}` | HTML | 17 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | patient_card |
| `GET /admin/patient/{pid}/acord` | HTML | 16 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | — |
| `GET /admin/patient/{pid}/anamneza/print` | HTML | 14 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | — |
| `GET /admin/patient/{pid}/export` | FILE | 27 | activity, admin, anamneza, backup, dbcrypt, demo, guards, lab, license_existing, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pin, plan_acord, privacy, recall, review2, rooms, settings_api, sign, sms, stock, teeth, visit, visit_api | 3489 | — |
| `GET /admin/patient/{pid}/fisa043` | HTML | 30 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | — |
| `GET /admin/patient/{pid}/odontograma` | HTML | 24 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | odontogram |
| `GET /admin/patient/{pid}/parodontograma` | HTML | 24 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | perio |
| `GET /admin/patient/{pid}/parodontograma/print` | HTML | 19 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | — |
| `GET /admin/patient/{pid}/plan-acord` | HTML | 25 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | — |
| `GET /admin/patient/{pid}/sign/{key}` | HTML | 15 | activity, anamneza, demo, guards, lab, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, plan_acord, privacy, recall, review2, rooms, sign, sms, stock, teeth, visit, visit_api | 2420 | — |
| `GET /admin/patients.xlsx` | FILE | 53 | admin, patients_api, pimport, pin | 797 | — |
| `GET /admin/patients/import` | HTML | 6 | pimport | 184 | patients_import |
| `GET /admin/search` | HTML | 23 | admin, anamneza, demo, patient_card, patients_api, pimport, pin | 1143 | patients_search |
| `GET /admin/visit/{appt_id}` | HTML | 19 | patient_card, visit, visit_api | 281 | visit |
| `POST /api/documents/{doc_id}/open` | JSON | 8 | hardening, license_gate, patient_card, stock | 398 | — |
| `GET /api/patients` | JSON | 32 | admin, anamneza, backup, booking, dbcrypt, demo, license_email, license_existing, license_gate, license_page, license_renew, license_terms, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pimport, pin, plan_acord, privacy, react_default, review2, scan, sign, stats_api, teeth | 2620 | — |
| `POST /api/patients` | JSON | 20 | admin, anamneza, backup, booking, dbcrypt, demo, license_email, license_existing, license_gate, license_page, license_renew, license_terms, odontogram_api, patient_card, patients_api, paylink, perio, perio_api, pimport, pin, plan_acord, privacy, react_default, review2, scan, sign, stats_api, teeth | 2620 | — |
| `GET /api/patients/summary` | JSON | 34 | admin, patients_api | 386 | — |
| `GET /api/patients/{pid}` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/patients/{pid}/activity` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/alerts` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/alerts/{aid}/delete` | JSON | 7 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, plan_tpl, privacy, react_default, recall, registre, review2, rooms, scan, schedule_api, settings_api, sign, sms, stats_api, stock, stock_tc, teeth, theme, visit, visit_api, visit_tpl | 4923 | — |
| `POST /api/patients/{pid}/anamneza` | JSON | 12 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/appoint` | JSON | 17 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/archive` | JSON | 11 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/bridges` | JSON | 16 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/bridges/{bid}/delete` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, plan_tpl, privacy, react_default, recall, registre, review2, rooms, scan, schedule_api, settings_api, sign, sms, stats_api, stock, stock_tc, teeth, theme, visit, visit_api, visit_tpl | 4923 | — |
| `POST /api/patients/{pid}/doctor` | JSON | 13 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/documents` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/documents/{doc_id}/delete` | JSON | 7 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, plan_tpl, privacy, react_default, recall, registre, review2, rooms, scan, schedule_api, settings_api, sign, sms, stats_api, stock, stock_tc, teeth, theme, visit, visit_api, visit_tpl | 4923 | — |
| `POST /api/patients/{pid}/erase` | JSON | 13 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/forms/{key}/sign` | JSON | 43 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/mkt` | JSON | 16 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/ocluzie` | JSON | 20 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/patients/{pid}/odontogram` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/patients/{pid}/odontogram/compare` | JSON | 33 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/odontogram/preview` | JSON | 19 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/payments` | JSON | 11 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/payments/{pay_id}/delete` | JSON | 8 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, plan_tpl, privacy, react_default, recall, registre, review2, rooms, scan, schedule_api, settings_api, sign, sms, stats_api, stock, stock_tc, teeth, theme, visit, visit_api, visit_tpl | 4923 | — |
| `GET /api/patients/{pid}/peek` | JSON | 8 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/patients/{pid}/perio` | JSON | 10 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/perio/exams` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/perio/{eid}` | JSON | 33 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/perio/{eid}/delete` | JSON | 14 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, plan_tpl, privacy, react_default, recall, registre, review2, rooms, scan, schedule_api, settings_api, sign, sms, stats_api, stock, stock_tc, teeth, theme, visit, visit_api, visit_tpl | 4923 | — |
| `POST /api/patients/{pid}/plan` | JSON | 23 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/plan/from-template` | JSON | 19 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/plan/save-template` | JSON | 13 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/patients/{pid}/plan/templates` | JSON | 15 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/plan/{item_id}/delete` | JSON | 7 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, plan_tpl, privacy, react_default, recall, registre, review2, rooms, scan, schedule_api, settings_api, sign, sms, stats_api, stock, stock_tc, teeth, theme, visit, visit_api, visit_tpl | 4923 | — |
| `POST /api/patients/{pid}/plan/{item_id}/edit` | JSON | 12 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/plan/{item_id}/status` | JSON | 12 | activity, admin, admin_canvas, anamneza, backup, booking, chair, day_actions, day_forms, demo, desk, doctor_rights, doctors, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, panel_model, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4526 | — |
| `POST /api/patients/{pid}/profile` | JSON | 11 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/scan/cancel` | JSON | 5 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/scan/finish` | JSON | 25 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/scan/page` | JSON | 15 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/patients/{pid}/slots` | JSON | 9 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, structure, teeth, visit, visit_api, visit_tpl | 4302 | — |
| `POST /api/patients/{pid}/sms-off` | JSON | 15 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/teeth` | JSON | 25 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `POST /api/patients/{pid}/teeth/{tooth}` | JSON | 26 | activity, admin, anamneza, backup, booking, day_actions, day_forms, demo, desk, doctor_rights, gcal, hardening, lab, license_existing, license_gate, migrate, mkt, ocluzie, odontogram_api, patient_card, patients_api, perio, perio_api, pimport, pin, plan_acord, plan_insert, privacy, react_default, recall, review2, rooms, scan, schedule_api, sign, sms, stats_api, stock, stock_tc, teeth, visit, visit_api, visit_tpl | 4224 | — |
| `GET /api/pimport` | JSON | 11 | pimport | 184 | — |
| `POST /api/pimport/check` | JSON | 35 | pimport | 184 | — |
| `GET /api/pimport/model.xlsx` | FILE | 10 | pimport | 184 | — |
| `POST /api/pimport/report` | FILE | 17 | pimport | 184 | — |
| `POST /api/pimport/run` | JSON | 56 | pimport | 184 | — |
| `POST /api/pimport/undo` | JSON | 31 | pimport | 184 | — |
| `GET /api/scan/status` | JSON | 6 | scan | 25 | — |
| `GET /api/visits/{aid}` | JSON | 9 | chair, day_forms, patient_card, plan_acord, schedule_api, stock_tc, visit, visit_api, visit_tpl | 718 | — |
| `POST /api/visits/{aid}` | JSON | 23 | chair, day_forms, patient_card, plan_acord, schedule_api, stock_tc, visit, visit_api, visit_tpl | 718 | — |
| `GET /api/visits/{aid}/template` | JSON | 16 | chair, day_forms, patient_card, plan_acord, schedule_api, stock_tc, visit, visit_api, visit_tpl | 718 | — |

## Журнал — группа 5


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin` | HTML | 28 | admin, admin_canvas, api, backup, cont_link, dbcrypt, demo, desk, doctor_rights, doctors, gcal, hardening, lab, lab_pages, license_email, license_existing, license_gate, license_page, license_renew, license_terms, migrate, notices, orders, patient_card, patients_api, paylink, pimport, pin, plan_tpl, react_default, recall, registre, review3_auth, schedule_api, settings_api, sms, split, stats_api, stock, stock_tc, structure, theme, update_server, visit_api, visit_tpl | 4373 | schedule_dash |
| `GET /admin/all` | HTML | 17 | admin, admin_canvas, demo, doctor_rights, doctors, gcal, pin, schedule_api, stats_api, visit_api | 1356 | schedule_all |
| `GET /admin/cabinet` | HTML | 10 | chair, doctor_rights | 123 | chair |
| `GET /admin/doctor/{dk}` | HTML | 16 | admin, doctor_rights, pin, schedule_api | 819 | schedule_doctor |
| `GET /admin/export.xlsx` | FILE | 45 | admin, doctor_rights, pin, rooms | 787 | — |
| `GET /admin/google` | HTML | 4 | gcal | 151 | gcal |
| `GET /admin/week` | HTML | 13 | admin, demo, schedule_api | 577 | schedule_week |
| `GET /api/chair` | JSON | 36 | admin, chair, doctor_rights, rooms | 611 | — |
| `GET /api/gcal` | JSON | 6 | gcal, migrate | 381 | — |
| `POST /api/gcal/clear` | JSON | 5 | gcal | 151 | — |
| `POST /api/gcal/events/{eid}/link` | JSON | 9 | gcal, rooms | 310 | — |
| `POST /api/gcal/events/{eid}/move` | JSON | 14 | booking, day_actions, day_forms, doctor_rights, doctor_windows, gcal, rooms, sms | 789 | — |
| `POST /api/gcal/events/{eid}/skip` | JSON | 9 | gcal, rooms, stock_tc | 355 | — |
| `POST /api/gcal/file` | JSON | 20 | gcal | 151 | — |
| `POST /api/gcal/source` | JSON | 11 | gcal | 151 | — |
| `POST /api/schedule/appointments` | JSON | 42 | activity, admin, admin_canvas, chair, day_actions, day_forms, desk, doctor_windows, doctors, hardening, patient_card, patients_api, plan_acord, privacy, react_default, schedule_api, stats_api, visit, visit_api, visit_tpl | 1676 | — |
| `POST /api/schedule/appointments/{appt_id}/comment` | JSON | 18 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, rooms, schedule_api, sms, stats_api, structure, visit, visit_api | 2418 | — |
| `POST /api/schedule/appointments/{appt_id}/duration` | JSON | 19 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, rooms, schedule_api, sms, stats_api, structure, visit, visit_api | 2418 | — |
| `POST /api/schedule/appointments/{appt_id}/move` | JSON | 23 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, gcal, odontogram_api, panel_model, patient_card, privacy, recall, rooms, schedule_api, sms, stats_api, structure, visit, visit_api | 2569 | — |
| `POST /api/schedule/appointments/{appt_id}/room` | JSON | 14 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, rooms, schedule_api, sms, stats_api, structure, visit, visit_api | 2418 | — |
| `GET /api/schedule/appointments/{appt_id}/service` | JSON | 23 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, rooms, schedule_api, sms, stats_api, structure, visit, visit_api | 2418 | — |
| `POST /api/schedule/appointments/{appt_id}/service` | JSON | 20 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, privacy, recall, rooms, schedule_api, sms, stats_api, structure, visit, visit_api | 2418 | — |
| `POST /api/schedule/appointments/{appt_id}/status` | JSON | 20 | activity, admin, admin_canvas, booking, chair, day_actions, day_forms, desk, doctor_rights, doctor_windows, doctors, odontogram_api, panel_model, patient_card, patients_api, plan_acord, plan_insert, privacy, recall, review2, rooms, scan, schedule_api, sms, stats_api, stock_tc, structure, visit, visit_api, visit_tpl | 2712 | — |
| `GET /api/schedule/canvas` | JSON | 13 | admin_canvas, doctor_rights, harness_clock, schedule_api | 369 | — |
| `GET /api/schedule/day` | JSON | 23 | admin, day_actions, desk, doctor_rights, pin, recall, rooms, schedule_api | 1225 | — |
| `POST /api/schedule/desk/call/{aid}` | JSON | 27 | admin_canvas, desk, doctor_rights, privacy, structure | 409 | — |
| `GET /api/schedule/live` | JSON | 34 | admin, demo, desk, doctor_rights, lab, recall, rooms, schedule_api | 1161 | — |
| `POST /api/schedule/notes` | JSON | 21 | admin, admin_canvas, booking, chair, day_actions, day_forms, doctor_rights, rooms, schedule_api | 1084 | — |
| `POST /api/schedule/sms-of` | JSON | 16 | pimport, sms | 373 | — |
| `GET /api/schedule/week` | JSON | 14 | admin, doctor_rights, schedule_api | 592 | — |

## Точка входа — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/license` | HTML | 9 | cont_link, demo, license_email, license_existing, license_page, license_renew, license_terms, notices, paylink | 468 | — |
| `POST /admin/license` | 303 | 22 | cont_link, demo, license_email, license_existing, license_page, license_renew, license_terms, notices, paylink | 468 | — |
| `POST /admin/license/email/change` | other | 4 | license_email | 39 | — |
| `POST /admin/license/email/code` | other | 4 | license_email | 39 | — |
| `POST /admin/license/email/confirm` | other | 3 | license_email | 39 | — |
| `POST /admin/license/email/later` | 303 | 7 | license_email | 39 | — |
| `POST /admin/license/renew` | 303 | 10 | license_email, license_renew, license_terms, paylink | 240 | — |
| `POST /admin/license/request` | 303 | 19 | license_page, license_renew, license_terms | 211 | — |
| `POST /admin/license/terms` | 303 | 13 | license_terms | 46 | — |
| `POST /admin/license/verify` | 303 | 12 | license_renew | 117 | — |
| `GET /admin/login` | HTML | 42 | admin, api, backup, chair, cont_link, demo, desk, doctor_rights, doctors, gcal, hardening, lab, lab_pages, license_email, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pimport, pin, plan_tpl, recall, registre, review3_auth, settings_api, sms, stats_api, stock, stock_tc, theme, visit_api, visit_tpl | 3756 | — |
| `POST /admin/login` | 303 | 27 | admin, api, backup, chair, cont_link, demo, desk, doctor_rights, doctors, gcal, hardening, lab, lab_pages, license_email, license_gate, license_page, license_renew, migrate, netcheck, patient_card, patients_api, paylink, pimport, pin, plan_tpl, recall, registre, review3_auth, settings_api, sms, stats_api, stock, stock_tc, theme, visit_api, visit_tpl | 3756 | — |
| `GET /admin/logout` | 303 | 8 | demo, pin | 284 | — |
| `GET /admin/recover` | HTML | 14 | dbcrypt, hardening | 149 | — |
| `POST /admin/recover` | HTML | 22 | dbcrypt, hardening | 149 | — |
| `POST /admin/security/ack` | 303 | 8 | orders, pin | 289 | — |
| `GET /admin/setup` | HTML | 16 | api, backup, desk, doctor_rights, doctors, gcal, hardening, lab, lab_pages, migrate, patient_card, patients_api, pimport, pin, plan_tpl, recall, registre, review2, review3_auth, settings_api, sms, stats_api, stock, stock_tc, visit_api, visit_tpl | 2875 | — |
| `POST /admin/setup` | HTML | 29 | api, backup, desk, doctor_rights, doctors, gcal, hardening, lab, lab_pages, migrate, patient_card, patients_api, pimport, pin, plan_tpl, recall, registre, review2, review3_auth, settings_api, sms, stats_api, stock, stock_tc, visit_api, visit_tpl | 2875 | — |
| `POST /admin/setup/ask` | 303 | 13 | pin | 227 | — |
| `POST /api/auth/login` | JSON | 36 | hardening, license_gate, pin, structure | 399 | — |
| `POST /api/auth/logout` | JSON | 11 | license_gate, pin | 249 | — |
| `GET /api/license` | JSON | 6 | demo, license_existing, license_page, license_renew | 245 | — |
| `POST /api/license/terms` | JSON | 11 | license_terms | 46 | — |
| `GET /clinic-logo` | other | 20 | settings_api, theme | 410 | — |
| `GET /cont/{ticket}` | HTML | 14 | cont_link | 19 | — |
| `GET /favicon.ico` | other | 5 | admin, demo | 386 | — |
| `GET /health` | other | 4 | admin, demo, guards, hardening, harness_client, harness_ports, license_renew, netcheck, pin | 959 | — |
| `GET /icon-{px}.png` | other | 11 | admin, demo | 386 | — |
| `GET /manifest.webmanifest` | other | 31 | admin, demo | 386 | — |
| `GET /plata/{ticket}` | HTML | 16 | cont_link, paylink, sms | 246 | — |
| `GET /static/{kind}/{name}` | other | 37 | admin, api, demo, doctors, odontogram_api, patient_card, patients_api, perio_api, schedule_api, settings_api, split, structure, theme, visit_api | 1820 | — |

## Прочее — не мигрирует


⛔ Аварийные и служебные маршруты: остаются серверными (§27).


| Маршрут | Тип | стр | Наборы | Проверок | Экран React |
|---|---|---|---|---|---|
| `GET /admin/lab` | HTML | 5 | demo, lab, lab_pages | 219 | lab |
| `GET /admin/lab/{oid}/tipar` | HTML | 9 | lab, stock | 274 | — |
| `GET /admin/migration` | HTML | 43 | guards, split | 123 | — |
| `POST /admin/migration/confirm` | 303 | 32 | split | 45 | — |
| `GET /admin/rechemari` | HTML | 5 | recall | 166 | recall |
| `GET /admin/registre` | HTML | 5 | demo, registre | 176 | registre |
| `GET /admin/registre/excel/{form}` | FILE | 11 | registre | 119 | — |
| `GET /admin/registre/tipar/{form}` | HTML | 20 | registre | 119 | — |
| `GET /admin/settings/lab` | HTML | 4 | lab_pages | 10 | settings_lab |
| `GET /admin/settings/registre` | HTML | 4 | registre, settings_api | 405 | settings_registre |
| `GET /admin/settings/stoc` | HTML | 4 | settings_api | 286 | settings_stock |
| `GET /admin/stoc` | HTML | 4 | demo | 57 | stock |
| `GET /admin/stoc/cumparat/tipar` | HTML | 5 | stock | 122 | — |
| `GET /admin/stoc/miscari.xlsx` | FILE | 11 | stock | 122 | — |
| `GET /api/lab` | other | 4 | demo, lab | 209 | — |
| `GET /api/lab/due` | JSON | 12 | lab | 152 | — |
| `GET /api/lab/form` | other | 4 | lab | 152 | — |
| `POST /api/lab/order` | JSON | 8 | lab | 152 | — |
| `GET /api/lab/order/{oid}` | other | 4 | lab | 152 | — |
| `POST /api/lab/order/{oid}` | other | 4 | lab | 152 | — |
| `POST /api/lab/order/{oid}/cancel` | other | 4 | backup, lab, scan, stock | 426 | — |
| `POST /api/lab/order/{oid}/etapa` | other | 4 | lab | 152 | — |
| `POST /api/lab/order/{oid}/refacere` | other | 4 | lab | 152 | — |
| `POST /api/lab/order/{oid}/step` | other | 4 | lab | 152 | — |
| `POST /api/lab/order/{oid}/undo` | other | 4 | lab, pimport, stock, stock_tc | 503 | — |
| `GET /api/lab/patient/{pid}` | other | 4 | lab | 152 | — |
| `GET /api/recall` | JSON | 21 | demo, migrate, recall | 453 | — |
| `POST /api/recall/mark` | JSON | 32 | recall | 166 | — |
| `POST /api/recall/sms` | JSON | 32 | recall | 166 | — |
| `GET /api/registre` | JSON | 5 | demo, migrate, registre | 406 | — |
| `POST /api/registre/257` | other | 4 | registre | 119 | — |
| `POST /api/registre/257/{row_id}/bio` | other | 4 | registre | 119 | — |
| `POST /api/registre/257/{row_id}/finish` | other | 5 | registre, scan | 144 | — |
| `POST /api/registre/501` | other | 4 | registre | 119 | — |
| `POST /api/registre/501/{row_id}/off` | other | 4 | registre, settings_api | 405 | — |
| `POST /api/registre/502` | other | 4 | migrate, registre | 349 | — |
| `POST /api/registre/502/{row_id}/sup` | other | 4 | registre | 119 | — |
| `POST /api/registre/{form}/{row_id}/delete` | JSON | 11 | activity, admin, doctors, hardening, lab, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, plan_tpl, registre, settings_api, stock, teeth, theme | 2580 | — |
| `POST /api/registre/{form}/{row_id}/fix` | other | 4 | migrate, registre | 349 | — |
| `GET /api/settings/lab` | other | 4 | lab | 152 | — |
| `POST /api/settings/lab/item` | JSON | 8 | lab | 152 | — |
| `POST /api/settings/lab/item/{lab_id}/delete` | JSON | 8 | activity, admin, doctors, hardening, lab, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, plan_tpl, registre, settings_api, stock, teeth, theme | 2580 | — |
| `POST /api/settings/lab/prefs` | other | 4 | lab | 152 | — |
| `GET /api/settings/registre` | JSON | 4 | registre | 119 | — |
| `POST /api/settings/registre/item` | JSON | 21 | migrate, registre | 349 | — |
| `POST /api/settings/registre/lamp/{lamp_id}/new` | other | 4 | registre | 119 | — |
| `GET /api/stock` | other | 4 | demo, stock, stock_tc | 224 | — |
| `GET /api/stock/buy` | other | 4 | stock | 122 | — |
| `POST /api/stock/doc` | JSON | 8 | stock, stock_tc | 167 | — |
| `GET /api/stock/doc/{doc_id}` | other | 4 | stock, stock_tc | 167 | — |
| `POST /api/stock/doc/{doc_id}` | other | 4 | stock, stock_tc | 167 | — |
| `POST /api/stock/doc/{doc_id}/close` | JSON | 8 | stock, stock_tc | 167 | — |
| `POST /api/stock/doc/{doc_id}/delete` | other | 4 | activity, admin, doctors, hardening, lab, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, plan_tpl, registre, settings_api, stock, stock_tc, teeth, theme | 2625 | — |
| `POST /api/stock/doc/{doc_id}/storno` | other | 6 | stock, stock_tc | 167 | — |
| `POST /api/stock/doc/{doc_id}/sums` | other | 6 | stock, stock_tc | 167 | — |
| `GET /api/stock/docs` | other | 4 | stock | 122 | — |
| `GET /api/stock/import` | JSON | 8 | stock | 122 | — |
| `POST /api/stock/import/check` | JSON | 26 | stock | 122 | — |
| `POST /api/stock/import/run` | JSON | 18 | stock | 122 | — |
| `POST /api/stock/import/{doc_id}/undo` | other | 6 | lab, pimport, stock, stock_tc | 503 | — |
| `POST /api/stock/item` | JSON | 8 | plan_insert, stock, stock_tc | 223 | — |
| `GET /api/stock/item/{item_id}` | other | 4 | stock | 122 | — |
| `POST /api/stock/item/{item_id}/delete` | other | 4 | activity, admin, doctors, hardening, lab, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, plan_tpl, registre, settings_api, stock, teeth, theme | 2580 | — |
| `POST /api/stock/move/{mid}/undo` | other | 4 | lab, pimport, stock, stock_tc | 503 | — |
| `GET /api/stock/moves` | other | 4 | stock | 122 | — |
| `POST /api/stock/open` | other | 4 | stock | 122 | — |
| `POST /api/stock/order` | other | 4 | stock | 122 | — |
| `POST /api/stock/order/{item_id}/cancel` | other | 4 | backup, lab, scan, stock | 426 | — |
| `POST /api/stock/out` | other | 4 | stock, stock_tc | 167 | — |
| `GET /api/stock/patient/{pid}` | other | 5 | stock | 122 | — |
| `GET /api/stock/plan-pending` | other | 4 | stock_tc | 45 | — |
| `GET /api/stock/plan/{plan_item_id}` | other | 4 | plan_insert, stock_tc | 101 | — |
| `POST /api/stock/plan/{plan_item_id}/consume` | other | 4 | plan_insert, stock_tc | 101 | — |
| `POST /api/stock/plan/{plan_item_id}/skip` | other | 4 | gcal, plan_insert, stock_tc | 252 | — |
| `POST /api/stock/plan/{plan_item_id}/undo` | JSON | 8 | lab, pimport, plan_insert, stock, stock_tc | 559 | — |
| `POST /api/stock/prefs` | other | 4 | stock, stock_tc | 167 | — |
| `GET /api/stock/report` | other | 4 | stock_tc | 45 | — |
| `POST /api/stock/supplier` | JSON | 8 | stock | 122 | — |
| `POST /api/stock/supplier/{sid}/delete` | other | 4 | activity, admin, doctors, hardening, lab, license_gate, migrate, odontogram_api, patient_card, perio, perio_api, pin, plan_acord, plan_tpl, registre, settings_api, stock, teeth, theme | 2580 | — |
| `GET /api/stock/tehcard` | other | 4 | stock_tc | 45 | — |
| `POST /api/stock/tehcard/replace` | other | 4 | stock_tc | 45 | — |
| `POST /api/stock/tehcard/{service_id}` | other | 4 | plan_insert, stock_tc | 101 | — |

## Колонки-состояния


`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности; старой страницы у неё нет (сняты по разделам 12–13.10, `legacy-removal.md`; ключ `ui.react` и `?ui=legacy` сняты там же). `—` значит «страница серверная по замыслу» — печать и аварийные экраны.


## Самые тяжёлые обработчики


| стр | Маршрут | Наборов |
|---|---|---|
| 64 | `GET /admin/settings/crypt/sheet` | 3 |
| 56 | `POST /api/pimport/run` | 1 |
| 53 | `GET /admin/patients.xlsx` | 4 |
| 47 | `POST /api/settings/backup/auto` | 3 |
| 45 | `GET /admin/export.xlsx` | 4 |
| 44 | `POST /api/settings/backup/restore/stage` | 2 |
| 43 | `GET /admin/migration` | 2 |
| 43 | `POST /api/patients/{pid}/forms/{key}/sign` | 43 |
| 42 | `GET /admin/login` | 36 |
| 42 | `POST /api/schedule/appointments` | 20 |
