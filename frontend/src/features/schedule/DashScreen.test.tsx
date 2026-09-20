import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
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

/** Тело POST из записанного вызова `fetch`. ⚠️ Мок объявлен ОДНИМ параметром
 *  (адрес), поэтому второй достаётся приведением: описывать весь `fetch`
 *  ради одной строки дороже, чем эта скобка. */
function bodyOf(call: unknown): Record<string, unknown> {
  return JSON.parse(String((call as [string, RequestInit])[1].body))
}

/** Ответ КОМАНДЫ живой поверхности: код и слово, и НИ БАЙТА состояния. */
function cmdReply(code: string, text: string, status = 200): Response {
  return new Response(
    JSON.stringify({ ok: status === 200, code, text, tone: status === 200 ? 'ok' : 'err' }),
    { status, headers: { 'content-type': 'application/json' } })
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

  it('⛔ подсказка обещает ровно то, что экран умеет, и ни строкой больше', async () => {
    /* ⚠️ Она правится ВМЕСТЕ с каждым шагом C26.5.3: карточка появилась —
       про неё сказано; записи по клику и переноса ещё нет — про них сказано,
       что они в старой панели. Подсказка, обещающая несделанное, — это
       обещание, которое видит регистратура. */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await show()
    const hint = document.querySelector('.dashmain .hint')!
    expect(hint.textContent).toContain('Click pe o programare')
    expect(hint.textContent).toContain('varianta clasică')
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

describe('C26.5.3-b: диалог визита', () => {
  const openFirst = async () => {
    await show()
    fireEvent.click(document.querySelector('[data-appt="1"]') as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  it('карточка открывается и по блоку канвы, и по строке повестки', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await openFirst()
    expect(document.querySelector('dialog .dlg-head span')?.textContent)
      .toContain('Ion Popa')

    fireEvent.click(document.querySelector('dialog [aria-label]') as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeNull())

    fireEvent.click(document.querySelector('.ag-i') as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  })

  it('ссылки показываются по pid/rec, а НЕ по clickable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await openFirst()
    const links = Array.from(document.querySelectorAll('dialog .dp-card-link'))
      .map((a) => a.getAttribute('href'))
    expect(links).toEqual(['/admin/patient/17', `/admin/visit/1?back=${encodeURIComponent(`/admin?date=${TODAY}`)}`])
  })

  it('⛔ у записи БЕЗ пациента ссылок нет вовсе', async () => {
    /* ⚠️ Эта ветка не исполняется на демо-профиле: там у всех записей есть
       пациент. Легаси-строка без него — реальность клиники, пережившей
       переезд, и ссылка вела бы на `/admin/patient/null`. */
    const m = model()
    const blk = m.canvas.columns[0]!.blocks[0]!
    if (blk.kind === 'appt') { blk.pid = null; blk.rec = false }
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, m)))
    await openFirst()
    expect(document.querySelectorAll('dialog .dp-card-link').length).toBe(0)
    /* но сама карточка открыта и комментарий править можно */
    expect(document.querySelector('dialog textarea')).toBeTruthy()
  })

  it('⭐ грязный черновик переживает конверт, а КАНВА под ним обновляется', async () => {
    /* Главное отличие от легаси: там открытое окно замораживало страницу
       целиком, и рабочее место переставало узнавать о бронях, оставаясь
       живым НА ВИД. Здесь черновик держит СЕБЯ, а не экран. */
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await openFirst()
    const area = document.querySelector('dialog textarea') as HTMLTextAreaElement
    fireEvent.change(area, { target: { value: 'de sunat inainte' } })

    const second = model()
    const b2 = second.canvas.columns[0]!.blocks[0]!
    if (b2.kind === 'appt') b2.comment = 'правка со второго места'
    second.canvas.columns[0]!.blocks.push({
      kind: 'appt', id: 2, time: '10:00', min: 600, dur: 60, busy: true, movable: true,
      top: 1, height: 1, col: 0, of: 1, title: '10:00', name: 'Maria Rusu',
      service: 'Consultație', phone: '069000001', status: 'confirmed',
      status_label: 'confirmată', urgent: false, source: 'bot', comment: '',
      comment_cut: '', age: null, doctor: 'Dr. Ion', pid: 18, rec: false,
      clickable: true, bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null,
    })
    f.mockImplementation(async () => reply(200, second, { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() =>
      expect(document.querySelectorAll('.gridbody [data-appt]').length).toBe(2))
    expect((document.querySelector('dialog textarea') as HTMLTextAreaElement).value)
      .toBe('de sunat inainte')
  })

  it('чистый черновик ПЕРЕСЕВАЕТСЯ приехавшим значением', async () => {
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await openFirst()

    const second = model()
    const b2 = second.canvas.columns[0]!.blocks[0]!
    if (b2.kind === 'appt') b2.comment = 'правка со второго места'
    f.mockImplementation(async () => reply(200, second, { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() =>
      expect((document.querySelector('dialog textarea') as HTMLTextAreaElement).value)
        .toBe('правка со второго места'))
  })

  it('⛔ запись исчезла — НАДГРОБИЕ: словом, и все кнопки исхода убраны', async () => {
    /* Молча размонтировать нельзя: человек решит, что промахнулся мимо
       кнопки. Врать «она есть» тоже нельзя. */
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await openFirst()
    expect(document.querySelectorAll('dialog .dlg-status button').length)
      .toBeGreaterThan(0)

    const empty = model()
    empty.canvas.columns[0]!.blocks = []
    f.mockImplementation(async () => reply(200, empty, { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() =>
      expect(document.querySelector('dialog .banner.err')?.textContent)
        .toBe('Programarea nu mai există.'))
    expect(document.querySelectorAll('dialog .dlg-status button').length).toBe(0)
    /* и то, что человек ОТКРЫВАЛ, на экране осталось */
    expect(document.querySelector('dialog .dlg-head span')?.textContent)
      .toContain('Ion Popa')
  })

  it('⭐ команда не приносит состояния: экран берёт его у КАНАЛА', async () => {
    const f = vi.fn(async (url: string) => (String(url).includes('/comment')
      /* ответ действия БЕЗ `data` — так отвечает `screen=panel` */
      ? new Response(JSON.stringify({ ok: true, code: 'ok_comment', text: 'Salvat', tone: 'ok' }),
        { status: 200, headers: { 'content-type': 'application/json' } })
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openFirst()
    const before = f.mock.calls.length

    fireEvent.change(document.querySelector('dialog textarea') as HTMLTextAreaElement,
      { target: { value: 'nou' } })
    fireEvent.submit(document.querySelector('dialog form') as HTMLFormElement)

    await waitFor(() => expect(f.mock.calls.length).toBeGreaterThan(before + 1))
    const urls = f.mock.calls.map((c) => String(c[0]))
    /* команда ушла с пометкой поверхности... */
    expect(urls.some((u) => u.includes('/comment?screen=panel'))).toBe(true)
    /* ...и сразу за ней экран спросил КАНАЛ — второй двери к состоянию нет */
    expect(urls[urls.length - 1]).toContain('/schedule/live')
  })
})

describe('C26.5.3-c: диалог пустого часа', () => {
  const fill = (name: string, phone: string) => {
    fireEvent.change(document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLElement,
      { target: { value: name } })
    fireEvent.change(document.querySelector('dialog input[placeholder="Telefon"]') as HTMLElement,
      { target: { value: phone } })
  }

  const openSlot = async (h = 10) => {
    await show()
    fireEvent.click(document.querySelector(`.gcell[data-h="${h}"]`) as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  it('открывается на СВОЕЙ ячейке: врач колонки и её час', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await openSlot()
    expect(document.querySelector('dialog .dlg-head span')?.textContent)
      .toBe('Dr. Ion — 10:00')
    expect(document.querySelectorAll('.halfpick .hp')[0]?.className).toContain('on')
    /* услуги и потолок «даты рождения» — ИЗ КОНВЕРТА, второго запроса нет */
    expect(Array.from(document.querySelectorAll('dialog select option'))
      .map((o) => o.textContent)).toEqual(['Consultație'])
    expect(document.querySelector('dialog input[type="date"]')?.getAttribute('max'))
      .toBe(TODAY)
  })

  it('⛔ получас меняет ТОЛЬКО время записи: концы блокировки остаются часовыми', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, model())))
    await openSlot()
    const ends = () => {
      fireEvent.click(document.querySelectorAll('.tabbtn')[1] as HTMLElement)
      const sel = document.querySelector('dialog select') as HTMLSelectElement
      return Array.from(sel.options).map((o) => o.value)
    }
    /* ⚠️ Концы приезжают конвертом (`note_ends`) и режутся началом часа: у
       10:00 это 11 и 12, а 10 — уже не конец, а начало. */
    expect(ends()).toEqual(['11', '12'])

    fireEvent.click(document.querySelectorAll('.tabbtn')[0] as HTMLElement)
    fireEvent.click(document.querySelectorAll('.halfpick .hp')[1] as HTMLElement)
    expect(document.querySelector('dialog .dlg-head span')?.textContent)
      .toBe('Dr. Ion — 10:30')
    expect(ends()).toEqual(['11', '12'])
  })

  it('⭐ набранное переживает конверт, а КАНВА под ним обновляется', async () => {
    /* То же, что у карточки, и по той же причине: открытый диалог не имеет
       права замораживать живой экран. Здесь это даётся построением — поля
       заводятся при монтировании, пересевать их нечему. */
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await openSlot()
    const name = document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLInputElement
    fireEvent.change(name, { target: { value: 'Ana Munteanu' } })

    const second = model()
    second.canvas.columns[0]!.blocks.push({
      kind: 'appt', id: 2, time: '10:00', min: 600, dur: 60, busy: true, movable: true,
      top: 1, height: 1, col: 0, of: 1, title: '10:00', name: 'Maria Rusu',
      service: 'Consultație', phone: '069000001', status: 'confirmed',
      status_label: 'confirmată', urgent: false, source: 'bot', comment: '',
      comment_cut: '', age: null, doctor: 'Dr. Ion', pid: 18, rec: false,
      clickable: true, bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null,
    })
    f.mockImplementation(async () => reply(200, second, { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() =>
      expect(document.querySelectorAll('.gridbody [data-appt]').length).toBe(2))
    expect((document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLInputElement)
      .value).toBe('Ana Munteanu')
  })

  it('⭐ команда уходит с пометкой поверхности, а состояние берётся у КАНАЛА', async () => {
    const f = vi.fn(async (url: string) => (String(url).includes('/schedule/appointments')
      ? cmdReply('ok', 'Programare adăugată')
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openSlot()
    fill('Ana Munteanu', '069111222')
    fireEvent.submit(document.querySelector('dialog .dlg-form') as HTMLFormElement)

    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeNull())
    const urls = f.mock.calls.map((c) => String(c[0]))
    expect(urls.some((u) => u.includes(`/schedule/appointments?screen=panel&date=${TODAY}`)))
      .toBe(true)
    /* ...и сразу за командой экран спросил КАНАЛ: второй двери к состоянию нет */
    expect(urls[urls.length - 1]).toContain('/schedule/live')
  })

  it('⛔ `nophone` — намерение ИЗ ФОРМЫ, а не «телефон пустой» (08-16)', async () => {
    /* Пустой номер БЕЗ галочки остаётся отказом `bad_phone` — это правило
       сервера. Если бы клиент выводил намерение из пустоты поля, тот же ввод
       давал бы разный результат в зависимости от того, что в поле осталось. */
    const f = vi.fn(async (url: string) => (String(url).includes('/schedule/appointments')
      ? cmdReply('ok', 'Programare adăugată')
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openSlot()
    fill('Ana Munteanu', '069111222')
    fireEvent.click(document.querySelector('dialog .nophone input') as HTMLElement)
    fireEvent.submit(document.querySelector('dialog .dlg-form') as HTMLFormElement)

    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeNull())
    const body = bodyOf(f.mock.calls.find(
      (c) => String(c[0]).includes('/schedule/appointments')))
    expect([body.nophone, body.phone, body.time]).toEqual([true, '', '10:00'])
  })

  it('⛔ на 409 диалог НЕ закрывается, набранное на месте, и канал всё равно спрошен', async () => {
    /* 409 значит «каноническое состояние уже изменилось под тобой», а отказ
       приходит БЕЗ данных: не спроси экран канал — человек прочтёт «интервал
       занят» и будет смотреть на пустую ячейку. */
    const f = vi.fn(async (url: string) => (String(url).includes('/schedule/appointments')
      ? cmdReply('conflict', 'Intervalul este deja ocupat la acest medic', 409)
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openSlot()
    fill('Ana Munteanu', '069111222')
    const before = f.mock.calls.length
    fireEvent.submit(document.querySelector('dialog .dlg-form') as HTMLFormElement)

    await waitFor(() => expect(f.mock.calls.length).toBeGreaterThan(before + 1))
    expect(document.querySelector('dialog[open]')).toBeTruthy()
    expect((document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLInputElement)
      .value).toBe('Ana Munteanu')
    expect(document.querySelector('.toastbox')?.textContent)
      .toContain('Intervalul este deja ocupat')
    expect(String(f.mock.calls[f.mock.calls.length - 1]![0])).toContain('/schedule/live')
  })

  it('⛔ кнопка ЗАПЕРТА, пока команда в полёте: второй клик — второй ответ', async () => {
    let release: () => void = () => {}
    const held = new Promise<void>((r) => { release = r })
    const f = vi.fn(async (url: string) => {
      if (String(url).includes('/schedule/appointments')) {
        await held
        return cmdReply('ok', 'Programare adăugată')
      }
      return reply(200, model())
    })
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openSlot()
    fill('Ana Munteanu', '069111222')
    const btn = document.querySelector('dialog .dlg-form > button') as HTMLButtonElement
    expect(btn.disabled).toBe(false)
    fireEvent.submit(document.querySelector('dialog .dlg-form') as HTMLFormElement)

    await waitFor(() => expect(
      (document.querySelector('dialog .dlg-form > button') as HTMLButtonElement).disabled)
      .toBe(true))
    release()
    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeNull())
  })

  it('заметка из вкладки уходит ГОЛЫМ часом и своим концом', async () => {
    /* Получас двигает только время записи: сервер берёт час как
       `int(ntime.split(":")[0])` и молча округлил бы получас вниз. */
    const f = vi.fn(async (url: string) => (String(url).includes('/schedule/notes')
      ? cmdReply('ok_note', 'Notiță adăugată — ora este blocată')
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openSlot()
    fireEvent.click(document.querySelectorAll('.halfpick .hp')[1] as HTMLElement)
    fireEvent.click(document.querySelectorAll('.tabbtn')[1] as HTMLElement)
    fireEvent.change(document.querySelector('dialog .dlg-form input') as HTMLElement,
      { target: { value: 'Pauză de masă' } })
    fireEvent.submit(document.querySelector('dialog .dlg-form') as HTMLFormElement)

    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeNull())
    const call = f.mock.calls.find((c) => String(c[0]).includes('/schedule/notes'))!
    expect(String(call[0])).toContain('screen=panel')
    expect(bodyOf(call))
      .toEqual({ date: TODAY, time: '10:00', doctor: 'd2', text: 'Pauză de masă', until: 11 })
  })
})

describe('C26.5.3-d: диалог заметки стойки', () => {
  /* ⚠️ Текст ровно такой длины, как его хранит база (120), и блок покажет из
     него 40: проверка про ПОЛНЫЙ текст ничего не стоит, если обрезок и полное
     значение совпадают. */
  const TEXT = `Pauză de masă și ședință cu tot personalul ${'9'.repeat(78)}`
  const NOTE = {
    kind: 'note' as const, id: 7, time: '10:00', min: 600, dur: 60, busy: true,
    movable: true, top: 1, height: 1, col: 0, of: 1, status: 'confirmed',
    title: TEXT.slice(0, 80), text: TEXT, label: TEXT.slice(0, 40),
  }
  const withNote = () => {
    const m = model()
    m.canvas.columns[0]!.blocks.push({ ...NOTE })
    return m
  }
  const openNote = async () => {
    await show()
    fireEvent.click(document.querySelector('[data-appt="7"]') as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  it('⭐ показывает ПОЛНЫЙ текст — тот, что на панели не виден больше нигде', async () => {
    /* В блоке 40 знаков, в подсказке 80, в базе 120. До этого шага длинную
       заметку на /admin было не прочитать вовсе, ни одним способом. */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, withNote())))
    await openNote()
    expect(document.querySelector('dialog .dp-note-text')?.textContent).toBe(TEXT)
    expect(document.querySelector('[data-appt="7"] b')?.textContent)
      .toContain(TEXT.slice(0, 40))
    expect(document.querySelector('[data-appt="7"] b')?.textContent)
      .not.toContain(TEXT.slice(0, 41))
  })

  it('⛔ у заметки РОВНО ОДНА кнопка, и слово у неё серверное', async () => {
    /* Матрица заметки знает два состояния из шести: прихода и исхода у неё
       нет, есть «убрать» и «вернуть». Своего списка в браузере нет. */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, withNote())))
    await openNote()
    const buttons = Array.from(document.querySelectorAll('dialog .dlg-status button'))
    expect(buttons.map((b) => b.textContent)).toEqual(['Șterge'])
  })

  it('⛔ текст заметки НЕ правится: поля ввода в диалоге нет вовсе', async () => {
    /* Маршрута для правки не существует — текст пишется один раз при вставке,
       и ни один UPDATE appointments не трогает колонку service. Поле ввода
       было бы обещанием, которого сервер не выполнит. */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, withNote())))
    await openNote()
    expect(document.querySelectorAll('dialog textarea').length).toBe(0)
    expect(document.querySelectorAll('dialog input').length).toBe(0)
    /* и это НЕ карточка визита: ни фиши, ни дневника у заметки не бывает */
    expect(document.querySelectorAll('dialog .dp-card-link').length).toBe(0)
  })

  it('⛔ убрали со второго рабочего места — НАДГРОБИЕ, и кнопок больше нет', async () => {
    const f = vi.fn(async () => reply(200, withNote()))
    vi.stubGlobal('fetch', f)
    await openNote()
    expect(document.querySelectorAll('dialog .dlg-status button').length).toBe(1)

    f.mockImplementation(async () => reply(200, model(), { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() =>
      expect(document.querySelector('dialog .banner.err')?.textContent)
        .toBe('Notița nu mai există.'))
    expect(document.querySelectorAll('dialog .dlg-status button').length).toBe(0)
    /* и то, что человек ОТКРЫВАЛ, на экране осталось */
    expect(document.querySelector('dialog .dp-note-text')?.textContent).toBe(TEXT)
  })

  it('⭐ «Șterge» шлёт `to` СЕРВЕРА тем же маршрутом статуса — и без вопроса', async () => {
    /* ⚠️ Это не удаление: заметка переводится в `cancelled`, строка остаётся.
       ⚠️ Вопрос подтверждения СЕРВЕРНЫЙ и по классу: «Șterge» не спрашивает
       ничего, спрашивает «Restabilește». Полярность обратная ожидаемой — и
       чинить её по дороге в React нельзя. */
    const ask = vi.spyOn(window, 'confirm')
    const f = vi.fn(async (url: string) => (String(url).includes('/status')
      /* ⚠️ У снятия блокировки нет кода сообщения вовсе: пустая строка
         числится успехом, и плашки после него не будет ни на одном экране. */
      ? cmdReply('', '')
      : reply(200, withNote())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await openNote()
    fireEvent.submit(document.querySelector('dialog .dlg-status form') as HTMLFormElement)

    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeNull())
    const call = f.mock.calls.find((c) => String(c[0]).includes('/status'))!
    expect(String(call[0]))
      .toBe(`/api/schedule/appointments/7/status?screen=panel&date=${TODAY}`)
    expect(bodyOf(call)).toEqual({ to: 'cancelled' })
    expect(ask).not.toHaveBeenCalled()
    expect(String(f.mock.calls[f.mock.calls.length - 1]![0])).toContain('/schedule/live')
    ask.mockRestore()
  })
})

describe('C26.5.3-f: перенос перетаскиванием', () => {
  /** ⛔ Не `fireEvent.drop(el, {clientY})`: в jsdom нет `DragEvent`, и
   *  testing-library молча откатывается на `window.Event`, который про
   *  `clientY` не знает — координата пришла бы нулём, а мишень пустой. */
  const dragTo = (el: Element, type: 'dragover' | 'drop', clientY: number) =>
    fireEvent(el, new MouseEvent(type, { bubbles: true, cancelable: true, clientY }))

  /* jsdom геометрию не считает: ряды по 40 пикселей со сотого, 9-й 100–140,
     10-й 140–180. */
  const stubRects = () => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
      function rect(this: Element) {
        const h = (this as HTMLElement).dataset?.h
        const i = h === undefined ? -1 : [9, 10].indexOf(Number(h))
        const top = i < 0 ? 0 : 100 + i * 40
        return { top, height: i < 0 ? 0 : 40, bottom: top + 40, left: 0, right: 0,
          width: 0, x: 0, y: top, toJSON: () => ({}) } as DOMRect
      })
  }

  const withTwo = () => {
    const m = model()
    m.canvas.columns[0]!.blocks.push({
      kind: 'appt', id: 2, time: '10:00', min: 600, dur: 60, busy: true, movable: true,
      top: 1, height: 1, col: 0, of: 1, title: '10:00', name: 'Maria Rusu',
      service: 'Consultație', phone: '069000001', status: 'confirmed',
      status_label: 'confirmată', urgent: false, source: 'manual', comment: '',
      comment_cut: '', age: null, doctor: 'Dr. Ion', pid: 18, rec: false,
      clickable: true, bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null,
    })
    return m
  }

  /** Взять блок 1 и бросить в колонку на координату `y`. */
  const dropAt = async (y: number) => {
    stubRects()
    fireEvent.dragStart(document.querySelector('[data-appt="1"]') as HTMLElement)
    dragTo(document.querySelector('.gridbody .gcol') as HTMLElement, 'drop', y)
  }

  it('⭐ перенос уходит командой, а состояние приезжает КАНАЛОМ', async () => {
    const f = vi.fn(async (url: string) => (String(url).includes('/move')
      ? cmdReply('ok_move', 'Programare mutată')
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await show()
    await dropAt(165)                       // низ ряда 10:00 → 10:30

    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
    expect(document.querySelector('dialog .mv-rows')?.textContent)
      .toContain('Dr. Ion · 10:30')
    fireEvent.click(document.querySelectorAll('dialog .mv-act button')[1] as HTMLElement)

    await waitFor(() => expect(
      f.mock.calls.some((c) => String(c[0]).includes('/move'))).toBe(true))
    const call = f.mock.calls.find((c) => String(c[0]).includes('/move'))!
    expect(String(call[0]))
      .toBe(`/api/schedule/appointments/1/move?screen=panel&date=${TODAY}`)
    expect(bodyOf(call)).toEqual({ date: TODAY, time: '10:30', doctor: 'd2' })
    expect(String(f.mock.calls[f.mock.calls.length - 1]![0])).toContain('/schedule/live')
  })

  it('⛔ бросок на СВОЁ ЖЕ место — не перенос: ни диалога, ни запроса', async () => {
    /* Сервер такой запрос ПРИНИМАЕТ и пишет строку в летопись пациента, а
       летопись не переписывают. Правило браузерное, и обойтись без него
       нельзя. */
    const f = vi.fn(async () => reply(200, model()))
    vi.stubGlobal('fetch', f)
    await show()
    await dropAt(105)                       // верх ряда 09:00 — откуда и взяли

    expect(document.querySelector('dialog')).toBeNull()
    expect(f.mock.calls.some(
      (c) => String((c as unknown as [string])[0]).includes('/move'))).toBe(false)
  })

  it('занятый час — подсказка в диалоге, и подтвердить нельзя', async () => {
    /* ⚠️ Это ПОДСКАЗКА: правду говорит сервер под `_BOOK_LOCK`. Но кнопка
       заперта — иначе регистратура отправляла бы заведомый отказ. */
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, withTwo())))
    await show()
    await dropAt(145)                       // верх ряда 10:00, где стоит визит 2

    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
    expect(document.querySelector('dialog .banner.err')?.textContent)
      .toContain('10:00')
    expect((document.querySelectorAll('dialog .mv-act button')[1] as HTMLButtonElement)
      .disabled).toBe(true)
  })

  it('⛔ отказ сервера — блок остаётся на месте, и это состояние КАНАЛА', async () => {
    /* React не двигает блок сам: он ушёл командой и вернётся конвертом. На
       отказе двигать нечего — и именно поэтому экран не «откатывает». */
    const f = vi.fn(async (url: string) => (String(url).includes('/move')
      ? cmdReply('conflict', 'Intervalul este deja ocupat la acest medic', 409)
      : reply(200, model())))
    vi.stubGlobal('fetch', f as unknown as typeof fetch)
    await show()
    await dropAt(165)

    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
    fireEvent.click(document.querySelectorAll('dialog .mv-act button')[1] as HTMLElement)

    await waitFor(() => expect(document.querySelector('.toastbox')?.textContent)
      .toContain('Intervalul este deja ocupat'))
    /* блок там же, где был: локального мира расписания у React нет */
    expect(document.querySelector('[data-appt="1"] small')?.textContent)
      .toContain('09:00')
    expect(String(f.mock.calls[f.mock.calls.length - 1]![0])).toContain('/schedule/live')
  })
})
