import { useCallback, useEffect, useState } from 'react'
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
   подсказка при наведении, диалог зуба по клику. Модель грузится своим
   запросом; после записи зуба фиша перезагружается тихо (`onChanged`) —
   пилюли шапки и летопись зависят от зубов. */
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
  say: (t: ToastState) => void
  onFail: (e: unknown) => void
  /** Зуб записан — фише пора перечитать себя. */
  onChanged: () => void
  /** Просьба открыть зуб снаружи (кнопка номера в плане): объект с меткой,
      чтобы повторный клик по тому же зубу тоже открыл диалог. */
  open?: { n: number; k: number } | null
}

export function OdontogramCard({ pid, say, onFail, onChanged, open = null }: Props) {
  const [got, setGot] = useState<{ pid: number; model: Odontogram | null; failed: boolean } | null>(null)
  const model = got && got.pid === pid ? got.model : null
  const failed = Boolean(got && got.pid === pid && got.failed)
  const replace = useCallback((m: Odontogram) => { setGot({ pid, model: m, failed: false }); onChanged() }, [pid, onChanged])
  const fail = useCallback((e: unknown) => onFail(asApiError(e)), [onFail])
  const c = useChart(pid, model, replace, fail, say)
  const [hover, setHover] = useState<Hover | null>(null)
  // просьба открыть зуб применяется один раз на метку — выводится при
  // отрисовке, без эффекта (правило хуков)
  const [seenOpen, setSeenOpen] = useState<number>(0)
  if (open && open.k !== seenOpen && model) {
    setSeenOpen(open.k)
    c.select(open.n)
  }

  useEffect(() => {
    const ctl = new AbortController()
    chart.get(pid, ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setGot({ pid, model: r.data, failed: false }) },
      (e: unknown) => { if (!ctl.signal.aborted) { setGot({ pid, model: null, failed: true }); onFail(asApiError(e)) } },
    )
    return () => ctl.abort()
  }, [pid, onFail])

  const base = `/admin/patient/${pid}`
  if (failed) {
    return (
      <div className="fcard">
        <p className="hint dp-m0">{T.failed} <a href={`${base}/odontograma`}>{T.open}</a></p>
      </div>
    )
  }
  if (!model) return <div className="fcard dp-odo-wait" aria-busy="true"><p className="hint dp-m0">{T.loading}</p></div>

  return (
    <>
      <div className="fcard odo" id="odo" data-view={c.view}>
        <div className="odo-head">
          <h3>{T.title} <small>· {T.sub}</small></h3>
          <div className="odo-actions">
            <ViewSwitch view={c.view} onChange={c.setView} />
            <a className="odo-more" href={`${base}/parodontograma`}><Icon name="tooth" /> {T.perio}</a>
            <a className="odo-more" href={`${base}/odontograma`}><Icon name="eye" /> {T.detail}</a>
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
        formKey={c.formKey}
        sel={c.sel}
        onSel={c.setSel}
        onSave={(n, body) => { void c.saveTooth(n, body).then((ok) => { if (ok) c.select(null) }) }}
        onClose={() => c.select(null)}
      />
    </>
  )
}
