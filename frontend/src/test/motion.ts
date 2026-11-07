import { vi } from 'vitest'

/** Система разрешает движение: `(prefers-reduced-motion: no-preference)`
 *  совпадает. В jsdom `matchMedia` нет вовсе — там движение выключено. */
export function allowMotion(): void {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('no-preference'), media: q, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  }))
}
