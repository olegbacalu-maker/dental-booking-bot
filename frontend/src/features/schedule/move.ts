import type { DayItem, DayModel } from './day'

/* Договор перетаскивания (C25.5b) — правила без единого узла DOM, поэтому их
   можно проверить по одному.

   ⛔ Четыре поля, и все четыре несущие. Их печатает `core/visits._move_attrs`
   на старой странице и отдаёт `day.appt_view` в модели:

     min      минуты от полуночи — ОТКУДА тащим (и что показывает «De la»);
     dur      длительность — по ней считается пересечение с соседом;
     busy     визит занимает интервал (ровно те статусы, что считает
              `db._conflicts`); завершённый и отменённый места не занимают;
     movable  тащить можно только активный визит и только из колонки
              настоящего врача.

   Потеряй любое — сломается молча: без `dur` пересечение считается по часу и
   предупреждение не загорится; без `busy` в помехи попадут завершённые;
   без `movable` потащится закрытая запись и получит `mv_closed` от сервера.

   ⚠️ Занятость здесь — ТОЛЬКО подсказка. Правду говорит сервер под
   `_BOOK_LOCK`: пока тянут, бронь мог поставить второй администратор. */

/** Перетаскиваемое: то, что снимается с карточки в начале броска. */
export interface Drag {
  id: number
  /** Колонка, ИЗ которой тащат. */
  dk: string
  min: number
  dur: number
  /** Имя пациента или текст заметки — то же, что `data-nm` у страницы. */
  nm: string
}

/** Куда бросили: колонка и минута (час ячейки плюс половина). */
export interface Target {
  dk: string
  min: number
}

export function hhmm(min: number): string {
  const h = Math.floor(min / 60)
  return `${String(h).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`
}

/**
 * Половина часа берётся из МЕСТА броска внутри ячейки, а не из её номера:
 * сетка стартов 30-минутная (`engine.GRID_STEP`), и «09:30 → 10:00» обязано
 * отличаться от «09:30 → 10:30». Верх ячейки — :00, низ — :30.
 */
export function halfAt(y: number, rect: { top: number; height: number }): 0 | 30 {
  return y - rect.top >= rect.height / 2 ? 30 : 0
}

/**
 * Ячейка ПО КООРДИНАТЕ, а не по `e.target` (C26.5.3-f).
 *
 * ⛔ На канве панели блоки лежат ПОВЕРХ ячеек и приходятся им СОСЕДЯМИ, а не
 * детьми: событие переноса над чужим визитом целится в него, и ячейка под
 * курсором не участвует в нём никак. Ищем её перебором прямоугольников, ровно
 * как `targetAt` в `panel.js`, — иначе бросок на соседний визит попадал бы в
 * никуда вместо его часа.
 * ⚠️ `null` — курсор вне приёмных часов: закрытая ячейка мишенью не бывает, и
 * список ей просто не содержит (у неё нет `data-h`).
 */
export interface CellRect {
  h: number
  top: number
  height: number
}

export function cellAtY(cells: CellRect[], y: number): { h: number; half: 0 | 30 } | null {
  for (const c of cells) {
    if (y >= c.top && y < c.top + c.height) {
      return { h: c.h, half: halfAt(y, c) }
    }
  }
  return null
}

/** Что снять с карточки, чтобы её тащить. `null` — эту запись не тащат. */
export function dragOf(item: DayItem, dk: string): Drag | null {
  if (!item.movable) return null
  return {
    id: item.id,
    dk,
    min: item.min,
    dur: item.dur || 60,
    nm: item.kind === 'note' ? item.text : item.name,
  }
}

/**
 * Бросок на своё же место. ⛔ Правило браузерное, и обойтись без него нельзя:
 * сервер такой перенос ПРИНИМАЕТ (`ok_move`) и пишет строку в летопись
 * пациента, а летопись не переписывают. Сравниваются колонка и минута —
 * получас считается переносом.
 */
export function sameSlot(d: Drag, t: Target): boolean {
  return d.dk === t.dk && d.min === t.min
}

/**
 * Занят ли интервал у ЭТОГО врача — теми же статусами, что считает
 * `db._conflicts` (поле `busy`). Возвращает минуту помехи или −1.
 *
 * ⚠️ Себя запись исключает по id: иначе визит нашёл бы САМ СЕБЯ и перенос к
 * другому врачу на тот же час всегда «сталкивался» бы.
 */
export function clash(model: DayModel, t: Target, dur: number, id: number): number {
  const col = model.doctors.findIndex((x) => x.id === t.dk)
  if (col < 0) return -1
  const items = model.hours.flatMap((row) => row.cells[col]?.items ?? [])
  return clashAmong(items, t.min, dur, id)
}

/**
 * То же правило над ГОТОВЫМ списком занятых — им живёт канва панели, где
 * записи лежат не в ячейках, а в колонке.
 *
 * ⛔ Одно правило на два экрана: разойдись они, подсказка о занятости
 * загоралась бы на одном и молчала на другом при одинаковых данных, и
 * увидеть это можно было бы, только открыв оба.
 */
export interface Occupies {
  id: number
  min: number
  dur: number
  busy: boolean
}

export function clashAmong(items: Occupies[], min: number, dur: number,
  id: number): number {
  for (const it of items) {
    if (!it.busy || it.id === id) continue
    const s = it.min
    const e = s + (it.dur || 60)
    if (s < min + dur && min < e) return s
  }
  return -1
}

/** Имя колонки для строк «De la» / «La» — из модели, а не из ссылок страницы. */
export function doctorName(model: DayModel, dk: string): string {
  return model.doctors.find((x) => x.id === dk)?.name ?? '—'
}
