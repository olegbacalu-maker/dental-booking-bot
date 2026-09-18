import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { VisitPage } from './visits'
import { VisitScreen } from './VisitScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const PAGE: VisitPage = {
  appt: { id: 7, when: '16.09.2026 10:00', patient_id: 3, patient: 'Vizita Test', service: 'Consultație',
    doctor: 'Dr. Activ Doi', status: 'confirmed', status_label: 'confirmată', comment: 'de sunat înainte' },
  record: { acuze: 'Durere la rece', examen: '', diagnostic: 'Pulpită 26', tratament: 'Trat', recomandari: '',
    created: '18.09.2026 11:58', updated: '', author: 'Director' },
  editable: true,
  note: '',
  fields: [
    { id: 'acuze', label: 'Acuze / motivul prezentării', rows: 2, placeholder: 'Ce acuză pacientul…' },
    { id: 'examen', label: 'Examen obiectiv', rows: 3, placeholder: 'Statusul local…' },
    { id: 'diagnostic', label: 'Diagnostic', rows: 2, placeholder: 'Diagnosticul stabilit…' },
    { id: 'tratament', label: 'Tratament efectuat', rows: 3, placeholder: 'Ce s-a efectuat…' },
    { id: 'recomandari', label: 'Recomandări', rows: 2, placeholder: 'Recomandări pentru pacient…' },
  ],
  templates: [
    { id: 'consult', label: 'Consultație', values: { acuze: 'Prezentare pentru consultație.', examen: 'Mucoasa orală roz.', diagnostic: '', tratament: 'Examen clinic complet.', recomandari: 'Control peste 6 luni.' } },
    { id: 'control', label: 'Control', values: { acuze: 'Prezentare la control programat.', examen: '', diagnostic: '', tratament: '', recomandari: '' } },
  ],
  plan: {
    linked: [{ id: 1, text: 'dinte 26 · Obturație 26 · 500 MDL' }],
    open: [{ id: 2, text: 'Detartraj · 300 MDL', in_lucru: true }, { id: 4, text: 'Consult gratuit', in_lucru: false }],
  },
  back: '/admin/all?date=2026-09-16',
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const area = (label: string) => screen.getByLabelText(label) as HTMLTextAreaElement

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

describe('VisitScreen', () => {
  it('успех: шапка с комментарием, графы с записью, шаблоны, выполненное и открытое, авторство', async () => {
    get.mockResolvedValueOnce(ok(PAGE))
    render(<VisitScreen aid={7} back="/admin/all?date=2026-09-16" />)
    expect(await screen.findByText(/vizita #7/)).toBeTruthy()
    expect((screen.getByText('Vizita Test') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/patient/3')
    expect(screen.getByText('confirmată')).toBeTruthy()
    expect(screen.getByText(/de sunat înainte/)).toBeTruthy()
    expect((screen.getByText('Înapoi').closest('a') as HTMLAnchorElement).getAttribute('href')).toBe('/admin/all?date=2026-09-16')
    expect(area('Acuze / motivul prezentării').value).toBe('Durere la rece')
    expect(area('Examen obiectiv').value).toBe('')
    expect(area('Examen obiectiv').rows).toBe(3)
    expect(screen.getByRole('button', { name: 'Consultație' })).toBeTruthy()
    expect(screen.getByText('dinte 26 · Obturație 26 · 500 MDL')).toBeTruthy()
    expect(screen.getByLabelText(/Detartraj · 300 MDL/)).toBeTruthy()
    expect(screen.getByText('— în lucru')).toBeTruthy()
    expect(screen.getByText('Înregistrat: 18.09.2026 11:58 · de Director')).toBeTruthy()
    expect(get).toHaveBeenCalledWith('/visits/7?back=%2Fadmin%2Fall%3Fdate%3D2026-09-16', expect.anything())
  })

  it('шаблон заполняет только пустые графы', async () => {
    get.mockResolvedValueOnce(ok(PAGE))
    render(<VisitScreen aid={7} back="" />)
    await screen.findByText(/vizita #7/)
    fireEvent.click(screen.getByRole('button', { name: 'Consultație' }))
    expect(area('Acuze / motivul prezentării').value).toBe('Durere la rece')
    expect(area('Examen obiectiv').value).toBe('Mucoasa orală roz.')
    expect(area('Diagnostic').value).toBe('Pulpită 26')
    expect(area('Recomandări').value).toBe('Control peste 6 luni.')
  })

  it('сохранение: шлёт графы, отмеченные позиции и адрес возврата; страница подменяется, плашка сервера', async () => {
    get.mockResolvedValueOnce(ok(PAGE))
    const after: VisitPage = { ...PAGE, record: { ...PAGE.record!, tratament: 'Detartraj efectuat', updated: '18.09.2026 12:30' },
      plan: { linked: [...PAGE.plan.linked, { id: 2, text: 'Detartraj · 300 MDL' }], open: [PAGE.plan.open[1]!] } }
    post.mockResolvedValueOnce(ok(after, 'ok_visit', 'Consultația a fost salvată'))
    render(<VisitScreen aid={7} back="/admin/all?date=2026-09-16" />)
    await screen.findByText(/vizita #7/)
    fireEvent.change(area('Tratament efectuat'), { target: { value: 'Detartraj efectuat' } })
    fireEvent.click(screen.getByLabelText(/Detartraj · 300 MDL/))
    fireEvent.click(screen.getByText('Salvează consultația'))
    expect(await screen.findByText('Consultația a fost salvată')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/visits/7', {
      acuze: 'Durere la rece', examen: '', diagnostic: 'Pulpită 26', tratament: 'Detartraj efectuat', recomandari: '',
      done: [2], back: '/admin/all?date=2026-09-16',
    })
    expect(screen.getByText(/actualizat: 18.09.2026 12:30/)).toBeTruthy()
    expect(screen.getAllByText('Detartraj · 300 MDL').length).toBe(1)
    expect(screen.queryByLabelText(/Detartraj · 300 MDL/)).toBeNull()
  })

  it('пустая запись — текст сервера, ввод остаётся', async () => {
    get.mockResolvedValueOnce(ok({ ...PAGE, record: null, plan: { linked: [], open: [] } }))
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_visit', text: 'Completați cel puțin o rubrică' }, 'v'))
    render(<VisitScreen aid={7} back="" />)
    await screen.findByText(/vizita #7/)
    fireEvent.change(area('Acuze / motivul prezentării'), { target: { value: '  ' } })
    fireEvent.click(screen.getByText('Salvează consultația'))
    expect(await screen.findByText('Completați cel puțin o rubrică')).toBeTruthy()
    expect(area('Acuze / motivul prezentării').value).toBe('  ')
  })

  it('отменённый визит: предупреждение и запись для чтения, без формы', async () => {
    get.mockResolvedValueOnce(ok({ ...PAGE, editable: false, note: 'Vizita este anulată — consultația nu se completează.',
      appt: { ...PAGE.appt, status: 'cancelled', status_label: 'anulată' } }))
    render(<VisitScreen aid={7} back="" />)
    expect(await screen.findByText('Vizita este anulată — consultația nu se completează.')).toBeTruthy()
    expect(screen.queryByText('Salvează consultația')).toBeNull()
    expect(screen.getByText('Acuze / motivul prezentării:')).toBeTruthy()
    expect(screen.getByText('Durere la rece')).toBeTruthy()
    expect(screen.queryByText('Examen obiectiv:')).toBeNull()
    expect(screen.getByText(/Înregistrat: 18.09.2026 11:58/)).toBeTruthy()
  })

  it('визита нет — 404 своим текстом; 401 — уход на вход', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'server', status: 404, code: '', text: '' }, 's'))
    render(<VisitScreen aid={7} back="" />)
    expect(await screen.findByText('Vizita nu există sau este o notă fără pacient.')).toBeTruthy()
    cleanup()
    get.mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u'))
    const navigate = vi.fn()
    render(<VisitScreen aid={7} back="" navigate={navigate} />)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin/login?next=x'))
  })
})
