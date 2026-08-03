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

**Owner stats** — no-shows priced in MDL from the clinic's own price list, value brought
by the bot, per-doctor occupancy:

![Stats](screenshots/stats.png)

**Patient search** by name or phone digits, with visit history and comments:

<img src="screenshots/patient-search.png" width="680" alt="Patient search">

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
- After the name the bot asks for the **birth year** (optional, skippable) — the doctor
  sees the age, the clinic stores privacy-minimal data (a year, not a full DOB).
- "My appointments" with cancellation (ownership enforced), price list, contacts.
- **Automatic reminders** for Telegram bookings: 24h and 2h before the visit, in the
  patient's language, with confirm/cancel buttons right in the message; sent ones are
  marked 🔔 in the journal.
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
Clicking **any appointment** (in the grid or the day list) opens its card: patient info
with age, an editable **reception comment** (allergies, call-back notes — shown as a 💬
line, never visible to patients) and came / no-show / cancel buttons.
Statuses per visit accumulate the clinic's real no-show stats.

More journal tools:

- **Doctors section** (`/admin/medici`): one card per doctor — photo (stored locally,
  never shown to patients), room, internal phone, personal working window, calendar
  colour, services performed (checkboxes) and 30-day figures. Three states instead of an
  on/off switch: *active* / *on leave* / *archived*; a doctor is never deleted (their
  appointments keep the link) and archiving is refused while future bookings exist.
- **Patient search** by name or phone digits (any format) with the full visit history.
- **Owner stats** (`/admin/stats`): bookings by source, visits, **no-shows priced in MDL**
  from the clinic's own price list, "value brought by the bot", per-doctor occupancy
  bars, top services — over any period.
- **CSV export** of a day or period (semicolon + UTF-8 BOM, opens cleanly in Excel).
- Date navigation everywhere: a native month-calendar picker plus ±7-day jumps.
- The journal is protected by a per-clinic password (`ADMIN_KEY` in `.env`, HMAC cookie);
  patient pages stay public. Empty key = open demo mode with a visible warning.

## One file = one clinic

Everything clinic-specific lives in [`clinic.json`](clinic.json): name, phone, address,
contacts, **working hours per weekday** (incl. days off), doctors with specialties and
state, services with prices and allowed doctors, demo-seed flag. The engine loads it at startup
(`CLINIC_CONFIG` env, mounted read-only in compose). Editing data = `docker compose restart bot`,
no rebuild.

A second clinic = a folder with its own `clinic.json` + a compose file pointing at the
same image — see [`examples/clinic-zambet/`](examples/clinic-zambet/): different doctors,
services, prices and a Saturday off, zero code changes.

## Two editions, one codebase

- **Cloud** (below): Docker compose with PostgreSQL — one VPS serves many clinics.
- **Desktop**: a single `DentPilot.exe` (PyInstaller, ~28 MB) for clinics that want
  everything local — native app window (WebView2), SQLite next to the exe,
  **phone-style PIN** set on first launch, Telegram bot via long polling (no ports,
  no tunnel), and **one-click self-update** from GitHub Releases (download → swap
  via a Task-Scheduler-relaunched script → restart; the clinic's data is untouched).
  Build it with `Build-Desktop.ps1`.
- **Installer**: `Build-Installer.ps1` wraps that exe into a single
  `dist\DentPilot-Setup-<version>.exe` (Inno Setup, [`installer/DentPilot.iss`](installer/DentPilot.iss)) —
  a normal Windows wizard: folder picker, desktop shortcut and autostart checkboxes,
  Start Menu entry, an uninstaller in *Apps & features*. DentPilot keeps
  `clinic.json`, `dental.env` and `data\dental.db` next to the exe, which decides
  where it may be installed: the wizard probes the chosen folder for writability
  (Program Files is rejected outright), and the default is the **shared**
  `C:\Users\Public\DentPilot` rather than a user profile — a clinic where two
  shifts log in under different Windows accounts must not end up with two separate
  databases. Demo appointments are an unchecked box, off for real clinics.
  Upgrades reuse the existing folder — the database is never touched, and uninstalling
  removes only the program, its shortcuts and the update leftovers, never the
  clinic's data.
  (`Install-DentPilot.ps1` is the older two-file USB flow, kept for reference.)
- **Releasing**: see [RELEASE.md](RELEASE.md). The self-updater and the installer
  consume different artifacts from the same release, so the release layout is
  load-bearing — `Build-Installer.ps1` and `scripts/check_release.py` enforce it.

## Quick start

```bash
docker compose up -d --build
# patient chat:   http://localhost:8088
# clinic journal: http://localhost:8088/admin
```

Reset to a fresh demo dataset: `docker compose down -v && docker compose up -d`.
DB credentials in compose are demo-only; Postgres is bound to loopback.
`Backup-Db.ps1` / `Restore-Db.ps1` dump and restore the database (`--clean`, 14-backup
retention) — the restore path is verified by a fire drill into a throwaway container.

`Start-Demo.ps1` / `Start_Demo.bat` are Windows helpers used for live demos:
they start the stack, open a temporary Cloudflare quick tunnel and a QR page (`/demo`)
so a clinic owner can scan and book from their own phone.

## Stack & design notes

- FastAPI + asyncpg + PostgreSQL 16, single `docker compose`, ~256 MB per container.
- The dialog engine is channel-agnostic (`engine.handle()`): the web chat and the
  **Telegram adapter** (aiogram, inline keyboards; enabled by setting `TELEGRAM_TOKEN`
  in `.env`) are two thin adapters over the same engine and database.
- The admin journal and the bot share one database by design — "integration" is a query,
  not a sync job.
- Reviewed adversarially (multi-agent code review); found issues (mid-flow text ejection,
  any-doctor race, DB exposed beyond loopback, stale-slot TOCTOU) are fixed and covered
  by regression scripts.

## Roadmap

- Waitlist auto-fill: a cancelled slot is offered to waiting patients automatically.
- Recall campaigns: "6 months since your cleaning" re-invites via Telegram.
- Google Calendar per doctor (push first, free/busy second).
- Multi-tenant single instance (today: one lightweight compose stack per clinic).

## Pe scurt / Кратко

Sistem de programări pentru clinici stomatologice: chat de programare pentru pacienți
(RO/RU) + registru pentru recepție, o singură bază de date. O clinică nouă = un singur
fișier `clinic.json`. / Система записи для стоматологий: чат записи для пациентов (RO/RU)
+ журнал для ресепшена, одна база данных. Новая клиника = один файл `clinic.json`.

## License

MIT © Oleg Bacalu
