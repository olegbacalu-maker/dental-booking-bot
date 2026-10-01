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
  call: '' | 'ok' | 'noanswer'
  call_at: string
  call_by: string
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

export interface Desk {
  confirm: { day: string; date: string; items: DeskConfirmItem[]; n: number; n_ok: number; n_left: number }
  unscheduled: { items: DeskUnscheduledItem[]; n: number; sum_s: string }
  /** `null` — роли деньги не положены (PERM_MONEY): блока нет вовсе. */
  collect: {
    items: DeskCollectItem[]
    n: number
    sum_s: string
    cash: { total_s: string; parts: { method: string; sum_s: string }[] }
    casa_href: string
  } | null
  free: DeskFree[]
}

export type CallResult = '' | 'ok' | 'noanswer'
