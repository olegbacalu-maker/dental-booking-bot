import type { DayItem } from './day'

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
  /** За какое место блок взяли: px от его верха. */
  grab?: number
}

/** Куда бросили: колонка и минута начала по делению сетки. */
export interface Target {
  dk: string
  min: number
}

export function hhmm(min: number): string {
  const h = Math.floor(min / 60)
  return `${String(h).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`
}

/** Конец визита по началу «HH:MM» и длительности — для «09:00–10:00» на
 *  карточке. Считается от того же `time`, что напечатан рядом: интервал
 *  обязан начинаться ровно им. */
export function endOf(time: string, dur: number): string {
  const [h = 0, m = 0] = time.split(':').map(Number)
  return hhmm((h * 60 + m + dur) % (24 * 60))
}

/**
 * Ячейка ПО КООРДИНАТЕ, а не по `e.target` (C26.5.3-f).
 *
 * На канве панели блоки лежат ПОВЕРХ ячеек и приходятся им СОСЕДЯМИ, а не
 * детьми: событие переноса над чужим визитом целится в него, и ячейка под
 * курсором не участвует в нём никак. Ищем её перебором прямоугольников —
 * иначе бросок на соседний визит попадал бы в никуда вместо его часа.
 * `null` — курсор вне приёмных часов: закрытая ячейка мишенью не бывает, и
 * список ей просто не содержит (у неё нет `data-h`).
 */
export interface CellRect {
  h: number
  top: number
  height: number
}

/** Минута часа (дробная) под координатой и её ячейка. */
export function cellAtY(cells: CellRect[], y: number): { h: number; at: number } | null {
  for (const c of cells) {
    if (y >= c.top && y < c.top + c.height) {
      return { h: c.h, at: ((y - c.top) / c.height) * 60 }
    }
  }
  return null
}

/**
 * Минута от полуночи под координатой, по делению `snap`. Щелчок берёт деление,
 * В КОТОРОЕ попал (вниз), бросок — ближайшее: верх блока тянут к линии.
 * Ближайшее деление может оказаться началом следующего часа; если тот закрыт,
 * остаётся последнее деление этого.
 */
export function minuteAtY(cells: CellRect[], y: number, snap: number,
  nearest = false): number | null {
  const c = cellAtY(cells, y)
  if (!c) return null
  const m = (nearest ? Math.round(c.at / snap) : Math.floor(c.at / snap)) * snap
  if (m < 60) return c.h * 60 + m
  return cells.some((x) => x.h === c.h + 1) ? (c.h + 1) * 60 : c.h * 60 + 60 - snap
}

/**
 * Куда встанет НАЧАЛО визита при броске: блок держат за точку `grab` (px от его
 * верха), и время считается по верху блока, а не по курсору — иначе сдвиг на
 * пять минут зависел бы от того, за какое место блок взяли. Верх вне приёмных
 * часов — считаем по курсору.
 */
export function dropMinute(cells: CellRect[], y: number, grab: number,
  snap: number): number | null {
  return minuteAtY(cells, y - grab, snap, true) ?? minuteAtY(cells, y, snap)
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
 * пациента, а летопись не переписывают. Сравниваются колонка и минута.
 */
export function sameSlot(d: Drag, t: Target): boolean {
  return d.dk === t.dk && d.min === t.min
}

/**
 * Занят ли интервал у ЭТОГО врача — теми же статусами, что считает
 * `db._conflicts` (поле `busy`). Возвращает минуту помехи или −1. Список —
 * блоки колонки канвы: ею с 06.10 живут оба экрана дня, панель и
 * «Programări» (табличный `clash` по модели дня ушёл вместе с таблицей).
 *
 * ⚠️ Себя запись исключает по id: иначе визит нашёл бы САМ СЕБЯ и перенос к
 * другому врачу на тот же час всегда «сталкивался» бы.
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
