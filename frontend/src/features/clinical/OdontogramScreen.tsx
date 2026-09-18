import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { BridgeBar, BridgeDialog } from './BridgeTool'
import { DentalArch } from './DentalArch'
import { ToothInspector } from './ToothInspector'
import { ToothMenu, type MenuAt } from './ToothMenu'
import { ViewSwitch } from './ViewSwitch'
import { chart, neighbour, type Arrow } from './chart'
import { useChart } from './useChart'

/* Детальная одонтограмма (C21): дуга крупно + постоянный инспектор справа,
   режим «Punte nouă» — та же раскладка и классы, что у старой страницы
   (.odop, .odop-top, .odop-grid, .odop-side). Сайдбар узкий — рамку с
   rail=True даёт сервер.

   C22 — клавиатура ТОЛЬКО когда карта в фокусе (контейнер .odop с
   tabIndex): стрелки — соседний зуб / другая челюсть, M O D V L —
   поверхность, P — алиас L на верхней челюсти, Enter — записать черновик,
   Esc — сброс черновика (в режиме моста — выход из него). ⛔ Внутри
   input/textarea/select и при открытом диалоге клавиши — браузерные: Enter
   там зуб не сохраняет. Enter и стрелки гасятся (preventDefault), иначе
   Enter на кнопке зуба в фокусе кликнул бы её же. */
const T = {
  title: 'Odontogramă',
  sub: 'notație FDI',
  newBridge: 'Punte nouă',
  perio: 'Parodontogramă',
  print: 'Printează',
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

const FIELD = new Set(['INPUT', 'TEXTAREA', 'SELECT'])
const LETTERS = new Set(['M', 'O', 'D', 'V', 'L'])
const ARROWS = new Set<string>(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'])

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
  const [menu, setMenu] = useState<MenuAt | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  const root = useRef<HTMLDivElement>(null)

  const focusTooth = useCallback((n: number) => {
    root.current?.querySelector<HTMLElement>(`.arch .tooth-btn[data-n="${n}"]`)?.focus()
  }, [])
  // зуб из адреса — в фокус, как только дуга нарисована: клавиатура работает сразу
  const ready = model !== null
  useEffect(() => { if (ready && t !== null) focusTooth(t) }, [ready, t, focusTooth])

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
  const bridgeFrom = (n: number) => { setMenu(null); setBrMode(true); setPicked([n]); setBrOpen(false) }
  const onMenu = (n: number, e: MouseEvent<HTMLButtonElement>) => {
    if (brMode) return
    setMenu({ n, x: e.clientX, y: e.clientY })
  }
  const menuState = (n: number, st: string) => { c.setState(n, st); setMenu(null); focusTooth(n) }

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return
    const el = e.target as HTMLElement
    if (FIELD.has(el.tagName) || el.isContentEditable) return
    if (document.querySelector('dialog[open]')) return
    if (menu) {
      setMenu(null)
      if (e.key === 'Escape') { e.preventDefault(); return }
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      if (brMode) stopBridge()
      else if (c.dirty) c.discard()
      return
    }
    if (brMode) return
    if (e.key === 'Enter') {
      if (c.selected === null) return
      e.preventDefault()
      if (c.dirty && !c.busy) void c.save()
      return
    }
    if (ARROWS.has(e.key)) {
      e.preventDefault()
      const to = neighbour(model, c.selected, e.key as Arrow)
      if (to !== null) { c.select(to); focusTooth(to) }
      return
    }
    if (!c.info || e.key.length !== 1) return
    const L = e.key.toUpperCase()
    if (L === 'P') {
      if (c.info.jaw === 'sus') { e.preventDefault(); c.setSel('L') }
      return
    }
    if (LETTERS.has(L) && L in model.surfaces) { e.preventDefault(); c.setSel(L) }
  }

  const menuInfo = menu ? model.teeth[String(menu.n)] : undefined
  const menuCurrent = menu && menu.n === c.selected && c.draft ? c.draft.state : (menuInfo?.state ?? '')

  return (
    <section className="dp-react-root">
      <div ref={root} className="odop odo" id="odo" data-view={c.view} tabIndex={0} onKeyDown={onKey}>
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
                dirty={c.dirtyTeeth}
                onSelect={onSelect}
                onSurface={onSurface}
                onMenu={onMenu}
              />
            </div>
          </div>
          <aside className="odop-side">
            <ToothInspector
              model={model}
              n={c.selected}
              view={c.view}
              busy={c.busy}
              sel={c.sel}
              onSel={c.setSel}
              onSurface={c.pickSurface}
              draft={c.draft}
              dirty={c.dirty}
              onEdit={c.edit}
              onSave={() => { void c.save() }}
              onDiscard={c.discard}
              onDelBridge={(bid) => { void c.delBridge(bid) }}
              onBridgeFrom={bridgeFrom}
            />
          </aside>
        </div>
      </div>
      {menu && (
        <ToothMenu model={model} at={menu} current={menuCurrent} onState={menuState} onBridge={bridgeFrom} onClose={closeMenu} />
      )}
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
