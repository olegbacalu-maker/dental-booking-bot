/**
 * Геометрия графиков — без единой библиотеки, как и на сервере
 * (`core/charts.py`). Причина та же: программа ставится клинике ОДНИМ exe и
 * работает без интернета, значит любая библиотека уехала бы внутрь сборки —
 * мегабайты к файлу, который качают по мобильному интернету, и чужой код в
 * медицинской программе ради четырёх фигур.
 *
 * ⛔ Здесь только ЧИСЛА: точки, дуги, подписи. Разметку рисуют компоненты, а
 * цвета берутся из темы клиники (`var(--teal)` и прочие), потому что
 * фирменный цвет зашитым хексом не работает с 08-09.
 * ⚠️ Размеры — в координатах viewBox, наружу отдаётся `width='100%'`:
 * карточка решает ширину сама, а числа внутри остаются целыми. Это тот же
 * договор, что у серверных фигур, и ломать его нельзя — CSS у них общий
 * (panel.css: `.spark`, `.linechart`, `.donut`, `.gauge`).
 */

/**
 * Точки спарклайна: ряд чисел → строка координат для `<polyline>`.
 *
 * ⛔ Нормировка по СВОЕМУ максимуму, а не по общей шкале: пять плиток на одной
 * шкале (24 записи и 2 неявки) дали бы прямую под потолком и прямую по полу,
 * то есть ничего.
 * ⛔ Ряд из одних нулей — это РОВНАЯ ЛИНИЯ ПО ПОЛУ, а не пустое место: две
 * недели без единой записи говорят ровно столько же, сколько две недели с
 * записями, и график обязан это сказать. Пустой ряд (`[]`) — другое дело, там
 * графика нет вовсе.
 */
export function sparkPoints(series: number[], h = 26): string {
  if (!series.length) return ''
  const w = 100, pad = 3
  const top = Math.max(...series) || 1
  const step = w / Math.max(series.length - 1, 1)
  return series
    .map((v, i) => `${(i * step).toFixed(1)},${(h - pad - (h - 2 * pad) * (v / top)).toFixed(1)}`)
    .join(' ')
}

/** Одна засечка оси Y: где линия сетки и какое число подписано слева. */
export interface LineGrid {
  y: number
  label: number
}

export interface LinePoint {
  x: number
  y: number
  v: number
}

export interface LinePlot {
  w: number
  h: number
  /** Пусто, когда рисовать нечего: экран показывает фразу вместо графика. */
  points: string
  dots: LinePoint[]
  grid: LineGrid[]
  xLabels: { x: number; text: string }[]
  /** Левая и правая границы площади — для заливки под линией. */
  x0: number
  x1: number
  yZero: number
}

/**
 * Дневной график с осью: сколько записей в каждый день периода.
 *
 * ⚠️ Подписи здесь настоящий ТЕКСТ, поэтому картинку нельзя растягивать по
 * одной оси — буквы поехали бы вместе с ней. Масштабируется целиком (meet), а
 * густые периоды прореживают подписи по оси X: 30 дат в ряд всё равно
 * нечитаемы.
 * ⭐ Потолок округляется вверх до «круглого» (шаг × 4), чтобы подписи оси были
 * человеко-читаемы, а не «0 / 7 / 14 / 21».
 */
export function linePlot(labels: string[], values: number[]): LinePlot {
  const w = 640, h = 210
  const l = 34, r = 8, t = 16, b = 26
  const empty: LinePlot = {
    w, h, points: '', dots: [], grid: [], xLabels: [], x0: l, x1: w - r, yZero: h - b,
  }
  if (!values.length) return empty
  const top = Math.max(...values) || 1
  const stepY = Math.max(1, Math.ceil(top / 4))
  const topR = stepY * 4
  const iw = w - l - r, ih = h - t - b
  const dx = iw / Math.max(values.length - 1, 1)
  const x = (i: number) => l + i * dx
  const y = (v: number) => t + ih - ih * (v / topR)

  const grid: LineGrid[] = []
  for (let k = 0; k < 5; k++) {
    const val = stepY * k
    grid.push({ y: +y(val).toFixed(1), label: val })
  }
  const dots = values.map((v, i) => ({ x: +x(i).toFixed(1), y: +y(v).toFixed(1), v }))
  /* густой период: подписи через одну и реже, но последняя дата — всегда */
  const every = Math.max(1, Math.floor(labels.length / 8))
  const xLabels = labels
    .map((text, i) => ({ text, i }))
    .filter(({ i }) => i % every === 0 || i === labels.length - 1)
    .map(({ text, i }) => ({ x: +x(i).toFixed(1), text }))

  return {
    w, h,
    points: dots.map((d) => `${d.x},${d.y}`).join(' '),
    dots, grid, xLabels,
    x0: l, x1: +x(values.length - 1).toFixed(1), yZero: +y(0).toFixed(1),
  }
}

export interface DonutArc {
  label: string
  color: string
  /** `stroke-dasharray` и `stroke-dashoffset` готовыми числами. */
  dash: string
  offset: number
}

export interface DonutPlot {
  total: number
  arcs: DonutArc[]
}

/**
 * Кольцо долей.
 *
 * ⭐ Доли считаются от суммы ПОКАЗАННЫХ частей, поэтому подписи процентов
 * рядом всегда сходятся в 100 — а не «почти», как выходит при округлении
 * каждой доли отдельно от какого-то внешнего итога.
 */
export function donutArcs(parts: { label: string; value: number; color: string }[]): DonutPlot {
  const total = parts.reduce((s, p) => s + p.value, 0)
  const arcs: DonutArc[] = []
  if (!total) return { total, arcs }
  const circ = 2 * Math.PI * DONUT_R
  let off = 0
  for (const p of parts) {
    if (p.value <= 0) continue
    const ln = circ * p.value / total
    arcs.push({
      label: p.label, color: p.color,
      dash: `${ln.toFixed(2)} ${(circ - ln).toFixed(2)}`,
      offset: +(-off).toFixed(2),
    })
    off += ln
  }
  return { total, arcs }
}

export const DONUT_R = 54
export const DONUT_C = 70

/**
 * Полукруг загрузки. Дуга — один путь, доля «выкушена» пунктиром: так
 * анимация появления бесплатна, CSS двигает один `stroke-dashoffset`.
 *
 * ⚠️ Зазор пунктира — ДВЕ длины дуги, не одна: анимация стартует со сдвига в
 * целую дугу, и при зазоре в одну длину узор успел бы повториться — на первом
 * кадре мелькал бы ХВОСТ дуги вместо пустоты.
 */
export function gaugeArc(pct: number): { pct: number; path: string; dash: string } {
  const p = Math.max(0, Math.min(100, Math.trunc(pct)))
  const r = 62, cx = 75, cy = 78
  const ln = Math.PI * r
  return {
    pct: p,
    path: `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`,
    dash: `${(ln * p / 100).toFixed(2)} ${(ln * 2).toFixed(2)}`,
  }
}
