import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../types/api'
import { CAN_DOC, form, list, ok, order, row } from '../../test/lab'
import { LabListScreen } from './LabListScreen'

/* Список «Laborator»: строки и фильтры с сервера, шаги строки — словами
   сервера, этап и переделка — своими окнами, новый заказ — пациент поиском,
   окно по `/api/lab/form`, цена — только с правом на деньги. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const nav = vi.fn()
function open(url = '/admin/lab') {
  const router = createMemoryRouter([{ path: '/admin/lab', element: <LabListScreen navigate={nav} /> }], { initialEntries: [url] })
  render(<RouterProvider router={router} />)
  return router
}

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); nav.mockReset(); vi.restoreAllMocks() })

describe('LabListScreen', () => {
  it('строки: опоздание красным, визит без работы, цена с правом на деньги, пустые фильтры спрятаны', async () => {
    get.mockResolvedValue(ok(list([
      row(),
      row({ id: 2, nr: 44, patient: 'Elena Cara', late: false, due_in: 1, visit_wait: true,
        next_appt: { id: 9, starts_at: '', date: '2026-11-15', time: '09:30', doctor: 'Dr. Elena Rusu', day: 'maine' } }),
    ])))
    open()
    const tr = (await screen.findByText('Ion Popescu')).closest('tr')!
    expect(tr.className).toContain('lb-late-r')
    expect(tr.textContent).toContain('Întârziat')
    expect(tr.textContent).toContain('2 zile în urmă')
    expect(tr.textContent).toContain('1.800')
    const tr2 = screen.getByText('Elena Cara').closest('tr')!
    expect(tr2.className).toContain('lb-warn-r')
    expect(tr2.textContent).toContain('mâine')
    expect(tr2.textContent).toContain('09:30')
    expect(screen.getByRole('tab', { name: /Programare fără lucrare/ })).toBeTruthy()
    expect(screen.queryByRole('tab', { name: /De ridicat/ })).toBeNull()
    expect(screen.getByRole('columnheader', { name: 'Preț lab.' })).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/lab', expect.anything())
  })

  it('без права на деньги — ни колонки, ни суммы', async () => {
    const r = row()
    delete r.total_bani
    get.mockResolvedValue(ok(list([r], { can: CAN_DOC })))
    open()
    await screen.findByText('Ion Popescu')
    expect(screen.queryByRole('columnheader', { name: 'Preț lab.' })).toBeNull()
    expect(document.body.textContent).not.toContain('preț laborator')
  })

  it('фильтр — в адрес и в запрос', async () => {
    get.mockResolvedValue(ok(list([row()])))
    const router = open()
    await screen.findByText('Ion Popescu')
    fireEvent.click(screen.getByRole('tab', { name: /Întârziate/ }))
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/lab?f=intarziate', expect.anything()))
    expect(router.state.location.search).toBe('?f=intarziate')
  })

  it('главный шаг строки — команда сервера, потом список перечитан; отказ — словами сервера', async () => {
    get.mockResolvedValue(ok(list([row()])))
    post.mockResolvedValueOnce(ok(null, 'ok_lab_step', 'Pasul e notat'))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'lab_step', text: 'Pasul nu se potrivește' }, 'c'))
    open()
    const tr = (await screen.findByText('Ion Popescu')).closest('tr')!
    fireEvent.click(within(tr).getByRole('button', { name: /E gata/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/lab/order/1/step', { to: 'gata', note: '' }))
    expect(await screen.findByText('Pasul e notat')).toBeTruthy()
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    fireEvent.click(within(screen.getByText('Ion Popescu').closest('tr')!).getByRole('button', { name: /E gata/ }))
    expect(await screen.findByText('Pasul nu se potrivește')).toBeTruthy()
  })

  it('после примерки: «Refacere» — причина и кто платит обязательны, уходят в тело', async () => {
    const steps = [{ act: 'finalizat' as const, label: 'Finalizează', main: true }, { act: 'etapa' as const, label: 'Etapa următoare', main: false },
      { act: 'refacere' as const, label: 'Refacere', main: false }]
    get.mockImplementation((url: string) => Promise.resolve(url.startsWith('/lab/form') ? ok(form()) : ok(list([row({ status: 'proba', status_label: 'La probă', late: false, steps })]))))
    post.mockResolvedValue(ok(null, 'ok_lab_refacere', 'Trimis la refacere'))
    open()
    const tr = (await screen.findByText('Ion Popescu')).closest('tr')!
    expect(within(tr).getByRole('button', { name: /Etapa următoare/ })).toBeTruthy()
    fireEvent.click(within(tr).getByRole('button', { name: /Refacere/ }))
    const dlg = await screen.findByRole('dialog', { name: /Refacere/ })
    fireEvent.click(await within(dlg).findByRole('button', { name: 'Ocluzie' }))
    fireEvent.click(within(dlg).getByRole('button', { name: 'Laboratorul (garanție)' }))
    fireEvent.change(within(dlg).getByRole('textbox'), { target: { value: 'contact înalt pe 26' } })
    fireEvent.click(within(dlg).getByRole('button', { name: /Trimite la refacere/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/lab/order/1/refacere',
      { cause: 'ocluzie', payer: 'laborator', due_on: '', note: 'contact înalt pe 26' }))
  })

  it('отмена заказа спрашивает причину', async () => {
    get.mockImplementation((url: string) => Promise.resolve(url.startsWith('/lab/order/')
      ? ok({ order: order(), steps: [{ act: 'cancel', label: 'Anulează comanda', main: false }], can: CAN_DOC })
      : url.startsWith('/lab/form') ? ok(form()) : ok(list([row()]))))
    post.mockResolvedValue(ok(null, 'ok_lab_cancel', 'Comanda e anulată'))
    open()
    fireEvent.click(within((await screen.findByText('Ion Popescu')).closest('tr')!).getByRole('button', { name: /Deschide comanda/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Comandă la laborator' })
    fireEvent.click(within(dlg).getByRole('button', { name: /Anulează comanda/ }))
    const why = await screen.findByRole('dialog', { name: 'Anulează comanda' })
    fireEvent.click(within(why).getByRole('button', { name: /Anulează comanda/ }))
    expect(post).not.toHaveBeenCalled()
    fireEvent.change(within(why).getByRole('textbox'), { target: { value: 'pacientul a amânat' } })
    fireEvent.click(within(why).getByRole('button', { name: /Anulează comanda/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/lab/order/1/cancel', { why: 'pacientul a amânat' }))
  })

  it('новый заказ из списка: пациент поиском, окно по форме сервера, две работы одним заказом', async () => {
    get.mockImplementation((url: string) => {
      if (url.startsWith('/patients?')) return Promise.resolve(ok({ rows: [{ id: 2, name: 'Ion Popescu', phone: '069' }] }))
      if (url.startsWith('/lab/form')) return Promise.resolve(ok(form()))
      if (url.startsWith('/lab/due')) return Promise.resolve(ok({ due_on: '2026-11-25' }))
      return Promise.resolve(ok(list([])))
    })
    post.mockResolvedValue(ok({ id: 7, nr: 45 }, 'ok_lab_new', 'Comanda nr. 45 e trimisă'))
    open()
    fireEvent.click(await screen.findByRole('button', { name: /Prima comandă/ }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Pacient' }), { target: { value: 'Ion' } })
    fireEvent.click(await screen.findByRole('button', { name: /Ion Popescu/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Comandă la laborator' })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/lab/form?pid=2', expect.anything()))
    fireEvent.change(within(dlg).getAllByRole('combobox')[0]!, { target: { value: 'Coroană' } })
    fireEvent.click(within(dlg).getByRole('button', { name: /încă o lucrare/ }))
    fireEvent.click(within(dlg).getByRole('button', { name: /Punte zirconiu 44–46/ }))
    expect(within(dlg).getAllByRole('tab')).toHaveLength(2)
    await waitFor(() => expect(dlg.querySelector<HTMLInputElement>('input[type=date][min]')!.value).toBe('2026-11-25'))
    fireEvent.click(within(dlg).getByRole('button', { name: /Trimite și tipărește/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/lab/order', expect.objectContaining({
      pid: 2, lab_id: 1, doctor_id: 'er', sent_on: '2026-11-14', due_on: '2026-11-25',
      items: [expect.objectContaining({ work: 'Coroană', teeth: [], plan_item_id: null }),
        expect.objectContaining({ work: 'Punte', material: 'Zirconiu', teeth: [44, 45, 46], plan_item_id: 5 })],
    })))
    await waitFor(() => expect(nav).toHaveBeenCalledWith('/admin/lab/7/tipar?back=%2Fadmin%2Flab'))
  })
})
