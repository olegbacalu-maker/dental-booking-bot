import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../../../types/api'
import type { CardActions } from '../actions'
import { patientCard, type Form, type PatientCard, type SignBody } from '../card'
import { SignDialog } from './SignDialog'

/* Окно подписи бланка на экране (09.11, раскладка A). Здесь: «Salvează» ждёт
   нужные поля (пациент; представитель — с именем; у согласия к плану — и
   врач); уходит ТОЛЬКО PNG и выборы, без точек линии; повторный щелчок во
   время записи не шлётся; отказ сервера — текстом в окне; нарисованное не
   теряется молча. Сервер, PDF и листы — `tests/test_sign.py` (sign-pdf).
   У jsdom нет холста: `getContext` → null (линия не рисуется, поле всё равно
   «в чернилах» по касанию), `toDataURL` подменён. */

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const FORMS: Record<'acord195' | 'acord_plan' | 'chestionar', Form> = {
  acord195: { key: 'acord195', title: 'Informare și acord (Legea 195)', sheet: 'acord', category: 'acord195', printed: '', signed: null, sign: true },
  acord_plan: { key: 'acord_plan', title: 'Acord informat la planul de tratament', sheet: 'plan-acord', category: 'acord_plan', printed: '', signed: null, n_active: 2, total: 1900, stale: false, sign: true },
  chestionar: { key: 'chestionar', title: 'Chestionar anamneză', sheet: 'anamneza/print', category: 'chestionar', printed: '', signed: null, filled: '18.09.2026', sign: true },
}
const CARD = {
  id: 5, name: 'Pin Test',
  options: { doc_categories: [{ id: 'acord195', label: 'Informare și acord (195) — semnat' }, { id: 'acord_plan', label: 'Acord informat la plan — semnat' }] },
} as unknown as PatientCard

function mount(key: keyof typeof FORMS, act?: CardActions['act']) {
  const onClose = vi.fn()
  const a: CardActions = {
    pid: 5, views: false, busy: false, back: '/admin/patient/5?tab=docs',
    act: act ?? (async (run) => { try { await run(); return null } catch (e) { return e as ApiError } }),
  }
  render(<SignDialog card={CARD} form={FORMS[key]} a={a} onClose={onClose} />)
  return { onClose }
}

const dlg = () => within(screen.getByRole('dialog'))
const saveBtn = () => dlg().getByRole('button', { name: /Salvează semnat|Se salvează/ }) as HTMLButtonElement
/** росчерк по полю: касание вниз-вверх (jsdom не знает координат — и не нужно) */
function ink(label: string) {
  const c = dlg().getByRole('img', { name: label })
  fireEvent.pointerDown(c, { pointerType: 'touch', pointerId: 1, clientX: 10, clientY: 10 })
  fireEvent.pointerMove(c, { pointerType: 'touch', pointerId: 1, clientX: 40, clientY: 20 })
  fireEvent.pointerUp(c, { pointerType: 'touch', pointerId: 1 })
}
const sent = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls[0]![3] as SignBody

let sign: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(PNG)
  sign = vi.spyOn(patientCard, 'signForm')
    .mockResolvedValue({ data: CARD as PatientCard & { doc: never }, code: 'ok_sign', text: 'Document semnat și salvat în fișă (PDF)', tone: 'ok' })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('SignDialog — подпись бланка на экране (09.11)', () => {
  it('лист — предпросмотр «как будет подписан», не печатный (печатный пишет «tipărit»)', () => {
    mount('acord195')
    expect(dlg().getByTitle('Informare și acord (Legea 195)').getAttribute('src')).toBe('/admin/patient/5/sign/acord195')
    expect(dlg().getByText(/categoria «Informare și acord \(195\) — semnat»/)).toBeTruthy()
  })

  it('пустое поле — «Salvează» неактивна; росчерк включает; «Șterge» снова выключает', () => {
    mount('acord195')
    expect(saveBtn().disabled).toBe(true)
    ink('Semnătura pacientului')
    expect(saveBtn().disabled).toBe(false)
    fireEvent.click(dlg().getByRole('button', { name: /Șterge/ }))
    expect(saveBtn().disabled).toBe(true)
  })

  it('представитель требует имя (2+ знака); уходит signer и signer_name, подпись — его', async () => {
    mount('chestionar')
    ink('Semnătura pacientului')
    fireEvent.click(dlg().getByRole('button', { name: 'Reprezentant legal' }))
    expect(dlg().getByRole('img', { name: 'Semnătura reprezentantului legal' })).toBeTruthy()
    expect(saveBtn().disabled).toBe(true)
    const name = dlg().getByLabelText('Numele reprezentantului legal')
    fireEvent.change(name, { target: { value: ' M ' } })
    expect(saveBtn().disabled).toBe(true)
    fireEvent.change(name, { target: { value: '  Popescu Maria ' } })
    expect(saveBtn().disabled).toBe(false)
    fireEvent.click(saveBtn())
    await waitFor(() => expect(sign).toHaveBeenCalledTimes(1))
    expect(sign.mock.calls[0]!.slice(0, 3)).toEqual([5, false, 'chestionar'])
    /* у анкеты согласий 195 нет и врача нет */
    expect(sent(sign)).toEqual({ signer: 'reprezentant', signer_name: 'Popescu Maria', sig_patient: PNG })
  })

  it('согласие к плану: два поля, «Salvează» ждёт и врача; уходит sig_doctor', async () => {
    const { onClose } = mount('acord_plan')
    expect(dlg().getAllByRole('img').map((c) => c.getAttribute('aria-label')))
      .toEqual(['Semnătura pacientului', 'Semnătura medicului'])
    ink('Semnătura pacientului')
    expect(saveBtn().disabled).toBe(true)
    ink('Semnătura medicului')
    expect(saveBtn().disabled).toBe(false)
    fireEvent.click(saveBtn())
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(sent(sign)).toEqual({ signer: 'pacient', sig_patient: PNG, sig_doctor: PNG })
  })

  it('Informare 195: уходит только PNG и согласия; не отвечено — null, повторный щелчок снимает выбор', async () => {
    mount('acord195')
    ink('Semnătura pacientului')
    const mkt = within(dlg().getByRole('group', { name: /marketing/ }))
    const photo = within(dlg().getByRole('group', { name: /Fotografii/ }))
    fireEvent.click(mkt.getByRole('button', { name: 'DA' }))
    fireEvent.click(photo.getByRole('button', { name: 'NU' }))
    fireEvent.click(photo.getByRole('button', { name: 'NU' }))
    expect(mkt.getByRole('button', { name: 'DA' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(saveBtn())
    await waitFor(() => expect(sign).toHaveBeenCalled())
    /* ⛔ никаких точек, нажима и времени — ровно эти ключи (закон 195) */
    expect(sent(sign)).toEqual({ signer: 'pacient', sig_patient: PNG, consents: { mkt: true, photo: null } })
    expect(sent(sign).sig_patient.startsWith('data:image/png;base64,')).toBe(true)
  })

  it('во время записи (~1 с PDF) кнопка «Se salvează…», второй щелчок не шлётся; удача закрывает окно', async () => {
    let done!: (v: Awaited<ReturnType<typeof patientCard.signForm>>) => void
    sign.mockReturnValue(new Promise((r) => { done = r }))
    const { onClose } = mount('acord195')
    ink('Semnătura pacientului')
    fireEvent.click(saveBtn())
    await waitFor(() => expect(saveBtn().textContent).toContain('Se salvează'))
    expect(saveBtn().disabled).toBe(true)
    fireEvent.click(saveBtn())
    expect(sign).toHaveBeenCalledTimes(1)
    done({ data: CARD as PatientCard & { doc: never }, code: 'ok_sign', text: '', tone: 'ok' })
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('отказ сервера — его текст в окне (плашка экрана под модальным окном не видна), окно и подпись остаются', async () => {
    sign.mockRejectedValue(new ApiError({ kind: 'server', status: 503, code: 'pdf_err', text: 'PDF-ul nu s-a putut crea. Încercați din nou.' }, 'x'))
    const { onClose } = mount('acord195')
    ink('Semnătura pacientului')
    fireEvent.click(saveBtn())
    expect((await dlg().findByRole('alert')).textContent).toContain('PDF-ul nu s-a putut crea')
    expect(onClose).not.toHaveBeenCalled()
    expect(saveBtn().disabled).toBe(false)
  })

  it('закрытие с нарисованным спрашивает; без подписи — закрывается сразу', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { onClose } = mount('acord195')
    fireEvent.click(dlg().getByRole('button', { name: 'Renunță' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(confirm).not.toHaveBeenCalled()
    cleanup()
    const second = mount('acord195')
    ink('Semnătura pacientului')
    fireEvent.click(dlg().getByRole('button', { name: 'Închide' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(second.onClose).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    fireEvent.click(dlg().getByRole('button', { name: 'Renunță' }))
    await waitFor(() => expect(second.onClose).toHaveBeenCalledTimes(1))
  })
})
