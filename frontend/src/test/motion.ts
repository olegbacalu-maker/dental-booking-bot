import { act } from '@testing-library/react'
import { vi } from 'vitest'

/** Переход свойства у узла доиграл (jsdom переходов не знает): окно, закрытое с
 *  движением, ждёт конца перехода прозрачности — `components/dialog.useDialogLeave`. */
export function endTransition(target: Element, propertyName = 'opacity'): void {
  const e = new Event('transitionend', { bubbles: true })
  Object.defineProperty(e, 'propertyName', { value: propertyName })
  act(() => { target.dispatchEvent(e) })
}

/** Система разрешает движение: `(prefers-reduced-motion: no-preference)`
 *  совпадает. В jsdom `matchMedia` нет вовсе — там движение выключено. */
export function allowMotion(): void {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('no-preference'), media: q, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  }))
}
