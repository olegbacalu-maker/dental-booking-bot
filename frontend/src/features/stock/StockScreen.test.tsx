import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { buy, buyRow, CAN_DESK, dash, imCheck, imHome, imRow, item, list, move, ok } from '../../test/stock'
import { DashStock } from './DashStock'
import { StockScreen } from './StockScreen'

/* «Stoc»: остатки и меню слева из `/api/stock`, деньги — только с правом, «Deschis» с отменой, «Comandat»,
   накладная в единицах расхода, «похоже на…» в импорте, плашка главной с крестиком. */

const { get, post, postRaw } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postRaw: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postRaw }, loginUrl: () => '/admin/login?next=x' }
})

const nav = vi.fn()
function open(url = '/admin/stoc', routes: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    const key = Object.keys(routes).find((k) => path.startsWith(k))
    return Promise.resolve(ok(key ? routes[key] : list()))
  })
  const router = createMemoryRouter([{ path: '/admin/stoc', element: <StockScreen navigate={nav} /> }], { initialEntries: [url] })
  render(<RouterProvider router={router} />)
  return router
}

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); postRaw.mockReset(); nav.mockReset(); vi.restoreAllMocks(); localStorage.clear() })

describe('StockScreen', () => {
  it('остатки: минус красным, «comandat» вместо «De comandat», категории в меню, стоимость у директора', async () => {
    open()
    const tr = (await screen.findByText('Septanest 1:100 000')).closest('tr')!
    expect(tr.className).toContain('st-neg-r')
    expect(tr.textContent).toContain('Pe minus')
    expect(tr.textContent).toContain('comandat 11.11')
    expect(tr.textContent).not.toContain('De comandat')
    const filtek = screen.getByText('Filtek Z550 A2').closest('tr')!
    expect(filtek.textContent).toContain('De comandat')
    expect(filtek.textContent).toContain('1 × seringă + 1,5 g')
    expect(screen.getByRole('columnheader', { name: 'Valoare' })).toBeTruthy()
    const menu = screen.getByRole('navigation', { name: 'Stoc' })
    expect(within(menu).getByRole('button', { name: /Anestezice/ })).toBeTruthy()
    expect(within(menu).getByRole('button', { name: /De cumpărat/ }).textContent).toContain('din care comandate: 1')
    expect(screen.queryByText('Filtek Z250 (scos din uz)')).toBeNull()
    expect(screen.getByText('Mănuși nitril M').closest('.st-tile')).toBeTruthy()
  })

  it('без права на деньги — ни колонки стоимости, ни суммы склада', async () => {
    const plain = list({ can: CAN_DESK, items: list().items.map((it) => {
      const c = { ...it }
      delete c.avg_bani
      delete c.value_bani
      return c
    }) })
    open('/admin/stoc', { '/stock': plain })
    await screen.findByText('Septanest 1:100 000')
    expect(screen.queryByRole('columnheader', { name: 'Valoare' })).toBeNull()
    expect(screen.queryByText(/valoarea stocului/)).toBeNull()
  })

  it('категория из меню и фильтр «Arhivă» — на клиенте, адресом', async () => {
    const router = open()
    await screen.findByText('Septanest 1:100 000')
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Stoc' })).getByRole('button', { name: /Compozite/ }))
    await waitFor(() => expect(screen.queryByText('Septanest 1:100 000')).toBeNull())
    expect(router.state.location.search).toContain('cat=Compozite')
    fireEvent.click(screen.getByRole('button', { name: /Arhivă/ }))
    await waitFor(() => expect(router.state.location.search).toContain('f=arh'))
  })

  it('«Deschis» — одной кнопкой, без окна; «Anulează» отменяет строку журнала', async () => {
    post.mockResolvedValueOnce(ok({ id: 77, qty_milli: 2000, neg: false })).mockResolvedValueOnce(ok({}))
    open()
    const tile = (await screen.findByText('Mănuși nitril M')).closest('.st-tile')!
    fireEvent.click(within(tile as HTMLElement).getByRole('button', { name: /Deschis/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/open', { item_id: 4 }))
    fireEvent.click(await screen.findByRole('button', { name: /Anulează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/move/77/undo', {}))
  })

  it('«Scoate din stoc»: на пациента с лотом — `pid` и `lot`, в минус — предупреждение', async () => {
    const implant = item({ id: 9, name: 'Implant Osstem 4.0', costly: true, unit: 'buc', pack_name: 'buc', pack_qty_milli: 1000, qty_milli: 1000,
      lots: [{ lot: 'TS-2405', exp_on: '2029-04-12', qty_milli: 1000 }] })
    get.mockImplementation((path: string) => Promise.resolve(ok(path.startsWith('/patients') ? { rows: [{ id: 4, name: 'Vasile Rotaru' }] } : list({ items: [implant] }))))
    post.mockResolvedValue(ok({ id: 1, qty_milli: 0, neg: false }))
    const router = createMemoryRouter([{ path: '/admin/stoc', element: <StockScreen navigate={nav} /> }], { initialEntries: ['/admin/stoc'] })
    render(<RouterProvider router={router} />)
    const tr = (await screen.findByText('Implant Osstem 4.0')).closest('tr')!
    fireEvent.click(within(tr).getByRole('button', { name: /Scade/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Scoate din stoc' })
    fireEvent.click(await within(dlg).findByRole('button', { name: 'Vasile Rotaru' }))
    fireEvent.click(within(dlg).getByRole('button', { name: /TS-2405/ }))
    fireEvent.click(within(dlg).getByRole('button', { name: /Scoate din stoc/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/out',
      { item_id: 9, qty_milli: 1000, reason: 'pacient', note: '', pid: 4, lot: 'TS-2405' }))
  })

  it('«De cumpărat»: отметка серая, истёкшая — «n-a venit»; «Comandat» и «Anulează» — команды сервера', async () => {
    post.mockResolvedValue(ok({}))
    open('/admin/stoc?v=cumparat', { '/stock/buy': buy([
      buyRow(),
      buyRow({ item_id: 2, name: 'Septanest', ordered: { at: '', on: '2026-11-12', by: 'Recepție', days: 2, late: false } }),
      buyRow({ item_id: 6, name: 'Hipoclorit', ordered: { at: '', on: '2026-11-05', by: 'Director', days: 9, late: true } }),
    ]) })
    const sep = (await screen.findByText('Septanest')).closest('tr')!
    expect(sep.className).toContain('st-ord-r')
    expect(sep.textContent).toContain('comandat 12.11')
    const hip = screen.getByText('Hipoclorit').closest('tr')!
    expect(hip.textContent).toContain('comandat acum 9 zile, n-a venit')
    expect(screen.getByRole('link', { name: /Tipărește/ }).getAttribute('href')).toContain('/admin/stoc/cumparat/tipar?q=3:3,6:3')
    fireEvent.click(within(screen.getByText('Filtek Z550 A2').closest('tr')!).getByRole('button', { name: /^Comandat$/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/order', { ids: [3] }))
    const again = await waitFor(() => {
      const b = within(screen.getByText('Septanest').closest('tr')!).getByRole('button', { name: 'Anulează' })
      expect(b).not.toHaveProperty('disabled', true)
      return b
    })
    fireEvent.click(again)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/order/2/cancel', {}))
  })

  it('накладная: упаковки уходят единицами расхода, регистратура сумм не видит и не шлёт', async () => {
    post.mockResolvedValueOnce(ok({ id: 31 })).mockResolvedValueOnce(ok({}))
    open('/admin/stoc?v=intrari&doc=nou', { '/stock/docs': { docs: [], can: CAN_DESK }, '/stock': list({ can: CAN_DESK }) })
    fireEvent.change(await screen.findByRole('combobox', { name: 'Furnizorul' }), { target: { value: '1' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Nr. facturii' }), { target: { value: 'DMD 1' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Materialul, rândul 1' }), { target: { value: '3' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Ambalaje, rândul 1' }), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Termen, rândul 1'), { target: { value: '2027-09-30' } })
    expect(screen.queryByRole('textbox', { name: 'Suma, rândul 1' })).toBeNull()
    expect(screen.getByText('+12 g')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Înregistrează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/doc/31/close', {}))
    expect(post.mock.calls[0]).toEqual(['/stock/doc', { kind: 'factura', nr: 'DMD 1', doc_date: '2026-11-14', supplier_id: 1,
      lines: [{ item_id: 3, qty_milli: 12000, lot: '', exp_on: '2027-09-30' }] }])
  })

  it('импорт: «похоже на…» — выбор «același» уходит в `choices` и проверяется заново', async () => {
    postRaw.mockResolvedValue(ok(imCheck([imRow({ similar: { kind: 'item', id: 1, name: 'Ubistesin Forte 4% (articaină)' } })])))
    open('/admin/stoc?v=import', { '/stock/import': imHome() })
    const input = (await screen.findByText(/Alege fișierul/)).closest('.pi')!.querySelector('input[type=file]') as HTMLInputElement
    const f = new File(['x'], 'stoc.xlsx')
    await act(async () => { fireEvent.change(input, { target: { files: [f] } }) })
    fireEvent.click(await screen.findByRole('button', { name: /Verifică/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'același' }))
    await waitFor(() => expect(postRaw).toHaveBeenCalledTimes(2))
    const url = String(postRaw.mock.calls[1]![0])
    expect(decodeURIComponent(url)).toContain('"choices":{"2":"same"}')
  })

  it('журнал: строку можно отменить только там, где сервер разрешил', async () => {
    open('/admin/stoc?v=jurnal', { '/stock/moves': { moves: [move(), move({ id: 11, kind: 'intrare', kind_label: 'Intrare', qty_milli: 100000, undoable: false })], more: false, actors: ['Recepție'], can: CAN_DESK } })
    await screen.findByRole('table')
    const rows = screen.getAllByRole('row').filter((r) => r.textContent?.includes('Ubistesin Forte 4%'))
    expect(within(rows[0]!).getByRole('button', { name: /Anulează/ })).toBeTruthy()
    expect(within(rows[1]!).queryByRole('button', { name: /Anulează/ })).toBeNull()
    expect(rows[0]!.textContent).toContain('-50 buc')
  })
})

describe('DashStock', () => {
  it('сколько ниже порога (с «comandate»), что истекает, крестик прячет до нового материала', () => {
    const router = createMemoryRouter([{ path: '/', element: <DashStock m={dash()} /> }])
    const { rerender } = render(<RouterProvider router={router} />)
    const box = screen.getByRole('status')
    expect(box.textContent).toContain('9 materiale sub prag')
    expect(box.textContent).toContain('din care comandate: 2')
    expect(box.textContent).toContain('4 expiră în curând')
    fireEvent.click(screen.getByRole('button', { name: 'Închide' }))
    expect(screen.queryByRole('status')).toBeNull()
    rerender(<RouterProvider router={createMemoryRouter([{ path: '/', element: <DashStock m={dash({ low: 10, low_items: [{ id: 8, name: 'Nou' }] })} /> }])} />)
    expect(screen.getByRole('status')).toBeTruthy()
  })

  it('врачу и пустому складу (`null`) — плашки нет', () => {
    render(<RouterProvider router={createMemoryRouter([{ path: '/', element: <DashStock m={null} /> }])} />)
    expect(screen.queryByRole('status')).toBeNull()
  })
})
