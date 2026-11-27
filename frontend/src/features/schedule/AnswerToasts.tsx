import { useCallback, useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { motionOk, stepMs } from '../../utils/motion'
import { ANSWER_MS, type AnswerPlate } from './answers'
import type { DeskAnswer } from './desk'

const T = {
  ok: 'a confirmat prin SMS',
  cant: 'nu poate veni (SMS)',
  open: 'Deschide vizita',
  close: 'Închide',
} as const

interface Props {
  plates: readonly AnswerPlate[]
  /** Нажатие на плашку: открыть окно визита (плашка уходит). */
  onOpen: (a: DeskAnswer) => void
  /** Плашка ушла: сама («Vin» через `ANSWER_MS`) или крестиком. */
  onGone: (key: string) => void
}

/**
 * Стопка плашек «пациент ответил» — вид нынешней плашки ответа программы (`.toastbox .banner`:
 * тёмный фон темы, кромка слева, крестик), внизу справа; новая снизу. «Vin» — галочка и кромка
 * фирменного цвета, уходит сама; «Nu poate veni» — трубка и кромка `--amber`, висит до крестика.
 * ⛔ Стоит рядом с плашкой действия экрана (`Toast`), а не вместо неё: если обе на экране, стопка
 * поднимается над ней (panel.css › `.toastbox ~ .dp-ans`).
 */
export function AnswerToasts({ plates, onOpen, onGone }: Props) {
  if (!plates.length) return null
  return (
    <div className="toastbox dp-ans" role="status" aria-live="polite">
      {plates.map((p) => <Plate key={p.key} plate={p} onOpen={onOpen} onGone={onGone} />)}
    </div>
  )
}

function Plate({ plate, onOpen, onGone }: { plate: AnswerPlate; onOpen: Props['onOpen']; onGone: Props['onGone'] }) {
  const { a, key } = plate
  const cant = a.call === 'cant'
  const [out, setOut] = useState(false)
  const going = useRef<number | null>(null)
  /* уход — как у плашки действия: сперва гаснет (класс `out`), потом просит хозяина её снять;
     без движения — сразу */
  const leave = useCallback(() => {
    if (!motionOk()) { onGone(key); return }
    setOut(true)
    if (going.current !== null) window.clearTimeout(going.current)
    going.current = window.setTimeout(() => onGone(key), stepMs('--dur'))
  }, [key, onGone])
  useEffect(() => () => { if (going.current !== null) window.clearTimeout(going.current) }, [])
  useEffect(() => {
    if (cant) return
    const t = window.setTimeout(leave, ANSWER_MS)
    return () => window.clearTimeout(t)
  }, [cant, leave])
  /* ⛔ Гаснет ОБЁРТКА, не плашка: у `.toastbox .banner` въезд — анимация с заполнением, и переход
     прозрачности на ней самой не играл бы (panel.css › «плавающий ответ въезжает»). */
  return (
    <div className={`dp-ans-w${out ? ' out' : ''}`}>
      <div className={`banner dp-ans-t${cant ? ' cant' : ''}`} data-appt={a.id}>
        <button type="button" className="dp-ans-open" title={T.open} onClick={() => { onOpen(a); leave() }}>
          <Icon name={cant ? 'phone-off' : 'check'} />
          <span><b>{a.name} · {a.when}</b> <span className="dp-ans-act">— {cant ? T.cant : T.ok}</span></span>
        </button>
        <button className="t-x" type="button" aria-label={T.close} onClick={leave}>
          <Icon name="close" />
        </button>
      </div>
    </div>
  )
}
