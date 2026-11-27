import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { AddDialog } from './AddDialog'
import { SlotDialog } from './SlotDialog'
import type { DayForm } from './day'
import { splitDigits, type PickRow } from './PatientPick'

/* Выбор существующей фиши в окне записи: повторного пациента не вписывают заново.
   Окно шапки «Programare nouă» целиком: поиск в поле имени, «Recenți», подсказки совпадений,
   клавиши, плашка выбранной фиши и тело записи. Сеть — подменой `api`. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post } }
})

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })

const FORM: DayForm = {
  doctors: [{ id: 'd2', name: 'Dr. Activ Doi', spec: '' }],
  times: { d2: ['09:00', '10:00'] },
  hours: ['09:00', '10:00'],
  services: [{ id: 'consult', label: 'Consultație' }],
  doctor: 'd2', time: '09:00', birth_max: '2026-11-27',
}

const ION: PickRow = { id: 41, name: 'Ion Popescu', phone: '069123456', year: '1985', file_no: '142', last: '14.10.2026' }
const IRINA: PickRow = { id: 42, name: 'Irina Popescu', phone: '069123456', year: '2015', file_no: '', last: '' }
const ANA: PickRow = { id: 7, name: 'Ana Rusu', phone: '078555210', year: '', file_no: '', last: '02.09.2026' }

const PH = 'Nume, telefon sau nr. fișei'
const nameField = () => document.querySelector(`dialog input[placeholder="${PH}"]`) as HTMLInputElement | null
const phoneField = () => document.querySelector('dialog input[placeholder="Telefon"]') as HTMLInputElement
const listbox = () => document.querySelector('[role="listbox"]')

function net({ found = [ION, IRINA], recent = [ANA], match = { phone: null, name: [] } as
  { phone: PickRow | null; name: PickRow[] } } = {}) {
  get.mockImplementation((path: string) => path.startsWith('/patients?')
    ? Promise.resolve(ok({ rows: found })) : Promise.reject(new Error(path)))
  post.mockImplementation((path: string) => {
    if (path === '/schedule/pick/recent') return Promise.resolve(ok({ rows: recent }))
    if (path === '/schedule/pick/match') return Promise.resolve(ok(match))
    return Promise.reject(new Error(path))
  })
}

function mount(here?: number) {
  const onAdd = vi.fn().mockResolvedValue(true)
  const onClose = vi.fn()
  render(<AddDialog open form={FORM} date="2026-11-30" of="" busy={false} onClose={onClose} onAdd={onAdd} here={here} />)
  return { onAdd, onClose }
}

async function type(el: HTMLInputElement, value: string) {
  await act(async () => { fireEvent.focus(el); fireEvent.change(el, { target: { value } }) })
}

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('PatientPick: выбор фиши в окне записи', () => {
  it('набор от двух знаков ищет поиском картотеки; выбор — плашка, телефон фиши закрыт, дата рождения прячется с местом', async () => {
    net()
    const { onAdd } = mount()
    await type(nameField() as HTMLInputElement, 'pope')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/patients?q=pope&per=10', expect.anything()))
    const opts = await waitFor(() => {
      const o = within(listbox() as HTMLElement).getAllByRole('option')
      expect(o).toHaveLength(3)
      return o
    })
    expect(opts[0]?.textContent).toContain('Ion Popescu')
    expect(opts[0]?.textContent).toContain('069123456 · n. 1985 · ultima: 14.10.2026')
    expect(opts[0]?.textContent).toContain('dosar 142')
    expect(opts[1]?.textContent).toContain('fără vizite')
    expect(opts[2]?.textContent).toBe('+ Pacient nou „pope”')
    await act(async () => { fireEvent.click(opts[0] as HTMLElement) })
    expect(nameField()).toBeNull()
    const chip = screen.getByRole('group', { name: 'Ion Popescu' })
    expect(chip.textContent).toContain('069123456 · n. 1985 · dosar 142')
    expect(phoneField().value).toBe('069123456')
    expect(phoneField().disabled).toBe(true)
    const birth = Array.from(document.querySelectorAll('dialog label')).find((l) => l.textContent?.includes('Data nașterii'))
    expect(birth?.classList.contains('dp-pick-off')).toBe(true)
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLFormElement) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ pid: 41, name: 'Ion Popescu', phone: '069123456', nophone: false })
  })

  it('«Alt pacient» снимает выбор: снова пустое поле, запись без номера фиши', async () => {
    net()
    const { onAdd } = mount()
    await type(nameField() as HTMLInputElement, 'pope')
    const first = await waitFor(() => {
      const o = within(listbox() as HTMLElement).getAllByRole('option')
      expect(o).toHaveLength(3)
      return o[0] as HTMLElement
    })
    await act(async () => { fireEvent.click(first) })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Alt pacient/ })) })
    expect(nameField()?.value).toBe('')
    expect(phoneField().disabled).toBe(false)
    await type(nameField() as HTMLInputElement, 'Pacient Nou')
    await act(async () => { fireEvent.change(phoneField(), { target: { value: '060111222' } }) })
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLFormElement) })
    const body = onAdd.mock.calls[0]?.[0] as Record<string, unknown>
    expect(body).toMatchObject({ name: 'Pacient Nou', phone: '060111222' })
    expect('pid' in body).toBe(false)
  })

  it('пустое поле — «Recenți» по щелчку (не по фокусу), фиша экрана первой; сама в окно не подставляется', async () => {
    net({ recent: [ION, ANA] })
    mount(41)
    await act(async () => { fireEvent.focus(nameField() as HTMLInputElement) })
    expect(listbox()).toBeNull()
    await act(async () => { fireEvent.click(nameField() as HTMLInputElement) })
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/pick/recent', { here: 41 }, expect.anything()))
    const list = await waitFor(() => listbox() as HTMLElement)
    expect(list.textContent).toContain('Recenți')
    const opts = within(list).getAllByRole('option')
    expect(opts.map((o) => o.textContent?.includes('fișa deschisă'))).toEqual([true, false])
    expect(nameField()?.value).toBe('')
    expect(screen.queryByRole('group', { name: 'Ion Popescu' })).toBeNull()
  })

  it('клавиши: ↓ и Enter выбирают фишу; Esc закрывает список, а не окно', async () => {
    net()
    const { onClose } = mount()
    const field = nameField() as HTMLInputElement
    await type(field, 'pope')
    await waitFor(() => expect(within(listbox() as HTMLElement).getAllByRole('option')).toHaveLength(3))
    const esc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(esc) })
    expect(esc.defaultPrevented).toBe(true)
    expect(listbox()).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
    await act(async () => { fireEvent.keyDown(field, { key: 'ArrowDown' }) })
    await waitFor(() => expect(listbox()).not.toBeNull())
    await act(async () => { fireEvent.keyDown(field, { key: 'ArrowDown' }) })
    await act(async () => { fireEvent.keyDown(field, { key: 'Enter' }) })
    expect(screen.getByRole('group', { name: 'Irina Popescu' })).toBeTruthy()
  })

  it('Enter на «+ Pacient nou» отправляет окно, как до списка', async () => {
    net({ found: [] })
    const { onAdd } = mount()
    const field = nameField() as HTMLInputElement
    await type(field, 'Vasile Lupu')
    await act(async () => { fireEvent.change(phoneField(), { target: { value: '060777888' } }) })
    await waitFor(() => expect(listbox()?.textContent).toContain('Nicio fișă găsită'))
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    await act(async () => { field.dispatchEvent(enter) })
    expect(enter.defaultPrevented).toBe(false)
    expect(onAdd).not.toHaveBeenCalled()
  })

  it('номер в поле имени: «+ Pacient nou» уносит его в «Telefon»', async () => {
    net({ found: [] })
    mount()
    await type(nameField() as HTMLInputElement, 'Vasile 069 77 09 99')
    const add = await waitFor(() => within(listbox() as HTMLElement).getByRole('option', { name: /Pacient nou/ }))
    await act(async () => { fireEvent.click(add) })
    expect(nameField()?.value).toBe('Vasile')
    expect(phoneField().value).toBe('069 77 09 99')
  })

  it('совпал телефон — кнопка «Fișă existentă» в поле телефона; нажатие выбирает фишу', async () => {
    net({ match: { phone: ION, name: [] } })
    mount()
    await act(async () => { fireEvent.change(phoneField(), { target: { value: '+373 69 123 456' } }) })
    const hit = await screen.findByRole('button', { name: /Fișă existentă: Ion Popescu/ })
    expect(post).toHaveBeenCalledWith('/schedule/pick/match', { phone: '+373 69 123 456', name: '' }, expect.anything())
    await act(async () => { fireEvent.click(hit) })
    expect(screen.getByRole('group', { name: 'Ion Popescu' })).toBeTruthy()
  })

  it('совпало имя — «Există fișa: X» в поле имени; две фиши — число и список', async () => {
    net({ match: { phone: null, name: [ION] } })
    mount()
    const field = nameField() as HTMLInputElement
    await type(field, 'Popescu Ion')
    await act(async () => { fireEvent.blur(field) })
    const hit = await screen.findByRole('button', { name: /Există fișa: Ion Popescu/ })
    await act(async () => { fireEvent.click(hit) })
    expect(screen.getByRole('group', { name: 'Ion Popescu' })).toBeTruthy()
    cleanup()
    net({ match: { phone: null, name: [ION, IRINA] } })
    mount()
    const f2 = nameField() as HTMLInputElement
    await type(f2, 'Popescu')
    await act(async () => { fireEvent.blur(f2) })
    expect((await screen.findByRole('button', { name: /2 fișe cu acest nume/ }))).toBeTruthy()
  })

  it('окно свободного часа: выбранная фиша уходит номером, имя и телефон — её', async () => {
    net()
    const onAdd = vi.fn().mockResolvedValue(true)
    render(<SlotDialog open slot={{ dk: 'd2', name: 'Dr. Ion', hour: '10:00' }} date="2026-11-30"
      form={{ services: [{ id: 'consult', label: 'Consultație' }], birth_max: '2026-11-27' }} noteEnds={[11]}
      taken={[]} busy={false} onClose={vi.fn()} onAdd={onAdd} onNote={vi.fn()} />)
    await type(nameField() as HTMLInputElement, 'pope')
    const opts = await waitFor(() => {
      const o = within(listbox() as HTMLElement).getAllByRole('option')
      expect(o).toHaveLength(3)
      return o
    })
    await act(async () => { fireEvent.click(opts[1] as HTMLElement) })
    expect(phoneField().disabled).toBe(true)
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLFormElement) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ pid: 42, name: 'Irina Popescu', phone: '069123456', time: '10:00' })
  })

  it('номер из имени выделяется только от шести цифр', () => {
    expect(splitDigits('Ion 069123456')).toEqual({ name: 'Ion', phone: '069123456' })
    expect(splitDigits('+373 69 12 34 56')).toEqual({ name: '', phone: '+373 69 12 34 56' })
    expect(splitDigits('Ion 12345')).toEqual({ name: 'Ion 12345', phone: '' })
  })
})
