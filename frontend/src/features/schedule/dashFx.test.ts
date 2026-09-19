import { describe, expect, it } from 'vitest'
import { CELL_MAX, CELL_MIN, cellPx, clinicNow, nowlineRows, waitLabel } from './dashFx'

describe('dashFx — высота часа', () => {
  it('держится между полом и потолком', () => {
    /* ⛔ Пол 66 задаёт высоту блока, и ниже него двустрочная запись
       схлопывается в одну строку (замер 08-17). Потолок 96 не даёт рельсу
       раздуть час у клиники с коротким днём. */
    expect(cellPx(10, 8)).toBe(CELL_MIN)
    expect(cellPx(100_000, 8)).toBe(CELL_MAX)
    expect(cellPx(744, 10)).toBe(74)
  })

  it('ИДЕМПОТЕНТНА: второй расчёт не двигает час', () => {
    /* ⭐ То самое, на чём обжигались: замерив зазор ПОСЛЕ растяжения, получаешь
       обратную связь, и час подрастает на пиксель за каждый вызов. */
    const once = cellPx(744, 9)
    expect(cellPx(744, 9)).toBe(once)
    expect(cellPx(9 * once, 9)).toBe(once)
  })

  it('поправка на переполнение не пробивает пол', () => {
    expect(cellPx(744, 9, 100_000)).toBe(CELL_MIN)
    expect(cellPx(744, 9, 0)).toBeGreaterThan(CELL_MIN)
  })
})

describe('dashFx — минуты ожидания', () => {
  const t0 = 1_758_000_000_000
  const ago = (min: number) => t0 - min * 60_000

  it('первые пять минут — молчание', () => {
    /* «Пришёл и почти сразу позвали» ожиданием не считается, а «așteaptă
       0 min» на каждом пришедшем — шум (Олег 08-21). */
    expect(waitLabel(ago(0), t0)).toBeNull()
    expect(waitLabel(ago(4), t0)).toBeNull()
  })

  it('с пяти минут говорит, с пятнадцати — тревожно', () => {
    expect(waitLabel(ago(5), t0)).toEqual({ text: 'așteaptă 5 min', long: false })
    expect(waitLabel(ago(14), t0)).toEqual({ text: 'așteaptă 14 min', long: false })
    expect(waitLabel(ago(15), t0)).toEqual({ text: 'așteaptă 15 min', long: true })
  })

  it('отметка из будущего не даёт отрицательных минут', () => {
    expect(waitLabel(t0 + 60_000, t0)).toBeNull()
  })
})

describe('dashFx — линия «сейчас»', () => {
  const at = { day: '2026-09-19', hh: 11, mm: 30 }

  it('стоит на своём часе плюс доля минут', () => {
    expect(nowlineRows([9, 10, 11, 12], '2026-09-19', at)).toBe(2.5)
  })

  it('⛔ считает по НОМЕРУ часа, а не по расстоянию от начала дня', () => {
    /* День со сдвинутым графиком: крайние закрытые часы срезаны в полоски.
       «Час минус первый час» дал бы 2 вместо 1 — линия встала бы этажом ниже. */
    expect(nowlineRows([10, 11, 12], '2026-09-19', at)).toBe(1.5)
  })

  it('в чужом дне и вне сетки линии нет', () => {
    expect(nowlineRows([9, 10, 11], '2026-09-18', at)).toBeNull()
    expect(nowlineRows([9, 10], '2026-09-19', at)).toBeNull()
  })
})

describe('dashFx — часы КЛИНИКИ, а не устройства', () => {
  it('день и час берутся в названном поясе', () => {
    /* В облаке через туннель браузер живёт в своём поясе, и линия по часам
       устройства стояла бы на чужом часе. */
    const at = new Date(Date.UTC(2026, 8, 19, 21, 30))
    expect(clinicNow('Europe/Chisinau', at)).toEqual({ day: '2026-09-20', hh: 0, mm: 30 })
    expect(clinicNow('UTC', at)).toEqual({ day: '2026-09-19', hh: 21, mm: 30 })
  })

  it('незнакомый пояс не роняет экран — берутся часы устройства', () => {
    const at = new Date(2026, 8, 19, 8, 5)
    expect(clinicNow('Nowhere/Nothing', at))
      .toEqual({ day: '2026-09-19', hh: 8, mm: 5 })
  })
})
