import { cleanup, render } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { allowMotion } from '../test/motion'
import { useFlip } from './flip'

/* Смыкание и переезд (07.11, вторая волна). jsdom раскладки не считает — место
   узла подставлено из `data-y`; движение — только вызов `animate`. Настоящие
   кадры и конечное место держит стенд `motion_check` (сценарии leave и move). */

const animate = vi.fn()

function List({ items, dep, after }: { items: [string, number][]; dep: unknown; after?: (el: HTMLElement) => void }) {
  const box = useRef<HTMLDivElement>(null)
  useFlip(box, dep, '.it', '--dur', after)
  return (
    <div ref={box}>
      {items.map(([id, y]) => <div key={id} className="it" data-appt={id} data-y={y} />)}
    </div>
  )
}

beforeEach(() => {
  animate.mockClear()
  Object.defineProperty(HTMLElement.prototype, 'offsetTop', {
    configurable: true,
    get(this: HTMLElement) { return Number(this.dataset.y ?? 0) },
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get(this: HTMLElement) { return this.parentElement },
  })
  Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  for (const k of ['offsetTop', 'offsetParent', 'animate']) {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)[k]
  }
})

describe('useFlip', () => {
  it('⛔ первая отрисовка и отрисовка без перемен не двигают ничего — опрос без изменений молчит', () => {
    allowMotion()
    const { rerender } = render(<List dep={1} items={[['a', 0], ['b', 40]]} />)
    rerender(<List dep={2} items={[['a', 0], ['b', 40]]} />)
    expect(animate).not.toHaveBeenCalled()
  })

  it('сменивший место доезжает сдвигом от прежнего места, без заполнения; соседи на месте', () => {
    allowMotion()
    const { rerender } = render(<List dep={1} items={[['a', 0], ['b', 40], ['c', 80]]} />)
    rerender(<List dep={2} items={[['b', 0], ['c', 80]]} />)
    expect(animate).toHaveBeenCalledTimes(1)
    const [frames, opts] = animate.mock.calls[0] as [Keyframe[], KeyframeAnimationOptions]
    expect(frames[0]!.transform).toBe('translate(0px, 40px)')
    expect(frames[1]!.transform).toBe('none')
    expect(opts.fill).toBeUndefined()
  })

  it('переехавший узел называют хозяину — только его: ни новый, ни оставшийся на месте', () => {
    allowMotion()
    const after = vi.fn()
    const { rerender } = render(<List dep={1} after={after} items={[['a', 0], ['b', 40], ['c', 80]]} />)
    expect(after).not.toHaveBeenCalled()
    rerender(<List dep={2} after={after} items={[['b', 0], ['c', 80], ['n', 120]]} />)
    expect(after).toHaveBeenCalledTimes(1)
    expect((after.mock.calls[0] as [HTMLElement])[0].getAttribute('data-appt')).toBe('b')
  })

  it('новый узел между старыми проявляется', () => {
    allowMotion()
    const { rerender } = render(<List dep={1} items={[['a', 0]]} />)
    rerender(<List dep={2} items={[['a', 0], ['n', 40]]} />)
    expect(animate).toHaveBeenCalledTimes(1)
    expect((animate.mock.calls[0] as [Keyframe[]])[0][0]!.opacity).toBe(0)
  })

  it('без движения в системе — ни одного запуска', () => {
    const { rerender } = render(<List dep={1} items={[['a', 0], ['b', 40]]} />)
    rerender(<List dep={2} items={[['b', 0]]} />)
    expect(animate).not.toHaveBeenCalled()
  })
})
