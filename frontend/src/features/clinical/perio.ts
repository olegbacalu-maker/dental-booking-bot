import { api } from '../../services/api'

/* Пародонтограмма (C23, docs/dentpilot-2/clinical-chart.md). Формы ответов —
   bot/app/modules/patients/api.py (`_perio_model`) и perio.model.

   ⚠️ Единица здесь — датированный ОСМОТР, а не текущее состояние зуба:
   пародонт имеет смысл только в сравнении во времени. Поэтому модель несёт
   список осмотров и измерения ВЫБРАННОГО, а не «карту пациента».
   ⚠️ Глубина 0 — «не измеряли», а не «ноль миллиметров»: здорового кармана в
   0 мм не бывает. От этого зависят и пустая клетка на экране, и знаменатель
   BOP%, и CAL (его сервер считает только у измеренных точек). */

export interface PerioRow {
  tooth: number
  /** Шесть глубин, порядок канона: MV V DV ML L DL. */
  pd: number[]
  rec: number[]
  /** Маска кровоточивости шести точек, «010010». */
  bop: string
  /** Подвижность по Miller, 0–3. */
  mob: number
  /** Фуркация по Hamp, 0–3. */
  furc: number
  /** CAL = PD + рецессия, считает СЕРВЕР и только у измеренных точек.
   *  ⚠️ Лист его пока не рисует (показан средний CAL в итоге): он приезжает
   *  для сравнения осмотров — отдельного этапа. Считать CAL в браузере ради
   *  черновика значило бы завести вторую формулу там, где она клиническая. */
  cal: number[]
}

/** Строка формы: то, что экран правит и отсылает. CAL сюда не входит — он
 *  вычислимый, и второго его счёта в браузере быть не должно. */
export type PerioEdit = Omit<PerioRow, 'cal'>

export interface PerioExam {
  id: number
  /** Дата осмотра в зоне клиники, dd.mm.yyyy — разворачивает сервер. */
  at: string
  doctor: string
  note: string
  /** Сколько зубов измерено в этом осмотре. */
  teeth: number
}

export interface PerioTooth {
  state: string
  /** Зуба нет по одонтограмме: колонка приглушена, но ввод не запрещён. */
  absent: boolean
  title: string
  svg: { frontal: string; occlusal: string }
}

export interface PerioSummary {
  teeth: number
  sites: number
  bop: number
  pd_mean: number
  cal_mean: number
  deep: number
  severe: number
  mob: [number, number][]
  furc: [number, number][]
}

export interface PerioLimits {
  mm_max: number
  mob_max: number
  furc_max: number
  /** С этой глубины начинается «карман». */
  deep: number
  severe: number
}

export interface PerioModel {
  patient: { id: number; name: string }
  exams: PerioExam[]
  exam: PerioExam | null
  /** Отпечаток осмотра, с которым он приехал; с ним же уезжает запись.
   *  Сервер по нему отличает «лист успело поправить второе рабочее место» от
   *  обычной записи. ⛔ Не замок: запись проходит в любом случае. */
  rev: string
  rows: Record<string, PerioRow>
  teeth: Record<string, PerioTooth>
  arches: { upper: number[]; lower: number[] }
  sites: { key: string; label: string }[]
  summary: PerioSummary
  limits: PerioLimits
  grades: { mob: Record<string, string>; furc: Record<string, string> }
  doctors: string[]
}

export interface PerioSave {
  /** Измерения ТРОНУТЫХ зубов: нетронутый не шлётся вовсе. */
  teeth: Record<string, PerioEdit>
  /** Зубы, О КОТОРЫХ запись сообщает. Стираются только они и только
   *  неприсланные — поэтому зуб, измеренный вторым рабочим местом, переживает
   *  нашу запись (прайоры 08-16 и 18.09). */
  covers: number[]
  /** Отпечаток осмотра при загрузке: по нему сервер говорит, что лист
   *  изменился под нами. */
  rev?: string
  /** Поля нет — «не сообщали»; пустая строка — «стереть». */
  doctor?: string
  note?: string
}

export const EMPTY_ROW: PerioEdit = {
  tooth: 0,
  pd: [0, 0, 0, 0, 0, 0],
  rec: [0, 0, 0, 0, 0, 0],
  bop: '000000',
  mob: 0,
  furc: 0,
}

export function rowOf(model: PerioModel, n: number): PerioEdit {
  const r = model.rows[String(n)]
  return r
    ? { tooth: n, pd: [...r.pd], rec: [...r.rec], bop: r.bop, mob: r.mob, furc: r.furc }
    : { ...EMPTY_ROW, tooth: n, pd: [...EMPTY_ROW.pd], rec: [...EMPTY_ROW.rec] }
}

export function sameRow(a: PerioEdit, b: PerioEdit): boolean {
  return a.bop === b.bop && a.mob === b.mob && a.furc === b.furc
    && a.pd.every((v, i) => v === b.pd[i]) && a.rec.every((v, i) => v === b.rec[i])
}

/** Есть ли у зуба хоть одно показание. Зуб без них не хранится вовсе: пустая
 *  строка в базе неотличима от «измерили, всё в норме», а это разные вещи. */
export function hasData(r: PerioEdit): boolean {
  return r.pd.some((v) => v > 0) || r.rec.some((v) => v > 0)
    || r.bop.includes('1') || r.mob > 0 || r.furc > 0
}

/**
 * Итог ЧЕРНОВИКА — тот же счёт, что у сервера (`perio.summary`), слово в
 * слово: врач видит BOP% и среднюю глубину сразу, не сохраняя осмотр.
 *
 * ⚠️ Это не второй владелец правила, а его предпросмотр: сохранённые числа
 * приезжают с сервера и подменяют эти. Расхождение живёт до записи осмотра,
 * и держит их равенство проверка на тех же данных, что серверный набор.
 * ⚠️ Знаменатель — ИЗМЕРЕННЫЕ точки (PD > 0). Считать от 192 значило бы
 * разбавить кровоточивость вдвое и показать лечение успешнее, чем оно есть.
 */
/**
 * Округление, как у сервера: Python округляет ПОЛОВИНУ К ЧЁТНОМУ, а
 * `Math.round` — вверх. Разница ровно в половинке, и на клинических числах
 * она видна: 10 кровоточащих точек из 80 — это 12.5 %, и браузер показывал бы
 * 13 %, а сервер после записи присылал бы 12. Цифра итога меняется в момент
 * сохранения, без единой правки — ровно то, чего на медицинском листе быть не
 * должно.
 */
export function roundLikeServer(value: number, digits = 0): number {
  const f = 10 ** digits
  const x = value * f
  const r = Math.round(x)
  const isHalf = Math.abs(x % 1) === 0.5
  return (isHalf && r % 2 !== 0 ? r - Math.sign(x) : r) / f
}

export function summarize(rows: PerioEdit[], limits: PerioLimits): PerioSummary {
  let sites = 0, bleed = 0, deep = 0, severe = 0, total = 0, att = 0, teeth = 0
  const mob: [number, number][] = []
  const furc: [number, number][] = []
  for (const r of [...rows].sort((a, b) => a.tooth - b.tooth)) {
    if (!hasData(r)) continue
    teeth += 1
    r.pd.forEach((mm, i) => {
      if (mm <= 0) return
      sites += 1
      total += mm
      att += mm + (r.rec[i] ?? 0)
      if (r.bop[i] === '1') bleed += 1
      if (mm >= limits.severe) { severe += 1; deep += 1 }
      else if (mm >= limits.deep) deep += 1
    })
    if (r.mob) mob.push([r.tooth, r.mob])
    if (r.furc) furc.push([r.tooth, r.furc])
  }
  return {
    teeth,
    sites,
    bop: sites ? roundLikeServer((100 * bleed) / sites) : 0,
    pd_mean: sites ? roundLikeServer(total / sites, 1) : 0,
    cal_mean: sites ? roundLikeServer(att / sites, 1) : 0,
    deep,
    severe,
    mob,
    furc,
  }
}

/** Миллиметры на экране — всегда с одним знаком: сервер отдаёт 3.0 числом,
 *  и без этого плашка показывала бы «3 mm» там, где печать и старая страница
 *  пишут «3.0 mm». */
export function mm1(value: number): string {
  return value.toFixed(1)
}

const P = (pid: number) => `/patients/${pid}/perio`

/**
 * Осмотр из адреса (`?exam=`) — правилом СТРАНИЦЫ сервера: обрезанное
 * значение из одних цифр ASCII — номер, всё прочее — «самый свежий» (null).
 * ⚠️ Не `Number` по сырому значению: «4.0», «+4», «0x4», «1e1» открыли бы
 * конкретный осмотр там, где страница отдаёт свежий. И не сырая строка в API:
 * полноширинную «４» Python читает как 4. Бесконечность (сотни цифр) —
 * тоже свежий, как и было. Один разбор на страницу и на вкладку фиши (B6).
 */
export function examOf(q: URLSearchParams): number | null {
  const raw = (q.getAll('exam').at(-1) ?? '').trim()
  const n = Number(raw)
  return /^\d+$/.test(raw) && Number.isInteger(n) ? n : null
}

export const perio = {
  get: (pid: number, exam: number | null, signal?: AbortSignal) =>
    api.get<PerioModel>(`${P(pid)}${exam ? `?exam=${exam}` : ''}`, signal ? { signal } : {}),
  newExam: (pid: number) => api.post<PerioModel>(`${P(pid)}/exams`, {}),
  save: (pid: number, eid: number, body: PerioSave) =>
    api.post<PerioModel>(`${P(pid)}/${eid}`, body),
  dropExam: (pid: number, eid: number) => api.post<PerioModel>(`${P(pid)}/${eid}/delete`, {}),
}
