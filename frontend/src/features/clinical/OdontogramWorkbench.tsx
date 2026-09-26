import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { ToastState } from '../../components/Toast'
import { BridgeBar, BridgeDialog } from './BridgeTool'
import { DentalArch } from './DentalArch'
import { ToothInspector } from './ToothInspector'
import { ToothMenu, type MenuAt } from './ToothMenu'
import { ViewSwitch } from './ViewSwitch'
import { neighbour, type Arrow, type Odontogram } from './chart'
import { useChart } from './useChart'

/* Рабочий стол одонтограммы (C21–C22; с 26.09 ОДИН на два места): дуга крупно +
   постоянный инспектор справа, режим «Punte nouă», меню зуба, клавиатура —
   раскладка и классы старой страницы (.odop, .odop-top, .odop-grid, .odop-side).
   Детальная страница `/odontograma` показывает его на всю ширину (сайдбар-рельс
   даёт сервер), вкладка Odontogramă фиши — внутри рабочего места (B6, шаг 2):
   инструмент один, а не «компактный» и «детальный» с разными возможностями.

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
  full: 'Pe tot ecranul',
  print: 'Printează',
} as const

const FIELD = new Set(['INPUT', 'TEXTAREA', 'SELECT'])
const LETTERS = new Set(['M', 'O', 'D', 'V', 'L'])
const ARROWS = new Set<string>(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'])

interface Props {
  pid: number
  model: Odontogram
  replace: (m: Odontogram) => void
  fail: (e: unknown) => void
  say: (t: ToastState) => void
  /** зуб в фокус с первого кадра — адрес `?t=` детальной страницы */
  initial?: number | null
  /** хвост адреса записи зуба: фиша просит им себя в ответ (`?card=1&views=1`) */
  saveQuery?: string
  /** просьба открыть зуб снаружи (номер в плане) — объект с меткой, чтобы
      повторный клик по тому же зубу тоже сработал */
  open?: { n: number; k: number } | null
  /** внутри фиши: без обратной ссылки и заголовка, со ссылкой «Pe tot ecranul» */
  embedded?: boolean
}

export function OdontogramWorkbench({
  pid, model, replace, fail, say, initial = null, saveQuery = '', open = null, embedded = false,
}: Props) {
  const c = useChart(pid, model, replace, fail, say, initial, saveQuery)
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
  useEffect(() => { if (initial !== null) focusTooth(initial) }, [initial, focusTooth])
  // просьба открыть зуб применяется один раз на метку — при отрисовке, без
  // эффекта (правило хуков); фокус — следом, эффектом
  const [seenOpen, setSeenOpen] = useState(0)
  if (open && open.k !== seenOpen) {
    setSeenOpen(open.k)
    c.select(open.n)
  }
  useEffect(() => { if (open) focusTooth(open.n) }, [open, focusTooth])

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
    <>
      <div ref={root} className="odop odo" id="odo" data-view={c.view} tabIndex={0} onKeyDown={onKey}>
        <div className="odop-top">
          {!embedded && (
            <AppLink className="odop-back" href={`${base}?tab=odonto`}><Icon name="pat" /> {model.patient.name}</AppLink>
          )}
          {!embedded && <h2>{T.title} <small>· {T.sub}</small></h2>}
          <div className="odo-actions">
            <ViewSwitch view={c.view} onChange={c.setView} />
            <button type="button" className="odo-more" onClick={() => { setBrMode(true); setPicked([]) }}>
              <Icon name="plus" /> {T.newBridge}
            </button>
            <AppLink className="odo-more" href={`${base}/parodontograma`}><Icon name="tooth" /> {T.perio}</AppLink>
            {embedded && <AppLink className="odo-more" href={`${base}/odontograma`}><Icon name="eye" /> {T.full}</AppLink>}
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
    </>
  )
}
