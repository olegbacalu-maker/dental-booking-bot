import type { ServerNotice } from '../../components/Notice'
import { api, type ApiResult } from '../../services/api'

/* Импорт пациентов из файла: формы ответов — bot/app/modules/patients/pimport_api.py.
   Файл держит браузер и шлёт его телом каждого запроса; сервер между шагами
   ничего не хранит. Слова групп, причин и полей — сервера. */

export interface PiImport {
  id: number
  at: string
  actor: string
  file: string
  rows: number
  created: number
  filled: number
  skipped: number
  removed: number
  /** Визиты из файла: поставлено (из них прошлых — в истории), не поставлено, снято отменой. */
  visits: number
  visits_past: number
  visits_skipped: number
  visits_removed: number
  undone: boolean
  can_undo: boolean
}

export interface PiHome {
  imports: PiImport[]
  fields: { id: string; label: string }[]
  limits: { bytes: number; rows: number; batch: number }
  encodings: string[]
  delimiters: string[]
  remote: ServerNotice | null
}

/** Выбор человека; в ответе проверки он доведён до конкретного. */
export interface PiOpts {
  sheet: number
  header: number
  cols: Record<string, string>
  enc: string
  delim: string
  fill: boolean
  force: number[]
  /** Решение по написанию врача в файле: id врача или NO_DOCTOR; нет ключа — как узнала программа. */
  docs: Record<string, string>
  /** Прошлые визиты файла — в историю «finalizată». */
  past: boolean
  /** SMS-напоминания по будущим визитам файла. */
  sms: boolean
  /** Процедура визита для строк без своей (ключ услуги агенды). */
  svc: string
}

export interface PiRow {
  line: number
  name: string
  phone: string
  birth: string
  idnp: string
  reason: string
  notes: string[]
  match: { id: number; name: string } | null
  forceable: boolean
  fill: string[]
}

export interface PiGroup {
  id: 'new' | 'noted' | 'exists' | 'dup' | 'bad'
  label: string
  count: number
  more: number
  rows: PiRow[]
}

export interface PiCounts {
  rows: number
  create: number
  new: number
  noted: number
  exists: number
  dup: number
  bad: number
  fill: number
  family: number
}

/** Одно написание врача в файле (шаг «Medici»). */
export interface PiDoctor {
  key: string
  value: string
  rows: number
  /** Врач, которого узнала программа, или "". */
  auto: string
  /** Если не узнан: кто подошёл одинаково хорошо. */
  cands: string[]
  /** Выбор человека: id, NO_DOCTOR или "". */
  choice: string
}

export interface PiClinicDoctor { id: string; name: string; active: boolean }

/** Визит строки файла на шаге проверки. */
export interface PiVisitRow {
  line: number
  name: string
  when: string
  doctor: string
  service: string
  reason: string
  notes: string[]
  patient: number | null
}

export interface PiVisitGroup {
  id: 'v_new' | 'v_past' | 'v_no'
  label: string
  count: number
  more: number
  rows: PiVisitRow[]
}

export interface PiVisits {
  counts: { v_new: number; v_past: number; v_no: number; rows: number }
  groups: PiVisitGroup[]
}

/** Колонка даты записи назначена: строки становятся визитами. */
export const hasVisits = (cols: Record<string, string>): boolean =>
  Object.values(cols).some((f) => f === 'appt' || f === 'appt_time')

export const NO_DOCTOR = '-'

/** Решение по написанию: выбор человека сильнее узнанного; "" — пустое значение снимает выбор. */
export function chooseDoctor(docs: Record<string, string>, key: string, value: string): Record<string, string> {
  const next = { ...docs }
  if (value) next[key] = value
  else delete next[key]
  return next
}

export interface PiCheck {
  file: { name: string; kind: string; size: number; sheets: { name: string; rows: number }[]; enc: string; delim: string }
  opts: PiOpts
  columns: { index: number; letter: string; title: string; field: string }[]
  preview: { line: number; cells: string[] }[]
  doctors: PiDoctor[]
  clinic_doctors: PiClinicDoctor[]
  ready: boolean
  counts: PiCounts | null
  groups: PiGroup[]
  /** Визиты файла; null — колонки даты записи нет. */
  visits: PiVisits | null
  services: { id: string; name: string }[]
  /** Пакет SMS работает: галочке напоминаний есть что включать. */
  sms_on: boolean
  token: string
  parts?: number
}

export interface PiRun {
  import: number
  part: number
  parts: number
  done: boolean
  created: number
  filled: number
  skipped: number
  visits: number
  visits_past: number
  visits_skipped: number
  /** Последняя порция: сколько пациентов импорта стоят теперь в «Rechemări». */
  recall: number
  total: PiImport
}

export type PiUndoPhase = 'v' | 'p'

export interface PiUndo {
  done: boolean
  /** Следующий этап: визиты (`v`), потом фиши (`p`). */
  phase: PiUndoPhase
  after: number
  removed: number
  visits_removed: number
  kept: number
  visits_kept: number
  total: PiImport
}

/** Поля, которые можно назначить нескольким колонкам; остальные — одной. */
export const MULTI = new Set(['notes', 'phone', 'phone2'])
const NAME = new Set(['full', 'last', 'first'])

export const hasName = (cols: Record<string, string>): boolean => Object.values(cols).some((f) => NAME.has(f))

/** Колонке назначено поле; одиночное поле у прежней колонки снимается. */
export function assign(cols: Record<string, string>, index: number, field: string): Record<string, string> {
  const next: Record<string, string> = {}
  for (const [k, f] of Object.entries(cols)) {
    if (Number(k) !== index && (f !== field || MULTI.has(f))) next[k] = f
  }
  if (field) next[String(index)] = field
  return next
}

const query = (file: File, opts: Partial<PiOpts>, more: Record<string, string | number> = {}): string => {
  const q = new URLSearchParams({ name: file.name, opts: JSON.stringify(opts) })
  for (const [k, v] of Object.entries(more)) q.set(k, String(v))
  return q.toString()
}

export const MODEL_HREF = '/api/pimport/model.xlsx'

export const pimportApi = {
  home: (signal?: AbortSignal): Promise<ApiResult<PiHome>> => api.get<PiHome>('/pimport', signal ? { signal } : {}),
  check: (file: File, opts: Partial<PiOpts>) => api.postRaw<PiCheck>(`/pimport/check?${query(file, opts)}`, file),
  run: (file: File, opts: PiOpts, token: string, part: number, importId: number) =>
    api.postRaw<PiRun>(`/pimport/run?${query(file, opts, { token, part, import: importId })}`, file),
  report: (file: File, opts: PiOpts, importId = 0) =>
    api.download(`/pimport/report?${query(file, opts, importId ? { import: importId } : {})}`, file),
  undo: (id: number, phase: PiUndoPhase, after: number) =>
    api.post<PiUndo>(`/pimport/undo?id=${id}&phase=${phase}&after=${after}`),
}

/** «1 200»: разряды неразрывным пробелом — в румынской локали браузер ставит точку. */
export function num(n: number): string {
  return String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

/** Отдать человеку файл, полученный ответом запроса. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.append(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
