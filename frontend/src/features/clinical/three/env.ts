import type * as T3 from 'three'
import type { Three } from './loadThree'

/* Окружение для отражений (06.10) —
   маленькая «студия» из светлых панелей, свёрнутая PMREM в карту окружения.
   Эмаль получает мягкий блик по форме, золото коронки — отражение, а не
   плоскую заливку. Ноль ассетов: панели — коробки ядра three. */
export function studioEnv(THREE: Three, renderer: T3.WebGLRenderer): T3.Texture {
  const scene = new THREE.Scene()
  const box = new THREE.BoxGeometry(1, 1, 1)
  const mats: T3.Material[] = []
  const add = (c: [number, number, number], p: [number, number, number], s: [number, number, number], side?: T3.Side): void => {
    const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(c[0], c[1], c[2]), ...(side !== undefined ? { side } : {}) })
    mats.push(m)
    const mesh = new THREE.Mesh(box, m)
    mesh.position.set(p[0], p[1], p[2])
    mesh.scale.set(s[0], s[1], s[2])
    scene.add(mesh)
  }
  add([0.3, 0.31, 0.33], [0, 0, 0], [44, 34, 44], THREE.BackSide)
  add([7.2, 6.9, 6.4], [0, 15, 2], [20, 0.5, 14])
  add([3.6, 3.5, 3.3], [-19, 5, 6], [0.5, 12, 16])
  add([2.8, 2.8, 2.7], [19, 4, 4], [0.5, 9, 12])
  add([2.4, 2.4, 2.4], [0, 3, 20], [18, 9, 0.5])
  add([0.9, 0.85, 0.82], [0, -15, 0], [34, 0.5, 34])
  const pm = new THREE.PMREMGenerator(renderer)
  const tex = pm.fromScene(scene, 0.035).texture
  pm.dispose()
  box.dispose()
  for (const m of mats) m.dispose()
  return tex
}
