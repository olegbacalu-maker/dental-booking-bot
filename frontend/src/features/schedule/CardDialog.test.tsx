import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CardDialog } from './CardDialog'
import type { ServiceOption, VisitCardView } from './day'

/* Смена процедуры в окне визита (22.10, Олег: сменить процедуру, не удаляя
   запись; вторая услуга в одну запись — нет).
   ⛔ «Можно ли» и список решает СЕРВЕР: на карточке — только флаг
   `service_edit`, список окно спрашивает само (`GET …/service`). В блоке
   живого канала списка нет: он раздул бы каждый опрос главной.
   ⛔ Отказ печатается В ОКНЕ, как у окна пустого часа: плашка экрана под
   `<dialog>` не видна. */

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post: vi.fn() } }
})

const OPTIONS: ServiceOption[] = [
  { id: 'consult', label: 'Consultație' },
  { id: 'pain', label: 'Durere acută' },
  { id: 'long', label: 'Tratament lung' },
]

function card(over: Partial<VisitCardView> = {}): VisitCardView {
  return {
    time: '09:00', name: 'Ion Popa', service: 'Consultație', doctor: 'Dr. Activ Doi',
    phone: '069000000', age: 41, comment: '', status: 'confirmed', pid: 7, rec: false,
    call: '', callable: false, service_id: 'consult', service_edit: true, ...over,
  }
}

const onClose = vi.fn()
const ok = async () => true

function show(c: VisitCardView, onService?: (sid: string, fail: (t: string) => void)
  => Promise<boolean>, note = '') {
  return render(<CardDialog open id={1} card={c} actions={[]} note={note} back="/admin/all"
    busy={false} onClose={onClose} onComment={ok} onStatus={ok}
    {...(onService ? { onService } : {})} />)
}

const picker = () => document.querySelector('dialog select[aria-label="Procedura"]') as
  HTMLSelectElement | null
const options = () => Array.from(picker()?.options ?? []).map((o) => [o.value, o.textContent, o.disabled])
const svcBtn = () => Array.from(document.querySelectorAll('dialog button'))
  .find((b) => b.textContent?.includes('Schimbă procedura')) as HTMLButtonElement
const banner = () => document.querySelector('dialog form[aria-label="Procedura"] .banner.err')
  ?.textContent ?? ''

beforeEach(() => {
  get.mockResolvedValue({ data: { service_id: 'consult', options: OPTIONS }, code: '', text: '',
    tone: 'ok' })
})
afterEach(() => { cleanup(); onClose.mockClear(); get.mockReset() })

describe('окно визита: смена процедуры', () => {
  it('список — ответ сервера для ЭТОГО визита; нынешняя выбрана, без перемены отправлять нечего', async () => {
    show(card(), ok)
    await waitFor(() => expect(picker()).toBeTruthy())
    expect(get).toHaveBeenCalledWith('/schedule/appointments/1/service', expect.anything())
    expect(options()).toEqual([['consult', 'Consultație', false], ['pain', 'Durere acută', false],
      ['long', 'Tratament lung', false]])
    expect(picker()?.value).toBe('consult')
    expect(svcBtn().disabled).toBe(true)
  })

  it('сервер снял флаг (закрытый визит, врач в отпуске) — окно не спрашивает, выбора нет', async () => {
    show(card({ status: 'done', service_edit: false }), ok)
    await act(async () => {})
    expect(get).not.toHaveBeenCalled()
    expect(picker()).toBeNull()
  })

  it('без колбэка экрана и у надгробия — не спрашивает и выбора нет', async () => {
    show(card())
    await act(async () => {})
    cleanup()
    show(card(), ok, 'Programarea nu mai există — reîmprospătați pagina')
    await act(async () => {})
    expect(get).not.toHaveBeenCalled()
    expect(picker()).toBeNull()
  })

  it('пустой список или отказ сети — выбора нет, остальное окно живёт', async () => {
    get.mockResolvedValueOnce({ data: { service_id: 'consult', options: [] }, code: '', text: '',
      tone: 'ok' })
    show(card(), ok)
    await act(async () => {})
    expect(picker()).toBeNull()
    cleanup()
    get.mockRejectedValueOnce(new Error('offline'))
    show(card(), ok)
    await act(async () => {})
    expect(picker()).toBeNull()
    expect(document.querySelector('dialog textarea')).toBeTruthy()
  })

  it('нынешней услуги нет среди разрешённых — она первой строкой и не выбирается', async () => {
    show(card({ service: 'Albire veche', service_id: '' }), ok)
    await waitFor(() => expect(picker()).toBeTruthy())
    expect(options()[0]).toEqual(['', 'Albire veche', true])
    expect(picker()?.value).toBe('')
  })

  it('выбрали другую — уходит ключ услуги, удача закрывает окно', async () => {
    const onService = vi.fn(async () => true)
    show(card(), onService)
    await waitFor(() => expect(picker()).toBeTruthy())
    fireEvent.change(picker() as HTMLSelectElement, { target: { value: 'long' } })
    expect(svcBtn().disabled).toBe(false)
    await act(async () => { fireEvent.click(svcBtn()) })
    expect(onService).toHaveBeenCalledWith('long', expect.any(Function))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('⛔ отказ сервера — словом в окне, окно открыто, выбор остаётся', async () => {
    const onService = vi.fn(async (_sid: string, fail: (t: string) => void) => {
      fail('Intervalul este deja ocupat la acest medic')
      return false
    })
    show(card(), onService)
    await waitFor(() => expect(picker()).toBeTruthy())
    fireEvent.change(picker() as HTMLSelectElement, { target: { value: 'long' } })
    await act(async () => { fireEvent.click(svcBtn()) })
    await waitFor(() => expect(banner()).toBe('Intervalul este deja ocupat la acest medic'))
    expect(onClose).not.toHaveBeenCalled()
    expect(picker()?.value).toBe('long')
    // другой выбор снимает слово прежнего отказа
    fireEvent.change(picker() as HTMLSelectElement, { target: { value: 'pain' } })
    expect(banner()).toBe('')
  })

  it('смена со второго рабочего места пересевает нетронутый выбор, тронутый — нет', async () => {
    const r = show(card(), ok)
    await waitFor(() => expect(picker()).toBeTruthy())
    r.rerender(<CardDialog open id={1} card={card({ service: 'Durere acută', service_id: 'pain' })}
      actions={[]} back="/admin/all" busy={false} onClose={onClose} onComment={ok}
      onStatus={ok} onService={ok} />)
    expect(picker()?.value).toBe('pain')
    fireEvent.change(picker() as HTMLSelectElement, { target: { value: 'long' } })
    r.rerender(<CardDialog open id={1} card={card({ service_id: 'consult' })}
      actions={[]} back="/admin/all" busy={false} onClose={onClose} onComment={ok}
      onStatus={ok} onService={ok} />)
    expect(picker()?.value).toBe('long')
    // тот же визит — список не спрашивается заново на каждой перерисовке
    expect(get).toHaveBeenCalledTimes(1)
  })
})
