import { useCallback, useState } from 'react'
import { asApiError, type ApiResult } from '../../services/api'
import type { ToastState } from '../../components/Toast'
import { chart, rememberView, savedView, type BridgeSave, type Odontogram, type ToothInfo, type ToothSave, type View } from './chart'

/* Состояние клинической карты — одно на детальную страницу и компактную
   карточку: выбранный зуб и поверхность, вид, ЧЕРНОВИКИ зубов, действия
   (зуб, мост) с подменой модели и плашкой сервера. Загрузка модели — у
   экрана (useLoad или тихая загрузка внутри фиши), сюда она приходит уже
   готовой.

   Черновик (C22) явный: правка зуба живёт здесь, а не в форме, потому что
   её делают ТРИ места — форма, клик по поверхности на рисунке (быстрый
   цикл) и контекстное меню. Черновик привязан к зубу и к тому, каким зуб
   был в модели, когда его начали править (`base`): клик по соседу правку
   не теряет (зуб остаётся помечен «нет записи»), а удачная запись меняет
   base — и черновик отпадает сам, без эффекта и без счётчика сохранений.
   Отказ сервера модель не трогает, поэтому ввод остаётся. */
export interface ToothDraft {
  state: string
  sfst: Record<string, string>
  marks: string[]
  doctor: string
  note: string
}

export function draftOf(info: ToothInfo): ToothDraft {
  return { state: info.state, sfst: { ...info.sfst }, marks: [...info.mk], doctor: info.doctor, note: info.note }
}

export function sameDraft(a: ToothDraft, b: ToothDraft): boolean {
  const ka = Object.keys(a.sfst).filter((k) => a.sfst[k]).sort()
  const kb = Object.keys(b.sfst).filter((k) => b.sfst[k]).sort()
  return a.state === b.state && a.doctor === b.doctor && a.note === b.note
    && a.marks.length === b.marks.length && a.marks.every((m) => b.marks.includes(m))
    && ka.length === kb.length && ka.every((k, i) => k === kb[i] && a.sfst[k] === b.sfst[k])
}

/** Быстрый цикл состояния поверхности: «—» → первое частое → … → «—».
 *  Список — сервера (`surface_states`), новых состояний здесь не бывает. */
export function cycleState(cur: string, states: readonly string[]): string {
  const i = states.indexOf(cur)
  if (i < 0) return states[0] ?? ''
  return states[i + 1] ?? ''
}

/** Поверхность, выбранная по умолчанию: первая отмеченная, иначе жевательная —
 *  поверхность выбирается СРАЗУ, иначе список её состояния скрыт до первого
 *  клика по букве, а догадаться, что по букве надо кликать, неоткуда. */
export function defaultSurface(info: ToothInfo, order: string[]): string {
  return order.find((k) => info.sfst[k]) ?? 'O'
}

interface Box { base: ToothDraft; d: ToothDraft }

export interface ChartApi {
  view: View
  setView: (v: View) => void
  selected: number | null
  /** Модель выбранного зуба. */
  info: ToothInfo | undefined
  select: (n: number | null) => void
  sel: string
  setSel: (letter: string) => void
  /** Клик по поверхности на рисунке: выбирает зуб и поверхность; повторный
   *  клик по УЖЕ выбранной поверхности крутит её состояние (быстрый цикл). */
  pickSurface: (n: number, letter: string) => void
  /** Черновик выбранного зуба (модель, пока его не правили). */
  draft: ToothDraft | null
  /** У выбранного зуба есть незаписанная правка. */
  dirty: boolean
  /** Все зубы с незаписанной правкой — для пометки на дуге. */
  dirtyTeeth: ReadonlySet<number>
  edit: (patch: Partial<ToothDraft>) => void
  /** Состояние зуба из контекстного меню: выбирает зуб и правит черновик. */
  setState: (n: number, state: string) => void
  /** Сброс черновика выбранного зуба (Esc, «Renunță»). */
  discard: () => void
  busy: boolean
  /** Запись черновика выбранного зуба (Save, Enter). */
  save: () => Promise<boolean>
  addBridge: (body: BridgeSave) => Promise<boolean>
  delBridge: (bid: number) => Promise<boolean>
}

export function useChart(
  pid: number,
  model: Odontogram | null,
  replace: (m: Odontogram) => void,
  fail: (e: unknown) => void,
  say: (t: ToastState) => void,
  initial: number | null = null,
): ChartApi {
  const [view, setViewState] = useState<View>(() => savedView())
  const [selected, setSelected] = useState<number | null>(initial)
  const [pick, setPick] = useState<{ n: number; sel: string } | null>(null)
  const [boxes, setBoxes] = useState<Record<number, Box>>({})
  const [busy, setBusy] = useState(false)

  const setView = useCallback((v: View) => { rememberView(v); setViewState(v) }, [])
  const select = useCallback((n: number | null) => setSelected(n), [])

  const order = model ? Object.keys(model.surfaces) : []
  const info = model && selected !== null ? model.teeth[String(selected)] : undefined
  const sel = pick && pick.n === selected ? pick.sel : info ? defaultSurface(info, order) : 'O'

  /** Черновик зуба n: ввод пользователя, пока зуб в модели тот же, иначе модель. */
  const draftFor = (n: number): { base: ToothDraft; d: ToothDraft } | null => {
    const t = model?.teeth[String(n)]
    if (!t) return null
    const base = draftOf(t)
    const b = boxes[n]
    return { base, d: b && sameDraft(b.base, base) ? b.d : base }
  }
  const cur = selected !== null ? draftFor(selected) : null
  const draft = cur ? cur.d : null
  const dirty = Boolean(cur && !sameDraft(cur.d, cur.base))
  const dirtyTeeth = new Set<number>()
  for (const k of Object.keys(boxes)) {
    const n = Number(k)
    const x = draftFor(n)
    if (x && !sameDraft(x.d, x.base)) dirtyTeeth.add(n)
  }

  const put = (n: number, base: ToothDraft, d: ToothDraft) => {
    setBoxes((prev) => {
      const next: Record<number, Box> = {}
      for (const k of Object.keys(prev)) {           // протухшие (зуб в модели сменился) — долой
        const t = model?.teeth[k]
        const b = prev[Number(k)]
        if (t && b && sameDraft(b.base, draftOf(t))) next[Number(k)] = b
      }
      next[n] = { base, d }
      return next
    })
  }

  const setSel = (letter: string) => { if (selected !== null) setPick({ n: selected, sel: letter }) }
  const edit = (patch: Partial<ToothDraft>) => {
    if (selected === null || !cur) return
    put(selected, cur.base, { ...cur.d, ...patch })
  }
  const setState = (n: number, state: string) => {
    const x = draftFor(n)
    if (!x) return
    setSelected(n)
    put(n, x.base, { ...x.d, state })
  }
  const pickSurface = (n: number, letter: string) => {
    if (n === selected && letter === sel && cur && model) {
      const sfst = { ...cur.d.sfst }
      const next = cycleState(sfst[letter] ?? '', model.surface_states)
      if (next) sfst[letter] = next
      else delete sfst[letter]
      put(n, cur.base, { ...cur.d, sfst })
      return
    }
    setSelected(n)
    setPick({ n, sel: letter })
  }
  const discard = () => {
    if (selected === null) return
    setBoxes((prev) => {
      if (!(selected in prev)) return prev
      const next = { ...prev }
      delete next[selected]
      return next
    })
  }

  const act = useCallback(async (run: () => Promise<ApiResult<Odontogram>>): Promise<boolean> => {
    setBusy(true)
    try {
      const r = await run()
      replace(r.data)
      if (r.text) say({ tone: r.tone, text: r.text })
      return true
    } catch (e) {
      fail(asApiError(e))
      return false
    } finally {
      setBusy(false)
    }
  }, [replace, fail, say])

  const save = () => {
    if (selected === null || !info || !cur) return Promise.resolve(false)
    const n = selected
    const d = cur.d
    const body: ToothSave = { state: d.state, state0: info.state, note: d.note, doctor: d.doctor, surfaces: d.sfst, marks: d.marks }
    return act(() => chart.saveTooth(pid, n, body))
  }

  return {
    view, setView, selected, info, select, sel, setSel, pickSurface,
    draft, dirty, dirtyTeeth, edit, setState, discard, busy, save,
    addBridge: (body) => act(() => chart.addBridge(pid, body)),
    delBridge: (bid) => act(() => chart.delBridge(pid, bid)),
  }
}
