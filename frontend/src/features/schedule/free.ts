import type { DashCanvasModel, DashColumn } from './dash'

/**
 * «Primul loc liber» (08.10, макет): ближайший свободный ЦЕЛЫЙ час у каждого
 * врача на показанном дне — по канве, которая уже на экране, без второго
 * запроса. Правило из промпта: сегодня — от следующего целого часа, в другой
 * день — от начала рабочего дня.
 *
 * ⛔ Свободен час, в котором ячейка ОТКРЫТА и который не задет НИ ОДНИМ
 * блоком — визитом или заметкой стойки: заметка тоже занимает кресло, и
 * сервер отказал бы записи в неё. Геометрия та же, что у блоков на сетке
 * (`top`/`height` в ячейках от первого ряда), второго счёта времени нет.
 * ⚠️ Это ПОДСКАЗКА, как и у диалога пустого часа: правду говорит сервер под
 * своим замком, и кнопка открывает тот же диалог, а не пишет сама.
 */
export interface FreeSlot {
  dk: string
  name: string
  initials: string
  hue: string
  /** Час «HH:00» или `null` — свободных целых часов нет. */
  hour: string | null
}

/** Первый открытый час колонки, не ниже `fromHour`, не задетый блоками. */
export function firstFreeHour(col: DashColumn, hours: number[], fromHour: number): number | null {
  for (let i = 0; i < hours.length; i++) {
    const h = hours[i]!
    if (h < fromHour || !col.cells[i]) continue
    const taken = col.blocks.some((b) => b.top < i + 1 && b.top + b.height > i)
    if (!taken) return h
  }
  return null
}

/**
 * Список по колонкам настоящих врачей (у сироты записать некуда). `now` —
 * часы клиники, когда показан СЕГОДНЯШНИЙ день; иначе `null` — с начала дня.
 * ⚠️ «Следующий целый час»: в 11:00 ровно — это 11:00, в 11:01 — 12:00.
 */
export function freeSlots(canvas: DashCanvasModel, now: { hh: number; mm: number } | null): FreeSlot[] {
  const from = now === null ? 0 : now.mm > 0 ? now.hh + 1 : now.hh
  const hours = canvas.hours.map((h) => h.h)
  return canvas.columns
    .filter((c) => c.id !== null && !c.orphan)
    .map((c) => {
      const h = c.off ? null : firstFreeHour(c, hours, from)
      return { dk: c.id!, name: c.name, initials: c.initials, hue: c.hue,
        hour: h === null ? null : `${String(h).padStart(2, '0')}:00` }
    })
}
