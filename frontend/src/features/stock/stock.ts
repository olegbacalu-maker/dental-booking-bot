import { api, type ApiResult } from '../../services/api'

/* Формы ответов — сервер раздела (`/api/stock*`, контракт `stock-contract.md`). Остаток, порог, срок и отметка
   «comandat» приходят готовыми: экран своих правил склада не держит. Количество — тысячные доли единицы расхода
   (`*_milli`), деньги — бани (`*_bani`); без права на деньги денежных полей в ответе нет вовсе. */

export type Unit = 'buc' | 'g' | 'ml' | 'cm' | 'cutie' | 'pachet'
export type Kind = 'intrare' | 'consum' | 'casare' | 'inventar' | 'corectie'
export type Reason = 'pacient' | 'deschis' | 'expirat' | 'defect' | 'pierdut' | 'altul'
export type Filter = 'all' | 'low' | 'exp' | 'arh'
export type View = 'stoc' | 'intrari' | 'jurnal' | 'inventar' | 'cumparat' | 'import'
export type DocKind = 'factura' | 'inventar' | 'import'
export type DocStatus = 'ciorna' | 'inchis' | 'anulat'

export interface Can { stock: boolean; money: boolean; settings: boolean }
export interface Prefs { exp_days: number; order_days: number }
export interface Lot { lot: string; exp_on: string | null; qty_milli: number }
export interface Ordered { at: string; on: string; by: string; days: number; late: boolean }

export interface Item {
  id: number
  name: string
  cat: string
  unit: Unit
  pack_name: string
  pack_qty_milli: number
  min_milli: number | null
  costly: boolean
  track_expiry: boolean
  bulk: boolean
  supplier_id: number | null
  supplier: string
  active: boolean
  note: string
  data: { raft?: string; code?: string; barcodes?: string[] }
  qty_milli: number
  low: boolean
  neg: boolean
  lots: Lot[]
  exp_on: string | null
  exp_days: number | null
  soon: boolean
  expired: boolean
  ordered: Ordered | null
  buy_packs: number
  moves: number
  avg_bani?: number
  value_bani?: number
}

export interface Supplier { id: number; name: string; idno: string; phone: string; email: string; note: string; active: boolean; items: number; docs: number }

export interface Words {
  units: Record<string, string>
  kinds: Record<string, string>
  reasons: Record<string, string>
  doc_kinds: Record<string, string>
  doc_status: Record<string, string>
}

export interface ListData {
  today: string
  prefs: Prefs
  words: Words
  cats: string[]
  counts: { all: number; low: number; neg: number; soon: number; expired: number; ordered: number; archive: number; bulk: number }
  items: Item[]
  suppliers: Supplier[]
  drafts: { factura: number; inventar: number }
  can: Can
}

export interface Move {
  id: number
  at: string
  on: string
  kind: Kind
  kind_label: string
  item_id: number
  item: string
  unit: Unit
  qty_milli: number
  cost_bani?: number | null
  doc: { id: number; kind: DocKind; nr: string; supplier: string } | null
  lot: string
  exp_on: string | null
  pid: number | null
  patient: string | null
  fisa: string | null
  reason: string
  reason_label: string
  note: string
  actor: string
  source: 'manual' | 'import'
  fixes: number | null
  undone: boolean
  undoable: boolean
}

export interface ItemCard {
  item: Item
  moves: Move[]
  prices?: { on: string; nr: string; supplier: string; qty_milli: number; cost_bani: number; unit_bani: number }[]
  can: Can
}

export interface MovesData { moves: Move[]; more: boolean; actors: string[]; can: Can }

export interface DocRow {
  id: number
  kind: DocKind
  kind_label: string
  nr: string
  doc_date: string
  supplier_id: number | null
  supplier: string
  status: DocStatus
  status_label: string
  no_sums: boolean
  lines: number
  actor: string
  created_at: string
  closed_at: string | null
  note: string
  total_bani?: number
  can_storno: boolean
}

export interface Line {
  id: number
  item_id: number
  item: string
  unit: Unit
  pack_qty_milli: number
  qty_milli: number | null
  prog_milli?: number
  diff_milli?: number | null
  cost_bani?: number | null
  unit_bani?: number
  avg_bani?: number
  lot: string
  exp_on: string | null
  note: string
}

export interface Doc extends Omit<DocRow, 'lines'> { cur: string; cur_amount: number | null; rate: string; lines: Line[] }
export interface DocsData { docs: DocRow[]; can: Can }
export interface DocData { doc: Doc; can: Can }

export interface BuyRow {
  item_id: number
  name: string
  unit: Unit
  pack_name: string
  pack_qty_milli: number
  qty_milli: number
  min_milli: number
  neg: boolean
  buy_packs: number
  ordered: Ordered | null
  est_bani?: number
}
export interface BuyGroup { supplier_id: number | null; supplier: string; phone: string; email: string; rows: BuyRow[] }
export interface BuyData { today: string; prefs: Prefs; groups: BuyGroup[]; counts: { low: number; ordered: number; late: number }; can: Can }

export interface DashData {
  low: number; neg: number; ordered: number; soon: number; expired: number
  low_items: { id: number; name: string }[]
  exp_items: { id: number; name: string; exp_on: string; days: number }[]
}

/* ---- импорт: файл телом каждого запроса, как у пациентов ---- */
export interface ImOpts { sheet?: number; header?: number; cols?: Record<string, string>; choices?: Record<string, 'same' | 'new'> }
export interface ImColumn { index: number; letter: string; title: string; field: string }
export interface ImRow {
  line: number; name: string; cat: string; unit: string; pack_name: string; pack_qty_milli: number; qty_milli: number
  min_milli: number | null; price_bani?: number; exp_on: string | null; lot: string; supplier: string; raft: string
  act: 'new' | 'exists' | 'merged' | 'error'; err: string; err_text: string
  similar: { kind: 'item' | 'row'; id?: number; line?: number; name: string } | null
  choice: 'new' | 'same'
}
export interface ImCheck {
  file: { name: string; kind: string; size: number; sheets: { name: string; rows: number }[] }
  opts: { sheet: number; header: number; cols: Record<string, string> }
  columns: ImColumn[]
  ready: boolean
  rows: ImRow[]
  counts: { new: number; exists: number; merged: number; errors: number; rests: number; similar: number }
  dup: { id: number; at: string; file: string } | null
  token: string
}
export interface ImRun { id: number; at: string; actor: string; file: string; rows: number; created: number; rests: number; undone: boolean; can_undo: boolean }
export interface ImHome {
  imports: ImRun[]
  fields: { id: string; label: string }[]
  limits: { bytes: number; rows: number }
  units: string[]
  remote: { tone: string; text: string } | null
  can: Can
}

export const UNITS: Unit[] = ['buc', 'g', 'ml', 'cm', 'cutie', 'pachet']

export const REASONS: [Reason, string][] = [
  ['pacient', 'Pe pacient'], ['deschis', 'Pachet deschis'], ['expirat', 'Expirat'], ['defect', 'Defect / deteriorat'],
  ['pierdut', 'Pierdut'], ['altul', 'Alt motiv'],
]

const qs = (o: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '' && v !== 0) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}
const opt = (signal?: AbortSignal) => (signal ? { signal } : {})

export type LineIn = { id?: number; item_id: number; qty_milli: number | null; cost_bani?: number | null; lot?: string; exp_on?: string | null; note?: string }
export type DocIn = {
  kind?: 'factura' | 'inventar'; nr?: string; doc_date?: string; supplier_id?: number | null; supplier_name?: string; supplier_idno?: string
  note?: string; cats?: string[]; lines?: LineIn[]
}

export const stockApi = {
  list: (signal?: AbortSignal): Promise<ApiResult<ListData>> => api.get('/stock', opt(signal)),
  item: (id: number, signal?: AbortSignal): Promise<ApiResult<ItemCard>> => api.get(`/stock/item/${id}`, opt(signal)),
  saveItem: (body: Record<string, unknown>): Promise<ApiResult<{ id: number }>> => api.post('/stock/item', body),
  dropItem: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/item/${id}/delete`, {}),
  saveSupplier: (body: Partial<Supplier>): Promise<ApiResult<{ id: number }>> => api.post('/stock/supplier', body),
  dropSupplier: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/supplier/${id}/delete`, {}),
  out: (body: { item_id: number; qty_milli: number; reason: Reason; note: string; pid?: number; lot?: string }): Promise<ApiResult<{ id: number; qty_milli: number; neg: boolean }>> =>
    api.post('/stock/out', body),
  open: (item_id: number): Promise<ApiResult<{ id: number; qty_milli: number; neg: boolean }>> => api.post('/stock/open', { item_id }),
  undo: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/move/${id}/undo`, {}),
  moves: (p: Record<string, string | number>, signal?: AbortSignal): Promise<ApiResult<MovesData>> => api.get(`/stock/moves${qs(p)}`, opt(signal)),
  docs: (kind: DocKind, signal?: AbortSignal): Promise<ApiResult<DocsData>> => api.get(`/stock/docs${qs({ kind })}`, opt(signal)),
  doc: (id: number, signal?: AbortSignal): Promise<ApiResult<DocData>> => api.get(`/stock/doc/${id}`, opt(signal)),
  createDoc: (body: DocIn): Promise<ApiResult<{ id: number }>> => api.post('/stock/doc', body),
  saveDoc: (id: number, body: DocIn): Promise<ApiResult<{ id: number }>> => api.post(`/stock/doc/${id}`, body),
  closeDoc: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/doc/${id}/close`, {}),
  dropDoc: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/doc/${id}/delete`, {}),
  sums: (id: number, lines: { id: number; cost_bani: number }[]): Promise<ApiResult<unknown>> => api.post(`/stock/doc/${id}/sums`, { lines }),
  storno: (id: number, why: string): Promise<ApiResult<unknown>> => api.post(`/stock/doc/${id}/storno`, { why }),
  buy: (signal?: AbortSignal): Promise<ApiResult<BuyData>> => api.get('/stock/buy', opt(signal)),
  order: (ids: number[]): Promise<ApiResult<unknown>> => api.post('/stock/order', { ids }),
  unorder: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/order/${id}/cancel`, {}),
  prefs: (body: Partial<Prefs>): Promise<ApiResult<unknown>> => api.post('/stock/prefs', body),
  importHome: (signal?: AbortSignal): Promise<ApiResult<ImHome>> => api.get('/stock/import', opt(signal)),
  importCheck: (file: Blob, name: string, opts: ImOpts): Promise<ApiResult<ImCheck>> =>
    api.postRaw(`/stock/import/check${qs({ name, opts: JSON.stringify(opts) })}`, file),
  importRun: (file: Blob, name: string, opts: ImOpts, token: string): Promise<ApiResult<{ id: number; created: number; rests: number; skipped: number }>> =>
    api.postRaw(`/stock/import/run${qs({ name, opts: JSON.stringify(opts), token })}`, file),
  importUndo: (id: number): Promise<ApiResult<unknown>> => api.post(`/stock/import/${id}/undo`, {}),
}

/** Лист «De cumpărat» сервера: отмеченные строки и поправленные упаковки. */
export const buyPrintHref = (rows: { id: number; packs: number }[]) =>
  `/admin/stoc/cumparat/tipar?q=${rows.map((r) => `${r.id}:${r.packs}`).join(',')}&back=${encodeURIComponent('/admin/stoc?v=cumparat')}`
export const movesXlsxHref = (month: string) => `/admin/stoc/miscari.xlsx?month=${month}`

/* ---- слова и числа ---- */
const nf = (max: number) => new Intl.NumberFormat('ro-RO', { maximumFractionDigits: max })
/** 12500 тысячных → «12,5». */
export const num = (milli: number, max = 2) => nf(max).format(milli / 1000)
export const qtyText = (milli: number, unit: string) => `${num(milli)} ${unit}`
export const lei = (bani: number) => `${nf(2).format(bani / 100)} MDL`
/** Ввод человека «2,5» → тысячные; пусто или мусор — NaN. */
export function parseQty(s: string): number {
  const t = s.trim().replace(/\s/g, '').replace(',', '.')
  if (!t || !/^-?\d*\.?\d+$/.test(t)) return NaN
  return Math.round(Number(t) * 1000)
}
export function parseLei(s: string): number {
  const t = s.trim().replace(/\s/g, '').replace(',', '.')
  if (!t || !/^\d*\.?\d+$/.test(t)) return NaN
  return Math.round(Number(t) * 100)
}
export const leiInput = (bani: number | null | undefined) => (bani == null ? '' : nf(2).format(bani / 100).replace(/\./g, ''))
export function dmy(s: string | null | undefined): string {
  if (!s) return '—'
  const [y, m, d] = s.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
}
/** «seringă 4 g» → «seringă». */
export const packWord = (it: { pack_name: string }) => it.pack_name.split(' ')[0] || 'ambalaj'
/** Остаток словами упаковок: «1 × cutie + 23 buc». */
export function packText(milli: number, it: { pack_name: string; pack_qty_milli: number; unit: string }): string {
  if (it.pack_qty_milli <= 1000 || milli <= 0) return qtyText(milli, it.unit)
  const whole = Math.trunc(milli / it.pack_qty_milli)
  const rest = milli - whole * it.pack_qty_milli
  const word = packWord(it)
  if (!rest) return `${whole} × ${word}`
  if (!whole) return `${num(rest)} ${it.unit} din ${word}`
  return `${whole} × ${word} + ${num(rest)} ${it.unit}`
}
/** Строка «Comandat»: свежая отметка серая, истёкшая — снова обычная с «n-a venit». */
export const orderState = (o: Ordered | null): 'none' | 'on' | 'late' => (!o ? 'none' : o.late ? 'late' : 'on')

export const MATERIALE = { one: '1 material', few: '{n} materiale', many: '{n} de materiale' }
