import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { openScreen } from '../../test/openScreen'
import { CAN, CAN_DESK, list, ok } from '../../test/stock'
import { loadServicesSettings, ServicesSettingsScreen } from '../settings/ServicesSettingsScreen'
import type { ServicesData } from '../settings/settings'
import { useConsume } from './ConsumeDialog'
import { loadStock, StockScreen } from './StockScreen'
import { loadStockSettings, StockSettingsScreen } from './StockSettingsScreen'
import type { PlanProposal, ReportData, TechCards } from './stock'

/* Ступень 2: техкарта в «Servicii», окно списания при «Finalizată», режим в «Setări › Stoc», отчёт «Consum». */

const { get, post, postRaw } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postRaw: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postRaw }, loginUrl: () => '/admin/login?next=x' }
})

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); postRaw.mockReset() })

const route = (routes: Record<string, unknown>) => get.mockImplementation((path: string) => {
  const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => path.startsWith(k))
  return key ? Promise.resolve(ok(routes[key])) : Promise.reject(new Error(`unexpected ${path}`))
})

const SVC: ServicesData = {
  services: [
    { id: 'obt', ro: 'Obturație compozit', ru: 'Пломба', price: '900', duration: 60, color: '', urgent: false, docs: [] },
    { id: '', ro: 'Nou', ru: '', price: '', duration: 60, color: '', urgent: false, docs: [] },
  ],
  palette: {}, durations: [30, 60], dur_step: 5, dur_max: 240, recalls: [0], doctors: [],
}
const TC: TechCards = {
  services: [{ id: 'obt', name: 'Obturație compozit', warn: 1, lines: [
    { item_id: 3, item: 'Filtek Z550 A2', unit: 'g', qty_milli: 300, optional: false, active: true },
    { item_id: 5, item: 'Filtek Z250 A3,5', unit: 'g', qty_milli: 200, optional: true, active: false }] }],
  items: [{ id: 3, name: 'Filtek Z550 A2', unit: 'g', cat: 'Compozite', active: true },
    { id: 5, name: 'Filtek Z250 A3,5', unit: 'g', cat: 'Compozite', active: false },
    { id: 7, name: 'Ubistesin Forte 4%', unit: 'buc', cat: 'Anestezice', active: true }],
  can: CAN,
}

describe('техкарта в «Setări › Servicii»', () => {
  it('колонка «Materiale»: число и точка архива; окно сохраняет весь список; новая услуга — сначала сохранить', async () => {
    route({ '/settings/services': SVC, '/stock/tehcard': TC })
    post.mockResolvedValueOnce(ok({}, 'ok_stock_tc', 'Materialele serviciului salvate'))
    openScreen('/admin/settings/services', '/admin/settings/services', <ServicesSettingsScreen />, loadServicesSettings)
    const btn = await screen.findByRole('button', { name: /2 materiale: Obturație/ })
    expect(btn.querySelector('.st-dot')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Adaugă materiale: Nou' }).hasAttribute('disabled')).toBe(true)
    fireEvent.click(btn)
    const dlg = await screen.findByRole('dialog', { name: /Materiale: Obturație/ })
    expect(dlg.textContent).toContain('în arhivă')
    fireEvent.change(within(dlg).getByRole('textbox', { name: 'Cantitatea 1' }), { target: { value: '0,4' } })
    fireEvent.click(within(dlg).getByRole('button', { name: 'Șterge 2' }))
    fireEvent.click(within(dlg).getByRole('button', { name: /Adaugă material/ }))
    fireEvent.change(within(dlg).getByRole('combobox', { name: 'Materialul 2' }), { target: { value: '7' } })
    fireEvent.change(within(dlg).getByRole('textbox', { name: 'Cantitatea 2' }), { target: { value: '1' } })
    fireEvent.click(within(dlg).getByRole('checkbox', { name: 'Opțional 2' }))
    fireEvent.click(within(dlg).getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/tehcard/obt',
      { lines: [{ item_id: 3, qty_milli: 400, optional: false }, { item_id: 7, qty_milli: 1000, optional: true }] }))
    expect(await screen.findByRole('button', { name: /2 materiale: Obturație/ })).toBeTruthy()
  })

  it('склад отказал — экран услуг жив, колонки «Materiale» нет', async () => {
    route({ '/settings/services': SVC })
    openScreen('/admin/settings/services', '/admin/settings/services', <ServicesSettingsScreen />, loadServicesSettings)
    await screen.findByDisplayValue('Obturație compozit')
    expect(screen.queryByRole('columnheader', { name: 'Materiale' })).toBeNull()
  })
})

const line = (p: Partial<PlanProposal['lines'][number]>): PlanProposal['lines'][number] => ({
  item_id: 1, item: '', unit: 'buc', qty_milli: 1000, optional: false, active: true, on: true, costly: false, lot: null, lots: [],
  stock_milli: 1000, neg_after: false, ...p,
})
const PROP: PlanProposal = {
  plan: { id: 41, pid: 4, procedure: 'Implant', tooth: 36, status: 'finalizat', service_id: 'impl', service: 'Implant', doctor: 'Dr. Elena Rusu' },
  mode: 'confirmare', state: 'pending', moves: [], can: CAN,
  lines: [
    line({ item_id: 16, item: 'Implant Osstem 4.0', costly: true, stock_milli: 2000, lot: 'TS-2405',
      lots: [{ lot: 'TS-2405', exp_on: '2029-04-12', qty_milli: 1000 }, { lot: 'TS-2311', exp_on: '2029-05-02', qty_milli: 1000 }] }),
    line({ item_id: 1, item: 'Ubistesin Forte 4%', qty_milli: 2000, stock_milli: 1000, neg_after: true }),
    line({ item_id: 9, item: 'Membrană Bio-Gide', optional: true, on: false, costly: true }),
  ],
}

function Harness({ service = 'impl' as string | null, loaded = null as number[] | null }) {
  const [said, setSaid] = useState('')
  const c = useConsume((t) => setSaid(t), loaded)
  return <><button type="button" onClick={() => c.afterFinal({ id: 41, what: 'Implant · dintele 36', service })}>fin</button>
    {c.chip({ id: 41, what: 'Implant · dintele 36' })}<p>{said}</p>{c.node}</>
}

describe('окно при «Finalizată»', () => {
  it('режим «cu confirmare»: опциональное снято, лот выбран, минус подсвечен; «Confirmă» шлёт отмеченное', async () => {
    route({ '/stock/plan/41': PROP })
    post.mockResolvedValueOnce(ok({ moves: 2, neg: [1] }, 'ok_stock_tc_consume', 'S-au scăzut 2 materiale'))
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'fin' }))
    const dlg = await screen.findByRole('dialog', { name: 'Materiale consumate' })
    expect(within(dlg).getByRole('checkbox', { name: 'Se scade: Membrană Bio-Gide' })).toHaveProperty('checked', false)
    expect(dlg.textContent).toContain('rămâne -1 buc')
    expect(dlg.textContent).toContain('intră pe minus')
    fireEvent.click(within(dlg).getByRole('button', { name: /TS-2311/ }))
    fireEvent.click(within(dlg).getByRole('button', { name: /Confirmă/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/plan/41/consume',
      { lines: [{ item_id: 16, qty_milli: 1000, lot: 'TS-2311' }, { item_id: 1, qty_milli: 2000 }] }))
    expect(await screen.findByText('S-au scăzut 2 materiale')).toBeTruthy()
  })

  it('«Fără scădere» — решение: `skip`, второй раз окно не спросит', async () => {
    route({ '/stock/plan/41': PROP })
    post.mockResolvedValueOnce(ok({}, 'ok_stock_tc_skip', 'Finalizată fără scădere din stoc'))
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'fin' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Fără scădere' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/plan/41/skip', {}))
  })

  it('окно закрыли без решения — значок в строке плана открывает его снова; решение значок снимает', async () => {
    route({ '/stock/plan/41': PROP })
    post.mockResolvedValueOnce(ok({}, 'ok_stock_tc_skip', 'Fără scădere'))
    render(<Harness loaded={[41]} />)
    fireEvent.click(screen.getByRole('button', { name: /Materiale de confirmat/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Fără scădere' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: /Materiale de confirmat/ })).toBeNull())
  })

  it('без услуги, режим «automat» или уже решено — окна нет', async () => {
    render(<Harness service={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'fin' }))
    expect(get).not.toHaveBeenCalled()
    cleanup()
    route({ '/stock/plan/41': { ...PROP, mode: 'automat', state: 'done' } })
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'fin' }))
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('режим и отчёт', () => {
  it('«Scădere la finalizare» уходит в prefs; без права на настройки — заперто', async () => {
    route({ '/stock': list({ prefs: { exp_days: 60, order_days: 7, tc_mode: 'confirmare' } }) })
    post.mockResolvedValueOnce(ok({}, 'ok_stock_prefs', 'Salvat'))
    openScreen('/admin/settings/stoc', '/admin/settings/stoc', <StockSettingsScreen />, loadStockSettings)
    fireEvent.click(await screen.findByRole('button', { name: 'automat' }))
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/stock/prefs', { exp_days: 60, order_days: 7, tc_mode: 'automat' }))
    cleanup()
    route({ '/stock': list({ can: CAN_DESK }) })
    openScreen('/admin/settings/stoc', '/admin/settings/stoc', <StockSettingsScreen />, loadStockSettings)
    expect((await screen.findByRole('button', { name: 'automat' })).hasAttribute('disabled')).toBe(true)
  })

  it('«Consum»: группы с материалами, стоимость — только с деньгами; группировка — адресом', async () => {
    const C: ReportData = { by: 'doctor', from: '2026-11-01', to: '2026-11-30', total_bani: 452000, can: CAN,
      rows: [{ key: 'er', label: 'Dr. Elena Rusu', qty_rows: 3, cost_bani: 452000,
        items: [{ item_id: 16, item: 'Implant Osstem 4.0', unit: 'buc', qty_milli: 1000, cost_bani: 280000 }, { item_id: 1, item: 'Ubistesin', unit: 'buc', qty_milli: 2000, cost_bani: 3920 }] }] }
    route({ '/stock/report': C, '/stock': list() })
    const { router } = openScreen('/admin/stoc', '/admin/stoc?v=consum', <StockScreen />, loadStock)
    const tr = (await screen.findByText('Dr. Elena Rusu')).closest('tr')!
    expect(tr.textContent).toContain('Implant Osstem 4.0')
    expect(tr.textContent).toContain('2.800 MDL')
    fireEvent.click(screen.getByRole('button', { name: 'Pacient' }))
    await waitFor(() => expect(router.state.location.search).toContain('by=patient'))
    await waitFor(() => expect(get.mock.calls.some((c) => String(c[0]).includes('by=patient'))).toBe(true))
  })
})
