import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { DayScreen } from './DayScreen'
import type { DayModel } from './day'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const appt = (id: number, time: string, name: string, extra = {}) => ({
  kind: 'appt' as const, id, time, name, service: 'Consultație',
  phone: '069000000', status: 'confirmed', status_label: 'Confirmat',
  urgent: false, source: 'panel', dur: 60, comment: '', age: null,
  clickable: true, bg: 'var(--green-soft)', bar: 'var(--green)',
  min: 600, busy: true, movable: true, ...extra,
})

const LONG = 'Alergie la penicilină; de sunat cu o zi înainte; vine cu mama; dimineața'

/* ⛔ Две колонки, и вторая пустая в 09:00: если ячейки раскладывать не по
   позиции в списке врачей, запись переедет к соседу — и это выглядит нормально. */
const MODEL: DayModel = {
  date: '2026-09-23',
  doctors: [
    { id: 'd2', name: 'Dr. Activ Doi', spec: 'Terapeut' },
    { id: 'd3', name: 'Dr. Activ Trei', spec: 'Ortodont · inactiv' },
  ],
  hours: [
    {
      h: 9, label: '09:00', closed: '', now: false, cells: [
        { kind: 'appts', drop: true, items: [appt(1, '09:00', 'Ion Popa', { min: 540 })] },
        { kind: 'free', drop: true, items: [] },
      ],
    },
    {
      h: 10, label: '10:00', closed: '', now: true, cells: [
        { kind: 'busy', drop: true, items: [] },
        {
          kind: 'appts', drop: true, items: [appt(2, '10:00', 'Maria Rusu', {
            status: 'noshow', status_label: 'Nu s-a prezentat', urgent: true,
            service: 'Durere acută', age: 36, comment: 'sună înainte',
            bg: 'var(--red-soft)', bar: 'var(--red)', movable: false, busy: false,
          })],
        },
      ],
    },
    {
      h: 13, label: '13:00', closed: 'pauza', now: false, cells: [
        { kind: 'off', drop: false, items: [] },
        { kind: 'off', drop: false, items: [] },
      ],
    },
    {
      h: 19, label: '19:00', closed: 'inchis', now: false, cells: [
        { kind: 'appts', drop: false, items: [{ kind: 'note', id: 9, time: '19:00', text: 'Livrare', min: 1140, dur: 60, busy: false, movable: false }] },
        { kind: 'off', drop: false, items: [] },
      ],
    },
  ],
  form: {
    doctors: [{ id: 'd2', name: 'Dr. Activ Doi', spec: '' },
      { id: 'd4', name: 'Dr. Activ Patru', spec: '' }],
    times: { d2: ['09:00', '09:30', '10:00'], d4: ['14:00', '14:30'] },
    hours: ['09:00', '09:30', '10:00', '14:00', '14:30'],
    services: [{ id: 'consult', label: 'Consultație' }, { id: 'pain', label: 'Durere acută' }],
    doctor: 'd2', time: '', birth_max: '2026-09-19',
  },
  note_ends: [10, 11, 12, 15],
  cards: {
    1: { name: 'Ion Popa', phone: '069000000', service: 'Consultație',
      doctor: 'Dr. Activ Doi', time: '09:00', comment: LONG, age: 41,
      st: 'confirmed', pid: 7, rec: false },
    2: { name: 'Maria Rusu', phone: '069000001', service: 'Durere acută',
      doctor: 'Dr. Activ Trei', time: '10:00', comment: '', age: 36,
      st: 'noshow', pid: 8, rec: true },
  },
  actions: {
    confirmed: [{ to: 'waiting', cls: 'b-waiting', label: 'A venit', confirm: '' },
      { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' }],
    noshow: [{ to: 'confirmed', cls: 'b-reopen', label: 'Redeschide',
      confirm: 'Redeschideți programarea (înapoi la «confirmată»)?' }],
  },
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: 'ok', text: 'Programare adăugată', tone: 'ok' })
const rows = () => Array.from(document.querySelectorAll('tr.hrow'))
const cellsOf = (i: number) => Array.from(rows()[i]?.querySelectorAll('td') ?? []).slice(1)
const dt = () => ({ setData: vi.fn(), dropEffect: '', effectAllowed: '' })

/* ⚠️ Координату броска приходится доставлять руками: jsdom не знает DragEvent,
   и fireEvent.drop({clientY}) роняет её по дороге — обработчик получает
   undefined, а половина часа считается ИМЕННО по ней. Мышиное событие с тем
   же именем доносит и координату, и объект переноса. */
const fireAt = (el: Element, type: string, y: number) => {
  const ev = new MouseEvent(type, { clientY: y, bubbles: true, cancelable: true })
  Object.defineProperty(ev, 'dataTransfer', { value: dt() })
  act(() => { el.dispatchEvent(ev) })
}

/* jsdom всем элементам возвращает нулевой прямоугольник, а половина часа
   считается ИМЕННО по нему: без подмены любой бросок оказывался бы на :30. */
const RECT = { top: 100, height: 60, bottom: 160, left: 0, right: 0, width: 0,
  x: 0, y: 100, toJSON: () => ({}) }

beforeEach(() => {
  get.mockResolvedValue(ok(MODEL))
  vi.spyOn(HTMLTableCellElement.prototype, 'getBoundingClientRect')
    .mockReturnValue(RECT as DOMRect)
})
afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); vi.restoreAllMocks() })

const show = async (props: { date?: string; doctor?: string } = {}) => {
  render(<DayScreen date={props.date ?? ''} doctor={props.doctor ?? ''} navigate={() => {}} />)
  await waitFor(() => expect(rows().length).toBeGreaterThan(0))
}

describe('день журнала: чтение', () => {
  it('колонки — врачи сервера, с подписями и ссылкой в их день', async () => {
    await show()
    const heads = Array.from(document.querySelectorAll('.dh-n'))
    expect(heads.map((h) => h.textContent)).toEqual(['Dr. Activ Doi', 'Dr. Activ Trei'])
    expect(heads[0]?.getAttribute('href')).toBe('/admin/doctor/d2?date=2026-09-23')
    expect(document.querySelectorAll('.dh-s')[1]?.textContent).toContain('inactiv')
  })

  it('запись стоит в колонке своего врача, у соседа в этот час «+»', async () => {
    await show()
    const c = cellsOf(0)
    expect(c[0]?.querySelector('[data-appt="1"]')).toBeTruthy()
    expect(c[1]?.querySelector('.free')).toBeTruthy()
  })

  it('закрытый час называет себя, и ячейки в нём пустые', async () => {
    await show()
    expect(rows()[2]?.querySelector('.hour')?.textContent).toContain('pauză')
    expect(rows()[3]?.querySelector('.hour')?.textContent).toContain('închis')
    expect(cellsOf(2).every((td) => td.className === 'goff')).toBe(true)
  })

  it('час под длинным визитом говорит «занято», а не «+»', async () => {
    await show()
    const c = cellsOf(1)
    expect(c[0]?.textContent).toContain('ocupat')
    expect(c[0]?.querySelector('.free')).toBeNull()
  })

  it('текущий час подсвечен ровно один раз', async () => {
    await show()
    expect(document.querySelectorAll('tr.hrow.now')).toHaveLength(1)
    expect(rows()[1]?.className).toContain('now')
  })

  it('карточка несёт слово статуса сервера, срочность, возраст и комментарий', async () => {
    await show()
    const card = cellsOf(1)[1]?.querySelector('[data-appt="2"]')
    expect(card?.className).toContain('noshow')
    expect(card?.className).toContain('urgent')
    expect(card?.textContent).toContain('Nu s-a prezentat')   // а не «noshow»
    expect(card?.textContent).toContain('36 a.')
    expect(card?.textContent).toContain('sună înainte')
    expect(card?.textContent).toContain('(60′)')
  })

  it('заметка стойки — своим видом и без телефона', async () => {
    await show()
    const note = cellsOf(3)[0]?.querySelector('[data-appt="9"]')
    expect(note?.className).toContain('note')
    expect(note?.textContent).toContain('Livrare')
    expect(note?.textContent).not.toContain('069000000')
  })

  it('соседний день запрашивается у сервера', async () => {
    await show({ date: '2026-09-23' })
    fireEvent.click(document.querySelectorAll('.nav a')[0] as HTMLElement)
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      '/schedule/day?date=2026-09-22', expect.anything()))
  })

  it('день врача просит только его записи', async () => {
    await show({ doctor: 'd2' })
    expect(get).toHaveBeenCalledWith('/schedule/day?doctor=d2', expect.anything())
  })
})

describe('форма записи', () => {
  it('врачи и часы — из формы сервера, а не из колонок сетки', async () => {
    await show()
    const sel = (i: number) => document.querySelectorAll('form.add select')[i] as HTMLSelectElement
    expect(Array.from(sel(1).options).map((o) => o.value)).toEqual(['d2', 'd4'])
    expect(Array.from(sel(0).options).map((o) => o.value)).toEqual(['09:00', '09:30', '10:00'])
  })

  it('смена врача переписывает часы', async () => {
    await show()
    const sel = (i: number) => document.querySelectorAll('form.add select')[i] as HTMLSelectElement
    fireEvent.change(sel(1), { target: { value: 'd4' } })
    expect(Array.from(sel(0).options).map((o) => o.value)).toEqual(['14:00', '14:30'])
  })

  it('галочка «fără telefon» гасит поле и снимает требование', async () => {
    await show()
    const form = document.querySelector('form.add') as HTMLFormElement
    const phone = form.querySelector('input[placeholder="Telefon"]') as HTMLInputElement
    expect(phone.required).toBe(true)
    fireEvent.click(form.querySelector('.nophone input') as HTMLElement)
    expect(phone.disabled).toBe(true)
    expect(phone.required).toBe(false)
  })

  it('отправка шлёт выбранное и показывает плашку сервера', async () => {
    post.mockResolvedValue(ok(MODEL))
    await show()
    const form = document.querySelector('form.add') as HTMLFormElement
    fireEvent.change(form.querySelector('input[placeholder="Nume pacient"]') as HTMLElement,
      { target: { value: 'Vasile Lupu' } })
    fireEvent.change(form.querySelector('input[placeholder="Telefon"]') as HTMLElement,
      { target: { value: '069112233' } })
    fireEvent.submit(form)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments', {
      date: '2026-09-23', time: '09:00', doctor: 'd2', service: 'consult',
      name: 'Vasile Lupu', phone: '069112233', nophone: false, birth: '',
    }))
    await waitFor(() => expect(document.querySelector('.toastbox')?.textContent)
      .toContain('Programare adăugată'))
  })

  it('у выключенного врача формы нет вовсе', async () => {
    get.mockResolvedValue(ok({ ...MODEL, form: null }))
    await show({ doctor: 'd3' })
    expect(document.querySelector('form.add')).toBeNull()
  })
})

describe('диалог «+»', () => {
  const openSlot = async () => {
    await show()
    fireEvent.click(cellsOf(0)[1]?.querySelector('.free') as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  it('открывается на своей ячейке: врач в заголовке, час ровный', async () => {
    await openSlot()
    expect(document.querySelector('.dlg-head span')?.textContent)
      .toBe('Dr. Activ Trei — 09:00')
    expect(document.querySelectorAll('.halfpick .hp')[0]?.className).toContain('on')
  })

  it('получас меняет ТОЛЬКО время записи', async () => {
    post.mockResolvedValue(ok(MODEL))
    await openSlot()
    fireEvent.click(document.querySelectorAll('.halfpick .hp')[1] as HTMLElement)
    expect(document.querySelector('.dlg-head span')?.textContent).toContain('09:30')
    fireEvent.change(document.querySelector('.dlg-form input[placeholder="Nume pacient"]') as HTMLElement,
      { target: { value: 'Ana' } })
    fireEvent.change(document.querySelector('.dlg-form input[placeholder="Telefon"]') as HTMLElement,
      { target: { value: '069111222' } })
    fireEvent.submit(document.querySelector('.dlg-form') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments',
      expect.objectContaining({ time: '09:30', doctor: 'd3' })))
  })

  it('вкладка заметки предлагает только концы ПОЗЖЕ начала и шлёт голый час', async () => {
    post.mockResolvedValue(ok(MODEL))
    await openSlot()
    fireEvent.click(document.querySelectorAll('.tabbtn')[1] as HTMLElement)
    const until = document.querySelector('.dlg-form select') as HTMLSelectElement
    expect(Array.from(until.options).map((o) => o.value)).toEqual(['10', '11', '12', '15'])
    fireEvent.change(document.querySelector('.dlg-form input') as HTMLElement,
      { target: { value: 'Ședință' } })
    fireEvent.change(until, { target: { value: '12' } })
    fireEvent.submit(document.querySelector('.dlg-form') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/notes', {
      date: '2026-09-23', time: '09:00', doctor: 'd3', text: 'Ședință', until: 12,
    }))
  })
})

describe('карточка визита', () => {
  const openCard = async (id: number, row = 0, col = 0) => {
    await show()
    fireEvent.click(cellsOf(row)[col]?.querySelector(`[data-appt="${id}"]`) as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  it('правится ПОЛНЫЙ комментарий, а не обрезанный в сетке', async () => {
    await openCard(1)
    expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe(LONG)
    expect(cellsOf(0)[0]?.querySelector('.cmt')).toBeNull()   // в сетке его нет вовсе
  })

  it('кнопки исхода — те, что прислал сервер для этого состояния', async () => {
    await openCard(1)
    expect(Array.from(document.querySelectorAll('.dlg-status button'))
      .map((b) => b.textContent?.trim())).toEqual(['A venit', 'Finalizat'])
  })

  it('возврат закрытой записи спрашивает подтверждение', async () => {
    post.mockResolvedValue(ok(MODEL))
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await openCard(2, 1, 1)
    fireEvent.submit(document.querySelector('.dlg-status form') as HTMLFormElement)
    expect(ask).toHaveBeenCalledWith('Redeschideți programarea (înapoi la «confirmată»)?')
    expect(post).not.toHaveBeenCalled()
  })

  it('дневник визита: слово зависит от того, заполнен ли он', async () => {
    await openCard(1)
    expect(document.querySelectorAll('.dp-card-link')[1]?.textContent)
      .toContain('Completează')
    cleanup()
    await openCard(2, 1, 1)
    expect(document.querySelectorAll('.dp-card-link')[1]?.textContent).toContain('Vezi')
  })

  it('комментарий уходит на сервер вместе с id записи', async () => {
    post.mockResolvedValue(ok(MODEL))
    await openCard(1)
    fireEvent.change(document.querySelector('textarea') as HTMLElement,
      { target: { value: 'Nou' } })
    fireEvent.submit(document.querySelector('.dp-card-cmt') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/comment', { comment: 'Nou' }))
  })
})

describe('перетаскивание', () => {
  const dragTo = async (row: number, col: number, y: number) => {
    const src = cellsOf(0)[0]?.querySelector('[data-appt="1"]') as HTMLElement
    fireEvent.dragStart(src, { dataTransfer: dt() })
    const cell = cellsOf(row)[col] as HTMLElement
    fireAt(cell, 'dragover', y)
    fireAt(cell, 'drop', y)
  }

  it('закрытый визит не тащится вовсе', async () => {
    await show()
    const done = cellsOf(1)[1]?.querySelector('[data-appt="2"]') as HTMLElement
    expect(done.getAttribute('draggable')).toBeNull()
    expect(done.getAttribute('data-mv')).toBeNull()
  })

  it('бросок в верх ячейки даёт ровный час, в низ — половину', async () => {
    await show()
    await dragTo(1, 0, 110)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelectorAll('.mv-rows b')[2]?.textContent)
      .toBe('Dr. Activ Doi · 10:00')
    fireEvent.click(document.querySelector('.mv-no') as HTMLElement)

    await dragTo(1, 0, 150)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelectorAll('.mv-rows b')[2]?.textContent)
      .toBe('Dr. Activ Doi · 10:30')
  })

  it('диалог говорит, КОГО и ОТКУДА двигают', async () => {
    await show()
    await dragTo(1, 0, 110)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    const b = document.querySelectorAll('.mv-rows b')
    expect([b[0]?.textContent, b[1]?.textContent])
      .toEqual(['Ion Popa', 'Dr. Activ Doi · 09:00'])
  })

  it('БРОСОК НА СВОЁ ЖЕ МЕСТО диалога не открывает и запроса не шлёт', async () => {
    await show()
    await dragTo(0, 0, 110)
    expect(document.querySelector('.mv-rows')).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })

  it('закрытый час не принимает бросок', async () => {
    await show()
    await dragTo(2, 0, 110)
    expect(document.querySelector('.mv-rows')).toBeNull()
  })

  it('подтверждение шлёт час, врача и дату экрана', async () => {
    post.mockResolvedValue(ok(MODEL))
    await show()
    await dragTo(1, 0, 150)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    fireEvent.click(document.querySelectorAll('.mv-act button')[1] as HTMLElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments/1/move',
      { date: '2026-09-23', time: '10:30', doctor: 'd2' }))
  })

  it('занятый интервал предупреждает и не даёт подтвердить', async () => {
    get.mockResolvedValue(ok({
      ...MODEL,
      hours: MODEL.hours.map((h) => (h.h !== 10 ? h : {
        ...h,
        cells: [{ kind: 'appts' as const, drop: true,
          items: [appt(5, '10:00', 'Ocupa Ora', { min: 600 })] }, h.cells[1]!],
      })),
    }))
    await show()
    await dragTo(1, 0, 110)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelector('.banner.err')?.textContent)
      .toContain('Medicul are deja o programare la 10:00.')
    expect((document.querySelectorAll('.mv-act button')[1] as HTMLButtonElement).disabled)
      .toBe(true)
  })
})
