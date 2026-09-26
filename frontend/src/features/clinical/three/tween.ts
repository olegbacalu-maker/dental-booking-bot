/* Твины (B7, ступень 3): кадры только пока что-то движется. Никакого
   постоянного цикла — сцена просит кадр (`wake`), когда твин добавлен, и
   продолжает просить, пока `step` отвечает «занято». При
   `prefers-reduced-motion` всё мгновенно: `fn(1)` и `done` синхронно, в
   очередь ничего не попадает (правило дизайн-системы Dental3D и решение 5
   Олега). Чистый модуль: время и пробуждение приходят снаружи. */

export type TweenFn = (k: number) => void

interface Tween {
  t0: number
  dur: number
  fn: TweenFn
  done: (() => void) | null
  tag: unknown
}

/** ease-in-out кубическая: та же, что в макете. */
export const ease = (k: number): number => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2)

export interface Tweens {
  /** запланировать; при reduced — выполнить сразу */
  add(dur: number, fn: TweenFn, done?: (() => void) | null, delay?: number, tag?: unknown): void
  /** снять все твины с этой меткой (незавершённые — без `done`) */
  kill(tag: unknown): void
  /** продвинуть до момента now; true — ещё есть что двигать */
  step(now: number): boolean
  readonly size: number
}

export interface TweenOptions {
  reduced: boolean
  /** часы; по умолчанию performance.now */
  now?: () => number
  /** попросить кадр — сцена вызывает invalidate */
  wake?: () => void
}

export function createTweens(opts: TweenOptions): Tweens {
  const list: Tween[] = []
  const now = opts.now ?? (() => performance.now())
  const wake = opts.wake ?? (() => undefined)
  return {
    add(dur, fn, done = null, delay = 0, tag = null) {
      if (opts.reduced || dur <= 0) {
        fn(1)
        if (done) done()
        return
      }
      list.push({ t0: now() + delay, dur, fn, done, tag })
      wake()
    },
    kill(tag) {
      for (let i = list.length - 1; i >= 0; i--) {
        if (list[i]?.tag === tag) list.splice(i, 1)
      }
    },
    step(t) {
      for (let i = list.length - 1; i >= 0; i--) {
        const tw = list[i]
        if (!tw || t < tw.t0) continue
        const k = Math.min(1, (t - tw.t0) / tw.dur)
        tw.fn(ease(k))
        if (k >= 1) {
          list.splice(i, 1)
          if (tw.done) tw.done()
        }
      }
      return list.length > 0
    },
    get size() { return list.length },
  }
}
