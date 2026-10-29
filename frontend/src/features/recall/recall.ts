import { api, type ApiResult } from '../../services/api'

/* «Rechemări» (29.10): формы ответов — bot/app/modules/recall/api.py,
   контракт — docs/dentpilot-2/recall-api.md. Правило списка считает сервер
   (core/recall.py); здесь только форма, письмо и адрес `mailto:`. */

export type RecallResult = 'contacted' | 'emailed' | 'noanswer' | 'later' | 'stop' | 'clear'
export type RecallTab = 'due' | 'snoozed' | 'stop'

export interface RecallMark {
  result: Exclude<RecallResult, 'clear'>
  /** Слово сервера («nu răspunde», «amânat»…) — одно на список, главную, фишу. */
  word: string
  /** Голая дата ISO (`later`, или конец тишины у contacted/emailed) или пусто. */
  until: string
  n_noanswer: number
  /** «DD.MM» — день отметки по часам клиники. */
  at: string
  actor: string
}

export interface RecallRow {
  pid: number
  name: string
  phone: string
  email: string
  lang: string
  service_id: string
  service: string
  months: number
  /** ISO-даты: последний завершённый визит и срок. */
  last_at: string
  doctor: string
  due: string
  /** >0 просрочен, <0 ещё не наступил; слово — `late` (сервера). */
  late_days: number
  late: string
  booked: { date: string; service: string } | null
  mark: RecallMark | null
  tab: RecallTab
}

export interface RecallService { id: string; ro: string; months: number; since: string }

export interface RecallData {
  services: RecallService[]
  rows: RecallRow[]
  counts: Record<RecallTab, number>
  clinic: { name: string; phone: string }
  /** Право на настройки у вошедшего (решает сервер): пустой экран без срока
   *  ведёт директора в Setări › Servicii, регистратуре говорит словом. */
  can_settings: boolean
  /** Статистика одной строкой (Олег 29.10, В4 → Б): за текущий и прошлый
   *  календарный месяц — пациенты с отметкой «sunat»/«e-mail» и из них те,
   *  у кого после отметки появилась запись на ту же услугу. Считает сервер;
   *  `null` — ни одной такой отметки: строки нет (нули не рисуются). */
  stats: { month: RecallStat; prev: RecallStat } | null
}

export interface RecallStat { contacted: number; booked: number }

export const recallApi = {
  get: (signal?: AbortSignal): Promise<ApiResult<RecallData>> =>
    api.get<RecallData>('/recall', signal ? { signal } : {}),
  mark: (pid: number, service_id: string, result: RecallResult, until = '') =>
    api.post<null>('/recall/mark', until ? { pid, service_id, result, until } : { pid, service_id, result }),
}

/** «2026-10-02» → «02.10.2026»; чужую строку отдаёт как есть. */
export function dmy(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso
}

/** Письмо пациенту: тема и текст — клинические, без цен, скидок и акций
 *  (план § 3: «прошло N месяцев… рекомендуем контроль» — забота; «скидка» —
 *  маркетинг, и там нужна галочка opt_mkt). Язык — из фиши (`lang`), как у
 *  печатных листов. Текст постоянный: правится в письме перед отправкой. */
export function letter(r: RecallRow, clinic: RecallData['clinic']): { subject: string; body: string } {
  const first = r.name.trim().split(/\s+/)[0] || r.name
  if (r.lang === 'ru') {
    return {
      subject: `Плановый контроль — ${clinic.name}`,
      body: `Здравствуйте, ${first}.\n\nПрошло ${r.months} мес. с последней процедуры «${r.service}» в ${clinic.name}. `
        + 'Врач рекомендует плановый контроль.\n\n'
        + `Позвоните нам по номеру ${clinic.phone}, чтобы выбрать удобное время.\n\n`
        + `С уважением,\n${clinic.name}`,
    }
  }
  return {
    subject: `Control periodic — ${clinic.name}`,
    body: `Bună ziua, ${first}.\n\nAu trecut ${r.months} luni de la ultima procedură „${r.service}” la ${clinic.name}. `
      + 'Medicul recomandă un control periodic.\n\n'
      + `Ne puteți suna la ${clinic.phone} pentru a stabili o oră potrivită.\n\n`
      + `Cu stimă,\n${clinic.name}`,
  }
}

/** Адрес `mailto:` — тема и тело в кодировке URL (диакритика, `&`, переносы
 *  строк как %0A). Оболочка отдаёт его почтовой программе Windows; через наш
 *  сервер письмо не идёт. Тело короткое: длинный `mailto:` часть программ режет. */
export function mailto(to: string, l: { subject: string; body: string }): string {
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(l.subject)}&body=${encodeURIComponent(l.body)}`
}
