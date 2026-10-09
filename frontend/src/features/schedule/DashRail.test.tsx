import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashRail } from './DashRail'
import { Spark } from '../../components/Spark'
import { sparkPoints } from '../../utils/chart'
import type { DashActions, DashAgenda, DashAgendaItem, DashCanvasModel, DashMiniCal } from './dash'
import type { Desk } from './desk'

/* Правая колонка панели. Фикстуры ТОЛЬКО этих проверок. */

const NOW = new Date(2026, 8, 19, 11, 30).getTime()
const SERIES = [0, 1, 2, 3, 2, 4, 5, 3, 2, 6, 4, 3, 7, 5]

function cell(day: number, over: Partial<DashMiniCal['weeks'][0][0]> = {}) {
  const date = `2026-09-${String(day).padStart(2, '0')}`
  return { date, day, other: false, today: false, selected: false, busy: false,
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
    wait_since: null, comment: '',
    doctor: 'Dr. Ion', doctor_id: 'd2', phone: '069 123 456', start_ms: 0, end_ms: 0, end: '10:00', in_at: '', ...over,
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

/* Канва дня — для «Primul loc liber» (08.10). Сейчас 11:30 (NOW): у Dr. Ion
   заметка стойки в 11:00, свободен с 12:00; Dr. Ana заблокирована весь день. */
function note(id: number, top: number, height: number) {
  return { id, kind: 'note' as const, time: '11:00', min: 660, dur: 60 * height, busy: true,
    movable: false, top, height, col: 0, of: 1, title: 'Pauză', text: 'Pauză', label: 'Pauză',
    status: 'confirmed' }
}

const CANVAS: DashCanvasModel = {
  date: '2026-09-19', empty: false, base_min: 540, tight: false,
  hours: [9, 10, 11, 12].map((h) => ({ h, label: `${String(h).padStart(2, '0')}:00`, now: h === 11 })),
  bands: { top: null, bottom: null },
  columns: [
    { key: 'k:d2', id: 'd2', name: 'Dr. Ion', orphan: false, spec: 'Terapie', off: false,
      hue: 'var(--teal)', photo: '', initials: 'DI', count: 1, free: '12:00', occupancy: null,
      title: 'Dr. Ion', cells: [true, true, true, true], relink: null, blocks: [note(1, 2, 1)] },
    { key: 'k:d3', id: 'd3', name: 'Dr. Ana', orphan: false, spec: 'Chirurgie', off: false,
      hue: 'var(--blue)', photo: '', initials: 'DA', count: 0, free: null, occupancy: null,
      title: 'Dr. Ana', cells: [true, true, true, true], relink: null, blocks: [note(2, 0, 4)] },
  ],
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

/* Матрица кнопок исхода — как у сервера (`core/visits._ACT_BUTTONS`): из неё
   и только из неё — слова статусов на вкладках потока и на их кнопках. */
const ACTIONS: DashActions = {
  confirmed: [
    { to: 'waiting', cls: 'b-waiting', label: 'A venit', confirm: '' },
    { to: 'arrived', cls: 'b-arrived', label: 'În cabinet', confirm: '' },
    { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' },
  ],
  waiting: [{ to: 'arrived', cls: 'b-arrived', label: 'În cabinet', confirm: '' }],
  arrived: [{ to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' }],
}

const show = (over: Partial<Parameters<typeof DashRail>[0]> = {}) => render(
  <DashRail minical={MINICAL} agenda={AGENDA} canvas={CANVAS} desk={DESK}
    date="2026-09-19" waitTick={NOW} busy={false} onCard={onCard} onCall={onCall} fresh={NO_FRESH}
    onFlow={onFlow} actions={ACTIONS} onSlot={onSlot} {...over} />)

/** Пустая пометка: подсветка приехавшего — дело экрана, рельс её получает. */

const NO_FRESH: ReadonlySet<number> = new Set()

const onCard = vi.fn()
const onCall = vi.fn()
const onFlow = vi.fn()
const onSlot = vi.fn()

afterEach(() => { cleanup(); onCall.mockClear(); onCard.mockClear(); onFlow.mockClear(); onSlot.mockClear() })

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
    /* 08.10: счётчик в шапке всегда; у СЕГОДНЯ он же — цифра плитки «Toate» */
    show()
    expect(document.querySelector('.ag-h span')?.textContent).toBe('3 programări')
    expect(document.querySelector('.fl-tab.on span')?.textContent).toBe('Toate')
    expect(document.querySelector('.fl-tab.on b')?.textContent).toBe('3')
    cleanup()
    show({ agenda: { ...AGENDA, today: false } })
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
    /* срочность — чипом со значком (макет 08.10), остальное — плашкой сервера */
    expect(rows.map((r) => r.querySelector('.pl-badge, .chip')?.className))
      .toEqual(['pl-badge off', 'pl-badge wai', 'chip urg'])
    expect(rows.map((r) => r.querySelector('.pl-badge, .chip')?.textContent))
      .toEqual(['Finalizată', 'Așteaptă', 'Urgent'])
  })

  it('08.10: кнопка следующего шага на каждой строке — только СЕГОДНЯ, словом из матрицы', () => {
    /* записан → «A venit», пришёл → «În cabinet»; клик — команда, не карточка */
    show()
    expect(Array.from(document.querySelectorAll('.ag-i .ag-next')).map((b) => b.textContent))
      .toEqual(['A venit', 'În cabinet', 'A venit'])
    fireEvent.click(screen.getByRole('button', { name: 'În cabinet: Maria Rusu' }))
    expect(onFlow).toHaveBeenCalledWith(2, 'arrived')
    expect(onCard).not.toHaveBeenCalled()
    cleanup()
    show({ agenda: { ...AGENDA, today: false } })
    expect(document.querySelector('.ag-next')).toBeNull()
    expect(document.querySelectorAll('.ag-odo').length).toBe(2)
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

  it('⛔ кнопка «Consultație» — ТОЛЬКО у визита с пациентом; ведёт в запись приёма ЭТОГО визита, «Înapoi» — в этот день', () => {
    /* 09.10 (слово Олега): вместо «Odontogramă» (зуб уже на блоке сетки) — запись
       приёма визита. У легаси-строки без пациента приёму некуда писаться. */
    show()
    const rows = Array.from(document.querySelectorAll('.ag-i'))
    expect(rows.map((r) => r.querySelector('.ag-odo')?.getAttribute('href') ?? null)).toEqual([
      '/admin/visit/1?back=%2Fadmin%3Fdate%3D2026-09-19', '/admin/visit/2?back=%2Fadmin%3Fdate%3D2026-09-19', null,
    ])
    expect(rows[0]?.querySelector('.ag-odo')?.textContent).toBe('Consultație')
  })

  it('минуты ожидания считает браузер, и только там, где есть отметка', () => {
    show()
    const waits = Array.from(document.querySelectorAll('.ag-i'))
      .map((r) => r.querySelector('.wait-min')?.textContent ?? null)
    expect(waits).toEqual([null, 'așteaptă 20 min', null])
    expect(document.querySelector('.wait-min')?.className).toBe('wait-min long')
  })
})

describe('03.10: поток пациента — вкладки над повесткой (вариант A, слово Олега)', () => {
  /* Сейчас 11:30. Отметки — как шлёт сервер: начало/конец и пришёл — числами,
     часы — готовыми строками. Минуты считает браузер по тику. */
  const T = (h: number, m: number) => new Date(2026, 8, 19, h, m).getTime()
  const appt = (over: Partial<DashAgendaItem>) => item({ end: '', in_at: '', ...over })
  const FLOW: DashAgenda = {
    count: 8, today: true,
    items: [
      appt({ id: 42, time: '10:00', name: 'Over Run', status: 'arrived', doctor: 'Dr. Ana', doctor_id: 'd1',
        start_ms: T(10, 0), end_ms: T(11, 0), end: '11:00', in_at: '10:05' }),
      appt({ id: 21, time: '11:00', name: 'Late Long', status: 'confirmed', doctor: 'Dr. Dan', doctor_id: 'd4',
        phone: '069 000 021', start_ms: T(11, 0), end_ms: T(11, 30) }),
      appt({ id: 32, time: '11:00', name: 'Long Wait', status: 'waiting', wait_since: T(11, 10),
        doctor: 'Dr. Ana', doctor_id: 'd1', start_ms: T(11, 0), end_ms: T(11, 30) }),
      appt({ id: 41, time: '11:00', name: 'On Time', status: 'arrived', doctor: 'Dr. Ion', doctor_id: 'd2',
        start_ms: T(11, 0), end_ms: T(12, 0), end: '12:00', in_at: '11:02' }),
      appt({ id: 23, time: '11:22', name: 'Late Short', status: 'confirmed', doctor: 'Dr. Vlad', doctor_id: 'd3',
        phone: '', start_ms: T(11, 22), end_ms: T(11, 52) }),
      appt({ id: 22, time: '11:27', name: 'Not Yet', status: 'confirmed', doctor: 'Dr. Dan', doctor_id: 'd4',
        start_ms: T(11, 27), end_ms: T(11, 57) }),
      appt({ id: 33, time: '11:45', name: 'Free Doc', status: 'waiting', wait_since: T(11, 22),
        doctor: 'Dr. Vlad', doctor_id: 'd3', start_ms: T(11, 45), end_ms: T(12, 15) }),
      appt({ id: 31, time: '12:00', name: 'Just Came', status: 'waiting', wait_since: T(11, 28),
        doctor: 'Dr. Ion', doctor_id: 'd2', start_ms: T(12, 0), end_ms: T(12, 30) }),
    ],
  }
  const tabs = () => Array.from(document.querySelectorAll('.fl-tab')).map((t) => {
    const b = t.querySelector('b')
    return `${t.querySelector('span')?.textContent} ${b?.textContent}${b?.className ? ` ${b.className}` : ''}`
  })
  const open = (word: string) => fireEvent.click(screen.getByRole('tab', { name: new RegExp(`^${word}`) }))
  const rows = () => Array.from(document.querySelectorAll('.fl-row')).map((r) => ({
    id: r.getAttribute('data-appt'),
    name: r.querySelector('.fl-l1 b')?.textContent,
    chip: `${r.querySelector('.fl-chip')?.textContent} ${r.querySelector('.fl-chip')?.className.replace('fl-chip ', '')}`,
    sub: r.querySelector('.fl-b > small')?.textContent,
    note: r.querySelector('.fl-note')?.textContent?.trim() ?? null,
    over: r.classList.contains('over'),
  }))

  it('вкладки — только у СЕГОДНЯ, с цифрами и цветом: красное ждёт/опаздывает 15+, янтарное — сверх плана', () => {
    show({ agenda: FLOW })
    expect(tabs()).toEqual(['Toate 8', 'Întârzie 2 red', 'A venit 3 red', 'În cabinet 2 amber'])
    expect(screen.getByRole('tab', { name: /^Toate/ }).getAttribute('aria-selected')).toBe('true')
    cleanup()
    show({ agenda: { ...FLOW, today: false } })
    expect(document.querySelector('.fl-tabs')).toBeNull()
  })

  it('⛔ слова статусов — из матрицы сервера, не свои: вкладки и кнопка', () => {
    const other: DashActions = {
      confirmed: [{ to: 'waiting', cls: 'b', label: 'Sosit', confirm: '' }],
      waiting: [{ to: 'arrived', cls: 'b', label: 'La medic', confirm: '' }],
      arrived: [{ to: 'done', cls: 'b', label: 'Gata', confirm: '' }],
    }
    show({ agenda: FLOW, actions: other })
    expect(Array.from(document.querySelectorAll('.fl-tab span')).map((t) => t.textContent))
      .toEqual(['Toate', 'Întârzie', 'Sosit', 'La medic'])
    open('La medic')
    expect(screen.getByRole('button', { name: 'Gata: Over Run' })).toBeTruthy()
  })

  it('Întârzie: с 5-й минуты, красное с 15, врач и телефон; одна кнопка — «A venit»', () => {
    show({ agenda: FLOW })
    open('Întârzie')
    expect(rows()).toEqual([
      { id: '21', name: 'Late Long', chip: '30 min red', sub: 'Dr. Dan · 069 000 021', note: null, over: false },
      { id: '23', name: 'Late Short', chip: '8 min amber', sub: 'Dr. Vlad', note: null, over: false },
    ])
    fireEvent.click(screen.getByRole('button', { name: 'A venit: Late Long' }))
    expect(onFlow).toHaveBeenCalledWith(21, 'waiting')
    expect(onCard).not.toHaveBeenCalled()
    expect(document.querySelectorAll('.fl-row .dk-btn').length).toBe(2)
  })

  it('A venit: «acum» до 5 минут, красное с 15; врач свободен / занят до / сверх плана', () => {
    show({ agenda: FLOW })
    open('A venit')
    expect(rows()).toEqual([
      { id: '32', name: 'Long Wait', chip: '20 min red', sub: 'Dr. Ana', note: 'medicul depășește cu 30 min', over: false },
      { id: '33', name: 'Free Doc', chip: '8 min violet', sub: 'Dr. Vlad', note: 'medicul e liber', over: false },
      { id: '31', name: 'Just Came', chip: 'acum violet', sub: 'Dr. Ion', note: 'medicul e ocupat până la 12:00', over: false },
    ])
    fireEvent.click(screen.getByRole('button', { name: 'În cabinet: Long Wait' }))
    expect(onFlow).toHaveBeenCalledWith(32, 'arrived')
  })

  it('În cabinet: сверх плана — первым и янтарным, с тем, кого задержит; в срок — «încă N min»', () => {
    show({ agenda: FLOW })
    open('În cabinet')
    expect(rows()).toEqual([
      { id: '42', name: 'Over Run', chip: '+30 min amber', sub: 'Dr. Ana · 10:05–11:00',
        note: 'Long Wait (11:00) așteaptă deja 20 min', over: true },
      { id: '41', name: 'On Time', chip: 'încă 30 min blue', sub: 'Dr. Ion · 11:02–12:00', note: null, over: false },
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Finalizat: Over Run' }))
    expect(onFlow).toHaveBeenCalledWith(42, 'done')
  })

  it('кого задержит затянувшийся приём: ещё не пришёл — «va aștepta», никого — так и сказано', () => {
    show({ agenda: { count: 3, today: true, items: [
      appt({ id: 1, time: '10:00', name: 'A', status: 'arrived', doctor: 'Dr. Ana', doctor_id: 'd1',
        start_ms: T(10, 0), end_ms: T(11, 0), end: '11:00', in_at: '10:00' }),
      appt({ id: 2, time: '11:15', name: 'B', status: 'confirmed', doctor: 'Dr. Ana', doctor_id: 'd1',
        start_ms: T(11, 15), end_ms: T(11, 45) }),
      appt({ id: 3, time: '10:30', name: 'C', status: 'arrived', doctor: 'Dr. Ion', doctor_id: 'd2',
        start_ms: T(10, 30), end_ms: T(11, 10), end: '11:10', in_at: '10:31' }),
    ] } })
    open('În cabinet')
    expect(rows().map((r) => r.note)).toEqual(['B (11:15) va aștepta', 'nu mai are pacienți azi'])
  })

  it('клик по строке — карточка визита; «Toate» возвращает ТОТ ЖЕ узел списка', () => {
    show({ agenda: FLOW })
    const list = document.querySelector('.ag-l')
    open('A venit')
    // список НЕ снимается и не `hidden`: невидим в своей клетке стека, высота блока стоит (09.10)
    expect(document.querySelector('.ag-l')!.classList.contains('off')).toBe(true)
    expect(document.querySelector('.ag-stack > .fl-list')).not.toBeNull()
    fireEvent.click(document.querySelector('.fl-row[data-appt="33"]')!)
    expect(onCard).toHaveBeenCalledWith(33)
    expect(onFlow).not.toHaveBeenCalled()
    open('Toate')
    expect(document.querySelector('.ag-l')).toBe(list)
    expect(list!.classList.contains('off')).toBe(false)
    expect(document.querySelector('.fl-list')).toBeNull()
  })

  it('пустая вкладка говорит словами, а не пустотой', () => {
    show({ agenda: { count: 1, today: true, items: [appt({ id: 9, start_ms: T(12, 0), end_ms: T(13, 0) })] } })
    open('Întârzie')
    expect(document.querySelector('.fl-empty')?.textContent).toBe('Nimeni nu întârzie')
    open('În cabinet')
    expect(document.querySelector('.fl-empty')?.textContent).toBe('Nimeni în cabinet')
  })
})

describe('01.10: «La recepție» — списки стойки', () => {
  it('порядок колонки: календарь, повестка, списки (слово Олега 28.09)', () => {
    const { container } = show()
    expect(Array.from(container.children).map((e) => e.className))
      .toEqual(['mcal', 'agenda', 'dp-free', 'desk'])
  })

  it('08.10: строки цифр дня и плиток «Azi» нет — цифры в подзаголовке страницы', () => {
    show()
    expect(document.querySelector('.dk-h')).toBeNull()
    expect(document.querySelector('.rk-i')).toBeNull()
    /* тихий день: ни одного списка — карточки стойки нет вовсе */
    cleanup()
    show({ desk: { ...DESK, collect: null, unscheduled: { items: [], n: 0, sum_s: '0' },
      confirm: { ...DESK.confirm, n: 0, items: [] } } })
    expect(document.querySelector('.desk')).toBeNull()
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

  it('Primul loc liber (08.10): по канве, сегодня от следующего целого часа; «Programează» — диалог часа', () => {
    /* сейчас 11:30: Dr. Ion занят в 11, свободен с 12; Dr. Ana занята весь день */
    show()
    const rows = Array.from(document.querySelectorAll('.dp-free-row')) as HTMLElement[]
    expect(rows.map((r) => [r.querySelector('b')?.textContent, r.querySelector('small')?.textContent,
      (r.querySelector('button') as HTMLButtonElement).disabled]))
      .toEqual([['Dr. Ion', 'azi 12:00', false], ['Dr. Ana', 'Fără intervale libere', true]])
    fireEvent.click(within(rows[0]!).getByRole('button', { name: 'Programează Dr. Ion 12:00' }))
    expect(onSlot).toHaveBeenCalledWith('d2', 'Dr. Ion', '12:00')
    /* чужой день — с начала рабочего дня, дата вместо «azi» */
    cleanup()
    show({ agenda: { ...AGENDA, today: false } })
    expect(document.querySelector('.dp-free-row small')?.textContent).toBe('19.09 09:00')
  })

  it('Plan fără programare — «încă N», и пустые списки не рисуются', () => {
    show()
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
