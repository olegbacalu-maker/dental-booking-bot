import { act, render, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Odontogram } from '../chart'
import { Odontogram3D } from './Odontogram3D'

/* Печать 3D ждёт прикус (08.11): план считает воркер (до ~1 с после открытия вкладки),
   челюсть доезжает твином — снимок раньше напечатал бы раскладку без прикуса. Сцена
   поддельная: проверяется ПОРЯДОК вызовов компонента, сама поза — стенды Edge. */
const log: string[] = []
let release: () => void = () => undefined

vi.mock('./loadTeeth', () => ({ load3d: () => Promise.resolve({ THREE: {}, teeth: {} }) }))
vi.mock('./scene', async (importOriginal) => {
  const real = await importOriginal<typeof import('./scene')>()
  const own: Record<string, unknown> = {
    whenOccluded: () => { log.push('wait'); return new Promise<void>((ok) => { release = ok }) },
    settleOcclusion: () => { log.push('settle') },
    snapshot: () => { log.push('shot'); return 'data:image/png;base64,AAAA' },
  }
  const fake = new Proxy({}, { get: (_t, k) => (k === 'then' ? undefined : own[k as string] ?? (() => undefined)) })
  return { ...real, createArchScene: () => fake }
})

const MODEL = { perio_layer: null, ocluzie: null, milk_open: false, palette: {}, teeth: {} } as unknown as Odontogram
const noop = (): void => undefined

function mount() {
  const ref = createRef<(() => Promise<void>) | null>() as { current: (() => Promise<void>) | null }
  render(<Odontogram3D model={MODEL} selected={null} onSurface={noop} onMenu={noop} focus={null} onZoom={noop}
    onDouble={noop} dim={new Set()} mode="stare" onFlat={noop} printShotRef={ref} />)
  return ref
}

afterEach(() => { log.length = 0 })

describe('печать 3D ждёт прикус', () => {
  it('кнопка: снимок — только после whenOccluded, затем прикус доведён на месте', async () => {
    const ref = mount()
    await waitFor(() => expect(document.querySelector('.odo-stage')).toBeTruthy())
    await act(async () => { await Promise.resolve() })
    let done = false
    let p: Promise<void> = Promise.resolve()
    act(() => { p = ref.current!().then(() => { done = true }) })
    await act(async () => { await Promise.resolve() })
    expect(log).toEqual(['wait'])
    expect(done).toBe(false)
    await act(async () => { release(); await p })
    expect(log).toEqual(['wait', 'settle', 'shot'])
  })

  it('Ctrl+P мимо кнопки: beforeprint доводит прикус синхронно и снимает сразу', async () => {
    mount()
    await waitFor(() => expect(document.querySelector('.odo-stage')).toBeTruthy())
    await act(async () => { await Promise.resolve() })
    act(() => { window.dispatchEvent(new Event('beforeprint')) })
    expect(log).toEqual(['settle', 'shot'])
    act(() => { window.dispatchEvent(new Event('afterprint')) })
  })
})
