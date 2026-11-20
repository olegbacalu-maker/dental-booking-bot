import { api, type ApiResult } from '../../services/api'

/* «Servicii și tarife»: формы ответов `/api/tarife` и сборка тела записи. Контракт — сервер (`core/tarife.py`):
   один список услуг `clinic.json › services`; где строка показывается, говорит `where`, группу — `cat`. */

export type Where = 'both' | 'agenda' | 'plan'

export interface TarifRow {
  id: string
  ro: string
  /** сервер отдаёт RO, если RU не писали */
  ru: string
  /** строка, как её написала клиника */
  price: string
  /** сумма, только если строка — ровно одно число */
  amount: number | null
  price_hint: string
  /** "" — «Fără categorie» */
  cat: string
  where: Where
}

export interface TarifCat {
  id: string
  name: string
  /** сколько строк прайса (в плане) в категории */
  n: number
}

export interface TarifeData {
  services: TarifRow[]
  cats: TarifCat[]
  uncat: number
  can_edit: boolean
  max: { name: number; price: number; cat: number; cats: number; services: number }
  import: { bytes: number; remote: { tone: 'ok' | 'warn' | 'err' | 'info'; text: string } | null }
  created?: { services: string[]; cats: Record<string, string> }
  imported?: Record<'new' | 'changed' | 'same' | 'bad', number>
}

/** Правка строки — только тронутые поля; `plan` — место в прайсе. */
export interface RowEdit {
  ro?: string
  ru?: string
  price?: string
  cat?: string
  plan?: boolean
}

export interface NewRow {
  key: string
  ro: string
  ru: string
  price: string
  cat: string
}

/** Тело POST /api/tarife: нет ключа — не сообщали. */
export interface TarifeForm {
  services?: Record<string, RowEdit>
  new?: Omit<NewRow, 'key'>[]
  cats?: Record<string, { name: string }>
  cats_new?: { key: string; name: string }[]
  cats_removed?: string[]
  cats_order?: string[]
}

export type ImAct = 'new' | 'changed' | 'same' | 'bad'

export interface ImRow {
  line: number
  cat: string
  ro: string
  ru: string
  price: string
  act: ImAct
  id: string
  what: ('price' | 'cat' | 'ru' | 'plan')[]
  old_price: string
  err: '' | 'name' | 'price' | 'dup'
}

export interface ImCheck {
  file: { name: string; size: number }
  rows: ImRow[]
  counts: Record<ImAct, number>
  cats_new: string[]
  token: string
}

const opt = (signal?: AbortSignal) => (signal ? { signal } : {})
const qs = (p: Record<string, string>) => `?${new URLSearchParams(p).toString()}`

export const tarifeApi = {
  load: (signal?: AbortSignal): Promise<ApiResult<TarifeData>> => api.get('/tarife', opt(signal)),
  save: (form: TarifeForm): Promise<ApiResult<TarifeData>> => api.post('/tarife', form),
  importCheck: (file: Blob, name: string): Promise<ApiResult<ImCheck>> =>
    api.postRaw(`/tarife/import/check${qs({ name })}`, file),
  importRun: (file: Blob, name: string, token: string): Promise<ApiResult<TarifeData>> =>
    api.postRaw(`/tarife/import/run${qs({ name, token })}`, file),
}

export const EXPORT_HREF = '/admin/tarife.xlsx'

/** Поиск без диакритики и регистра: «restaurare» найдёт «Restaurare», «coroana» — «Coroană». */
export const fold = (s: string): string =>
  s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase('ro').trim()

export const inPlan = (w: Where): boolean => w !== 'agenda'
export const inAgenda = (w: Where): boolean => w !== 'plan'

/**
 * Тело записи из черновика: только поля, которые отличаются от профиля. Строка, которую вернули к
 * прежнему виду, не уходит вовсе — пересохранение без правки тождественно.
 */
export function buildForm(data: TarifeData, edits: Record<string, RowEdit>, added: NewRow[]): TarifeForm {
  const form: TarifeForm = {}
  const services: Record<string, RowEdit> = {}
  for (const [id, e] of Object.entries(edits)) {
    const row = data.services.find((r) => r.id === id)
    if (!row) continue
    const d = diffOf(row, e)
    if (Object.keys(d).length) services[id] = d
  }
  if (Object.keys(services).length) form.services = services
  const fresh = added.filter((n) => n.ro.trim() || n.ru.trim() || n.price.trim())
  if (fresh.length) form.new = fresh.map(({ ro, ru, price, cat }) => ({ ro: ro.trim(), ru: ru.trim(), price: price.trim(), cat }))
  return form
}

/** RU на экране: пусто, если сервер отдал RO вместо RU (не писали). */
const ruOf = (row: TarifRow): string => (row.ru === row.ro ? '' : row.ru)

function diffOf(row: TarifRow, e: RowEdit): RowEdit {
  const d: RowEdit = {}
  if (e.ro !== undefined && e.ro.trim() !== row.ro) d.ro = e.ro.trim()
  /* RU-строка сервера = RO, если RU не писали; пустое поле на экране значит то же самое */
  if (e.ru !== undefined && e.ru.trim() !== ruOf(row)) d.ru = e.ru.trim()
  if (e.price !== undefined && e.price.trim() !== row.price) d.price = e.price.trim()
  if (e.cat !== undefined && e.cat !== row.cat) d.cat = e.cat
  if (e.plan !== undefined && e.plan !== inPlan(row.where)) d.plan = e.plan
  return d
}

/** Строка, как её видит экран: профиль плюс правка. */
export function shown(row: TarifRow, e: RowEdit | undefined): { ro: string; ru: string; price: string; cat: string; plan: boolean } {
  return {
    ro: e?.ro ?? row.ro,
    ru: e?.ru ?? ruOf(row),
    price: e?.price ?? row.price,
    cat: e?.cat ?? row.cat,
    plan: e?.plan ?? inPlan(row.where),
  }
}
