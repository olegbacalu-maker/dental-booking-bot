import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { shellOn, useCommand } from '../../app/bridge'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import type { ToastState } from '../../components/Toast'
import { defaultReload } from '../../hooks/useLive'
import { asApiError } from '../../services/api'
import { BridgeBar, BridgeDialog } from './BridgeTool'
import { DentalArch } from './DentalArch'
import { LegendFilter } from './LegendFilter'
import { ModeTabs } from './ModeTabs'
import { PlanDialog } from './PlanDialog'
import { ToothMap } from './ToothMap'
import { ToothMenu, type MenuAt } from './ToothMenu'
import { ToothPanel } from './ToothPanel'
import { chart, legendCounts, modeSet, neighbour, screenDim, shownTeeth, type Arrow, type Odontogram, type PlanAdd } from './chart'
import { Odontogram3D, type Mode } from './three/Odontogram3D'
import { unsavedTeeth, useChart } from './useChart'

/* Рабочий стол одонтограммы (C21–C22; с 26.09 ОДИН на два места): вьюпорт
   (3D или рисунки сервера) с легендой-фильтром, карта зубов и постоянная
   панель зуба справа, режим «Punte nouă», меню зуба, клавиатура. Детальная
   страница `/odontograma` показывает его на всю ширину (сайдбар-рельс даёт
   сервер), вкладка Odontogramă фиши — внутри рабочего места (B6, шаг 2):
   инструмент один, а не «компактный» и «детальный» с разными возможностями.

   Раскладка B (Олег 24.10 «da давай вариант B», волна 2 — 25.10; макет и
   замеры — design/odonto-redesign, кадры — design/odonto-layout): рабочий
   стол = высота окна, страница не прокручивается. Шапка — ОДНОЙ строкой: имя
   пациента (ссылка в фишу; на детальной странице оно и есть заголовок —
   `h1` оболочки снимает CSS по `data-page`), режимы вкладками, справа
   значки «Punte nouă» / «Pe tot ecranul» / печать (подписи — на широком окне).
   Под шапкой две колонки: слева ряд зубов «Harta dinților» НАД сценой и
   карточка вьюпорта (сцена во всю карточку, виды/зум/слои — плашками поверх,
   легенда чипами внизу), справа панель зуба (`ToothPanel`) 360 px, 400 на
   ≥1700; панель прокручивается сама, «Salvează» внизу видна всегда. Рисунки
   сервера (frontal / ocluzal) — за кнопкой «2D». Планшет: в альбоме панель —
   той же колонкой, в портрете — шторка снизу, и рабочий стол на это время
   ужимается над ней (сцена не уходит под шторку). Логика, API и движок не
   менялись: `useChart`, `scene.ts`.

   C22 — клавиатура ТОЛЬКО когда карта в фокусе (контейнер .odop с
   tabIndex): стрелки — соседний зуб / другая челюсть, M O D V L —
   поверхность, P — алиас L на верхней челюсти, Enter — записать черновик,
   Esc — сброс черновика (в режиме моста — выход из него). С волны 2
   (25.10) Enter пишет черновики ВСЕХ зубов — то же, что «Salvează tot». ⛔ Внутри
   input/textarea/select и при открытом диалоге клавиши — браузерные: Enter
   там зуб не сохраняет. Enter и стрелки гасятся (preventDefault), иначе
   Enter на кнопке зуба в фокусе кликнул бы её же.

   «Adaugă în plan» (01.10) — из меню зуба и из панели: диалог с номером
   зуба шлёт позицию на маршрут плана фиши с `?odo=1` (24.10), и в ответе
   приходит СВЕЖАЯ МОДЕЛЬ одонтограммы — план зуба во вкладке «Tratament»
   панели сразу с позицией, без перечитывания. Хвост адреса — тот же, что у
   записи зуба (`saveQuery`): фиша просит им себя (`card`), и владелец
   (`replace`) отдаёт её наверх, как после записи зуба. Занятость и виновное
   поле у диалога свои: черновик зуба запись плана не трогает.

   Фокус камеры 3D (01.10): `zoom` — режим «камера у выбранного зуба»; пока он
   включён, выбор другого зуба везёт камеру к нему. F / кнопка камеры —
   переключатель, двойной щелчок по зубу — выбрать и подъехать, кнопка вида —
   выход. В 2D и в режиме моста фокуса нет.

   Легенда-фильтр (01.10): легенда общая для 2D, 3D и карты и стоит под
   вьюпортом; нажатый пункт гасит зубы не про него (`dimmedTeeth` — классом
   на дуге и карте, прозрачностью в сцене), счётчик у пункта — сколько зубов
   про него. Фильтр — экрана: в модель, в запись и в печать 043/e он не
   попадает.

   Режимы (Олег 24.10, макет B): вкладки шапки `ModeTabs` по словарю сервера
   `model.modes` — Examinare (всё видно, прежнее «Stare dinți»), Carii,
   Restaurare, Endodonție, Parodonțiu (прежний «Parodont»: слой осмотра на
   десне, живёт в 3D), Chirurgie, Implant, Proteză. Режим ЗАДАЁТ набор зубов —
   всё вне его гаснет тем же `dim`, что у легенды; легенда СУЖАЕТ внутри
   набора, и её счётчики считают внутри него (`screenDim`, `legendCounts`).
   Выбор режима снимает фильтр легенды: иначе «Carii» поверх нажатой
   «Coroană» гасил бы всё, и непонятно почему. Меню зуба ставит пункты
   режима первыми. Режим не запоминается (как и легенда) и, как она, —
   свойство экрана: в запись, 043/e и печать не попадает.

   Черновик до записи (волна 2, Олег 25.10: «сначала всю работу и потом
   сохранить … напомнить, что не было сделано сохранение»): виды — сцена,
   дуга, карта — и гашение режима и легенды рисуют `c.shown` (сохранённое +
   предпросмотр черновиков сервера, см. `useChart`); панель, меню, диалоги и
   счётчик «înregistrată» — сохранённую модель. Несохранённое охраняется:
   - уход адресом и смена вкладки фиши — блокер ВЛАДЕЛЬЦА (`onDirty` наверх):
     роутер держит один блокер, и второй здесь молча выключил бы вопрос
     анамнеза фиши;
   - F5 и «Reîncarcă» в окне оболочки — команда страницы (`act:reload`): её
     заявляет рабочий стол и спрашивает своим окном; `beforeunload` — только
     без оболочки (браузер второго ПК, телефон): переходы самой оболочки
     (прятание к часам на общем ПК) будить диалогом нельзя;
   - печать при черновиках — через вопрос «Salvează și tipărește»: иначе на
     бумагу ушло бы несохранённое как записанное.
   Фокус на кнопку зуба — без прокрутки (`preventScroll`): выбор в сцене или
   меню уводил страницу к «Harta dinților» (Олег 25.10: «экран прыгает на
   зуб»; 14.10: без прыжков страницы). */
const T = {
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
  reload: 'Reîncărcați pagina fără să le salvați?',
  reloadOk: 'Reîncarcă',
  printAsk: 'Pe foaie ajunge doar ce e salvat. Salvați acum și tipăriți?',
  printOk: 'Salvează și tipărește',
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
  /** Зубы с несохранённой правкой — владельцу для вопроса при уходе (у роутера
   *  один блокер на всех); при снятии рабочего стола — пустой список. */
  onDirty?: ((teeth: number[]) => void) | undefined
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
  pid, model, replace, fail, say, initial = null, saveQuery = '', open = null, embedded = false, onDirty,
}: Props) {
  const c = useChart(pid, model, replace, fail, say, initial, saveQuery)
  /* что рисуют виды: сохранённое + черновики в предпросмотре сервера */
  const shown = c.shown ?? model
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
  /* режим экрана: с «всё видно»; «Parodonțiu» живёт в 3D и только при осмотре —
     в 2D (или без осмотра) экран показывает «всё видно», как прежний «Parodont» */
  const modes = model.modes ?? []
  const allMode = modes.find((m) => m.kind === 'all') ?? null
  const [modeKey, setModeKey] = useState(() => allMode?.key ?? '')
  const layer = model.perio_layer ?? null
  const chosen = modes.find((m) => m.key === modeKey) ?? allMode
  const mode = chosen?.kind === 'perio' && !(c.view === '3d' && layer) ? allMode : chosen
  const scene: Mode = mode?.kind === 'perio' ? 'paro' : 'stare'
  const legendItems = c.view === 'ocluzal' ? model.legend.occlusal : model.legend.frontal
  const dim = useMemo(() => screenDim(shown, mode, filter), [shown, mode, filter])
  const counts = useMemo(() => legendCounts(shown, legendItems, modeSet(shown, mode)), [shown, legendItems, mode])
  const recorded = useMemo(() => recordedCount(model), [model])
  const pickLegend = (k: string) => setFilter((f) => (f === k ? null : k))
  const pickMode = (k: string) => {
    const m = modes.find((x) => x.key === k)
    if (!m || (m.kind === 'perio' && !layer)) return
    if (m.kind === 'perio' && c.view !== '3d') c.setView('3d')
    setModeKey(k)
    setFilter(null)
  }
  const onDouble = (n: number) => { if (!brMode) { c.select(n); setZoom(true) } }
  const closePlan = useCallback(() => setPlan(null), [])
  /* «Salvat: dinții …» — зубы последней удачной записи; строка живёт, пока
     нет новых черновиков */
  const [savedN, setSavedN] = useState<number[] | null>(null)
  const doSave = async (): Promise<boolean> => {
    const ns = await c.saveAll()
    if (ns) setSavedN(ns)
    return ns !== null
  }
  /* печать при черновиках: экран рисует несохранённое, и бумага выдала бы его
     за записанное — сперва запись, печать после того, как экран её отрисовал */
  const printChart = async () => {
    if (c.pending.length) {
      if (!await ask({ text: `${unsavedTeeth(c.pending)} ${T.printAsk}`, ok: T.printOk })) return
      if (!await doSave()) return
      await new Promise<void>((done) => requestAnimationFrame(() => setTimeout(done, 0)))
    }
    window.print()
  }
  /* «Tipărește…» меню окна Tauri — кнопка печати шапки ниже */
  useCommand('act:print', () => { void printChart() })
  /* F5 и «Reîncarcă» окна оболочки: с черновиками — своим окном вопроса */
  const pendingKey = c.pending.join(',')
  useCommand('act:reload', pendingKey !== '' && (() => {
    void ask({ text: `${unsavedTeeth(c.pending)} ${T.reload}`, ok: T.reloadOk, danger: true })
      .then((yes) => { if (yes) defaultReload() })
  }))
  /* без оболочки (браузер второго ПК, телефон) — вопрос браузера на F5 и
     закрытие вкладки; в окне оболочки не ставится: её собственные переходы
     (прятание к часам на общем ПК) диалогом будить нельзя */
  useEffect(() => {
    if (pendingKey === '' || shellOn()) return
    const stay = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', stay)
    return () => window.removeEventListener('beforeunload', stay)
  }, [pendingKey])
  /* несохранённые зубы — владельцу (блокер ухода); снятие стола — пустой список */
  useEffect(() => { onDirty?.(pendingKey ? pendingKey.split(',').map(Number) : []) }, [pendingKey, onDirty])
  useEffect(() => () => onDirty?.([]), [onDirty])
  const savePlan = async (body: PlanAdd): Promise<boolean> => {
    setPlanBusy(true)
    setPlanBad(false)
    try {
      const r = await chart.addPlan(pid, body, saveQuery)
      if (r.text) say({ tone: r.tone, text: r.text })
      replace(r.data)
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

  /* кнопка зуба — на дуге (2D) или на карте (всегда): первая видимая в документе.
     ⛔ Без прокрутки: в 3D первая — кнопка карты ПОД сценой, и фокус после
     пункта меню уводил страницу к «Harta dinților» (Олег 25.10) */
  const focusTooth = useCallback((n: number) => {
    root.current?.querySelector<HTMLElement>(`.arch .tooth-btn[data-n="${n}"], .dp-tm-btn[data-n="${n}"]`)?.focus({ preventScroll: true })
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

  /* Планшет (B7; с 25.10 — раскладка B): прокрутки к выбранному зубу и
     выбора стороны панели больше нет — страница не прокручивается, ряд зубов
     всегда над сценой, в альбоме панель — колонкой (не поверх карты: прежняя
     закрывала вкладки Implant / Proteză), в портрете шторка снизу, а рабочий
     стол над ней ужимается (`data-sel` + CSS). */

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
      else if (c.brush) c.setBrush(null)        // сперва кисть, потом черновик
      else if (c.dirty) c.discard()
      return
    }
    if (brMode) return
    if (e.key === 'Enter') {
      if (c.selected === null && !c.pending.length) return
      e.preventDefault()
      if (c.pending.length && !c.busy) void doSave()
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
    // буква поверхности: с кистью — красит, без — выбирает
    const hit = (letter: string) => { if (c.brush && c.selected !== null) c.pickSurface(c.selected, letter); else c.setSel(letter) }
    if (L === 'P') {
      if (c.info.jaw === 'sus') { e.preventDefault(); hit('L') }
      return
    }
    if (LETTERS.has(L) && L in model.surfaces) { e.preventDefault(); hit(L) }
  }

  const menuInfo = menu ? model.teeth[String(menu.n)] : undefined
  const menuCurrent = menu && menu.n === c.selected && c.draft ? c.draft.state : (menuInfo?.state ?? '')
  const menuMarks = menu && menu.n === c.selected && c.draft ? c.draft.marks : (menuInfo?.mk ?? [])
  const pickedSet = new Set(picked)

  return (
    <>
      <div ref={root} className="odop odo dp-odo" id="odo" data-page={embedded ? undefined : ''} data-view={c.view}
        data-sel={c.selected ?? undefined} data-brush={c.brush ?? undefined} tabIndex={0} onKeyDown={onKey}>
        <div className="dp-odo-head">
          {/* имя — заголовок детальной страницы и дорога назад в фишу; во вкладке фиши имя уже в её шапке */}
          {!embedded && (
            <div className="dp-odo-who">
              <AppLink className="dp-odo-lnk" href={`${base}?tab=odonto`} title={T.back}><Icon name="pat" /> <span>{model.patient.name}</span></AppLink>
            </div>
          )}
          <ModeTabs model={shown} value={mode?.key ?? ''} onPick={pickMode} />
          <div className="dp-odo-headr">
            <span className="dp-odo-count"><b>{recorded}</b> {T.recorded}</span>
            <button type="button" className="dp-odo-lnk dp-odo-ic" aria-label={T.newBridge} title={T.newBridge}
              onClick={() => { setBrMode(true); setPicked([]) }}>
              <Icon name="plus" /> <span>{T.newBridge}</span>
            </button>
            {/* «Parodontogramă» здесь снята (09.10, разбор): к листу ведут вкладка
                фиши и режим «Parodonțiu» шапки — третий вход только путал. */}
            {embedded && (
              <AppLink className="dp-odo-lnk dp-odo-ic" href={`${base}/odontograma`} title={T.full}><Icon name="eye" /> <span>{T.full}</span></AppLink>
            )}
            <button type="button" className="dp-ibtn" aria-label={T.print} title={T.print} onClick={() => { void printChart() }}><Icon name="print" /></button>
          </div>
        </div>
        <BridgeBar model={model} active={brMode} picked={picked} onCancel={stopBridge} onContinue={() => setBrOpen(true)} />
        <div className="odop-grid dp-odo-cols">
          <div className="odop-main dp-odo-main">
            <div className="dp-card dp-vp">
              {c.view === '3d' ? (
                /* B7: объёмный вид — тот же контроллер, те же действия; выбор,
                   поверхность и меню идут в панель, как из карты */
                <Odontogram3D model={shown} selected={brMode ? null : c.selected} onSurface={onSurface} onMenu={onMenu}
                  focus={focus3d} onZoom={setZoom} onDouble={onDouble} dim={dim} mode={scene}
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
                      model={shown}
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
            {/* ряд зубов стоит НАД сценой (CSS `order`), а в разметке — после неё:
                первая кнопка зуба в документе — на дуге 2D, туда и уходит фокус
                клавиатуры (`focusTooth`) */}
            <ToothMap model={shown} selected={brMode ? null : c.selected} picked={pickedSet} dirty={c.dirtyTeeth}
              dim={dim} onSelect={onSelect} onMenu={onMenu} />
          </div>
          <aside className="odop-side dp-odo-side">
            <ToothPanel
              model={model}
              n={c.selected}
              busy={c.busy}
              sel={c.sel}
              onSurface={onSurface}
              brush={brMode ? null : c.brush}
              onBrush={c.setBrush}
              draft={c.draft}
              dirty={c.dirty}
              onEdit={c.edit}
              pending={c.pending}
              onSave={() => { void doSave() }}
              onDiscard={c.discard}
              onDelBridge={(bid) => { void c.delBridge(bid) }}
              onBridgeFrom={bridgeFrom}
              onPlan={planFrom}
              onClose={() => c.select(null)}
              saved={savedN}
            />
          </aside>
        </div>
      </div>
      {menu && (
        <ToothMenu model={model} at={menu} current={menuCurrent} onState={menuState} marks={menuMarks} onMark={menuMark}
          onPlan={planFrom} onBridge={bridgeFrom} onClose={closeMenu} mode={mode} />
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
