import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { chart, shownTeeth, type Compare, type Odontogram } from './chart'

/* «Сравнить с визитом» (волна 2 одонтограммы, 25.10; Олег 24.10: «сравнение с
   визитом — волна 2»). Врач выбирает прошлый визит и видит, какие зубы с тех
   пор изменились: было → стало словами сервера, а виды — сцена, дуга, ряд —
   рисуют ТОТ ЖЕ `shown`-путь, что у черновика: сохранённая модель, где
   изменившиеся зубы и мосты заменены ответом сервера на ту дату («Era»), или
   нынешняя («Acum»). Изменившиеся отмечены гашением прочих — тем же `dim`, что
   у режимов и легенды. Второго рисовальщика нет: зуб «было» строит
   `odontogram.tooth_entry`.

   ⛔ Слой — свойство ЭКРАНА: ни в запись, ни в 043/e, ни в печать (рабочий
   стол закрывает его перед печатью). С черновиками не смешивается: открыть
   при черновиках нельзя, пока открыт — правка выключена (рабочий стол).
   Выбор визита не запоминается. */

export type CmpSide = 'was' | 'now'

export interface CompareState {
  open: boolean
  /** выбранный визит */
  visit: number | null
  /** ответ сервера для `visit`; null — ещё не пришёл */
  data: Compare | null
  busy: boolean
  side: CmpSide
  /** зуб, подсвеченный в списке и кольцом в видах */
  focus: number | null
  /** открыть: визит по умолчанию — последний С ДАННЫМИ, иначе последний */
  start: () => void
  close: () => void
  pick: (visit: number) => void
  setSide: (s: CmpSide) => void
  setFocus: (n: number | null) => void
  /** что рисуют виды; null — то же, что без сравнения */
  shown: Odontogram | null
  /** зубы, которые сравнение гасит (не изменившиеся); null — никого */
  dim: ReadonlySet<number> | null
}

/** Модель «было»: изменившиеся зубы и мосты той даты поверх сохранённой. Молочный
 *  ряд открыт, если он нужен хоть одной из двух карт, — на обеих сторонах, иначе
 *  переключатель Era/Acum сдвигал бы раскладку. */
export function compareShown(model: Odontogram, data: Compare | null, side: CmpSide): Odontogram | null {
  if (!data?.known) return null
  const milk = model.milk_open || data.milk_open
  if (side === 'now') return milk === model.milk_open ? null : { ...model, milk_open: milk }
  return { ...model, teeth: { ...model.teeth, ...data.teeth }, bridges: data.bridges, milk_open: milk }
}

/** Неизменившиеся зубы экрана — их гасит сравнение. */
export function compareDim(model: Odontogram, data: Compare | null): ReadonlySet<number> | null {
  if (!data?.known) return null
  const changed = new Set(data.changes.map((c) => c.n))
  return new Set(shownTeeth({ ...model, milk_open: model.milk_open || data.milk_open }).filter((n) => !changed.has(n)))
}

export function useCompare(pid: number, model: Odontogram, fail: (e: unknown) => void): CompareState {
  const [open, setOpen] = useState(false)
  const [visit, setVisit] = useState<number | null>(null)
  const [data, setData] = useState<Compare | null>(null)
  const [busy, setBusy] = useState(false)
  const [side, setSide] = useState<CmpSide>('was')
  const [focus, setFocus] = useState<number | null>(null)
  const ctl = useRef<AbortController | null>(null)
  /* запрос — по действию человека (выбор визита), не эффектом: ответ прежнего
     визита обрывается и не ложится поверх нового */
  const pick = useCallback((id: number) => {
    ctl.current?.abort()
    const ac = new AbortController()
    ctl.current = ac
    setVisit(id)
    setData(null)
    setFocus(null)
    setSide('was')
    setBusy(true)
    chart.compare(pid, id, ac.signal).then((r) => {
      if (ac.signal.aborted) return
      setData(r.data)
      setBusy(false)
    }, (e: unknown) => {
      if (ac.signal.aborted) return
      setBusy(false)
      fail(e)
    })
  }, [pid, fail])
  const visits = model.visits
  const start = useCallback(() => {
    const first = visits?.find((v) => v.known) ?? visits?.[0]
    if (!first) return
    setOpen(true)
    pick(first.id)
  }, [visits, pick])
  const close = useCallback(() => {
    ctl.current?.abort()
    ctl.current = null
    setOpen(false)
    setVisit(null)
    setData(null)
    setBusy(false)
    setFocus(null)
  }, [])
  useEffect(() => () => ctl.current?.abort(), [])
  const live = open ? data : null
  const shown = useMemo(() => compareShown(model, live, side), [model, live, side])
  const dim = useMemo(() => compareDim(model, live), [model, live])
  return { open, visit, data: live, busy, side, focus, start, close, pick, setSide, setFocus, shown, dim }
}
