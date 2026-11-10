import { useState } from 'react'

/* «Durată» в окнах записи (10.11.2026, жалоба пилота: «Consultație 15′, а
   пациенту нужно 30′, и минуты не поменять»). Один выбор на оба окна записи —
   «Programare nouă» (`AddDialog`) и окно часа на панели (`SlotDialog`):
   два своих селекта разошлись бы молча.

   ⛔ Поле едет на сервер ТОЛЬКО тронутым (прайор 08-16: намерение из формы, не
   угадывать по базе): пока его не трогали, оно показывает длительность
   выбранной услуги и следует за сменой услуги, а запись берёт длительность
   услуги, как всегда. Тронули — визит ложится этой длины с признаком «задана
   руками», и смена процедуры её потом не перебьёт.
   Список — с сервера (`form.durations` = `eng.DURATIONS`, тот же, что у услуги
   в настройках); нет списка — нет и поля. */

const T = { dur: 'Durată' } as const

interface Svc { id: string; dur?: number }

export interface DurBox {
  durations: number[]
  value: number
  pick: (minutes: number) => void
  /** Добавка к телу записи: пусто, пока поле не тронуто. */
  field: { duration?: number }
}

export function useDurPick(services: Svc[], service: string,
  durations: number[] | undefined): DurBox {
  const [picked, setPicked] = useState<number | null>(null)
  const base = services.find((s) => s.id === service)?.dur ?? 0
  return {
    durations: durations ?? [],
    value: picked ?? base,
    pick: setPicked,
    field: picked !== null ? { duration: picked } : {},
  }
}

export function DurSelect({ box }: { box: DurBox }) {
  if (!box.durations.length) return null
  /* длительность услуги вне списка (старая запись в clinic.json) — стоит
     первой строкой, чтобы поле не показывало чужое число */
  const list = box.durations.includes(box.value) || !box.value
    ? box.durations : [box.value, ...box.durations]
  return (
    <select className="dp-dur" value={box.value} aria-label={T.dur} title={T.dur}
            onChange={(e) => box.pick(Number(e.target.value))}>
      {box.value ? null : <option value={0} disabled>{T.dur}</option>}
      {list.map((d) => <option key={d} value={d}>{d} min</option>)}
    </select>
  )
}
