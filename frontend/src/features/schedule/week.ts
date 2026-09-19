import { api } from '../../services/api'

/* Недельный календарь (C24). Формы ответа — bot/app/modules/schedule/api.py
   и week.py: состав колонок, счётчики и цвет чипа считает СЕРВЕР.

   ⛔ Дни приходят СПИСКОМ показанных, а не семью позициями. Закрытый день
   исчезает из недели, если в нём нет записей, поэтому колонок 5, 6 или 7.
   Раскладка по `weekday()` поставила бы субботу под воскресенье — выглядит
   правдоподобно, а данные стоят под чужим днём.
   ⛔ Цвет приезжает строкой `var(--green-soft)`, а не значением: клиника
   выбирает свой цвет темы, и зашитый хекс остался бы зелёным на синем
   интерфейсе. Строка подставляется в style как есть. */

export interface WeekItemAppt {
  kind: 'appt'
  id: number
  time: string
  name: string
  service: string
  noshow: boolean
  /** Переменная темы для фона чипа. */
  bg: string
  /** Переменная темы для левой полосы. */
  bar: string
}

export interface WeekItemNote {
  kind: 'note'
  time: string
  /** Обрезок, 30 знаков: чип недели показывает начало заметки. Полного
   *  значения у недели нет — ни диалога, ни живого канала здесь тоже нет. */
  text_cut: string
}

export type WeekItem = WeekItemAppt | WeekItemNote

export interface WeekDay {
  /** ISO-дата колонки. Ключ и адрес ссылки — она, а не индекс. */
  date: string
  /** Та же дата человеку: «22.09». */
  dm: string
  /** Короткая подпись дня недели словами сервера. */
  label: string
  /** Сколько ПАЦИЕНТОВ: заметки стойки сюда не входят. */
  count: number
  today: boolean
  /** Рабочий ли день по графику клиники. */
  open: boolean
  items: WeekItem[]
}

export interface WeekModel {
  monday: string
  sunday: string
  prev: string
  next: string
  /** «21.09 – 27.09.2026», собирает сервер. */
  span: string
  total: number
  days: WeekDay[]
  /** День, от которого открыли неделю: ссылки «Zi» ведут на него. */
  day: string
}

export const week = {
  get: (date: string, signal?: AbortSignal) =>
    api.get<WeekModel>(`/schedule/week${date ? `?date=${date}` : ''}`,
      signal ? { signal } : {}),
}
