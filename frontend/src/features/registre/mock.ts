/* «Registre» — ЗАГЛУШКА данных макета (10.11.2026, san-registers, этап 1).
   ⚠️ Ни одного запроса: всё, что видно на кадрах, лежит здесь. На этапе 2
   данные даст сервер (`/api/registre`), «сейчас» и подпись — тоже сервер.
   Колонки — по бланкам ANSP: 257/e (Ordin MS 828/2011), 502/e и 501/e
   (Ordin MS 630/2016); разбор — side-session-notes/2026-11-10/san-registers.md. */

export type RegKey = '257' | '502' | '501'
export type Test = 'ok' | 'fail' | ''

export const NOW = { date: '10.11.2026', time: '11:42', iso: '2026-11-10' }
/* кто подписывает — тот, кто вошёл: в макете имя берётся из шапки оболочки
   (на этапе 2 его поставит сервер, клиенту оно не доверяется) */
const who = () => (typeof document === 'undefined' ? null : document.querySelector('.who'))
export const ME = {
  get name() { return who()?.querySelector('b')?.textContent?.trim() || 'Ana Rusu' },
  get role() { return (who()?.querySelector('small')?.textContent ?? '').split('·')[0]?.trim() || 'Asistentă medicală' },
  director: false,
}
export const DIRECTOR = 'Dr. Elena Ceban'

export const REGS: { key: RegKey; form: string; short: string; title: string; order: string; keep: string }[] = [
  { key: '257', form: '257/e', short: 'Sterilizare',
    title: 'Registru de evidență a controlului lucrului sterilizatoarelor cu aer, cu aburi (autoclav)',
    order: 'Aprobat de MS al RM nr. 828 din 31.10.2011', keep: '1 an' },
  { key: '502', form: '502/e', short: 'Curățenie generală',
    title: 'Registru de evidență a efectuării curățeniei generale',
    order: 'Aprobat de MS al RM nr. 630 din 08.08.2016', keep: '3 ani' },
  { key: '501', form: '501/e', short: 'Lămpi bactericide',
    title: 'Registru de evidență a utilizării lămpilor bactericide pentru dezinfecție',
    order: 'Aprobat de MS al RM nr. 630 din 08.08.2016', keep: '3 ani' },
]

export interface Program { id: string; label: string; t: number; p: string; min: number; total: number }
export interface Sterilizer { id: string; name: string; nr: string; kind: 'abur' | 'aer'; room: string; programs: Program[] }
export interface Lamp { id: string; name: string; nr: string; room: string; m3: number; since: string; hours: number; used: number; screened: boolean }
export interface Room { id: string; name: string; every: number; last: string; next: string }

export const STERILIZERS: Sterilizer[] = [
  { id: 'a1', name: 'Melag 23 B+', nr: '23-11845', kind: 'abur', room: 'Sala de sterilizare',
    programs: [
      { id: 'p134', label: 'Universal 134 °C', t: 134, p: '2,1', min: 5, total: 45 },
      { id: 'p121', label: 'Delicat 121 °C', t: 121, p: '1,1', min: 20, total: 60 },
      { id: 'p134r', label: 'Prioni 134 °C', t: 134, p: '2,1', min: 18, total: 60 },
    ] },
  { id: 'a2', name: 'GP-40', nr: '0412', kind: 'aer', room: 'Sala de sterilizare',
    programs: [
      { id: 'p180', label: 'Aer 180 °C', t: 180, p: '—', min: 60, total: 90 },
      { id: 'p160', label: 'Aer 160 °C', t: 160, p: '—', min: 150, total: 180 },
    ] },
]

export const LAMPS: Lamp[] = [
  { id: 'l1', name: 'OBN-150 ecranată', nr: '2', room: 'Cabinet 1', m3: 45, since: '01.03.2025', hours: 8000, used: 7962, screened: true },
  { id: 'l2', name: 'Dezar-3 (recirculator)', nr: '7', room: 'Cabinet 2', m3: 42, since: '12.01.2026', hours: 9000, used: 1240, screened: true },
  { id: 'l3', name: 'OBN-75', nr: '4', room: 'Sala de sterilizare', m3: 18, since: '20.06.2025', hours: 8000, used: 2615, screened: false },
]

export const ROOMS: Room[] = [
  { id: 'r1', name: 'Cabinet 1', every: 7, last: '03.11.2026', next: '10.11.2026' },
  { id: 'r2', name: 'Cabinet 2', every: 7, last: '05.11.2026', next: '12.11.2026' },
  { id: 'r3', name: 'Sala de sterilizare', every: 7, last: '07.11.2026', next: '14.11.2026' },
  { id: 'r4', name: 'Recepție și hol', every: 30, last: '20.10.2026', next: '19.11.2026' },
]

export const SOLUTIONS = ['Septodor Forte 0,2 % · 60 min', 'Clorantoin 0,1 % · 60 min', 'Dezactiv-M 1 % · 30 min']
export const ARTICLES = ['Instrumentar stomatologic', 'Freze și pile', 'Piese de mână', 'Tăvițe și pense', 'Material textil']
export const PACKS = ['Pungă', 'Casetă', 'Bix', 'Fără ambalaj']
export const NORMS = [
  'HG nr. 4/2026 — Regulamentul sanitar privind condițiile de igienă pentru prestatorii de servicii medicale',
  'Ordinul MS nr. 668/2025 — Ghid practic „Prevenirea și controlul infecțiilor” (ambulator)',
  'Instrucțiunea producătorului Melag Vacuklav 23 B+',
]
export const SUPERVISORS = [DIRECTOR, 'Maria Lungu (asistentă-șefă)']

export interface Art { name: string; qty: number; pack: string }
export interface Cycle {
  nr: number; date: string; start: string; end: string; ster: string; prog: string; t: number; p: string
  arts: Art[]; chem: Test; term: Test; bio: Test | 'wait'
  by: string; at: string; running?: boolean; fixes?: number; fixedBy?: number; why?: string
}

export const CYCLES: Cycle[] = [
  { nr: 1, date: '03.11.2026', start: '08:40', end: '09:25', ster: 'a1', prog: 'p134', t: 134, p: '2,1',
    arts: [{ name: 'Instrumentar stomatologic', qty: 12, pack: 'Pungă' }, { name: 'Freze și pile', qty: 2, pack: 'Casetă' }],
    chem: 'ok', term: 'ok', bio: 'ok', by: 'Ana Rusu', at: '03.11.2026 09:26' },
  { nr: 2, date: '03.11.2026', start: '13:10', end: '14:40', ster: 'a2', prog: 'p180', t: 180, p: '—',
    arts: [{ name: 'Tăvițe și pense', qty: 6, pack: 'Bix' }],
    chem: 'ok', term: 'ok', bio: '', by: 'Maria Lungu', at: '03.11.2026 14:41' },
  { nr: 3, date: '05.11.2026', start: '08:35', end: '09:20', ster: 'a1', prog: 'p134', t: 134, p: '2,1',
    arts: [{ name: 'Instrumentar stomatologic', qty: 15, pack: 'Pungă' }, { name: 'Piese de mână', qty: 4, pack: 'Pungă' }],
    chem: 'ok', term: 'ok', bio: '', by: 'Ana Rusu', at: '05.11.2026 09:21', fixedBy: 4 },
  { nr: 4, date: '05.11.2026', start: '08:35', end: '09:20', ster: 'a1', prog: 'p134', t: 134, p: '2,1',
    arts: [{ name: 'Instrumentar stomatologic', qty: 15, pack: 'Pungă' }, { name: 'Piese de mână', qty: 3, pack: 'Pungă' }],
    chem: 'ok', term: 'ok', bio: '', by: 'Ana Rusu', at: '05.11.2026 09:48', fixes: 3,
    why: 'Piese de mână: 3, nu 4' },
  { nr: 5, date: '07.11.2026', start: '09:05', end: '10:05', ster: 'a1', prog: 'p121', t: 121, p: '1,1',
    arts: [{ name: 'Material textil', qty: 3, pack: 'Bix' }],
    chem: 'fail', term: 'ok', bio: '', by: 'Maria Lungu', at: '07.11.2026 10:07' },
  { nr: 6, date: '07.11.2026', start: '10:20', end: '11:20', ster: 'a1', prog: 'p121', t: 121, p: '1,1',
    arts: [{ name: 'Material textil', qty: 3, pack: 'Bix' }],
    chem: 'ok', term: 'ok', bio: '', by: 'Maria Lungu', at: '07.11.2026 11:21' },
  { nr: 7, date: '10.11.2026', start: '08:30', end: '09:15', ster: 'a1', prog: 'p134', t: 134, p: '2,1',
    arts: [{ name: 'Instrumentar stomatologic', qty: 18, pack: 'Pungă' }, { name: 'Freze și pile', qty: 3, pack: 'Casetă' }],
    chem: 'ok', term: 'ok', bio: 'wait', by: 'Ana Rusu', at: '10.11.2026 09:16' },
  { nr: 8, date: '10.11.2026', start: '11:20', end: '', ster: 'a1', prog: 'p134', t: 134, p: '2,1',
    arts: [{ name: 'Instrumentar stomatologic', qty: 9, pack: 'Pungă' }, { name: 'Piese de mână', qty: 2, pack: 'Pungă' }],
    chem: '', term: '', bio: '', by: 'Ana Rusu', at: '10.11.2026 11:20', running: true },
]

export interface Clean {
  nr: number; room: string; plan: string; done: string; sol: string; by: string; at: string
  sup: string; supAt: string; fixes?: number; fixedBy?: number; why?: string
}
export const CLEANS: Clean[] = [
  { nr: 1, room: 'Recepție și hol', plan: '20.10.2026', done: '20.10.2026', sol: 'Clorantoin 0,1 % · 60 min', by: 'Ion Cebotari', at: '20.10.2026 19:05', sup: DIRECTOR, supAt: '21.10.2026 08:30' },
  { nr: 2, room: 'Cabinet 1', plan: '03.11.2026', done: '03.11.2026', sol: 'Septodor Forte 0,2 % · 60 min', by: 'Ion Cebotari', at: '03.11.2026 19:40', sup: DIRECTOR, supAt: '04.11.2026 08:15' },
  { nr: 3, room: 'Cabinet 2', plan: '05.11.2026', done: '05.11.2026', sol: 'Septodor Forte 0,2 % · 60 min', by: 'Ion Cebotari', at: '05.11.2026 19:20', sup: 'Maria Lungu (asistentă-șefă)', supAt: '06.11.2026 08:05' },
  { nr: 4, room: 'Sala de sterilizare', plan: '07.11.2026', done: '07.11.2026', sol: 'Dezactiv-M 1 % · 30 min', by: 'Maria Lungu', at: '07.11.2026 18:55', sup: '', supAt: '' },
]

export interface Uv {
  nr: number; date: string; lamp: string; cond: 'fără persoane' | 'în prezența persoanelor'
  on: string; off: string; min: number; rest: number; by: string; at: string; running?: boolean
}
export const UVS: Uv[] = [
  { nr: 1, date: '07.11.2026', lamp: 'l1', cond: 'fără persoane', on: '07:45', off: '08:15', min: 30, rest: 39, by: 'Ana Rusu', at: '07.11.2026 08:15' },
  { nr: 2, date: '07.11.2026', lamp: 'l3', cond: 'fără persoane', on: '18:10', off: '18:40', min: 30, rest: 5386, by: 'Maria Lungu', at: '07.11.2026 18:40' },
  { nr: 3, date: '10.11.2026', lamp: 'l1', cond: 'fără persoane', on: '07:50', off: '08:20', min: 30, rest: 38, by: 'Ana Rusu', at: '10.11.2026 08:20' },
  { nr: 4, date: '10.11.2026', lamp: 'l2', cond: 'în prezența persoanelor', on: '08:00', off: '', min: 0, rest: 7760, by: 'Ana Rusu', at: '10.11.2026 08:00', running: true },
]

export const sterOf = (id: string) => STERILIZERS.find((s) => s.id === id) ?? STERILIZERS[0]!
export const progOf = (s: Sterilizer, id: string) => s.programs.find((p) => p.id === id) ?? s.programs[0]!
export const lampOf = (id: string) => LAMPS.find((l) => l.id === id) ?? LAMPS[0]!
export const lampRest = (l: Lamp) => l.hours - l.used
export const lampLow = (l: Lamp) => lampRest(l) <= Math.max(50, l.hours * 0.02)
