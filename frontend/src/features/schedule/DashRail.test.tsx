import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashRail } from './DashRail'
import { sparkPoints } from '../../utils/chart'
import type {
  DashAgenda, DashAgendaItem, DashMiniCal, DashOccupancy, DashTile,
} from './dash'

/* Правая колонка панели. Фикстуры ТОЛЬКО этих проверок. */

const NOW = new Date(2026, 8, 19, 11, 30).getTime()
const SERIES = [0, 1, 2, 3, 2, 4, 5, 3, 2, 6, 4, 3, 7, 5]

function cell(day: number, over: Partial<DashMiniCal['weeks'][0][0]> = {}) {
  const date = `2026-09-${String(day).padStart(2, '0')}`
  return { date, day, other: false, today: false, selected: false,
    href: `/admin?date=${date}`, ...over }
}

const MINICAL: DashMiniCal = {
  title: 'Septembrie 2026',
  weekdays: ['Lu', 'Ma', 'Mi', 'Jo', 'Vi', 'Sâ', 'Du'],
  weeks: [
    [
      /* ⚠️ Хвост прошлого месяца, и он же СЕГОДНЯ: две метки складываются */
      { ...cell(31), date: '2026-08-31', other: true, today: true },
      cell(1), cell(2), cell(3), cell(4), cell(5), cell(6),
    ],
    [cell(7), cell(8), cell(9), cell(10), cell(11), cell(12), cell(13, { selected: true })],
  ],
  prev: { date: '2026-08-01', href: '/admin?date=2026-08-01' },
  next: { date: '2026-10-01', href: '/admin?date=2026-10-01' },
}

function item(over: Partial<DashAgendaItem> = {}): DashAgendaItem {
  return {
    id: 1, time: '09:00', dur: 60, name: 'Ion Popa', service: 'Consultație',
    status: 'confirmed', badge: { cls: 'act', label: 'Confirmată' }, urgent: false,
    bar: 'var(--green)', state: 'future', clickable: true, patient_id: 17,
    wait_since: null, ...over,
  }
}

const AGENDA: DashAgenda = {
  count: 3,
  today: true,
  items: [
    item({ id: 1, state: 'past', badge: { cls: 'off', label: 'Finalizată' } }),
    item({
      id: 2, time: '10:00', name: 'Maria Rusu', status: 'waiting',
      badge: { cls: 'wai', label: 'Așteaptă' }, wait_since: NOW - 20 * 60_000,
      state: 'current',
    }),
    /* ⛔ Легаси-строка без пациента: кнопки одонтограммы у неё быть не должно */
    item({ id: 3, time: '11:00', name: 'Vasile Lupu', patient_id: null, urgent: true,
      badge: { cls: 'bad', label: 'Urgent' } }),
  ],
}

function tile(over: Partial<DashTile> = {}): DashTile {
  return {
    key: 'total', label: 'Programări', value: 7, icon: 'cal',
    soft: 'var(--green-soft)', tone: 'var(--green)', filter: '',
    href: '/admin/all?date=2026-09-19', cls: '',
    sub: { kind: 'delta', diff: 2, dir: 'up', text: 'față de ieri' },
    series: SERIES, ...over,
  }
}

const TILES: DashTile[] = [
  tile(),
  tile({ key: 'rec', label: 'Recepție', value: 4, icon: 'headset', filter: 'rec',
    href: '/admin/all?date=2026-09-19&f=rec',
    sub: { kind: 'same', diff: 0, dir: null, text: 'la fel ca ieri' } }),
  tile({ key: 'urg', label: 'Urgențe', value: 1, icon: 'alarm', filter: 'urg', cls: 'warn',
    href: '/admin/all?date=2026-09-19&f=urg',
    sub: { kind: 'static', text: 'intercalate azi' } }),
  /* ⛔ Неявки: рост — стрелка ВВЕРХ и класс `dn` (красный). Полярность
     считает сервер, и она обратная. */
  tile({ key: 'noshow', label: 'Neprezentări', value: 3, icon: 'ban', filter: 'noshow',
    cls: 'bad', href: '/admin/all?date=2026-09-19&f=noshow',
    sub: { kind: 'delta', diff: 2, dir: 'dn', text: 'față de ieri' } }),
]

const OCC: DashOccupancy = {
  label: 'Grad de ocupare', icon: 'trend',
  soft: 'var(--violet-soft)', tone: 'var(--violet)',
  value: 86, series: SERIES,
  from: { label: 'ieri', value: '70%' }, to: { label: 'azi', value: '86%' },
  dir: 'up',
}

const show = (over: Partial<Parameters<typeof DashRail>[0]> = {}) => render(
  <DashRail minical={MINICAL} agenda={AGENDA} tiles={TILES} occupancy={OCC}
    date="2026-09-19" waitTick={NOW} onCard={onCard} fresh={NO_FRESH} {...over} />)

/** Пустая пометка: подсветка приехавшего — дело экрана, рельс её получает. */

const NO_FRESH: ReadonlySet<number> = new Set()

const onCard = vi.fn()

afterEach(cleanup)

describe('C26.5.2: мини-календарь', () => {
  it('⛔ три метки НЕЗАВИСИМЫ и складываются', () => {
    /* Склей их в одно поле — и сегодняшний день в хвосте прошлого месяца
       перестанет подсвечиваться как сегодняшний. */
    show()
    const first = document.querySelector('.mcal td a') as HTMLElement
    expect(first.className).toBe('oth tdy')
    expect(document.querySelector('.mcal .seld')?.textContent).toBe('13')
  })

  it('недель столько, сколько прислал сервер, и шапка из его же слов', () => {
    /* ⚠️ Недель бывает ПЯТЬ или шесть — это не константа. */
    show()
    expect(document.querySelectorAll('.mcal tr').length).toBe(1 + MINICAL.weeks.length)
    expect(Array.from(document.querySelectorAll('.mcal th')).map((t) => t.textContent))
      .toEqual(['Lu', 'Ma', 'Mi', 'Jo', 'Vi', 'Sâ', 'Du'])
    expect(document.querySelector('.mhead b')?.textContent).toBe('Septembrie 2026')
  })

  it('соседние месяцы ведут на ПЕРВОЕ число', () => {
    /* ⛔ «31 марта минус месяц» не существует, и адрес на «31 февраля» открыл
       бы не тот месяц или отказ. */
    show()
    const links = document.querySelectorAll('.mhead a')
    expect(links[0]?.getAttribute('href')).toBe('/admin?date=2026-08-01')
    expect(links[1]?.getAttribute('href')).toBe('/admin?date=2026-10-01')
  })
})

describe('C26.5.2: повестка дня', () => {
  it('пустой день — ДРУГОЕ дерево, а не пустой список', () => {
    show({ agenda: { count: 0, today: true, items: [] } })
    expect(document.querySelector('.agenda .hint')?.textContent).toBe('— nicio programare —')
    expect(document.querySelector('.ag-l')).toBeNull()
    expect(document.querySelector('.ag-all')).toBeNull()
    expect(document.querySelector('.ag-h span')).toBeNull()
  })

  it('счётчик, порядок строк и ссылка в список ЭТОГО дня', () => {
    show()
    expect(document.querySelector('.ag-h span')?.textContent).toBe('3 programări')
    expect(Array.from(document.querySelectorAll('.ag-t')).map((t) => t.textContent))
      .toEqual(['09:00', '10:00', '11:00'])
    expect(document.querySelector('.ag-all')?.getAttribute('href'))
      .toBe('/admin/all?date=2026-09-19')
  })

  it('приглушается только ПРОШЕДШЕЕ, и бейдж приходит с сервера', () => {
    show()
    const rows = Array.from(document.querySelectorAll('.ag-i'))
    expect(rows.map((r) => r.className)).toEqual(['ag-i past', 'ag-i', 'ag-i'])
    expect(rows.map((r) => r.querySelector('.pl-badge')?.className))
      .toEqual(['pl-badge off', 'pl-badge wai', 'pl-badge bad'])
    expect(rows.map((r) => r.querySelector('.pl-badge')?.textContent))
      .toEqual(['Finalizată', 'Așteaptă', 'Urgent'])
  })

  it('⛔ кнопка одонтограммы — ТОЛЬКО у визита с пациентом', () => {
    /* У легаси-строки без пациента ссылка вела бы на `/admin/patient/None/`. */
    show()
    const odo = Array.from(document.querySelectorAll('.ag-i'))
      .map((r) => r.querySelector('.ag-odo')?.getAttribute('href') ?? null)
    expect(odo).toEqual([
      '/admin/patient/17/odontograma', '/admin/patient/17/odontograma', null,
    ])
  })

  it('минуты ожидания считает браузер, и только там, где есть отметка', () => {
    show()
    const waits = Array.from(document.querySelectorAll('.ag-i'))
      .map((r) => r.querySelector('.wait-min')?.textContent ?? null)
    expect(waits).toEqual([null, 'așteaptă 20 min', null])
    expect(document.querySelector('.wait-min')?.className).toBe('wait-min long')
  })
})

describe('C26.5.2: плитки «Azi» и тренды', () => {
  it('плиток столько, сколько прислал сервер: «Prin bot» может не быть вовсе', () => {
    /* ⛔ Фиксированные пять позиций дали бы React дыру на месте четвёртой, и
       он честно нарисовал бы пустую плитку там, где её нет на старом экране. */
    show()
    expect(Array.from(document.querySelectorAll('.rk-i .rk-l')).map((x) => x.textContent))
      .toEqual(['Programări', 'Recepție', 'Urgențe', 'Neprezentări'])
    cleanup()
    show({ tiles: [...TILES, tile({ key: 'bot', label: 'Prin bot', icon: 'bot', value: 2,
      sub: { kind: 'bot_new', new: 3, text: 'azi' } })] })
    expect(document.querySelectorAll('.rk-i').length).toBe(5)
  })

  it('число на плитке ведёт в список, из которого оно посчитано', () => {
    /* ⭐ Самый дешёвый пин, которого не было: число и адрес проверялись
       порознь, а СВЯЗЬ — ничем. */
    show()
    const links = Array.from(document.querySelectorAll('.rk-i'))
      .map((a) => [a.querySelector('.rk-l')?.textContent, a.getAttribute('href')])
    expect(links).toEqual([
      ['Programări', '/admin/all?date=2026-09-19'],
      ['Recepție', '/admin/all?date=2026-09-19&f=rec'],
      ['Urgențe', '/admin/all?date=2026-09-19&f=urg'],
      ['Neprezentări', '/admin/all?date=2026-09-19&f=noshow'],
    ])
  })

  it('⛔ у неявок стрелка ВВЕРХ, а цвет КРАСНЫЙ: знак и полярность — разное', () => {
    /* Возьми цвет из знака разницы — и рост неявок позеленел бы. Молча:
       цифра при этом верная и меняется правильно. */
    show()
    const noshow = document.querySelectorAll('.rk-i')[3]!
    const colored = noshow.querySelector('.trend > span')!
    expect(colored.className).toBe('dn')
    expect(colored.textContent).toContain('+2')
    expect(noshow.className).toBe('rk-i bad')

    const total = document.querySelectorAll('.rk-i')[0]!
    expect(total.querySelector('.trend > span')?.className).toBe('up')
  })

  it('четыре формы подписи остаются четырьмя', () => {
    show({ tiles: [...TILES, tile({ key: 'bot', label: 'Prin bot', icon: 'bot',
      sub: { kind: 'bot_new', new: 3, text: 'azi' } })] })
    const subs = Array.from(document.querySelectorAll('.rk-i .trend'))
      .map((s) => s.textContent?.replace(/\s+/g, ' ').trim())
    expect(subs).toEqual([
      '+2 față de ieri', 'la fel ca ieri', 'intercalate azi', '+2 față de ieri',
      '3 noi azi',
    ])
    /* у «столько же» и у статичной подписи цветного span нет вовсе */
    expect(document.querySelectorAll('.rk-i')[1]!.querySelector('.trend > span')).toBeNull()
    expect(document.querySelectorAll('.rk-i')[2]!.querySelector('.trend > span')).toBeNull()
  })
})

describe('C26.5.2: загрузка кресел', () => {
  it('говорит «было → стало», а не разницу в пунктах', () => {
    /* ⚠️ Процентные пункты пришлось объяснять даже директору. */
    show()
    const occ = document.querySelector('.rk-occ')!
    expect(occ.querySelector('.trend')?.textContent?.replace(/\s+/g, ' ').trim())
      .toBe('ieri 70% › azi 86%')
    expect(occ.querySelector('b')?.textContent).toBe('86%')
  })

  it('закрытый вчера день говорит «închis», а не «0%»', () => {
    /* ⛔ Ноль процентов — это «работали и простояли», и на выходном он
       читался бы как провал. */
    show({ occupancy: { ...OCC, from: { label: 'ieri', value: 'închis' }, dir: null } })
    const occ = document.querySelector('.rk-occ')!
    expect(occ.querySelector('.trend')?.textContent).toContain('închis')
    /* при равенстве стрелки нет вовсе */
    expect(occ.querySelector('.trend > span')).toBeNull()
  })
})

describe('C26.5.2: спарклайн', () => {
  it('четырнадцать точек, нормировка по СВОЕМУ максимуму', () => {
    const pts = sparkPoints(SERIES).split(' ')
    expect(pts.length).toBe(14)
    expect(pts[0]).toBe('0.0,23.0')          // ноль — по полу
    expect(pts[12]).toBe('92.3,3.0')         // максимум ряда — под потолком
  })

  it('⛔ две недели нулей — РОВНАЯ ЛИНИЯ ПО ПОЛУ, а не пустое место', () => {
    /* Две недели без единой записи говорят ровно столько же, сколько две
       недели с записями, и график обязан это сказать. */
    const pts = sparkPoints([0, 0, 0, 0]).split(' ')
    expect(pts.every((p) => p.endsWith(',23.0'))).toBe(true)
  })

  it('пустой ряд — это другое: графика нет вовсе', () => {
    expect(sparkPoints([])).toBe('')
    show({ tiles: [tile({ series: [] })] })
    expect(document.querySelector('.rk-i .spark')).toBeNull()
  })

  it('заливка замкнута снизу, а линия не масштабирует штрих', () => {
    /* ⛔ Без `vector-effect` `preserveAspectRatio="none"` размазал бы штрих
       вместе с координатами. */
    show()
    const svg = document.querySelector('.rk-i .spark')!
    expect(svg.getAttribute('viewBox')).toBe('0 0 100 26')
    expect(svg.querySelector('.sp-a')?.getAttribute('points')).toMatch(/^0,26 .* 100,26$/)
    expect(svg.querySelector('.sp-l')?.getAttribute('vector-effect')).toBe('non-scaling-stroke')
  })
})

describe('C26.5.4: цифра считает от нуля, но истина — значение', () => {
  const anim = (on: boolean) => document.documentElement.classList.toggle('anim', on)
  const num = () => document.querySelector('.rk-i b')
  afterEach(() => { anim(false); vi.unstubAllGlobals() })

  it('без класса `anim` цифра статична: перепоказ после действия не считает', () => {
    /* Класс снимает каркас на 303-повторе и React — на первом же обновлении.
       Считать в этот момент значило бы мигать цифрой на каждое действие. */
    anim(false)
    show()
    expect(num()?.textContent).toBe('7')
  })

  it('⭐ с `anim` цифра идёт от нуля и приходит РОВНО к значению', async () => {
    anim(true)
    show()
    expect(num()?.textContent).toBe('0')
    await waitFor(() => expect(num()?.textContent).toBe('7'))
  })

  it('⛔ `data-count` равен значению ВСЕГДА — атрибут и есть контракт', () => {
    /* У легаси проверки разбирают атрибут, а не текст, и это записано: текст
       во время счёта врёт по замыслу, атрибут — никогда. */
    anim(true)
    show()
    expect(num()?.getAttribute('data-count')).toBe('7')
    expect(num()?.textContent).toBe('0')
  })

  it('⛔ приехавшее конвертом значение показывается СРАЗУ, без счёта', async () => {
    anim(true)
    const { rerender } = show()
    await waitFor(() => expect(num()?.textContent).toBe('7'))
    rerender(
      <DashRail minical={MINICAL} agenda={AGENDA} occupancy={OCC}
        tiles={[{ ...TILES[0]!, value: 40 }, ...TILES.slice(1)]}
        date="2026-09-19" waitTick={NOW} onCard={onCard} fresh={NO_FRESH} />)
    expect(num()?.textContent).toBe('40')
  })

  it('⚠️ ноль и единица не считаются: это мигание, а не движение', () => {
    anim(true)
    show({ tiles: [{ ...TILES[0]!, value: 1 }, ...TILES.slice(1)] })
    expect(num()?.textContent).toBe('1')
  })

  it('⭐ просьбу системы уменьшить движение цифра УВАЖАЕТ', () => {
    /* ⚠️ Расхождение с легаси, названное вслух: там счётчик живёт в JS и про
       `prefers-reduced-motion` не знает вовсе, хотя оформление знает. */
    anim(true)
    vi.stubGlobal('matchMedia', (q: string) => ({
      matches: q.includes('reduce'), media: q, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {},
      dispatchEvent: () => false,
    }))
    show()
    expect(num()?.textContent).toBe('7')
  })

  it('процент занятости считает так же и со своим знаком', async () => {
    anim(true)
    show()
    const occ = () => document.querySelector('.rk-occ b')
    expect(occ()?.textContent).toBe('0%')
    await waitFor(() => expect(occ()?.textContent).toBe('86%'))
    expect(occ()?.getAttribute('data-count')).toBe('86')
  })
})
