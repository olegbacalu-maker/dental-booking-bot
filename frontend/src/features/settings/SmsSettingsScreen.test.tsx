import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import type { SmsData } from './settings'
import { loadSmsSettings, SmsSettingsScreen } from './SmsSettingsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const PV = (word: string) => ({
  ro: { text: `Buna ziua! Clinica Test va reaminteste ca ${word}, 17.10, la ora 12:00 aveti o programare la noi. O zi buna!`, segments: 1 },
  ru: { text: `Клиника Test: ждём вас ${word === 'maine' ? 'завтра' : 'сегодня'}, 17.10, в 12:00.`, segments: 1 },
})

const BASE: SmsData = {
  available: true, offered: true, enabled: true, active: true, why: '', blocked: '',
  account: {
    balance: 42, from: 'DentPilot', sender: '', sender_state: 'none', sender_note: '', sender_until: '',
    packs: [{ units: 100, price: 150 }, { units: 300, price: 400 }], name_price: 200, name_days: 365,
    daily_cap: 300, used_today: 3,
  },
  settings: {
    day_before: { on: true, hour: 10, variant: 'standard' },
    same_day: { on: false, hours: 2, variant: 'standard' },
    phone_line: false,
    recall: { on: true, variant: 'standard', auto: false },
  },
  options: {
    hours: [8, 9, 10, 11, 12], leads: [1, 2, 3],
    variants: [{ key: 'standard', label: 'Standard' }, { key: 'scurt', label: 'Scurt' }],
    recall_variants: [{ key: 'standard', label: 'Standard' }, { key: 'scurt', label: 'Scurt' }],
    recall_auto_daily: 20,
  },
  previews: {
    day_before: { standard: PV('maine'), scurt: PV('maine') },
    same_day: { standard: PV('astazi'), scurt: PV('astazi') },
    recall: {
      standard: {
        ro: { text: 'Buna ziua! Clinica Test va reaminteste ca a venit timpul pentru controlul periodic. Pentru programare: +373 60 000 000. O zi buna!', segments: 1 },
        ru: { text: 'Клиника Test: пора на плановый осмотр. Тел. +373 60 000 000', segments: 1 },
      },
      scurt: {
        ro: { text: 'Clinica Test: e timpul pentru controlul periodic. Programari: +373 60 000 000.', segments: 1 },
        ru: { text: 'Клиника Test: плановый осмотр. Тел. +373 60 000 000', segments: 1 },
      },
    },
  },
  forecast: { visits: 120, month: 120, daily: 4, days_left: 10 },
  low: null,
  counts: { queued: 2, today: 3, delivered: 1, failed: 0 },
  last: { at: '2026-10-16T09:00:00Z', when: '16.10.2026 12:00', outcome: 'sent', error_text: '' },
  can_order: true,
  clinic: { name: 'Clinica Test', phone: '+373 60 000 000' },
  support: { phone: '+373 60 508 048', email: 'contact@dentpilot.md' },
}

const open = () => openScreen('/admin/settings/sms', '/admin/settings/sms', <SmsSettingsScreen />, loadSmsSettings)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('SmsSettingsScreen', () => {
  it('пакет включён: остаток, события, предпросмотр со своим названием и числом SMS', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    open()
    expect(await screen.findByText('42')).toBeTruthy()
    expect(screen.getByText('DentPilot')).toBeTruthy()
    expect(screen.getByText(/Clinica Test va reaminteste ca maine/)).toBeTruthy()
    expect(screen.getAllByText('română · 1 SMS').length).toBe(2)   // накануне + Rechemări (30.10)
    expect(screen.getByText(/~120 SMS pe lună/)).toBeTruthy()
    expect(screen.getByText(/restul ajunge pentru ~10 zile/)).toBeTruthy()
    const day = screen.getByLabelText('Cu o zi înainte') as HTMLInputElement
    expect(day.checked).toBe(true)
    expect((screen.getByLabelText('În ziua vizitei') as HTMLInputElement).checked).toBe(false)
    expect(screen.queryByText(/Clinica Test va reaminteste ca astazi/)).toBeNull()
  })

  it.each([[1, '~1 zi'], [2, '~2 zile'], [20, '~20 de zile']])(
    'остаток на %i дн. — румынской формой «%s» (09.11: было «~1 zile»)', async (days, want) => {
      get.mockResolvedValueOnce(ok({ ...BASE, forecast: { ...BASE.forecast, days_left: days } }))
      open()
      await screen.findByText('42')
      expect(screen.getByText(new RegExp(`restul ajunge pentru ${want}$`))).toBeTruthy()
    })

  it('ultima verificare — готовое время сервера в поясе клиники, не сырая ISO-строка (07.11)', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    open()
    await screen.findByText('42')
    /* сервер хранит UTC (`at`, 09:00Z) и сам переводит в пояс клиники (`when`, 12:00);
       экран режет ISO — и час уезжает на UTC */
    expect(screen.getByText(/ultima verificare: 16\.10\.2026 12:00/)).toBeTruthy()
    expect(screen.queryByText(/2026-10-16/)).toBeNull()
  })

  it('переключатель сохраняется сразу: POST с полной формой, ответ подменяет данные', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    const after: SmsData = { ...BASE, settings: { ...BASE.settings, same_day: { ...BASE.settings.same_day, on: true } } }
    post.mockResolvedValueOnce(ok(after, 'ok_sms', 'Setări SMS salvate'))
    open()
    await screen.findByText('42')
    fireEvent.click(screen.getByLabelText('În ziua vizitei'))
    expect(post).toHaveBeenCalledWith('/settings/sms', {
      day_before: { on: true, hour: 10, variant: 'standard' },
      same_day: { on: true, hours: 2, variant: 'standard' },
      phone_line: false,
      recall: { on: true, variant: 'standard', auto: false },
    })
    expect(await screen.findByText('Setări SMS salvate')).toBeTruthy()
    expect(screen.getByText(/Clinica Test va reaminteste ca astazi/)).toBeTruthy()
    expect((screen.getByLabelText('În ziua vizitei') as HTMLInputElement).checked).toBe(true)
  })

  it('Rechemări (30.10): галочка «Buton SMS» включена, предпросмотр без услуги; снятие шлёт полную форму', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    const after: SmsData = { ...BASE, settings: { ...BASE.settings, recall: { on: false, variant: 'standard', auto: false } } }
    post.mockResolvedValueOnce(ok(after, 'ok_sms', 'Setări SMS salvate'))
    open()
    await screen.findByText('42')
    const box = screen.getByLabelText('Buton „SMS” în lista Rechemări') as HTMLInputElement
    expect(box.checked).toBe(true)
    expect(screen.getByText(/a venit timpul pentru controlul periodic/)).toBeTruthy()
    expect(screen.getByText(/пора на плановый осмотр/)).toBeTruthy()
    /* автоматическая отправка: выключена по умолчанию, лимит дня — число сервера */
    const auto = screen.getByLabelText('Trimite SMS automat când pacientul ajunge în listă') as HTMLInputElement
    expect(auto.checked).toBe(false)
    expect(auto.disabled).toBe(false)
    expect(screen.getByText(/cel mult 20 SMS pe zi/)).toBeTruthy()
    fireEvent.click(box)
    expect(post).toHaveBeenCalledWith('/settings/sms', { ...BASE.settings, recall: { on: false, variant: 'standard', auto: false } })
    expect(await screen.findByText('Setări SMS salvate')).toBeTruthy()
    expect(screen.queryByText(/a venit timpul pentru controlul periodic/)).toBeNull()
    /* без кнопки автоматика недоступна */
    expect((screen.getByLabelText('Trimite SMS automat când pacientul ajunge în listă') as HTMLInputElement).disabled).toBe(true)
  })

  it('Rechemări: галочка автоматической отправки шлёт полную форму с auto: true', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    const after: SmsData = { ...BASE, settings: { ...BASE.settings, recall: { on: true, variant: 'standard', auto: true } } }
    post.mockResolvedValueOnce(ok(after, 'ok_sms', 'Setări SMS salvate'))
    open()
    await screen.findByText('42')
    fireEvent.click(screen.getByLabelText('Trimite SMS automat când pacientul ajunge în listă'))
    expect(post).toHaveBeenCalledWith('/settings/sms', { ...BASE.settings, recall: { on: true, variant: 'standard', auto: true } })
    expect(await screen.findByText('Setări SMS salvate')).toBeTruthy()
    expect((screen.getByLabelText('Trimite SMS automat când pacientul ajunge în listă') as HTMLInputElement).checked).toBe(true)
  })

  it('вариант текста и час — тем же сохранением', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    post.mockResolvedValue(ok(BASE))
    open()
    await screen.findByText('42')
    fireEvent.change(screen.getByLabelText('Cu o zi înainte — textul'), { target: { value: 'scurt' } })
    await waitFor(() => expect(post).toHaveBeenCalledWith('/settings/sms', expect.objectContaining({
      day_before: { on: true, hour: 10, variant: 'scurt' },
    })))
    fireEvent.change(screen.getByLabelText('Cu o zi înainte — ora'), { target: { value: '12' } })
    await waitFor(() => expect(post).toHaveBeenLastCalledWith('/settings/sms', expect.objectContaining({
      day_before: { on: true, hour: 12, variant: 'standard' },
    })))
  })

  const NOTE = { kind: 'sms', reference: 'DP-7', amount: 150, units: 100, pay_url: 'https://cloud.dentpilot.md/plata/x' }
  const withNotes = (notes: unknown): SmsData => ({ ...BASE, account: { ...BASE.account!, notes } as SmsData['account'] })

  it('директор: пополнение — окно называет карту и перевод, POST order, блок ноты из свежих данных экрана', async () => {
    get.mockResolvedValueOnce(ok(withNotes([])))
    post.mockResolvedValueOnce(ok({ ...NOTE, created: true, screen: withNotes([NOTE]) }, 'sms_order_ok', 'Nota este gata'))
    const asked = vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    open()
    await screen.findByText('42')
    expect(screen.queryByText('Nota de plată DP-7')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '100 SMS — 150 MDL' }))
    expect(await screen.findByText('Nota de plată DP-7')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/sms/order', { pack: 100 })
    // окно говорит, что будет после клика и чем платить, — не «нота придёт на e-mail» и всё
    const question = String(asked.mock.calls[0]?.[0])
    expect(question).toContain('Comandați 100 SMS pentru 150 MDL?')
    expect(question).toContain('cu cardul')
    expect(question).toContain('transfer bancar')
    const pay = screen.getByRole('link', { name: 'Plătește cu cardul' })
    expect(pay.getAttribute('href')).toBe('https://cloud.dentpilot.md/plata/x')
    expect(pay.getAttribute('target')).toBe('_blank')
    // рядом — плашка «нота готова» с той же ролью: блок ноты ищем по его словам
    expect(screen.getAllByRole('status').map((e) => e.textContent ?? '')
      .some((t) => t.includes('Nota de plată DP-7 — pachet 100 SMS: 150 MDL · în așteptare'))).toBe(true)
  })

  it('ожидающая нота стоит на экране при каждом открытии — без заказа, с картой, способами оплаты и переводом', async () => {
    get.mockResolvedValueOnce(ok(withNotes([NOTE, { kind: 'sms_name', reference: 'DP-8', amount: 200, units: null, pay_url: '' }])))
    open()
    await screen.findByText('42')
    expect(post).not.toHaveBeenCalled()
    const [pack, name] = screen.getAllByRole('status')
    expect(pack?.textContent).toContain('Nota de plată DP-7 — pachet 100 SMS: 150 MDL · în așteptare')
    expect(name?.textContent).toContain('Nota de plată DP-8 — numele de expeditor, un an: 200 MDL · în așteptare')
    // карта — только у ноты со страницей оплаты; фраза о способах — слово в слово страницы оплаты
    expect(screen.getAllByRole('link', { name: 'Plătește cu cardul' })).toHaveLength(1)
    expect(screen.getByText(/pagina securizată a băncii maib: card Visa sau Mastercard, Google Pay sau Apple Pay\. Datele cardului nu ajung la DentPilot\./)).toBeTruthy()
    expect(screen.getByText(/^Sau prin transfer bancar: .* SMS-urile se adaugă automat\.$/)).toBeTruthy()
    expect(screen.getByText(/^Prin transfer bancar: .* anul numelui se înregistrează automat\.$/)).toBeTruthy()
    // пакеты остаются в продаже рядом с нотой
    expect(screen.getByRole('button', { name: '100 SMS — 150 MDL' })).toBeTruthy()
  })

  it('нота оплачена или отклонена — сервер её больше не шлёт, блок уходит сам («Verifică acum»)', async () => {
    get.mockResolvedValueOnce(ok(withNotes([NOTE])))
    post.mockResolvedValueOnce(ok(withNotes([])))
    open()
    expect(await screen.findByText('Nota de plată DP-7')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Verifică acum/ }))
    await waitFor(() => expect(screen.queryByText('Nota de plată DP-7')).toBeNull())
    expect(screen.queryByRole('link', { name: 'Plătește cu cardul' })).toBeNull()
  })

  it('сервер до 05.11 (нот в счёте нет): экран открывается как раньше, после заказа — нота из ответа заказа', async () => {
    // BASE без поля `notes` — так отвечает старый сервер; ответ заказа без `screen` — старый движок не бывает,
    // но поле необязательное: экран обязан жить и без него
    get.mockResolvedValueOnce(ok(BASE))
    post.mockResolvedValueOnce(ok({ ...NOTE, created: true }, 'sms_order_ok', 'Nota este gata'))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    open()
    await screen.findByText('42')
    expect(screen.queryByRole('status')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '100 SMS — 150 MDL' }))
    expect(await screen.findByText('Nota de plată DP-7')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Plătește cu cardul' }).getAttribute('href')).toBe('https://cloud.dentpilot.md/plata/x')
    // и явный null вместо списка — то же, что отсутствие поля
    cleanup()
    get.mockResolvedValueOnce(ok(withNotes(null)))
    open()
    await screen.findByText('42')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('шесть пакетов с сервера: экран рисует все, в порядке сервера (по units), без своего списка', async () => {
    // цены — только с сервера (cloud.env DP_SMS_PACKS; в Git цен нет): число кнопок = число пакетов
    const packs = [100, 200, 300, 400, 500, 1000].map((units, i) => ({ units, price: ([1, 2, 3, 4, 5, 7][i] ?? 0) * 10 }))
    get.mockResolvedValueOnce(ok({ ...BASE, account: { ...BASE.account!, packs } }))
    open()
    await screen.findByText('42')
    const labels = screen.getAllByRole('button', { name: /^\d+ SMS — \d+ MDL$/ }).map((b) => b.textContent?.trim())
    expect(labels).toEqual(packs.map((p) => `${p.units} SMS — ${p.price} MDL`))
    expect(labels[5]).toBe('1000 SMS — 70 MDL')
    expect(screen.queryByText('Pachetele nu sunt încă disponibile.')).toBeNull()
  })

  it('имя отправителя: правило стоит под полем, 12-й знак не вводится, недопустимое не уходит заявкой', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    open()
    await screen.findByText('42')
    const field = screen.getByLabelText<HTMLInputElement>('Numele (ex. ZambetDent)')
    const btn = screen.getByRole<HTMLButtonElement>('button', { name: 'Cere numele' })
    expect(screen.getByText(/Maximum 11 caractere: litere latine, cifre, spațiu, punct sau cratimă\./)).toBeTruthy()
    expect(field.maxLength).toBe(11)
    expect(btn.disabled).toBe(true)

    fireEvent.change(field, { target: { value: 'ZambetDental' } })
    expect(field.value).toBe('ZambetDenta')
    expect(screen.getByText(/11 \/ 11/)).toBeTruthy()
    expect(btn.disabled).toBe(false)

    fireEvent.change(field, { target: { value: 'Zâmbet' } })
    expect(screen.getByRole('alert').textContent).toContain('„â”')
    expect(field.getAttribute('aria-invalid')).toBe('true')
    expect(btn.disabled).toBe(true)
    fireEvent.submit(field.closest('form')!)

    fireEvent.change(field, { target: { value: '12345' } })
    expect(screen.getByRole('alert').textContent).toBe('Numele trebuie să conțină cel puțin o literă.')
    fireEvent.submit(field.closest('form')!)
    expect(post).not.toHaveBeenCalled()

    fireEvent.change(field, { target: { value: 'Dr.Pop-2 A' } })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(btn.disabled).toBe(false)
  })

  it('отказ в вопросе — ничего не шлёт; заявка на имя — POST sender', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    post.mockResolvedValueOnce(ok({ ...BASE, account: { ...BASE.account!, sender: 'ZambetDent', sender_state: 'requested' } }))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
    open()
    await screen.findByText('42')
    fireEvent.click(screen.getByRole('button', { name: '300 SMS — 400 MDL' }))
    expect(post).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Numele (ex. ZambetDent)'), { target: { value: 'ZambetDent' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cere numele' }))
    expect(post).toHaveBeenCalledWith('/settings/sms/sender', { name: 'ZambetDent' })
    expect(await screen.findByText(/cerere trimisă/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Cere numele' })).toBeNull()
  })

  it('регистратура: переключатели есть, «Comandă» и тест — нет', async () => {
    get.mockResolvedValueOnce(ok({ ...BASE, can_order: false }))
    open()
    await screen.findByText('42')
    expect(screen.getByLabelText('Cu o zi înainte')).toBeTruthy()
    expect(screen.getByText('Comanda și testul — doar directorul.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '100 SMS — 150 MDL' })).toBeNull()
    expect(screen.queryByText('SMS de test')).toBeNull()
  })

  it('мало SMS: баннер словами сервера, без дней; сервер не предлагает пакет: объяснение без счёта', async () => {
    const text = 'Au rămas 30 SMS în pachet; când se termină, memento-urile nu mai pleacă. '
      + 'Comandați un pachet nou în Setări › SMS.'
    get.mockResolvedValueOnce(ok({ ...BASE, low: { left: 30, limit: 30, trial: false,
      title: 'Pachetul SMS se termină', text }, forecast: { ...BASE.forecast, days_left: 3 } }))
    open()
    const banner = (await screen.findByText(/Au rămas 30 SMS în pachet/)).closest('.banner')
    expect(banner?.textContent).toBe(`Pachetul SMS se termină. ${text}`)
    expect(banner?.textContent).not.toMatch(/zile/)
    cleanup()
    get.mockResolvedValueOnce(ok({ ...BASE, offered: false, enabled: false, active: false, account: null,
      why: 'modulul SMS nu este disponibil' }))
    open()
    expect(await screen.findByText(/Modulul SMS nu este disponibil acum pentru clinica dvs/)).toBeTruthy()
    expect(screen.queryByText('SMS rămase')).toBeNull()
    expect(screen.getByLabelText('Cu o zi înainte')).toBeTruthy()
  })

  it('модуль выключен в облаке: Basic ведёт к Plus, тумблер — к нам; спокойная строка, не ошибка', async () => {
    get.mockResolvedValueOnce(ok({ ...BASE, enabled: false, active: false, blocked: 'sms_basic',
      why: 'modulul SMS este oprit (face parte din DentPilot Plus)' }))
    open()
    const line = await screen.findByText('Modulul SMS este oprit: el face parte din DentPilot Plus.')
    const banner = line.closest('.banner') as HTMLElement
    expect(banner.className).toContain('warn')
    expect(banner.getAttribute('role')).toBe('status')
    expect(banner.textContent).toContain('Îl porniți plătind varianta Plus în Setări › Licența („Plătește acum”) '
      + 'sau scriindu-ne: +373 60 508 048 · contact@dentpilot.md')
    expect(screen.queryByRole('alert')).toBeNull()
    cleanup()
    // тумблер облака (исключения) — та же спокойная строка, но без «Plus»: клиника может быть на Plus
    get.mockResolvedValueOnce(ok({ ...BASE, enabled: false, active: false, blocked: 'sms_off',
      why: 'modulul SMS este oprit' }))
    open()
    const off = (await screen.findByText('Modulul SMS este oprit.')).closest('.banner') as HTMLElement
    expect(off.className).toContain('warn')
    expect(off.textContent).toBe('Modulul SMS este oprit. Pentru reluare, contactați-ne: +373 60 508 048 · contact@dentpilot.md')
    expect(screen.queryByText(/DentPilot Plus/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    cleanup()
    get.mockResolvedValueOnce(ok({ ...BASE, enabled: false, active: false, blocked: 'sms_plan',
      why: 'abonamentul nu este activ' }))
    open()
    expect((await screen.findByRole('alert')).textContent).toBe('abonamentul nu este activ')
    expect(screen.queryByText(/Modulul SMS este oprit/)).toBeNull()
    cleanup()
    // код, которого программа не знает, — виден как есть красной строкой, а не спрятан
    get.mockResolvedValueOnce(ok({ ...BASE, enabled: false, active: false, blocked: 'sms_new', why: 'sms_new' }))
    open()
    expect((await screen.findByRole('alert')).textContent).toBe('sms_new')
    expect(screen.queryByText(/Modulul SMS este oprit/)).toBeNull()
  })

  it('без лицензии с renew: одна фраза, ни счёта, ни событий', async () => {
    get.mockResolvedValueOnce(ok({ ...BASE, available: false, offered: false, enabled: false, active: false, account: null }))
    open()
    expect(await screen.findByText(/doar în programul activat cu licență/)).toBeTruthy()
    expect(screen.queryByLabelText('Cu o zi înainte')).toBeNull()
  })
})


/* Premium волна 2а: «Detaliat», ответ пациента ссылкой, плашка ответа, подарки, разбивка расхода
   (кадры design/premium-w2, раскладка A). Поля — `plink_loop.screen`, `sms_loop.screen`. */
const LINK_PV = {
  ro: { text: 'Buna ziua! Clinica Test va reaminteste de programarea dvs.: maine, 17.10, ora 12:00.\nConfirmare/anulare: v.dentpilot.md/K7Q2MX', segments: 2 },
  ru: { text: 'Клиника Test: вы записаны завтра, 17.10, в 12:00.\nОтветить: v.dentpilot.md/K7Q2MX', segments: 2 },
}
const DET_PV = {
  ro: { text: 'Buna ziua! Clinica Test va reaminteste de programarea dvs.: maine, 17.10, ora 12:00. Va rugam sa veniti cu 10 minute mai devreme.', segments: 2 },
  ru: { text: 'Клиника Test: вы записаны завтра, 17.10, в 12:00. Приходите за 10 минут.', segments: 2 },
}
const LINK = {
  allowed: true, until: '30.11.2027', confirm: true, on: true, notify: true, notify_on: true,
  event: 'day_before', variant: 'detaliat', parts: 2,
}
const W2: SmsData = {
  ...BASE,
  account: { ...BASE.account!, sender: 'ZambetDent', sender_state: 'active', from: 'ZambetDent',
    name_year: 'free', gifts: { bonus_units: 80, bonus_day: '12.11.2026', name_free: true } },
  settings: { ...BASE.settings, link: { confirm: true, notify: true } },
  options: { ...BASE.options, variants: [
    { key: 'standard', label: 'Standard', parts: 1 }, { key: 'scurt', label: 'Scurt', parts: 1 },
    { key: 'detaliat', label: 'Detaliat', parts: 2 }] },
  previews: { ...BASE.previews,
    day_before: { ...BASE.previews.day_before, detaliat: DET_PV },
    same_day: { ...BASE.previews.same_day, detaliat: DET_PV },
    link: LINK_PV as never },
  forecast: { visits: 118, month: 236, daily: 7.9, days_left: 5, parts: { day_before: 2, same_day: 0 } },
  link: LINK,
}
const PLUS: SmsData = {
  ...W2,
  account: { ...BASE.account!, name_year: 'unpaid', gifts: { bonus_units: 0, bonus_day: '', name_free: false } },
  settings: { ...W2.settings, day_before: { ...W2.settings.day_before, variant: 'detaliat' }, link: { confirm: false, notify: true } },
  link: { ...LINK, allowed: false, until: '', confirm: false, on: false, notify_on: false },
}

describe('SmsSettingsScreen — Premium волна 2а', () => {
  it('Premium: галочка ссылки с меткой, пояснение, предупреждение «2 SMS», текст заперт на «Detaliat», предпросмотр со ссылкой', async () => {
    get.mockResolvedValueOnce(ok(W2))
    open()
    await screen.findByText('42')
    const link = screen.getByLabelText(/Pacientul răspunde prin link/) as HTMLInputElement
    expect(link.checked).toBe(true)
    expect(link.disabled).toBe(false)
    expect(link.closest('label')!.querySelector('.dp-sms-tag')!.textContent).toBe('Premium')
    expect(screen.getByText(/Programul nu anulează nimic singur/)).toBeTruthy()
    expect(screen.getByText(/2 SMS din pachet pentru fiecare memento „Cu o zi înainte” \(în loc de 1\)/)).toBeTruthy()
    const sel = screen.getByLabelText('Cu o zi înainte — textul') as HTMLSelectElement
    expect(sel.disabled).toBe(true)
    expect(sel.value).toBe('detaliat')
    expect(sel.selectedOptions[0]!.textContent).toBe('Detaliat (2 SMS)')
    expect(screen.getByText('cu link — textul Detaliat')).toBeTruthy()
    // предпросмотр накануне — текст со ссылкой сервера, а не выбранный вариант
    expect(screen.getByText(/Confirmare\/anulare: v\.dentpilot\.md\/K7Q2MX/)).toBeTruthy()
    expect(screen.queryByText(/Clinica Test va reaminteste ca maine/)).toBeNull()
    expect(screen.getAllByText('română · 2 SMS pe memento').length).toBe(1)
    expect(screen.queryByText('Disponibil în Premium')).toBeNull()
  })

  it('Premium: подарки в «Starea pachetului», имя «inclus în Premium anual», без заказа года имени', async () => {
    get.mockResolvedValueOnce(ok(W2))
    open()
    await screen.findByText('42')
    const box = document.querySelector('.dp-sms-incl') as HTMLElement
    expect(box.textContent).toContain('80 SMS incluse la prima plată Premium · adăugate pe 12.11.2026')
    expect(box.textContent).toContain('Numele expeditorului (până la 11 caractere) inclus (Premium anual) · ZambetDent, fără plata anului numelui')
    expect(screen.getByText(/activ · inclus în Premium anual/)).toBeTruthy()
    expect(screen.queryByText(/Comandă numele/)).toBeNull()
  })

  it('облако без подарков (старое или Plus): строк подарков нет, заказ года имени на месте', async () => {
    get.mockResolvedValueOnce(ok({ ...W2, account: { ...BASE.account!, sender: 'Zmb', sender_state: 'active' } }))
    open()
    await screen.findByText('42')
    expect(document.querySelector('.dp-sms-incl')).toBeNull()
    expect(screen.getByText(/Comandă numele — 200 MDL/)).toBeTruthy()
  })

  it('Plus: серо «Disponibil în Premium» со значком замка, «Detaliat» без ссылки выбирается, плашка ответов неактивна', async () => {
    get.mockResolvedValueOnce(ok(PLUS))
    open()
    await screen.findByText('42')
    const link = screen.getByLabelText(/Pacientul răspunde prin link/) as HTMLInputElement
    expect(link.disabled).toBe(true)
    expect(link.checked).toBe(false)
    const chip = screen.getByText('Disponibil în Premium').closest('.chip') as HTMLElement
    expect(chip.querySelector('svg')).toBeTruthy()          // замок — наш SVG, не знак Windows
    expect(screen.getByText(/fără să sune la clinică/)).toBeTruthy()
    expect(screen.queryByText(/Atenție: SMS-ul cu link/)).toBeNull()
    expect((screen.getByLabelText('Anunță pe ecran răspunsurile pacienților') as HTMLInputElement).disabled).toBe(true)
    expect(document.querySelector('.dp-sms-incl')).toBeNull()
    const sel = screen.getByLabelText('Cu o zi înainte — textul') as HTMLSelectElement
    expect(sel.disabled).toBe(false)
    expect(sel.value).toBe('detaliat')
    expect(screen.queryByText(/cu link — textul/)).toBeNull()
    // «Detaliat» без ссылки — свой предпросмотр, 2 SMS
    expect(screen.getByText(/Va rugam sa veniti cu 10 minute mai devreme/)).toBeTruthy()
    expect(screen.queryByText(/v\.dentpilot\.md/)).toBeNull()
  })

  it('галочка ссылки и плашки ответов шлют `link` целиком; без ссылки плашка ответов неактивна', async () => {
    const off: SmsData = { ...W2, settings: { ...W2.settings, link: { confirm: false, notify: true } },
      link: { ...LINK, confirm: false, on: false, notify_on: false } }
    get.mockResolvedValueOnce(ok(off))
    post.mockResolvedValueOnce(ok(W2, 'ok_sms', 'Setări SMS salvate'))
    open()
    await screen.findByText('42')
    const notify = screen.getByLabelText('Anunță pe ecran răspunsurile pacienților') as HTMLInputElement
    expect(notify.disabled).toBe(true)
    expect(screen.queryByText(/Plăcuță jos în dreapta/)).toBeNull()
    // текст не заперт, пока ссылки нет
    expect((screen.getByLabelText('Cu o zi înainte — textul') as HTMLSelectElement).disabled).toBe(false)
    fireEvent.click(screen.getByLabelText(/Pacientul răspunde prin link/))
    expect(post).toHaveBeenLastCalledWith('/settings/sms', expect.objectContaining({ link: { confirm: true, notify: true } }))
    await screen.findByText('Setări SMS salvate')
    const on = screen.getByLabelText('Anunță pe ecran răspunsurile pacienților') as HTMLInputElement
    expect(on.disabled).toBe(false)
    expect(on.checked).toBe(true)
    expect(screen.getByText(/Plăcuță jos în dreapta/)).toBeTruthy()
    post.mockResolvedValueOnce(ok(W2))
    fireEvent.click(on)
    expect(post).toHaveBeenLastCalledWith('/settings/sms', expect.objectContaining({ link: { confirm: true, notify: false } }))
  })

  it('«Consum estimat» — разбивка по напоминаниям; строка под предпросмотрами честна о числе SMS', async () => {
    get.mockResolvedValueOnce(ok(W2))
    open()
    await screen.findByText('42')
    const items = [...document.querySelectorAll('.dp-sms-fc li')].map((li) => li.textContent)
    expect(items).toEqual(['Cu o zi înainte — 118 × 2 SMS = 236 (textul cu link)', 'În ziua vizitei — oprit'])
    expect(screen.queryByText(/un singur SMS/)).toBeNull()
    expect(screen.getByText(/Detaliat și textul cu link — 2 SMS/)).toBeTruthy()
  })

  it('сервер до волны 2а (нет `link`, `parts`): блока ссылки нет, варианты без числа', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    open()
    await screen.findByText('42')
    expect(screen.queryByLabelText(/Pacientul răspunde prin link/)).toBeNull()
    expect(document.querySelector('.dp-sms-fc')).toBeNull()
    expect((screen.getByLabelText('Cu o zi înainte — textul') as HTMLSelectElement).selectedOptions[0]!.textContent).toBe('Standard')
  })
})
