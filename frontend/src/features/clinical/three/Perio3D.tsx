import { useEffect, useRef, useState } from 'react'
import { chart, type Odontogram } from '../chart'
import { loadThree } from './loadThree'
import { PerioLegend } from './PerioLegend'
import { createArchScene, type ArchScene, type CameraProbe, type PerioInput, type ToothProbe, type ViewName } from './scene'

/* 3D над листом пародонтограммы (06.10, ступень 4 плана — слово Олега «да»).
   Та же сцена, что у одонтограммы, но данные — ЧЕРНОВИК листа: врач диктует
   «6», ассистент печатает — край десны и полоса кармана меняются сразу, без
   записи. Зубы и их состояния — модель одонтограммы (один запрос при открытии
   3D). Курсор листа ведёт камеру к зубу (сверху — видны все шесть точек) и
   ставит маркер на точку; щелчок по зубу в сцене ставит курсор в его первую
   клетку. Ничего не считается: положения — из чисел черновика, пороги и цвета
   — из модели листа (сервер). ⛔ Дерево статично, как у `Odontogram3D`: сцена
   получает всё императивно, движение мыши reconciliation не вызывает. */

const T = {
  loading: 'Se încarcă vederea 3D…',
  failed: '3D nu s-a încărcat. Foaia funcționează ca de obicei.',
  nogl: 'WebGL nu este disponibil în acest browser.',
  group: 'Vedere 3D a parodontogramei',
  views: { frontal: 'Frontal', sus: 'Ocluzal sus', jos: 'Ocluzal jos', dreapta: 'Dreapta', stanga: 'Stânga' } as Record<ViewName, string>,
  xray: 'Rădăcini',
} as const

const VIEW_ORDER: ViewName[] = ['frontal', 'sus', 'jos', 'dreapta', 'stanga']

interface Props {
  pid: number
  /** черновик листа по зубам — шесть точек в порядке сервера */
  rows: PerioInput['rows']
  limits: { deep: number; severe: number }
  colors: { deep: string; severe: string }
  /** клетка листа под курсором: зуб и точка (0–5) */
  active: { n: number; site: number } | null
  /** щелчок по зубу в сцене — курсор в его колонку листа */
  onPickTooth: (n: number) => void
}

type Status = 'loading' | 'ready' | 'failed' | 'nogl'
type Probed = HTMLDivElement & { __dp3d?: { inspect: (n: number) => ToothProbe | null; camera: () => CameraProbe | null } }

export function Perio3D({ pid, rows, limits, colors, active, onPickTooth }: Props) {
  const host = useRef<HTMLDivElement | null>(null)
  const sceneRef = useRef<ArchScene | null>(null)
  const [model, setModel] = useState<Odontogram | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [view, setView] = useState<ViewName | null>('frontal')
  const [xray, setXray] = useState(false)
  const pickRef = useRef(onPickTooth)
  const inputRef = useRef<PerioInput>({ rows, limits, colors })
  const activeRef = useRef(active)
  useEffect(() => {
    pickRef.current = onPickTooth
    inputRef.current = { rows, limits, colors }
    activeRef.current = active
  })

  // модель одонтограммы — один раз при открытии 3D: зубы, состояния, размеры
  useEffect(() => {
    const ctl = new AbortController()
    chart.get(pid, ctl.signal).then((r) => setModel(r.data), () => {
      if (!ctl.signal.aborted) setStatus('failed')
    })
    return () => ctl.abort()
  }, [pid])

  useEffect(() => {
    if (!model) return
    let alive = true
    loadThree().then((THREE) => {
      if (!alive || !host.current) return
      const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
      try {
        const scene = createArchScene({
          THREE, container: host.current, reduced,
          onHover: () => undefined,
          onPick: (h) => pickRef.current(h.n),
          onMenu: (n) => pickRef.current(n),
          onViewLeft: () => setView((v) => (v === null ? v : null)),
          onDouble: (n) => pickRef.current(n),
        })
        sceneRef.current = scene
        ;(host.current as Probed).__dp3d = { inspect: (n) => scene.inspect(n), camera: () => scene.camera() }
        scene.setModel(model)
        scene.setPerio(inputRef.current)
        const a = activeRef.current
        if (a) {
          scene.setSelected(a.n)
          scene.setActiveSite(a.n, a.site)
        }
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
  }, [model])

  // черновик → десна: не чаще кадра (цифра за цифрой при диктовке)
  const sig = JSON.stringify(rows)
  useEffect(() => {
    const id = requestAnimationFrame(() => sceneRef.current?.setPerio(inputRef.current))
    return () => cancelAnimationFrame(id)
  }, [sig, limits, colors])

  // курсор листа → маркер точки и выбранный зуб
  const an = active?.n ?? null
  const as = active?.site ?? null
  useEffect(() => {
    const sc = sceneRef.current
    if (!sc) return
    sc.setSelected(an)
    sc.setActiveSite(an, as)
  }, [an, as, status])

  // другой зуб — камера к нему сверху; челюсть напротив уходит, иначе закрыла бы вид
  useEffect(() => {
    const sc = sceneRef.current
    if (!sc || an === null) return
    const upper = an < 30
    sc.setToggle(upper ? 'upper' : 'lower', true)
    sc.setToggle(upper ? 'lower' : 'upper', false)
    sc.focus(an, 'occlusal')
    setView(null)
  }, [an, status])

  const pickView = (v: ViewName): void => {
    setView(v)
    sceneRef.current?.focus(null)
    sceneRef.current?.setView(v)
  }
  const flipXray = (): void => {
    const on = !xray
    setXray(on)
    sceneRef.current?.setToggle('xray', on)
  }

  return (
    <div className="odo-3d perio-3d">
      <div className="odo-3d-bar" role="group" aria-label={T.group}>
        <div className="viewsw">
          {VIEW_ORDER.map((v) => (
            <button key={v} type="button" data-v3={v} className={view === v ? 'on' : ''} aria-pressed={view === v}
              disabled={status !== 'ready'} onClick={() => pickView(v)}>{T.views[v]}</button>
          ))}
        </div>
        <div className="odo-3d-togs">
          <button type="button" className="odo-more" data-tog="xray" aria-pressed={xray}
            disabled={status !== 'ready'} onClick={flipXray}>{T.xray}</button>
        </div>
      </div>
      <PerioLegend limits={limits} colors={colors} />
      <div ref={host} className="odo-stage" data-status={status} data-mode="paro">
        {status === 'loading' && <p className="hint odo-3d-msg" aria-busy="true">{T.loading}</p>}
        {status === 'failed' && <p className="hint odo-3d-msg">{T.failed}</p>}
        {status === 'nogl' && <p className="hint odo-3d-msg">{T.nogl}</p>}
      </div>
    </div>
  )
}
