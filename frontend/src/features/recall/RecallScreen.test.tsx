import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { openScreen } from '../../test/openScreen'
import { loadRecall, RecallScreen } from './RecallScreen'
import type { RecallData, RecallRow } from './recall'

/* Экран «Rechemări» (29.10): вкладки со счётчиками, строка, пустые
   состояния (К7а/К7б), меню отметок → команда и перечитывание, окно письма
   (mailto + «Copiază» + «E-mail trimis»), фильтр по услуге. Правило списка
   — сервера; здесь только то, что рисует и шлёт экран. */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

function row(over: Partial<RecallRow> = {}): RecallRow {
  return {
    pid: 7, name: 'Maria Ceban', phone: '069 123 456', email: 'maria@example.md', lang: 'ro',
    service_id: 'hygiene', service: 'Igienizare', months: 6,
    last_at: '2026-04-02', doctor: 'Dr. Rusu', due: '2026-10-02', late_days: 4, late: 'întârziere 4 zile',
    booked: null, mark: null, tab: 'due', ...over,
  }
}

const DATA: RecallData = {
  services: [{ id: 'hygiene', ro: 'Igienizare', months: 6, since: '2026-10-01' },
    { id: 'consult', ro: 'Consultație', months: 12, since: '2026-10-01' }],
  rows: [
    row(),
    row({ pid: 8, name: 'Elena Rotari', email: '', late_days: -3, late: 'peste 3 zile',
      booked: { date: '03.11', service: 'Tratament carie' } }),
    row({ pid: 9, name: 'Victor Bodiu', service_id: 'consult', service: 'Consultație', months: 12,
      mark: { result: 'noanswer', word: 'nu răspunde', until: '', n_noanswer: 2, at: '28.10', actor: 'Ana' } }),
    row({ pid: 10, name: 'Ion Amanat', tab: 'snoozed',
      mark: { result: 'later', word: 'amânat', until: '2026-11-28', n_noanswer: 0, at: '27.10', actor: 'Ana' } }),
    row({ pid: 11, name: 'Nu Mai', tab: 'stop',
      mark: { result: 'stop', word: 'nu mai reamintim', until: '', n_noanswer: 0, at: '20.10', actor: 'Director' } }),
  ],
  counts: { due: 3, snoozed: 1, stop: 1 },
  clinic: { name: 'Clinica Test', phone: '+373 60 000 000' },
  can_settings: true,
  stats: { month: { contacted: 4, booked: 1 }, prev: { contacted: 0, booked: 0 } },
  sms: null,
}

/* Plus с кнопкой SMS (30.10): текст и сегменты — сервера; причины — кодами */
const SMS_TEXT = 'Buna ziua! Clinica Test va reaminteste ca a venit timpul pentru controlul periodic. Pentru programare: +373 60 000 000. O zi buna!'
const DATA_SMS: RecallData = {
  ...DATA,
  rows: [
    row({ sms: { can: true, why: '', text: SMS_TEXT, segments: 1 } }),
    row({ pid: 8, name: 'Elena Rotari', phone: '022 123 456', sms: { can: false, why: 'phone', text: SMS_TEXT, segments: 1 } }),
    row({ pid: 9, name: 'Victor Bodiu', sms: { can: false, why: 'sms_off', text: SMS_TEXT, segments: 1 } }),
    row({ pid: 12, name: 'Trimis Deja', tab: 'snoozed', sms: null,
      mark: { result: 'sms', word: 'SMS trimis', until: '2026-11-12', n_noanswer: 0, at: '29.10', actor: 'Ana',
        sms: { state: 'delivered', word: 'SMS livrat' } } }),
    row({ pid: 13, name: 'Nelivrat Ion', sms: null,
      mark: { result: 'sms', word: 'SMS trimis', until: '', n_noanswer: 0, at: '29.10', actor: 'Ana',
        sms: { state: 'undelivered', word: 'SMS nelivrat' } } }),
  ],
  counts: { due: 4, snoozed: 1, stop: 0 },
  sms: { on: true, balance: 42, quiet: false },
}

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/rechemari', '/admin/rechemari', <RecallScreen {...(navigate ? { navigate } : {})} />, loadRecall, navigate)
const rows = () => Array.from(document.querySelectorAll('.rc-row')) as HTMLElement[]
const names = () => rows().map((r) => r.querySelector('.rc-who b')?.textContent)

afterEach(() => { cleanup(); get.mockReset(); post.mockReset() })

describe('RecallScreen', () => {
  it('вкладки со счётчиками, строка: пациент, услуга, срок, просрочка, пометки, кнопки', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    open()
    expect(await screen.findByRole('tab', { name: /De sunat/ })).toBeTruthy()
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['De sunat 3', 'Amânate 1', 'Nu mai reaminti 1'])
    expect(names()).toEqual(['Maria Ceban', 'Elena Rotari', 'Victor Bodiu'])
    const r = rows()[0]!
    expect(r.querySelector('.rc-who a')?.getAttribute('href')).toBe('/admin/patient/7')
    expect(r.querySelector('.rc-who small')?.textContent).toBe('069 123 456 · maria@example.md')
    expect(r.querySelector('.rc-what')?.textContent).toBe('Igienizareultima 02.04.2026 · Dr. Rusu')
    expect(r.querySelector('.rc-when')?.textContent).toBe('~02.10.2026întârziere 4 zile')
    expect(r.querySelector('.rc-late')?.className).toContain('bad')
    expect(within(r).getByRole('link', { name: /Sună/ }).getAttribute('href')).toBe('tel:069 123 456')
    expect((within(r).getByRole('button', { name: /E-mail/ }) as HTMLButtonElement).disabled).toBe(false)
    /* скоро, записан на другую услугу, без e-mail */
    const e = rows()[1]!
    expect(e.querySelector('.rc-late')?.className).toContain('soon')
    expect(e.querySelector('.rc-pill.blue')?.textContent).toContain('vine pe 03.11 (Tratament carie) — spuneți atunci')
    expect((within(e).getByRole('button', { name: /E-mail/ }) as HTMLButtonElement).disabled).toBe(true)
    /* nu răspunde ×2 — тусклая строка внизу */
    const v = rows()[2]!
    expect(v.className).toContain('dim')
    expect(v.querySelector('.rc-pill.amber')?.textContent).toContain('nu răspunde ×2 · 28.10 Ana')
    expect(screen.getByText(/Servicii urmărite: Igienizare \(6 luni\) · Consultație \(12 luni\)/)).toBeTruthy()
    /* статистика одной строкой (В4 → Б): цифры сервера, прошлый месяц рядом */
    expect(document.querySelector('.rc-stats')?.textContent)
      .toBe('Luna aceasta: contactați 4 · programați 1 · luna trecută: 0 · 0')
  })

  it('вкладки «Amânate» и «Nu mai reaminti»; фильтр по услуге', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    fireEvent.click(screen.getByRole('tab', { name: /Amânate/ }))
    expect(names()).toEqual(['Ion Amanat'])
    expect(rows()[0]?.querySelector('.rc-pill.green')?.textContent).toContain('amânat · până la 28.11.2026 · 27.10 Ana')
    fireEvent.click(screen.getByRole('tab', { name: /Nu mai reaminti/ }))
    expect(names()).toEqual(['Nu Mai'])
    expect(rows()[0]?.querySelector('.rc-pill.grey')?.textContent).toContain('nu mai reamintim')
    fireEvent.click(screen.getByRole('tab', { name: /De sunat/ }))
    fireEvent.change(screen.getByLabelText('Toate serviciile'), { target: { value: 'consult' } })
    expect(names()).toEqual(['Victor Bodiu'])
  })

  it('пусто: ни у одной услуги нет срока — факт и дверь в Setări › Servicii (директор) или слово', async () => {
    get.mockResolvedValueOnce(ok({ ...DATA, services: [], rows: [], counts: { due: 0, snoozed: 0, stop: 0 } }))
    open()
    expect(await screen.findByText('Niciun serviciu nu are termen de rechemare.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Deschide Setări › Servicii' }).getAttribute('href')).toBe('/admin/settings/services')
    expect(screen.queryByRole('tab')).toBeNull()
    cleanup()
    get.mockResolvedValueOnce(ok({ ...DATA, services: [], rows: [], counts: { due: 0, snoozed: 0, stop: 0 }, can_settings: false }))
    open()
    expect(await screen.findByText('Niciun serviciu nu are termen de rechemare.')).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Deschide Setări › Servicii' })).toBeNull()
    expect(screen.getByText(/Cereți directorului/)).toBeTruthy()
  })

  it('пусто: срок есть, звонить некому — откуда берётся список; пустой журнал — строки статистики нет', async () => {
    get.mockResolvedValueOnce(ok({ ...DATA, rows: [], counts: { due: 0, snoozed: 0, stop: 0 }, stats: null }))
    open()
    expect(await screen.findByText('Nimeni de sunat acum.')).toBeTruthy()
    expect(document.querySelector('.rc-stats')).toBeNull()
    expect(screen.getByText(/Vizita a avut loc/)).toBeTruthy()
    expect(screen.getAllByRole('tab').length).toBe(3)
  })

  it('меню отметок: слова как на кадре; «Nu răspunde» шлёт команду и перечитывает список', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    const after = { ...DATA, rows: DATA.rows.map((r) => (r.pid === 7
      ? { ...r, mark: { result: 'noanswer' as const, word: 'nu răspunde', until: '', n_noanswer: 1, at: '29.10', actor: 'Director' } } : r)) }
    get.mockResolvedValueOnce(ok(after))
    post.mockResolvedValueOnce(ok(null, 'ok_recall', 'Marcaj salvat'))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    fireEvent.click(within(rows()[0]!).getByRole('button', { name: /Marchează/ }))
    const menu = screen.getByRole('menu')
    expect(within(menu).getAllByRole('menuitem').map((b) => b.textContent))
      .toEqual([' Sunat — revineascunde 14 zile', ' Nu răspunderămâne în listă', ' Nu mai reamintipentru igienizare'])
    expect(within(menu).getByLabelText('Amânat până la')).toBeTruthy()
    expect(within(menu).queryByRole('menuitem', { name: /Anulează marcajul/ })).toBeNull()
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Nu răspunde/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/recall/mark', { pid: 7, service_id: 'hygiene', result: 'noanswer' }))
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Marcaj salvat')).toBeTruthy()
    await waitFor(() => expect(rows()[0]?.querySelector('.rc-pill.amber')?.textContent).toContain('nu răspunde · 29.10 Director'))
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('«Amânat până la» шлёт дату; у строки с отметкой есть «Anulează marcajul»', async () => {
    get.mockResolvedValue(ok(DATA))
    post.mockResolvedValue(ok(null, 'ok_recall', 'Marcaj salvat'))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    fireEvent.click(within(rows()[0]!).getByRole('button', { name: /Marchează/ }))
    fireEvent.change(screen.getByLabelText('Amânat până la'), { target: { value: '2026-11-28' } })
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/recall/mark', { pid: 7, service_id: 'hygiene', result: 'later', until: '2026-11-28' }))
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
    fireEvent.click(within(rows()[2]!).getByRole('button', { name: /Marchează/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /Anulează marcajul/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/recall/mark', { pid: 9, service_id: 'consult', result: 'clear' }))
  })

  it('отказ отметки — слово сервера в плашке, список не перечитывается', async () => {
    get.mockResolvedValue(ok(DATA))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'recall_gone', text: 'Pacientul nu mai este în lista de rechemări — reîmprospătați pagina' }, 'c'))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    fireEvent.click(within(rows()[0]!).getByRole('button', { name: /Marchează/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /Sunat — revine/ }))
    expect(await screen.findByText(/Pacientul nu mai este în lista/)).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('окно письма: кому, тема, текст, mailto с кодировкой, «Copiază», «E-mail trimis» ставит отметку', async () => {
    get.mockResolvedValue(ok(DATA))
    post.mockResolvedValue(ok(null, 'ok_recall', 'Marcaj salvat'))
    const write = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    fireEvent.click(within(rows()[0]!).getByRole('button', { name: /E-mail/ }))
    const dlg = document.querySelector('dialog.rc-mail') as HTMLDialogElement
    expect(dlg.textContent).toContain('Maria Ceban <maria@example.md>')
    expect(dlg.textContent).toContain('Control periodic — Clinica Test')
    expect(dlg.querySelector('.rc-mail-t')?.textContent).toContain('Bună ziua, Maria.')
    expect(dlg.textContent).toContain('DentPilot nu trimite nimic prin internet')
    const href = within(dlg).getByRole('link', { name: /Deschide în programul de e-mail/ }).getAttribute('href') ?? ''
    expect(href.startsWith('mailto:maria%40example.md?subject=Control%20periodic')).toBe(true)
    expect(href).toContain('&body=Bun%C4%83%20ziua%2C%20Maria.%0A%0A')
    fireEvent.click(within(dlg).getByRole('button', { name: /Copiază adresa/ }))
    expect(write).toHaveBeenCalledWith('maria@example.md')
    fireEvent.click(within(dlg).getByRole('button', { name: /Copiază textul/ }))
    expect((write.mock.calls[1] as unknown as string[])[0]).toContain('Control periodic — Clinica Test\n\nBună ziua, Maria.')
    fireEvent.click(within(dlg).getByRole('button', { name: /Am trimis/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/recall/mark', { pid: 7, service_id: 'hygiene', result: 'emailed' }))
  })

  it('Basic (sms null): ни кнопки, ни слова SMS в строках', async () => {
    get.mockResolvedValueOnce(ok(DATA))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    expect(screen.queryByRole('button', { name: /^SMS$/ })).toBeNull()
    expect(document.querySelector('dialog.rc-sms')).toBeNull()
  })

  it('Plus: кнопка SMS по данным строки — можно / не мобильный / отказался; окно с текстом и остатком; POST и перечитывание', async () => {
    get.mockResolvedValue(ok(DATA_SMS))
    post.mockResolvedValue(ok({ state: 'sent', balance: 41 }, 'ok_recall_sms', 'SMS trimis'))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    const btn = (i: number) => within(rows()[i]!).getByRole('button', { name: /^SMS$/ }) as HTMLButtonElement
    expect(btn(0).disabled).toBe(false)
    expect(btn(1).disabled).toBe(true)
    expect(btn(1).title).toBe('numărul nu este un mobil din Moldova')
    expect(btn(2).disabled).toBe(true)
    expect(btn(2).title).toBe('pacientul a refuzat memento-urile SMS')
    /* SMS этого цикла уже ушла — кнопки нет, пилюля со словом доставки; недоставленная — янтарная */
    expect(within(rows()[3]!).queryByRole('button', { name: /^SMS$/ })).toBeNull()
    expect(rows()[3]!.querySelector('.rc-pill.amber')?.textContent).toContain('SMS nelivrat')
    fireEvent.click(btn(0))
    const dlg = document.querySelector('dialog.rc-sms') as HTMLDialogElement
    expect(dlg.textContent).toContain('Maria Ceban')
    expect(dlg.querySelector('.rc-mail-t')?.textContent).toBe(SMS_TEXT)
    expect(dlg.textContent).toContain('1 SMS · rămân 41 în pachet')
    fireEvent.click(within(dlg).getByRole('button', { name: /Trimite SMS/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/recall/sms', { pid: 7, service_id: 'hygiene' }))
    expect(await screen.findByText('SMS trimis')).toBeTruthy()
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
  })

  it('тихие часы: кнопка выключена с подсказкой; «Amânate» показывает доставленную SMS', async () => {
    get.mockResolvedValue(ok({ ...DATA_SMS, sms: { on: true, balance: 42, quiet: true } }))
    open()
    await screen.findByRole('tab', { name: /De sunat/ })
    const b = within(rows()[0]!).getByRole('button', { name: /^SMS$/ }) as HTMLButtonElement
    expect(b.disabled).toBe(true)
    expect(b.title).toBe('SMS-urile se trimit între 08:00 și 21:00')
    fireEvent.click(screen.getByRole('tab', { name: /Amânate/ }))
    expect(rows()[0]!.querySelector('.rc-pill.green')?.textContent).toContain('SMS livrat')
    expect(rows()[0]!.textContent).toContain('până la 12.11.2026')
  })

  it('отказ загрузки — «Reîncearcă»', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    get.mockResolvedValueOnce(ok(DATA))
    open()
    fireEvent.click(await screen.findByRole('button', { name: /Reîncearcă/ }))
    expect(await screen.findByRole('tab', { name: /De sunat/ })).toBeTruthy()
  })
})
