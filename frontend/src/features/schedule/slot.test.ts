import { describe, expect, it } from 'vitest'
import { freeHalves, freeKind, hourLabel, slotTimes } from './slot'
import type { Occupies } from './move'

/* Времена пустого часа. Проверка отвечает на ОДИН вопрос — что двигает
   переключатель получаса, — и ответ у неё тот же, что у сервера: время записи
   двигает, час заметки и её концы не трогает. */

/* День клиники 9–18 с обедом 13–14: концы блокировки идут подряд и 14:00
   среди них НЕТ. Это не дыра в фикстуре — так их считает `pday.note_ends`. */
const ENDS = [10, 11, 12, 13, 15, 16, 17, 18]

describe('C26.5.3-c: получас двигает ОДНО время из двух', () => {
  it('ровный час: запись в 10:00, заметка с 10:00 и до 11:00', () => {
    const t = slotTimes('10:00', 0, ENDS)
    expect(t.atime).toBe('10:00')
    expect(t.ntime).toBe('10:00')
    expect(t.ends[0]).toBe(11)
  })

  it('⛔ получас меняет ТОЛЬКО atime — интервал заметки не пересчитывается', () => {
    /* Заметка блокирует ЧАСЫ ПРИЁМА, как и ячейки сетки. Уедь `ntime` на
       10:30 — сервер молча округлил бы его вниз (`int(ntime.split(":")[0])`),
       и экран сказал бы «с 10:30», а в базе легла бы блокировка с 10:00. */
    const full = slotTimes('10:00', 0, ENDS)
    const half = slotTimes('10:00', 30, ENDS)
    expect(half.atime).toBe('10:30')
    expect(half.ntime).toBe(full.ntime)
    expect(half.ends).toEqual(full.ends)
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

/* Свободные старты часа по блокам колонки (17.10). ⛔ Половина занята, если
   её задевает ЛЮБОЙ занятый блок: визит 09:00–09:45 забирает обе — слот в
   09:45 канва не предлагает, и подсказка «+ Programare» там не нужна. */
describe('свободные старты часа — подсказка по канве', () => {
  const b = (min: number, dur: number, busy = true, id = 1): Occupies => ({ id, min, dur, busy })

  it('пустой час — оба старта свободны', () => {
    expect(freeHalves([], 9)).toEqual({ h0: true, h30: true })
    expect(freeKind(freeHalves([], 9))).toBe('both')
  })

  it('визит на 45 минут с :00 забирает ОБЕ половины — у ячейки нет старта', () => {
    expect(freeHalves([b(540, 45)], 9)).toEqual({ h0: false, h30: false })
    expect(freeKind(freeHalves([b(540, 45)], 9))).toBe('none')
  })

  it('получас с :30 оставляет верхнюю половину, визит с прошлого часа — нижнюю', () => {
    expect(freeKind(freeHalves([b(570, 30)], 9))).toBe('top')
    /* 08:30 на час кончается в 09:30: занята только первая половина девятого */
    expect(freeKind(freeHalves([b(510, 60)], 9))).toBe('bottom')
  })

  it('незанятый блок (отменённый, не пришёл) старт не отнимает; соседний час — тоже', () => {
    expect(freeKind(freeHalves([b(540, 60, false)], 9))).toBe('both')
    expect(freeKind(freeHalves([b(600, 60)], 9))).toBe('both')
  })

  it('заметка стойки считается как визит — блокировка это и есть занятый час', () => {
    expect(freeKind(freeHalves([b(540, 60, true, 44)], 9))).toBe('none')
  })
})
