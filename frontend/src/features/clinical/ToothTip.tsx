import { useLayoutEffect, useRef, useState } from 'react'
import type { Odontogram, ToothInfo } from './chart'

/* Плавающая подсказка компактной карточки: одна на всю дугу, встаёт под
   кнопкой зуба. Показывается только там, где есть что сказать — здоровый
   зуб без заметки, врача и отметки молчит (отметка держит подсказку
   наравне с заметкой: «здоров, но в работе» — законная запись). */
const T = {
  tooth: 'Dinte',
  updated: 'Actualizat:',
  doctor: 'Medic:',
  surfaces: 'Suprafețe:',
} as const

export interface Hover {
  n: number
  el: HTMLElement
}

interface Props {
  model: Odontogram
  hover: Hover | null
}

export function tipWorthy(info: ToothInfo): boolean {
  return !(info.state === 'ok' && !info.note && !info.doctor && !info.mk.length)
}

export function ToothTip({ model, hover }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const info = hover ? model.teeth[String(hover.n)] : undefined
  const show = Boolean(hover && info && tipWorthy(info))

  useLayoutEffect(() => {
    if (!show || !hover || !ref.current) {
      setPos((p) => (p ? null : p))
      return
    }
    const r = hover.el.getBoundingClientRect()
    const w = ref.current.offsetWidth || 220
    let left = r.left + r.width / 2 - w / 2 + window.scrollX
    left = Math.max(8, Math.min(left, document.documentElement.clientWidth - w - 8))
    setPos({ left, top: r.bottom + window.scrollY + 8 })
  }, [show, hover])

  if (!show || !info || !hover) return null
  return (
    <div ref={ref} className="toothtip" style={{ display: 'block', left: pos?.left ?? 0, top: pos?.top ?? 0 }}>
      <b className="tt-n">{T.tooth} {hover.n}</b>
      <div className="tt-s">{model.states[info.state] ?? info.state}</div>
      <div className="tt-d">
        {info.mkx && <div className="tt-mk">{info.mkx}</div>}
        {info.at && <div>{T.updated} <b>{info.at}</b></div>}
        {info.doctor && <div>{T.doctor} <b>{info.doctor}</b></div>}
        {info.sfx && <div>{T.surfaces} <b>{info.sfx}</b></div>}
        {info.note && <div className="tt-note">{info.note}</div>}
      </div>
    </div>
  )
}
