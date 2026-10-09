import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { ToastState } from '../../components/Toast'
import { asApiError } from '../../services/api'
import { BridgeBar, BridgeDialog } from './BridgeTool'
import { DentalArch } from './DentalArch'
import { LegendFilter } from './LegendFilter'
import { PlanDialog } from './PlanDialog'
import { ToothMap } from './ToothMap'
import { ToothMenu, type MenuAt } from './ToothMenu'
import { ToothPanel } from './ToothPanel'
import { chart, dimmedTeeth, legendCounts, neighbour, shownTeeth, type Arrow, type Odontogram, type PlanAdd } from './chart'
import { Odontogram3D, type Mode } from './three/Odontogram3D'
import { useCoarse } from './touch'
import { useChart } from './useChart'

/* Рабочий стол одонтограммы (C21–C22; с 26.09 ОДИН на два места): вьюпорт
   (3D или рисунки сервера) с легендой-фильтром, карта зубов и постоянная
   панель зуба справа, режим «Punte nouă», меню зуба, клавиатура. Детальная
   страница `/odontograma` показывает его на всю ширину (сайдбар-рельс даёт
   сервер), вкладка Odontogramă фиши — внутри рабочего места (B6, шаг 2):
   инструмент один, а не «компактный» и «детальный» с разными возможностями.

   Вид — по макету Олега (08.10, design/redesign-2026-10, промпт 3): вкладки
   «Stare dinți | Parodont» и счётчик записанных зубов в шапке; карточка
   вьюпорта (полоса видов и зума, слои слева, сцена, легенда чипами); новая
   карточка «Harta dinților» — плоская карта кнопками, тот же выбор, что в
   сцене; панель зуба — `ToothPanel`. Рисунки сервера (frontal / ocluzal)
   остались за кнопкой «2D» в той же полосе. Логика, API и движок не
   менялись: `useChart`, `scene.ts` (плюс один метод зума).

   C22 — клавиатура ТОЛЬКО когда карта в фокусе (контейнер .odop с
   tabIndex): стрелки — соседний зуб / другая челюсть, M O D V L —
   поверхность, P — алиас L на верхней челюсти, Enter — записать черновик,
   Esc — сброс черновика (в режиме моста — выход из него). ⛔ Внутри
   input/textarea/select и при открытом диалоге клавиши — браузерные: Enter
   там зуб не сохраняет. Enter и стрелки гасятся (preventDefault), иначе
   Enter на кнопке зуба в фокусе кликнул бы её же.

   «Adaugă în plan» (01.10) — из меню зуба и из панели: диалог с номером
   зуба шлёт позицию на маршрут плана фиши; в ответе приходит СВЕЖАЯ ФИША, и
   она уходит владельцу (`onCard`) — вкладка фиши подменяет ею карту, как после
   записи зуба; детальной странице и креслу фиша не нужна, им хватает плашки.
   ⛔ Не через `useChart.act`: тот подменяет ответом МОДЕЛЬ одонтограммы.

   Фокус камеры 3D (01.10): `zoom` — режим «камера у выбранного зуба»; пока он
   включён, выбор другого зуба везёт камеру к нему. F / кнопка камеры —
   переключатель, двойной щелчок по зубу — выбрать и подъехать, кнопка вида —
   выход. В 2D и в режиме моста фокуса нет.

   Легенда-фильтр (01.10): легенда общая для 2D, 3D и карты и стоит под
   вьюпортом; нажатый пункт гасит зубы не про него (`dimmedTeeth` — классом
   на дуге и карте, прозрачностью в сцене), счётчик у пункта — сколько зубов
   про него. Фильтр — экрана: в модель, в запись и в печать 043/e он не
   попадает. */
const T = {
  stare: 'Stare dinți',
  paro: 'Parodont',
  modes: 'Ce arată vederea',
  paroNone: 'Pacientul nu are încă o parodontogramă cu măsurători',
  paroTitle: 'Parodontograma din {at} pe gingie: recesiune, pungi, sângerare',
  recorded: 'dinți cu stare înregistrată',
  back: 'Înapoi la fișă',
  newBridge: 'Punte nouă',
  perio: 'Parodontogramă',
  full: 'Pe tot ecranul',
  print: 'Printează',
  views: 'Vedere',
  frontal: 'Vedere frontală',
  ocluzal: 'Vedere ocluzală',
  three: '3D',
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
  /** внутри фиши: без обратной ссылки, со ссылкой «Pe tot ecranul» */
  embedded?: boolean
  /** режим ленты фиши (`?views=1`) — едет в запрос позиции плана, как в запись зуба */
  views?: boolean
  /** свежая фиша из ответа «Adaugă în plan» — владельцу, который её показывает */
  onCard?: (card: unknown) => void
}

/** Сколько зубов на экране с записанной находкой: состояние, поверхность или
 *  отметка. Подпись шапки, не клиническая величина. */
function recordedCount(model: Odontogram): number {
  return shownTeeth(model).filter((n) => {
    const t = model.teeth[String(n)]
    return Boolean(t && (t.state !== 'ok' || Object.keys(t.sfst).length > 0 || t.mk.length > 0))
  }).length
}

export function OdontogramWorkbench({
  pid, model, replace, fail, say, initial = null, saveQuery = '', open = null, embedded = false,
  views = false, onCard,
}: Props) {
  const c = useChart(pid, model, replace, fail, say, initial, saveQuery)
  const [brMode, setBrMode] = useState(false)
  const [picked, setPicked] = useState<number[]>([])
  const [brOpen, setBrOpen] = useState(false)
  const [menu, setMenu] = useState<MenuAt | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  const root = useRef<HTMLDivElement>(null)
  /* зуб → план: диалог открыт для зуба `plan`; занятость и виновное поле — свои,
     черновик зуба при этом не трогается */
  const [plan, setPlan] = useState<number | null>(null)
  const [planBusy, setPlanBusy] = useState(false)
  const [planBad, setPlanBad] = useState(false)
  const planFrom = (n: number) => { setMenu(null); setPlanBad(false); setPlan(n) }
  const [zoom, setZoom] = useState(false)
  const focus3d = zoom && !brMode && c.view === '3d' ? c.selected : null
  const [filter, setFilter] = useState<string | null>(null)
  /* вкладка страницы: «Parodont» живёт в 3D — слой осмотра на десне */
  const [mode, setMode] = useState<Mode>('stare')
  const layer = model.perio_layer ?? null
  const paroOn = mode === 'paro' && c.view === '3d' && layer !== null
  const legendItems = c.view === 'ocluzal' ? model.legend.occlusal : model.legend.frontal
  const dim = useMemo(() => dimmedTeeth(model, filter), [model, filter])
  const counts = useMemo(() => legendCounts(model, legendItems), [model, legendItems])
  const recorded = useMemo(() => recordedCount(model), [model])
  const pickLegend = (k: string) => setFilter((f) => (f === k ? null : k))
  const onDouble = (n: number) => { if (!brMode) { c.select(n); setZoom(true) } }
  const closePlan = useCallback(() => setPlan(null), [])
  /* «Salvat pentru dintele N» — зуб последней удачной записи; живёт до
     следующей правки (dirty) и показывается только на нём */
  const [savedN, setSavedN] = useState<number | null>(null)
  const doSave = async () => {
    const n = c.selected
    const ok = await c.save()
    if (ok) setSavedN(n)
  }
  const savePlan = async (body: PlanAdd): Promise<boolean> => {
    setPlanBusy(true)
    setPlanBad(false)
    try {
      const r = await chart.addPlan(pid, body, views ? '?views=1' : '')
      if (r.text) say({ tone: r.tone, text: r.text })
      onCard?.(r.data)
      setPlan(null)
      return true
    } catch (e) {
      const err = asApiError(e)
      if (err.field) setPlanBad(true)
      fail(err)
      return false
    } finally {
      setPlanBusy(false)
    }
  }

  /* кнопка зуба — на дуге (2D) или на карте (всегда): первая видимая в документе */
  const focusTooth = useCallback((n: number) => {
    root.current?.querySelector<HTMLElement>(`.arch .tooth-btn[data-n="${n}"], .dp-tm-btn[data-n="${n}"]`)?.focus()
  }, [])
  // зуб из адреса — в фокус, как только карта нарисована: клавиатура работает сразу
  useEffect(() => { if (initial !== null) focusTooth(initial) }, [initial, focusTooth])
  // просьба открыть зуб применяется один раз на метку — при отрисовке, без
  // эффекта (правило хуков); фокус — следом, эффектом
  const [seenOpen, setSeenOpen] = useState(0)
  if (open && open.k !== seenOpen) {
    setSeenOpen(open.k)
    c.select(open.n)
  }
  useEffect(() => { if (open) focusTooth(open.n) }, [open, focusTooth])

  /* B7 · планшет: пальцем панель — шторка снизу (портрет) или панель справа
     (альбом), поверх карты. Выбранный зуб прокручивается в видимую часть: в
     портрете — над шторкой (она до 56 % высоты). Мышью ничего не меняется. */
  const coarse = useCoarse()
  const sel = c.selected
  /* в альбоме панель ложится ПОВЕРХ карты с той стороны, где выбранного зуба нет */
  const [side, setSide] = useState<'left' | 'right'>('right')
  useEffect(() => {
    if (!coarse || sel === null) return
    const el = root.current?.querySelector<HTMLElement>(`.arch .tooth-btn[data-n="${sel}"], .dp-tm-btn[data-n="${sel}"]`)
    if (!el) return
    const r = el.getBoundingClientRect()
    const box = (root.current?.querySelector('.odop-main') ?? root.current)?.getBoundingClientRect()
    if (box) setSide(r.left + r.width / 2 < box.left + box.width / 2 ? 'right' : 'left')
    const portrait = window.innerHeight > window.innerWidth
    const bottom = portrait ? window.innerHeight * 0.44 : window.innerHeight
    const top = 72
    if (r.top >= top && r.bottom <= bottom - 8) return
    const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollBy({ top: r.top - Math.max(top, (bottom - r.height) / 2), behavior: reduced ? 'auto' : 'smooth' })
  }, [coarse, sel])

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
  /* меню зуба у точки: правая кнопка мыши, долгое нажатие пальцем — на карте, дуге и в 3D */
  const onMenu = (n: number, x: number, y: number) => {
    if (brMode) return
    setMenu({ n, x, y })
  }
  const menuState = (n: number, st: string) => { c.setState(n, st); setMenu(null); focusTooth(n) }
  const menuMark = (n: number, mk: string) => { c.toggleMark(n, mk); setMenu(null); focusTooth(n) }

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
      if (c.dirty && !c.busy) void doSave()
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
    if (L === 'F') {
      if (c.view === '3d') { e.preventDefault(); setZoom((z) => !z) }
      return
    }
    if (L === 'P') {
      if (c.info.jaw === 'sus') { e.preventDefault(); c.setSel('L') }
      return
    }
    if (LETTERS.has(L) && L in model.surfaces) { e.preventDefault(); c.setSel(L) }
  }

  const menuInfo = menu ? model.teeth[String(menu.n)] : undefined
  const menuCurrent = menu && menu.n === c.selected && c.draft ? c.draft.state : (menuInfo?.state ?? '')
  const menuMarks = menu && menu.n === c.selected && c.draft ? c.draft.marks : (menuInfo?.mk ?? [])
  const pickedSet = new Set(picked)

  return (
    <>
      <div ref={root} className="odop odo dp-odo" id="odo" data-view={c.view} data-sel={c.selected ?? undefined} data-side={side} tabIndex={0} onKeyDown={onKey}>
        <div className="dp-odo-head">
          <div className="dp-tabs" role="group" aria-label={T.modes}>
            <button type="button" data-mode="stare" className={`dp-tab${paroOn ? '' : ' on'}`} aria-pressed={!paroOn}
              onClick={() => setMode('stare')}>{T.stare}</button>
            <button type="button" data-mode="paro" className={`dp-tab${paroOn ? ' on' : ''}`} aria-pressed={paroOn}
              disabled={layer === null}
              title={layer ? T.paroTitle.replace('{at}', layer.exam.at) : T.paroNone}
              onClick={() => { if (c.view !== '3d') c.setView('3d'); setMode('paro') }}>{T.paro}</button>
          </div>
          <div className="dp-odo-headr">
            <span className="dp-odo-count"><b>{recorded}</b> {T.recorded}</span>
            {!embedded && (
              <AppLink className="dp-odo-lnk" href={`${base}?tab=odonto`} title={T.back}><Icon name="pat" /> {model.patient.name}</AppLink>
            )}
            <button type="button" className="dp-odo-lnk" onClick={() => { setBrMode(true); setPicked([]) }}>
              <Icon name="plus" /> {T.newBridge}
            </button>
            {/* «Parodontogramă» здесь снята (09.10, разбор): к листу ведут вкладка
                фиши и режим «Parodont» выше — третий вход только путал. */}
            {embedded && <AppLink className="dp-odo-lnk" href={`${base}/odontograma`}><Icon name="eye" /> {T.full}</AppLink>}
            <button type="button" className="dp-ibtn" aria-label={T.print} title={T.print} onClick={() => window.print()}><Icon name="print" /></button>
          </div>
        </div>
        <BridgeBar model={model} active={brMode} picked={picked} onCancel={stopBridge} onContinue={() => setBrOpen(true)} />
        <div className="odop-grid dp-odo-cols">
          <div className="odop-main dp-odo-main">
            <div className="dp-card dp-vp">
              {c.view === '3d' ? (
                /* B7: объёмный вид — тот же контроллер, те же действия; выбор,
                   поверхность и меню идут в панель, как из карты */
                <Odontogram3D model={model} selected={brMode ? null : c.selected} onSurface={onSurface} onMenu={onMenu}
                  focus={focus3d} onZoom={setZoom} onDouble={onDouble} dim={dim} mode={mode}
                  onFlat={() => c.setView('frontal')} />
              ) : (
                <>
                  <div className="dp-vp-bar">
                    <div className="dp-seg dp-views" role="group" aria-label={T.views}>
                      {(['frontal', 'ocluzal'] as const).map((v) => (
                        <button key={v} type="button" data-v={v} className={c.view === v ? 'on' : ''} aria-pressed={c.view === v}
                          onClick={() => c.setView(v)}>{T[v]}</button>
                      ))}
                      <span className="dp-seg-sep" />
                      <button type="button" data-v="3d" aria-pressed={false} onClick={() => c.setView('3d')}>{T.three}</button>
                    </div>
                  </div>
                  <div className="dp-vp-body dp-vp-2d">
                    <DentalArch
                      model={model}
                      view={c.view}
                      selected={brMode ? null : c.selected}
                      picked={pickedSet}
                      dirty={c.dirtyTeeth}
                      dim={dim}
                      onSelect={onSelect}
                      onSurface={onSurface}
                      onMenu={onMenu}
                    />
                  </div>
                </>
              )}
              <div className="tleg dp-vp-legend" data-filter={filter ?? undefined}>
                <LegendFilter items={legendItems} palette={model.palette} active={filter} counts={counts} onPick={pickLegend} />
              </div>
            </div>
            <ToothMap model={model} selected={brMode ? null : c.selected} picked={pickedSet} dirty={c.dirtyTeeth}
              dim={dim} onSelect={onSelect} onMenu={onMenu} />
          </div>
          <aside className="odop-side dp-odo-side">
            <ToothPanel
              model={model}
              n={c.selected}
              busy={c.busy}
              sel={c.sel}
              onSurface={onSurface}
              draft={c.draft}
              dirty={c.dirty}
              onEdit={c.edit}
              onSave={() => { void doSave() }}
              onDiscard={c.discard}
              onDelBridge={(bid) => { void c.delBridge(bid) }}
              onBridgeFrom={bridgeFrom}
              onPlan={planFrom}
              onClose={() => { c.discard(); c.select(null) }}
              saved={savedN}
            />
          </aside>
        </div>
      </div>
      {menu && (
        <ToothMenu model={model} at={menu} current={menuCurrent} onState={menuState} marks={menuMarks} onMark={menuMark}
          onPlan={planFrom} onBridge={bridgeFrom} onClose={closeMenu} />
      )}
      <PlanDialog model={model} n={plan} busy={planBusy} invalid={planBad} onClose={closePlan} onSave={savePlan} />
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
