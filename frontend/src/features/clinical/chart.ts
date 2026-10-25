import { api } from '../../services/api'

/* Клинический модуль (docs/dentpilot-2/clinical-chart.md). Формы ответов —
   bot/app/modules/patients/api.py (`_odontogram`) и odontogram.model:
   сервер владеет клинической истиной и геометрией (SVG зуба с целями
   поверхностей `data-s`), клиент — композицией и интерактивом. Второго
   словаря состояний и второй геометрии здесь нет. */

/** Вид одонтограммы: два рисунка сервера и объёмный (B7); 2D-компоненты
 *  различают только «ocluzal», для них 3D — то же, что frontal. */
export type View = 'frontal' | 'ocluzal' | '3d'
export type Jaw = 'sus' | 'jos'

/** Что нужно, чтобы НАРИСОВАТЬ зуб, и ничего сверх того: рисунок сервера и
 *  готовая подпись. Пародонтограмма даёт компоненту `Tooth` ровно это —
 *  второго рисовальщика зуба в клиенте не будет (контракт clinical-chart.md). */
export interface ToothVisual {
  /** Подпись зуба словами — та же, что title кнопки старой страницы. */
  title: string
  svg: { frontal: string; occlusal: string }
}

/** Размеры зуба для объёмного вида, мм, — с сервера (`teeth_svg.tooth_geom`):
 *  клиент строит по ним форму, но ничего клинического не считает (B7). */
export interface ToothGeom {
  md: number
  bl: number
  crown: number
  root: number
  roots: number
  cls: string
  upper: boolean
}

export interface ToothInfo extends ToothVisual {
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
  /** Название по позиции («Incisiv central») и сторона пациента («dreapta»/
   *  «stânga») — слова сервера для панели зуба (08.10, макет). */
  name?: string
  side?: string
  bridge: { role: string; material: string } | null
  /** есть у каждого зуба модели с B7 ступени 1; необязателен, пока 3D не читает его */
  geom?: ToothGeom
}

/** Строка зуба последнего осмотра: шесть точек в порядке сервера MV V DV ML L DL. */
export interface PerioLayerRow {
  tooth: number
  pd: number[]
  rec: number[]
  /** маска кровоточивости «010010» */
  bop: string
  mob: number
  furc: number
  /** CAL = PD + рецессия, считает сервер и только у измеренных точек */
  cal: number[]
}

export interface PerioLayer {
  exam: { id: number; at: string }
  rows: Record<string, PerioLayerRow>
  /** «карман» с deep мм, глубокий с severe — те же пороги, что в итогах листа и 043/e */
  limits: { deep: number; severe: number }
  /** цвет полосы кармана на десне по тем же ключам */
  colors: { deep: string; severe: string }
  sites: { key: string; label: string }[]
  grades: { mob: Record<string, string>; furc: Record<string, string> }
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

/** Режим рабочего стола (Олег 24.10, макет B) — словарь сервера
 *  (`odontogram.MODES`). Режим — фильтр ЭКРАНА по записанным данным: в
 *  запись, 043/e и печать не попадает. Ключи `keys` — те же, что у легенды. */
export interface ChartMode {
  key: string
  label: string
  /** all — всё видно; keys — зубы с этими состояниями/отметками; perio — слой осмотра на десне */
  kind: 'all' | 'keys' | 'perio'
  keys: string[]
  /** ещё и зубы мостов (Proteză) */
  bridges: boolean
}

export interface ArchRows {
  upper: number[]
  lower: number[]
  milk_upper: number[]
  milk_lower: number[]
}

/** Позиция плана ЗУБА — та же строка, что у плана фиши (`api._plan_item`), без
 *  кнопок переходов: панель её только показывает. Подпись статуса, срок,
 *  просрочка и врач — с сервера; `active` — перечислением сервера
 *  (`db.PLAN_ACTIVE`), а не «всё, кроме finalizat». */
export interface ToothPlanItem {
  id: number
  procedure: string
  status: string
  label: string
  doctor: string
  price: number | null
  /** dd.mm.yyyy или пусто */
  due: string
  overdue: boolean
  /** дата закрытия (финал или отказ), пусто у открытой */
  done: string
  /** причина отказа, только у `refuzat` */
  motiv: string
  active: boolean
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
  /** состояния про ВЕСЬ зуб (коронка, имплант, удалён, отсутствует + ok):
   *  `carie`/`obturatie` вводятся только по поверхностям кистью (11.10) */
  tooth_states: Record<string, string>
  /** цвет состояния и отметки — тот же, что у 2D и легенды (`teeth_svg.COLORS` + `MARK_COLORS`) */
  palette?: Record<string, string>
  marks: Record<string, string>
  surfaces: Record<string, string>
  surface_states: string[]
  bridge_roles: Record<string, string>
  materials: { id: string; label: string }[]
  /** режимы вкладками шапки; сервер шлёт всегда (держит `test_teeth`), без
   *  них — старые засевы проверок — экран просто без вкладок режимов */
  modes?: ChartMode[]
  patient: { id: number; name: string; primary_doctor: string }
  doctors: string[]
  /** Последний пародонтальный замер по зубам: дата, id осмотра и ГОТОВАЯ
   *  фраза сервера. ⛔ Своей фразы у клиента нет — слова про глубину и степени
   *  живут в `perio.py`, как `sfx` у поверхностей. Пусто, если осмотра с
   *  измерениями у пациента ещё не было. */
  perio?: Record<string, { at: string; exam: number; text: string }>
  /** Тот же осмотр ЧИСЛАМИ (06.10) — слой пародонта в 3D и таблица точек в
   *  инспекторе. CAL, пороги и цвета полосы — с сервера (`perio.layer`).
   *  null — осмотра с измерениями нет. */
  perio_layer?: PerioLayer | null
  /** Позиции плана по зубам (24.10, вкладка «Tratament» панели зуба). У зуба
   *  без позиций ключа нет; позиция «на весь рот» (без зуба) сюда не едет. */
  plan?: Record<string, ToothPlanItem[]>
  /** Свежая фиша — ТОЛЬКО в ответе записи зуба, которая её попросила
   *  (`?card=1`, см. `saveTooth`). Её тип знает фиша, а не этот модуль. */
  card?: unknown
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

/** Каким экран ПОКАЗАЛ зуб, когда начал его править (волна 2, 25.10): сервер
 *  сверяет его с записью (`db.set_teeth`) — зуб, изменённый с тех пор на
 *  другом компьютере, даёт отказ 409 `odo_conflict`, и не пишется ничего. */
export interface ToothBase {
  state: string
  sfst: Record<string, string>
  marks: string[]
  doctor: string
  note: string
}

/** Зуб пачки «Salvează tot» и предпросмотра — поля записи зуба плюс номер;
 *  `base` нужен записи, предпросмотр его не читает. */
export interface TeethItem extends ToothSave {
  n: number
  base?: ToothBase
}

export interface BridgeSave {
  teeth: [number, string][]
  material: string
  material_alt: string
  doctor: string
}

/** Позиция плана С ЗУБА (01.10; Олег 27.09: «одонтограмма с планом не
 *  связана»): те же поля и те же строки, что шлёт форма плана фиши
 *  (`patients/card › PlanForm`) — правила у сервера одни (`_add_plan`). */
export interface PlanAdd {
  tooth: string
  procedure: string
  doctor: string
  price: string
  due_date: string
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
    const v = localStorage.getItem(VIEW_KEY)
    return v === 'ocluzal' || v === '3d' ? v : 'frontal'
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
  /** «Salvează tot» (волна 2, 25.10): черновики всех зубов одной записью — всё
   *  или ничего (`api_teeth_save`). `q` дописывается к адресу: фиша шлёт
   *  `?card=1…` и получает рядом с моделью свежую себя — перечитывать её
   *  открытием (а это строка журнала доступа) не нужно. Запись по одному
   *  зубу (`POST …/teeth/{n}`) на сервере осталась, экран её больше не зовёт. */
  saveTeeth: (pid: number, teeth: TeethItem[], q = '') =>
    api.post<Odontogram>(`${P(pid)}/teeth${q}`, { teeth }),
  /** Черновик РИСУНКОМ до записи: зубы такими, какими их сделала бы запись
   *  (то же правило и тот же построитель на сервере), — без записи, без
   *  летописи и без «Fișa deschisă» (`api_odontogram_preview`). */
  preview: (pid: number, teeth: TeethItem[], signal?: AbortSignal) =>
    api.post<{ teeth: Record<string, ToothInfo> }>(`${P(pid)}/odontogram/preview`, { teeth }, signal ? { signal } : {}),
  addBridge: (pid: number, body: BridgeSave) =>
    api.post<Odontogram>(`${P(pid)}/bridges`, body),
  delBridge: (pid: number, bid: number) =>
    api.post<Odontogram>(`${P(pid)}/bridges/${bid}/delete`, {}),
  /** Позиция плана с зуба — маршрут плана фиши с `?odo=1` (24.10): в ответе
   *  свежая МОДЕЛЬ одонтограммы — план зуба во вкладке «Tratament» сразу с
   *  позицией. `q` — тот же хвост, что у записи зуба: фиша шлёт `?card=1…` и
   *  получает рядом с моделью себя (`card`). */
  addPlan: (pid: number, body: PlanAdd, q = '') =>
    api.post<Odontogram>(`${P(pid)}/plan?odo=1${q ? `&${q.replace(/^\?/, '')}` : ''}`, body),
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

/** Легенда как фильтр (01.10): зуб «про это», если состояние у него целиком,
 *  на любой поверхности или отметкой. Ключи — те же, что у легенды сервера
 *  (`legend[].key`: состояния и отметки); второго словаря нет. */
export function toothMatches(info: Pick<ToothInfo, 'state' | 'sfst' | 'mk'>, key: string): boolean {
  return info.state === key || Object.values(info.sfst).includes(key) || info.mk.includes(key)
}

/** Зубы на экране: постоянные ряды и молочные, пока их ряд открыт. */
export function shownTeeth(model: Odontogram): number[] {
  const a = model.arches
  return model.milk_open ? [...a.upper, ...a.lower, ...a.milk_upper, ...a.milk_lower] : [...a.upper, ...a.lower]
}

/** Сколько зубов на экране «про» каждый пункт легенды — подпись счётчика;
 *  `within` — набор режима: легенда считает внутри него. */
export function legendCounts(model: Odontogram, items: LegendItem[], within: ReadonlySet<number> | null = null): Record<string, number> {
  const out: Record<string, number> = {}
  const shown = within ? shownTeeth(model).filter((n) => within.has(n)) : shownTeeth(model)
  for (const it of items) {
    out[it.key] = shown.filter((n) => { const t = model.teeth[String(n)]; return t ? toothMatches(t, it.key) : false }).length
  }
  return out
}

const NO_TEETH: ReadonlySet<number> = new Set()

/** Зубы, которые фильтр ГАСИТ: все, что не про выбранный пункт; без фильтра — никого. */
export function dimmedTeeth(model: Odontogram, key: string | null): ReadonlySet<number> {
  if (key === null) return NO_TEETH
  const out = new Set<number>()
  for (const [k, t] of Object.entries(model.teeth)) if (!toothMatches(t, key)) out.add(Number(k))
  return out
}

/** Зубы режима — набор, внутри которого работает экран; null — режим ничего
 *  не сужает («all» и «perio»: слой осмотра гасит находки сам, не зубы).
 *  «keys» — зуб с любым ключом режима (как у легенды) или в мосте при `bridges`. */
export function modeSet(model: Odontogram, mode: ChartMode | null): ReadonlySet<number> | null {
  if (!mode || mode.kind !== 'keys') return null
  const out = new Set<number>()
  for (const [k, t] of Object.entries(model.teeth)) {
    const n = Number(k)
    if (mode.keys.some((key) => toothMatches(t, key)) || (mode.bridges && bridgeOf(model, n))) out.add(n)
  }
  return out
}

/** Число у вкладки режима: зубы на экране про него; у «perio» — зубы с
 *  карманом от порога сервера `deep` (тот же порог, что у полосы на десне);
 *  у «all» числа нет — сколько записано, говорит шапка. */
export function modeCount(model: Odontogram, mode: ChartMode): number | null {
  if (mode.kind === 'all') return null
  if (mode.kind === 'perio') {
    const l = model.perio_layer
    return l ? Object.values(l.rows).filter((r) => r.pd.some((v) => v >= l.limits.deep)).length : 0
  }
  const set = modeSet(model, mode)
  return set ? shownTeeth(model).filter((n) => set.has(n)).length : 0
}

/** Что гасит экран (24.10): режим задаёт набор — гаснет всё вне его, легенда
 *  сужает внутри — гаснет и то, что не про её пункт. Ни режима, ни легенды —
 *  никого. */
export function screenDim(model: Odontogram, mode: ChartMode | null, key: string | null): ReadonlySet<number> {
  const set = modeSet(model, mode)
  if (!set) return dimmedTeeth(model, key)
  const out = new Set(dimmedTeeth(model, key))
  for (const k of Object.keys(model.teeth)) if (!set.has(Number(k))) out.add(Number(k))
  return out
}

export type Arrow = 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown'

/** Сосед для стрелок (C22): влево/вправо — по ряду в порядке экрана,
 *  вверх/вниз — та же позиция другой челюсти; молочные — в своей паре
 *  рядов. Ничего не выбрано — первый зуб верхней дуги. Соседа нет — null. */
export function neighbour(model: Odontogram, n: number | null, key: Arrow): number | null {
  const a = model.arches
  if (n === null) return a.upper[0] ?? null
  for (const [up, lo] of [[a.upper, a.lower], [a.milk_upper, a.milk_lower]] as const) {
    const iu = up.indexOf(n)
    const il = lo.indexOf(n)
    if (iu < 0 && il < 0) continue
    const row = iu >= 0 ? up : lo
    const i = iu >= 0 ? iu : il
    switch (key) {
      case 'ArrowLeft': return row[i - 1] ?? null
      case 'ArrowRight': return row[i + 1] ?? null
      case 'ArrowUp': return il >= 0 ? (up[i] ?? null) : null
      case 'ArrowDown': return iu >= 0 ? (lo[i] ?? null) : null
    }
  }
  return null
}
