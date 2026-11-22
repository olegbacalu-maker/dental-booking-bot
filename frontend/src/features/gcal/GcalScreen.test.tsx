import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { openScreen } from '../../test/openScreen'
import type { DashMiniCal } from '../schedule/dash'
import type { DayForm } from '../schedule/day'
import { GcalScreen, loadGcal } from './GcalScreen'
import {
  fileSource, firstLine, presetOf, queryOf, spanOf, whereOf, type GcalGoogle, type GcalList, type GcalRow,
} from './gcal'

const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const FORM: DayForm = {
  doctors: [{ id: 'd2', name: 'Dr. Activ Doi', spec: '' }, { id: 'd3', name: 'Dr. Activ Trei', spec: '' }],
  times: { d2: ['09:00', '10:00', '11:00'], d3: ['10:00', '11:00'] },
  hours: ['09:00', '10:00', '11:00'],
  services: [{ id: 'consult', label: 'Consultație' }],
  durations: [15, 30, 60], dur_step: 5, dur_max: 240, step: 5,
  doctor: 'd2', time: '09:00', birth_max: '2026-11-12',
}

function row(over: Partial<GcalRow> = {}): GcalRow {
  return {
    id: 5, when: '2026-11-16T11:08', date: '2026-11-16', time: '11:08', minutes: 30,
    title: 'Lungu Petru control', body: 'vine cu radiografia\nLoc: Cabinet 2', series: false,
    state: 'nou', changed: false, gstatus: '', why: null,
    round: { from: '11:08–11:38', to: '11:10–11:40' },
    hint: { phone: '', name: 'Lungu Petru', doctor: null, patients: [], exists: null },
    preset: { date: '2026-11-16', time: '11:10', duration: '30', doctor: '', service: '',
      name: 'Lungu Petru', phone: '', nophone: true },
    appt: null, can: { move: true, link: true, skip: true, back: false },
    ...over,
  }
}

const KNOWN = row({
  id: 6, when: '2026-11-16T14:00', time: '14:00', title: 'Rotaru Ana 069123456', body: '', round: null,
  hint: { phone: '69123456', name: 'Rotaru Ana', doctor: { key: 'd3', name: 'Dr. Activ Trei' },
    patients: [{ id: 41, name: 'Ana Rotaru', phone: '069123456' }], exists: null },
  preset: { date: '2026-11-16', time: '10:00', duration: '30', doctor: 'd3', service: 'consult',
    name: 'Rotaru Ana', phone: '069123456', nophone: false },
})

const EVIL = row({ id: 7, when: '2026-11-17T09:00', date: '2026-11-17', time: '09:00', round: null,
  title: '<img src=x onerror=alert(1)> Popa', body: '' })

const cell = (date: string, over = {}) => ({ date, day: Number(date.slice(8)), other: false, today: false,
  selected: false, busy: false, href: `/admin/google?date=${date}`, ...over })

/** Неделя месяца: 16-го и 17-го есть события, 12-е — сегодня. */
const CAL: DashMiniCal = {
  title: 'Noiembrie 2026', weekdays: ['Lu', 'Ma', 'Mi', 'Jo', 'Vi', 'Sâ', 'Du'],
  weeks: [[cell('2026-11-12', { today: true }), cell('2026-11-13'), cell('2026-11-14'), cell('2026-11-15'),
    cell('2026-11-16', { busy: true }), cell('2026-11-17', { busy: true }), cell('2026-11-18')]],
  prev: { date: '2026-10-01', href: '/admin/google?month=2026-10-01' },
  next: { date: '2026-12-01', href: '/admin/google?month=2026-12-01' },
}

function list(over: Partial<GcalList> = {}): GcalList {
  return {
    date: '', minical: CAL,
    source: { id: 1, kind: 'ics', name: 'Clinica Zâmbet', loaded_at: '12.11.2026 14:20', loaded_by: 'Ana', service: '' },
    f: 'nou', q: '',
    filters: [{ key: 'nou', label: 'De mutat', n: 3 }, { key: 'mutat', label: 'Mutate', n: 1 },
      { key: 'omis', label: 'Omise', n: 2 }, { key: 'nerecunoscut', label: 'Nerecunoscute', n: 0 }],
    days: [{ date: '2026-11-16', rows: [row(), KNOWN] }, { date: '2026-11-17', rows: [EVIL] }],
    undated: [], total: 3,
    help: ['Pasul unu.', 'Pasul doi.', 'Pasul trei.'],
    keep_days: 7, horizon_days: 365, max_mb: 20, can: { clear: true },
    ...over,
  }
}

const EMPTY = list({ source: null, days: [], total: 0, filters: [{ key: 'nou', label: 'De mutat', n: 0 }] })

const MOVED = row({
  id: 8, title: '', body: '', state: 'mutat', round: null, hint: null, preset: null,
  appt: { id: 90, pid: 41, patient: 'Ana Rotaru', doctor: 'Dr. Activ Trei', when: '2026-11-16T10:00',
    status: { code: 'confirmed', text: 'programată' }, day_href: '/admin/all?date=2026-11-16' },
  can: { move: false, link: false, skip: false, back: false },
})

/** Ответы GET по адресу: форма дня — журналу, остальное — вкладке. */
function serve(data: GcalList) {
  get.mockImplementation((path: string) => (path.startsWith('/schedule/day')
    ? Promise.resolve(ok({ date: '2026-11-16', form: FORM }))
    : Promise.resolve(ok(data))))
}

async function open(data: GcalList, navigate = vi.fn()) {
  serve(data)
  const view = openScreen('/admin/google', '/admin/google', <GcalScreen navigate={navigate} />, loadGcal)
  await waitFor(() => expect(document.querySelector('.gc')).not.toBeNull())
  return { ...view, navigate }
}

const rowEl = (id: number) => document.querySelector(`.gc-row[data-id="${id}"]`) as HTMLElement
const dialogForm = () => document.querySelector('.dp-addform') as HTMLFormElement | null
const field = (ph: string) => dialogForm()?.querySelector(`input[placeholder="${ph}"]`) as HTMLInputElement
const doctorSel = () => dialogForm()?.querySelector('select[aria-label="Medic"]') as HTMLSelectElement
const goBtn = () => dialogForm()?.querySelector('button:not([type="button"])') as HTMLButtonElement

async function openMove(id: number) {
  fireEvent.click(within(rowEl(id)).getByRole('button', { name: /Mută în jurnal/ }))
  await waitFor(() => expect(dialogForm()).not.toBeNull())
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('GcalScreen: пусто и загрузка', () => {
  it('без календаря — объяснение в три шага и выбор файла; списка и «Șterge tot» нет', async () => {
    await open(EMPTY)
    expect(Array.from(document.querySelectorAll('.gc-help li')).map((x) => x.textContent))
      .toEqual(['Pasul unu.', 'Pasul doi.', 'Pasul trei.'])
    expect(screen.getByRole('button', { name: /Alege fișierul/ })).toBeTruthy()
    expect(document.querySelector('.gc-row')).toBeNull()
    expect(screen.queryByRole('button', { name: /Șterge tot din Google/ })).toBeNull()
    expect(document.body.textContent).toContain('cel mult 20 MB')
  })

  it('файл уходит multipart, итог — словом: принято и оставлено с причинами', async () => {
    await open(EMPTY)
    postForm.mockResolvedValue(ok(list({
      load: { new: 14, updated: 0, same: 0, changed: 0, gone: 0, unparsed: 1, skipped: 2,
        all_day: 1, cancelled: 1, past: 3, beyond: 0, refused: [] },
    }), 'gc_loaded', 'Fișierul a fost citit'))
    const file = new File(['BEGIN:VCALENDAR'], 'clinica.ics', { type: 'text/calendar' })
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } })
    await waitFor(() => expect(postForm).toHaveBeenCalled())
    expect(postForm.mock.calls[0]?.[0]).toBe('/gcal/file')
    expect((postForm.mock.calls[0]?.[1] as FormData).get('file')).toBe(file)
    await waitFor(() => expect(document.querySelector('.gc-report')).not.toBeNull())
    const text = document.querySelector('.gc-report')?.textContent ?? ''
    expect(text).toContain('Primite: 14 evenimente noi.')
    expect(text).toContain('Lăsate deoparte: 3 trecute, 1 pe toată ziua, 1 anulat în Google, 1 nerecunoscut.')
    expect(document.querySelectorAll('.gc-row').length).toBe(3)
  })

  it('отказ файла — словом сервера в плашке, экран остаётся', async () => {
    await open(EMPTY)
    postForm.mockRejectedValue(new ApiError(
      { kind: 'validation', code: 'gc_not_calendar', text: 'Acesta nu este un fișier de calendar', field: 'file' }, 'x'))
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement,
      { target: { files: [new File(['x'], 'poza.jpg')] } })
    await waitFor(() => expect(document.querySelector('.toastbox')?.textContent)
      .toContain('Acesta nu este un fișier de calendar'))
    expect(screen.getByRole('button', { name: /Alege fișierul/ })).toBeTruthy()
  })
})

describe('GcalScreen: список', () => {
  it('события по дням: час уже округлён, длительность, название текстом, описание свёрнуто', async () => {
    await open(list())
    expect(Array.from(document.querySelectorAll('.gc-day-h')).map((x) => x.textContent))
      .toEqual(['luni, 16 noiembrie 2026', 'marți, 17 noiembrie 2026'])
    const r = rowEl(5)
    expect(r.querySelector('.gc-time b')?.textContent).toBe('11:10–11:40')
    expect(r.querySelector('.gc-time small')?.textContent).toBe('30 min')
    expect(r.textContent).toContain('ora rotunjită 11:08–11:38 › 11:10–11:40')
    expect(r.querySelector('.gc-state')?.textContent).toBe('nemutat')
    const body = r.querySelector('details.gc-body') as HTMLDetailsElement
    expect(body.open).toBe(false)
    expect(body.querySelector('.gc-desc')?.textContent).toBe('vine cu radiografia')
    expect(body.querySelector('pre')?.textContent).toContain('Loc: Cabinet 2')
    expect(document.body.textContent).toContain('3 evenimente')
  })

  it('название с разметкой печатается текстом', async () => {
    await open(list())
    expect(rowEl(7).querySelector('.gc-title')?.textContent).toBe('<img src=x onerror=alert(1)> Popa')
    expect(rowEl(7).querySelector('img')).toBeNull()
  })

  it('подсказки строки: врач и фиша — только пометками', async () => {
    await open(list())
    expect(rowEl(6).textContent).toContain('posibil Dr. Activ Trei')
    expect(rowEl(6).textContent).toContain('fișă: Ana Rotaru')
  })

  it('вкладки и счётчики — сервера; щелчок пишет отбор в адрес и спрашивает его список', async () => {
    const { router } = await open(list())
    expect(Array.from(document.querySelectorAll('.rc-tab')).map((x) => x.textContent))
      .toEqual(['De mutat 3', 'Mutate 1', 'Omise 2', 'Nerecunoscute 0'])
    serve(list({ f: 'mutat', days: [{ date: '2026-11-16', rows: [MOVED] }], total: 1 }))
    fireEvent.click(screen.getByRole('tab', { name: /Mutate/ }))
    await waitFor(() => expect(rowEl(8)).not.toBeNull())
    expect(get).toHaveBeenCalledWith('/gcal?f=mutat', expect.anything())
    expect(router.state.location.search).toBe('?f=mutat')
    expect(screen.getByRole('tab', { name: /Mutate/ }).getAttribute('aria-selected')).toBe('true')
  })

  it('поиск уходит после паузы, тем же отбором', async () => {
    await open(list())
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'rota' } })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/gcal?q=rota', expect.anything()))
  })

  it('набрали текст и сразу сменили вкладку: отложенный поиск спрашивает новую вкладку', async () => {
    await open(list())
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'rota' } })
    fireEvent.click(screen.getByRole('tab', { name: /Omise/ }))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/gcal?f=omis&q=rota', expect.anything()))
    await new Promise((r) => setTimeout(r, 400))
    expect(get).not.toHaveBeenCalledWith('/gcal?q=rota', expect.anything())
  })

  it('перенесённое: ссылка на день журнала; изменившееся в Google — пометка без кнопок', async () => {
    await open(list({ f: 'mutat', total: 2, days: [{ date: '2026-11-16', rows: [
      MOVED,
      { ...MOVED, id: 9, changed: true, when: '2026-11-17T12:00' },
      { ...MOVED, id: 10, changed: true, gstatus: 'gone', why: { code: 'gone', text: 'nu mai este în calendarul Google' } },
    ] }] }))
    const link = rowEl(8).querySelector('.gc-what a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/admin/all?date=2026-11-16')
    expect(link.textContent).toBe('Ana Rotaru · Dr. Activ Trei · 16.11 10:00')
    expect(rowEl(8).textContent).not.toContain('s-a schimbat')
    expect(rowEl(9).textContent).toContain('s-a schimbat în Google — în Google acum 17.11 12:00')
    expect(rowEl(10).textContent).toContain('s-a schimbat în Google — nu mai este în calendarul Google')
    expect(rowEl(9).querySelectorAll('.rc-acts button').length).toBe(0)
  })

  it('отложенное: само (весь день) — с причиной, руками — «de dvs.» и возврат', async () => {
    await open(list({ f: 'omis', days: [{ date: '2026-11-16', rows: [
      row({ id: 11, state: 'omis', time: '', round: null, why: { code: 'all_day', text: 'eveniment pe toată ziua' },
        can: { move: true, link: true, skip: false, back: true } }),
      row({ id: 12, state: 'omis', can: { move: true, link: true, skip: false, back: true } }),
    ] }] }))
    expect(rowEl(11).querySelector('.gc-state')?.textContent).toBe('omis — eveniment pe toată ziua')
    expect(rowEl(11).querySelector('.gc-time b')?.textContent).toBe('toată ziua')
    expect(rowEl(12).querySelector('.gc-state')?.textContent).toBe('omis — de dvs.')
    post.mockResolvedValue(ok(list(), 'gc_back', 'Evenimentul este din nou în listă'))
    fireEvent.click(within(rowEl(12)).getByRole('button', { name: /Readu în listă/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/events/12/skip', { on: false }))
  })

  it('«Nu muta» шлёт команду и берёт список из её ответа', async () => {
    await open(list())
    post.mockResolvedValue(ok(list({ days: [{ date: '2026-11-17', rows: [EVIL] }], total: 1 }), 'gc_skipped', 'Nu va fi mutat'))
    fireEvent.click(within(rowEl(5)).getByRole('button', { name: 'Nu muta' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/events/5/skip', { on: true }))
    await waitFor(() => expect(rowEl(5)).toBeNull())
    expect(document.querySelector('.toastbox')?.textContent).toContain('Nu va fi mutat')
  })

  it('«Există deja în jurnal» — «Leagă» шлёт номер записи', async () => {
    await open(list({ days: [{ date: '2026-11-16', rows: [row({
      hint: { phone: '', name: 'Lungu Petru', doctor: null, patients: [],
        exists: { appt_id: 77, text: 'Petru Lungu · Dr. Activ Doi · 16.11 11:10' } } })] }] }))
    expect(rowEl(5).textContent).toContain('Există deja în jurnal: Petru Lungu · Dr. Activ Doi · 16.11 11:10')
    post.mockResolvedValue(ok(list(), 'gc_linked', 'Legat'))
    fireEvent.click(within(rowEl(5)).getByRole('button', { name: 'Leagă' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/events/5/link', { appt_id: 77 }))
  })
})

describe('GcalScreen: календарь месяца', () => {
  it('тот же календарь, что у журнала: точки дней с событиями, «сегодня», ссылки дня и месяца', async () => {
    await open(list())
    const side = document.querySelector('.gc-side') as HTMLElement
    expect(side.querySelector('.mhead b')?.textContent).toBe('Noiembrie 2026')
    expect(Array.from(side.querySelectorAll('td a')).filter((a) => a.querySelector('.dot')).map((a) => a.textContent))
      .toEqual(['16', '17'])
    expect(side.querySelector('td a.tdy')?.textContent).toBe('12')
    expect(side.querySelector('td a[title="2026-11-16 · are evenimente"]')).not.toBeNull()
    expect(within(side).getByLabelText('Luna următoare').getAttribute('href')).toBe('/admin/google?month=2026-12-01')
    expect(side.textContent).not.toContain('Arată toate zilele')
  })

  it('нажатие на день пишет его в адрес; список — этого дня, сброс одной кнопкой', async () => {
    const { router } = await open(list())
    const picked = list({ date: '2026-11-17', total: 1, days: [{ date: '2026-11-17', rows: [EVIL] }],
      minical: { ...CAL, weeks: [CAL.weeks[0]!.map((c) => ({ ...c, selected: c.date === '2026-11-17' }))] } })
    serve(picked)
    fireEvent.click((document.querySelector('.gc-side td a[title^="2026-11-17"]') as HTMLElement))
    await waitFor(() => expect(document.querySelector('.gc-dayline')?.textContent).toContain('marți, 17 noiembrie 2026'))
    expect(get).toHaveBeenCalledWith('/gcal?date=2026-11-17', expect.anything())
    expect(document.querySelectorAll('.gc-row').length).toBe(1)
    expect(document.querySelector('.gc-side td a.seld')?.textContent).toBe('17')
    serve(list())
    fireEvent.click(within(document.querySelector('.gc-side') as HTMLElement).getByRole('button', { name: /Arată toate zilele/ }))
    await waitFor(() => expect(document.querySelectorAll('.gc-row').length).toBe(3))
    expect(router.state.location.search).toBe('?month=2026-11-17')
  })

  it('команда строки уходит в отборе адреса: день и вкладка остаются', async () => {
    serve(list({ f: 'omis', date: '2026-11-16' }))
    openScreen('/admin/google', '/admin/google?f=omis&date=2026-11-16', <GcalScreen />, loadGcal)
    await waitFor(() => expect(rowEl(5)).not.toBeNull())
    expect(get).toHaveBeenCalledWith('/gcal?f=omis&date=2026-11-16', expect.anything())
    post.mockResolvedValue(ok(list({ f: 'omis', date: '2026-11-16' }), 'gc_skipped', 'x'))
    fireEvent.click(within(rowEl(5)).getByRole('button', { name: 'Nu muta' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/events/5/skip?f=omis&date=2026-11-16', { on: true }))
  })

  it('узкий экран: тот же месяц под кнопкой с датой', async () => {
    await open(list())
    const btn = document.querySelector('.gc-calbtn button') as HTMLElement
    expect(btn.textContent).toContain('Toate zilele')
    fireEvent.click(btn)
    expect(document.querySelector('.gc-calbtn .dp-calpop .mcal')).not.toBeNull()
  })
})

describe('GcalScreen: перенос окном записи', () => {
  it('окно открывается заполненным: дата, час, минута, длительность, имя; врача выбирает человек', async () => {
    await open(list())
    await openMove(5)
    expect(get).toHaveBeenCalledWith('/schedule/day?date=2026-11-16', expect.anything())
    const f = dialogForm() as HTMLFormElement
    expect((f.querySelector('input[type="date"]') as HTMLInputElement).value).toBe('2026-11-16')
    expect(Array.from(f.querySelectorAll('.dp-minpick .mp.on')).map((b) => b.textContent)).toEqual([':10'])
    expect((f.querySelector('select[aria-label="Durată"]') as HTMLSelectElement).value).toBe('30')
    expect(field('Nume pacient').value).toBe('Lungu Petru')
    expect(f.querySelector('.dp-addnote')?.textContent)
      .toBe('Din Google: luni, 16 noiembrie 2026, 11:08–11:38 · Lungu Petru control')
    expect(doctorSel().value).toBe('')
    expect(goBtn().disabled).toBe(true)
    fireEvent.change(doctorSel(), { target: { value: 'd2' } })
    expect(goBtn().disabled).toBe(false)
  })

  it('удача: тело окна уходит на перенос, строка уходит из списка, плашка со ссылкой на день', async () => {
    await open(list())
    await openMove(5)
    fireEvent.change(doctorSel(), { target: { value: 'd2' } })
    fireEvent.click(dialogForm()?.querySelector('.nophone input') as HTMLElement)
    post.mockResolvedValue(ok(list({ days: [{ date: '2026-11-17', rows: [EVIL] }], total: 1, appt_id: 91 }),
      'ok', 'Programare adăugată'))
    fireEvent.submit(dialogForm() as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/events/5/move', {
      date: '2026-11-16', time: '11:10', doctor: 'd2', service: 'consult',
      name: 'Lungu Petru', phone: '', nophone: true, birth: '', duration: 30,
    }))
    await waitFor(() => expect(rowEl(5)).toBeNull())
    const toast = document.querySelector('.toastbox') as HTMLElement
    expect(toast.textContent).toContain('Programare adăugată')
    expect(toast.querySelector('a')?.getAttribute('href')).toBe('/admin/all?date=2026-11-16')
  })

  it('отказ журнала («ocupat») — словом в окне, событие остаётся непереносённым', async () => {
    await open(list())
    await openMove(5)
    fireEvent.change(doctorSel(), { target: { value: 'd2' } })
    fireEvent.click(dialogForm()?.querySelector('.nophone input') as HTMLElement)
    post.mockRejectedValue(new ApiError({ kind: 'conflict', code: 'conflict', text: 'Interval ocupat' }, 'x'))
    fireEvent.submit(dialogForm() as HTMLFormElement)
    await waitFor(() => expect(dialogForm()?.querySelector('.banner.err')?.textContent).toBe('Interval ocupat'))
    expect(rowEl(5).querySelector('.gc-state')?.textContent).toBe('nemutat')
    expect(document.querySelector('.toastbox')).toBeNull()
  })

  it('однозначный врач подставлен; выбранная фиша уходит номером, имя и телефон — её', async () => {
    await open(list())
    await openMove(6)
    expect(doctorSel().value).toBe('d3')
    const chip = await within(dialogForm() as HTMLElement).findByRole('button', { name: /Ana Rotaru/ })
    fireEvent.click(chip)
    expect(chip.getAttribute('aria-pressed')).toBe('true')
    expect(field('Nume pacient').disabled).toBe(true)
    expect(field('Nume pacient').value).toBe('Ana Rotaru')
    post.mockResolvedValue(ok(list(), 'ok', 'Programare adăugată'))
    fireEvent.submit(dialogForm() as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0]?.[1]).toMatchObject({ pid: 41, name: 'Ana Rotaru', phone: '069123456',
      doctor: 'd3', time: '10:00', duration: 30 })
  })

  it('событие уже перенёс сосед: слово в окне и свежий список', async () => {
    await open(list())
    await openMove(6)
    post.mockRejectedValue(new ApiError({ kind: 'conflict', code: 'gc_moved', text: 'Evenimentul este deja mutat în jurnal' }, 'x'))
    get.mockClear()
    fireEvent.submit(dialogForm() as HTMLFormElement)
    await waitFor(() => expect(dialogForm()?.querySelector('.banner.err')?.textContent)
      .toBe('Evenimentul este deja mutat în jurnal'))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/gcal', {}))
  })
})

describe('GcalScreen: «Șterge tot din Google»', () => {
  it('директору — кнопка с вопросом; отказ от вопроса ничего не шлёт', async () => {
    await open(list())
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: /Șterge tot din Google/ }))
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(post).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    post.mockResolvedValue(ok(EMPTY, 'gc_cleared', 'Evenimentele au fost șterse'))
    fireEvent.click(screen.getByRole('button', { name: /Șterge tot din Google/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/clear', {}))
    await waitFor(() => expect(screen.getByRole('button', { name: /Alege fișierul/ })).toBeTruthy())
  })

  it('без права кнопки нет; строка о хранении и сроке — всем', async () => {
    await open(list({ can: { clear: false } }))
    expect(screen.queryByRole('button', { name: /Șterge tot din Google/ })).toBeNull()
    expect(document.querySelector('.gc-foot')?.textContent).toContain('la 7 zile după data lui')
  })
})

describe('gcal: заполнение окна и часы строки', () => {
  it('пустой врач и пустой час остаются пустыми, длительность — числом', () => {
    expect(presetOf(row())).toEqual({ date: '2026-11-16', time: '11:10', duration: 30, doctor: '',
      name: 'Lungu Petru', phone: '' })
    expect(presetOf(row({ preset: { date: '2026-11-16', time: '', duration: '', doctor: '', service: '',
      name: '', phone: '', nophone: true } }))).toEqual({ date: '2026-11-16', doctor: '', name: '', phone: '' })
  })

  it('отбор и адрес: пустое не пишется, чтение обратно то же', () => {
    expect(queryOf({ f: '', q: '', date: '', month: '' })).toBe('')
    const w = { f: 'omis', q: 'ana maria', date: '2026-11-16', month: '' }
    expect(queryOf(w)).toBe('?f=omis&q=ana+maria&date=2026-11-16')
    expect(whereOf(new URLSearchParams(queryOf(w)))).toEqual(w)
  })

  it('в строку встаёт первая непустая строка описания', () => {
    expect(firstLine('\n  vine cu radiografia \nLoc: Cabinet 2')).toBe('vine cu radiografia')
    expect(firstLine('')).toBe('')
  })

  it('часы без округления считаются из начала и длины', () => {
    expect(spanOf(row({ round: null, time: '09:10', minutes: 20 }))).toBe('09:10–09:30')
    expect(spanOf(row({ round: null, time: '', minutes: 0 }))).toBe('')
  })
})

/* Блок связи с аккаунтом Google: состояние, кнопки и слова — сервера (gcal_link.view). */
const WORDS: GcalGoogle['words'] = {
  connect: 'Conectează contul Google', disconnect: 'Deconectează', check: 'Verifică acum',
  calendar: 'Alege calendarul', change: 'Schimbă', title: 'Contul Google al clinicii',
  lead: 'Programările vin singure', hint: 'Se deschide browserul.',
  connected: 'Conectat:', calendar_label: 'calendarul', last_check: 'Ultima verificare:',
  last_ok: 'Ultima reușită:', primary: 'calendarul principal al contului',
  waiting_title: 'Așteptăm răspunsul Google…', waiting_detail: 'Terminați conectarea în browser.',
  reopen: 'Deschide din nou pagina', cancel: 'Renunță',
  disconnect_ask: 'Deconectați contul Google?', disconnect_ok: 'Deconectează',
  plus_lead: 'O porniți plătind varianta Plus în', details: 'Detalii:',
}

function google(over: Partial<GcalGoogle> = {}): GcalGoogle {
  return {
    state: 'off', connected: false, account: '', calendar: null, calendars: [], last: null, why: null,
    notice: 'Programul citește evenimentele unui calendar Google ales de dvs.',
    privacy: { href: 'https://dentpilot.md/privacy.html#google', label: 'dentpilot.md/privacy.html#google' },
    plus: null, waiting: false, remote: null, every_min: 10,
    can: { connect: true, calendar: false, check: false, disconnect: false }, words: WORDS,
    ...over,
  }
}

const CALS = [{ id: 'main', name: 'Clinica', primary: true }, { id: 'prog', name: 'Programări', primary: false }]
const ON = google({
  state: 'on', connected: true, account: 'clinica@gmail.com', calendar: { id: 'prog', name: 'Programări' },
  calendars: CALS, last: { at: '2026-11-22T12:20:00Z', when: '22.11.2026 14:20' },
  can: { connect: false, calendar: true, check: true, disconnect: true },
})
const OFFLINE: GcalGoogle = { ...ON, why: { code: 'gc_g_offline', tone: 'warn', text: 'Google nu a răspuns', detail: '',
  at: '2026-11-22T12:30:00Z', when: '22.11.2026 14:30' } }
const PLUS = google({
  state: 'plus', plus: { href: '/admin/license', label: 'Setări › Licența' },
  why: { code: 'gc_g_plus', tone: 'warn', text: 'Conectarea la contul Google face parte din DentPilot Plus',
    detail: 'În DentPilot Basic calendarul se încarcă din fișierul exportat din Google.' },
  can: { connect: false, calendar: false, check: false, disconnect: false },
})
const NO_CAN = { connect: false, calendar: false, check: false, disconnect: false }

const strip = () => document.querySelector('.gl-strip') as HTMLElement | null
const gl = () => strip()?.querySelector('.gl') as HTMLElement
const inStrip = (name: string | RegExp) => within(strip() as HTMLElement).getByRole('button', { name })
const stripButtons = () => within(strip() as HTMLElement).queryAllByRole('button').map((x) => x.textContent?.trim())
const lines = () => Array.from(gl().querySelectorAll('.gl-line > .gl-h, .gl-line > .gl-d')).map((x) => x.textContent)

describe('GcalScreen: связь с аккаунтом Google', () => {
  it('блока нет, когда сервер его не даёт (демо, сервер, сборка без клиента): полоса файла как была', async () => {
    await open(list({ google: null }))
    expect(strip()).toBeNull()
    expect(screen.getByRole('button', { name: /Încarcă din nou/ })).toBeTruthy()
  })

  it('Basic: строка Plus и путь на «Setări › Licența», кнопок нет; загрузка файла на месте', async () => {
    await open(list({ google: PLUS }))
    expect(gl().dataset.gl).toBe('plus')
    expect(lines()).toEqual([
      'Conectarea la contul Google face parte din DentPilot Plus. O porniți plătind varianta Plus în Setări › Licența ›',
      'În DentPilot Basic calendarul se încarcă din fișierul exportat din Google.',
    ])
    expect(within(strip() as HTMLElement).getByRole('link', { name: /Setări › Licența/ }).getAttribute('href'))
      .toBe('/admin/license')
    expect(stripButtons()).toEqual([])
    expect(screen.getByRole('button', { name: /Încarcă din nou/ })).toBeTruthy()
  })

  it('пустая вкладка: блок над карточкой файла, выбор файла остаётся', async () => {
    await open({ ...EMPTY, google: PLUS })
    const blocks = Array.from(document.querySelectorAll('.gc > .fcard'))
    expect(blocks.map((x) => x.className)).toEqual(['fcard gl-strip', 'fcard gc-empty'])
    expect(screen.getByRole('button', { name: /Alege fișierul/ })).toBeTruthy()
  })

  it('не подключено: уведомление, ссылка на политику новым окном, «Conectează» открывает Google в браузере', async () => {
    await open(list({ google: google() }))
    expect(gl().querySelector('.gl-notice')?.textContent)
      .toBe('Programul citește evenimentele unui calendar Google ales de dvs. Detalii: dentpilot.md/privacy.html#google')
    const privacy = within(strip() as HTMLElement).getByRole('link', { name: 'dentpilot.md/privacy.html#google' })
    expect(privacy.getAttribute('href')).toBe('https://dentpilot.md/privacy.html#google')
    expect(privacy.getAttribute('target')).toBe('_blank')
    const opened = vi.spyOn(window, 'open').mockReturnValue(null)
    post.mockResolvedValue(ok({ ...list({ google: google({ waiting: true }) }), url: 'https://accounts.example/o' },
      'gc_g_url', 'Pagina Google se deschide în browser'))
    fireEvent.click(inStrip(/Conectează contul Google/))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/google/connect', {}))
    await waitFor(() => expect(opened).toHaveBeenCalledWith('https://accounts.example/o', '_blank', 'noopener'))
    await waitFor(() => expect(gl().dataset.gl).toBe('waiting'))
    expect(lines()).toEqual(['Așteptăm răspunsul Google…', 'Terminați conectarea în browser.'])
  })

  it('со второго ПК: «Conectează» видна выключенной, рядом слово сервера', async () => {
    await open(list({ google: google({
      remote: { code: 'only_local', tone: 'warn', text: 'Doar de pe calculatorul programului' }, can: NO_CAN,
    }) }))
    expect((inStrip(/Conectează contul Google/) as HTMLButtonElement).disabled).toBe(true)
    expect(strip()?.textContent).toContain('Doar de pe calculatorul programului')
  })

  it('ждём браузер: опрос раз в 3 с тем же отбором, при возврате в окно — сразу; «Renunță» снимает ожидание', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    serve(list({ f: 'omis', google: google({ waiting: true }) }))
    openScreen('/admin/google', '/admin/google?f=omis', <GcalScreen />, loadGcal)
    await waitFor(() => expect(gl()?.dataset.gl).toBe('waiting'))
    get.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(3010) })
    expect(get).toHaveBeenCalledWith('/gcal?f=omis', {})
    get.mockClear()
    act(() => { window.dispatchEvent(new Event('focus')) })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/gcal?f=omis', {}))
    post.mockResolvedValue(ok(list({ f: 'omis', google: google() }), 'gc_g_cancel', 'Conectarea a fost oprită'))
    fireEvent.click(inStrip('Renunță'))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/google/cancel?f=omis', {}))
    await waitFor(() => expect(gl().dataset.gl).toBe('off'))
    get.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(6100) })
    expect(get).not.toHaveBeenCalled()
  })

  it('ждём браузер: вход закончился — опрос приносит выбор календаря и останавливается', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await open(list({ google: google({ waiting: true }) }))
    serve(list({ google: { ...ON, state: 'choose', calendar: null, last: null } }))
    await act(async () => { await vi.advanceTimersByTimeAsync(3010) })
    await waitFor(() => expect(gl().dataset.gl).toBe('choose'))
    get.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(6100) })
    expect(get).not.toHaveBeenCalled()
  })

  it('ответ опроса другого отбора отбрасывается: вкладку сменили, пока он шёл', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await open(list({ google: google({ waiting: true }) }))
    let late: (v: ApiResult<GcalList>) => void = () => {}
    get.mockImplementation((path: string) => (path === '/gcal'
      ? new Promise((res) => { late = res })
      : Promise.resolve(ok(list({ f: 'mutat', days: [{ date: '2026-11-16', rows: [MOVED] }], total: 1,
        google: google({ waiting: true }) })))))
    await act(async () => { await vi.advanceTimersByTimeAsync(3010) })
    fireEvent.click(screen.getByRole('tab', { name: /Mutate/ }))
    await waitFor(() => expect(rowEl(8)).not.toBeNull())
    await act(async () => { late(ok(list({ google: google({ waiting: true }) }))) })
    expect(rowEl(8)).not.toBeNull()
    expect(rowEl(5)).toBeNull()
  })

  it('ответ опроса, обогнанный командой, отбрасывается: список после команды не откатывается', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await open(list({ google: google({ waiting: true }) }))
    let late: (v: ApiResult<GcalList>) => void = () => {}
    get.mockImplementation(() => new Promise((res) => { late = res }))
    await act(async () => { await vi.advanceTimersByTimeAsync(3010) })
    post.mockResolvedValue(ok(list({ days: [{ date: '2026-11-17', rows: [EVIL] }], total: 1, google: google() }),
      'gc_g_cancel', 'Conectarea a fost oprită'))
    fireEvent.click(inStrip('Renunță'))
    await waitFor(() => expect(gl().dataset.gl).toBe('off'))
    await act(async () => { late(ok(list({ google: google({ waiting: true }) }))) })
    expect(gl().dataset.gl).toBe('off')
    expect(rowEl(5)).toBeNull()
  })

  it('выбор календаря: основной подписан, выбранный уходит id, ответ — подключено', async () => {
    await open(list({ google: { ...ON, state: 'choose', calendar: null, last: null } }))
    const radios = Array.from(gl().querySelectorAll('input[type="radio"]')) as HTMLInputElement[]
    expect(radios.map((x) => [x.value, x.checked])).toEqual([['main', true], ['prog', false]])
    expect(gl().querySelector('.gl-cal small')?.textContent).toBe('calendarul principal al contului')
    fireEvent.click(radios[1] as HTMLInputElement)
    post.mockResolvedValue(ok(list({ google: ON }), 'gc_g_calendar', 'Calendarul este ales'))
    fireEvent.click(inStrip(/Alege calendarul/))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/google/calendar', { id: 'prog' }))
    await waitFor(() => expect(gl().dataset.gl).toBe('on'))
  })

  it('выбранного календаря больше нет: причина и что делать — словами сервера над списком', async () => {
    await open(list({ google: { ...ON, state: 'choose', calendar: null,
      why: { code: 'gc_g_not_found', tone: 'err', text: 'Calendarul ales nu mai este', detail: 'Alegeți alt calendar.' } } }))
    expect(gl().querySelector('.gl-who')?.textContent).toContain('Calendarul ales nu mai este Alegeți alt calendar.')
    expect(gl().querySelector('.gl-mark')?.className).toBe('gl-mark err')
  })

  it('подключено: две строки — кто и когда; «Verifică acum» в отборе адреса, значок вращается, подпись та же', async () => {
    serve(list({ f: 'mutat', google: ON }))
    openScreen('/admin/google', '/admin/google?f=mutat', <GcalScreen />, loadGcal)
    await waitFor(() => expect(gl()?.dataset.gl).toBe('on'))
    expect(lines()).toEqual(['Conectat: clinica@gmail.com · calendarul „Programări” Schimbă',
      'Ultima verificare: 22.11.2026 14:20'])
    let done: (v: ApiResult<GcalList>) => void = () => {}
    post.mockReturnValue(new Promise((res) => { done = res }))
    fireEvent.click(inStrip(/Verifică acum/))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/google/check?f=mutat', {}))
    expect(gl().querySelector('.gl-ico')?.className).toBe('gl-ico spin')
    expect(inStrip(/Verifică acum/).textContent).toBe(' Verifică acum')
    // кнопка файла не меняет подпись на чужой команде: иначе она шире и полоса файла сдвигается
    expect(within(document.querySelector('.gc-src') as HTMLElement).getByRole('button', { name: /Încarcă din nou/ }))
      .toBeTruthy()
    await act(async () => { done(ok(list({ f: 'mutat', google: ON }), 'gc_g_checked', 'Calendarul Google a fost verificat')) })
    expect(gl().querySelector('.gl-ico')?.className).toBe('gl-ico')
    expect(document.querySelector('.toastbox')?.textContent).toContain('Calendarul Google a fost verificat')
  })

  it('неудачная проверка: те же две строки — причина с часом и последняя удачная; кнопки на месте', async () => {
    await open(list({ google: OFFLINE }))
    expect(gl().dataset.gl).toBe('on')
    expect(lines()).toEqual(['Google nu a răspuns (22.11.2026 14:30)', 'Ultima reușită: 22.11.2026 14:20'])
    expect(gl().querySelector('.gl-mark')?.className).toBe('gl-mark warn')
    expect(stripButtons()).toEqual(['Verifică acum', 'Deconectează'])
  })

  it('«Schimbă» раскрывает выбор на месте с нынешним календарём; «Renunță» закрывает без команды', async () => {
    await open(list({ google: ON }))
    fireEvent.click(inStrip('Schimbă'))
    const checked = gl().querySelector('input[type="radio"]:checked') as HTMLInputElement
    expect(checked.value).toBe('prog')
    expect(within(strip() as HTMLElement).queryByRole('button', { name: /Verifică acum/ })).toBeNull()
    fireEvent.click(inStrip('Renunță'))
    expect(gl().dataset.gl).toBe('on')
    expect(post).not.toHaveBeenCalled()
  })

  it('пауза после «Șterge tot»: причина, что делать, «Verifică acum» и «Deconectează»', async () => {
    await open(list({ google: { ...ON, state: 'paused', why: { code: 'gc_g_paused', tone: 'warn',
      text: 'Verificarea este oprită', detail: '„Verifică acum” reia verificarea.' } } }))
    expect(lines()).toEqual(['Verificarea este oprită', '„Verifică acum” reia verificarea.'])
    expect(stripButtons()).toEqual(['Verifică acum', 'Deconectează'])
  })

  it('переподключить: причина, вход заново и «Deconectează»', async () => {
    await open(list({ google: { ...ON, state: 'reconnect', why: { code: 'gc_g_dead', tone: 'err',
      text: 'Google nu mai acceptă conectarea', detail: 'Conectați din nou contul Google.' },
      can: { connect: true, calendar: false, check: false, disconnect: true } } }))
    expect(lines()).toEqual(['Google nu mai acceptă conectarea', 'Conectați din nou contul Google.'])
    expect(stripButtons()).toEqual(['Conectează contul Google', 'Deconectează'])
  })

  it('Plus › Basic при живой связи: связь видна приглушённо, отключить можно, проверить — нет', async () => {
    await open(list({ google: { ...ON, state: 'plus', plus: PLUS.plus,
      why: { code: 'gc_g_plus_off', tone: 'warn', text: 'Legătura este oprită: face parte din DentPilot Plus',
        detail: 'Contul rămâne conectat' }, can: { ...NO_CAN, disconnect: true } } }))
    expect(gl().querySelector('.gl-dim')?.textContent).toBe('Conectat: clinica@gmail.com · calendarul „Programări”')
    expect(stripButtons()).toEqual(['Deconectează'])
  })

  it('режим чтения: причина и только «Deconectează»', async () => {
    await open(list({ google: { ...ON, state: 'readonly', why: { code: 'gc_g_readonly', tone: 'warn',
      text: 'Oprită în regim de citire', detail: 'Pornește singură după reînnoire.' }, can: { ...NO_CAN, disconnect: true } } }))
    expect(gl().dataset.gl).toBe('readonly')
    expect(stripButtons()).toEqual(['Deconectează'])
  })

  it('«Deconectează» спрашивает словами сервера; отказ ничего не шлёт', async () => {
    await open(list({ google: ON }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(inStrip(/Deconectează/))
    await waitFor(() => expect(confirm).toHaveBeenCalledWith('Deconectați contul Google?'))
    expect(post).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    post.mockResolvedValue(ok(list({ google: google() }), 'gc_g_off', 'Contul Google este deconectat'))
    fireEvent.click(inStrip(/Deconectează/))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/gcal/google/disconnect', {}))
    await waitFor(() => expect(gl().dataset.gl).toBe('off'))
  })

  it('связь работает: возврат в окно перечитывает список — события пришли сами', async () => {
    await open(list({ google: ON }))
    get.mockClear()
    act(() => { window.dispatchEvent(new Event('focus')) })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/gcal', {}))
  })

  it('полоса файла — про файл: события только из Google — «Fișier .ics» и выбор файла, а не «din nou»', async () => {
    const g = { id: 2, kind: 'google', name: 'Programări', loaded_at: '22.11.2026 14:20', loaded_by: 'sistem', service: '' }
    await open(list({ google: ON, source: g, sources: [g] }))
    expect(document.querySelector('.gc-src-l')?.textContent).toBe('Fișier .ics')
    expect(within(document.querySelector('.gc-src') as HTMLElement).getByRole('button', { name: /Alege fișierul/ }))
      .toBeTruthy()
  })
})

describe('gcal: источник полосы файла', () => {
  it('последний файл, а не последний источник вообще', () => {
    const f = { id: 1, kind: 'ics', name: 'Clinica', loaded_at: '', loaded_by: '', service: '' }
    const g = { ...f, id: 2, kind: 'google' }
    expect(fileSource({ source: g, sources: [g, f] })).toBe(f)
    expect(fileSource({ source: g, sources: [g] })).toBeNull()
    expect(fileSource({ source: f })).toBe(f)
  })
})

describe('GcalScreen: перенос пачкой и автоматом', () => {
  const AM = { batch: { go: 2, all: 5, can: true }, sms: { show: true, on: false }, last: null, moves: [] }
  const AUTO = { on: false, can_on: true, can_off: false, stopped: false }
  const SERVICES = [{ key: 'consult', label: 'Consultație' }, { key: 'hygiene', label: 'Igienizare' }]
  const PV = {
    go: [{ id: 6, date: '2026-11-16', time: '14:00–14:30', title: 'Rotaru Ana 069123456', doctor: 'Dr. Activ Trei',
      patient: 'Ana Rotaru', fresh: false, phone: '', link: false },
    { id: 9, date: '2026-11-16', time: '15:00–15:30', title: 'Lungu Dan 069111222 dr Doi', doctor: 'Dr. Activ Doi',
      patient: 'Lungu Dan', fresh: true, phone: '069111222', link: false }],
    stay: [{ id: 5, date: '2026-11-16', time: '11:10–11:40', title: 'Lungu Petru control',
      why: { code: 'a_doctor', text: 'medicul nu se recunoaște în titlu' } }],
    counts: { go: 2, fresh: 1, stay: 1, all: 3 }, service: 'consult', sms: { show: true, on: false },
    auto: false, token: 'tok1',
  }
  const bar = () => document.querySelector('.gcb-bar') as HTMLElement | null
  const dlg = () => document.querySelector('dialog.gcb-dlg[open]') as HTMLElement | null
  const am = (over = {}) => ({ ...AM, ...over })
  const calls = (path: string) => post.mock.calls.filter((c) => String(c[0]).startsWith(path))

  function answer(map: Record<string, unknown>) {
    post.mockImplementation((path: string) => {
      const hit = Object.keys(map).find((k) => path.startsWith(k))
      const v = hit ? map[hit] : undefined
      return v instanceof Error ? Promise.reject(v) : Promise.resolve(v)
    })
  }

  it('полоса над «De mutat» — счёт сервера; на «Mutate» её нет', async () => {
    await open(list({ automove: am(), form: { services: SERVICES } }))
    expect(bar()?.textContent).toContain('2 din 5 evenimente au dată, oră, medic și pacient recunoscuți')
    expect(within(bar() as HTMLElement).getByRole('button', { name: /Mută în jurnal toate cu medic/ })).toBeTruthy()
    cleanup()
    await open(list({ f: 'mutat', automove: am() }))
    expect(bar()).toBeNull()
  })

  it('годных нет — кнопка выключена; с сети (can=false) кнопки нет', async () => {
    await open(list({ automove: am({ batch: { go: 0, all: 3, can: true } }) }))
    expect(bar()?.textContent).toContain('Niciun eveniment din listă nu are medic și pacient recunoscuți')
    expect((within(bar() as HTMLElement).getByRole('button') as HTMLButtonElement).disabled).toBe(true)
    cleanup()
    await open(list({ automove: am({ batch: { go: 2, all: 3, can: false } }) }))
    expect(within(bar() as HTMLElement).queryAllByRole('button')).toEqual([])
  })

  it('предпросмотр: группы и причины — слова сервера; запуск с отпечатком, итог и отмена', async () => {
    await open(list({ automove: am(), form: { services: SERVICES } }))
    const after = list({
      automove: am({ batch: { go: 0, all: 3, can: true },
        moves: [{ key: 'batch:1', when: '22.11.2026 10:32', how: 'batch', by: 'Ana', n: 2, fresh: 1, undone: null }] }),
      batch: { key: 'batch:1', n: 2, fresh: 1, refused: 0 },
    })
    answer({
      '/gcal/batch/check': ok({ preview: PV }),
      '/gcal/batch/run': ok(after, 'gc_a_moved', 'Evenimentele au fost mutate în jurnal'),
      '/gcal/moves/undo': ok(list({ automove: am() }), 'gc_a_undone', 'Mutarea a fost anulată'),
    })
    fireEvent.click(within(bar() as HTMLElement).getByRole('button', { name: /Mută în jurnal toate cu medic/ }))
    await waitFor(() => expect(dlg()?.querySelector('.gcb-table')).not.toBeNull())
    expect(calls('/gcal/batch/check')[0]).toEqual(['/gcal/batch/check', { auto: false }])
    const d = dlg() as HTMLElement
    expect(Array.from(d.querySelectorAll('.gcb-counts b')).map((x) => x.textContent)).toEqual(['2', '1', '1'])
    expect(d.textContent).toContain('fișă nouă Lungu Dan · 069111222')
    expect(d.querySelector('.gcb-why')?.textContent).toBe('medicul nu se recunoaște în titlu')
    fireEvent.click(within(d).getByRole('button', { name: /Mută 2 programări/ }))
    await waitFor(() => expect(bar()?.dataset.bar).toBe('done'))
    expect(calls('/gcal/batch/run')[0]).toEqual(['/gcal/batch/run', { token: 'tok1', auto: false }])
    expect(bar()?.textContent).toContain('2 programări mutate în jurnal, 1 fișă nouă. Rămân 3')
    expect(document.body.textContent).toContain('Evenimentele au fost mutate în jurnal')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(within(bar() as HTMLElement).getByRole('button', { name: /Anulează mutarea/ }))
    await waitFor(() => expect(calls('/gcal/moves/undo')).toHaveLength(1))
    expect(confirm.mock.calls[0]?.[0]).toContain('Anulați mutarea din 22.11.2026 10:32? Se șterg din jurnal 2 programări')
    expect(calls('/gcal/moves/undo')[0]?.[1]).toEqual({ key: 'batch:1' })
    await waitFor(() => expect(bar()?.dataset.bar).toBe('idle'))
  })

  it('список изменился до запуска — слово сервера в окне и предпросмотр заново', async () => {
    await open(list({ automove: am(), form: { services: SERVICES } }))
    answer({
      '/gcal/batch/check': ok({ preview: PV }),
      '/gcal/batch/run': new ApiError({ kind: 'conflict', code: 'gc_a_stale', text: 'Lista s-a schimbat între timp' }, 'x'),
    })
    fireEvent.click(within(bar() as HTMLElement).getByRole('button', { name: /Mută în jurnal toate cu medic/ }))
    await waitFor(() => expect(dlg()?.querySelector('.gcb-table')).not.toBeNull())
    fireEvent.click(within(dlg() as HTMLElement).getByRole('button', { name: /Mută 2 programări/ }))
    await waitFor(() => expect(dlg()?.textContent).toContain('Lista s-a schimbat între timp'))
    await waitFor(() => expect(calls('/gcal/batch/check')).toHaveLength(2))
  })

  it('процедура и SMS в окне — команды вкладки, потом предпросмотр заново', async () => {
    await open(list({ automove: am(), form: { services: SERVICES } }))
    answer({
      '/gcal/batch/check': ok({ preview: PV }),
      '/gcal/source': ok(list({ automove: am() }), 'gc_set'),
      '/gcal/sms': ok(list({ automove: am({ sms: { show: true, on: true } }) }), 'gc_a_sms_on'),
    })
    fireEvent.click(within(bar() as HTMLElement).getByRole('button', { name: /Mută în jurnal toate cu medic/ }))
    await waitFor(() => expect(dlg()?.querySelector('.gcb-table')).not.toBeNull())
    fireEvent.change(dlg()?.querySelector('select') as HTMLSelectElement, { target: { value: 'hygiene' } })
    await waitFor(() => expect(calls('/gcal/batch/check')).toHaveLength(2))
    expect(calls('/gcal/source')[0]?.[1]).toEqual({ service: 'hygiene' })
    fireEvent.click(within(dlg() as HTMLElement).getByRole('checkbox', { name: /SMS de reamintire/ }))
    await waitFor(() => expect(calls('/gcal/batch/check')).toHaveLength(3))
    expect(calls('/gcal/sms')[0]?.[1]).toEqual({ on: true })
  })

  it('строка автопереноса: включение — через окно «Pornește», выключение и SMS — командами', async () => {
    const g = { ...ON, auto: AUTO }
    await open(list({ google: g, automove: am(), form: { services: SERVICES } }))
    const autoRow = () => document.querySelector('.gl-auto') as HTMLElement
    expect(autoRow().textContent).toContain('La pornire vedeți mai întâi ce se mută acum.')
    answer({
      '/gcal/batch/check': ok({ preview: { ...PV, auto: true } }),
      '/gcal/batch/run': ok(list({ google: { ...g, auto: { ...AUTO, on: true, can_off: true } }, automove: am() }),
        'gc_a_auto_on', 'Mutarea automată este pornită'),
      '/gcal/sms': ok(list({ google: g, automove: am({ sms: { show: true, on: true } }) }), 'gc_a_sms_on'),
      '/gcal/auto': ok(list({ google: g, automove: am() }), 'gc_a_auto_off'),
    })
    fireEvent.click(within(autoRow()).getByRole('checkbox', { name: /Mută automat/ }))
    await waitFor(() => expect(dlg()?.getAttribute('aria-label')).toBe('Pornește mutarea automată'))
    await waitFor(() => expect(dlg()?.querySelector('.gcb-table')).not.toBeNull())
    expect(dlg()?.textContent).toContain('De acum, la fiecare verificare (din 10 în 10 minute)')
    expect(calls('/gcal/batch/check')[0]?.[1]).toEqual({ auto: true })
    fireEvent.click(within(dlg() as HTMLElement).getByRole('button', { name: /Mută 2 și pornește/ }))
    await waitFor(() => expect(calls('/gcal/batch/run')[0]?.[1]).toEqual({ token: 'tok1', auto: true }))
    await waitFor(() => expect((autoRow().querySelector('input') as HTMLInputElement).checked).toBe(true))
    expect(bar()?.dataset.bar).toBe('auto')
    fireEvent.click(within(autoRow()).getByRole('checkbox', { name: /Mută automat/ }))
    await waitFor(() => expect(calls('/gcal/auto')[0]?.[1]).toEqual({ on: false }))
    fireEvent.click(within(autoRow()).getByRole('checkbox', { name: /SMS de reamintire/ }))
    await waitFor(() => expect(calls('/gcal/sms')[0]?.[1]).toEqual({ on: true }))
  })

  it('строки нет без связи и пока ждём браузер; на паузе Plus — галочка стоит, полоса говорит «stă»', async () => {
    await open(list({ google: google(), automove: am() }))
    expect(document.querySelector('.gl-auto')).toBeNull()
    cleanup()
    await open(list({ google: { ...ON, waiting: true, auto: AUTO }, automove: am() }))
    expect(document.querySelector('.gl-auto')).toBeNull()
    cleanup()
    const stopped = { ...PLUS, connected: true, auto: { on: true, can_on: false, can_off: true, stopped: true } }
    await open(list({ google: stopped, automove: am({ last: { when: 'azi, 10:40', n: 3 } }) }))
    const autoRow = document.querySelector('.gl-auto') as HTMLElement
    expect(autoRow.textContent).toContain('Stă cât timp legătura este oprită; bifa rămâne.')
    expect(autoRow.textContent).not.toContain('SMS de reamintire')
    expect(bar()?.textContent).toContain('Mutarea automată stă cât timp verificarea Google este oprită')
  })

  it('«Ultima: …» и история: отменённая мутация — словом, отмены у неё нет', async () => {
    const moves = [
      { key: 'auto:2', when: '22.11.2026 10:40', how: 'auto' as const, by: 'sistem', n: 3, fresh: 1, undone: null },
      { key: 'batch:1', when: '21.11.2026 18:20', how: 'batch' as const, by: 'Ana', n: 1, fresh: 0,
        undone: { when: '21.11.2026 18:30', removed: 1, kept: 0, cards: 0 } },
    ]
    await open(list({ google: { ...ON, auto: { ...AUTO, on: true, can_off: true } },
      automove: am({ last: { when: 'azi, 10:40', n: 3 }, moves }) }))
    expect(document.querySelector('.gl-autot')?.textContent).toBe('Ultima: azi, 10:40 — 3 programări.')
    fireEvent.click(within(document.querySelector('.gl-auto') as HTMLElement)
      .getByRole('button', { name: /Istoricul mutărilor/ }))
    await waitFor(() => expect(dlg()?.querySelectorAll('.gcb-hist li')).toHaveLength(2))
    const items = Array.from(dlg()?.querySelectorAll('.gcb-hist li') ?? [])
    expect(items[0]?.textContent).toContain('22.11.2026 10:40 · automat')
    expect(within(items[0] as HTMLElement).getByRole('button', { name: /Anulează mutarea/ })).toBeTruthy()
    expect(items[1]?.textContent).toContain('anulată: 1 șterse')
    expect(within(items[1] as HTMLElement).queryByRole('button')).toBeNull()
  })

  it('строки: «nu se mută singur», «mutat automat», кнопки «schimbat» — по `can` сервера', async () => {
    const stay = row({ auto: { why: { code: 'a_doctor', text: 'medicul nu se recunoaște în titlu' }, how: '', dp: false } })
    const auto = { ...MOVED, auto: { why: null, how: 'auto' as const, dp: false } }
    const cancelled = {
      ...MOVED, id: 11, changed: true, gstatus: 'cancelled' as const, auto: { why: null, how: 'batch' as const, dp: false },
      can: { move: false, link: false, skip: false, back: false, follow: false, cancel_appt: true, keep: true },
    }
    const touched = {
      ...MOVED, id: 12, changed: true, auto: { why: null, how: '' as const, dp: true },
      can: { move: false, link: false, skip: false, back: false, follow: false, cancel_appt: false, keep: true },
    }
    await open(list({ automove: am(), days: [{ date: '2026-11-16', rows: [stay, auto, cancelled, touched] }] }))
    expect(rowEl(5).textContent).toContain('nu se mută singur: medicul nu se recunoaște în titlu')
    expect(rowEl(8).textContent).toContain('mutat automat')
    expect(within(rowEl(11)).getByRole('button', { name: /Anulează programarea/ })).toBeTruthy()
    expect(within(rowEl(11)).queryByRole('button', { name: /Mută și programarea/ })).toBeNull()
    expect(rowEl(12).textContent).toContain('programarea a fost schimbată în DentPilot')
    expect(within(rowEl(12)).getAllByRole('button').map((b) => b.textContent?.trim())).toEqual(['Lasă cum e'])
    answer({ '/gcal/events/11/cancel-appt': ok(list({ automove: am() }), 'gc_a_cancelled', 'Programarea a fost anulată') })
    fireEvent.click(within(rowEl(11)).getByRole('button', { name: /Anulează programarea/ }))
    await waitFor(() => expect(calls('/gcal/events/11/cancel-appt')).toHaveLength(1))
  })
})
