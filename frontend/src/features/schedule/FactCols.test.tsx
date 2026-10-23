import { createRef } from 'react'
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashCanvas } from './DashCanvas'
import { ago } from './FactCols'
import { fitFacts } from './dashFx'
import type { DashBlock, DashCanvasModel } from './dash'
import type { VisitFacts } from './day'

/* Карточка визита дня ОДНОГО врача — колонки фактов (22.10, вариант A
   Олега). Факты строит сервер (`routes._visit_facts`, риски сведены
   `core.risks.merge`); здесь — что канва рисует их только когда их дали, что
   рисует ровно то, что дали, и что лишнее в колонке уходит в «+N». */

const DAY = '2026-09-23'

function appt(over: Partial<Extract<DashBlock, { kind: 'appt' }>> = {})
  : Extract<DashBlock, { kind: 'appt' }> {
  return {
    kind: 'appt', id: 1, time: '09:00', min: 540, dur: 60, busy: true, movable: true,
    top: 0, height: 1, col: 0, of: 1, title: '09:00 · 60′ · Consultație · Pavel Moraru',
    name: 'Pavel Moraru', service: 'Consultație', phone: '069000000',
    status: 'confirmed', status_label: 'confirmată', urgent: false, source: 'manual',
    comment: '', comment_cut: '', age: null,
    doctor: 'Dr. Ion', pid: 17, rec: false, call: '', callable: true, clickable: true,
    service_id: 'consult', service_edit: true,
    bg: 'var(--green-soft)', bar: 'var(--green)', wait_since: null, ...over,
  }
}

const MODEL: DashCanvasModel = {
  date: DAY, empty: false, base_min: 9 * 60, tight: false,
  hours: [{ h: 9, label: '09:00', now: false }, { h: 10, label: '10:00', now: false },
    { h: 11, label: '11:00', now: false }],
  bands: { top: null, bottom: null },
  columns: [{
    key: 'k:d2', id: 'd2', name: 'Dr. Ion', orphan: false, spec: '', off: false,
    hue: 'var(--teal)', photo: '', initials: 'DI', count: 2, free: null,
    occupancy: null, title: '', cells: [true, true, true], relink: null,
    blocks: [appt(), appt({ id: 2, time: '10:30', min: 630, top: 1.5, height: 0.5,
      name: 'Ana Nouă', title: '10:30 · 30′ · Consultație · Ana Nouă' })],
  }],
}

/* Pavel: пять рисков (сервер уже свёл дубли), план с «în lucru», третий
   визит. Ana: новая, анамнез не собран, плана нет. */
const PAVEL: VisitFacts = {
  nth: 3, last: { date: '2026-08-12', what: 'Extracție 46' }, anam: true, denies: null,
  risks: [
    { tone: 'orange', icon: 'sos', text: 'Alergie: penicilină', title: 'Alergie: penicilină' },
    { tone: 'orange', icon: 'pill', text: 'Anticoagulant: Xarelto 20 mg', title: 'Anticoagulant: Xarelto 20 mg' },
    { tone: 'amber', icon: 'sos', text: 'latex', title: 'Alergii: latex' },
    { tone: 'amber', icon: 'pill', text: 'Concor 5 mg', title: 'Medicamente: Concor 5 mg' },
    { tone: 'amber', icon: '', text: 'Boli cardiovasculare', title: 'Boli cardiovasculare / hipertensiune' },
  ],
  plan: [{ tooth: 46, proc: 'Implant', work: true }, { tooth: 45, proc: 'Obturație compozit', work: false },
    { tooth: 44, proc: 'Obturație compozit', work: false }],
}
const ANA: VisitFacts = { nth: 1, last: null, anam: false, denies: null, risks: [], plan: [] }
/* Maria (23.10): анамнез собран, заявила, что ничем из списка не болеет —
   третье состояние колонки, дата опроса из данных сервера. */
const MARIA: VisitFacts = { nth: 2, last: { date: '2025-11-03', what: 'Consultație' }, anam: true,
  denies: '2025-11-03', risks: [], plan: [] }

const rail = createRef<HTMLDivElement>()
const show = (facts?: Record<string, VisitFacts>) =>
  render(<DashCanvas model={MODEL} rail={rail} waitTick={0} lineTick={0}
    onCard={vi.fn()} onSlot={vi.fn()} onNote={vi.fn()}
    drag={null} hover="" onDrag={vi.fn()} onHover={vi.fn()} onDrop={vi.fn()}
    fresh={new Set()} facts={facts} />)

const blk = (id: number) => document.querySelector(`[data-appt="${id}"]`) as HTMLElement
const colsOf = (id: number) => Array.from(blk(id).querySelectorAll<HTMLElement>('.vf-col'))
const texts = (el: Element, q: string) =>
  Array.from(el.querySelectorAll(q)).map((e) => e.textContent?.trim())

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('день врача: колонки фактов карточки (22.10, вариант A)', () => {
  it('без фактов (главная, «Toți medicii») карточка прежняя: ни колонок, ни класса', () => {
    show()
    expect(document.querySelector('.vf')).toBeNull()
    expect(blk(1).className).toBe('gappt')
  })

  it('с фактами — три колонки у визита, о котором они есть; у прочих — ничего', () => {
    show({ 1: PAVEL })
    expect(blk(1).classList.contains('has-vf')).toBe(true)
    expect(colsOf(1).map((c) => c.getAttribute('aria-label')))
      .toEqual(['Atenționări', 'Plan de tratament', 'Istoric'])
    expect(blk(2).querySelector('.vf')).toBeNull()
    expect(blk(2).classList.contains('has-vf')).toBe(false)
  })

  it('риски — ровно список сервера, по порядку: сведение без дублей — его, второго здесь нет', () => {
    show({ 1: PAVEL })
    const [risk] = colsOf(1)
    expect(texts(risk!, '.vf-chip')).toEqual(PAVEL.risks.map((r) => r.text))
    expect(Array.from(risk!.querySelectorAll('.vf-chip')).map((e) => e.className))
      .toEqual(['vf-chip orange', 'vf-chip orange', 'vf-chip amber', 'vf-chip amber', 'vf-chip amber'])
    /* подсказка называет поле анамнеза; у галочки значка нет */
    expect(risk!.querySelectorAll('.vf-chip')[2]!.getAttribute('title')).toBe('Alergii: latex')
    expect(risk!.querySelectorAll('.vf-chip')[4]!.querySelector('svg')).toBeNull()
  })

  it('план — по процедуре, номера зубов значками; «în lucru» залит', () => {
    show({ 1: PAVEL })
    const plan = colsOf(1)[1]!
    expect(texts(plan, '.vf-proc')).toEqual(['Implant', 'Obturație compozit'])
    expect(texts(plan, '.vf-tn')).toEqual(['46', '45', '44'])
    expect(Array.from(plan.querySelectorAll('.vf-tn.work')).map((e) => e.textContent)).toEqual(['46'])
  })

  it('история: какой визит и прошлый визит с давностью от ДНЯ ЭКРАНА — три строки, денег нет', () => {
    show({ 1: PAVEL })
    const hist = colsOf(1)[2]!
    /* 12.08 → 23.09: 42 дня, шесть недель — от дня экрана, не от часов */
    expect(Array.from(hist.children).filter((c) => !c.classList.contains('vf-more'))
      .map((c) => c.textContent)).toEqual(['vizita a 3-a', 'ultima 12.08 · acum 6 săpt.', 'Extracție 46'])
    /* Олег 22.10: деньги врачу на этом экране не нужны */
    expect(blk(1).querySelector('.vf')!.textContent).not.toMatch(/Datorie|Avans|MDL/)
  })

  it('новый пациент без анамнеза: «Pacient nou», серое «Anamneză necompletată»', () => {
    show({ 2: ANA })
    const [risk, plan, hist] = colsOf(2)
    expect(texts(risk!, '.vf-chip.grey')).toEqual(['Anamneză necompletată'])
    expect(texts(plan!, '.vf-muted')).toEqual(['fără plan activ'])
    expect(texts(hist!, '.vf-chip')).toEqual(['Pacient nou'])
    expect(hist!.querySelector('.vf-last')).toBeNull()
  })

  it('собранный анамнез без рисков — «fără riscuri», без серой метки', () => {
    show({ 2: { ...ANA, anam: true } })
    expect(texts(colsOf(2)[0]!, '.vf-muted')).toEqual(['fără riscuri'])
    expect(colsOf(2)[0]!.querySelector('.vf-chip')).toBeNull()
  })

  it('23.10: заявил, что здоров, рисков нет — серое «Neagă afecțiunile din chestionar» и дата опроса с годом; ни «fără riscuri», ни «necompletată»', () => {
    show({ 2: MARIA })
    const [risk] = colsOf(2)
    expect(texts(risk!, '.vf-chip.grey')).toEqual(['Neagă afecțiunile din chestionar'])
    expect(texts(risk!, '.vf-muted')).toEqual(['completat 03.11.2025'])
    expect(risk!.textContent).not.toMatch(/fără riscuri|necompletată/)
    /* подсказка несёт слово и дату целиком — в «+N» уходит она */
    expect(risk!.querySelector('.vf-chip.grey')!.getAttribute('title'))
      .toBe('Neagă afecțiunile din chestionar · completat 03.11.2025')
  })

  it('23.10: заявил, что здоров, но свободное поле дало риск — колонка показывает риски, слова «neagă» нет', () => {
    show({ 2: { ...MARIA, risks: [{ tone: 'amber', icon: 'sos', text: 'penicilină', title: 'Alergii: penicilină' }] } })
    const [risk] = colsOf(2)
    expect(texts(risk!, '.vf-chip')).toEqual(['penicilină'])
    expect(risk!.textContent).not.toMatch(/Neagă|completat/)
  })
})

describe('«+N»: не влезшее в колонку не режется, а называется числом', () => {
  /* jsdom геометрию не считает: высота колонки подставлена — 49px (блок часа
     на полу), строка 16px; не влезло то, что не спрятано `vf-cut`. */
  const stub = () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function h(this: HTMLElement) {
      if (!this.classList.contains('vf-col')) return 0
      return Array.from(this.children)
        .filter((c) => !c.classList.contains('vf-more') && !c.classList.contains('vf-cut')).length * 16
    })
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function h(this: HTMLElement) {
      return this.classList.contains('vf-col') ? 49 : 0
    })
  }

  it('пять рисков в колонке на три строки: видно три и «+2» — в строке последней видимой', () => {
    stub()
    show({ 1: PAVEL })
    const risk = colsOf(1)[0]!
    const chips = Array.from(risk.querySelectorAll('.vf-chip'))
    /* «+N» стоит в строке последней видимой, и она уступает ему место */
    expect(chips.map((c) => c.classList.contains('vf-cut'))).toEqual([false, false, false, true, true])
    expect(chips[2]!.classList.contains('vf-tail')).toBe(true)
    const more = risk.querySelector('.vf-more')!
    expect(more.className).toBe('vf-more on')
    expect(more.textContent).toBe('+2')
    /* подсказка — полный текст спрятанного, как у поля анамнеза */
    expect(more.getAttribute('title'))
      .toBe('Medicamente: Concor 5 mg\nBoli cardiovasculare / hipertensiune')
  })

  it('влезло — «+N» нет; план из двух строк не тронут', () => {
    stub()
    show({ 1: PAVEL })
    const plan = colsOf(1)[1]!
    expect(plan.querySelector('.vf-cut')).toBeNull()
    expect(plan.querySelector('.vf-more')!.className).toBe('vf-more')
  })

  it('первая строка остаётся всегда: она режется своим многоточием', () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function h(this: HTMLElement) {
      return this.classList.contains('vf-col') ? 999 : 0
    })
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function h(this: HTMLElement) {
      return this.classList.contains('vf-col') ? 10 : 0
    })
    show({ 1: PAVEL })
    const chips = Array.from(colsOf(1)[0]!.querySelectorAll('.vf-chip'))
    expect(chips[0]!.classList.contains('vf-cut')).toBe(false)
    expect(colsOf(1)[0]!.querySelector('.vf-more')!.textContent).toBe('+4')
  })

  it('перемер с нуля: на новой модели прежние «+N» и спрятанное сняты', () => {
    stub()
    show({ 1: PAVEL })
    const a = blk(1)
    vi.restoreAllMocks()
    fitFacts(a)
    expect(a.querySelector('.vf-cut')).toBeNull()
    expect(a.querySelector('.vf-more.on')).toBeNull()
  })
})

describe('давность прошлого визита словами', () => {
  it('дни, недели, месяцы, годы — с румынским числом', () => {
    expect([0, 1, 5, 13, 14, 42, 59, 60, 75, 364, 365, 800, 7400].map(ago)).toEqual([
      'azi', 'ieri', 'acum 5 zile', 'acum 13 zile', 'acum 2 săpt.', 'acum 6 săpt.',
      'acum 8 săpt.', 'acum 2 luni', 'acum 3 luni', 'acum 12 luni', 'acum un an',
      'acum 2 ani', 'acum 20 de ani'])
  })
})
