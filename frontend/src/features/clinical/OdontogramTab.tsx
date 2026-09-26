import { useCallback, useEffect, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import type { ToastState } from '../../components/Toast'
import { asApiError } from '../../services/api'
import { OdontogramWorkbench } from './OdontogramWorkbench'
import { chart, type Odontogram } from './chart'

/* Одонтограмма во вкладке фиши (B6, шаг 2; до 26.09 — компактная карточка C21
   с диалогом зуба). Инструмент тот же, что на детальной странице
   (`OdontogramWorkbench`): инспектор, поверхности, мосты, история, клавиатура —
   врачу не надо уходить из рабочего места. Модель приезжает С ФИШЕЙ
   (загрузчик фиши, `initial`) — так дуга стоит в первом кадре вкладки; своим
   запросом контейнер грузит её только если фиша модели не принесла (отказ
   карты или фиша уже подменена ответом действия — там `odontogram` нет).
   Запись зуба просит у сервера и свежую фишу (`?card=1`) и отдаёт её наверх
   (`onChanged`) — пилюли шапки и летопись зависят от зубов. ⛔ Фиша не
   перечитывает себя GET-ом: это ОТКРЫТИЕ, и каждое сохранение зуба оставляло
   бы в журнале доступа ложное «Fișa deschisă». */
const T = {
  loading: 'Se încarcă formula dentară…',
  failed: 'Formula dentară nu s-a încărcat.',
  open: 'Deschide formula detaliată',
} as const

interface Props {
  pid: number
  /** Режим ленты фиши (`?views=1`): свежая фиша в ответе записи — в нём же. */
  views: boolean
  say: (t: ToastState) => void
  onFail: (e: unknown) => void
  /** Зуб записан — свежая фиша из того же ответа (её тип знает фиша). */
  onChanged: (card: unknown) => void
  /** Просьба открыть зуб снаружи (кнопка номера в плане): объект с меткой,
      чтобы повторный клик по тому же зубу тоже выбрал его. */
  open?: { n: number; k: number } | null
  /** Модель, приехавшая с фишей (загрузчик); `null` — грузить самой. */
  initial?: Odontogram | null
}

export function OdontogramTab({ pid, views, say, onFail, onChanged, open = null, initial = null }: Props) {
  const [got, setGot] = useState<{ pid: number; model: Odontogram | null; failed: boolean } | null>(null)
  /* Своё состояние (ответ записи, свой запрос) главнее засева; засев — только
     для ЭТОГО пациента: после перехода на другую фишу старый не годится. */
  const mine = got && got.pid === pid ? got : null
  const seeded = initial && initial.patient.id === pid ? initial : null
  const model = mine ? mine.model : seeded
  const failed = Boolean(mine?.failed)
  const replace = useCallback((m: Odontogram) => {
    const { card, ...fresh } = m
    setGot({ pid, model: fresh, failed: false })
    onChanged(card)
  }, [pid, onChanged])
  const fail = useCallback((e: unknown) => onFail(asApiError(e)), [onFail])

  useEffect(() => {
    if (seeded || (got && got.pid === pid)) return   // модель уже есть — запрос не нужен
    const ctl = new AbortController()
    chart.get(pid, ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setGot({ pid, model: r.data, failed: false }) },
      (e: unknown) => { if (!ctl.signal.aborted) { setGot({ pid, model: null, failed: true }); onFail(asApiError(e)) } },
    )
    return () => ctl.abort()
  }, [pid, onFail, seeded, got])

  const base = `/admin/patient/${pid}`
  if (failed) {
    return (
      <div className="fcard">
        <p className="hint dp-m0">{T.failed} <AppLink href={`${base}/odontograma`}>{T.open}</AppLink></p>
      </div>
    )
  }
  if (!model) return <div className="fcard dp-odo-wait" aria-busy="true"><p className="hint dp-m0">{T.loading}</p></div>
  return (
    <OdontogramWorkbench pid={pid} model={model} replace={replace} fail={fail} say={say} open={open}
      saveQuery={`?card=1${views ? '&views=1' : ''}`} embedded />
  )
}
