import { useCallback, useEffect, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { ToastState } from '../../components/Toast'
import { asApiError } from '../../services/api'
import { DentalArch } from './DentalArch'
import { ToothDialog } from './ToothDialog'
import { ToothTip, type Hover } from './ToothTip'
import { ViewSwitch } from './ViewSwitch'
import { chart, type Odontogram } from './chart'
import { useChart } from './useChart'

/* Компактная одонтограмма в фише (C21 закрывает точку интеграции C18):
   тот же ClinicalChart, что на детальной странице, — обе дуги, оба вида,
   подсказка при наведении, диалог зуба по клику. Модель приезжает С ФИШЕЙ
   (загрузчик фиши, `initial`) — так дуга стоит в первом кадре и ничего под
   ней не прыгает; своим запросом карточка грузит её только если фиша модели
   не принесла (отказ карты). Запись зуба просит у сервера и свежую фишу (`?card=1`) и
   отдаёт её наверх (`onChanged`) — пилюли шапки и летопись зависят от
   зубов. ⛔ Фиша не перечитывает себя GET-ом: это ОТКРЫТИЕ, и каждое
   сохранение зуба оставляло бы в журнале доступа ложное «Fișa deschisă».
   Закрытие диалога = отказ от правки: черновик сбрасывается, как у старой
   модалки. */
const T = {
  title: 'Formula dentară',
  sub: 'notație FDI · click pe dinte',
  perio: 'Parodontogramă',
  detail: 'Detaliat',
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
      чтобы повторный клик по тому же зубу тоже открыл диалог. */
  open?: { n: number; k: number } | null
  /** Модель, приехавшая с фишей (загрузчик); `null` — грузить самой. */
  initial?: Odontogram | null
}

export function OdontogramCard({ pid, views, say, onFail, onChanged, open = null, initial = null }: Props) {
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
  const c = useChart(pid, model, replace, fail, say, null, `?card=1${views ? '&views=1' : ''}`)
  const [hover, setHover] = useState<Hover | null>(null)
  // просьба открыть зуб применяется один раз на метку — выводится при
  // отрисовке, без эффекта (правило хуков)
  const [seenOpen, setSeenOpen] = useState<number>(0)
  if (open && open.k !== seenOpen && model) {
    setSeenOpen(open.k)
    c.select(open.n)
  }

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

  const close = () => { c.discard(); c.select(null) }
  return (
    <>
      <div className="fcard odo" id="odo" data-view={c.view}>
        <div className="odo-head">
          <h3>{T.title} <small>· {T.sub}</small></h3>
          <div className="odo-actions">
            <ViewSwitch view={c.view} onChange={c.setView} />
            <AppLink className="odo-more" href={`${base}/parodontograma`}><Icon name="tooth" /> {T.perio}</AppLink>
            <AppLink className="odo-more" href={`${base}/odontograma`}><Icon name="eye" /> {T.detail}</AppLink>
          </div>
        </div>
        <DentalArch
          model={model}
          view={c.view}
          selected={null}
          onSelect={c.select}
          onSurface={c.pickSurface}
          onHover={(n, el) => setHover(el ? { n, el } : null)}
        />
      </div>
      <ToothTip model={model} hover={hover} />
      <ToothDialog
        model={model}
        n={c.selected}
        busy={c.busy}
        sel={c.sel}
        onSel={c.setSel}
        draft={c.draft}
        dirty={c.dirty}
        onEdit={c.edit}
        onSave={() => { void c.save().then((ok) => { if (ok) c.select(null) }) }}
        onDiscard={c.discard}
        onClose={close}
      />
    </>
  )
}
