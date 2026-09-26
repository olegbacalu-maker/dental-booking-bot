import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useMenuDismiss } from '../../components/menu'
import type { Odontogram, ToothInfo } from './chart'
import { Tooth } from './Tooth'
import { ToothForm } from './ToothForm'
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

describe('крупные кнопки состояний', () => {
  const MODEL = {
    states: { ok: 'Sănătos', carie: 'Carie', extras: 'Extras', lipsa: 'Lipsă' },
    palette: { ok: '#1F2937', carie: '#EF4444', extras: '#64748B', lipsa: '#CBD5E1' },
    surfaces: { M: 'mezial', O: 'ocluzal', D: 'distal', V: 'vestibular', L: 'lingual' },
    surface_states: ['carie'], marks: { tratament: 'În tratament' }, doctors: [],
  } as unknown as Odontogram
  const TINFO = { jaw: 'sus', mez: 'right', state: 'ok', sfst: {} } as unknown as ToothInfo
  const DRAFT = { state: 'ok', note: '', doctor: '', sfst: {}, marks: [] }
  const form = (onEdit = vi.fn()) => {
    render(<ToothForm model={MODEL} n={16} info={TINFO} busy={false} sel="O" onSel={() => undefined}
      draft={DRAFT} dirty={false} onEdit={onEdit} onSave={() => undefined} onDiscard={() => undefined} />)
    return onEdit
  }

  it('пальцем — кнопки по одной на состояние с цветом палитры; касание правит черновик', () => {
    coarse(true)
    const onEdit = form()
    const group = screen.getByRole('radiogroup', { name: 'Starea dintelui' })
    const radios = [...group.querySelectorAll('[role=radio]')]
    expect(radios.map((r) => r.textContent)).toEqual(['Sănătos', 'Carie', 'Extras', 'Lipsă'])
    expect(radios[0]?.getAttribute('aria-checked')).toBe('true')
    expect((radios[1]?.querySelector('i') as HTMLElement).style.background).toBe('rgb(239, 68, 68)')
    fireEvent.click(screen.getByRole('radio', { name: 'Extras' }))
    expect(onEdit).toHaveBeenCalledWith({ state: 'extras' })
    expect(screen.queryByLabelText('Starea dintelui', { selector: 'select' })).toBeNull()
  })

  it('мышью — прежний выпадающий список, кнопок нет', () => {
    form()
    expect(screen.getByLabelText('Starea dintelui', { selector: 'select' })).toBeTruthy()
    expect(screen.queryByRole('radiogroup')).toBeNull()
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
