import { useCallback, useState } from 'react'
import { asApiError, type ApiResult } from '../../services/api'
import type { ToastState } from '../../components/Toast'
import { chart, rememberView, savedView, type BridgeSave, type Odontogram, type ToothSave, type View } from './chart'
import { defaultSurface } from './ToothForm'

/* Состояние клинической карты — одно на детальную страницу и компактную
   карточку: выбранный зуб и поверхность, вид, действия (зуб, мост) с
   подменой модели и плашкой сервера. Загрузка модели — у экрана (useLoad
   или тихая загрузка внутри фиши), сюда она приходит уже готовой. */
export interface ChartApi {
  view: View
  setView: (v: View) => void
  selected: number | null
  select: (n: number | null) => void
  sel: string
  setSel: (letter: string) => void
  /** Клик по поверхности на рисунке: выбирает зуб и поверхность. */
  pickSurface: (n: number, letter: string) => void
  busy: boolean
  saves: number
  formKey: string
  saveTooth: (n: number, body: ToothSave) => Promise<boolean>
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
  const [busy, setBusy] = useState(false)
  const [saves, setSaves] = useState(0)

  const setView = useCallback((v: View) => { rememberView(v); setViewState(v) }, [])
  const select = useCallback((n: number | null) => setSelected(n), [])
  const setSel = useCallback((letter: string) => {
    setSelected((n) => { if (n !== null) setPick({ n, sel: letter }); return n })
  }, [])
  const pickSurface = useCallback((n: number, letter: string) => {
    setSelected(n)
    setPick({ n, sel: letter })
  }, [])

  const order = model ? Object.keys(model.surfaces) : []
  const info = model && selected !== null ? model.teeth[String(selected)] : undefined
  const sel = pick && pick.n === selected ? pick.sel : info ? defaultSurface(info, order) : 'O'

  const act = useCallback(async (run: () => Promise<ApiResult<Odontogram>>): Promise<boolean> => {
    setBusy(true)
    try {
      const r = await run()
      replace(r.data)
      setSaves((k) => k + 1)
      if (r.text) say({ tone: r.tone, text: r.text })
      return true
    } catch (e) {
      fail(asApiError(e))
      return false
    } finally {
      setBusy(false)
    }
  }, [replace, fail, say])

  return {
    view, setView, selected, select, sel, setSel, pickSurface, busy, saves,
    formKey: `${selected ?? 0}-${saves}`,
    saveTooth: (n, body) => act(() => chart.saveTooth(pid, n, body)),
    addBridge: (body) => act(() => chart.addBridge(pid, body)),
    delBridge: (bid) => act(() => chart.delBridge(pid, bid)),
  }
}
