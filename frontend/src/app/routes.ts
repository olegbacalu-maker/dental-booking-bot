// Сгенерировано scripts/screen_map.py из словаря FLAG.
// НЕ ПРАВИТЬ РУКАМИ: правится FLAG, потом `python scripts/screen_map.py`.
// Маршрут — адрес FastAPI, где `{pid}` записан как `:pid`. Новых адресов нет:
// перезагрузка на адресе, которого не знает сервер, дала бы 404.
export const ROUTES = [
  { path: "/admin", screen: "schedule_dash" },
  { path: "/admin/all", screen: "schedule_all" },
  { path: "/admin/cabinet", screen: "chair" },
  { path: "/admin/medici", screen: "doctors_list" },
  { path: "/admin/search", screen: "patients_search" },
  { path: "/admin/settings", screen: "settings_hub" },
  { path: "/admin/stats", screen: "stats" },
  { path: "/admin/week", screen: "schedule_week" },
  { path: "/admin/doctor-card/:dk", screen: "doctor_card" },
  { path: "/admin/doctor/:dk", screen: "schedule_doctor" },
  { path: "/admin/patient/:pid", screen: "patient_card" },
  { path: "/admin/settings/backup", screen: "settings_backup" },
  { path: "/admin/settings/clinic", screen: "settings_clinic" },
  { path: "/admin/settings/crypt", screen: "settings_crypt" },
  { path: "/admin/settings/faq", screen: "settings_faq" },
  { path: "/admin/settings/hours", screen: "settings_hours" },
  { path: "/admin/settings/lan", screen: "settings_lan" },
  { path: "/admin/settings/security", screen: "settings_security" },
  { path: "/admin/settings/services", screen: "settings_services" },
  { path: "/admin/settings/system", screen: "settings_system" },
  { path: "/admin/settings/theme", screen: "settings_theme" },
  { path: "/admin/visit/:appt_id", screen: "visit" },
  { path: "/admin/patient/:pid/odontograma", screen: "odontogram" },
  { path: "/admin/patient/:pid/parodontograma", screen: "perio" },
] as const

export type ScreenName = (typeof ROUTES)[number]['screen']
