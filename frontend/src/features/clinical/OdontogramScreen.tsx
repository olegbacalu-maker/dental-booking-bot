import { useCallback, useState } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { BridgeBar, BridgeDialog } from './BridgeTool'
import { DentalArch } from './DentalArch'
import { ToothInspector } from './ToothInspector'
import { ViewSwitch } from './ViewSwitch'
import { chart } from './chart'
import { useChart } from './useChart'

/* Детальная одонтограмма (C21): дуга крупно + постоянный инспектор справа,
   режим «Punte nouă» — та же раскладка и классы, что у старой страницы
   (.odop, .odop-top, .odop-grid, .odop-side). Сайдбар узкий — рамку с
   rail=True даёт сервер. */
const T = {
  title: 'Odontogramă',
  sub: 'notație FDI',
  newBridge: 'Punte nouă',
  perio: 'Parodontogramă',
  print: 'Printează',
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  pid: number
  /** Зуб из адреса (?t=): выбор переживает перезагрузку. */
  t?: number | null
  navigate?: (url: string) => void
}

export function OdontogramScreen({ pid, t = null, navigate = defaultNavigate }: Props) {
  const load = useCallback((signal: AbortSignal) => chart.get(pid, signal), [pid])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const say = useCallback((x: ToastState) => setToast(x), [])
  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])
  const model = state.status === 'ready' ? state.data : null
  const c = useChart(pid, model, replace, fail, say, t)
  const [brMode, setBrMode] = useState(false)
  const [picked, setPicked] = useState<number[]>([])
  const [brOpen, setBrOpen] = useState(false)

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }
  if (!model) return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>

  const base = `/admin/patient/${pid}`
  const onSelect = (n: number) => {
    if (brMode) {
      if (n > 50) return                    // молочных мостов не бывает (врач, 08-21)
      setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]))
      return
    }
    c.select(n)
  }
  const onSurface = (n: number, letter: string) => {
    if (brMode) { onSelect(n); return }
    c.pickSurface(n, letter)
  }
  const stopBridge = () => { setBrMode(false); setPicked([]); setBrOpen(false) }

  return (
    <section className="dp-react-root">
      <div className="odop odo" id="odo" data-view={c.view}>
        <div className="odop-top">
          <a className="odop-back" href={base}><Icon name="pat" /> {model.patient.name}</a>
          <h2>{T.title} <small>· {T.sub}</small></h2>
          <div className="odo-actions">
            <ViewSwitch view={c.view} onChange={c.setView} />
            <button type="button" className="odo-more" onClick={() => { setBrMode(true); setPicked([]) }}>
              <Icon name="plus" /> {T.newBridge}
            </button>
            <a className="odo-more" href={`${base}/parodontograma`}><Icon name="tooth" /> {T.perio}</a>
            <button type="button" className="odo-more" onClick={() => window.print()}><Icon name="print" /> {T.print}</button>
          </div>
        </div>
        <BridgeBar model={model} active={brMode} picked={picked} onCancel={stopBridge} onContinue={() => setBrOpen(true)} />
        <div className="odop-grid">
          <div className="odop-main">
            <div className="fcard">
              <DentalArch
                model={model}
                view={c.view}
                selected={brMode ? null : c.selected}
                picked={new Set(picked)}
                onSelect={onSelect}
                onSurface={onSurface}
              />
            </div>
          </div>
          <aside className="odop-side">
            <ToothInspector
              model={model}
              n={c.selected}
              view={c.view}
              busy={c.busy}
              formKey={c.formKey}
              sel={c.sel}
              onSel={c.setSel}
              onSave={(n, body) => { void c.saveTooth(n, body) }}
              onDelBridge={(bid) => { void c.delBridge(bid) }}
            />
          </aside>
        </div>
      </div>
      <BridgeDialog
        model={model}
        open={brOpen}
        picked={picked}
        busy={c.busy}
        onClose={() => setBrOpen(false)}
        onSave={async (body) => { const ok = await c.addBridge(body); if (ok) stopBridge(); return ok }}
      />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
