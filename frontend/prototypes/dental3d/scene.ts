import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { buildToothGeometry } from './toothGeometry'
import { SURFACE_ORDER, type SurfaceId } from './surfaces'

/**
 * Сцена прототипа — ЧИСТЫЙ three.js, без единой строки React.
 *
 * ⛔ Почему не react-three-fiber, хотя в задании он назван. Установленный в
 * проекте React — 19.3.0 (frontend/node_modules/react), а `@react-three/fiber`
 * 9.7 объявляет peer `react: ">=19 <19.3"`. CI (.github/workflows/tests.yml)
 * ставит клиент через `npm ci`, который на конфликте peer'ов падает ДО
 * typecheck. Значит цена R3F — либо откат React (правка существующей
 * архитектуры), либо `--legacy-peer-deps` для всего проекта. И то и другое
 * запрещено рамками прототипа, поэтому взят голый three: у него вообще нет
 * peer-зависимостей. Компонент от этого React'овым быть не перестаёт —
 * обёртка `Dental3DViewer` владеет жизненным циклом, а этот модуль знает
 * только про DOM-узел и два колбэка. Когда R3F расширит диапазон peer, слой
 * меняется здесь и только здесь.
 *
 * Кадры рисуются ПО ТРЕБОВАНИЮ: постоянного animation loop нет (Phase 8).
 * Кадр заказывает `invalidate()` — его зовут orbit controls, наведение и
 * ресайз. Инерция камеры сама себя поддерживает: `controls.update()` при
 * затухании снова шлёт 'change', и цепочка гаснет вместе с движением.
 */

export interface ToothSceneOptions {
  container: HTMLElement
  /** Поверхность под курсором изменилась (null — курсор ушёл с зуба). */
  onHover: (surface: SurfaceId | null) => void
  /** Клик по поверхности (не перетаскивание камеры). */
  onSelect: (surface: SurfaceId) => void
}

export interface ToothSceneStats {
  crownTriangles: number
  rootTriangles: number
  vertices: number
}

export interface ToothScene {
  setHovered: (surface: SurfaceId | null) => void
  setSelected: (surface: SurfaceId | null) => void
  resetView: () => void
  stats: ToothSceneStats
  dispose: () => void
}

/* Палитра. Цвета клинические, приглушённые: эмаль тёплая, выделение —
   бирюза движка, а не «кислота». Насыщенность выбрана так, чтобы поверхность
   читалась и на светлой, и на тёмной теме страницы. */
const ENAMEL = 0xe9e1d1
const ENAMEL_HOVER = 0xcfe2e6
const ENAMEL_SELECTED = 0xa5cfd9
const GLOW_HOVER = 0x1f6b7c
const GLOW_SELECTED = 0x0b6b7a
const DENTIN = 0xd6c2a4

const MAX_DPR = 2

export function createToothScene(opts: ToothSceneOptions): ToothScene {
  const { container } = opts

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_DPR))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 0.92
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  const canvas = renderer.domElement
  canvas.style.display = 'block'
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  canvas.style.outline = 'none'
  canvas.setAttribute('aria-hidden', 'true')
  container.appendChild(canvas)

  const scene = new THREE.Scene()

  // Окружение процедурное (RoomEnvironment) — ни одного байта HDRI на диске.
  // Без него физический материал эмали выглядит пластиком.
  const pmrem = new THREE.PMREMGenerator(renderer)
  const envRT = pmrem.fromScene(new RoomEnvironment(), 0.04)
  scene.environment = envRT.texture
  pmrem.dispose()

  const camera = new THREE.PerspectiveCamera(28, 1, 0.5, 400)

  // --- свет -----------------------------------------------------------
  const hemi = new THREE.HemisphereLight(0xeef5f7, 0xb9a692, 0.38)
  scene.add(hemi)

  const key = new THREE.DirectionalLight(0xfff4e8, 1.75)
  key.position.set(14, 26, 20)
  key.castShadow = true
  key.shadow.mapSize.set(1024, 1024)
  key.shadow.bias = -0.0012
  key.shadow.normalBias = 0.35
  const cam = key.shadow.camera
  cam.left = -18
  cam.right = 18
  cam.top = 22
  cam.bottom = -22
  cam.near = 6
  cam.far = 80
  cam.updateProjectionMatrix()
  scene.add(key)

  const fill = new THREE.DirectionalLight(0xdfeaf2, 0.5)
  fill.position.set(-20, 6, 14)
  scene.add(fill)

  const rim = new THREE.DirectionalLight(0xffffff, 0.7)
  rim.position.set(-6, 12, -24)
  scene.add(rim)

  // --- зуб --------------------------------------------------------------
  const built = buildToothGeometry()

  /** Пять материалов = пять групп геометрии. Индекс материала == индекс
   *  поверхности в SURFACE_ORDER, поэтому подсветка — это одно присваивание
   *  без перестройки сцены и без перерисовки React-дерева. */
  const enamel = SURFACE_ORDER.map(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: ENAMEL,
        roughness: 0.30,
        metalness: 0,
        clearcoat: 0.45,
        clearcoatRoughness: 0.20,
        sheen: 0.25,
        sheenColor: new THREE.Color(0xfff2e0),
        envMapIntensity: 0.9,
        emissive: new THREE.Color(GLOW_HOVER),
        emissiveIntensity: 0,
      }),
  )

  const crown = new THREE.Mesh(built.crown, enamel)
  crown.castShadow = true
  crown.receiveShadow = true

  const rootMat = new THREE.MeshPhysicalMaterial({
    color: DENTIN,
    roughness: 0.62,
    metalness: 0,
    clearcoat: 0.12,
    envMapIntensity: 0.55,
  })
  const roots = new THREE.Mesh(built.roots, rootMat)
  roots.castShadow = true
  roots.receiveShadow = true
  // Корни не кликабельны: прототип проверяет ПЯТЬ поверхностей коронки.
  roots.raycast = () => {}

  const tooth = new THREE.Group()
  tooth.add(crown, roots)
  scene.add(tooth)

  // Модель центрируется по своей же габаритной коробке: числа в геометрии
  // можно менять, кадрирование не поедет.
  const box = new THREE.Box3().setFromObject(tooth)
  const centre = box.getCenter(new THREE.Vector3())
  tooth.position.sub(centre)
  const size = box.getSize(new THREE.Vector3())

  // Тень-подложка: мягкое пятно под верхушками корней, без «пола».
  const shadowPlane = new THREE.Mesh(
    new THREE.CircleGeometry(size.x * 1.9, 64),
    new THREE.ShadowMaterial({ opacity: 0.17 }),
  )
  shadowPlane.rotation.x = -Math.PI / 2
  shadowPlane.position.y = -size.y / 2 - 1.2
  shadowPlane.receiveShadow = true
  scene.add(shadowPlane)

  // --- камера и орбита ---------------------------------------------------
  // Цель чуть выше центра: смысловой объект — коронка, а не корни.
  const target = new THREE.Vector3(0, size.y * 0.10, 0)
  const radius = size.y * 2.55
  camera.position.set(radius * 0.40, target.y + radius * 0.32, radius * 0.86)

  const controls = new OrbitControls(camera, canvas)
  controls.target.copy(target)
  controls.enableDamping = true
  controls.dampingFactor = 0.085
  controls.rotateSpeed = 0.85
  controls.zoomSpeed = 0.8
  controls.panSpeed = 0.7
  controls.enablePan = true
  controls.screenSpacePanning = true
  controls.minDistance = size.y * 0.75
  controls.maxDistance = size.y * 4
  controls.minPolarAngle = 0.12
  controls.maxPolarAngle = Math.PI - 0.12
  controls.update()
  controls.saveState()

  // --- кадры по требованию ------------------------------------------------
  let frame = 0
  let disposed = false

  function render() {
    frame = 0
    if (disposed) return
    const moving = controls.update()
    renderer.render(scene, camera)
    // Инерция ещё гасится — нужен следующий кадр. Остановилась — цикла нет.
    if (moving) invalidate()
  }

  function invalidate() {
    if (disposed || frame) return
    frame = requestAnimationFrame(render)
  }

  controls.addEventListener('change', invalidate)

  // --- размер --------------------------------------------------------------
  let lastW = 0
  let lastH = 0

  function resize() {
    if (disposed) return
    const w = Math.max(1, Math.round(container.clientWidth))
    const h = Math.max(1, Math.round(container.clientHeight))
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR)
    if (w === lastW && h === lastH && dpr === renderer.getPixelRatio()) return
    lastW = w
    lastH = h
    renderer.setPixelRatio(dpr)
    // `false`: размеры canvas задаёт CSS, иначе three вписал бы свои px и
    // контейнер прыгал бы на каждый ресайз — ровно тот flicker, которого
    // просили не добавлять.
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    invalidate()
  }

  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()

  // --- выбор поверхности ----------------------------------------------------
  const raycaster = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  let hovered: SurfaceId | null = null
  let selected: SurfaceId | null = null

  function paint() {
    const hoverSlot = hovered ? SURFACE_ORDER.indexOf(hovered) : -1
    const selectSlot = selected ? SURFACE_ORDER.indexOf(selected) : -1
    for (let i = 0; i < enamel.length; i += 1) {
      const m = enamel[i]
      if (!m) continue
      const isSel = i === selectSlot
      const isHot = i === hoverSlot
      m.color.setHex(isSel ? ENAMEL_SELECTED : isHot ? ENAMEL_HOVER : ENAMEL)
      m.emissive.setHex(isSel ? GLOW_SELECTED : GLOW_HOVER)
      m.emissiveIntensity = isSel ? (isHot ? 0.34 : 0.26) : isHot ? 0.10 : 0
    }
    invalidate()
  }

  function pick(ev: PointerEvent): SurfaceId | null {
    const rect = canvas.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) return null
    ndc.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1
    ndc.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1
    raycaster.setFromCamera(ndc, camera)
    const hit = raycaster.intersectObject(crown, false)[0]
    const faceIndex = hit?.faceIndex
    if (faceIndex === undefined || faceIndex === null) return null
    const slot = built.faceSurface[faceIndex]
    if (slot === undefined) return null
    return SURFACE_ORDER[slot] ?? null
  }

  /* Наведение считается не чаще кадра: pointermove приходит сотнями в
     секунду, а луч и React-состояние столько раз в секунду не нужны. */
  let pendingMove: PointerEvent | null = null
  let hoverFrame = 0

  function runHover() {
    hoverFrame = 0
    const ev = pendingMove
    pendingMove = null
    if (!ev || disposed) return
    const next = pick(ev)
    canvas.style.cursor = next ? 'pointer' : 'default'
    if (next === hovered) return
    hovered = next
    paint()
    opts.onHover(next)
  }

  function onPointerMove(ev: PointerEvent) {
    pendingMove = ev
    if (!hoverFrame) hoverFrame = requestAnimationFrame(runHover)
  }

  function onPointerLeave() {
    pendingMove = null
    canvas.style.cursor = 'default'
    if (hovered === null) return
    hovered = null
    paint()
    opts.onHover(null)
  }

  // Клик — только если это не было вращением камеры.
  let downX = 0
  let downY = 0
  let downId = -1

  function onPointerDown(ev: PointerEvent) {
    downX = ev.clientX
    downY = ev.clientY
    downId = ev.pointerId
  }

  function onPointerUp(ev: PointerEvent) {
    if (ev.pointerId !== downId) return
    downId = -1
    if (Math.abs(ev.clientX - downX) > 4 || Math.abs(ev.clientY - downY) > 4) return
    const surface = pick(ev)
    if (surface) opts.onSelect(surface)
  }

  function onContextLost(ev: Event) {
    // Без preventDefault браузер не восстановит контекст никогда.
    ev.preventDefault()
    console.warn('Dental3D: WebGL-контекст потерян')
  }

  canvas.addEventListener('pointermove', onPointerMove)
  canvas.addEventListener('pointerleave', onPointerLeave)
  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('pointerup', onPointerUp)
  canvas.addEventListener('webglcontextlost', onContextLost)

  invalidate()

  return {
    stats: built.stats,
    setHovered(surface) {
      if (surface === hovered) return
      hovered = surface
      paint()
    },
    setSelected(surface) {
      if (surface === selected) return
      selected = surface
      paint()
    },
    resetView() {
      controls.reset()
      invalidate()
    },
    dispose() {
      if (disposed) return
      disposed = true
      if (frame) cancelAnimationFrame(frame)
      if (hoverFrame) cancelAnimationFrame(hoverFrame)
      observer.disconnect()
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerleave', onPointerLeave)
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('webglcontextlost', onContextLost)
      controls.removeEventListener('change', invalidate)
      controls.dispose()
      built.crown.dispose()
      built.roots.dispose()
      shadowPlane.geometry.dispose()
      shadowPlane.material.dispose()
      for (const m of enamel) m.dispose()
      rootMat.dispose()
      envRT.dispose()
      scene.environment = null
      renderer.dispose()
      // Явно отпускаем контекст: браузер держит их считаное число (обычно 16),
      // а StrictMode в dev монтирует компонент дважды.
      renderer.forceContextLoss()
      canvas.remove()
    },
  }
}
