import { api } from '../../services/api'

/* Клинический модуль (docs/dentpilot-2/clinical-chart.md). Формы ответов —
   bot/app/modules/patients/api.py (`_odontogram`) и odontogram.model:
   сервер владеет клинической истиной и геометрией (SVG зуба с целями
   поверхностей `data-s`), клиент — композицией и интерактивом. Второго
   словаря состояний и второй геометрии здесь нет. */

export type View = 'frontal' | 'ocluzal'
export type Jaw = 'sus' | 'jos'

export interface ToothInfo {
  jaw: Jaw
  /** Где мезиальная сторона на экране — считает сервер по квадранту. */
  mez: 'left' | 'right'
  state: string
  note: string
  doctor: string
  /** Дата последней записи dd.mm.yyyy, пусто у нетронутого. */
  at: string
  /** Буквы поверхностей в каноне («MO»). */
  sf: string
  /** Подпись поверхностей словами сервера («Carie (M), Obturație (O)» или буквы). */
  sfx: string
  /** Состояние на поверхность. */
  sfst: Record<string, string>
  mk: string[]
  mkx: string
  milk: boolean
  /** Подпись зуба словами — та же, что title кнопки старой страницы. */
  title: string
  bridge: { role: string; material: string } | null
  svg: { frontal: string; occlusal: string }
}

export interface Bridge {
  id: number
  teeth: [number, string][]
  material: string
  doctor: string
}

export interface LegendItem {
  kind: 'state' | 'mark'
  key: string
  label: string
  svg: string
}

export interface ArchRows {
  upper: number[]
  lower: number[]
  milk_upper: number[]
  milk_lower: number[]
}

export interface Odontogram {
  teeth: Record<string, ToothInfo>
  history: Record<string, { at: string; text: string }[]>
  arches: ArchRows
  /** Подъём зуба в виде сверху, px, по позиции в ряду. */
  arc: ArchRows
  milk_open: boolean
  bridges: Bridge[]
  legend: { frontal: LegendItem[]; occlusal: LegendItem[] }
  states: Record<string, string>
  marks: Record<string, string>
  surfaces: Record<string, string>
  surface_states: string[]
  bridge_roles: Record<string, string>
  materials: { id: string; label: string }[]
  patient: { id: number; name: string; primary_doctor: string }
  doctors: string[]
}

/** Запись зуба — намерение явным полем: `surfaces` всегда карта (форма
 *  знает поверхности), `marks` всегда список (форма знает отметки),
 *  `state0` — состояние, каким его показала форма. */
export interface ToothSave {
  state: string
  state0: string
  note: string
  doctor: string
  surfaces: Record<string, string>
  marks: string[]
}

export interface BridgeSave {
  teeth: [number, string][]
  material: string
  material_alt: string
  doctor: string
}

/** Подпись поверхности на экране: у верхней челюсти язычная — нёбная, «P»;
 *  ключ данных остаётся «L» (решение Олега 18.09). */
export function surfaceLetter(letter: string, jaw: Jaw): string {
  return letter === 'L' && jaw === 'sus' ? 'P' : letter
}

export function surfaceName(letter: string, jaw: Jaw, names: Record<string, string>): string {
  if (letter === 'L' && jaw === 'sus') return 'palatinal'
  return names[letter] ?? letter
}

/** Выбор вида ПЕРЕЖИВАЕТ перезагрузку и запуск программы — тот же ключ,
 *  что у скрипта старой страницы. */
export const VIEW_KEY = 'dp_odo_view'

export function savedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'ocluzal' ? 'ocluzal' : 'frontal'
  } catch {
    return 'frontal'
  }
}

export function rememberView(v: View) {
  try {
    localStorage.setItem(VIEW_KEY, v)
  } catch {
    /* приватный режим */
  }
}

export const JAW_RO: Record<Jaw, string> = { sus: 'Maxilar', jos: 'Mandibular' }

const P = (pid: number) => `/patients/${pid}`

export const chart = {
  get: (pid: number, signal?: AbortSignal) =>
    api.get<Odontogram>(`${P(pid)}/odontogram`, signal ? { signal } : {}),
  saveTooth: (pid: number, n: number, body: ToothSave) =>
    api.post<Odontogram>(`${P(pid)}/teeth/${n}`, body),
  addBridge: (pid: number, body: BridgeSave) =>
    api.post<Odontogram>(`${P(pid)}/bridges`, body),
  delBridge: (pid: number, bid: number) =>
    api.post<Odontogram>(`${P(pid)}/bridges/${bid}/delete`, {}),
}

/** Мост, в котором стоит зуб, и его роль там. */
export function bridgeOf(model: Odontogram, n: number): { bridge: Bridge; role: string } | null {
  for (const b of model.bridges) {
    const t = b.teeth.find((x) => x[0] === n)
    if (t) return { bridge: b, role: t[1] }
  }
  return null
}

/** Индекс зуба в порядке дуги (верхняя, потом нижняя) — для сортировки
 *  выбранных зубов моста в порядке кликов → в порядок ряда. */
export function archIndex(model: Odontogram, n: number): number {
  const u = model.arches.upper.indexOf(n)
  return u >= 0 ? u : 100 + model.arches.lower.indexOf(n)
}
