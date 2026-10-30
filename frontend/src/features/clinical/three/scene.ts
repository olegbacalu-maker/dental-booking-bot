import type * as T3 from 'three'
import type { Odontogram, ToothGeom, ToothInfo } from '../chart'
import { archCurve, GAP, GAP_CLOSED, layoutArch, type ArchLayout, type PlacedTooth } from './arch'
import { focusOcclusal, focusOrbit, nearestTheta } from './focus'
import type { Three } from './loadThree'
import { attachEnamel, enamelLive, enamelTooth, type EnamelLive, type EnamelMaterial } from './enamel'
import { COLOR, FINISH, finishOf, hex, lerpHex, mixFinish, physOf, sameFinish, sameLook, setFinish, setTransparent, structChanged, targetLook, type Finish, type Look } from './look'
import type { RawMesh } from './mesh'
import { buildDashedLoop, buildRoots, buildScrew, SURF, toCls, type Letter } from './toothGeometry'
import { crownModel, type CrownModel } from './crown'
import { sculptModel, type SculptSet } from './sculpt'
import { posed } from './pose'
import { anchorsFor, buildGum, linRgb, marginH, SITE_DEG, stripesFor, wallPoint, type GumKind, type GumTooth } from './gum'
import { roomEnv } from './env'
import { comesFrom, MS, sceneFor, startLift } from './transition'
import { createTweens, type Tweens } from './tween'
import { EMPTY_BOUNDS, fillAt, fitRadius, isEmpty, union, type Bounds } from './fit'
import { isFinger, LONG_MS, slopOf, swallowNextClick } from '../touch'

/* Сцена одонтограммы (B7, ступень 4) — чистый three.js, без React: обе
   челюсти на дуге движка, пять материалов на коронку (= пять поверхностей),
   корни, винт импланта, кольца отметок и выбора, номера. С 06.10 (кадры
   до/после, слово Олега «нравится»): коронка `crown.ts`, постановка `pose.ts`,
   десна по краю каждого зуба `gum.ts`, блики от карты окружения `env.ts`
   (с 24.10 — вид «Simplu»: комната и отделка поверхностей по смыслу `look.FINISH`);
   слой пародонта — рецессия, полосы карманов, BOP, зонды — `setPerio`.
   THREE приходит снаружи уже загруженным (`loadThree`), поэтому модуль
   импортирует только его ТИПЫ. Кадры — ТОЛЬКО по требованию: `invalidate()`
   просит один кадр, и цепочка живёт, пока идёт твин, переезд камеры или
   вращение по кнопке; в покое — ноль кадров (правило прототипа dental3d).
   Данные не считаются: что видно и какого цвета — `look.targetLook` от модели
   и палитры сервера; сцены смены состояния — ступень 6. */

/** Углы камеры по видам (азимут, от оси y), градусы. Дистанции здесь нет с
 *  11.10: её считает `fit.ts` под размер окна (`fitR`), прежние числа 172–180
 *  держали дугу одного размера в пикселях и на ноутбуке, и на мониторе. */
export const VIEWS = {
  frontal: [0, 80], sus: [0, 152], jos: [0, 28], dreapta: [-62, 82], stanga: [62, 82],
} as const
export type ViewName = keyof typeof VIEWS
export type Toggle = 'xray' | 'labels' | 'upper' | 'lower' | 'closed' | 'rotate'

/** Номера по умолчанию выключены (11.10): во фронтальном виде моляры стоят друг
 *  за другом в перспективе, и 14/15/16 наезжали. На окклюзионных видах зубы не
 *  перекрываются, и там номера включаются сами — ОДНО правило на сцену и на
 *  кнопку «Numere» компонента (она следует за сценой, как кнопки челюстей). */
export const labelsFor = (v: ViewName): boolean => v === 'sus' || v === 'jos'

/** Пределы радиуса орбиты — колесо, щипок и подгонка под окно. */
const R_MIN = 70
const R_MAX = 420
/** Размер спрайта номера, мм: обычный и у выбранного зуба (он виден всегда). */
const LABEL = 3.9
const LABEL_SEL = 5.6
// формирователь десны имплантата без коронки, мм по оси зуба (шейка = 0, десна закрывает её на 0,7)
const CAP_H = 4
const CAP_Y = 1.6

export interface Hit { n: number; letter: Letter }

export interface SceneOptions {
  THREE: Three
  container: HTMLElement
  reduced: boolean
  onHover: (h: Hit | null) => void
  /** щелчок (не перетаскивание) по поверхности коронки */
  onPick: (h: Hit) => void
  /** правая кнопка по зубу — меню, как у кнопки зуба в 2D */
  onMenu: (n: number, x: number, y: number) => void
  /** камера сошла с предустановки (перетаскивание) — снять подсветку кнопки вида */
  onViewLeft: () => void
  /** двойной щелчок по зубу — камера к нему (01.10, `focus`) */
  onDouble?: (n: number) => void
  /** свои модели зубов (`loadTeeth`); нет — коронки-формулы `crown.ts` */
  teeth?: SculptSet | null
}

/** Последний осмотр пародонтограммы с измерениями — числа сервера как есть:
 *  рецессия ставит край десны, глубина — полосу и зонд, CAL здесь не считается. */
export interface PerioInput {
  /** CAL сцене не нужен (она ставит край по рецессии и зонд по глубине) — у черновика листа его нет */
  rows: Record<string, { pd: number[]; rec: number[]; bop: string; mob: number; furc: number; cal?: number[] }>
  limits: { deep: number; severe: number }
  /** цвет полосы кармана по порогу — с сервера (`teeth_svg.PERIO_COLORS`) */
  colors: { deep: string; severe: string }
}

/** Где стоит камера — для стендов Edge и разбора. */
export interface CameraProbe {
  r: number
  theta: number
  phi: number
  target: [number, number, number]
  /** камера ещё едет (вид, фокус) */
  moving: boolean
  /** радиус вида, подобранный под окно (`fit.ts`) — база зума */
  viewR: number
  /** какую долю кадра по ширине и высоте занимает габарит видимых челюстей при текущем радиусе */
  fill: { w: number; h: number } | null
  aspect: number
}

/** Что сцена показывает для зуба — для стендов и разбора: вид, видимость
 *  частей, прозрачность коронки, идёт ли ещё твин по этому зубу. */
export interface ToothProbe {
  look: Look | null
  crown: boolean
  roots: boolean
  screw: boolean
  socket: boolean
  opacity: number
  y: number
  busy: boolean
  /** номер показан (слой «Numere» или выбранный зуб) и его размер */
  label: boolean
  labelScale: number
  /** отделка материалов коронки сейчас (порядок `SURF`) и прозрачность первого —
   *  сошёлся ли материал с видом после твина (24.10, вид «Simplu») */
  fin: Finish[]
  transparent: boolean
  depthWrite: boolean
}

export interface ArchScene {
  /** зонд для стендов Edge и разбора; null — такого зуба в сцене нет */
  inspect(n: number): ToothProbe | null
  camera(): CameraProbe
  setModel(model: Odontogram): void
  setSelected(n: number | null): void
  setView(name: ViewName): void
  setToggle(k: Toggle, on: boolean): void
  /** камера к зубу (цель — коронка, снаружи дуги) или назад к виду; null — назад.
   *  'occlusal' (лист пародонтограммы) — сверху на зуб, видны все шесть точек */
  focus(n: number | null, how?: 'buccal' | 'occlusal'): void
  /** камера ближе/дальше (08.10, кнопки «−»/«+»): радиус орбиты = радиус
   *  вида (или фокуса) × 100/pct; 100 — как у вида. Углы и цель не трогает. */
  zoomTo(pct: number): void
  /** точка листа под курсором (06.10): маркер у края в этой точке; null — снять */
  setActiveSite(n: number | null, site: number | null): void
  /** зубы, погашенные фильтром легенды (01.10): полупрозрачные, без колец и с бледным номером */
  setDim(teeth: ReadonlySet<number>): void
  /** слой пародонта (край по рецессии, полосы карманов, BOP, зонды); null — снять */
  setPerio(p: PerioInput | null): void
  /** замер (24.10): мс на кадр — n кадров подряд с шагом орбиты, каждый дождан
   *  чтением пикселя (иначе считалась бы очередь команд, а не GPU). Для стендов
   *  Edge: `.odo-stage canvas.__dpBench(n)`; кадров в покое не добавляет. */
  bench(n: number): number
  invalidate(): void
  dispose(): void
}

interface ToothNodes {
  n: number
  /** место на дуге — для фокуса камеры */
  place: PlacedTooth
  group: T3.Group
  crown: T3.Mesh
  mats: EnamelMaterial[]
  roots: T3.Mesh
  rootMat: T3.MeshStandardMaterial
  screw: T3.Mesh
  screwX: T3.Mesh
  cap: T3.Mesh
  ringT: T3.Mesh
  ringD: T3.Mesh
  ringI: T3.Mesh
  ringS: T3.Mesh
  socket: T3.Mesh
  /** пустое место отсутствующего зуба — пунктир шейки у десны */
  gap: T3.Mesh
  gapMat: T3.MeshBasicMaterial
  sprite: T3.Sprite
  tex: [T3.CanvasTexture, T3.CanvasTexture]
  sx: number
  look: Look | null
}

const FALLBACK: Omit<ToothGeom, 'upper'> = { md: 8, bl: 8, crown: 9, root: 12, roots: 1, cls: 'molar' }
const rad = (d: number): number => (d * Math.PI) / 180
const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v))

function toGeometry(THREE: Three, m: RawMesh): T3.BufferGeometry {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(m.positions, 3))
  if (m.colors) g.setAttribute('color', new THREE.Float32BufferAttribute(m.colors, 3))
  g.setIndex(m.index)
  for (const gr of m.groups) g.addGroup(gr.start, gr.count, gr.materialIndex)
  g.computeVertexNormals()
  g.computeBoundingSphere()
  return g
}

/** Номер зуба на спрайте: рисуется вшитым шрифтом страницы, не системным значком. */
function labelTexture(THREE: Three, n: number, on: boolean): T3.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = 96
  c.height = 96
  const x = c.getContext('2d')
  if (x) {
    x.font = '700 46px Inter, system-ui, sans-serif'
    x.textAlign = 'center'
    x.textBaseline = 'middle'
    x.lineJoin = 'round'
    x.lineWidth = 8
    x.strokeStyle = 'rgba(255,255,255,.92)'
    x.strokeText(String(n), 48, 50)
    x.fillStyle = on ? '#0b6b7a' : '#3b4757'
    x.fillText(String(n), 48, 50)
  }
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

export function createArchScene(opts: SceneOptions): ArchScene {
  const { THREE, container } = opts
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  const canvas = renderer.domElement
  canvas.style.display = 'block'
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  canvas.style.touchAction = 'none'
  canvas.setAttribute('aria-label', 'Odontogramă 3D')
  canvas.tabIndex = 0
  container.appendChild(canvas)

  const scene = new THREE.Scene()
  // свет «Simplu» (прототип 19.10, Олег: «да уже лучше»): форму и блики даёт карта
  // окружения комнаты (`env.ts`), заливка и низ слабее, ключ и контровой сильнее —
  // поверхность читается лаком и бликом, а не ровной заливкой; постобработки нет
  // (тень + SSAO + SMAA прототипа — ×1,9 времени кадра на слабом GPU, отвергнуты)
  scene.add(new THREE.HemisphereLight(0xeef5f7, 0xb9a692, 0.25))
  const key = new THREE.DirectionalLight(0xfff4e8, 1.9)
  key.position.set(40, 80, 90)
  const fill = new THREE.DirectionalLight(0xdfeaf2, 0.35)
  fill.position.set(-70, 20, 50)
  const rim = new THREE.DirectionalLight(0xffffff, 0.7)
  rim.position.set(-20, 40, -120)
  const low = new THREE.DirectionalLight(0xfff4e8, 0.25)
  low.position.set(20, -80, 60)
  scene.add(key, fill, rim, low)
  const envTex = roomEnv(THREE, renderer)
  scene.environment = envTex
  scene.environmentIntensity = 1.1
  renderer.toneMappingExposure = 1.1

  // цвет десны — в вершинах (`gum.ts`: свободная, прикреплённая, слизистая, полоса кармана)
  const gumMat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff, vertexColors: true, roughness: 0.5, metalness: 0, clearcoat: 0.35, clearcoatRoughness: 0.4,
    sheen: 0.45, sheenColor: new THREE.Color(0xffd2cc), sheenRoughness: 0.55, side: THREE.DoubleSide, envMapIntensity: 0.7,
  })
  const upperG = new THREE.Group()
  const lowerG = new THREE.Group()
  scene.add(upperG, lowerG)

  let disposed = false
  let frame = 0
  const invalidate = (): void => {
    if (disposed || frame) return
    frame = requestAnimationFrame(draw)
  }
  const tweens: Tweens = createTweens({ reduced: opts.reduced, wake: invalidate })

  // --- челюсти: смыкание и уход из кадра — оба сдвигом группы ---
  const jaw = {
    upper: { grp: upperG, closeY: 0, hideY: 0, dir: 1 },
    lower: { grp: lowerG, closeY: 0, hideY: 0, dir: -1 },
  }
  const placeJaws = (): void => {
    upperG.position.y = -jaw.upper.closeY + jaw.upper.hideY
    lowerG.position.y = jaw.lower.closeY + jaw.lower.hideY
  }

  // --- зубы ---
  const teeth = new Map<number, ToothNodes>()
  const crowns: T3.Mesh[] = []
  const disposables: { dispose(): void }[] = [gumMat]
  let palette: Record<string, string> = {}
  let selected: number | null = null
  let hover: Hit | null = null
  /** погашенные фильтром легенды; прозрачность коронки у них `DIM` */
  let dimmed: ReadonlySet<number> = new Set()
  const DIM = 0.16
  const togs: Record<Toggle, boolean> = { xray: false, labels: labelsFor('frontal'), upper: true, lower: true, closed: false, rotate: false }
  // живая эмаль сцены: один uniform на все коронки, в «Rădăcini» — выключена (`enamel.ts`)
  const live: EnamelLive = { value: enamelLive(togs.xray) }

  const geomOf = (info: ToothInfo | undefined, upper: boolean): ToothGeom => info?.geom ?? { ...FALLBACK, upper }

  // --- десна по краю зуба и слой пародонта (06.10) ---
  interface JawGum {
    lay: ArchLayout; list: number[]; upper: boolean; grp: T3.Group; mesh: T3.Mesh | null; geo: T3.BufferGeometry | null; marks: T3.Group
    /** габарит челюсти в её системе (коронки по матрицам зубов + тело десны) — камера под окно */
    box: Bounds
  }
  const jawGum: JawGum[] = []
  const shape = new Map<number, { place: PlacedTooth; g: ToothGeom; cm: CrownModel }>()
  let perio: PerioInput | null = null
  let perioVer = 0
  let gumSig = ''
  let siteCol = { deep: linRgb(0xf59e0b), severe: linRgb(0xdc2626) }
  const dotGeo = new THREE.SphereGeometry(0.42, 14, 10)
  const dotMat = new THREE.MeshStandardMaterial({ color: 0xdc2626, emissive: 0x991b1b, emissiveIntensity: 0.45, roughness: 0.35 })
  const probeMat = {
    ok: new THREE.MeshStandardMaterial({ color: 0x64748b, roughness: 0.4, metalness: 0.3 }),
    deep: new THREE.MeshStandardMaterial({ color: 0xf59e0b, roughness: 0.4, metalness: 0.1, emissive: 0x92400e, emissiveIntensity: 0.25 }),
    severe: new THREE.MeshStandardMaterial({ color: 0xdc2626, roughness: 0.4, metalness: 0.1, emissive: 0x7f1d1d, emissiveIntensity: 0.3 }),
  }

  // маркер точки листа под курсором: бирюзовый шарик чуть снаружи края
  const siteGeo = new THREE.SphereGeometry(0.62, 18, 12)
  const siteMat = new THREE.MeshStandardMaterial({ color: COLOR.ringSelected, emissive: COLOR.ringSelected, emissiveIntensity: 0.55, roughness: 0.3 })
  const siteMark = new THREE.Mesh(siteGeo, siteMat)
  siteMark.visible = false
  siteMark.raycast = () => undefined
  let activeSite: { n: number; site: number } | null = null
  function placeSite(): void {
    siteMark.visible = false
    if (!activeSite) return
    const t = gumTooth(activeSite.n)
    const node = teeth.get(activeSite.n)
    if (!t || !node || t.kind !== 'tooth') return
    const th = ((SITE_DEG[activeSite.site] ?? 90) * Math.PI) / 180
    const p = wallPoint(t, th, marginH(t.anchors, th) + 0.2, 1.1)
    const grp = node.group.parent
    if (!grp) return
    if (siteMark.parent !== grp) grp.add(siteMark)
    siteMark.position.set(p[0], p[1], p[2])
    siteMark.visible = true
  }

  const kindOf = (t: ToothNodes | undefined): GumKind => {
    const lk = t?.look
    if (!lk) return 'tooth'
    if (lk.gone) return 'socket'
    if (lk.ghost) return 'missing'
    if (lk.pontic) return 'pontic'
    return 'tooth'
  }
  const ACROSS: Record<number, number> = { 1: 21, 2: 11, 3: 41, 4: 31 }
  const mesialOf = (n: number): number => (n % 10 === 1 ? (ACROSS[Math.floor(n / 10)] ?? 0) : n - 1)
  const distalOf = (n: number): number => (n % 10 < 8 ? n + 1 : 0)

  function gumTooth(n: number): GumTooth | null {
    const info = shape.get(n)
    if (!info) return null
    const { place, g, cm } = info
    const gone = (m: number): boolean => {
      const t = teeth.get(m)
      return !t || kindOf(t) !== 'tooth'
    }
    const row = perio?.rows[String(n)]
    const lim = perio?.limits
    const sites = row && lim
      ? row.pd.map((pd) => (pd >= lim.severe ? siteCol.severe : pd >= lim.deep ? siteCol.deep : null))
      : null
    return {
      n, kind: kindOf(teeth.get(n)), s: place.s, md: g.md, bl: g.bl, root: g.root,
      position: place.position, xAxis: place.xAxis, yAxis: place.yAxis, zAxis: place.zAxis,
      surf: cm.surf,
      anchors: anchorsFor(toCls(g.cls), row ? row.rec : null, gone(mesialOf(n)), gone(distalOf(n))),
      stripe: stripesFor(sites),
    }
  }

  function clearMarks(J: JawGum): void {
    J.marks.traverse((o) => {
      const m = o as T3.Mesh
      if (m.isMesh && m.geometry !== dotGeo) m.geometry.dispose()
    })
    J.marks.clear()
  }

  /** BOP точками на краю; зонды (линия от края вниз на глубину кармана) — видны сквозь прозрачную десну. */
  function buildMarks(J: JawGum, list: GumTooth[]): void {
    clearMarks(J)
    if (!perio) return
    const lim = perio.limits
    const probes = new THREE.Group()
    probes.name = 'probes'
    probes.visible = togs.xray
    for (const t of list) {
      if (t.kind !== 'tooth') continue
      const row = perio.rows[String(t.n)]
      if (!row) continue
      SITE_DEG.forEach((deg, i) => {
        const th = (deg * Math.PI) / 180
        const hm = marginH(t.anchors, th)
        if (row.bop[i] === '1') {
          const p = wallPoint(t, th, hm + 0.1, 0.5)
          const m = new THREE.Mesh(dotGeo, dotMat)
          m.position.set(p[0], p[1], p[2])
          m.raycast = () => undefined
          J.marks.add(m)
        }
        const pd = row.pd[i] ?? 0
        if (pd > 0) {
          const pts: T3.Vector3[] = []
          for (let k = 0; k <= 6; k++) {
            const p = wallPoint(t, th, hm - (pd * k) / 6, 0.32)
            pts.push(new THREE.Vector3(p[0], p[1], p[2]))
          }
          const geo = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 10, 0.17, 6, false)
          const mat = pd >= lim.severe ? probeMat.severe : pd >= lim.deep ? probeMat.deep : probeMat.ok
          const m = new THREE.Mesh(geo, mat)
          m.raycast = () => undefined
          probes.add(m)
        }
      })
    }
    J.marks.add(probes)
  }

  function rebuildGums(): void {
    if (!jawGum.length) return
    const sig = [...teeth.values()].map((t) => t.n + kindOf(t)).join(',') + '|' + perioVer
    if (sig === gumSig) return
    gumSig = sig
    for (const J of jawGum) {
      const list = J.list.map(gumTooth).filter((x): x is GumTooth => x !== null)
      const geo = toGeometry(THREE, buildGum({ A: J.lay.A, D: J.lay.D, apex: J.lay.apex, yBase: J.lay.yBase, occ: J.upper ? -1 : 1, teeth: list }))
      if (J.mesh) {
        J.geo?.dispose()
        J.mesh.geometry = geo
      } else {
        J.mesh = new THREE.Mesh(geo, gumMat)
        J.mesh.raycast = () => undefined
        J.grp.add(J.mesh)
      }
      J.geo = geo
      buildMarks(J, list)
      // габарит для камеры под окно: коронки в системе челюсти (матрица зуба —
      // его место на дуге) и тело десны, под которым стоят корни; сдвиги
      // группы челюсти (смыкание 4 мм, уход из кадра) здесь не учитываются
      const bb = new THREE.Box3()
      for (const n of J.list) {
        const t = teeth.get(n)
        if (!t) continue
        t.crown.geometry.computeBoundingBox()
        const cb = t.crown.geometry.boundingBox
        if (cb) bb.union(cb.clone().applyMatrix4(t.group.matrix))
      }
      geo.computeBoundingBox()
      if (geo.boundingBox) bb.union(geo.boundingBox)
      J.box = { min: [bb.min.x, bb.min.y, bb.min.z], max: [bb.max.x, bb.max.y, bb.max.z] }
    }
    placeSite()
    invalidate()
  }

  function buildArch(model: Odontogram, list: number[], upper: boolean): void {
    const sizes = list.map((n) => ({ n, md: geomOf(model.teeth[String(n)], upper).md }))
    const lay = layoutArch(sizes, upper)
    const grp = upper ? upperG : lowerG
    const models = new Map<number, CrownModel>()
    // окклюзионная плоскость — по вершине коронки-ФОРМУЛЫ первого моляра, даже
    // когда у всех зубов своя модель: дуга и зазор между челюстями рассчитаны под
    // неё, а своя модель анатомически ниже (моляр 7,5 мм до бугра, формула ~9,5;
    // слово Олега 07.10 «сделай по анатомии»). Каждый свой зуб встаёт бугром в
    // эту плоскость, шейка поднимается — и десна вместе с ней (`gum.ts`).
    // Без файла моделей (`teeth.js` не загрузился) — формулы, как до 07.10.
    const poseTip = new Map<number, number>()
    /** вершины коронок-формул — по ним эталонный моляр (плоскость не прыгает) */
    const poseRef = new Map<number, number>()
    for (const n of list) {
      const g = geomOf(model.teeth[String(n)], upper)
      const formula = crownModel(g)
      const tab = opts.teeth?.SCULPT[opts.teeth.SCULPT_OF[n] ?? '']
      const cm = tab ? sculptModel(tab, g) : formula
      // своя модель встаёт по СВОЕЙ вершине: бугры — в общую окклюзионную плоскость
      poseTip.set(n, cm.tip)
      if (!tab) poseRef.set(n, formula.tip)
      models.set(n, cm)
    }
    // окклюзионная плоскость — по вершине первого моляра этой челюсти (он остаётся на месте)
    const ref = (upper ? [16, 26, 17, 27] : [36, 46, 37, 47]).map((n) => poseRef.get(n) ?? crownModel(geomOf(model.teeth[String(n)], upper)).tip)
      .find((x) => x !== undefined) ?? Math.max(...[...poseTip.values()])
    const marks = new THREE.Group()
    grp.add(marks)
    jawGum.push({ lay, list, upper, grp, mesh: null, geo: null, marks, box: EMPTY_BOUNDS })
    for (const p0 of lay.teeth) {
      const g = geomOf(model.teeth[String(p0.n)], upper)
      const cm = models.get(p0.n) as CrownModel
      const p = posed(p0, toCls(g.cls), upper, poseTip.get(p0.n) ?? cm.tip, ref)
      shape.set(p0.n, { place: p, g, cm })
      addTooth(model, p, upper, grp, cm)
    }
  }

  function addTooth(model: Odontogram, p: PlacedTooth, upper: boolean, grp: T3.Group, cm: CrownModel): void {
    const g = geomOf(model.teeth[String(p.n)], upper)
    const hmd = g.md / 2
    const hbl = g.bl / 2
    // эмаль с лаком и тёплым бархатом: блик по форме коронки; цвет вершин — оттенок по высоте
    // (`crown.ts`); отделку поверхности по смыслу (пломба, кариес, коронка, цирконий) ставит `applyLook`
    // живая эмаль (25.10): полупрозрачный край и линия эмаль–цемент в шейдере (`enamel.ts`),
    // доля `natural` — часть отделки, её ставит `applyLook` вместе с остальной
    const tooth = enamelTooth(toCls(g.cls), upper, cm.tip)
    const mats = SURF.map(() => {
      const m = Object.assign(new THREE.MeshPhysicalMaterial({
        color: COLOR.enamel, vertexColors: true, ...physOf(FINISH.enamel),
        sheenColor: new THREE.Color(COLOR.sheenEnamel), sheenRoughness: 0.45,
        emissive: new THREE.Color(COLOR.glow), emissiveIntensity: 0,
      }), { natural: FINISH.enamel.natural })
      attachEnamel(m, tooth, live)
      return m
    })
    const crownGeo = toGeometry(THREE, cm.mesh)
    const crown = new THREE.Mesh(crownGeo, mats)
    crown.userData['n'] = p.n
    crowns.push(crown)
    const rootMat = new THREE.MeshPhysicalMaterial({
      color: COLOR.dentin, ...physOf(FINISH.dentin), sheenColor: new THREE.Color(COLOR.sheenDentin), sheenRoughness: 0.5,
    })
    // корни своей модели (25.10) — по таблице; без неё (молочные, старая таблица) — формула
    const rootsGeo = toGeometry(THREE, cm.roots ?? buildRoots(g, cm.neck))
    const roots = new THREE.Mesh(rootsGeo, rootMat)
    roots.raycast = () => undefined
    const screwGeo = toGeometry(THREE, buildScrew(Math.min(hmd, hbl) * 0.9))
    const screwMat = new THREE.MeshPhysicalMaterial({ color: COLOR.screw, ...physOf(FINISH.titanium) })
    const screw = new THREE.Mesh(screwGeo, screwMat)
    screw.raycast = () => undefined
    // винт виден ВСЕГДА, даже сквозь десну: та же геометрия поверх всего, полупрозрачная, со свечением состояния
    const screwXMat = new THREE.MeshStandardMaterial({
      color: COLOR.titan, roughness: 0.35, metalness: 0.6, transparent: true, opacity: 0.62, depthTest: false, depthWrite: false,
      emissive: new THREE.Color(COLOR.ringImplant), emissiveIntensity: 0.35,
    })
    const screwX = new THREE.Mesh(screwGeo, screwXMat)
    screwX.raycast = () => undefined
    screwX.renderOrder = 5
    // формирователь десны — короткий титановый цилиндр над винтом (имплантат без коронки)
    const capR = Math.min(hmd, hbl) * 0.9 * 0.82
    const capGeo = new THREE.CylinderGeometry(capR * 0.92, capR, CAP_H, 32)
    // свой материал: темнее винта и ПОСЛЕ его полупрозрачной копии (renderOrder 6, прозрачный проход),
    // иначе сквозная копия винта (depthTest false) закрывает формирователь сверху
    const capMat = new THREE.MeshPhysicalMaterial({ color: 0x8a94a3, ...physOf(FINISH.titanium), transparent: true, opacity: 1 })
    const cap = new THREE.Mesh(capGeo, capMat)
    cap.renderOrder = 6
    cap.raycast = () => undefined
    cap.position.y = CAP_Y
    disposables.push(capGeo, capMat)
    const mkRing = (color: number, y: number): T3.Mesh => {
      const geo = new THREE.TorusGeometry(hbl * 1.06, 0.34, 8, 48)
      const mat = new THREE.MeshBasicMaterial({ color })
      const m = new THREE.Mesh(geo, mat)
      m.rotation.x = Math.PI / 2
      m.scale.set(hmd / hbl, 1, 1)
      m.position.y = y
      m.raycast = () => undefined
      disposables.push(geo, mat)
      return m
    }
    // цвет кольца отметки — из палитры сервера (тот же, что у ореола и каналов в 2D); константа — запасной
    const markCol = (k: string, fb: number): number => hex(palette[k] ?? '') || fb
    const ringT = mkRing(markCol('tratament', COLOR.ringMark), 1.6)
    // «nerv extras» — ниже кольца «в работе», над десной (она закрывает шейку на 0,7 мм)
    const ringD = mkRing(markCol('devital', COLOR.ringDevital), 1.0)
    const ringI = mkRing(COLOR.ringImplant, 1.1)
    const ringS = mkRing(COLOR.ringSelected, 2.1)
    const socketGeo = new THREE.CircleGeometry(1, 32)
    const socketMat = new THREE.MeshStandardMaterial({ color: COLOR.socket, roughness: 0.95, metalness: 0 })
    const socket = new THREE.Mesh(socketGeo, socketMat)
    socket.scale.set(hmd * 0.85, hbl * 0.85, 1)
    socket.rotation.x = -Math.PI / 2
    socket.position.y = 0.05
    socket.raycast = () => undefined
    // пунктир шейки над беззубым гребнем (он на 0,4 мм ниже шейки), цветом «Lipsă» палитры, темнее для десны
    const gapGeo = toGeometry(THREE, buildDashedLoop(cm.outline(48), 0.05, 0.2))
    const gapMat = new THREE.MeshBasicMaterial({ color: lerpHex(hex(palette['lipsa'] ?? '#CBD5E1'), 0x64748b, 0.45), transparent: true })
    const gap = new THREE.Mesh(gapGeo, gapMat)
    gap.visible = false
    gap.raycast = () => undefined
    const tex: [T3.CanvasTexture, T3.CanvasTexture] = [labelTexture(THREE, p.n, false), labelTexture(THREE, p.n, true)]
    const spriteMat = new THREE.SpriteMaterial({ map: tex[0], transparent: true, depthTest: true })
    const sprite = new THREE.Sprite(spriteMat)
    sprite.scale.set(LABEL, LABEL, 1)
    sprite.position.set(0, -2.4, 8.8)
    sprite.raycast = () => undefined
    const group = new THREE.Group()
    group.add(crown, roots, screw, screwX, cap, ringT, ringD, ringI, ringS, socket, gap, sprite)
    group.matrixAutoUpdate = false
    group.matrix.makeBasis(
      new THREE.Vector3(...p.xAxis), new THREE.Vector3(...p.yAxis), new THREE.Vector3(...p.zAxis),
    ).setPosition(new THREE.Vector3(...p.position))
    grp.add(group)
    disposables.push(crownGeo, rootsGeo, screwGeo, rootMat, screwMat, screwXMat, socketGeo, socketMat, gapGeo, gapMat, spriteMat, tex[0], tex[1], ...mats)
    teeth.set(p.n, {
      n: p.n, place: p, group, crown, mats, roots, rootMat, screw, screwX, cap, ringT, ringD, ringI, ringS, socket, gap, gapMat, sprite, tex, sx: hmd / hbl, look: null,
    })
  }

  /** Применить вид: мгновенно (первый кадр, смена состояния) или твином по цвету. */
  function applyLook(t: ToothNodes, look: Look, instant: boolean): void {
    t.crown.visible = look.crown
    t.socket.visible = look.socket
    t.gap.visible = look.gap
    t.gapMat.opacity = 1
    t.roots.visible = look.roots
    // девитальный зуб — корни подкрашены цветом отметки (пролеченные каналы), видно сквозь прозрачную десну
    t.rootMat.color.setHex(look.devital ? lerpHex(COLOR.dentin, COLOR.ringDevital, 0.4) : COLOR.dentin)
    t.screw.visible = look.screw
    t.screwX.visible = look.screw
    t.cap.visible = look.cap
    t.crown.position.y = 0
    t.roots.position.y = 0
    screwY(t, 0)
    screwSpin(t, 0)
    t.crown.scale.setScalar(1)
    // полупрозрачная коронка — призрак ИЛИ погашенный фильтром зуб (opacity < 1)
    const see = look.ghost || look.opacity < 1
    t.gapMat.opacity = look.opacity
    const sm = t.socket.material as T3.MeshStandardMaterial
    sm.opacity = look.opacity
    setTransparent(sm, look.opacity < 1)
    const scm = t.screw.material as T3.MeshStandardMaterial
    scm.opacity = look.opacity
    setTransparent(scm, look.opacity < 1)
    ;(t.screwX.material as T3.MeshStandardMaterial).opacity = 0.62 * look.opacity
    ;(t.sprite.material as T3.SpriteMaterial).opacity = look.opacity < 1 ? 0.35 : 1
    // корни гаснут вместе с коронкой: сразу или тем же твином
    const rm = t.rootMat
    if (instant || rm.opacity === look.opacity) {
      rm.opacity = look.opacity
      setTransparent(rm, look.opacity < 1)
    } else {
      const o0 = rm.opacity
      setTransparent(rm, true)
      tweens.add(380, (k) => { rm.opacity = o0 + (look.opacity - o0) * k }, () => setTransparent(rm, look.opacity < 1), 0, t)
    }
    SURF.forEach((_L, i) => {
      const m = t.mats[i]
      const c = look.cols[i]
      const f = look.fin[i]
      if (!m || c === undefined || !f) return
      const target = new THREE.Color(c)
      if (instant) {
        m.color.copy(target)
        setFinish(m, f)
        m.opacity = look.opacity
        setTransparent(m, see)
        m.depthWrite = !see
        return
      }
      const c0 = m.color.clone()
      const f0 = finishOf(m)
      const op0 = m.opacity
      if (c0.equals(target) && sameFinish(f0, f) && op0 === look.opacity) {
        setTransparent(m, see)
        m.depthWrite = !see
        return
      }
      // на время твина прозрачна, только если прозрачность меняется или была/будет < 1:
      // у непрозрачного зуба перекраска не меняет программу шейдера (`setTransparent`)
      setTransparent(m, see || op0 < 1)
      // отделка едет тем же твином, что цвет: лак пломбы проявляется, кариес матовеет
      tweens.add(380, (k) => {
        m.color.copy(c0).lerp(target, k)
        setFinish(m, mixFinish(f0, f, k))
        m.opacity = op0 + (look.opacity - op0) * k
      }, () => {
        setTransparent(m, see)
        m.depthWrite = !see
      }, 0, t)
    })
  }

  const setOpacity = (t: ToothNodes, v: number): void => {
    for (const m of t.mats) {
      setTransparent(m, true)
      m.opacity = v
    }
  }
  const screwY = (t: ToothNodes, y: number): void => {
    t.screw.position.y = y
    t.screwX.position.y = y
    t.cap.position.y = y + CAP_Y
  }
  const screwSpin = (t: ToothNodes, a: number): void => {
    t.screw.rotation.y = a
    t.screwX.rotation.y = a
  }
  function fadeRoots(t: ToothNodes, on: boolean): void {
    const rm = t.rootMat
    setTransparent(rm, true)
    if (on) {
      t.roots.visible = true
      rm.opacity = 0
    }
    const o0 = rm.opacity
    const o1 = on ? 1 : 0
    tweens.add(MS.roots, (k) => { rm.opacity = o0 + (o1 - o0) * k }, () => {
      if (!on) t.roots.visible = false
      rm.opacity = 1
      setTransparent(rm, false)
    }, 0, t)
  }

  /** пунктир пустого места гаснет, когда на место возвращается коронка */
  function gapOut(t: ToothNodes): void {
    const gm = t.gapMat
    tweens.add(MS.socketFade, (k) => { gm.opacity = 1 - k }, () => { t.gap.visible = false; gm.opacity = 1 }, 0, t)
  }

  /** Смена состояния — маленькая сцена (ступень 6): что именно играется, решает
   *  `transition.ts`; в конце всегда `applyLook(…, true)` — вид сходится с данными
   *  независимо от того, дожил твин до конца или его сняли следующей сменой. */
  function animateStruct(t: ToothNodes, prev: Look, look: Look): void {
    tweens.kill(t)
    const finish = (): void => applyLook(t, look, true)
    const from = comesFrom(prev)
    // цвет и отделка нового состояния — до того, как коронка проявится
    const paintCols = (): void => {
      t.mats.forEach((m, i) => {
        const c = look.cols[i]
        const f = look.fin[i]
        if (c !== undefined) m.color.setHex(c)
        if (f) setFinish(m, f)
      })
    }
    switch (sceneFor(look)) {
      case 'screw': {
        // имплантат без коронки: винт вкручивается, формирователь едет с ним; коронка, если была, уходит вверх и тает
        if (t.roots.visible) fadeRoots(t, false)
        t.cap.visible = true
        const crownOut = t.crown.visible
        if (crownOut) {
          const op0 = t.mats[0]?.opacity ?? 1
          // винт уже стоял (коронку сняли) — сцена кончается вместе с коронкой
          tweens.add(MS.ghost, (k) => { t.crown.position.y = 6 * k; setOpacity(t, op0 * (1 - k)) }, prev.screw ? finish : null, 0, t)
        }
        if (prev.screw) {
          if (!crownOut) finish()
          return
        }
        t.screw.visible = true
        t.screwX.visible = true
        screwY(t, 16)
        screwSpin(t, 0)
        tweens.add(MS.screwIn, (k) => { screwY(t, 16 * (1 - k)); screwSpin(t, k * Math.PI * 6) }, finish, 0, t)
        return
      }
      case 'implant': {
        if (prev.cap) {
          // этап 2: винт уже в кости — формирователь снимается, садится коронка
          t.cap.visible = false
          paintCols()
          setOpacity(t, 0)
          tweens.add(MS.crownSeat, (k) => {
            t.crown.visible = true
            t.crown.position.y = 12 * (1 - k)
            setOpacity(t, k)
          }, finish, 0, t)
          return
        }
        if (t.roots.visible) fadeRoots(t, false)
        t.crown.visible = false
        t.screw.visible = true
        t.screwX.visible = true
        screwY(t, 16)
        screwSpin(t, 0)
        tweens.add(MS.screwIn, (k) => { screwY(t, 16 * (1 - k)); screwSpin(t, k * Math.PI * 6) }, null, 0, t)
        paintCols()
        setOpacity(t, 0)
        tweens.add(MS.crownSeat, (k) => {
          t.crown.visible = true
          t.crown.position.y = 12 * (1 - k)
          setOpacity(t, k)
        }, finish, MS.crownSeatDelay, t)
        return
      }
      case 'extract': {
        const rm = t.rootMat
        const rootsOn = t.roots.visible
        setTransparent(rm, true)
        const op0 = t.mats[0]?.opacity ?? 1
        t.socket.visible = true
        const sm = t.socket.material as T3.MeshStandardMaterial
        setTransparent(sm, true)
        sm.opacity = 0
        tweens.add(MS.extract, (k) => {
          t.crown.position.y = 16 * k
          t.roots.position.y = 16 * k
          screwY(t, 16 * k)
          setOpacity(t, op0 * (1 - k))
          if (rootsOn) rm.opacity = 1 - k
          sm.opacity = k
        }, () => { setTransparent(sm, false); sm.opacity = 1; finish() }, 0, t)
        return
      }
      case 'ghost': {
        // отсутствующий: коронка тает целиком, на её месте проявляется пунктир шейки
        const op0 = t.crown.visible ? (t.mats[0]?.opacity ?? 1) : 0
        if (t.roots.visible) fadeRoots(t, false)
        if (t.screw.visible) tweens.add(MS.ghost, (k) => screwY(t, 16 * k), null, 0, t)
        t.gap.visible = true
        t.gapMat.opacity = 0
        tweens.add(MS.ghost, (k) => {
          setOpacity(t, op0 * (1 - k))
          t.gapMat.opacity = k
        }, finish, 0, t)
        return
      }
      case 'gold': {
        if (t.roots.visible && look.pontic) fadeRoots(t, false)
        if (!t.roots.visible && !look.pontic && from !== 'gone' && from !== 'implant') fadeRoots(t, true)
        if (from) {
          t.crown.visible = true
          paintCols()
          setOpacity(t, 0)
          if (from === 'implant') tweens.add(MS.screwOut, (k) => screwY(t, 16 * k), null, 0, t)
          if (from === 'ghost') gapOut(t)
          const lift = startLift(from)
          tweens.add(MS.crownReturn, (k) => {
            t.crown.position.y = lift * (1 - k)
            setOpacity(t, k)
          }, finish, 0, t)
        } else {
          applyLook(t, look, false)
          tweens.add(MS.breath, (k) => t.crown.scale.setScalar(1 + 0.07 * Math.sin(Math.PI * k)),
            () => t.crown.scale.setScalar(1), 0, t)
        }
        return
      }
      default: {
        // живой зуб возвращается: из лунки, из-под импланта, из призрака или из-под коронки
        if (from === 'implant') tweens.add(MS.screwOut, (k) => { screwY(t, 16 * k); screwSpin(t, -k * Math.PI * 6) }, null, 0, t)
        if (from === 'gone') {
          const sm = t.socket.material as T3.MeshStandardMaterial
          setTransparent(sm, true)
          tweens.add(MS.socketFade, (k) => { sm.opacity = 1 - k }, () => { setTransparent(sm, false); sm.opacity = 1 }, 0, t)
        }
        if (!t.roots.visible) fadeRoots(t, true)
        if (from) {
          t.crown.visible = true
          paintCols()
          if (from === 'ghost') gapOut(t)
          const lift = startLift(from)
          setOpacity(t, 0)
          tweens.add(MS.crownReturn, (k) => {
            t.crown.position.y = lift * (1 - k)
            setOpacity(t, k)
          }, finish, 0, t)
        } else {
          applyLook(t, look, false)
        }
      }
    }
  }

  function paintGlow(): void {
    for (const t of teeth.values()) {
      SURF.forEach((L, i) => {
        const m = t.mats[i]
        if (!m) return
        m.emissiveIntensity = hover && hover.n === t.n && hover.letter === L ? 0.16 : t.n === selected ? 0.05 : 0
      })
    }
    invalidate()
  }

  function paint(model: Odontogram): void {
    for (const t of teeth.values()) {
      const info = model.teeth[String(t.n)]
      if (!info) continue
      const look = targetLook(info, palette)
      // в режиме пародонта находки зубов приглушены: красный кариеса спорил бы с
      // красным кармана и кровоточивости; коронка, имплант и отсутствие остаются
      if (perio && !look.gold && !look.implant) {
        look.cols = look.cols.map(() => COLOR.enamel)
        look.fin = look.fin.map(() => FINISH.enamel)
      }
      // гашение — поверх вида данных, но не в данных: `targetLook` чист, фильтр — экрана
      const dim = dimmed.has(t.n)
      if (dim) look.opacity = DIM
      const prev = t.look
      t.look = look
      // номер: слой «Numere» — у всех, у выбранного зуба — всегда и крупнее
      const selNum = t.n === selected
      t.sprite.visible = togs.labels || selNum
      const ls = selNum ? LABEL_SEL : LABEL
      if (t.sprite.scale.x !== ls) t.sprite.scale.set(ls, ls, 1)
      const want = t.tex[selNum ? 1 : 0]
      const sm = t.sprite.material as T3.SpriteMaterial
      if (sm.map !== want) {
        sm.map = want
        sm.needsUpdate = true
      }
      t.ringT.visible = !look.gone && look.mark && !dim
      // у импланта каналов нет — кольцо «nerv extras» там не показывается (и стояло бы вплотную к кольцу импланта)
      t.ringD.visible = !look.gone && !look.implant && !look.cap && look.devital && !dim
      t.ringI.visible = (look.implant || look.cap) && !dim
      const selNow = t.n === selected && !look.gone
      if (selNow && !t.ringS.visible) {
        t.ringS.visible = true
        const sx = t.sx
        tweens.add(220, (k) => {
          const s = 0.55 + 0.45 * k
          t.ringS.scale.set(sx * s, 1, s)
        }, () => t.ringS.scale.set(sx, 1, 1), 0, 'sel')
      } else if (!selNow) {
        t.ringS.visible = false
      }
      if (!prev) applyLook(t, look, true)
      else if (structChanged(prev, look)) animateStruct(t, prev, look)
      // вид не изменился — зуб не трогаем: второй `paint` того же коммита (`setDim`,
      // `setPerio`) иначе обрезал бы идущую сцену смены состояния (`look.sameLook`)
      else if (!sameLook(prev, look)) applyLook(t, look, false)
    }
    rebuildGums()
    paintGlow()
  }

  // --- камера и орбита ---
  // цель орбиты едет так же, как углы и радиус (`tgt` — куда, `target` — где):
  // вид смотрит в середину дуги, фокус (01.10) — в коронку выбранного зуба
  const HOME: [number, number, number] = [0, 0, -16]
  const cam = new THREE.PerspectiveCamera(30, 1, 1, 1000)
  const target = new THREE.Vector3(...HOME)
  const tgt = new THREE.Vector3(...HOME)
  const R0 = 172
  const orb = { theta: 0, phi: rad(VIEWS.frontal[1]), r: R0, tt: 0, tp: rad(VIEWS.frontal[1]), tr: R0 }
  /** радиус вида — подобран под окно (`fitR`); куда возвращается камера из фокуса, база зума */
  let viewR = R0
  /** радиус фокуса на зубе (01.10); null — камера у вида. База для зума. */
  let focusR: number | null = null
  /** габарит челюстей, которые вид показывает (спрятанная не в счёт) */
  const visibleBox = (): Bounds => {
    let box = EMPTY_BOUNDS
    for (const J of jawGum) if (togs[J.upper ? 'upper' : 'lower']) box = union(box, J.box)
    return box
  }
  /** Радиус вида под окно (11.10, `fit.ts`): габарит видимых челюстей занимает
   *  долю FILL кадра по ограничивающей оси. Пока сцена не построена — прежний. */
  const fitR = (theta: number, phi: number): number => {
    const box = visibleBox()
    if (isEmpty(box)) return viewR
    return clamp(fitRadius(box, HOME, theta, phi, cam.fov, cam.aspect), R_MIN, R_MAX)
  }
  let anim = false
  /** довести камеру до цели: твином кадров или сразу при reduced-motion */
  const settle = (): void => {
    if (opts.reduced) {
      orb.theta = orb.tt
      orb.phi = orb.tp
      orb.r = orb.tr
      target.copy(tgt)
      anim = false
    } else {
      anim = true
    }
    invalidate()
  }
  const applyCam = (): void => {
    const sp = Math.sin(orb.phi)
    cam.position.set(
      target.x + orb.r * sp * Math.sin(orb.theta),
      target.y + orb.r * Math.cos(orb.phi),
      target.z + orb.r * sp * Math.cos(orb.theta),
    )
    cam.lookAt(target)
  }

  function draw(now: number): void {
    frame = 0
    if (disposed) return
    const busy = tweens.step(now)
    if (anim) {
      const k = 0.18
      orb.theta += (orb.tt - orb.theta) * k
      orb.phi += (orb.tp - orb.phi) * k
      orb.r += (orb.tr - orb.r) * k
      target.lerp(tgt, k)
      if (Math.abs(orb.tt - orb.theta) < 0.002 && Math.abs(orb.tp - orb.phi) < 0.002 && Math.abs(orb.tr - orb.r) < 0.2
          && target.distanceTo(tgt) < 0.05) {
        orb.theta = orb.tt
        orb.phi = orb.tp
        orb.r = orb.tr
        target.copy(tgt)
        anim = false
      }
    }
    if (togs.rotate && !anim) {
      orb.theta += 0.0035
      orb.tt = orb.theta
    }
    applyCam()
    renderer.render(scene, cam)
    if (anim || busy || togs.rotate) invalidate()
  }

  function setJaw(k: 'upper' | 'lower', on: boolean): void {
    const J = jaw[k]
    togs[k] = on
    const from = J.hideY
    const to = on ? 0 : J.dir * 70
    if (from === to && J.grp.visible === on) return
    tweens.kill('jaw-' + k)
    if (on) J.grp.visible = true
    tweens.add(420, (t) => {
      J.hideY = from + (to - from) * t
      placeJaws()
    }, () => { if (!on) J.grp.visible = false }, 0, 'jaw-' + k)
  }

  function setClosed(on: boolean): void {
    const fu = jaw.upper.closeY
    const fl = jaw.lower.closeY
    const c = on ? (GAP - GAP_CLOSED) / 2 : 0
    tweens.kill('close')
    tweens.add(700, (k) => {
      jaw.upper.closeY = fu + (c - fu) * k
      jaw.lower.closeY = fl + (c - fl) * k
      placeJaws()
    }, null, 0, 'close')
  }

  // --- размер ---
  let lw = 0
  let lh = 0
  function resize(): void {
    if (disposed) return
    const w = Math.max(1, Math.round(container.clientWidth))
    const h = Math.max(1, Math.round(container.clientHeight))
    if (w === lw && h === lh) return
    lw = w
    lh = h
    renderer.setSize(w, h, false)
    cam.aspect = w / h
    cam.updateProjectionMatrix()
    // окно изменилось — вид подгоняется заново (без твина: это не действие
    // человека), доля зума колесом или «−/+» сохраняется множителем
    if (focusR === null) {
      const r = fitR(orb.tt, orb.tp)
      const k = r / viewR
      viewR = r
      orb.tr *= k
      orb.r *= k
    }
    invalidate()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()

  // --- указатель: орбита, наведение, щелчок, правая кнопка ---
  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  const ptrs = new Map<number, [number, number]>()
  let drag = false
  let downX = 0
  let downY = 0
  let moved = false
  let pinch0 = 0
  let r0 = 0
  let slop = 4
  /* долгое нажатие пальцем → меню зуба (iPad не шлёт contextmenu) */
  let longTimer: ReturnType<typeof setTimeout> | null = null
  const stopLong = (): void => {
    if (longTimer) clearTimeout(longTimer)
    longTimer = null
  }

  function pick(ev: { clientX: number; clientY: number }): Hit | null {
    const rc = canvas.getBoundingClientRect()
    if (!rc.width || !rc.height) return null
    ndc.x = ((ev.clientX - rc.left) / rc.width) * 2 - 1
    ndc.y = -((ev.clientY - rc.top) / rc.height) * 2 + 1
    ray.setFromCamera(ndc, cam)
    const visible = crowns.filter((c) => c.visible && c.parent?.parent?.visible)
    const hit = ray.intersectObjects(visible, false)[0]
    if (!hit || !hit.face) return null
    const letter = SURF[hit.face.materialIndex]
    const n = hit.object.userData['n']
    if (letter === undefined || typeof n !== 'number') return null
    return { n, letter }
  }

  function setHover(h: Hit | null): void {
    const same = (h && hover && h.n === hover.n && h.letter === hover.letter) || (!h && !hover)
    if (same) return
    hover = h
    canvas.style.cursor = h ? 'pointer' : 'default'
    paintGlow()
    opts.onHover(h)
  }

  let pend: PointerEvent | null = null
  let hf = 0
  function runHover(): void {
    hf = 0
    const ev = pend
    pend = null
    if (!ev || drag || disposed) return
    setHover(pick(ev))
  }

  const onDown = (ev: PointerEvent): void => {
    canvas.setPointerCapture(ev.pointerId)
    ptrs.set(ev.pointerId, [ev.clientX, ev.clientY])
    if (ptrs.size === 1) {
      drag = true
      moved = false
      downX = ev.clientX
      downY = ev.clientY
      slop = slopOf(ev)
      stopLong()
      if (isFinger(ev)) {
        const x = ev.clientX
        const y = ev.clientY
        longTimer = setTimeout(() => {
          longTimer = null
          if (moved || ptrs.size !== 1) return
          const h = pick({ clientX: x, clientY: y })
          if (!h) return
          moved = true          // отпускание пальца — уже не щелчок
          swallowNextClick()
          opts.onMenu(h.n, x, y)
        }, LONG_MS)
      }
    } else if (ptrs.size === 2) {
      stopLong()
      const a = [...ptrs.values()]
      const p0 = a[0]
      const p1 = a[1]
      if (p0 && p1) {
        pinch0 = Math.hypot(p0[0] - p1[0], p0[1] - p1[1])
        r0 = orb.r
      }
    }
  }
  const onMove = (ev: PointerEvent): void => {
    const prev = ptrs.get(ev.pointerId)
    if (prev) {
      ptrs.set(ev.pointerId, [ev.clientX, ev.clientY])
      if (ptrs.size === 2) {
        const a = [...ptrs.values()]
        const p0 = a[0]
        const p1 = a[1]
        if (p0 && p1 && pinch0 > 0) {
          const d = Math.hypot(p0[0] - p1[0], p0[1] - p1[1])
          orb.r = clamp((r0 * pinch0) / d, R_MIN, R_MAX)
          orb.tr = orb.r
          anim = false
          invalidate()
        }
        moved = true
        return
      }
      const dx = ev.clientX - prev[0]
      const dy = ev.clientY - prev[1]
      if (Math.abs(ev.clientX - downX) > slop || Math.abs(ev.clientY - downY) > slop) {
        moved = true
        stopLong()
      }
      if (moved) {
        orb.theta -= dx * 0.006
        orb.phi = clamp(orb.phi - dy * 0.006, 0.08, Math.PI - 0.08)
        orb.tt = orb.theta
        orb.tp = orb.phi
        anim = false
        opts.onViewLeft()
        invalidate()
      }
      return
    }
    pend = ev
    if (!hf) hf = requestAnimationFrame(runHover)
  }
  const onUp = (ev: PointerEvent): void => {
    if (!ptrs.has(ev.pointerId)) return
    ptrs.delete(ev.pointerId)
    stopLong()
    if (ptrs.size) return
    drag = false
    if (!moved) {
      const h = pick(ev)
      if (h) {
        if (ev.button === 2) opts.onMenu(h.n, ev.clientX, ev.clientY)
        else opts.onPick(h)
      }
    }
  }
  const onLeave = (): void => {
    pend = null
    if (!drag) setHover(null)
  }
  const onWheel = (ev: WheelEvent): void => {
    ev.preventDefault()
    orb.r = clamp(orb.r * (1 + ev.deltaY * 0.0012), R_MIN, R_MAX)
    orb.tr = orb.r
    invalidate()
  }
  const onCtx = (ev: Event): void => ev.preventDefault()
  const onLost = (ev: Event): void => ev.preventDefault()
  /* двойной щелчок — камера к зубу; два одиночных до него уже выбрали зуб (onPick) */
  const onDbl = (ev: MouseEvent): void => {
    const h = pick(ev)
    if (h) opts.onDouble?.(h.n)
  }
  canvas.addEventListener('pointerdown', onDown)
  canvas.addEventListener('dblclick', onDbl)
  canvas.addEventListener('pointermove', onMove)
  canvas.addEventListener('pointerup', onUp)
  canvas.addEventListener('pointercancel', onUp)
  canvas.addEventListener('pointerleave', onLeave)
  canvas.addEventListener('wheel', onWheel, { passive: false })
  canvas.addEventListener('contextmenu', onCtx)
  canvas.addEventListener('webglcontextlost', onLost)

  let built = false
  let lastModel: Odontogram | null = null
  applyCam()

  function bench(n: number): number {
    const gl = renderer.getContext()
    const px = new Uint8Array(4)
    const th = orb.theta
    const t0 = performance.now()
    for (let i = 0; i < n; i++) {
      orb.theta = th + i * 0.01
      applyCam()
      renderer.render(scene, cam)
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px)
    }
    const ms = (performance.now() - t0) / Math.max(1, n)
    orb.theta = th
    invalidate()
    return ms
  }
  // зонд замера — на холсте: узел `__dp3d` собирает компонент, а замер — дело сцены
  ;(canvas as HTMLCanvasElement & { __dpBench?: (n: number) => number }).__dpBench = bench

  return {
    bench,
    inspect(n) {
      const t = teeth.get(n)
      if (!t) return null
      return {
        look: t.look, crown: t.crown.visible, roots: t.roots.visible, screw: t.screw.visible, cap: t.cap.visible, socket: t.socket.visible,
        opacity: t.mats[0]?.opacity ?? 1, y: t.crown.position.y, busy: tweens.has(t),
        label: t.sprite.visible, labelScale: t.sprite.scale.x,
        fin: t.mats.map(finishOf), transparent: t.mats[0]?.transparent ?? false, depthWrite: t.mats[0]?.depthWrite ?? true,
      }
    },
    setModel(model) {
      lastModel = model
      palette = model.palette ?? {}
      if (!built) {
        built = true
        // решение 6 Олега: молочный ряд в 3D первой версии не показывается
        buildArch(model, model.arches.upper, true)
        buildArch(model, model.arches.lower, false)
        placeJaws()
        paint(model)
        // первый кадр — камера под окно (габариты есть после первой покраски: десна построена)
        orb.r = orb.tr = viewR = fitR(orb.tt, orb.tp)
        return
      }
      paint(model)
    },
    setSelected(n) {
      if (n === selected) return
      selected = n
      if (lastModel) paint(lastModel)
    },
    camera() {
      const box = visibleBox()
      return {
        r: orb.r, theta: orb.theta, phi: orb.phi, target: [target.x, target.y, target.z], moving: anim,
        viewR, aspect: cam.aspect,
        fill: isEmpty(box) ? null : fillAt(box, HOME, orb.theta, orb.phi, cam.fov, cam.aspect, orb.r),
      }
    },
    setView(name) {
      const v = VIEWS[name]
      orb.tt = nearestTheta(orb.theta, rad(v[0]))
      orb.tp = rad(v[1])
      focusR = null
      tgt.set(...HOME)
      togs.rotate = false
      // вид на жевательные поверхности одной челюсти невозможен, пока другая
      // стоит перед камерой — и радиус считается уже без неё
      setJaw('upper', name !== 'jos')
      setJaw('lower', name !== 'sus')
      orb.tr = viewR = fitR(orb.tt, orb.tp)
      // номера — по виду (`labelsFor`); кнопка компонента ставит то же
      togs.labels = labelsFor(name)
      if (lastModel) paint(lastModel)
      settle()
    },
    focus(n, how = 'buccal') {
      const t = n !== null ? teeth.get(n) : undefined
      if (t) {
        const upper = t.group.parent === upperG
        const g = lastModel ? geomOf(lastModel.teeth[String(n)], upper) : { ...FALLBACK, upper }
        const f = (how === 'occlusal' ? focusOcclusal : focusOrbit)(t.place, g.crown, (upper ? upperG : lowerG).position.y, upper)
        tgt.set(...f.target)
        orb.tt = nearestTheta(orb.theta, f.theta)
        orb.tp = f.phi
        orb.tr = f.r
        focusR = f.r
        togs.rotate = false
      } else {
        // назад к виду: цель и радиус вида, углы — как человек их оставил
        tgt.set(...HOME)
        orb.tr = viewR
        focusR = null
      }
      settle()
    },
    zoomTo(pct) {
      const base = focusR ?? viewR
      orb.tr = clamp(base * (100 / clamp(pct, 40, 300)), 20, 600)
      settle()
    },
    setToggle(k, on) {
      togs[k] = on
      if (k === 'xray') {
        live.value = enamelLive(on)
        setTransparent(gumMat, on)
        gumMat.opacity = on ? 0.28 : 1
        gumMat.depthWrite = !on
        for (const J of jawGum) {
          const pr = J.marks.getObjectByName('probes')
          if (pr) pr.visible = on
        }
      } else if (k === 'upper' || k === 'lower') {
        setJaw(k, on)
      } else if (k === 'closed') {
        setClosed(on)
      }
      if (lastModel) paint(lastModel)
      invalidate()
    },
    setDim(set) {
      dimmed = set
      if (lastModel) paint(lastModel)
    },
    setActiveSite(n, site) {
      activeSite = n !== null && site !== null ? { n, site } : null
      placeSite()
      invalidate()
    },
    setPerio(p) {
      perio = p
      if (p) {
        // цвета полосы и зондов — те, что прислал сервер; свои — только запасные
        const deep = hex(p.colors.deep) || 0xf59e0b
        const severe = hex(p.colors.severe) || 0xdc2626
        siteCol = { deep: linRgb(deep), severe: linRgb(severe) }
        probeMat.deep.color.setHex(deep)
        probeMat.severe.color.setHex(severe)
      }
      perioVer += 1
      if (lastModel) paint(lastModel)
      rebuildGums()
    },
    invalidate,
    dispose() {
      if (disposed) return
      disposed = true
      if (frame) cancelAnimationFrame(frame)
      if (hf) cancelAnimationFrame(hf)
      stopLong()
      observer.disconnect()
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('dblclick', onDbl)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointercancel', onUp)
      canvas.removeEventListener('pointerleave', onLeave)
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('contextmenu', onCtx)
      canvas.removeEventListener('webglcontextlost', onLost)
      for (const d of disposables) d.dispose()
      for (const J of jawGum) {
        clearMarks(J)
        J.geo?.dispose()
      }
      dotGeo.dispose()
      dotMat.dispose()
      siteGeo.dispose()
      siteMat.dispose()
      for (const m of Object.values(probeMat)) m.dispose()
      envTex?.dispose()
      renderer.dispose()
      // явно отпускаем контекст: браузер держит их считаное число
      renderer.forceContextLoss()
      canvas.remove()
    },
  }
}

/** Длина дуги для тестов и подписей — та же формула, что у сцены. */
export const archLength = (A: number, D: number): number => archCurve(A, D, 0, -1).total
