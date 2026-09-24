# Карта маршрутов B2

Адрес FastAPI → маршрут React → экран → параметры узла → загрузчик.


⚠️ Файл **производный**: правится не он, а `scripts/screen_map.py`
(словари `FLAG` и `B2` лежат там рядом). Пересобрать —
`python scripts/screen_map.py`.


⛔ Колонка «маршрут React» ВЫЧИСЛЯЕТСЯ из адреса сервера, а не
набирается: новых адресов вроде `/dashboard` или `/pacienti` на сервере
нет, и перезагрузка такой страницы дала бы 404. Бэкенд не переписывается
ради роутера.


Поверхностей **23**.


| адрес FastAPI | маршрут React | экран | параметры узла | загрузчик |
|---|---|---|---|---|
| `/admin` | `/admin` | `schedule_dash` | date, day_label | GET /api/schedule/live |
| `/admin/all` | `/admin/all` | `schedule_all` | date, f? | GET /api/schedule/day |
| `/admin/medici` | `/admin/medici` | `doctors_list` | — | GET /api/doctors |
| `/admin/search` | `/admin/search` | `patients_search` | q?, med?, st?, ch?, dat?, sort?, page?, per? | GET /api/patients/summary + GET /api/patients |
| `/admin/settings` | `/admin/settings` | `settings_hub` | — | GET /api/settings/hub |
| `/admin/stats` | `/admin/stats` | `stats` | from, to | GET /api/stats |
| `/admin/week` | `/admin/week` | `schedule_week` | date | GET /api/schedule/week |
| `/admin/doctor-card/{dk}` | `/admin/doctor-card/:dk` | `doctor_card` | dk | GET /api/doctors/{dk} |
| `/admin/doctor/{dk}` | `/admin/doctor/:dk` | `schedule_doctor` | date, dk | GET /api/schedule/day |
| `/admin/patient/{pid}` | `/admin/patient/:pid` | `patient_card` | pid, views? | GET /api/patients/{pid} |
| `/admin/settings/backup` | `/admin/settings/backup` | `settings_backup` | — | GET /api/settings/backup |
| `/admin/settings/clinic` | `/admin/settings/clinic` | `settings_clinic` | — | GET /api/settings/clinic |
| `/admin/settings/crypt` | `/admin/settings/crypt` | `settings_crypt` | — | GET /api/settings/crypt |
| `/admin/settings/faq` | `/admin/settings/faq` | `settings_faq` | — | GET /api/settings/faq |
| `/admin/settings/hours` | `/admin/settings/hours` | `settings_hours` | — | GET /api/settings/hours |
| `/admin/settings/lan` | `/admin/settings/lan` | `settings_lan` | — | GET /api/settings/lan |
| `/admin/settings/security` | `/admin/settings/security` | `settings_security` | — | GET /api/settings/security |
| `/admin/settings/services` | `/admin/settings/services` | `settings_services` | — | GET /api/settings/services |
| `/admin/settings/system` | `/admin/settings/system` | `settings_system` | — | GET /api/settings/system |
| `/admin/settings/theme` | `/admin/settings/theme` | `settings_theme` | — | GET /api/settings/theme |
| `/admin/visit/{appt_id}` | `/admin/visit/:appt_id` | `visit` | aid, back | GET /api/visits/{aid} |
| `/admin/patient/{pid}/odontograma` | `/admin/patient/:pid/odontograma` | `odontogram` | pid, t? | GET /api/patients/{pid}/odontogram |
| `/admin/patient/{pid}/parodontograma` | `/admin/patient/:pid/parodontograma` | `perio` | pid, exam? | GET /api/patients/{pid}/perio |

## Что нельзя потерять при переносе

- `/admin` — живой КАНАЛ, а не разовая загрузка: 204 «не менялось», отпечаток
- `/admin/all` — экран DayScreen, общий с днём врача
- `/admin/search` — ДВА запроса разом (Promise.all) — loader обязан ждать оба
- `/admin/doctor-card/{dk}` — ⛔ НЕ путать с /admin/doctor/{dk} — это день врача в журнале
- `/admin/doctor/{dk}` — тот же DayScreen, отличается dk
- `/admin/settings/clinic` — ⚠️ единственный экран НЕ на useLoad: свой useEffect
- `/admin/visit/{appt_id}` — ⚠️ ключ узла `aid`, а параметр пути `appt_id` — имена РАЗНЫЕ

## Чего в этой карте намеренно нет

Крошка раздела (`frame.crumbs`) — она в модели ОБОЛОЧКИ, а не в
параметрах экрана, и одна на все десять страниц настроек. В
конфигурацию маршрута её тянуть незачем: она уже приезжает готовой.


Права. Страница зовёт `require(PERM_…)`, её загрузчик — `api_require`.
Свести их в одно место — это B3, и до выбора режима роутера трогать
нечего. ⚠️ Расхождение прав между страницей и её загрузчиком обязано
быть проверено ДО B3, иначе проверка переедет в загрузчик вместе с
ошибкой.


---
Связано: [spa-transition.md](spa-transition.md),
[screen-test-map.md](screen-test-map.md).
