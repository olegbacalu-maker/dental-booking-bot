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
    recall: { on: true, variant: 'standard' },
  },
  options: {
    hours: [8, 9, 10, 11, 12], leads: [1, 2, 3],
    variants: [{ key: 'standard', label: 'Standard' }, { key: 'scurt', label: 'Scurt' }],
    recall_variants: [{ key: 'standard', label: 'Standard' }, { key: 'scurt', label: 'Scurt' }],
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
  last: { at: '2026-10-16T09:00:00Z', outcome: 'sent', error_text: '' },
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
      recall: { on: true, variant: 'standard' },
    })
    expect(await screen.findByText('Setări SMS salvate')).toBeTruthy()
    expect(screen.getByText(/Clinica Test va reaminteste ca astazi/)).toBeTruthy()
    expect((screen.getByLabelText('În ziua vizitei') as HTMLInputElement).checked).toBe(true)
  })

  it('Rechemări (30.10): галочка «Buton SMS» включена, предпросмотр без услуги; снятие шлёт полную форму', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    const after: SmsData = { ...BASE, settings: { ...BASE.settings, recall: { on: false, variant: 'standard' } } }
    post.mockResolvedValueOnce(ok(after, 'ok_sms', 'Setări SMS salvate'))
    open()
    await screen.findByText('42')
    const box = screen.getByLabelText('Buton „SMS” în lista Rechemări') as HTMLInputElement
    expect(box.checked).toBe(true)
    expect(screen.getByText(/a venit timpul pentru controlul periodic/)).toBeTruthy()
    expect(screen.getByText(/пора на плановый осмотр/)).toBeTruthy()
    fireEvent.click(box)
    expect(post).toHaveBeenCalledWith('/settings/sms', { ...BASE.settings, recall: { on: false, variant: 'standard' } })
    expect(await screen.findByText('Setări SMS salvate')).toBeTruthy()
    expect(screen.queryByText(/a venit timpul pentru controlul periodic/)).toBeNull()
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

  it('директор: пополнение — вопрос, POST order, нота со ссылкой на оплату', async () => {
    get.mockResolvedValueOnce(ok(BASE))
    post.mockResolvedValueOnce(ok({ kind: 'sms', reference: 'DP-7', amount: 150, units: 100,
      pay_url: 'https://cloud.dentpilot.md/plata/x', created: true }, 'sms_order_ok', 'Nota a fost emisă'))
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    open()
    await screen.findByText('42')
    fireEvent.click(screen.getByRole('button', { name: '100 SMS — 150 MDL' }))
    expect(await screen.findByText(/Nota DP-7 \(150 MDL\)/)).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/settings/sms/order', { pack: 100 })
    expect((screen.getByText('Plătește cu cardul') as HTMLAnchorElement).getAttribute('href'))
      .toBe('https://cloud.dentpilot.md/plata/x')
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
