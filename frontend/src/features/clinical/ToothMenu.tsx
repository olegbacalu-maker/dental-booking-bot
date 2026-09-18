import { useEffect, useRef } from 'react'
import type { Odontogram } from './chart'

/* Контекстное меню зуба (C22): состояния зуба — в ЧЕРНОВИК (запись — Save
   или Enter, как и у всего остального) и «Punte nouă de la acest dinte».
   Список состояний — сервера, своего словаря здесь нет. Меню не
   единственный путь: то же есть в инспекторе (touch, доступность). Закрывается
   кликом мимо, Esc, прокруткой и сменой размера окна; в окно вписывается. */
const T = {
  tooth: 'Dinte',
  bridgeFrom: 'Punte nouă de la acest dinte',
} as const

export interface MenuAt {
  n: number
  x: number
  y: number
}

interface Props {
  model: Odontogram
  at: MenuAt
  /** Текущее состояние зуба (черновик, если он есть) — отмечается в списке. */
  current: string
  onState: (n: number, state: string) => void
  onBridge: (n: number) => void
  onClose: () => void
}

const WIDTH = 236
const ROW = 32

export function ToothMenu({ model, at, current, onState, onBridge, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const down = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    window.addEventListener('resize', onClose)
    window.addEventListener('scroll', onClose, true)
    return () => {
      document.removeEventListener('mousedown', down)
      document.removeEventListener('keydown', key)
      window.removeEventListener('resize', onClose)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [onClose])

  const info = model.teeth[String(at.n)]
  const states = Object.entries(model.states)
  const bridge = Boolean(info && !info.milk)
  const height = 40 + states.length * ROW + (bridge ? ROW + 9 : 0) + 12
  const left = Math.max(4, Math.min(at.x, window.innerWidth - WIDTH - 4))
  const top = Math.max(4, Math.min(at.y, window.innerHeight - height - 4))
  return (
    <div ref={ref} className="dp-cmenu" role="menu" aria-label={`${T.tooth} ${at.n}`} style={{ left, top, width: WIDTH }}>
      <div className="dp-cmenu-h">{T.tooth} {at.n}</div>
      {states.map(([k, v]) => (
        <button
          key={k}
          type="button"
          role="menuitemradio"
          aria-checked={k === current}
          className={`dp-cmenu-i${k === current ? ' on' : ''}`}
          onClick={() => onState(at.n, k)}
        >
          {v}
        </button>
      ))}
      {bridge && (
        <>
          <div className="dp-cmenu-sep" />
          <button type="button" role="menuitem" className="dp-cmenu-i" onClick={() => onBridge(at.n)}>{T.bridgeFrom}</button>
        </>
      )}
    </div>
  )
}
