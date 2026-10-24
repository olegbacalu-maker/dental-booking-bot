import type * as T3 from 'three'
import type { Three } from './loadThree'

/* Окружение для отражений — «комната» (вид «Simplu», прототип 19.10, в продукте
   с 24.10; до того — студия из пяти панелей, 06.10). Перенос КОДОМ класса
   `RoomEnvironment` из three r180 (`examples/jsm/environments/RoomEnvironment.js`,
   MIT, © 2010-2025 three.js authors; он сам — EnvironmentScene из
   google/model-viewer): аддонов в `three.module.min.js`, который грузит
   `loadThree`, нет, а отдельный файл рядом с бандлом прописывался бы в четырёх
   местах (vite.config.ts, оба игнора, demo/Dockerfile). Числа — как в r180.
   Комната с шестью коробками и шестью светящимися панелями сворачивается PMREM в
   карту окружения: эмаль и лак получают мягкие блики по форме, металл коронки и
   титан винта — отражение. Ноль ассетов; сцена комнаты живёт только на время
   свёртки. THREE приходит параметром — модуль импортирует только типы. */

/** лампа под потолком: положение, сила, дальность, затухание */
const ROOM_LAMP = [0.418, 16.199, 0.3, 900, 28, 2] as const
/** стены комнаты (коробка изнутри): положение, размер */
const ROOM_WALLS = [-0.757, 13.219, 0.717, 31.713, 28.305, 28.591] as const

/** коробка «мебели»: положение, поворот вокруг y, размер */
const ROOM_BOXES: readonly (readonly [number, number, number, number, number, number, number])[] = [
  [-10.906, 2.009, 1.846, -0.195, 2.328, 7.905, 4.651],
  [-5.607, -0.754, -0.758, 0.994, 1.97, 1.534, 3.955],
  [6.167, 0.857, 7.803, 0.561, 3.927, 6.285, 3.687],
  [-2.017, 0.018, 6.124, 0.333, 2.002, 4.566, 2.064],
  [2.291, -0.756, -2.621, -0.286, 1.546, 1.552, 1.496],
  [-2.193, -0.369, -5.547, 0.516, 3.875, 3.487, 2.986],
]

/** панель света: яркость свечения, положение, размер */
const ROOM_PANELS: readonly (readonly [number, number, number, number, number, number, number])[] = [
  [50, -16.116, 14.37, 8.208, 0.1, 2.428, 2.739], // −x справа
  [50, -16.109, 18.021, -8.207, 0.1, 2.425, 2.751], // −x слева
  [17, 14.904, 12.198, -1.832, 0.15, 4.265, 6.331], // +x
  [43, -0.462, 8.89, 14.52, 4.38, 5.441, 0.088], // +z
  [20, 3.235, 11.486, -12.541, 2.5, 2.0, 0.1], // −z
  [100, 0, 20, 0, 1, 0.1, 1], // +y
]

export function roomEnv(THREE: Three, renderer: T3.WebGLRenderer): T3.Texture {
  const room = new THREE.Scene()
  const box = new THREE.BoxGeometry()
  box.deleteAttribute('uv')
  const wallMat = new THREE.MeshStandardMaterial({ side: THREE.BackSide })
  const boxMat = new THREE.MeshStandardMaterial()
  const mats: T3.Material[] = [wallMat, boxMat]

  const [lx, ly, lz, li, ld, lk] = ROOM_LAMP
  const lamp = new THREE.PointLight(0xffffff, li, ld, lk)
  lamp.position.set(lx, ly, lz)
  room.add(lamp)

  const [wx, wy, wz, wsx, wsy, wsz] = ROOM_WALLS
  const walls = new THREE.Mesh(box, wallMat)
  walls.position.set(wx, wy, wz)
  walls.scale.set(wsx, wsy, wsz)
  room.add(walls)

  const boxes = new THREE.InstancedMesh(box, boxMat, ROOM_BOXES.length)
  const tr = new THREE.Object3D()
  ROOM_BOXES.forEach(([x, y, z, ry, sx, sy, sz], i) => {
    tr.position.set(x, y, z)
    tr.rotation.set(0, ry, 0)
    tr.scale.set(sx, sy, sz)
    tr.updateMatrix()
    boxes.setMatrixAt(i, tr.matrix)
  })
  room.add(boxes)

  // панель — только свечение (three #31348): чёрный цвет, белое излучение
  for (const [e, x, y, z, sx, sy, sz] of ROOM_PANELS) {
    const m = new THREE.MeshLambertMaterial({ color: 0x000000, emissive: 0xffffff, emissiveIntensity: e })
    mats.push(m)
    const p = new THREE.Mesh(box, m)
    p.position.set(x, y, z)
    p.scale.set(sx, sy, sz)
    room.add(p)
  }

  const pm = new THREE.PMREMGenerator(renderer)
  const tex = pm.fromScene(room, 0.04).texture
  pm.dispose()
  boxes.dispose()
  box.dispose()
  for (const m of mats) m.dispose()
  return tex
}
