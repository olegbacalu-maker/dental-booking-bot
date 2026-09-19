import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DashScreen } from './DashScreen'
import { clinicNow } from './dashFx'
import type { DashModel } from './dash'

/* Панель дня целиком: ОДИН конверт кормит пять блоков, и экран живой.
   Фикстуры ТОЛЬКО этих проверок. */

const NOW = new Date(2026, 8, 19, 11, 30).getTime()
const TODAY = clinicNow('', new Date(NOW)).day
const SERIES = [0, 1, 2, 3, 2, 4, 5, 3, 2, 6, 4, 3, 7, 5]

function model(over: Partial<DashModel> = {}): DashModel {
  return {
    screen: 'panel', date: TODAY, live: true,
    canvas: {
      date: TODAY, empty: false, base_min: 540, tight: false,
      hours: [{ h: 9, label: '09:00', now: false }, { h: 10, label: '10:00', now: true }],
      bands: { top: null, bottom: null },
      columns: [{
        key: 'k:d2', id: 'd2', name: 'Dr. Ion', orphan: false, spec: 'Terapeut',
        off: false, hue: 'var(--teal)', photo: '', initials: 'DI', room: '', phone: '',
        count: 1, free: '10:00', occupancy: { busy: 60, cap: 480, pct: 13 },
        title: 'Dr. Ion', cells: [true, true], relink: null,
        blocks: [{
          kind: 'appt', id: 1, time: '09:00', min: 540, dur: 60, busy: true, movable: true,
          top: 0, height: 1, col: 0, of: 1, title: '09:00 · 60′ · Consultație · Ion Popa',
          name: 'Ion Popa', service: 'Consultație', phone: '069000000',
          status: 'confirmed', status_label: 'confirmată', urgent: false, source: 'manual',
          comment: '', comment_cut: '', age: null,
          doctor: 'Dr. Ion', pid: 17, rec: false, clickable: true,
          bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null,
        }],
      }],
    },
    agenda: {
      count: 1, today: true,
      items: [{
        id: 1, time: '09:00', dur: 60, name: 'Ion Popa', service: 'Consultație',
        status: 'confirmed', badge: { cls: 'act', label: 'Confirmată' }, urgent: false,
        bar: 'var(--green)', state: 'future', clickable: true, patient_id: 17,
        wait_since: null,
      }],
    },
    tiles: [{
      key: 'total', label: 'Programări', value: 1, icon: 'cal',
      soft: 'var(--green-soft)', tone: 'var(--green)', filter: '',
      href: `/admin/all?date=${TODAY}`, cls: '',
      sub: { kind: 'same', diff: 0, dir: null, text: 'la fel ca ieri' }, series: SERIES,
    }],
    occupancy: {
      label: 'Grad de ocupare', icon: 'trend', soft: 'var(--violet-soft)',
      tone: 'var(--violet)', value: 13, series: SERIES,
      from: { label: 'ieri', value: '10%' }, to: { label: 'azi', value: '13%' }, dir: 'up',
    },
    actions: { confirmed: [{ to: 'waiting', cls: 'b-wait', label: 'A venit', confirm: '' }] },
    note_actions: { confirmed: [{ to: 'cancelled', cls: 'b-cancel', label: 'Șterge', confirm: '' }] },
    note_ends: [10, 11, 12],
    slotform: { services: [{ id: 'consult', label: 'Consultație' }], birth_max: TODAY },
    minical: {
      title: 'Septembrie 2026', weekdays: ['Lu', 'Ma', 'Mi', 'Jo', 'Vi', 'Sâ', 'Du'],
      weeks: [[
        { date: TODAY, day: 19, other: false, today: true, selected: true,
          href: `/admin?date=${TODAY}` },
      ]],
      prev: { date: '2026-08-01', href: '/admin?date=2026-08-01' },
      next: { date: '2026-10-01', href: '/admin?date=2026-10-01' },
    },
    ...over,
  }
}

function reply(status: number, data: unknown, head: Record<string, string> = {}): Response {
  const headers: Record<string, string> = {
    'X-DP-V': '1.27.0', 'X-DP-Surface': 'react', 'X-DP-Hash': 'h1', ...head,
  }
  if (data !== null) headers['content-type'] = 'application/json'
  return new Response(
    data === null ? null : JSON.stringify({ ok: true, code: '', text: '', tone: 'ok', data }),
    { status, headers })
}

beforeEach(() => {
  document.body.dataset.v = '1.27.0'
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const show = async () => {
  render(<DashScreen date={TODAY} />)
  await waitFor(() => expect(document.querySelector('.gridbody')).toBeTruthy())
}

describe('C26.5.2: панель дня — экран целиком', () => {
  it('ОДИН конверт кормит все четыре блока сразу', async () => {
    /* ⛔ Панель включается целиком, а не по блоку: половина экрана на новых
       данных и половина на старых — это два разных дня рядом (слово Олега
       19.09). */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await show()

    expect(document.querySelectorAll('.gridbody .gcol').length).toBe(1)
    expect(document.querySelector('.mcal b')?.textContent).toBe('Septembrie 2026')
    expect(document.querySelector('.ag-h span')?.textContent).toBe('1 programări')
    expect(document.querySelector('.rk-i .rk-l')?.textContent).toBe('Programări')
    expect(document.querySelector('.rk-occ .rk-l')?.textContent).toBe('Grad de ocupare')
  })

  it('спрашивает СВОЙ адрес канала и шлёт отпечаток со второго запроса', async () => {
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await show()

    expect((f.mock.calls[0] as unknown as [string])[0])
      .toBe(`/api/schedule/live?screen=panel&date=${TODAY}`)
    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() => expect(f.mock.calls.length).toBeGreaterThan(1))
    expect((f.mock.calls[1] as unknown as [string, RequestInit])[1].headers)
      .toEqual({ 'X-DP-Hash': 'h1' })
  })

  it('⭐ живой: запись, добавленная ДРУГИМ рабочим местом, приезжает сама', async () => {
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await show()
    expect(document.querySelectorAll('.gridbody [data-appt]').length).toBe(1)

    const second = model()
    second.canvas.columns[0]!.blocks.push({
      kind: 'appt', id: 2, time: '10:00', min: 600, dur: 60, busy: true, movable: true,
      top: 1, height: 1, col: 0, of: 1, title: '10:00 · 60′ · Consultație · Maria Rusu',
      name: 'Maria Rusu', service: 'Consultație', phone: '069000001',
      status: 'confirmed', status_label: 'confirmată', urgent: false, source: 'bot',
      comment: '', comment_cut: '', age: null,
      doctor: 'Dr. Ion', pid: 18, rec: false, clickable: true,
      bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null,
    })
    second.agenda = { count: 2, today: true, items: [...model().agenda.items] }
    f.mockImplementation(async () => reply(200, second, { 'X-DP-Hash': 'h2' }))

    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() =>
      expect(document.querySelectorAll('.gridbody [data-appt]').length).toBe(2))
    expect(document.querySelector('[data-appt="2"] b')?.textContent).toContain('Maria Rusu')
    /* ⛔ Соседний блок при этом не поехал: геометрия у него прежняя. */
    expect((document.querySelector('[data-appt="1"]') as HTMLElement).style.top)
      .toBe((document.querySelector('[data-appt="2"]') as HTMLElement).style.top
        .replace('1', '0'))
  })

  it('204 «не менялось» не трогает экран вовсе', async () => {
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await show()
    const before = document.querySelector('.dash')!.innerHTML

    f.mockImplementation(async () => reply(204, null))
    await vi.advanceTimersByTimeAsync(12_000 * 3)

    expect(document.querySelector('.dash')!.innerHTML).toBe(before)
  })

  it('⛔ подсказка говорит ПРАВДУ: экран читающий, действия — в старой панели', async () => {
    /* Печатать подсказку старой страницы («click — детали, тащите — перенос»)
       значило бы обещать то, чего экран не умеет: диалоги это C26.5.3. */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await show()
    const hint = document.querySelector('.dashmain .hint')!
    expect(hint.textContent).toContain('doar pentru citit')
    expect(hint.querySelector('a')?.getAttribute('href')).toBe(`/admin?date=${TODAY}&ui=legacy`)
  })

  it('⛔ класс anim снимается на ПЕРВОМ ОБНОВЛЕНИИ, и снять его больше некому', async () => {
    /* Ставит его каркас всякой странице, а снимал единственный — `apply()`
       живого опроса panel.js, который на React-странице не запускается. Без
       этого `.anim .ag-i` и `.anim .spark` переигрывали бы вход на каждом
       новом узле вечно, а сцена браузера этого не увидела бы: анимация CSS
       мутацией DOM не является. */
    document.documentElement.classList.add('anim')
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await show()
    /* первая отрисовка анимируется — как серверная у старой страницы */
    expect(document.documentElement.classList.contains('anim')).toBe(true)

    const second = model()
    second.agenda = { count: 2, today: true, items: [...model().agenda.items] }
    f.mockImplementation(async () => reply(200, second, { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() =>
      expect(document.documentElement.classList.contains('anim')).toBe(false))
  })

  it('движок молчит на первой загрузке → отказ с повтором, а не пустой экран', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    render(<DashScreen date={TODAY} />)
    await waitFor(() => expect(document.querySelector('.banner.err')).toBeTruthy())
    expect(document.querySelector('.savebtn')).toBeTruthy()
  })
})
