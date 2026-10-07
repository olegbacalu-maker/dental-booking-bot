import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../../components/Icon'
import type { Odontogram, PerioLayer } from '../chart'
import { load3d } from './loadTeeth'
import { PerioLegend } from './PerioLegend'
import { createArchScene, type ArchScene, type CameraProbe, type Hit, type PerioInput, type Toggle, type ToothProbe, type ViewName } from './scene'
import type { Letter } from './toothGeometry'

/* Объёмный вид одонтограммы (B7, ступень 4): React владеет узлом и жизненным
   циклом, three — картинкой. ⛔ Дерево компонента статично: движение мыши,
   наведение и вращение не вызывают reconciliation — сцена получает всё
   императивно (`setModel`, `setSelected`, `setView`, `setToggle`), колбэки
   живут в ref, чтобы сцена создавалась ОДИН раз (новый контекст WebGL —
   вспышка). three.js едет по требованию: до загрузки — ожидание, отказ —
   текст, 2D под рукой на соседней кнопке вида. Молочный ряд в 3D не
   показывается (решение 6): при открытом молочном ряде — надпись.

   Режим «Parodont» (06.10, слово Олега «да» на «режим Parodont с таблицей
   точек»): последний осмотр пародонтограммы с измерениями (`perio_layer`
   модели — тот же, что в 043/e) ложится на десну: рецессия опускает край,
   карман от порога — полоса у края, кровоточивость — точка, с «Rădăcini» —
   зонд на глубину кармана. Находки зубов в этом режиме приглушены. Режим —
   экрана: в модель, запись и печать не попадает.

   Фокус (01.10): камера едет к выбранному зубу — кнопкой «Apropie», клавишей
   F (рабочий стол) или двойным щелчком по зубу; кнопки видов возвращают.
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
  focus: 'Apropie',
  focusTitle: 'Camera la dintele selectat (dublu-clic pe dinte sau tasta F); o vedere o aduce înapoi',
  modes: 'Ce arată vederea 3D',
  stare: 'Stare dinți',
  paro: 'Parodont',
  paroNone: 'Pacientul nu are încă o parodontogramă cu măsurători',
  paroTitle: 'Parodontograma din {at} pe gingie: recesiune, pungi, sângerare',
} as const

type Mode = 'stare' | 'paro'

const toInput = (l: PerioLayer): PerioInput => ({ rows: l.rows, limits: l.limits, colors: l.colors })

const VIEW_ORDER: ViewName[] = ['frontal', 'sus', 'jos', 'dreapta', 'stanga']
const TOG_ORDER: Toggle[] = ['xray', 'labels', 'upper', 'lower', 'closed', 'rotate']

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
  /** кнопка «Apropie» и кнопки видов: включить/выключить фокус на выбранном */
  onZoom: (on: boolean) => void
  /** двойной щелчок по зубу в сцене */
  onDouble: (n: number) => void
  /** зубы, погашенные фильтром легенды */
  dim: ReadonlySet<number>
}

type Status = 'loading' | 'ready' | 'failed' | 'nogl'
/** зонд сцены на узле — стенды Edge читают его через CDP, тестов в jsdom это не касается */
type Probed = HTMLDivElement & { __dp3d?: { inspect: (n: number) => ToothProbe | null; camera: () => CameraProbe | null } }

export function Odontogram3D({ model, selected, onSurface, onMenu, onHover, focus, onZoom, onDouble, dim }: Props) {
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
  const [togs, setTogs] = useState<Record<Toggle, boolean>>({ xray: false, labels: true, upper: true, lower: true, closed: false, rotate: false })
  const togsRef = useRef(togs)
  const layer = model.perio_layer ?? null
  const [mode, setMode] = useState<Mode>('stare')
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
  }, [focus])

  const pickView = (v: ViewName): void => {
    setView(v)
    // вид на одну челюсть прячет другую — кнопки челюстей следуют за сценой
    setTogs((t) => ({ ...t, upper: v !== 'jos', lower: v !== 'sus', rotate: false }))
    sceneRef.current?.setView(v)
    onZoom(false)
  }
  const flip = (k: Toggle): void => {
    const on = !togs[k]
    setTogs((t) => ({ ...t, [k]: on }))
    if (k === 'rotate' && on) setView(null)
    sceneRef.current?.setToggle(k, on)
  }

  return (
    <div className="odo-3d" data-focus={focus ?? undefined}>
      <div className="odo-3d-bar" role="group" aria-label={T.group}>
        <div className="viewsw odo-mode" role="group" aria-label={T.modes}>
          <button type="button" data-mode="stare" className={paro ? '' : 'on'} aria-pressed={!paro}
            disabled={status !== 'ready'} onClick={() => setMode('stare')}>{T.stare}</button>
          <button type="button" data-mode="paro" className={paro ? 'on' : ''} aria-pressed={paro}
            disabled={status !== 'ready' || !layer}
            title={layer ? T.paroTitle.replace('{at}', layer.exam.at) : T.paroNone}
            onClick={() => setMode('paro')}>{T.paro}</button>
        </div>
        <div className="viewsw">
          {VIEW_ORDER.map((v) => (
            <button key={v} type="button" data-v3={v} className={view === v ? 'on' : ''} aria-pressed={view === v}
              disabled={status !== 'ready'} onClick={() => pickView(v)}>{T.views[v]}</button>
          ))}
          <button type="button" data-v3="focus" className={`odo-focus${focus !== null ? ' on' : ''}`} aria-pressed={focus !== null}
            title={T.focusTitle} disabled={status !== 'ready' || selected === null} onClick={() => onZoom(focus === null)}>
            <Icon name="search" /> {T.focus}
          </button>
        </div>
        <div className="odo-3d-togs">
          {TOG_ORDER.map((k) => (
            <button key={k} type="button" className="odo-more" data-tog={k} aria-pressed={togs[k]}
              disabled={status !== 'ready'} onClick={() => flip(k)}>{T.togs[k]}</button>
          ))}
        </div>
      </div>
      {paro && layer && <PerioLegend at={layer.exam.at} limits={layer.limits} colors={layer.colors} />}
      <div ref={host} className="odo-stage" data-status={status} data-mode={paro ? 'paro' : 'stare'}>
        {status === 'loading' && <p className="hint odo-3d-msg" aria-busy="true">{T.loading}</p>}
        {status === 'failed' && <p className="hint odo-3d-msg">{T.failed}</p>}
        {status === 'nogl' && <p className="hint odo-3d-msg">{T.nogl}</p>}
      </div>
      {model.milk_open && <p className="hint dp-m0"><Icon name="tooth" /> {T.milk}</p>}
    </div>
  )
}
