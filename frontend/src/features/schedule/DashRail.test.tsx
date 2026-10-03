import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashRail } from './DashRail'
import { Spark } from '../../components/Spark'
import { sparkPoints } from '../../utils/chart'
import type {
  DashAgenda, DashAgendaItem, DashMiniCal, DashOccupancy, DashTile,
} from './dash'
import type { Desk } from './desk'

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
    wait_since: null, comment: '', ...over,
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

/* «La recepție» (01.10): списки стойки из того же конверта */
const DESK: Desk = {
  confirm: {
    day: 'mâine', date: '2026-09-21', n: 3, n_ok: 1, n_left: 1,
    items: [
      { id: 11, pid: 17, time: '09:00', name: 'Ana Suna', phone: '069111222', doctor: 'Dr. Ion', service: 'Consultație', call: '', call_at: '', call_by: '' },
      { id: 12, pid: 18, time: '10:00', name: 'Nu Raspunde', phone: '069111333', doctor: 'Dr. Ion', service: 'Consultație', call: 'noanswer', call_at: '09:41', call_by: 'Recepție' },
      { id: 13, pid: 19, time: '11:00', name: 'Gata Confirmat', phone: '', doctor: 'Dr. Ana', service: 'Igienizare', call: 'ok', call_at: '09:30', call_by: 'Recepție' },
    ],
  },
  unscheduled: { items: [{ pid: 20, name: 'Plan Fara', phone: '069111444', n: 2, total: 9000, total_s: '9 000', days: 12 }], n: 9, sum_s: '41 300' },
  collect: {
    items: [{ pid: 21, name: 'Datornic', time: '08:30', status: 'done', status_label: 'finalizată', debt: 300, debt_s: '300' }],
    n: 1, sum_s: '300',
    cash: { total_s: '1 700', parts: [{ method: 'numerar', sum_s: '1 200' }, { method: 'card', sum_s: '500' }] },
    casa_href: '/admin/casa?d=2026-09-19',
  },
  free: [
    { dk: 'd2', name: 'Dr. Ion', when: 'azi 11:00', today: true, href: '/admin?date=2026-09-19' },
    { dk: 'd3', name: 'Dr. Ana', when: 'mâine 09:00', today: false, href: '/admin?date=2026-09-21' },
  ],
}

const show = (over: Partial<Parameters<typeof DashRail>[0]> = {}) => render(
  <DashRail minical={MINICAL} agenda={AGENDA} tiles={TILES} occupancy={OCC} desk={DESK}
    date="2026-09-19" waitTick={NOW} busy={false} onCard={onCard} onCall={onCall} fresh={NO_FRESH} {...over} />)

/** Пустая пометка: подсветка приехавшего — дело экрана, рельс её получает. */

const NO_FRESH: ReadonlySet<number> = new Set()

const onCard = vi.fn()
const onCall = vi.fn()

afterEach(() => { cleanup(); onCall.mockClear() })

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

  it('значок «есть комментарий» — только у визита с комментарием, текст в подсказке (03.10)', () => {
    show({ agenda: { count: 2, today: true, items: [
      item({ id: 1, comment: 'alergie la penicilină' }),
      item({ id: 2, time: '10:00' }),
    ] } })
    const rows = Array.from(document.querySelectorAll('.ag-i'))
    expect(rows[0]?.querySelector('.ag-cmt')?.getAttribute('title'))
      .toBe('Comentariu: alergie la penicilină')
    expect(rows[0]?.querySelector('.ag-cmt svg')).toBeTruthy()
    expect(rows[1]?.querySelector('.ag-cmt')).toBeNull()
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

describe('01.10: «La recepție» — списки стойки', () => {
  it('порядок колонки: календарь, повестка, списки (слово Олега 28.09)', () => {
    const { container } = show()
    expect(Array.from(container.children).map((e) => e.className)).toEqual(['mcal', 'agenda', 'desk'])
  })

  it('цифры дня — одной строкой в шапке; плиток «Azi» больше нет', () => {
    show()
    expect(document.querySelector('.dk-h small')?.textContent)
      .toBe('Azi: 7 programări · 1 urgențe · 3 nu au venit · ocupare 86%')
    expect(document.querySelector('.rk-i')).toBeNull()
  })

  it('De încasat azi и касса — только когда сервер их дал (PERM_MONEY); регистратура без них', () => {
    show()
    expect(screen.getByText('De încasat azi')).toBeTruthy()
    const cash = document.querySelector('.dk-cash') as HTMLElement
    expect(cash.textContent).toContain('1 700 MDL')
    expect(cash.textContent).toContain('numerar 1 200 · card 500')
    expect((cash.querySelector('a') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/casa?d=2026-09-19')
    cleanup()
    show({ desk: { ...DESK, collect: null } })
    expect(screen.queryByText('De încasat azi')).toBeNull()
    expect(document.querySelector('.dk-cash')).toBeNull()
  })

  it('De confirmat: «осталось из», отметки словами, кнопки по состоянию, команда с id и результатом', () => {
    show()
    const sec = screen.getByText(/De confirmat mâine/).closest('.dk-sec') as HTMLElement
    expect(sec.querySelector('.dk-cnt')?.textContent).toBe('1 din 3')
    const rows = Array.from(sec.querySelectorAll('.dk-row')) as HTMLElement[]
    expect(rows.map((r) => r.className)).toEqual(['dk-row', 'dk-row', 'dk-row done'])
    fireEvent.click(within(rows[0]!).getByRole('button', { name: 'Confirmat: Ana Suna' }))
    expect(onCall).toHaveBeenCalledWith(11, 'ok')
    fireEvent.click(within(rows[0]!).getByRole('button', { name: 'Nu răspunde: Ana Suna' }))
    expect(onCall).toHaveBeenCalledWith(11, 'noanswer')
    /* не ответил: отметка словами; снять можно, подтвердить — тоже */
    expect(rows[1]!.textContent).toContain('nu răspunde 09:41')
    expect(within(rows[1]!).getByRole('button', { name: 'Anulează bifa: Nu Raspunde' })).toBeTruthy()
    expect(within(rows[1]!).getByRole('button', { name: 'Confirmat: Nu Raspunde' })).toBeTruthy()
    /* подтверждён: только снять */
    expect(within(rows[2]!).getAllByRole('button').map((b) => b.getAttribute('aria-label')))
      .toEqual(['Anulează bifa: Gata Confirmat'])
    fireEvent.click(within(rows[2]!).getByRole('button', { name: /Anulează bifa/ }))
    expect(onCall).toHaveBeenCalledWith(13, '')
    cleanup()
    show({ desk: { ...DESK, confirm: { ...DESK.confirm, n_left: 0 } } })
    expect(document.querySelector('.dk-cnt.green')?.textContent).toBe('toți 3')
    cleanup()
    show({ busy: true })
    expect(screen.getByRole('button', { name: 'Confirmat: Ana Suna' })).toHaveProperty('disabled', true)
  })

  it('Primul loc liber: сегодняшнее окно зелёным и ссылкой в день; Plan fără programare — «încă N»', () => {
    show()
    const free = screen.getByText('Primul loc liber').closest('.dk-sec') as HTMLElement
    const links = Array.from(free.querySelectorAll('a.dk-when')) as HTMLAnchorElement[]
    expect(links.map((a) => [a.textContent, a.className, a.getAttribute('href')])).toEqual([
      ['azi 11:00', 'dk-when today', '/admin?date=2026-09-19'],
      ['mâine 09:00', 'dk-when', '/admin?date=2026-09-21'],
    ])
    const plan = screen.getByText('Plan fără programare').closest('.dk-sec') as HTMLElement
    expect(plan.textContent).toContain('9 000 MDL')
    expect(plan.textContent).toContain('2 proc. · de 12 zile')
    expect(plan.querySelector('.dk-more')?.textContent).toBe('încă 8 ›')
    expect(plan.querySelector('.dk-cnt')?.textContent).toBe('9')
    cleanup()
    show({ desk: { ...DESK, unscheduled: { items: [], n: 0, sum_s: '0' },
      confirm: { ...DESK.confirm, n: 0, items: [] } } })
    expect(screen.queryByText('Plan fără programare')).toBeNull()
    expect(screen.queryByText(/De confirmat/)).toBeNull()
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
    render(<Spark series={[]} tone="var(--teal)" />)
    expect(document.querySelector('.spark')).toBeNull()
  })

  it('заливка замкнута снизу, а линия не масштабирует штрих', () => {
    /* ⛔ Без `vector-effect` `preserveAspectRatio="none"` размазал бы штрих
       вместе с координатами. */
    render(<Spark series={SERIES} tone="var(--teal)" />)
    const svg = document.querySelector('.spark')!
    expect(svg.getAttribute('viewBox')).toBe('0 0 100 26')
    expect(svg.querySelector('.sp-a')?.getAttribute('points')).toMatch(/^0,26 .* 100,26$/)
    expect(svg.querySelector('.sp-l')?.getAttribute('vector-effect')).toBe('non-scaling-stroke')
  })
})
