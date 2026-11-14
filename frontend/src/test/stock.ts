import type { ApiResult } from '../services/api'
import type { BuyData, BuyRow, DashData, ImCheck, ImHome, ImRow, Item, ListData, Move } from '../features/stock/stock'

/* Ответы сервера для проверок клиента — формы контракта `stock-contract.md`. */

export const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

export const CAN = { stock: true, money: true, settings: true }
export const CAN_DESK = { stock: true, money: false, settings: false }

export const item = (p: Partial<Item> = {}): Item => ({
  id: 1, name: 'Ubistesin Forte 4%', cat: 'Anestezice', unit: 'buc', pack_name: 'cutie 50 carpule', pack_qty_milli: 50000,
  min_milli: 40000, costly: false, track_expiry: true, bulk: false, supplier_id: 1, supplier: 'DentaMed', active: true, note: '',
  data: {}, qty_milli: 73000, low: false, neg: false, lots: [], exp_on: '2026-12-08', exp_days: 24, soon: true, expired: false,
  ordered: null, buy_packs: 0, moves: 5, avg_bani: 1960, value_bani: 143080,
  ...p,
})

export const ITEMS: Item[] = [
  item(),
  item({ id: 2, name: 'Septanest 1:100 000', qty_milli: -3000, neg: true, low: true, min_milli: 25000, exp_on: null, exp_days: null, soon: false,
    ordered: { at: '2026-11-11T09:50:00Z', on: '2026-11-11', by: 'Recepție', days: 3, late: false }, buy_packs: 2 }),
  item({ id: 3, name: 'Filtek Z550 A2', cat: 'Compozite și adezive', unit: 'g', pack_name: 'seringă 4 g', pack_qty_milli: 4000, min_milli: 8000,
    qty_milli: 5500, low: true, exp_on: '2027-09-30', exp_days: 320, soon: false, buy_packs: 3, avg_bani: 13000, value_bani: 71500 }),
  item({ id: 4, name: 'Mănuși nitril M', cat: 'Consumabile diverse', unit: 'cutie', pack_name: 'cutie 100 buc', pack_qty_milli: 1000,
    min_milli: 4000, qty_milli: 3000, low: true, bulk: true, track_expiry: false, exp_on: null, exp_days: null, soon: false, buy_packs: 5 }),
  item({ id: 5, name: 'Filtek Z250 (scos din uz)', active: false, low: false, soon: false }),
]

export const list = (p: Partial<ListData> = {}): ListData => ({
  today: '2026-11-14', prefs: { exp_days: 60, order_days: 7 },
  words: { units: {}, kinds: { intrare: 'Intrare', consum: 'Pe pacient', casare: 'Scoatere', inventar: 'Inventariere', corectie: 'Corecție' },
    reasons: {}, doc_kinds: {}, doc_status: {} },
  cats: ['Anestezice', 'Compozite și adezive', 'Consumabile diverse'],
  counts: { all: 4, low: 3, neg: 1, soon: 1, expired: 0, ordered: 1, archive: 1, bulk: 1 },
  items: ITEMS,
  suppliers: [{ id: 1, name: 'DentaMed', idno: '', phone: '022 210 450', email: '', note: '', active: true, items: 3, docs: 2 }],
  drafts: { factura: 1, inventar: 0 },
  can: CAN,
  ...p,
})

export const move = (p: Partial<Move> = {}): Move => ({
  id: 10, at: '2026-11-12T14:10:00Z', on: '2026-11-12', kind: 'casare', kind_label: 'Scoatere', item_id: 1, item: 'Ubistesin Forte 4%', unit: 'buc',
  qty_milli: -50000, cost_bani: 98000, doc: null, lot: '', exp_on: null, pid: null, patient: null, fisa: null, reason: 'deschis',
  reason_label: 'Pachet deschis', note: '', actor: 'Recepție', source: 'manual', fixes: null, undone: false, undoable: true,
  ...p,
})

export const buyRow = (p: Partial<BuyRow> = {}): BuyRow => ({
  item_id: 3, name: 'Filtek Z550 A2', unit: 'g', pack_name: 'seringă 4 g', pack_qty_milli: 4000, qty_milli: 5500, min_milli: 8000, neg: false,
  buy_packs: 3, ordered: null, est_bani: 156000, ...p,
})

export const buy = (rows: BuyRow[], p: Partial<BuyData> = {}): BuyData => ({
  today: '2026-11-14', prefs: { exp_days: 60, order_days: 7 },
  groups: [{ supplier_id: 1, supplier: 'DentaMed', phone: '022 210 450', email: '', rows }],
  counts: { low: rows.length, ordered: rows.filter((r) => r.ordered && !r.ordered.late).length, late: rows.filter((r) => r.ordered?.late).length },
  can: CAN, ...p,
})

export const dash = (p: Partial<DashData> = {}): DashData => ({
  low: 9, neg: 2, ordered: 2, soon: 4, expired: 0,
  low_items: [{ id: 2, name: 'Septanest 1:100 000' }, { id: 3, name: 'Filtek Z550 A2' }], exp_items: [{ id: 1, name: 'Ubistesin Forte 4%', exp_on: '2026-12-08', days: 24 }],
  ...p,
})

export const imRow = (p: Partial<ImRow> = {}): ImRow => ({
  line: 2, name: 'Ubistesin Forte 4%', cat: 'Anestezice', unit: 'buc', pack_name: 'cutie 50 carpule', pack_qty_milli: 50000, qty_milli: 64000,
  min_milli: 40000, exp_on: '2027-03-30', lot: '', supplier: '', raft: '', act: 'new', err: '', err_text: '', similar: null, choice: 'new', ...p,
})

export const imHome = (p: Partial<ImHome> = {}): ImHome => ({
  imports: [], fields: [{ id: 'name', label: 'Denumirea' }, { id: 'unit', label: 'Unitatea' }, { id: 'qty', label: 'Restul pe raft' }],
  limits: { bytes: 5000000, rows: 2000 }, units: ['buc', 'g', 'ml'], remote: null, can: CAN, ...p,
})

export const imCheck = (rows: ImRow[], p: Partial<ImCheck> = {}): ImCheck => ({
  file: { name: 'stoc.xlsx', kind: 'xlsx', size: 1000, sheets: [{ name: 'Stoc', rows: rows.length + 1 }] },
  opts: { sheet: 0, header: 1, cols: { 0: 'name', 1: 'unit', 2: 'qty' } },
  columns: [{ index: 0, letter: 'A', title: 'Denumire', field: 'name' }, { index: 1, letter: 'B', title: 'UM', field: 'unit' }, { index: 2, letter: 'C', title: 'Stoc', field: 'qty' }],
  ready: true, rows,
  counts: { new: rows.filter((r) => r.act === 'new').length, exists: rows.filter((r) => r.act === 'exists').length, merged: 0,
    errors: rows.filter((r) => r.act === 'error').length, rests: rows.length, similar: rows.filter((r) => r.similar).length },
  dup: null, token: 'tok1', ...p,
})
