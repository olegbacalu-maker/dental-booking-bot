import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Icon } from '../../../components/Icon'
import { useMenuDismiss } from '../../../components/menu'
import type { Odontogram, PerioLayer } from '../chart'
import { load3d } from './loadTeeth'
import { PerioLegend } from './PerioLegend'
import { createArchScene, labelsFor, type ArchScene, type CameraProbe, type Hit, type PerioInput, type Toggle, type ToothProbe, type ViewName } from './scene'
import type { Letter } from './toothGeometry'
import { VIEW_ICON } from './viewIcons'

/* Объёмный вид одонтограммы (B7, ступень 4): React владеет узлом и жизненным
   циклом, three — картинкой. ⛔ Дерево компонента статично: движение мыши,
   наведение и вращение не вызывают reconciliation — сцена получает всё
   императивно (`setModel`, `setSelected`, `setView`, `setToggle`), колбэки
   живут в ref, чтобы сцена создавалась ОДИН раз (новый контекст WebGL —
   вспышка). three.js едет по требованию: до загрузки — ожидание, отказ —
   текст, 2D под рукой на соседней кнопке. Молочный ряд в 3D не
   показывается (решение 6): при открытом молочном ряде — надпись.

   Раскладка B (Олег 24.10 «da давай вариант B», волна 2 — 25.10; до того —
   полоса сверху и колонка «Straturi» слева по макету 08.10): сцена — во всю
   карточку, управление ПЛАШКАМИ поверх неё. Слева сверху — сегмент пяти
   видов значками (подпись рядом — только на широкой сцене, имя — в
   aria-label и подсказке) и кнопка «2D» назад к рисункам сервера; справа сверху — «Straturi»
   (поповер: челюсти «Arcade» и слои) и группа зума «− 100% +», камера к
   зубу, сброс. Высоту сцене даёт рабочий стол (окно минус шапка, ряд зубов
   и легенда), отдельной полосы над ней нет. Плашки — сплошные, без размытия
   (`test_structure`: размытие только над прокруткой). Поповер — состояние
   этого компонента, закрывается нажатием мимо и Esc (`useMenuDismiss`); его
   кнопки живут, только пока он открыт. Зум — `scene.zoomTo`:
   радиус орбиты от радиуса вида (или фокуса), вид и фокус возвращают 100%.
   100 % вида — не число, а подгонка под окно (11.10, `three/fit.ts`): дуга
   занимает ~80 % кадра по ограничивающей оси и пересчитывается при смене
   размера. Слой «Numere» по умолчанию выключен и следует за видом
   (`labelsFor`: окклюзионные виды — включён), как кнопки челюстей; у
   выбранного зуба номер в сцене виден всегда.

   Режим «Parodont» (06.10, слово Олега «да» на «режим Parodont с таблицей
   точек»; с 08.10 — вкладка страницы, состояние у рабочего стола): последний
   осмотр пародонтограммы с измерениями (`perio_layer` модели — тот же, что
   в 043/e) ложится на десну: рецессия опускает край, карман от порога —
   полоса у края, кровоточивость — точка, с «Rădăcini» — зонд на глубину
   кармана. Находки зубов в этом режиме приглушены. Режим — экрана: в
   модель, запись и печать не попадает.

   Фокус (01.10): камера едет к выбранному зубу — кнопкой, клавишей F
   (рабочий стол) или двойным щелчком по зубу; кнопки видов возвращают.
   Решает рабочий стол (`focus` — номер или null), здесь — исполнение: если
   челюсть зуба спрятана, она возвращается, иначе камера подъехала бы к
   пустому месту. Движение — только вслед за действием человека, при
   reduced-motion мгновенно (решение 5). */

const T = {
  loading: 'Se încarcă vederea 3D…',
  failed: '3D nu s-a încărcat. Vederea frontală și cea ocluzală funcționează.',
  nogl: 'WebGL nu este disponibil în acest browser.',
  milk: 'Dinții de lapte — în vederea frontală sau ocluzală.',
  views: { frontal: 'Frontal', sus: 'Ocluzal sus', jos: 'Ocluzal jos', dreapta: 'Dreapta', stanga: 'Stânga' } as Record<ViewName, string>,
  togs: { xray: 'Rădăcini', labels: 'Numere', upper: 'Maxilar', lower: 'Mandibular', closed: 'Ocluzie', rotate: 'Rotire' } as Record<Toggle, string>,
  group: 'Vedere 3D',
  flat: '2D',
  flatTitle: 'Desenele frontal și ocluzal',
  layers: 'Straturi',
  arch: 'Arcade',
  zoom: 'Apropiere',
  zoomIn: 'Apropie',
  zoomOut: 'Depărtează',
  reset: 'Resetează vizualizarea',
  focus: 'Camera la dinte',
  focusTitle: 'Camera la dintele selectat (dublu-clic pe dinte sau tasta F); o vedere o aduce înapoi',
} as const

export type Mode = 'stare' | 'paro'

const toInput = (l: PerioLayer): PerioInput => ({ rows: l.rows, limits: l.limits, colors: l.colors })

const VIEW_ORDER: ViewName[] = ['frontal', 'sus', 'jos', 'dreapta', 'stanga']
/* поповер «Straturi»: челюсти отдельной группой «Arcade», потом слои */
const ARCH_TOGS: Toggle[] = ['upper', 'lower']
const LAYER_TOGS: Toggle[] = ['xray', 'labels', 'closed', 'rotate']
const ZOOM_STEP = 20
const ZOOM_MIN = 60
const ZOOM_MAX = 200

interface Props {
  model: Odontogram
  selected: number | null
  /** щелчок по поверхности коронки — как щелчок по зоне поверхности в 2D */
  onSurface: (n: number, letter: Letter) => void
  /** правая кнопка — меню зуба у курсора */
  onMenu: (n: number, x: number, y: number) => void
  onHover?: (h: Hit | null) => void
  /** зуб, к которому подъехала камера; null — вид целиком */
  focus: number | null
  /** кнопка камеры и кнопки видов: включить/выключить фокус на выбранном */
  onZoom: (on: boolean) => void
  /** двойной щелчок по зубу в сцене */
  onDouble: (n: number) => void
  /** зубы, погашенные фильтром легенды */
  dim: ReadonlySet<number>
  /** вкладка страницы «Stare dinți» / «Parodont» — решает рабочий стол */
  mode: Mode
  /** назад к рисункам сервера (frontal / ocluzal) */
  onFlat: () => void
}

type Status = 'loading' | 'ready' | 'failed' | 'nogl'
/** зонд сцены на узле — стенды Edge читают его через CDP, тестов в jsdom это не касается */
type Probed = HTMLDivElement & { __dp3d?: { inspect: (n: number) => ToothProbe | null; camera: () => CameraProbe | null } }

export function Odontogram3D({ model, selected, onSurface, onMenu, onHover, focus, onZoom, onDouble, dim, mode, onFlat }: Props) {
  const host = useRef<HTMLDivElement | null>(null)
  const sceneRef = useRef<ArchScene | null>(null)
  const surfaceRef = useRef(onSurface)
  const menuRef = useRef(onMenu)
  const hoverRef = useRef(onHover)
  const doubleRef = useRef(onDouble)
  const modelRef = useRef(model)
  const selRef = useRef(selected)
  const focusRef = useRef(focus)
  const dimRef = useRef(dim)
  const [status, setStatus] = useState<Status>('loading')
  const [view, setView] = useState<ViewName | null>('frontal')
  const [togs, setTogs] = useState<Record<Toggle, boolean>>({ xray: false, labels: labelsFor('frontal'), upper: true, lower: true, closed: false, rotate: false })
  const togsRef = useRef(togs)
  const [zoom, setZoom] = useState(100)
  /* поповер «Straturi» — свойство экрана, не сцены */
  const [layOpen, setLayOpen] = useState(false)
  const layBox = useRef<HTMLDivElement | null>(null)
  const closeLay = useCallback(() => setLayOpen(false), [])
  const layer = model.perio_layer ?? null
  // осмотра нет (или его сняли) — режим пародонта сам возвращается к состоянию зубов
  const paro = mode === 'paro' && layer !== null
  const paroRef = useRef<PerioInput | null>(null)
  // свежие пропсы — в ref после каждой отрисовки (не во время неё): сцена
  // читает их из асинхронной загрузки и из событий указателя
  useEffect(() => {
    surfaceRef.current = onSurface
    menuRef.current = onMenu
    hoverRef.current = onHover
    doubleRef.current = onDouble
    modelRef.current = model
    selRef.current = selected
    focusRef.current = focus
    dimRef.current = dim
    togsRef.current = togs
    paroRef.current = paro && layer ? toInput(layer) : null
  })

  useEffect(() => {
    let alive = true
    const el = host.current
    if (!el) return
    load3d().then(({ THREE, teeth }) => {
      if (!alive || !host.current) return
      const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
      try {
        const scene = createArchScene({
          THREE, teeth, container: host.current, reduced,
          onHover: (h) => hoverRef.current?.(h),
          onPick: (h) => surfaceRef.current(h.n, h.letter),
          onMenu: (n, x, y) => menuRef.current(n, x, y),
          onViewLeft: () => setView((v) => (v === null ? v : null)),
          onDouble: (n) => doubleRef.current(n),
        })
        sceneRef.current = scene
        ;(host.current as Probed).__dp3d = { inspect: (n) => scene.inspect(n), camera: () => scene.camera() }
        scene.setModel(modelRef.current)
        if (dimRef.current.size) scene.setDim(dimRef.current)
        scene.setSelected(selRef.current)
        if (focusRef.current !== null) scene.focus(focusRef.current)
        if (paroRef.current) scene.setPerio(paroRef.current)
        setStatus('ready')
      } catch {
        setStatus('nogl')
      }
    }, () => { if (alive) setStatus('failed') })
    return () => {
      alive = false
      sceneRef.current?.dispose()
      sceneRef.current = null
    }
  }, [])

  useEffect(() => { sceneRef.current?.setModel(model) }, [model])
  useEffect(() => { sceneRef.current?.setSelected(selected) }, [selected])
  useEffect(() => { sceneRef.current?.setDim(dim) }, [dim])
  useEffect(() => { sceneRef.current?.setPerio(paro && layer ? toInput(layer) : null) }, [paro, layer])
  useEffect(() => {
    const sc = sceneRef.current
    if (focus !== null) {
      // спрятанная челюсть возвращается — иначе камера подъехала бы к пустому месту
      const jaw: Toggle = modelRef.current.teeth[String(focus)]?.jaw === 'jos' ? 'lower' : 'upper'
      if (!togsRef.current[jaw]) {
        setTogs((t) => ({ ...t, [jaw]: true }))
        sc?.setToggle(jaw, true)
      }
    }
    sc?.focus(focus)
    // фокус и возврат ставят свой радиус — зум от него заново
    setZoom(100)
  }, [focus])

  const pickView = (v: ViewName): void => {
    setView(v)
    // вид решает слои, кнопки следуют за сценой: вид на одну челюсть прячет
    // другую, окклюзионные виды показывают номера (`labelsFor` — то же правило, что в сцене)
    setTogs((t) => ({ ...t, upper: v !== 'jos', lower: v !== 'sus', labels: labelsFor(v), rotate: false }))
    sceneRef.current?.setView(v)
    setZoom(100)
    onZoom(false)
  }
  const flip = (k: Toggle): void => {
    const on = !togs[k]
    setTogs((t) => ({ ...t, [k]: on }))
    if (k === 'rotate' && on) setView(null)
    sceneRef.current?.setToggle(k, on)
  }
  const zoomTo = (pct: number): void => {
    const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, pct))
    setZoom(z)
    sceneRef.current?.zoomTo(z)
  }
  const reset = (): void => {
    // сброс = вид заново: углы, цель и радиус вида, фокус снят
    const v = view ?? 'frontal'
    pickView(v)
  }
  const ready = status === 'ready'

  const togBtn = (k: Toggle) => (
    <button key={k} type="button" className={`dp-lay${togs[k] ? ' on' : ''}`} data-tog={k} aria-pressed={togs[k]}
      disabled={!ready} onClick={() => flip(k)}>
      <span className="box"><Icon name="check" /></span>{T.togs[k]}
    </button>
  )

  return (
    <div className="odo-3d" data-focus={focus ?? undefined}>
      {paro && layer && <PerioLegend at={layer.exam.at} limits={layer.limits} colors={layer.colors} />}
      <div className="dp-vp-body">
        <div ref={host} className="odo-stage" data-status={status} data-mode={paro ? 'paro' : 'stare'}>
          {status === 'loading' && <p className="hint odo-3d-msg" aria-busy="true">{T.loading}</p>}
          {status === 'failed' && <p className="hint odo-3d-msg">{T.failed}</p>}
          {status === 'nogl' && <p className="hint odo-3d-msg">{T.nogl}</p>}
        </div>
        <div className="dp-vp-ov">
          <div className="dp-seg dp-views dp-vp-pl" role="group" aria-label={T.group}>
            {VIEW_ORDER.map((v) => (
              <button key={v} type="button" data-v3={v} className={view === v ? 'on' : ''} aria-pressed={view === v}
                aria-label={T.views[v]} title={T.views[v]} disabled={!ready} onClick={() => pickView(v)}>
                <Icon name={VIEW_ICON[v]} /><span>{T.views[v]}</span>
              </button>
            ))}
            <span className="dp-seg-sep" />
            <button type="button" data-v3="2d" title={T.flatTitle} onClick={onFlat}><Icon name="arch-flat" />{T.flat}</button>
          </div>
          <div className="dp-vp-ovr">
            {/* Esc закрывает поповер и дальше не идёт: рабочий стол по Esc снял бы кисть или черновик */}
            <div className="dp-vp-lay" ref={layBox}
              onKeyDown={(e) => { if (e.key === 'Escape' && layOpen) { e.stopPropagation(); setLayOpen(false) } }}>
              {/* открывается и без сцены: состояние слоёв видно, переключатели внутри выключены */}
              <button type="button" className={`dp-vp-pl dp-vp-layb${layOpen ? ' on' : ''}`} aria-expanded={layOpen}
                aria-haspopup="true" aria-label={T.layers} title={T.layers} onClick={() => setLayOpen((o) => !o)}>
                <Icon name="layers" />
              </button>
              {layOpen && <LayerPop box={layBox} onClose={closeLay} arch={ARCH_TOGS.map(togBtn)} layers={LAYER_TOGS.map(togBtn)} />}
            </div>
            <div className="dp-zoom dp-vp-pl" role="group" aria-label={T.zoom}>
              <button type="button" className="dp-ibtn" aria-label={T.zoomOut} title={T.zoomOut} disabled={!ready || zoom <= ZOOM_MIN}
                onClick={() => zoomTo(zoom - ZOOM_STEP)}><Icon name="minus" /></button>
              <span className="dp-zoom-l" aria-live="polite">{zoom}%</span>
              <button type="button" className="dp-ibtn" aria-label={T.zoomIn} title={T.zoomIn} disabled={!ready || zoom >= ZOOM_MAX}
                onClick={() => zoomTo(zoom + ZOOM_STEP)}><Icon name="plus" /></button>
              <button type="button" className={`dp-ibtn odo-focus${focus !== null ? ' on' : ''}`} data-v3="focus"
                aria-pressed={focus !== null} aria-label={T.focus} title={T.focusTitle}
                disabled={!ready || selected === null} onClick={() => onZoom(focus === null)}><Icon name="search" /></button>
              <button type="button" className="dp-ibtn" aria-label={T.reset} title={T.reset} disabled={!ready}
                onClick={reset}><Icon name="refresh" /></button>
            </div>
          </div>
        </div>
      </div>
      {model.milk_open && <p className="hint dp-m0 dp-vp-milk"><Icon name="tooth" /> {T.milk}</p>}
    </div>
  )
}

/** Поповер «Straturi»: закрывается нажатием мимо и Esc — тот же хук, что у меню зуба. */
function LayerPop({ box, onClose, arch, layers }: {
  box: RefObject<HTMLDivElement | null>; onClose: () => void; arch: ReactNode; layers: ReactNode
}) {
  useMenuDismiss(box, onClose)
  return (
    <div className="dp-vp-pop" role="group" aria-label={T.layers}>
      <span className="dp-lbl">{T.arch}</span>
      {arch}
      <span className="dp-lbl">{T.layers}</span>
      {layers}
    </div>
  )
}
