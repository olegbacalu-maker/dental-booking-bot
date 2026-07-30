# 🦷 Dental Booking Bot — config-driven clinic booking demo

A self-hosted appointment system for small dental clinics (built with the Moldovan market
in mind): a **messenger-style booking chat** for patients (Romanian + Russian) and a
**reception journal** for the clinic — both running on one Postgres, so there is nothing
to synchronize: bot bookings appear in the journal instantly, and manual entries instantly
block the slot in the bot.

> Demo project with synthetic data. One `clinic.json` = one clinic; the same Docker image
> serves any number of clinics.

## Screenshots

**Patient books from a phone** — opened via the QR page / a link in the clinic's Instagram bio:

<img src="screenshots/patient-chat-mobile.png" width="300" alt="Patient chat on a phone">

**Clinic journal — full day, every source in one grid** (🤖 bot · ✍️ reception · 📝 note blocking a slot · 🆘 urgent highlighted):

![Journal grid](screenshots/admin-grid.png)

**Dashboard** — day tiles and per-doctor cards with urgent badges and "free from":

![Dashboard](screenshots/admin-dashboard.png)

**Click "+" on any free slot** — book a patient or leave a note that blocks the slot for the bot too:

<img src="screenshots/slot-modal.png" width="430" alt="Slot modal">

**Per-doctor day view** and the **live-demo QR page** (temporary Cloudflare tunnel):

![Doctor day](screenshots/doctor-day.png)

<img src="screenshots/demo-qr.png" width="560" alt="QR demo page">

## Patient side (web chat, RO/RU)

- Full booking dialog: service → doctor (or *any available*) → day → time → name/phone → confirm.
- **Service→doctor mapping**: extractions go to the surgeon, cleanings to the hygienist;
  if only one doctor performs a service, the bot skips the question entirely.
- **🆘 Acute pain flow**: no doctor/day questions — the nearest free slots *including today*,
  with the clinic phone always visible. All retry paths return to the nearest-slots view.
- "My appointments" with cancellation (ownership enforced), price list, contacts,
  reminder preview (scheduled reminders are on the roadmap).
- Race-safe: double-booking is impossible (partial unique indexes on doctor/slot and
  patient/slot); the "any doctor" flow retries the remaining doctors before giving up;
  stale same-day slots are re-checked at confirmation time.

## Clinic side (`/admin`)

Three levels:

1. **Dashboard** — day tiles (total / via bot 🤖 / by reception ✍️ / 🆘 urgent / no-shows)
   and one card per doctor: specialty, load, urgent badge, "free from HH:MM".
2. **Doctor day view** — single-column schedule, add-form locked to that doctor.
3. **Full grid** — all doctors side by side.

Clicking **"+"** on any free slot opens a modal: *book a patient* or *leave a note /
block the slot* ("lunch break", "seminar") — notes visibly block the slot for the bot too.
Statuses per visit (came / no-show / cancelled) accumulate the clinic's real no-show stats.

## One file = one clinic

Everything clinic-specific lives in [`clinic.json`](clinic.json): name, phone, address,
contacts, **working hours per weekday** (incl. days off), doctors with specialties,
services with prices and allowed doctors, demo-seed flag. The engine loads it at startup
(`CLINIC_CONFIG` env, mounted read-only in compose). Editing data = `docker compose restart bot`,
no rebuild.

A second clinic = a folder with its own `clinic.json` + a compose file pointing at the
same image — see [`examples/clinic-zambet/`](examples/clinic-zambet/): different doctors,
services, prices and a Saturday off, zero code changes.

## Quick start

```bash
docker compose up -d --build
# patient chat:   http://localhost:8088
# clinic journal: http://localhost:8088/admin
```

Reset to a fresh demo dataset: `docker compose down -v && docker compose up -d`.
DB credentials in compose are demo-only; Postgres is bound to loopback.

`Start-Demo.ps1` / `Start_Demo.bat` are Windows helpers used for live demos:
they start the stack, open a temporary Cloudflare quick tunnel and a QR page (`/demo`)
so a clinic owner can scan and book from their own phone.

## Stack & design notes

- FastAPI + asyncpg + PostgreSQL 16, single `docker compose`, ~256 MB per container.
- The dialog engine is channel-agnostic (`engine.handle()`): the web chat is one adapter,
  a Telegram adapter is the next one.
- The admin journal and the bot share one database by design — "integration" is a query,
  not a sync job.
- Reviewed adversarially (multi-agent code review); found issues (mid-flow text ejection,
  any-doctor race, DB exposed beyond loopback, stale-slot TOCTOU) are fixed and covered
  by regression scripts.

## Roadmap

- Scheduled reminders (the −20–25% no-show lever) + Telegram adapter.
- Auth on `/admin`, backups, multi-tenant single instance.
- Google Calendar per doctor (push first, free/busy second).

## Pe scurt / Кратко

Sistem de programări pentru clinici stomatologice: chat de programare pentru pacienți
(RO/RU) + registru pentru recepție, o singură bază de date. O clinică nouă = un singur
fișier `clinic.json`. / Система записи для стоматологий: чат записи для пациентов (RO/RU)
+ журнал для ресепшена, одна база данных. Новая клиника = один файл `clinic.json`.

## License

MIT © Oleg Bacalu
