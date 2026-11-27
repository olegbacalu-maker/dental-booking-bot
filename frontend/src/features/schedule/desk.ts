import type { RecallRow } from '../recall/recall'

/* «La recepție» (01.10): рабочие списки регистратуры — форма куска `desk`
   живого конверта панели (`bot/app/modules/schedule/desk.py`). Своего GET у
   них нет: состояние панели едет одной дверью, отметка звонка — командой. */

export interface DeskConfirmItem {
  id: number
  pid: number
  time: string
  name: string
  phone: string
  doctor: string
  service: string
  call: CallMark
  /** `'sms'` — отметку поставил пациент ссылкой из напоминания (Premium); пусто — звонок стойки. */
  call_via?: string
  call_at: string
  /** Когда нажал пациент (UTC ISO, только при `call_via = 'sms'`). */
  answer_at?: string
  call_by: string
}

/** Ответ пациента ссылкой — строка плашки на главной (`desk.answers`, вид A). */
export interface DeskAnswer {
  id: number
  pid: number
  name: string
  call: 'ok' | 'cant'
  /** «luni 30.11, 14:30» / «azi, 14:30» — готовой строкой сервера. */
  when: string
  /** Когда нажал (UTC ISO): пара `id`+`answer_at`+`call` отличает новое от прежнего. */
  answer_at: string
}

export interface DeskUnscheduledItem {
  pid: number
  name: string
  phone: string
  n: number
  total: number
  total_s: string
  days: number
}

export interface DeskCollectItem {
  pid: number
  name: string
  time: string
  status: string
  status_label: string
  debt: number
  debt_s: string
}

export interface DeskFree {
  dk: string
  name: string
  when: string
  today: boolean
  href: string
}

/** Строка «Nefinalizate» / «Anulate fără reprogramare»: визит прошлого дня. */
export interface DeskPastItem {
  id: number
  pid: number
  date: string
  time: string
  /** День визита ISO — ссылка на день журнала. */
  iso: string
  name: string
  phone: string
  doctor: string
  status: string
  status_label: string
}

/** Список обзвона одного дня — одна форма на «azi» и «mâine». */
export interface DeskConfirm {
  day: string; date: string; items: DeskConfirmItem[]; n: number; n_ok: number; n_left: number
  /** «Nu poate veni» ответом ссылкой — сервер ставит их наверх; стойке звонить им сейчас. */
  n_cant?: number
}

export interface Desk {
  /** Сегодняшние, кого не подтвердили вчера (12.10, слово Олега). */
  confirm_today: DeskConfirm
  confirm: DeskConfirm
  unscheduled: { items: DeskUnscheduledItem[]; n: number; sum_s: string }
  /** «Nefinalizate»: визиты прошлых дней без исхода, свежие сверху. */
  unclosed: { items: DeskPastItem[]; n: number }
  /** «Anulate fără reprogramare»: отмены и неявки без новой записи. */
  lost: { items: DeskPastItem[]; n: number }
  /** `null` — роли деньги не положены (PERM_MONEY): блока нет вовсе. */
  collect: {
    items: DeskCollectItem[]
    n: number
    sum_s: string
    cash: { total_s: string; parts: { method: string; sum_s: string }[] }
    casa_href: string
  } | null
  free: DeskFree[]
  /** «Rechemări» (29.10): счётчик «De sunat» и первые строки той же формы,
   *  что у экрана; `null` — у роли нет права (врач): раздела нет вовсе. */
  recall: { n: number; items: RecallRow[] } | null
  /** Ответы пациентов ссылкой сегодня и на следующий рабочий день (Premium); `null` или нет поля —
   *  плашек нет (нет права, ссылки или галочки «Anunță pe ecran»). Врачу — только его визиты. */
  answers?: DeskAnswer[] | null
}

export type CallResult = '' | 'ok' | 'noanswer'

/** Отметка, как её видит экран: к командам стойки добавлено `cant` — «nu poate veni», его ставит
 *  только ответ пациента ссылкой (стойка шлёт по-прежнему `CallResult`). */
export type CallMark = CallResult | 'cant'

/** Слова отметки звонка — ОДНИ на «De confirmat», карточку визита и меню
 *  правой кнопки (12.10): три места с тремя наборами слов разошлись бы молча,
 *  как расходились слова статусов (08-12, 08-16). Слово вида записи после
 *  звонка («confirmată») — сервера (`layout.CALL_LABEL`), здесь только кнопки. */
export const CALL_WORDS = {
  call: 'Confirmare telefonică',
  ok: 'Confirmat',
  no: 'Nu răspunde',
  undo: 'Anulează bifa',
  okDone: 'confirmat',
  noDone: 'nu răspunde',
  // ответ пациента ссылкой из напоминания (Premium, волна 2а)
  okSms: 'Confirmat · SMS',
  cantSms: 'Nu poate veni · SMS',
  okSmsDone: 'confirmat · SMS',
  cantDone: 'nu poate veni · SMS',
  okSmsWhen: 'pacientul a apăsat „Vin” în link · {at}',
  cantSmsWhen: 'pacientul a apăsat „Nu pot veni” în link · {at}.',
  cantSay: 'Sunați pacientul. Vizita rămâne în jurnal până o mutați sau o anulați.',
  /** Слово на блоке канвы — то же, что у сервера (`labels.CALL_LABEL["cant"]`). */
  cantWord: 'nu poate veni',
  /** Подсказка галочки на блоке при новом «Vin». */
  vinHint: 'Pacientul a confirmat prin SMS',
} as const
