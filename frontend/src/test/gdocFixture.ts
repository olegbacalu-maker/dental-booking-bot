import type { GdocWords } from '../features/doctors/gdoc'

/* Слова блока календаря врача — как их отдаёт сервер (`gcal_doctor.WORDS`); общие для проверок карточки
   врача и списка Medici. */
export const GDOC_WORDS: GdocWords = {
  title: 'Calendarul medicului în Google',
  lead: 'Programările medicului ajung singure în Google Calendar, pe telefonul lui',
  connect: 'Conectează', reconnect: 'Conectează din nou', disconnect: 'Deconectează', disconnect_ok: 'Deconectează',
  check: 'Sincronizează acum',
  hint: 'Se deschide browserul: medicul intră cu contul său Google și permite accesul.',
  connected: 'Conectat:', calendar_label: 'calendarul', last_ok: 'Ultima actualizare:',
  pending: 'Încă de trimis:', level_label: 'În eveniment:',
  waiting_title: 'Așteptăm răspunsul Google…',
  waiting_detail: 'Medicul termină conectarea în browser. Dacă pagina s-a închis, deschideți-o din nou.',
  reopen: 'Deschide din nou pagina', cancel: 'Renunță',
  disconnect_ask: 'Deconectați calendarul medicului? Programul șterge din Google calendarul făcut de DentPilot.',
  premium_lead: 'O porniți plătind varianta Premium în', details: 'Detalii:',
  list_title: 'Calendarele medicilor în Google',
  level_title: 'Ce arată evenimentul în calendarele medicilor',
  level_ack: 'Am înțeles', level_save: 'Salvează',
}
