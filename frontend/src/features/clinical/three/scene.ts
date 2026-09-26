import type * as T3 from 'three'
import type { Odontogram, ToothGeom, ToothInfo } from '../chart'
import { archCurve, buildRidge, GAP, GAP_CLOSED, layoutArch, type PlacedTooth } from './arch'
import type { Three } from './loadThree'
import { COLOR, hex, lerpHex, structChanged, targetLook, type Look } from './look'
import type { RawMesh } from './mesh'
import { buildCrown, buildDashedLoop, buildRoots, buildScrew, neckOutline, SURF, type Letter } from './toothGeometry'
import { comesFrom, MS, sceneFor, startLift } from './transition'
import { createTweens, type Tweens } from './tween'

/* Сцена одонтограммы (B7, ступень 4) — чистый three.js, без React: обе
   челюсти на дуге движка, десна, пять материалов на коронку (= пять
   поверхностей), корни, винт импланта, кольца отметок и выбора, номера.
   THREE приходит снаружи уже загруженным (`loadThree`), поэтому модуль
   импортирует только его ТИПЫ. Кадры — ТОЛЬКО по требованию: `invalidate()`
   просит один кадр, и цепочка живёт, пока идёт твин, переезд камеры или
   вращение по кнопке; в покое — ноль кадров (правило прототипа dental3d).
   Данные не считаются: что видно и какого цвета — `look.targetLook` от модели
   и палитры сервера; сцены смены состояния — ступень 6. */

export const VIEWS = {
  frontal: [0, 80, 172], sus: [0, 152, 180], jos: [0, 28, 180], dreapta: [-62, 82, 175], stanga: [62, 82, 175],
} as const
export type ViewName = keyof typeof VIEWS
export type Toggle = 'xray' | 'labels' | 'upper' | 'lower' | 'closed' | 'rotate'

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
}

export interface ArchScene {
  /** зонд для стендов Edge и разбора; null — такого зуба в сцене нет */
  inspect(n: number): ToothProbe | null
  setModel(model: Odontogram): void
  setSelected(n: number | null): void
  setView(name: ViewName): void
  setToggle(k: Toggle, on: boolean): void
  invalidate(): void
  dispose(): void
}

interface ToothNodes {
  n: number
  group: T3.Group
  crown: T3.Mesh
  mats: T3.MeshStandardMaterial[]
  roots: T3.Mesh
  rootMat: T3.MeshStandardMaterial
  screw: T3.Mesh
  screwX: T3.Mesh
  ringT: T3.Mesh
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
  renderer.toneMappingExposure = 0.95
  const canvas = renderer.domElement
  canvas.style.display = 'block'
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  canvas.style.touchAction = 'none'
  canvas.setAttribute('aria-label', 'Odontogramă 3D')
  canvas.tabIndex = 0
  container.appendChild(canvas)

  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xeef5f7, 0xb9a692, 1.1))
  const key = new THREE.DirectionalLight(0xfff4e8, 2.3)
  key.position.set(40, 80, 90)
  const fill = new THREE.DirectionalLight(0xdfeaf2, 0.9)
  fill.position.set(-70, 20, 50)
  const rim = new THREE.DirectionalLight(0xffffff, 0.7)
  rim.position.set(-20, 40, -120)
  const low = new THREE.DirectionalLight(0xfff4e8, 0.8)
  low.position.set(20, -80, 60)
  scene.add(key, fill, rim, low)

  const gumMat = new THREE.MeshStandardMaterial({ color: COLOR.gum, roughness: 0.78, metalness: 0, side: THREE.DoubleSide })
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
  const togs: Record<Toggle, boolean> = { xray: false, labels: true, upper: true, lower: true, closed: false, rotate: false }

  const geomOf = (info: ToothInfo | undefined, upper: boolean): ToothGeom => info?.geom ?? { ...FALLBACK, upper }

  function buildArch(model: Odontogram, list: number[], upper: boolean): void {
    const sizes = list.map((n) => ({ n, md: geomOf(model.teeth[String(n)], upper).md }))
    const lay = layoutArch(sizes, upper)
    const grp = upper ? upperG : lowerG
    const ridgeGeo = toGeometry(THREE, buildRidge(lay.A, lay.D, lay.apex, lay.yBase, lay.dir))
    const ridge = new THREE.Mesh(ridgeGeo, gumMat)
    ridge.raycast = () => undefined
    grp.add(ridge)
    disposables.push(ridgeGeo)
    for (const p of lay.teeth) addTooth(model, p, upper, grp)
  }

  function addTooth(model: Odontogram, p: PlacedTooth, upper: boolean, grp: T3.Group): void {
    const g = geomOf(model.teeth[String(p.n)], upper)
    const hmd = g.md / 2
    const hbl = g.bl / 2
    const mats = SURF.map(() => new THREE.MeshStandardMaterial({
      color: COLOR.enamel, roughness: 0.32, metalness: 0, emissive: new THREE.Color(COLOR.glow), emissiveIntensity: 0,
    }))
    const crownGeo = toGeometry(THREE, buildCrown(g))
    const crown = new THREE.Mesh(crownGeo, mats)
    crown.userData['n'] = p.n
    crowns.push(crown)
    const rootMat = new THREE.MeshStandardMaterial({ color: COLOR.dentin, roughness: 0.62, metalness: 0 })
    const rootsGeo = toGeometry(THREE, buildRoots(g))
    const roots = new THREE.Mesh(rootsGeo, rootMat)
    roots.raycast = () => undefined
    const screwGeo = toGeometry(THREE, buildScrew(Math.min(hmd, hbl) * 0.9))
    const screwMat = new THREE.MeshStandardMaterial({ color: COLOR.titan, roughness: 0.35, metalness: 0.9 })
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
    const ringT = mkRing(COLOR.ringMark, 1.6)
    const ringI = mkRing(COLOR.ringImplant, 1.1)
    const ringS = mkRing(COLOR.ringSelected, 2.1)
    const socketGeo = new THREE.CircleGeometry(1, 32)
    const socketMat = new THREE.MeshStandardMaterial({ color: COLOR.socket, roughness: 0.95, metalness: 0 })
    const socket = new THREE.Mesh(socketGeo, socketMat)
    socket.scale.set(hmd * 0.85, hbl * 0.85, 1)
    socket.rotation.x = -Math.PI / 2
    socket.position.y = 0.05
    socket.raycast = () => undefined
    // пунктир чуть выше десны (она закрывает шейку на 0,7 мм), цветом «Lipsă» палитры, темнее для десны
    const gapGeo = toGeometry(THREE, buildDashedLoop(neckOutline(g), 1.4, 0.2))
    const gapMat = new THREE.MeshBasicMaterial({ color: lerpHex(hex(palette['lipsa'] ?? '#CBD5E1'), 0x64748b, 0.45), transparent: true })
    const gap = new THREE.Mesh(gapGeo, gapMat)
    gap.visible = false
    gap.raycast = () => undefined
    const tex: [T3.CanvasTexture, T3.CanvasTexture] = [labelTexture(THREE, p.n, false), labelTexture(THREE, p.n, true)]
    const spriteMat = new THREE.SpriteMaterial({ map: tex[0], transparent: true, depthTest: true })
    const sprite = new THREE.Sprite(spriteMat)
    sprite.scale.set(3.9, 3.9, 1)
    sprite.position.set(0, -2.4, 8.8)
    sprite.raycast = () => undefined
    const group = new THREE.Group()
    group.add(crown, roots, screw, screwX, ringT, ringI, ringS, socket, gap, sprite)
    group.matrixAutoUpdate = false
    group.matrix.makeBasis(
      new THREE.Vector3(...p.xAxis), new THREE.Vector3(...p.yAxis), new THREE.Vector3(...p.zAxis),
    ).setPosition(new THREE.Vector3(...p.position))
    grp.add(group)
    disposables.push(crownGeo, rootsGeo, screwGeo, rootMat, screwMat, screwXMat, socketGeo, socketMat, gapGeo, gapMat, spriteMat, tex[0], tex[1], ...mats)
    teeth.set(p.n, {
      n: p.n, group, crown, mats, roots, rootMat, screw, screwX, ringT, ringI, ringS, socket, gap, gapMat, sprite, tex, sx: hmd / hbl, look: null,
    })
  }

  /** Применить вид: мгновенно (первый кадр, смена состояния) или твином по цвету. */
  function applyLook(t: ToothNodes, look: Look, instant: boolean): void {
    t.crown.visible = look.crown
    t.socket.visible = look.socket
    t.gap.visible = look.gap
    t.gapMat.opacity = 1
    t.roots.visible = look.roots
    t.screw.visible = look.screw
    t.screwX.visible = look.screw
    t.crown.position.y = 0
    t.roots.position.y = 0
    screwY(t, 0)
    screwSpin(t, 0)
    t.crown.scale.setScalar(1)
    t.rootMat.opacity = 1
    t.rootMat.transparent = false
    const sm = t.socket.material as T3.MeshStandardMaterial
    sm.opacity = 1
    sm.transparent = false
    SURF.forEach((_L, i) => {
      const m = t.mats[i]
      const c = look.cols[i]
      if (!m || c === undefined) return
      const target = new THREE.Color(c)
      if (instant) {
        m.color.copy(target)
        m.metalness = look.metalness
        m.roughness = look.roughness
        m.opacity = look.opacity
        m.transparent = look.ghost
        m.depthWrite = !look.ghost
        return
      }
      const c0 = m.color.clone()
      const met0 = m.metalness
      const r0 = m.roughness
      const op0 = m.opacity
      if (c0.equals(target) && met0 === look.metalness && op0 === look.opacity) {
        m.roughness = look.roughness
        m.transparent = look.ghost
        m.depthWrite = !look.ghost
        return
      }
      m.transparent = true
      tweens.add(380, (k) => {
        m.color.copy(c0).lerp(target, k)
        m.metalness = met0 + (look.metalness - met0) * k
        m.roughness = r0 + (look.roughness - r0) * k
        m.opacity = op0 + (look.opacity - op0) * k
      }, () => {
        m.transparent = look.ghost
        m.depthWrite = !look.ghost
      }, 0, t)
    })
  }

  const setOpacity = (t: ToothNodes, v: number): void => {
    for (const m of t.mats) {
      m.transparent = true
      m.opacity = v
    }
  }
  const screwY = (t: ToothNodes, y: number): void => {
    t.screw.position.y = y
    t.screwX.position.y = y
  }
  const screwSpin = (t: ToothNodes, a: number): void => {
    t.screw.rotation.y = a
    t.screwX.rotation.y = a
  }
  function fadeRoots(t: ToothNodes, on: boolean): void {
    const rm = t.rootMat
    rm.transparent = true
    if (on) {
      t.roots.visible = true
      rm.opacity = 0
    }
    const o0 = rm.opacity
    const o1 = on ? 1 : 0
    tweens.add(MS.roots, (k) => { rm.opacity = o0 + (o1 - o0) * k }, () => {
      if (!on) t.roots.visible = false
      rm.opacity = 1
      rm.transparent = false
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
    const paintCols = (metal: number, rough: number): void => {
      t.mats.forEach((m, i) => {
        const c = look.cols[i]
        if (c !== undefined) m.color.setHex(c)
        m.metalness = metal
        m.roughness = rough
      })
    }
    switch (sceneFor(look)) {
      case 'implant': {
        if (t.roots.visible) fadeRoots(t, false)
        t.crown.visible = false
        t.screw.visible = true
        t.screwX.visible = true
        screwY(t, 16)
        screwSpin(t, 0)
        tweens.add(MS.screwIn, (k) => { screwY(t, 16 * (1 - k)); screwSpin(t, k * Math.PI * 6) }, null, 0, t)
        paintCols(0, 0.22)
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
        rm.transparent = true
        const op0 = t.mats[0]?.opacity ?? 1
        t.socket.visible = true
        const sm = t.socket.material as T3.MeshStandardMaterial
        sm.transparent = true
        sm.opacity = 0
        tweens.add(MS.extract, (k) => {
          t.crown.position.y = 16 * k
          t.roots.position.y = 16 * k
          screwY(t, 16 * k)
          setOpacity(t, op0 * (1 - k))
          if (rootsOn) rm.opacity = 1 - k
          sm.opacity = k
        }, () => { sm.transparent = false; sm.opacity = 1; finish() }, 0, t)
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
          paintCols(0.85, 0.28)
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
          sm.transparent = true
          tweens.add(MS.socketFade, (k) => { sm.opacity = 1 - k }, () => { sm.transparent = false; sm.opacity = 1 }, 0, t)
        }
        if (!t.roots.visible) fadeRoots(t, true)
        if (from) {
          t.crown.visible = true
          paintCols(0, 0.32)
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
      const prev = t.look
      t.look = look
      t.sprite.visible = togs.labels
      const want = t.tex[t.n === selected ? 1 : 0]
      const sm = t.sprite.material as T3.SpriteMaterial
      if (sm.map !== want) {
        sm.map = want
        sm.needsUpdate = true
      }
      t.ringT.visible = !look.gone && look.mark
      t.ringI.visible = look.implant
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
      else applyLook(t, look, false)
    }
    paintGlow()
  }

  // --- камера и орбита ---
  const cam = new THREE.PerspectiveCamera(30, 1, 1, 1000)
  const target = new THREE.Vector3(0, 0, -16)
  const orb = { theta: 0, phi: rad(80), r: 172, tt: 0, tp: rad(80), tr: 172 }
  let anim = false
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
      if (Math.abs(orb.tt - orb.theta) < 0.002 && Math.abs(orb.tp - orb.phi) < 0.002 && Math.abs(orb.tr - orb.r) < 0.2) {
        orb.theta = orb.tt
        orb.phi = orb.tp
        orb.r = orb.tr
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
    } else if (ptrs.size === 2) {
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
          orb.r = clamp((r0 * pinch0) / d, 70, 420)
          orb.tr = orb.r
          anim = false
          invalidate()
        }
        moved = true
        return
      }
      const dx = ev.clientX - prev[0]
      const dy = ev.clientY - prev[1]
      if (Math.abs(ev.clientX - downX) > 4 || Math.abs(ev.clientY - downY) > 4) moved = true
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
    orb.r = clamp(orb.r * (1 + ev.deltaY * 0.0012), 70, 420)
    orb.tr = orb.r
    invalidate()
  }
  const onCtx = (ev: Event): void => ev.preventDefault()
  const onLost = (ev: Event): void => ev.preventDefault()
  canvas.addEventListener('pointerdown', onDown)
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

  return {
    inspect(n) {
      const t = teeth.get(n)
      if (!t) return null
      return {
        look: t.look, crown: t.crown.visible, roots: t.roots.visible, screw: t.screw.visible, socket: t.socket.visible,
        opacity: t.mats[0]?.opacity ?? 1, y: t.crown.position.y, busy: tweens.has(t),
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
      }
      paint(model)
    },
    setSelected(n) {
      if (n === selected) return
      selected = n
      if (lastModel) paint(lastModel)
    },
    setView(name) {
      const v = VIEWS[name]
      orb.tt = rad(v[0])
      orb.tp = rad(v[1])
      orb.tr = v[2]
      if (opts.reduced) {
        orb.theta = orb.tt
        orb.phi = orb.tp
        orb.r = orb.tr
        anim = false
      } else {
        anim = true
      }
      togs.rotate = false
      // вид на жевательные поверхности одной челюсти невозможен, пока другая стоит перед камерой
      setJaw('upper', name !== 'jos')
      setJaw('lower', name !== 'sus')
      invalidate()
    },
    setToggle(k, on) {
      togs[k] = on
      if (k === 'xray') {
        gumMat.transparent = on
        gumMat.opacity = on ? 0.28 : 1
        gumMat.depthWrite = !on
      } else if (k === 'upper' || k === 'lower') {
        setJaw(k, on)
      } else if (k === 'closed') {
        setClosed(on)
      }
      if (lastModel) paint(lastModel)
      invalidate()
    },
    invalidate,
    dispose() {
      if (disposed) return
      disposed = true
      if (frame) cancelAnimationFrame(frame)
      if (hf) cancelAnimationFrame(hf)
      observer.disconnect()
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointercancel', onUp)
      canvas.removeEventListener('pointerleave', onLeave)
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('contextmenu', onCtx)
      canvas.removeEventListener('webglcontextlost', onLost)
      for (const d of disposables) d.dispose()
      renderer.dispose()
      // явно отпускаем контекст: браузер держит их считаное число
      renderer.forceContextLoss()
      canvas.remove()
    },
  }
}

/** Длина дуги для тестов и подписей — та же формула, что у сцены. */
export const archLength = (A: number, D: number): number => archCurve(A, D, 0, -1).total
