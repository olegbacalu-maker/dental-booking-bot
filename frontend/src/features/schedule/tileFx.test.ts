import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { allowMotion } from '../../test/motion'
import { attachTileFx, cascadeIn, near, settleTile } from './tileFx'

/* Отклик блоков визита на курсор и перенос. jsdom не знает ни геометрии, ни
   Web Animations: прямоугольники и `animate` подставляются здесь, движение
   включается `allowMotion()` — без него модуль обязан молчать. Живой вид (подъём
   без дрожи, копия под курсором) держит стенд `motion_check`. */

interface Run { el: Element; frames: Keyframe[]; opts: KeyframeAnimationOptions; end: () => void; cancel: ReturnType<typeof vi.fn> }
let runs: Run[] = []

function stubAnimate() {
  ;(Element.prototype as { animate?: unknown }).animate = function animate(
    this: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
    let end!: () => void
    const finished = new Promise<void>((r) => { end = r })
    const run: Run = { el: this, frames, opts, end, cancel: vi.fn() }
    runs.push(run)
    return { id: opts.id, finished, cancel: run.cancel }
  }
}

function rect(el: Element, top: number, height = 60, left = 100, width = 200) {
  el.getBoundingClientRect = () => ({ top, height, bottom: top + height, left, width, right: left + width,
    x: left, y: top, toJSON: () => ({}) }) as DOMRect
}

/** Канва: колонка с двумя блоками визита (зуб и слой эффектов) и заметкой. */
function canvas() {
  document.body.innerHTML = `
    <div class="gridcard-host"><div class="gridcard"><div class="gridbody">
      <div class="gcol" data-lanes="2">
        <button class="gcell" data-h="9"></button>
        <div class="gappt" data-appt="1" title="Ion"><b>Ion</b><a class="apact"><svg></svg></a><i class="gfx"><i></i></i></div>
        <div class="gappt" data-appt="2"><b>Maria</b><a class="apact"><svg></svg></a><i class="gfx"><i></i></i></div>
        <div class="gappt gnote" data-appt="3"><b>Notă</b></div>
      </div>
    </div></div></div>`
  const body = document.querySelector<HTMLElement>('.gridbody')!
  const [a, b, note] = Array.from(body.querySelectorAll<HTMLElement>('.gappt'))
  rect(a!, 100)
  rect(b!, 166)
  rect(note!, 232)
  rect(body.querySelector('.gcol')!, 0, 600, 100, 200)
  return { body, a: a!, b: b!, note: note!, cell: body.querySelector<HTMLElement>('.gcell')! }
}

const ptr = (el: Element, type: string, x: number, y: number, related: Element | null = null, extra: object = {}) => {
  const e = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, relatedTarget: related })
  Object.assign(e, extra)
  el.dispatchEvent(e)
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
const of = (prop: string) => runs.filter((r) => prop in (r.frames[0] ?? {}))

beforeEach(() => { runs = [] })
afterEach(() => {
  delete (Element.prototype as { animate?: unknown }).animate
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('near: курсор над блоком или в полоске под ним', () => {
  it('полоска — только снизу', () => {
    const r = { left: 100, right: 300, top: 100, bottom: 160 }
    expect(near(r, 200, 130)).toBe(true)
    expect(near(r, 200, 163)).toBe(true)
    expect(near(r, 200, 165)).toBe(false)
    expect(near(r, 200, 99)).toBe(false)
    expect(near(r, 99, 130)).toBe(false)
    expect(near(r, 200, 163, 0)).toBe(false)
  })
})

describe('наведение — пометкой data-hov', () => {
  it('⛔ курсор ушёл в полоску под поднятым блоком — пометка держится; дальше — снята', () => {
    const { body, a, cell } = canvas()
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130)
    expect(a.hasAttribute('data-hov')).toBe(true)
    /* блок поднялся, курсор оказался под его кромкой — над часом */
    ptr(a, 'pointerout', 200, 162, cell)
    expect(a.hasAttribute('data-hov')).toBe(true)
    ptr(cell, 'pointermove', 200, 163)
    expect(a.hasAttribute('data-hov')).toBe(true)
    ptr(cell, 'pointermove', 200, 166)
    expect(a.hasAttribute('data-hov')).toBe(false)
  })

  it('ушёл вверх — снята сразу; перешёл на соседний блок — пометка у соседа, одна', () => {
    const { body, a, b, cell } = canvas()
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130)
    ptr(a, 'pointerout', 200, 98, cell)
    expect(a.hasAttribute('data-hov')).toBe(false)
    ptr(a, 'pointerover', 200, 130)
    ptr(a, 'pointerout', 200, 162, cell)
    ptr(b, 'pointerover', 200, 170, cell)
    expect(body.querySelectorAll('[data-hov]')).toHaveLength(1)
    expect(b.hasAttribute('data-hov')).toBe(true)
  })

  it('курсор ушёл с канвы — пометки нет; касание пометку не ставит; снятие слушателей убирает пометку', () => {
    const { body, a } = canvas()
    const off = attachTileFx(body)
    ptr(a, 'pointerover', 200, 130)
    body.dispatchEvent(new MouseEvent('pointerleave'))
    expect(a.hasAttribute('data-hov')).toBe(false)
    ptr(a, 'pointerover', 200, 130, null, { pointerType: 'touch' })
    expect(a.hasAttribute('data-hov')).toBe(false)
    ptr(a, 'pointerover', 200, 130)
    off()
    expect(a.hasAttribute('data-hov')).toBe(false)
    ptr(a, 'pointerover', 200, 130)
    expect(a.hasAttribute('data-hov')).toBe(false)
  })
})

describe('оборот зубчика и блик — один раз за наведение', () => {
  it('⛔ курсор ходит внутри блока — повтора нет; доиграло, ушёл и вернулся — играет снова', async () => {
    allowMotion()
    stubAnimate()
    const { body, a, cell } = canvas()
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130, cell)
    expect(of('rotate')).toHaveLength(1)
    expect(of('rotate')[0]!.el).toBe(a.querySelector('svg'))
    expect(of('translate')).toHaveLength(1)
    expect(of('translate')[0]!.el).toBe(a.querySelector('.gfx > i'))
    /* с имени на зуб и обратно — тот же блок */
    ptr(a.querySelector('b')!, 'pointerover', 210, 130, a.querySelector('svg'))
    /* вышел посреди анимации и вернулся — она ещё играет */
    ptr(a, 'pointerout', 200, 98, cell)
    ptr(a, 'pointerover', 200, 130, cell)
    expect(runs).toHaveLength(2)
    /* доиграло при курсоре над блоком: до ухода — тишина */
    runs.forEach((r) => r.end())
    await tick()
    ptr(a.querySelector('b')!, 'pointerover', 210, 130, a.querySelector('svg'))
    expect(runs).toHaveLength(2)
    ptr(a, 'pointerout', 200, 98, cell)
    ptr(a, 'pointerover', 200, 130, cell)
    expect(runs).toHaveLength(4)
  })

  it('доиграло, когда курсор уже ушёл, — следующее наведение играет сразу', async () => {
    allowMotion()
    stubAnimate()
    const { body, a, cell } = canvas()
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130, cell)
    ptr(a, 'pointerout', 200, 400, cell)
    runs.forEach((r) => r.end())
    await tick()
    ptr(a, 'pointerover', 200, 130, cell)
    expect(runs).toHaveLength(4)
  })

  it('в узком блоке зуба нет — играет один блик; у заметки не играет ничего', () => {
    allowMotion()
    stubAnimate()
    const { body, a, note, cell } = canvas()
    a.querySelector<HTMLElement>('.apact')!.style.display = 'none'
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130, cell)
    expect(of('rotate')).toHaveLength(0)
    expect(of('translate')).toHaveLength(1)
    ptr(note, 'pointerover', 200, 250, cell)
    expect(runs).toHaveLength(1)
    expect(note.hasAttribute('data-hov')).toBe(true)
  })

  it('⛔ без движения не играет ничего (пометка наведения стоит — её вид гасит CSS)', () => {
    stubAnimate()
    const { body, a, cell } = canvas()
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130, cell)
    expect(runs).toHaveLength(0)
    expect(a.hasAttribute('data-hov')).toBe(true)
  })
})

describe('перенос', () => {
  function drag(el: Element, x = 180, y = 120) {
    const setDragImage = vi.fn()
    const e = new MouseEvent('dragstart', { bubbles: true, clientX: x, clientY: y })
    Object.defineProperty(e, 'dataTransfer', { value: { setDragImage } })
    el.dispatchEvent(e)
    return setDragImage
  }

  it('⛔ в миг хвата канва помечена (блок встаёт на место), свои анимации блока сняты, наведение снято', () => {
    allowMotion()
    stubAnimate()
    const { body, a, cell } = canvas()
    attachTileFx(body)
    ptr(a, 'pointerover', 200, 130, cell)
    const mine = { id: 'tile', cancel: vi.fn() }
    const flip = { id: '', cancel: vi.fn() }
    ;(a as unknown as { getAnimations: () => unknown[] }).getAnimations = () => [mine, flip]
    drag(a)
    expect(body.hasAttribute('data-dragging')).toBe(true)
    expect(a.hasAttribute('data-hov')).toBe(false)
    expect(mine.cancel).toHaveBeenCalledTimes(1)
    /* сдвиг переезда — не свой: его перенос не трогает */
    expect(flip.cancel).not.toHaveBeenCalled()
  })

  it('под курсор отдана копия блока в копии колонки, курсор держит её за ту же точку; источник помечен', () => {
    allowMotion()
    const { body, a } = canvas()
    attachTileFx(body)
    const setDragImage = drag(a, 180, 120)
    expect(setDragImage).toHaveBeenCalledTimes(1)
    const [img, x, y] = setDragImage.mock.calls[0] as [HTMLElement, number, number]
    expect(img.className).toBe('gdragimg')
    const lane = img.firstElementChild as HTMLElement
    expect(lane.className).toBe('gcol')
    expect(lane.getAttribute('data-lanes')).toBe('2')
    expect(lane.style.width).toBe('200px')
    const copy = lane.firstElementChild as HTMLElement
    expect(copy.classList.contains('gappt')).toBe(true)
    expect(copy.textContent).toBe('Ion')
    /* копия — не блок канвы: ни номера записи, ни подсказки, ни своего переноса */
    expect(copy.hasAttribute('data-appt')).toBe(false)
    expect(copy.hasAttribute('title')).toBe(false)
    expect(copy.style.height).toBe('60px')
    /* колонка начинается со 100 px, блок — со 100 px: точка хвата (180, 120) плюс поле копии */
    expect([x, y]).toEqual([30 + 80, 30 + 20])
    /* копия стоит под корнем экрана, рядом с канвой, и вне самой канвы */
    expect(img.parentElement?.className).toBe('gridcard-host')
    expect(a.hasAttribute('data-src')).toBe(true)
    expect(body.querySelectorAll('[data-appt="1"]')).toHaveLength(1)
  })

  it('конец переноса (бросок, отмена, блок сняли посреди броска) — пометки сняты', () => {
    allowMotion()
    const { body, a, cell } = canvas()
    attachTileFx(body)
    for (const end of ['dragend', 'drop']) {
      drag(a)
      a.dispatchEvent(new MouseEvent(end, { bubbles: true }))
      expect(body.hasAttribute('data-dragging')).toBe(false)
      expect(a.hasAttribute('data-src')).toBe(false)
    }
    drag(a)
    /* `dragend` не пришёл: первое движение мыши без кнопки снимает пометку */
    ptr(cell, 'pointermove', 200, 50)
    expect(body.hasAttribute('data-dragging')).toBe(false)
    expect(a.hasAttribute('data-src')).toBe(false)
  })

  it('без движения копии и пометки источника нет, а блок на место встаёт всё равно', () => {
    const { body, a } = canvas()
    attachTileFx(body)
    const setDragImage = drag(a)
    expect(setDragImage).not.toHaveBeenCalled()
    expect(a.hasAttribute('data-src')).toBe(false)
    expect(body.hasAttribute('data-dragging')).toBe(true)
  })

  it('наведение во время переноса не ставится', () => {
    allowMotion()
    const { body, a, b } = canvas()
    attachTileFx(body)
    drag(a)
    ptr(b, 'pointerover', 200, 170)
    expect(b.hasAttribute('data-hov')).toBe(false)
  })
})

describe('очередь появления и осадка', () => {
  it('блоки дня проявляются сверху вниз, каждый следующий — позже; очередь не длиннее потолка', () => {
    allowMotion()
    stubAnimate()
    const { body, a, b, note } = canvas()
    Object.defineProperty(a, 'offsetTop', { value: 200 })
    Object.defineProperty(b, 'offsetTop', { value: 20 })
    Object.defineProperty(note, 'offsetTop', { value: 90 })
    cascadeIn(body)
    expect(runs.map((r) => r.el)).toEqual([b, note, a])
    expect(runs.map((r) => r.opts.delay)).toEqual([0, 22, 44])
    expect(runs.every((r) => r.opts.fill === 'backwards' && r.frames[0]!.opacity === 0)).toBe(true)
    runs = []
    for (let i = 0; i < 40; i++) body.querySelector('.gcol')!.appendChild(a.cloneNode(true))
    cascadeIn(body)
    expect(Math.max(...runs.map((r) => Number(r.opts.delay)))).toBe(500)
  })

  it('переехавший блок «садится» после сдвига: только масштаб, с задержкой на сдвиг', () => {
    allowMotion()
    stubAnimate()
    const { a } = canvas()
    settleTile(a)
    expect(runs).toHaveLength(1)
    expect(Object.keys(runs[0]!.frames[0]!)).toEqual(['scale'])
    expect(Number(runs[0]!.opts.delay)).toBeGreaterThan(100)
  })

  it('⛔ без движения нет ни очереди, ни осадки', () => {
    stubAnimate()
    const { body, a } = canvas()
    cascadeIn(body)
    settleTile(a)
    expect(runs).toHaveLength(0)
  })
})
