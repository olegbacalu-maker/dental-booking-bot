import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CardDialog } from './CardDialog'
import type { ServiceOption, StatusAction, VisitCardView } from './day'

/* Окно визита «три этажа» (23.10, выбор Олега по кадрам design/visit-card —
   вариант A с рядом 1): факты → связь → работа и один фирменный акцент.
   ⛔ Набор исходов — матрица СЕРВЕРА (`actions[status]`): окно делит его на
   ступени и исключения по КЛАССУ кнопки и меняет только вес и место.
   ⛔ «Можно ли» сменить процедуру и список решает СЕРВЕР: на карточке —
   только флаг `service_edit`, список окно спрашивает само (`GET …/service`);
   карандаш в строке фактов раскрывает его. Отказ печатается В ОКНЕ. */

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

/* Копия серверной матрицы `core/visits._ACT_BUTTONS` — слова и классы те же,
   что печатает `all_status_actions`. */
const ASK_REOPEN = 'Redeschideți programarea (înapoi la «programată»)?'
const ASK_CANCEL = 'Anulați programarea? Ea dispare din grila zilei; o puteți redeschide din «Lista zilei».'
const REOPEN: StatusAction = { to: 'confirmed', cls: 'b-reopen', label: 'Redeschide', confirm: ASK_REOPEN }
const MATRIX: Record<'confirmed' | 'waiting' | 'arrived' | 'done' | 'noshow' | 'cancelled', StatusAction[]> = {
  confirmed: [
    { to: 'waiting', cls: 'b-waiting', label: 'A venit', confirm: '' },
    { to: 'arrived', cls: 'b-arrived', label: 'În cabinet', confirm: '' },
    { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' },
    { to: 'noshow', cls: 'b-noshow', label: 'Nu a venit', confirm: '' },
    { to: 'cancelled', cls: 'b-cancel', label: 'Anulează', confirm: ASK_CANCEL },
  ],
  waiting: [
    { to: 'arrived', cls: 'b-arrived', label: 'În cabinet', confirm: '' },
    { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' },
    { to: 'cancelled', cls: 'b-cancel', label: 'Anulează', confirm: ASK_CANCEL },
  ],
  arrived: [
    { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' },
    { to: 'cancelled', cls: 'b-cancel', label: 'Anulează', confirm: ASK_CANCEL },
  ],
  done: [REOPEN], noshow: [REOPEN], cancelled: [REOPEN],
}

function card(over: Partial<VisitCardView> = {}): VisitCardView {
  return {
    time: '09:00', name: 'Ion Popa', service: 'Consultație', doctor: 'Dr. Activ Doi',
    phone: '069000000', age: 41, comment: '', status: 'confirmed', pid: 7, rec: false,
    call: '', callable: false, service_id: 'consult', service_edit: true, ...over,
  }
}

const onClose = vi.fn()
const ok = async () => true

interface ShowOpts {
  actions?: StatusAction[]
  note?: string
  onService?: (sid: string, fail: (t: string) => void) => Promise<boolean>
  onDuration?: (minutes: number, fail: (t: string) => void) => Promise<boolean>
  onStatus?: (to: string) => Promise<boolean>
  onComment?: (text: string) => Promise<boolean>
  onCall?: (result: '' | 'ok' | 'noanswer') => Promise<boolean>
  busy?: boolean
}

function show(c: VisitCardView, o: ShowOpts = {}) {
  return render(<CardDialog open id={1} card={c} actions={o.actions ?? []} note={o.note ?? ''}
    back="/admin/all" busy={o.busy ?? false} onClose={onClose}
    onComment={o.onComment ?? ok} onStatus={o.onStatus ?? ok}
    {...(o.onService ? { onService: o.onService } : {})}
    {...(o.onDuration ? { onDuration: o.onDuration } : {})}
    {...(o.onCall ? { onCall: o.onCall } : {})} />)
}

const q = (sel: string) => document.querySelector(sel)
const texts = (sel: string) => Array.from(document.querySelectorAll(sel)).map((b) => b.textContent?.trim())
const pen = () => q('dialog button[aria-label="Schimbă procedura"]') as HTMLButtonElement | null
const picker = () => q('dialog form.dp-card-svc select[aria-label="Procedura"]') as HTMLSelectElement | null
const options = () => Array.from(picker()?.options ?? []).map((o) => [o.value, o.textContent, o.disabled])
const svcBtn = () => Array.from(document.querySelectorAll('dialog form.dp-card-svc button'))
  .find((b) => b.textContent?.trim() === 'Schimbă') as HTMLButtonElement
const svcCancel = () => Array.from(document.querySelectorAll('dialog form.dp-card-svc button'))
  .find((b) => b.textContent?.trim() === 'Renunță') as HTMLButtonElement
const banner = () => q('dialog form[aria-label="Procedura"] .banner.err')?.textContent ?? ''
const area = () => q('dialog textarea') as HTMLTextAreaElement
const saveBtn = () => Array.from(document.querySelectorAll('dialog .dp-card-cmt button'))
  .find((b) => b.textContent?.includes('Salvează comentariul')) as HTMLButtonElement | undefined

beforeEach(() => {
  get.mockResolvedValue({ data: { service_id: 'consult', options: OPTIONS }, code: '', text: '',
    tone: 'ok' })
})
afterEach(() => { cleanup(); onClose.mockClear(); get.mockReset(); vi.restoreAllMocks() })

describe('окно визита: ряд исходов (A + ряд 1, 23.10)', () => {
  const foot = () => ({
    next: texts('dialog .dp-card-foot .dp-card-next'),
    steps: texts('dialog .dp-card-foot .dp-card-step:not(.reopen)'),
    reopen: texts('dialog .dp-card-foot .dp-card-step.reopen'),
    neg: texts('dialog .dp-card-neg button'),
  })

  it('programată: следующий шаг — одна большая кнопка, ступени контуром, исключения тихой строкой', () => {
    show(card(), { actions: MATRIX.confirmed })
    expect(foot()).toEqual({ next: ['A venit'], steps: ['În cabinet', 'Finalizat'], reopen: [],
      neg: ['Nu a venit', 'Anulează'] })
    /* цветных кнопок старого ряда больше нет — ни одной `.bstat` в окне */
    expect(document.querySelectorAll('dialog .bstat').length).toBe(0)
  })

  it('a venit → «În cabinet» крупно; în cabinet → «Finalizat» крупно; «Anulează» остаётся тихой', () => {
    show(card({ status: 'waiting' }), { actions: MATRIX.waiting })
    expect(foot()).toEqual({ next: ['În cabinet'], steps: ['Finalizat'], reopen: [], neg: ['Anulează'] })
    cleanup()
    show(card({ status: 'arrived' }), { actions: MATRIX.arrived })
    expect(foot()).toEqual({ next: ['Finalizat'], steps: [], reopen: [], neg: ['Anulează'] })
  })

  it('закрытый визит (finalizat, nu a venit, anulat): только «Redeschide» контуром', () => {
    for (const st of ['done', 'noshow', 'cancelled'] as const) {
      show(card({ status: st }), { actions: MATRIX[st] })
      expect(foot()).toEqual({ next: [], steps: [], reopen: ['Redeschide'], neg: [] })
      cleanup()
    }
  })

  it('⛔ надгробие: кнопок не прислали — ни ряда, ни тихой строки', () => {
    show(card(), { actions: [], note: 'Programarea nu mai există.' })
    expect(q('dialog .dp-card-foot')).toBeNull()
    expect(q('dialog .dp-card-neg')).toBeNull()
    expect(q('dialog .banner.err')?.textContent).toBe('Programarea nu mai există.')
  })

  it('следующий шаг и ступень шлют свой `to` без вопроса; «Anulează» и «Redeschide» — с серверным словом', async () => {
    const onStatus = vi.fn(async () => true)
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
    show(card(), { actions: MATRIX.confirmed, onStatus })
    await act(async () => { fireEvent.click(q('dialog .dp-card-next') as HTMLButtonElement) })
    expect(onStatus).toHaveBeenLastCalledWith('waiting')
    await act(async () => { fireEvent.click(q('dialog .dp-card-step') as HTMLButtonElement) })
    expect(onStatus).toHaveBeenLastCalledWith('arrived')
    expect(ask).not.toHaveBeenCalled()
    await act(async () => {
      fireEvent.click(Array.from(document.querySelectorAll('dialog .dp-card-neg button'))
        .find((b) => b.textContent === 'Anulează') as HTMLButtonElement)
    })
    expect(ask).toHaveBeenLastCalledWith(ASK_CANCEL)
    expect(onStatus).toHaveBeenCalledTimes(2)       // отказ в вопросе — запроса нет
    cleanup()
    show(card({ status: 'done' }), { actions: MATRIX.done, onStatus })
    await act(async () => { fireEvent.click(q('dialog .dp-card-step.reopen') as HTMLButtonElement) })
    expect(ask).toHaveBeenLastCalledWith(ASK_REOPEN)
    expect(onStatus).toHaveBeenCalledTimes(2)
  })

  it('⭐ деление — по классу сервера: незнакомый класс — ступень, а не исключение', () => {
    show(card(), { actions: [{ to: 'waiting', cls: 'b-wait', label: 'A venit', confirm: '' }] })
    expect(foot()).toEqual({ next: ['A venit'], steps: [], reopen: [], neg: [] })
  })

  it('пока команда в полёте — все кнопки исхода заперты', () => {
    show(card(), { actions: MATRIX.confirmed, busy: true })
    expect(Array.from(document.querySelectorAll('dialog .dp-card-foot button, dialog .dp-card-neg button'))
      .every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
  })
})

describe('окно визита: факты, ссылки, звонок, комментарий (23.10)', () => {
  it('факты двумя строками: услуга · врач, под ними телефон · возраст; ссылки — чипы', () => {
    show(card())
    expect(q('dialog .dp-card-fl')?.textContent).toBe('Consultație·Dr. Activ Doi')
    expect(q('dialog .dp-card-sub')?.textContent).toBe('069000000·41 ani')
    expect(Array.from(document.querySelectorAll('dialog .dp-card-links a.dp-card-chip'))
      .map((a) => [a.getAttribute('href'), a.textContent?.trim()]))
      .toEqual([['/admin/patient/7', 'Fișa pacientului'], ['/admin/visit/1?back=%2Fadmin%2Fall', 'Completează consultația']])
  })

  it('дневник заполнен — «Consultația»; без пациента — ссылок нет вовсе', () => {
    show(card({ rec: true }))
    expect(texts('dialog .dp-card-links a')[1]).toBe('Consultația')
    cleanup()
    show(card({ pid: null }))
    expect(document.querySelectorAll('dialog .dp-card-links').length).toBe(0)
    expect(area()).toBeTruthy()
  })

  it('кнопка сохранения комментария — только у ТРОНУТОГО поля; сохранение закрывает окно, отказ — нет', async () => {
    let answer = false
    const onComment = vi.fn(async () => answer)
    show(card({ comment: 'vechi' }), { onComment })
    expect(saveBtn()).toBeUndefined()
    fireEvent.change(area(), { target: { value: 'vechi' } })     // то же слово — не правка
    expect(saveBtn()).toBeUndefined()
    fireEvent.change(area(), { target: { value: 'nou' } })
    expect(saveBtn()).toBeTruthy()
    await act(async () => { fireEvent.click(saveBtn() as HTMLButtonElement) })
    expect(onComment).toHaveBeenCalledWith('nou')
    expect(onClose).not.toHaveBeenCalled()
    expect(area().value).toBe('nou')
    answer = true
    await act(async () => { fireEvent.click(saveBtn() as HTMLButtonElement) })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('приехавший комментарий пересевает ЧИСТОЕ поле (кнопки нет); тронутое остаётся с кнопкой', () => {
    const r = show(card({ comment: 'a' }))
    r.rerender(<CardDialog open id={1} card={card({ comment: 'b' })} actions={[]} back="/admin/all"
      busy={false} onClose={onClose} onComment={ok} onStatus={ok} />)
    expect(area().value).toBe('b')
    expect(saveBtn()).toBeUndefined()
    fireEvent.change(area(), { target: { value: 'al meu' } })
    r.rerender(<CardDialog open id={1} card={card({ comment: 'c' })} actions={[]} back="/admin/all"
      busy={false} onClose={onClose} onComment={ok} onStatus={ok} />)
    expect(area().value).toBe('al meu')
    expect(saveBtn()).toBeTruthy()
  })

  it('сегмент звонка: щелчок ставит отметку, горит отмеченный, щелчок по горящему СНИМАЕТ (= «Anulează bifa»)', async () => {
    const onCall = vi.fn(async () => true)
    const seg = () => Array.from(document.querySelectorAll('dialog .dp-card-call .dp-card-seg-b')) as HTMLButtonElement[]
    show(card({ callable: true }), { onCall })
    expect(seg().map((b) => [b.textContent?.trim(), b.getAttribute('aria-pressed')]))
      .toEqual([['Confirmat', 'false'], ['Nu răspunde', 'false']])
    await act(async () => { fireEvent.click(seg()[0] as HTMLButtonElement) })
    expect(onCall).toHaveBeenLastCalledWith('ok')
    expect(onClose).not.toHaveBeenCalled()                       // окно остаётся открытым
    cleanup()
    show(card({ callable: true, call: 'ok' }), { onCall })
    expect(seg().map((b) => [b.getAttribute('aria-pressed'), b.classList.contains('on')]))
      .toEqual([['true', true], ['false', false]])
    await act(async () => { fireEvent.click(seg()[0] as HTMLButtonElement) })
    expect(onCall).toHaveBeenLastCalledWith('')
    await act(async () => { fireEvent.click(seg()[1] as HTMLButtonElement) })
    expect(onCall).toHaveBeenLastCalledWith('noanswer')
  })

  it('callable false, без колбэка или у надгробия — сегмента звонка нет', () => {
    show(card({ callable: false }), { onCall: ok })
    expect(q('dialog .dp-card-call')).toBeNull()
    cleanup()
    show(card({ callable: true }))
    expect(q('dialog .dp-card-call')).toBeNull()
    cleanup()
    show(card({ callable: true }), { onCall: ok, note: 'Programarea nu mai există.' })
    expect(q('dialog .dp-card-call')).toBeNull()
  })
})

describe('окно визита: смена процедуры', () => {
  it('список — ответ сервера для ЭТОГО визита; карандаш раскрывает его: нынешняя выбрана, без перемены отправлять нечего', async () => {
    show(card(), { onService: ok })
    await waitFor(() => expect(pen()).toBeTruthy())
    expect(get).toHaveBeenCalledWith('/schedule/appointments/1/service', expect.anything())
    expect(picker()).toBeNull()                                   // до карандаша списка на экране нет
    fireEvent.click(pen() as HTMLButtonElement)
    expect(options()).toEqual([['consult', 'Consultație', false], ['pain', 'Durere acută', false],
      ['long', 'Tratament lung', false]])
    expect(picker()?.value).toBe('consult')
    expect(svcBtn().disabled).toBe(true)
    expect(pen()).toBeNull()                                      // карандаш уступил место списку
  })

  it('сервер снял флаг (закрытый визит, врач в отпуске) — окно не спрашивает, карандаша нет', async () => {
    show(card({ status: 'done', service_edit: false }), { onService: ok })
    await act(async () => {})
    expect(get).not.toHaveBeenCalled()
    expect(pen()).toBeNull()
  })

  it('без колбэка экрана и у надгробия — не спрашивает и карандаша нет', async () => {
    show(card())
    await act(async () => {})
    cleanup()
    show(card(), { onService: ok, note: 'Programarea nu mai există — reîmprospătați pagina' })
    await act(async () => {})
    expect(get).not.toHaveBeenCalled()
    expect(pen()).toBeNull()
  })

  it('пустой список или отказ сети — карандаша нет, остальное окно живёт', async () => {
    get.mockResolvedValueOnce({ data: { service_id: 'consult', options: [] }, code: '', text: '',
      tone: 'ok' })
    show(card(), { onService: ok })
    await act(async () => {})
    expect(pen()).toBeNull()
    cleanup()
    get.mockRejectedValueOnce(new Error('offline'))
    show(card(), { onService: ok })
    await act(async () => {})
    expect(pen()).toBeNull()
    expect(area()).toBeTruthy()
  })

  it('нынешней услуги нет среди разрешённых — она первой строкой и не выбирается', async () => {
    show(card({ service: 'Albire veche', service_id: '' }), { onService: ok })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
    expect(options()[0]).toEqual(['', 'Albire veche', true])
    expect(picker()?.value).toBe('')
  })

  it('выбрали другую — уходит ключ услуги, удача закрывает окно', async () => {
    const onService = vi.fn(async () => true)
    show(card(), { onService })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
    fireEvent.change(picker() as HTMLSelectElement, { target: { value: 'long' } })
    expect(svcBtn().disabled).toBe(false)
    await act(async () => { fireEvent.click(svcBtn()) })
    expect(onService).toHaveBeenCalledWith('long', expect.any(Function))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('«Renunță» прячет список и возвращает нетронутый выбор', async () => {
    show(card(), { onService: ok })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
    fireEvent.change(picker() as HTMLSelectElement, { target: { value: 'long' } })
    fireEvent.click(svcCancel())
    expect(picker()).toBeNull()
    expect(pen()).toBeTruthy()
    fireEvent.click(pen() as HTMLButtonElement)
    expect(picker()?.value).toBe('consult')
  })

  it('⛔ отказ сервера — словом в окне, окно открыто, выбор остаётся', async () => {
    const onService = vi.fn(async (_sid: string, fail: (t: string) => void) => {
      fail('Intervalul este deja ocupat la acest medic')
      return false
    })
    show(card(), { onService })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
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
    const r = show(card(), { onService: ok })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
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

describe('окно визита: длительность (10.11, жалоба пилота «15′, а нужно 30′»)', () => {
  const DURS = [5, 10, 15, 20, 30, 45, 60, 90, 120]
  const durPen = () => q('dialog button[aria-label="Schimbă durata"]') as HTMLButtonElement | null
  const durPicker = () => q('dialog form.dp-card-dur select[aria-label="Durată"]') as HTMLSelectElement | null
  const durBtn = (word: string) => Array.from(document.querySelectorAll('dialog form.dp-card-dur button'))
    .find((b) => b.textContent?.trim() === word) as HTMLButtonElement
  const durBanner = () => q('dialog form[aria-label="Durată"] .banner.err')?.textContent ?? ''
  const facts = () => q('dialog .dp-card-fl')?.textContent ?? ''
  const withDur = (over: Record<string, unknown> = {}) => {
    get.mockResolvedValue({ data: { service_id: 'consult', options: OPTIONS, dur: 30,
      dur_set: false, durations: DURS, dur_step: 5, dur_max: 240, ...over }, code: '', text: '', tone: 'ok' })
  }

  it('длительность — в строке фактов; карандаш раскрывает список сервера: нынешняя выбрана, без перемены отправлять нечего', async () => {
    withDur()
    show(card({ dur: 30 }), { onService: ok, onDuration: ok })
    await waitFor(() => expect(durPen()).toBeTruthy())
    expect(facts()).toContain('30 min')
    expect(durPicker()).toBeNull()
    fireEvent.click(durPen() as HTMLButtonElement)
    expect(Array.from(durPicker()?.options ?? []).map((o) => o.textContent))
      .toEqual(['5 min', '10 min', '15 min', '20 min', '30 min', '45 min', '60 min', '90 min', '120 min',
        'Altă durată…'])
    expect(durPicker()?.value).toBe('30')
    expect(durBtn('Schimbă').disabled).toBe(true)
  })

  it('«Altă durată…»: 35 уходит числом; не кратное 5 и выше потолка — кнопка выключена', async () => {
    withDur()
    const onDuration = vi.fn(async () => true)
    show(card({ dur: 30 }), { onService: ok, onDuration })
    await waitFor(() => expect(durPen()).toBeTruthy())
    fireEvent.click(durPen() as HTMLButtonElement)
    fireEvent.change(durPicker() as HTMLSelectElement, { target: { value: 'other' } })
    const inp = () => q('dialog form.dp-card-dur input.dp-dur-n') as HTMLInputElement
    expect(inp().value).toBe('30')
    for (const raw of ['37', '245', '']) {
      fireEvent.change(inp(), { target: { value: raw } })
      expect(durBtn('Schimbă').disabled).toBe(true)
      expect(q('dialog form.dp-card-dur .dp-dur-rule.bad')).toBeTruthy()
    }
    fireEvent.change(inp(), { target: { value: '35' } })
    expect(q('dialog form.dp-card-dur .dp-dur-rule.bad')).toBeNull()
    await act(async () => { fireEvent.click(durBtn('Schimbă')) })
    expect(onDuration).toHaveBeenCalledWith(35, expect.any(Function))
  })

  it('длительность вне быстрых значений (35) стоит первой строкой списка', async () => {
    withDur({ dur: 35 })
    show(card({ dur: 35 }), { onService: ok, onDuration: ok })
    await waitFor(() => expect(durPen()).toBeTruthy())
    fireEvent.click(durPen() as HTMLButtonElement)
    expect(durPicker()?.options[0]?.textContent).toBe('35 min')
    expect(durPicker()?.value).toBe('35')
  })

  it('выбрали 45 — уходит число минут, удача закрывает окно', async () => {
    withDur()
    const onDuration = vi.fn(async () => true)
    show(card({ dur: 30 }), { onService: ok, onDuration })
    await waitFor(() => expect(durPen()).toBeTruthy())
    fireEvent.click(durPen() as HTMLButtonElement)
    fireEvent.change(durPicker() as HTMLSelectElement, { target: { value: '45' } })
    await act(async () => { fireEvent.click(durBtn('Schimbă')) })
    expect(onDuration).toHaveBeenCalledWith(45, expect.any(Function))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('⛔ отказ сервера (сосед) — словом в окне, окно открыто, выбор остаётся', async () => {
    withDur()
    const onDuration = vi.fn(async (_m: number, fail: (t: string) => void) => {
      fail('Intervalul este deja ocupat la acest medic')
      return false
    })
    show(card({ dur: 30 }), { onService: ok, onDuration })
    await waitFor(() => expect(durPen()).toBeTruthy())
    fireEvent.click(durPen() as HTMLButtonElement)
    fireEvent.change(durPicker() as HTMLSelectElement, { target: { value: '60' } })
    await act(async () => { fireEvent.click(durBtn('Schimbă')) })
    await waitFor(() => expect(durBanner()).toBe('Intervalul este deja ocupat la acest medic'))
    expect(onClose).not.toHaveBeenCalled()
    expect(durPicker()?.value).toBe('60')
  })

  it('«Renunță» возвращает нетронутое; открыт всегда один список — процедура или длительность', async () => {
    withDur()
    show(card({ dur: 30 }), { onService: ok, onDuration: ok })
    await waitFor(() => expect(durPen()).toBeTruthy())
    fireEvent.click(durPen() as HTMLButtonElement)
    fireEvent.change(durPicker() as HTMLSelectElement, { target: { value: '90' } })
    fireEvent.click(pen() as HTMLButtonElement)                    // карандаш процедуры
    expect(durPicker()).toBeNull()
    expect(picker()).toBeTruthy()
    fireEvent.click(durPen() as HTMLButtonElement)
    expect(picker()).toBeNull()
    expect(durPicker()?.value).toBe('30')                          // выбор сброшен закрытием
    fireEvent.click(durBtn('Renunță'))
    expect(durPicker()).toBeNull()
    expect(durPen()).toBeTruthy()
  })

  it('длительность, заданная руками, — смена процедуры предупреждает, что её не тронет', async () => {
    withDur({ dur_set: true })
    show(card({ dur: 30 }), { onService: ok, onDuration: ok })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
    expect(q('dialog form.dp-card-svc .dp-card-kept')?.textContent)
      .toBe('Durata rămâne 30 min — aleasă manual.')
  })

  it('минуты услуги — в списке процедур («Consultație · 15 min»)', async () => {
    withDur({ options: [{ id: 'consult', label: 'Consultație', dur: 15 },
      { id: 'long', label: 'Tratament lung', dur: 120 }] })
    show(card({ dur: 15 }), { onService: ok, onDuration: ok })
    await waitFor(() => expect(pen()).toBeTruthy())
    fireEvent.click(pen() as HTMLButtonElement)
    expect(options().map((o) => o[1])).toEqual(['Consultație · 15 min', 'Tratament lung · 120 min'])
  })

  it('сервер снял флаг или нет колбэка — минуты видны, карандаша нет; нет поля — нет и строки', async () => {
    withDur()
    show(card({ dur: 30, status: 'done', service_edit: false }), { onService: ok, onDuration: ok })
    await act(async () => {})
    expect(facts()).toContain('30 min')
    expect(durPen()).toBeNull()
    cleanup()
    show(card({ dur: 30 }), { onService: ok })
    await act(async () => {})
    expect(durPen()).toBeNull()
    cleanup()
    show(card(), { onService: ok, onDuration: ok })
    await act(async () => {})
    expect(facts()).not.toContain('min')
    expect(durPen()).toBeNull()
  })
})
