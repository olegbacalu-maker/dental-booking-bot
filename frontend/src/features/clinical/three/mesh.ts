/* Сырая сетка без three.js (B7, ступень 3). three грузится по требованию
   (`loadThree`), поэтому модули геометрии его не импортируют: они отдают
   буферы, а сцена (ступень 4) делает из них BufferGeometry уже загруженным
   THREE. Так геометрия проверяется Vitest в jsdom без WebGL, а в бандл не
   попадает ни байта three. Группы — диапазоны индексов на материал: у коронки
   пять групп в порядке поверхностей O V L M D (`toothGeometry.SURF`), и
   `face.materialIndex` пикинга — это буква поверхности. */
export interface MeshGroup {
  start: number
  count: number
  materialIndex: number
}

export interface RawMesh {
  /** x y z подряд */
  positions: number[]
  /** тройки вершин */
  index: number[]
  groups: MeshGroup[]
}

export const triangles = (m: RawMesh): number => m.index.length / 3
export const vertices = (m: RawMesh): number => m.positions.length / 3

/** Одна группа на всю сетку. */
export function oneGroup(positions: number[], index: number[]): RawMesh {
  return { positions, index, groups: [{ start: 0, count: index.length, materialIndex: 0 }] }
}

/** Тело вращения вокруг оси y из профиля `[радиус, y]…` — замена
 *  THREE.LatheGeometry, которой у нас нет до загрузки three. */
export function lathe(profile: [number, number][], segments: number): RawMesh {
  const positions: number[] = []
  const index: number[] = []
  const cols = segments + 1
  for (const [r, y] of profile) {
    for (let j = 0; j <= segments; j++) {
      const th = (2 * Math.PI * j) / segments
      positions.push(Math.cos(th) * r, y, Math.sin(th) * r)
    }
  }
  for (let i = 0; i < profile.length - 1; i++) {
    for (let j = 0; j < segments; j++) {
      const a = i * cols + j
      const b = a + 1
      const c = a + cols
      const d = c + 1
      index.push(a, c, b, b, c, d)
    }
  }
  return oneGroup(positions, index)
}

/** Все координаты — числа (не NaN и не бесконечность): сетка с дырой в
 *  данных рисуется молча пустой, поэтому это проверка, а не предположение. */
export function finite(m: RawMesh): boolean {
  return m.positions.every(Number.isFinite) && m.index.every((i) => Number.isInteger(i) && i >= 0 && i < m.positions.length / 3)
}
