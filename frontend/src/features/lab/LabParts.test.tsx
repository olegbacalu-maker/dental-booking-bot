import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import type { ReactElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../types/api'
import { CAN_DOC, form, lab, ok, patient, row, settings } from '../../test/lab'
import type { PatientCard, PlanItem } from '../patients/card/card'
import { DashLab } from './DashLab'
import { LabSettingsScreen } from './LabSettingsScreen'
import { LabBlock, LabSummary, usePatientLab } from './PatientLab'

/* Блок фиши (значок строки плана, блок под планом, «Rezumat»), каталог
   Setări › Laboratoare и плашка главной — на формах контракта сервера. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

function mount(el: ReactElement, url = '/x') {
  const router = createMemoryRouter([{ path: '*', element: el }], { initialEntries: [url] })
  render(<RouterProvider router={router} />)
}

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); vi.restoreAllMocks() })

const item = (p: Partial<PlanItem>): PlanItem => ({ id: 3, tooth: 26, procedure: 'Coroană metalo-ceramică', doctor: 'Dr. Elena Rusu', status: 'in_lucru',
  label: 'În lucru', price: 4500, due: '', overdue: false, done: '', motiv: '', next: 'finalizat', refusable: true, deletable: false, ...p })
const CARD = {
  id: 2, name: 'Ion Popescu', profile: { primary_doctor: 'Dr. Elena Rusu', file_no: '' },
  plan: { items: [item({}), item({ id: 4, tooth: 36, procedure: 'Coroană zirconiu pe implant' }), item({ id: 2, tooth: 16, procedure: 'Obturație compozit' })] },
} as unknown as PatientCard

function Fisa() {
  const L = usePatientLab(CARD, () => {})
  return (
    <>
      {CARD.plan.items.map((it) => <div key={it.id} data-plan={it.id}>{it.procedure}{L.chip(it)}</div>)}
      <LabBlock lab={L} />
      <LabSummary lab={L} onOpen={() => {}} />
      {L.host.node}
    </>
  )
}

describe('фиша: заказы пациента', () => {
  it('значок у позиции с заказом, кнопка заказа у протезной без заказа, ничего у пломбы', async () => {
    get.mockResolvedValue(ok(patient([row()])))
    mount(<Fisa />)
    const p3 = document.querySelector('[data-plan="3"]') as HTMLElement
    expect((await within(p3).findByRole('button', { name: /Laborator · întârziat/ }))).toBeTruthy()
    expect(within(document.querySelector('[data-plan="4"]') as HTMLElement).getByRole('button', { name: /Comandă la laborator/ })).toBeTruthy()
    expect(within(document.querySelector('[data-plan="2"]') as HTMLElement).queryByRole('button')).toBeNull()
    expect(get).toHaveBeenCalledWith('/lab/patient/2', expect.anything())
    const block = document.getElementById('laborator')!
    expect(block.textContent).toContain('1 întârziată')
    expect(block.textContent).toContain('Dental Lab Prim')
    expect(document.querySelector('.lb-sum')!.textContent).toContain('Coroană')
  })

  it('«Comandă la laborator» у строки плана — форма с предвыбранной позицией', async () => {
    get.mockImplementation((url: string) => Promise.resolve(url.startsWith('/lab/form') ? ok(form())
      : url.startsWith('/lab/due') ? ok({ due_on: '2026-11-25' }) : ok(patient([]))))
    mount(<Fisa />)
    fireEvent.click(await within(document.querySelector('[data-plan="4"]') as HTMLElement).findByRole('button', { name: /Comandă la laborator/ }))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/lab/form?pid=2&plan_item=4', expect.anything()))
    expect(await screen.findByRole('dialog', { name: 'Comandă la laborator' })).toBeTruthy()
  })

  it('без права на деньги в окне нет цены; без лабораторий и без права на каталог — подсказка, а не поле', async () => {
    const f = form({ labs: [], can: CAN_DOC })
    delete f.last_prices
    get.mockImplementation((url: string) => Promise.resolve(url.startsWith('/lab/form') ? ok(f)
      : ok(patient([]))))
    mount(<Fisa />)
    fireEvent.click(await within(document.querySelector('[data-plan="3"]') as HTMLElement).findByRole('button', { name: /Comandă la laborator/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Comandă la laborator' })
    expect(dlg.textContent).not.toContain('Preț laborator')
    expect(dlg.textContent).toContain('Laboratoarele le adaugă recepția')
    expect(within(dlg).queryByPlaceholderText('ex. Dental Lab')).toBeNull()
  })
})

describe('Setări › Laboratoare', () => {
  it('каталог: рабочие дни словами, счёт заказов; правка дней уходит строкой цифр', async () => {
    get.mockResolvedValue(ok(settings([lab(), lab({ id: 2, name: 'ArtDent', workdays: '123456', orders: 0, open: 0, active: false })])))
    post.mockResolvedValue(ok({ id: 1 }, 'ok_lab_item', 'Laboratorul e salvat'))
    mount(<LabSettingsScreen />)
    expect(await screen.findByText('Dental Lab Prim')).toBeTruthy()
    expect(document.body.textContent).toContain('7 zile lucrătoare · luni–vineri')
    expect(document.body.textContent).toContain('4 comenzi, 2 în lucru')
    expect(document.body.textContent).toContain('Lu, Ma, Mi, Jo, Vi, Sâ')
    fireEvent.click(screen.getByRole('button', { name: 'Editează Dental Lab Prim' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sâ' }))
    expect(screen.queryByRole('button', { name: /Șterge/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/lab/item', expect.objectContaining({ id: 1, workdays: '123456', days: 7 })))
    expect(await screen.findByText('Laboratorul e salvat')).toBeTruthy()
  })

  it('пустой каталог — сразу форма; отказ — словами сервера и полем', async () => {
    get.mockResolvedValue(ok(settings([], { can: { money: false, labs: true, settings: false } })))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'lab_bad', text: 'Există deja', field: 'name' }, 'v'))
    mount(<LabSettingsScreen />)
    const name = await screen.findByPlaceholderText('ex. Dental Lab Prim')
    expect(screen.queryByText('Fișa de comandă')).toBeNull()
    fireEvent.change(name, { target: { value: 'Dental Lab Prim' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText('Există deja')).toBeTruthy()
    expect(name.className).toContain('bad')
  })
})

describe('плашка главной', () => {
  it('визит без работы и опоздания красным, ссылки в список с фильтром', () => {
    const r = { id: 1, nr: 41, pid: 2, patient: 'Ion Popescu', work: 'Coroană', lab: 'Dental Lab Prim', due_on: '2026-11-12', days_late: 2, next_appt: null }
    mount(<DashLab m={{ late: [r], ready: [], visit: [{ ...r, next_appt: { id: 9, starts_at: '', date: '2026-11-15', time: '09:30', doctor: '', day: 'maine' } }],
      counts: { late: 1, ready: 0, visit: 1 } }} />)
    const plate = screen.getByRole('status')
    expect(plate.className).toContain('bad')
    expect(plate.textContent).toContain('Programare fără lucrare: 1 lucrare')
    expect(plate.textContent).toContain('mâine 09:30')
    expect(plate.textContent).toContain('2 z.')
    expect(within(plate).getByRole('link', { name: /Întârziate/ }).getAttribute('href')).toBe('/admin/lab?f=intarziate')
  })

  it('пусто или ключа нет в конверте — плашки нет', () => {
    mount(<DashLab m={{ late: [], ready: [], visit: [], counts: { late: 0, ready: 0, visit: 0 } }} />)
    expect(screen.queryByRole('status')).toBeNull()
    cleanup()
    mount(<DashLab m={undefined} />)
    expect(screen.queryByRole('status')).toBeNull()
  })
})
