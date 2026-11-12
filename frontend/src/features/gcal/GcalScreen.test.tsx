import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { openScreen } from '../../test/openScreen'
import type { DashMiniCal } from '../schedule/dash'
import type { DayForm } from '../schedule/day'
import { GcalScreen, loadGcal } from './GcalScreen'
import { firstLine, presetOf, queryOf, spanOf, whereOf, type GcalList, type GcalRow } from './gcal'

/* Вкладка «Google Calendar»: пустой экран и загрузка файла с итогом словами,
   список по дням, отбор и поиск, перенос обычным окном записи (заполнение,
   выбор врача человеком, фиша по номеру, отказ в окне), «Nu muta» и возврат,
   пометка изменившегося, «Șterge tot» только с правом. */

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
