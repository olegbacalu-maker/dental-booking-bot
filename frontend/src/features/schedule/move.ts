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
  for (const row of model.hours) {
    const cell = row.cells[col]
    if (!cell) continue
    for (const it of cell.items) {
      if (!it.busy || it.id === id) continue
      const s = it.min
      const e = s + (it.dur || 60)
      if (s < t.min + dur && t.min < e) return s
    }
  }
  return -1
}

/** Имя колонки для строк «De la» / «La» — из модели, а не из ссылок страницы. */
export function doctorName(model: DayModel, dk: string): string {
  return model.doctors.find((x) => x.id === dk)?.name ?? '—'
}
