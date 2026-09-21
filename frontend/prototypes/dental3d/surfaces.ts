/**
 * Пять поверхностей зуба — единственный словарь прототипа.
 *
 * `letter` — та же буква, которой поверхности зовёт движок DentPilot
 * (`Odontogram.surfaces`, `ToothInfo.sf`, цели `data-s` в серверном SVG:
 * M / O / D / V / L). Прототип НИЧЕГО не сохраняет и в API не ходит, но имена
 * совпадают заранее — иначе при интеграции пришлось бы заводить второй
 * словарь, чего клинический контракт не допускает.
 *
 * Для верхней челюсти язычная поверхность на экране называется нёбной
 * («P»), ключ данных остаётся «L» — правило `surfaceLetter()` из
 * src/features/clinical/chart.ts. Зуб 16 верхний, поэтому здесь `display: 'P'`.
 */
export type SurfaceId = 'occlusal' | 'buccal' | 'lingual' | 'mesial' | 'distal'

export interface SurfaceMeta {
  id: SurfaceId
  /** Буква канона DentPilot (ключ данных). */
  letter: 'O' | 'V' | 'L' | 'M' | 'D'
  /** Буква на экране: у верхней челюсти L показывается как P. */
  display: string
  /** Подпись прототипа (английская — так в ТЗ на этот этап). */
  label: string
  /** Клиническое имя, как его пишет движок на румынском. */
  ro: string
}

/** Порядок — клинический: жевательная, щёчная, нёбная, медиальная, дистальная. */
export const SURFACES: readonly SurfaceMeta[] = [
  { id: 'occlusal', letter: 'O', display: 'O', label: 'Occlusal', ro: 'ocluzal' },
  { id: 'buccal', letter: 'V', display: 'V', label: 'Buccal', ro: 'vestibular' },
  { id: 'lingual', letter: 'L', display: 'P', label: 'Lingual', ro: 'palatinal' },
  { id: 'mesial', letter: 'M', display: 'M', label: 'Mesial', ro: 'mezial' },
  { id: 'distal', letter: 'D', display: 'D', label: 'Distal', ro: 'distal' },
]

/** Порядок групп в геометрии = порядок материалов меша. Один источник истины. */
export const SURFACE_ORDER: readonly SurfaceId[] = SURFACES.map((s) => s.id)

const BY_ID = new Map<SurfaceId, SurfaceMeta>(SURFACES.map((s) => [s.id, s]))

export function surfaceMeta(id: SurfaceId): SurfaceMeta {
  const meta = BY_ID.get(id)
  if (!meta) throw new Error(`Неизвестная поверхность: ${id}`)
  return meta
}
