import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useMenuDismiss } from '../../components/menu'
import { Tooth } from './Tooth'
import { StatusPicker } from './StatusPicker'
import { LONG_MS, slopOf, TOUCH_SLOP, useCoarse } from './touch'

/* Одонтограмма под палец (B7 · планшет): долгое нажатие открывает меню зуба
   без contextmenu (iPad его не шлёт), протяжка его отменяет, мышь живёт как
   жила; под пальцем состояние зуба — крупные кнопки. */

const INFO = { title: '16 · Sănătos', svg: { frontal: "<svg><g class='sfz'><circle data-s='O'/></g></svg>", occlusal: '<svg></svg>' } }

function mountTooth() {
  const onMenu = vi.fn()
  const onSelect = vi.fn()
  render(<Tooth n={16} info={INFO} view="frontal" onSelect={onSelect} onMenu={onMenu} />)
  const btn = document.querySelector('.tooth-btn') as HTMLButtonElement
  return { btn, onMenu, onSelect }
}

const coarse = (on: boolean) => {
  window.matchMedia = vi.fn().mockImplementation((q: string) => ({
    matches: on && q.includes('coarse'), media: q, addEventListener: () => undefined, removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => {
  // одноразовый перехватчик click (swallowNextClick) снимается сам через 1,5 с —
  // на поддельных часах их надо дойти, иначе он съел бы click следующего теста
  vi.runOnlyPendingTimers()
  cleanup()
  vi.useRealTimers()
  // jsdom без matchMedia — как было
  delete (window as { matchMedia?: unknown }).matchMedia
})

describe('долгое нажатие на зубе', () => {
  it('палец, удержание 500 мс → меню в точке касания; отпускание не выбирает зуб', () => {
    const { btn, onMenu, onSelect } = mountTooth()
    fireEvent.pointerDown(btn, { pointerType: 'touch', pointerId: 1, clientX: 50, clientY: 60 })
    act(() => { vi.advanceTimersByTime(LONG_MS - 1) })
    expect(onMenu).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(1) })
    expect(onMenu).toHaveBeenCalledWith(16, 50, 60)
    fireEvent.pointerUp(btn, { pointerType: 'touch', pointerId: 1 })
    fireEvent.click(btn)
    expect(onSelect).not.toHaveBeenCalled()
    // следующее обычное касание снова выбирает
    fireEvent.pointerDown(btn, { pointerType: 'touch', pointerId: 2, clientX: 50, clientY: 60 })
    fireEvent.pointerUp(btn, { pointerType: 'touch', pointerId: 2 })
    fireEvent.click(btn)
    expect(onSelect).toHaveBeenCalledWith(16)
  })

  it('протяжка дальше 10 px отменяет меню; короткое касание — обычный выбор', () => {
    const { btn, onMenu, onSelect } = mountTooth()
    fireEvent.pointerDown(btn, { pointerType: 'touch', pointerId: 1, clientX: 50, clientY: 60 })
    fireEvent.pointerMove(btn, { pointerType: 'touch', pointerId: 1, clientX: 50 + TOUCH_SLOP + 1, clientY: 60 })
    act(() => { vi.advanceTimersByTime(LONG_MS * 2) })
    expect(onMenu).not.toHaveBeenCalled()
    fireEvent.pointerDown(btn, { pointerType: 'touch', pointerId: 2, clientX: 50, clientY: 60 })
    act(() => { vi.advanceTimersByTime(120) })
    fireEvent.pointerUp(btn, { pointerType: 'touch', pointerId: 2 })
    act(() => { vi.advanceTimersByTime(LONG_MS) })
    fireEvent.click(btn)
    expect(onMenu).not.toHaveBeenCalled()
    expect(onSelect).toHaveBeenCalledWith(16)
  })

  it('мышь: удержание меню не открывает, правая кнопка — открывает у курсора', () => {
    const { btn, onMenu, onSelect } = mountTooth()
    fireEvent.pointerDown(btn, { pointerType: 'mouse', pointerId: 1, clientX: 5, clientY: 6 })
    act(() => { vi.advanceTimersByTime(LONG_MS * 3) })
    expect(onMenu).not.toHaveBeenCalled()
    fireEvent.click(btn)
    expect(onSelect).toHaveBeenCalledWith(16)
    fireEvent.contextMenu(btn, { clientX: 70, clientY: 80 })
    expect(onMenu).toHaveBeenCalledWith(16, 70, 80)
  })

  it('contextmenu Android после сработавшего долгого нажатия гасится — меню одно', () => {
    const { btn, onMenu } = mountTooth()
    fireEvent.pointerDown(btn, { pointerType: 'touch', pointerId: 1, clientX: 50, clientY: 60 })
    act(() => { vi.advanceTimersByTime(LONG_MS) })
    fireEvent.contextMenu(btn, { clientX: 51, clientY: 61 })
    expect(onMenu).toHaveBeenCalledTimes(1)
  })

  it('порог сдвига: палец 10 px, мышь 4 px', () => {
    expect(slopOf({ pointerType: 'touch' })).toBe(10)
    expect(slopOf({ pointerType: 'pen' })).toBe(10)
    expect(slopOf({ pointerType: 'mouse' })).toBe(4)
  })
})

describe('устройство ввода', () => {
  function Probe() {
    return <b>{useCoarse() ? 'palec' : 'mouse'}</b>
  }
  it('(pointer: coarse) → палец; без matchMedia (jsdom) — мышь', () => {
    render(<Probe />)
    expect(screen.getByText('mouse')).toBeTruthy()
    cleanup()
    coarse(true)
    render(<Probe />)
    expect(screen.getByText('palec')).toBeTruthy()
  })
})

describe('состояние зуба — сетка кнопок (08.10: одна и та же мышью и пальцем)', () => {
  const STATES = { ok: 'Sănătos', carie: 'Carie', extras: 'Extras', lipsa: 'Lipsă' }
  const PALETTE = { carie: '#EF4444', extras: '#94A3B8', lipsa: '#CBD5E1' }
  const pick = (value: string, onChange = vi.fn()) => {
    render(<StatusPicker states={STATES} palette={PALETTE} value={value} onChange={onChange} />)
    return onChange
  }

  it('по кнопке на состояние сервера с цветом палитры; «здоров» — ничего не нажато', () => {
    const onChange = pick('ok')
    const group = screen.getByRole('group', { name: 'Starea dintelui' })
    const btns = [...group.querySelectorAll('button')]
    expect(btns.map((b) => b.textContent)).toEqual(['Carie', 'Extras', 'Lipsă'])
    expect(btns.every((b) => b.getAttribute('aria-pressed') === 'false')).toBe(true)
    expect((btns[0]?.querySelector('i') as HTMLElement).style.background).toBe('rgb(239, 68, 68)')
    fireEvent.click(screen.getByRole('button', { name: 'Extras' }))
    expect(onChange).toHaveBeenCalledWith('extras')
    expect(screen.queryByLabelText('Starea dintelui', { selector: 'select' })).toBeNull()
  })

  it('повторное нажатие на выбранном снимает состояние — зуб здоров', () => {
    const onChange = pick('carie')
    expect(screen.getByRole('button', { name: 'Carie' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Carie' }))
    expect(onChange).toHaveBeenCalledWith('ok')
  })
})

describe('меню не закрывается отпусканием пальца', () => {
  function Menu({ onClose }: { onClose: () => void }) {
    const ref = useRef<HTMLDivElement>(null)
    useMenuDismiss(ref, onClose)
    return <div ref={ref}><button type="button">item</button></div>
  }
  it('совместимые mousedown/click отпускания не закрывают; нажатие мимо (pointerdown) закрывает, внутри — нет', () => {
    const onClose = vi.fn()
    render(<Menu onClose={onClose} />)
    fireEvent.mouseDown(document.body)
    fireEvent.click(document.body)
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.pointerDown(screen.getByText('item'))
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.pointerDown(document.body)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('после долгого нажатия первый click гасится где угодно (в том числе на пункте меню), следующий — живой', () => {
    const { btn } = mountTooth()
    const item = document.createElement('button')
    const onItem = vi.fn()
    item.addEventListener('click', onItem)
    document.body.appendChild(item)
    fireEvent.pointerDown(btn, { pointerType: 'touch', pointerId: 1, clientX: 50, clientY: 60 })
    act(() => { vi.advanceTimersByTime(LONG_MS) })
    fireEvent.click(item)
    expect(onItem).not.toHaveBeenCalled()
    fireEvent.click(item)
    expect(onItem).toHaveBeenCalledTimes(1)
    item.remove()
  })
})
