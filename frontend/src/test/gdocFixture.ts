import type { GdocListWords, GdocWords } from '../features/doctors/gdoc'

/* Слова блока календаря врача и полосы списка — как их отдаёт сервер (`gcal_doctor.WORDS`, `LIST_WORDS`);
   общие для проверок карточки врача и списка Medici. */
export const GDOC_WORDS: GdocWords = {
  title: 'Google Calendar',
  lead: 'Programările medicului ajung singure în calendarul lui din Google, în cel mult 5 minute.',
  hint: 'Se deschide browserul: medicul alege contul lui Google și permite accesul.',
  details: 'Detalii:',
  connect: 'Conectează Google', connect_here: 'Conectează aici', reconnect: 'Conectează din nou',
  check: 'Sincronizează acum', disconnect: 'Deconectează',
  disconnect_ask: 'Deconectați Google Calendar al medicului? Calendarul „DentPilot · Clinica Test · Dr. Activ Doi” se șterge.',
  waiting_title: 'Așteptăm răspunsul Google…',
  waiting_detail: 'În browser medicul alege contul lui Google și permite accesul.',
  reopen: 'Deschide din nou pagina', cancel: 'Renunță',
  connected: 'Conectat:', calendar_label: 'Calendarul',
  last: 'Ultima actualizare:', all_in: 'totul e la zi.', last_ok: 'Ultima reușită:',
  pending: '',
  level_lead: 'Ce vede medicul:', level_link: 'Se schimbă în lista Medici',
  premium_lead: 'O porniți plătind varianta Premium în',
}

export const GDOC_LIST_WORDS: GdocListWords = {
  title: 'Calendarele medicilor în Google',
  lead: 'Fiecare medic conectat își vede programările în telefon.',
  count: 'Conectați: 1 din 2 medici',
  label: 'Ce vede medicul în Google', phone: 'În telefon:', change: 'Schimbă',
  only_dir: 'Schimbă doar directorul.', remote: 'Se schimbă doar de pe calculatorul pe care rulează programul.',
  premium: 'Calendarele medicilor în Google fac parte din DentPilot Premium:',
  premium_more: 'fiecare medic își vede programările în telefon, implicit doar ora.',
  default: 'implicit', rewrite: 'La schimbare calendarele se rescriu singure, în cel mult 5 minute.',
  dlg_title: 'Ce vede medicul în Google',
  dlg_ack: 'Am înțeles: aceste date ale pacienților vor fi în Google.',
  dlg_ok: 'Alege', dlg_cancel: 'Renunță',
  chip: { on: 'Google conectat', off: 'Google neconectat', reconnect: 'Google: de refăcut' },
}
