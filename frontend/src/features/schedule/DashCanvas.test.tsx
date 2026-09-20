import { createRef } from 'react'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashCanvas } from './DashCanvas'
import { clinicNow } from './dashFx'
import type { DashBlock, DashCanvasModel, DashColumn } from './dash'

/* Канва панели дня. Фикстуры ТОЛЬКО этих проверок: бандл их не видит.
   ⛔ День собран из всего, обо что канва спотыкается: колонка-сирота,
   кластер пересечений, заметка стойки, ожидающий пациент, перебронированный
   врач, срезанные края и закрытый час в середине. */

const NOW = new Date(2026, 8, 19, 11, 30).getTime()
const TODAY = clinicNow('', new Date(NOW)).day

const LONG_NOTE = 'Livrare materiale pentru cabinetul doi: freze, anestezic, manusi'

function appt(over: Partial<Extract<DashBlock, { kind: 'appt' }>> = {})
  : Extract<DashBlock, { kind: 'appt' }> {
  return {
    kind: 'appt', id: 1, time: '09:00', min: 540, dur: 60, busy: true, movable: true,
    top: 0, height: 1, col: 0, of: 1, title: '09:00 · 60′ · Consultație · Ion Popa',
    name: 'Ion Popa', service: 'Consultație', phone: '069000000',
    status: 'confirmed', status_label: 'confirmată', urgent: false, source: 'manual',
    comment: '', comment_cut: '', age: null,
    doctor: 'Dr. Ion', pid: 17, rec: false, clickable: true,
    bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null, ...over,
  }
}

function column(over: Partial<DashColumn> = {}): DashColumn {
  return {
    key: 'k:d2', id: 'd2', name: 'Dr. Ion', orphan: false, spec: 'Terapeut',
    off: false, hue: 'var(--teal)', photo: '', initials: 'DI',
    room: '12', phone: '069111111', count: 2, free: '11:00',
    occupancy: { busy: 240, cap: 480, pct: 50 }, title: 'Dr. Ion · 12 · 069111111',
    cells: [true, true, false, true], blocks: [], relink: null, ...over,
  }
}

const ORPHAN: DashColumn = {
  key: 'n:Dr. Vechi', id: null, name: 'Dr. Vechi', orphan: true, spec: '',
  off: true, hue: '#94A3B8', photo: '', initials: 'DV',
  count: 1, free: null, occupancy: null, title: '',
  cells: [false, false, false, false],
  blocks: [appt({ id: 9, time: '10:00', top: 1, height: 1, name: 'Pacient Pierdut' })],
  relink: { name: 'Dr. Vechi', options: [{ id: 'd2', name: 'Dr. Ion' }, { id: 'd3', name: 'Dr. Ana' }] },
}

const MODEL: DashCanvasModel = {
  date: TODAY, empty: false, base_min: 9 * 60, tight: false,
  hours: [
    { h: 9, label: '09:00', now: false },
    { h: 10, label: '10:00', now: false },
    { h: 11, label: '11:00', now: true },
    { h: 12, label: '12:00', now: false },
  ],
  bands: { top: { from: '07:00', to: '09:00' }, bottom: { from: '13:00', to: '19:00' } },
  columns: [
    column({
      blocks: [
        /* кластер: две пересекающиеся записи делят ширину */
        appt({ id: 1, col: 0, of: 2 }),
        appt({
          id: 2, col: 1, of: 2, time: '09:30', top: 0.5, height: 0.5,
          status: 'waiting', status_label: 'a venit', name: 'Maria Rusu',
          wait_since: NOW - 20 * 60_000,
        }),
        appt({
          id: 3, time: '11:00', top: 2, height: 1, urgent: true,
          service: 'Durere acută', name: 'Vasile Lupu',
        }),
        {
          kind: 'note', id: 4, time: '12:00', min: 720, dur: 60, busy: true,
          status: 'confirmed',
          movable: false, top: 3, height: 1, col: 0, of: 1,
          title: LONG_NOTE, text: `${LONG_NOTE} si doua truse`, label: LONG_NOTE.slice(0, 40),
        },
      ],
    }),
    column({
      key: 'k:d3', id: 'd3', name: 'Dr. Ana', spec: '', off: true, count: 5,
      free: null, occupancy: { busy: 624, cap: 480, pct: 130 },
      cells: [true, true, true, true], blocks: [],
    }),
    ORPHAN,
  ],
}

const rail = createRef<HTMLDivElement>()
const show = (model: DashCanvasModel = MODEL) =>
  render(<DashCanvas model={model} rail={rail} waitTick={NOW} lineTick={NOW}
    onCard={onCard} onSlot={onSlot} onNote={onNote} />)

const cols = () => Array.from(document.querySelectorAll('.gridbody > .gcol'))
const cards = () => Array.from(document.querySelectorAll('.gridhead .gh-doc'))

const onCard = vi.fn()
const onSlot = vi.fn()
const onNote = vi.fn()

afterEach(() => {
  cleanup()
  onCard.mockClear()
  onSlot.mockClear()
  onNote.mockClear()
})

describe('C26.5.2: канва панели — колонки, часы и геометрия', () => {
  it('ряды часов и метка ТЕКУЩЕГО часа приходят с сервера', () => {
    /* ⚠️ Подсветка часа серверная намеренно: она меняется раз в час, и её
       смена — честное изменение состояния. Непрерывное (линия) — браузерное. */
    show()
    const time = Array.from(document.querySelectorAll('.gcol-time > div'))
    expect(time.map((d) => d.textContent)).toEqual(['09:00', '10:00', '11:00', '12:00'])
    expect(time.filter((d) => d.className === 'nowh').map((d) => d.textContent))
      .toEqual(['11:00'])
  })

  it('⛔ закрытая ячейка НЕ несёт data-h: куда нельзя записать, туда нельзя и перенести', () => {
    show()
    const cells = Array.from(cols()[0]!.querySelectorAll('.gcell'))
    expect(cells.map((c) => c.className)).toEqual(['gcell', 'gcell', 'gcell off', 'gcell'])
    expect(cells.map((c) => c.getAttribute('data-h'))).toEqual(['9', '10', null, '12'])
  })

  it('C26.5.3-c: открытая ячейка отдаёт врача и СВОЙ час, «HH:00»', () => {
    show()
    const cells = Array.from(cols()[0]!.querySelectorAll('.gcell'))
    fireEvent.click(cells[1] as HTMLElement)
    expect(onSlot).toHaveBeenCalledWith('d2', 'Dr. Ion', '10:00')
  })

  it('⛔ C26.5.3-c: закрытая ячейка молчит — признак ОДИН на вид и на нажатие', () => {
    /* Доступность действия выражает сам DOM: нет `data-h` — нет и мишени.
       Второго признака «кликабельна» не заводится: он разошёлся бы с первым, и
       ячейка выглядела бы открытой, ничего при этом не открывая. */
    show()
    const cells = Array.from(cols()[0]!.querySelectorAll('.gcell'))
    fireEvent.click(cells[2] as HTMLElement)
    expect(onSlot).not.toHaveBeenCalled()
  })

  it('геометрия блока — множители модели, а пиксель часа остаётся за CSS', () => {
    /* ⚠️ Сравнивается СМЫСЛ, а не строка: jsdom нормализует `calc()`
       («calc(1*(100% - 8px)/2 + 4px)» → «calc(4px + 0.5 * (100% - 8px))»),
       и проверка на точный текст ломалась бы от чужого нормализатора. */
    show()
    const col = cols()[0]!
    const b1 = col.querySelector('[data-appt="1"]') as HTMLElement
    const b2 = col.querySelector('[data-appt="2"]') as HTMLElement
    const solo = col.querySelector('[data-appt="3"]') as HTMLElement

    expect(b2.style.top).toContain('var(--cell)')
    expect(b2.style.top).toContain('0.5')
    expect(b2.style.height).toContain('var(--cell)')
    /* кластер делит ширину: две из двух стоят рядом и уже одиночной */
    expect(b1.style.left).not.toBe(b2.style.left)
    expect(b1.style.width).toBe(b2.style.width)
    expect(solo.style.width).not.toBe(b1.style.width)
  })

  it('срезанные края — полоски СНАРУЖИ сетки, с часами в подсказке', () => {
    /* ⛔ Внутри `.gridbody` полоска сдвинула бы начало координат, от которого
       блоки считают `top`. */
    show()
    const bands = Array.from(document.querySelectorAll('.gband'))
    expect(bands.map((b) => b.className))
      .toEqual(['gband gb-top', 'gband gb-bot'])
    expect(bands[0]!.getAttribute('title')).toBe('Închis · 07:00 - 09:00')
    expect(document.querySelector('.gridbody .gband')).toBeNull()
  })

  it('пустой день говорит словом, а не пустой сеткой', () => {
    show({ ...MODEL, empty: true, hours: [], columns: [], bands: { top: null, bottom: null } })
    expect(document.querySelector('.dp-freeday')?.textContent)
      .toBe('Zi liberă — clinica este închisă')
    expect(document.querySelector('.gridbody')).toBeNull()
  })

  it('больше четырёх колонок — шапка ужимается', () => {
    show()
    expect(document.querySelector('.gridhead')?.className).toBe('gridhead')
    cleanup()
    show({ ...MODEL, tight: true })
    expect(document.querySelector('.gridhead')?.className).toBe('gridhead tight')
  })
})

describe('C26.5.2: канва панели — шапка врача', () => {
  it('счётчик, ближайший свободный час и точка состояния', () => {
    show()
    const first = cards()[0]!
    expect(first.querySelector('.mt')?.textContent).toBe('2 prog. · liber 11:00')
    expect((first.querySelector('.st') as HTMLElement).style.background).toBe('var(--green)')
    expect(first.querySelector('.st')?.getAttribute('title')).toBe('liber 11:00')
  })

  it('полный день говорит «complet», и точка гаснет', () => {
    show()
    const full = cards()[1]!
    expect(full.querySelector('.mt')?.textContent).toBe('5 prog. · complet')
    expect((full.querySelector('.st') as HTMLElement).style.background).toBe('var(--text3)')
  })

  it('⛔ перебронированный день показывает 130%, а сотней обрезана только ПОЛОСА', () => {
    /* Это единственный признак, по которому директор увидит перебронирование:
       обрежь само число — и день на 130% станет неотличим от ровно полного. */
    show()
    const occ = cards()[1]!.querySelector('.occ')!
    expect(occ.querySelector('b')?.textContent).toBe('130%')
    expect((occ.querySelector('.statbar > div') as HTMLElement).style.width).toBe('100%')
    expect(occ.getAttribute('title')).toBe('624 din 480 minute de lucru')
  })

  it('выключенный врач помечен, и его карточка приглушена', () => {
    show()
    expect(cards()[0]!.querySelector('.dcard')?.className).toBe('dcard')
    expect(cards()[1]!.querySelector('.dcard')?.className).toBe('dcard off')
  })
})

describe('C26.5.2: колонка-сирота — единственный вход в relink', () => {
  it('её визит ВИДЕН, и это главное: иначе час выглядел бы свободным', () => {
    /* ⛔ Канва — единственное место в программе, где видны записи врача,
       которого больше нет в справочнике. Собери панель по модели дня — он
       слился бы в колонку живого врача и исчез. */
    show()
    const orphan = cols()[2]!
    expect(orphan.querySelector('[data-appt="9"]')).toBeTruthy()
    expect(orphan.querySelector('[data-appt="9"] b')?.textContent).toContain('Pacient Pierdut')
  })

  it('в неё нельзя записать: ни data-dk у колонки, ни data-h у ячеек', () => {
    show()
    const orphan = cols()[2]!
    expect(orphan.getAttribute('data-dk')).toBeNull()
    expect(Array.from(orphan.querySelectorAll('.gcell')).map((c) => c.className))
      .toEqual(['gcell off', 'gcell off', 'gcell off', 'gcell off'])
  })

  it('⛔ и её ячейка не открывает диалог: мишень — это ПАРА «врач + час»', () => {
    /* Врача с таким именем в справочнике нет, и отправлять запись было бы
       некому: сервер отвечает такому ключу отказом. Здесь этого просто не
       случается — слота без врача не бывает. */
    show()
    fireEvent.click(cols()[2]!.querySelector('.gcell') as HTMLElement)
    expect(onSlot).not.toHaveBeenCalled()
  })

  it('форма переприкрепления — обычная, с 303, и несёт возврат на панель', () => {
    /* ⛔ Не fetch: маршрут живёт под HTML-охраной и отвечает редиректом —
       fetch принёс бы форму входа как «успех». */
    show()
    const form = cards()[2]!.querySelector('form') as HTMLFormElement
    expect(form.getAttribute('action')).toBe('/admin/relink')
    expect(form.getAttribute('method')).toBe('post')
    expect((form.querySelector('[name="old_name"]') as HTMLInputElement).value).toBe('Dr. Vechi')
    expect((form.querySelector('[name="back"]') as HTMLInputElement).value)
      .toBe(`/admin?date=${TODAY}`)
    expect(Array.from(form.querySelectorAll('option')).map((o) => o.textContent))
      .toEqual(['Dr. Ion', 'Dr. Ana'])
  })

  it('и она подписана «в afara listei» со счётчиком', () => {
    show()
    expect(cards()[2]!.querySelector('small')?.textContent).toBe('în afara listei · 1 prog.')
    expect(cards()[2]!.querySelector('.st')).toBeNull()
    expect(cards()[2]!.querySelector('a')?.getAttribute('href')).toBeNull()
  })
})

describe('C26.5.2: блок записи', () => {
  it('слово статуса печатается только у НЕ подтверждённого', () => {
    show()
    const col = cols()[0]!
    expect(col.querySelector('[data-appt="1"] .stw')).toBeNull()
    expect(col.querySelector('[data-appt="2"] .stat')?.textContent).toBe('a venit')
    expect(col.querySelector('[data-appt="2"] .stat')?.className).toBe('stat s-waiting')
  })

  it('минуты ожидания считает БРАУЗЕР по отметке сервера', () => {
    /* ⛔ Серверная строка с минутами меняла бы отпечаток живого состояния
       каждую минуту, и подмена шла бы на каждый опрос — мигание чёрным ходом. */
    show()
    const wait = cols()[0]!.querySelector('[data-appt="2"] .wait-min')
    expect(wait?.textContent).toBe('așteaptă 20 min')
    expect(wait?.className).toBe('wait-min long')
  })

  it('C26.5.3-d: нажатие по заметке ведёт в ЕЁ диалог, а не в карточку визита', () => {
    /* ⛔ И не в диалог пустого часа: блок лежит ПОВЕРХ ячейки, у которой свой
       обработчик, но ячейка ему сосед, а не родитель — «записать в этот час»
       поверх уже заблокированного часа человек не нажимал. */
    show()
    fireEvent.click(cols()[0]!.querySelector('[data-appt="4"]') as HTMLElement)
    expect(onNote).toHaveBeenCalledWith(4)
    expect(onCard).not.toHaveBeenCalled()
    expect(onSlot).not.toHaveBeenCalled()
  })

  it('заметка стойки — своим видом и ОБРЕЗКОМ, а полный текст остаётся в данных', () => {
    show()
    const note = cols()[0]!.querySelector('[data-appt="4"]')!
    expect(note.className).toBe('gappt gnote')
    const shown = note.querySelector('b')?.textContent ?? ''
    expect(shown).toContain(LONG_NOTE.slice(0, 40))
    expect(shown).not.toContain(LONG_NOTE.slice(0, 41))
    expect(note.getAttribute('title')).toBe(LONG_NOTE)
  })

  it('неявка помечена классом, а срочный подтверждённый — своим значком', () => {
    show()
    const col = cols()[0]!
    expect(col.querySelector('[data-appt="3"] .stt')).toBeTruthy()
    cleanup()
    show({
      ...MODEL,
      columns: [column({ blocks: [appt({ id: 7, status: 'noshow', status_label: 'nu a venit' })] })],
    })
    expect(document.querySelector('[data-appt="7"]')?.className).toBe('gappt noshow')
  })
})

describe('C26.5.2: линия «сейчас»', () => {
  it('стоит на своём часе и ТОЛЬКО на сегодняшнем дне', () => {
    show()
    const line = document.querySelector('.nowline') as HTMLElement
    expect(line).toBeTruthy()
    /* 11:30 при рядах 9,10,11,12 — третий ряд плюс половина */
    expect(line.style.top).toBe('calc(2.5*var(--cell))')

    cleanup()
    show({ ...MODEL, date: '2026-01-05' })
    expect(document.querySelector('.nowline')).toBeNull()
  })

  it('⛔ её в модели НЕТ, и высота часа не уезжает в состояние', () => {
    /* Множитель считает код, пиксель — CSS: ровно то же разделение, что у
       блоков. Отсюда и `calc(... * var(--cell))` вместо числа в пикселях. */
    show()
    expect((document.querySelector('.nowline') as HTMLElement).style.top)
      .toContain('var(--cell)')
    /* пиксель живёт в CSS-переменной, которую поставил замер, а не в дереве */
    const gb = document.querySelector('.gridbody') as HTMLElement
    expect(gb.style.getPropertyValue('--cell')).toMatch(/^\d+px$/)
  })
})
