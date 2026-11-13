import { describe, expect, it } from 'vitest'
import { freeSpans, hourLabel, hourMinutes, slotTimes, spanAt, startIn, takenMinutes } from './slot'
import type { Occupies } from './move'

/* Времена пустого часа. Проверка отвечает на ОДИН вопрос — что двигает выбор
   минуты, — и ответ у неё тот же, что у сервера: время записи двигает, час
   заметки и её концы не трогает. */

/* День клиники 9–18 с обедом 13–14: концы блокировки идут подряд и 14:00
   среди них НЕТ. Это не дыра в фикстуре — так их считает `pday.note_ends`. */
const ENDS = [10, 11, 12, 13, 15, 16, 17, 18]

describe('C26.5.3-c: минута двигает ОДНО время из двух', () => {
  it('ровный час: запись в 10:00, заметка с 10:00 и до 11:00', () => {
    const t = slotTimes('10:00', 0, ENDS)
    expect(t.atime).toBe('10:00')
    expect(t.ntime).toBe('10:00')
    expect(t.ends[0]).toBe(11)
  })

  it('минута меняет ТОЛЬКО atime — интервал заметки не пересчитывается', () => {
    /* Заметка блокирует ЧАСЫ ПРИЁМА, как и ячейки сетки. Уедь `ntime` на
       10:30 — сервер молча округлил бы его вниз (`int(ntime.split(":")[0])`),
       и экран сказал бы «с 10:30», а в базе легла бы блокировка с 10:00. */
    const full = slotTimes('10:00', 0, ENDS)
    const half = slotTimes('10:00', 30, ENDS)
    expect(half.atime).toBe('10:30')
    expect(half.ntime).toBe(full.ntime)
    expect(half.ends).toEqual(full.ends)
    const five = slotTimes('10:00', 5, ENDS)
    expect([five.atime, five.ntime]).toEqual(['10:05', '10:00'])
    expect(five.ends).toEqual(full.ends)
  })

  it('концы блокировки — только ПОЗЖЕ начала, и обеденного часа среди них нет', () => {
    /* ⚠️ При обеде 13–14 закончить блокировку в 14:00 нельзя: обеденный час
       выпал из `day_slots`, а значит и из `note_ends`. Правило сервера, а не
       недосмотр списка. */
    expect(slotTimes('12:00', 0, ENDS).ends).toEqual([13, 15, 16, 17, 18])
    expect(slotTimes('17:00', 0, ENDS).ends).toEqual([18])
    /* последний час дня: кончить блокировку нечем — кнопка запирается */
    expect(slotTimes('18:00', 0, ENDS).ends).toEqual([])
  })

  it('час ячейки канвы называется так же, как его печатал сервер', () => {
    expect([hourLabel(9), hourLabel(13)]).toEqual(['09:00', '13:00'])
  })
})

/* Свободные отрезки часа по блокам колонки: по ним ячейка канвы решает, звать
   ли «+ Programare» и с какой минуты открыть окно. */
describe('свободные отрезки часа — подсказка по канве', () => {
  const b = (min: number, dur: number, busy = true, id = 1): Occupies => ({ id, min, dur, busy })
  /* час 14 стенда: 14:00 на 10 минут, 14:20 на 5, 14:40 на 15 */
  const BUSY = [b(840, 10, true, 1), b(860, 5, true, 2), b(880, 15, true, 3)]

  it('пустой час — один отрезок на весь час; занятый целиком — ни одного', () => {
    expect(freeSpans([], 9)).toEqual([{ from: 0, to: 60 }])
    expect(freeSpans([b(540, 60)], 9)).toEqual([])
  })

  it('обе половины задеты визитами, а дыра 14:10–14:20 — свободный отрезок', () => {
    expect(freeSpans(BUSY, 14)).toEqual([
      { from: 10, to: 20 }, { from: 25, to: 40 }, { from: 55, to: 60 }])
  })

  it('визит на 45 минут оставляет хвост часа; визит с прошлого часа — его конец', () => {
    expect(freeSpans([b(540, 45)], 9)).toEqual([{ from: 45, to: 60 }])
    expect(freeSpans([b(510, 60)], 9)).toEqual([{ from: 30, to: 60 }])
  })

  it('незанятый блок (отменённый, не пришёл) отрезок не отнимает; соседний час — тоже', () => {
    expect(freeSpans([b(540, 60, false)], 9)).toEqual([{ from: 0, to: 60 }])
    expect(freeSpans([b(600, 60)], 9)).toEqual([{ from: 0, to: 60 }])
  })

  it('отрезок под минутой, а на занятом месте — ближайший', () => {
    const spans = freeSpans(BUSY, 14)
    expect(spanAt(spans, 12)).toEqual({ from: 10, to: 20 })
    expect(spanAt(spans, 5)).toEqual({ from: 10, to: 20 })
    expect(spanAt(spans, 50)).toEqual({ from: 55, to: 60 })
    expect(spanAt([], 10)).toBeNull()
  })

  it('минута окна — деление щелчка, но внутри свободного отрезка', () => {
    const spans = freeSpans(BUSY, 14)
    /* дыра 14:10–14:20 короче двух делений обычного шага: запись встаёт в её
       начало, куда бы в ней ни щёлкнули */
    expect([12, 17].map((at) => startIn(spans, at, 15))).toEqual([10, 10])
    /* на крупном шаге в той же дыре два деления — решает место щелчка */
    expect([12, 17].map((at) => startIn(spans, at, 5))).toEqual([10, 15])
    expect(startIn(spans, 38, 5)).toBe(35)
    expect(startIn(spans, 59, 15)).toBe(55)
    /* длинный отрезок: деление щелчка, но не раньше его начала */
    const tail = freeSpans([b(840, 20)], 14)
    expect([22, 31, 59].map((at) => startIn(tail, at, 15))).toEqual([20, 30, 45])
    /* щелчок по занятому месту — ближайший отрезок */
    expect(startIn(spans, 5, 15)).toBe(10)
    /* с клавиатуры координаты нет — первый свободный старт часа */
    expect(startIn(spans, null, 15)).toBe(10)
    expect(startIn([], 10, 15)).toBeNull()
  })
})

describe('минуты часа и их занятость — то, что нужно окнам', () => {
  const b = (min: number, dur: number, busy = true, id = 1): Occupies => ({ id, min, dur, busy })

  it('шаг 5 — двенадцать стартов часа; шаг 15 — четыре', () => {
    expect(hourMinutes(5)).toEqual([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
    expect(hourMinutes(15)).toEqual([0, 15, 30, 45])
  })

  it('занят старт, с которого визит ЭТОЙ длины задевает соседа', () => {
    /* сосед 09:20–09:35: пятиминутный встаёт в 09:15 и в 09:35, получасовой —
       только после него */
    const items = [b(560, 15)]
    expect([...takenMinutes([items], 9, 5, 5)]).toEqual([20, 25, 30])
    expect([...takenMinutes([items], 9, 30, 5)]).toEqual([0, 5, 10, 15, 20, 25, 30])
  })

  it('сосед из следующего часа занимает концы этого', () => {
    expect([...takenMinutes([[b(600, 30)]], 9, 15, 5)]).toEqual([50, 55])
  })

  it('завершённый блок и сам переносимый визит — не помеха', () => {
    expect(takenMinutes([[b(540, 60, false)]], 9, 30, 5).size).toBe(0)
    expect(takenMinutes([[b(540, 60, true, 7)]], 9, 30, 5, 7).size).toBe(0)
    expect(takenMinutes([[b(540, 60, true, 7)]], 9, 30, 5).size).toBe(12)
  })
})
