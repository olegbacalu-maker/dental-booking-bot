/**
 * Отклик блоков визита на курсор и перенос — канва панели дня и «Programări».
 *
 * Что живёт, пока курсор над блоком (подъём, полоска, нажатие), и что играет
 * на событие статуса — чистый CSS (panel.css › «блок визита отвечает…»). Здесь
 * то, чего CSS не умеет:
 * - наведение пометкой `data-hov` вместо `:hover` — поднятый блок иначе дрожит
 *   у своей нижней кромки;
 * - оборот зубчика и блик один раз за наведение, доигрывающие до конца, —
 *   анимация на `:hover` обрывалась бы, едва курсор ушёл;
 * - перенос: блок обязан стоять ровно на своём месте в миг хвата, под курсор
 *   отдаётся наклонённая копия;
 * - появление блоков дня по очереди и осадка блока после переезда.
 *
 * Движение — только когда его разрешила система (`motionOk`): без него блок
 * ведёт себя как прежде. Размеры блока не трогаются нигде — их читает перемер
 * ступеней сжатия.
 */
import { useEffect, useLayoutEffect, type RefObject } from 'react'
import { hookPrint } from '../../utils/flip'
import { motionOk, stepMs } from '../../utils/motion'

/** Метка своих анимаций: перед переносом гасятся только они, сдвиг переезда цел. */
const TAG = 'tile'

const TOOTH_MS = 600
const SHEEN_MS = 700
const SETTLE_MS = 300
const CASCADE_MS = 260
/** Шаг очереди появления и её потолок: день в сорок записей не ждёт секунду. */
const CASCADE_STEP = 22
const CASCADE_CAP = 500
/** Полоска под поднятым блоком, в которой наведение ещё держится, px. */
const SKIRT = 4
/** Поле вокруг копии блока в картинке переноса: наклон и тень не обрезаются. */
const PAD = 30

const SPIN = 'cubic-bezier(.3,.7,.2,1)'

interface Box { left: number; right: number; top: number; bottom: number }

/** Курсор над блоком или в полоске под ним. */
export function near(r: Box, x: number, y: number, skirt = SKIRT): boolean {
  return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom + skirt
}

function tileOf(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? target.closest<HTMLElement>('.gappt') : null
}

function canAnimate(el: Element): boolean {
  return typeof el.animate === 'function' && motionOk()
}

/** Блок, сменивший место, коротко «садится» после сдвига переезда. */
export function settleTile(el: HTMLElement): void {
  if (!canAnimate(el)) return
  el.animate([{ scale: '1' }, { scale: '1.05', offset: 0.45 }, { scale: '1' }],
    { duration: SETTLE_MS, delay: stepMs('--dur') - 70, easing: 'ease-out', id: TAG })
}

/** Блоки дня проявляются по очереди сверху вниз. */
export function cascadeIn(body: HTMLElement): void {
  if (!canAnimate(body)) return
  hookPrint()
  const tiles = Array.from(body.querySelectorAll<HTMLElement>('.gappt'))
    .sort((a, b) => a.offsetTop - b.offsetTop)
  tiles.forEach((t, i) => {
    t.animate([{ opacity: 0, translate: '0 8px' }, { opacity: 1, translate: '0 0' }],
      { duration: CASCADE_MS, delay: Math.min(i * CASCADE_STEP, CASCADE_CAP), easing: 'ease-out', fill: 'backwards', id: TAG })
  })
}

/** Оборот зубчика и блик. В узком блоке и в «только имя» зуба нет — играет один блик. */
function play(tile: HTMLElement): Animation[] {
  const runs: Animation[] = []
  const link = tile.querySelector<HTMLElement>('.apact')
  const svg = link?.querySelector<SVGElement>('svg')
  if (link && svg && getComputedStyle(link).display !== 'none') {
    runs.push(svg.animate([{ rotate: '0deg' }, { rotate: '360deg' }], { duration: TOOTH_MS, easing: SPIN, id: TAG }))
  }
  const band = tile.querySelector<HTMLElement>('.gfx > i')
  if (band) {
    runs.push(band.animate([{ translate: '-130% 0', opacity: 1 }, { translate: '260% 0', opacity: 1 }],
      { duration: SHEEN_MS, easing: 'ease-out', id: TAG }))
  }
  return runs
}

/* Картинку под курсором браузер снимает один раз, в `dragstart`: наклон и тень
   кладутся на копию блока, которая и отдаётся картинкой. Копия стоит в копии
   колонки той же ширины — вид блока зависит от колонки (дорожки кабинетов,
   ширина контейнера). */
function dragImage(e: DragEvent, tile: HTMLElement): void {
  const col = tile.parentElement
  if (!col || !e.dataTransfer || typeof e.dataTransfer.setDragImage !== 'function') return
  const r = tile.getBoundingClientRect()
  const cr = col.getBoundingClientRect()
  const wrap = document.createElement('div')
  wrap.className = 'gdragimg'
  wrap.style.padding = `${PAD}px`
  const lane = document.createElement('div')
  lane.className = col.className
  for (const a of ['data-lanes', 'data-ctl']) {
    const v = col.getAttribute(a)
    if (v !== null) lane.setAttribute(a, v)
  }
  lane.style.cssText = `width:${cr.width}px;height:${r.height}px;border:0;flex:none`
  const copy = tile.cloneNode(true) as HTMLElement
  for (const a of ['data-appt', 'title', 'draggable', 'data-hov', 'data-src']) copy.removeAttribute(a)
  copy.style.top = '0'
  copy.style.height = `${r.height}px`
  lane.appendChild(copy)
  wrap.appendChild(lane)
  /* рядом с канвой, а не в конце документа: правила блока написаны под корнем экрана */
  ;(tile.closest('.gridcard')?.parentElement ?? document.body).appendChild(wrap)
  e.dataTransfer.setDragImage(wrap, PAD + e.clientX - cr.left, PAD + e.clientY - r.top)
  window.setTimeout(() => wrap.remove(), 0)
}

/**
 * Повесить отклик на канву. Возвращает снятие.
 * Слушатели стоят на самой канве: её `dragstart` приходит раньше обработчика
 * блока (тот слушает у корня приложения), и блок успевает встать на место.
 */
export function attachTileFx(body: HTMLElement): () => void {
  let hov: HTMLElement | null = null
  let held = false
  let px = -1
  let py = -1
  /* блок, сыгравший своё: `busy` — играет, `spent` — доиграл, а курсор ещё над ним */
  const live = new WeakMap<Element, 'busy' | 'spent'>()

  const setHov = (tile: HTMLElement | null) => {
    held = false
    if (hov === tile) return
    hov?.removeAttribute('data-hov')
    hov = tile
    tile?.setAttribute('data-hov', '')
  }
  const nearHov = () => hov !== null && hov.isConnected && near(hov.getBoundingClientRect(), px, py)
  const leftTile = (e: PointerEvent, tile: Element) =>
    !(e.relatedTarget instanceof Node && tile.contains(e.relatedTarget))

  function onOver(e: PointerEvent) {
    if (e.pointerType === 'touch' || body.hasAttribute('data-dragging')) return
    const tile = tileOf(e.target)
    if (!tile) return
    px = e.clientX
    py = e.clientY
    setHov(tile)
    if (tile.classList.contains('gnote') || live.has(tile) || !leftTile(e, tile) || !canAnimate(tile)) return
    hookPrint()
    const runs = play(tile)
    if (!runs.length) return
    live.set(tile, 'busy')
    void Promise.allSettled(runs.map((a) => a.finished)).then(() => {
      if (tile.isConnected && near(tile.getBoundingClientRect(), px, py, 0)) live.set(tile, 'spent')
      else live.delete(tile)
    })
  }

  function onOut(e: PointerEvent) {
    const tile = tileOf(e.target)
    if (!tile || !leftTile(e, tile)) return
    px = e.clientX
    py = e.clientY
    if (tile === hov) {
      if (nearHov()) held = true
      else setHov(null)
    }
    if (live.get(tile) === 'spent') live.delete(tile)
  }

  function onMove(e: PointerEvent) {
    px = e.clientX
    py = e.clientY
    if (held && !nearHov()) setHov(null)
    /* перенос, у которого `dragend` не пришёл: блок сняли посреди броска */
    if (!e.buttons && body.hasAttribute('data-dragging')) dragOver()
  }

  function onDragStart(e: DragEvent) {
    const tile = tileOf(e.target)
    if (!tile) return
    /* место хвата меряется по прямоугольнику блока: подъём, сжатие и свои анимации сняты до замера */
    body.setAttribute('data-dragging', '')
    setHov(null)
    if (typeof tile.getAnimations === 'function') {
      for (const a of tile.getAnimations({ subtree: true })) if (a.id === TAG) a.cancel()
    }
    if (!motionOk()) return
    dragImage(e, tile)
    tile.setAttribute('data-src', '')
  }

  function dragOver() {
    body.removeAttribute('data-dragging')
    for (const t of body.querySelectorAll('[data-src]')) t.removeAttribute('data-src')
  }

  const leave = () => setHov(null)
  body.addEventListener('pointerover', onOver)
  body.addEventListener('pointerout', onOut)
  body.addEventListener('pointermove', onMove)
  body.addEventListener('pointerleave', leave)
  body.addEventListener('dragstart', onDragStart, true)
  body.addEventListener('dragend', dragOver)
  body.addEventListener('drop', dragOver)
  return () => {
    body.removeEventListener('pointerover', onOver)
    body.removeEventListener('pointerout', onOut)
    body.removeEventListener('pointermove', onMove)
    body.removeEventListener('pointerleave', leave)
    body.removeEventListener('dragstart', onDragStart, true)
    body.removeEventListener('dragend', dragOver)
    body.removeEventListener('drop', dragOver)
    dragOver()
    setHov(null)
  }
}

/**
 * Отклик блоков канвы. `day` — день канвы («» — канвы нет): слушатели вешаются,
 * когда канва появилась, очередь появления играет на первом показе дня и на его
 * смене. Опрос живого канала день не меняет — на нём не играет ничего.
 */
export function useTileFx(body: RefObject<HTMLElement | null>, day: string): void {
  useEffect(() => {
    const el = body.current
    if (!el || !day) return
    return attachTileFx(el)
  }, [body, day])
  useLayoutEffect(() => {
    const el = body.current
    if (el && day) cascadeIn(el)
  }, [body, day])
}
