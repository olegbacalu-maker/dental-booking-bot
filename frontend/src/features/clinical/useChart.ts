import { useCallback, useEffect, useMemo, useState } from 'react'
import { asApiError, type ApiResult } from '../../services/api'
import type { ToastState } from '../../components/Toast'
import { chart, rememberView, savedView, type BridgeSave, type Odontogram, type TeethItem, type ToothInfo, type View } from './chart'

/* Состояние клинической карты — одно на детальную страницу и компактную
   карточку: выбранный зуб и поверхность, вид, ЧЕРНОВИКИ зубов, действия
   (зубы, мост) с подменой модели и плашкой сервера. Загрузка модели — у
   экрана (useLoad или тихая загрузка внутри фиши), сюда она приходит уже
   готовой.

   Черновик (C22) явный: правка зуба живёт здесь, а не в форме, потому что
   её делают ТРИ места — форма, клик по поверхности на рисунке (быстрый
   цикл) и контекстное меню. Черновик привязан к зубу и к тому, каким зуб
   был в модели, когда его начали править (`base`): клик по соседу правку
   не теряет (зуб остаётся помечен «нет записи»), а удачная запись меняет
   base — и черновик отпадает сам, без эффекта и без счётчика сохранений.
   Отказ сервера модель не трогает, поэтому ввод остаётся.

   Волна 2 (Олег 25.10: «сначала всю работу и потом сохранить»):
   - запись — ВСЕХ черновиков разом (`saveAll`, «Salvează tot», Enter), всё
     или ничего; `base` уезжает на сервер, и зуб, изменённый с тех пор на
     другом компьютере, даёт отказ 409: модель перечитывается, черновики
     прочих зубов переживают (их base совпал), черновик конфликтного уходит
     как устаревший — плашка сервера называет зуб;
   - черновик виден СРАЗУ: сервер рисует зубы такими, какими их сделала бы
     запись (`chart.preview`, то же правило и тот же построитель — второго
     рисовальщика и второго нормализатора у клиента нет), и виды получают
     `shown` — сохранённую модель с этими зубами. Сцена 3D играет смену
     состояния в момент выбора; после записи зуб в модели тот же, что в
     предпросмотре, и второй раз она не играет. Пока идёт новый
     предпросмотр, виден прежний: иначе сцена отыграла бы назад к
     сохранённому и вперёд снова. Черновик снят (отмена, запись, правка
     вернула зуб к записанному) — его предпросмотр забыт, а запрос, ещё
     идущий за ним, оборван: эффект предпросмотра снимается при любой смене
     того, что нужно рисовать. Ответ, всё же успевший лечь после записи,
     вида не меняет: предпросмотр годен только грязному зубу с тем же `base`. */
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

/** Поверхность, выбранная по умолчанию: первая отмеченная, иначе жевательная —
 *  поверхность выбирается СРАЗУ, иначе список её состояния скрыт до первого
 *  клика по букве, а догадаться, что по букве надо кликать, неоткуда. */
export function defaultSurface(info: ToothInfo, order: string[]): string {
  return order.find((k) => info.sfst[k]) ?? 'O'
}

/** «Dintele 16 are» / «Dinții 16, 21 au» — подлежащее вопросов о несохранённом
 *  (уход, «Reîncarcă», печать); вопрос дописывает место, которое спрашивает. */
export function unsavedTeeth(teeth: readonly number[]): string {
  return teeth.length === 1
    ? `Dintele ${teeth[0]} are modificări nesalvate în formula dentară.`
    : `Dinții ${teeth.join(', ')} au modificări nesalvate în formula dentară.`
}

/** Черновик строкой — каноном (поверхности без пустых, по букве; отметки по
 *  порядку): ключ предпросмотра. Строка — JSON самого черновика, поэтому
 *  запрос предпросмотра собирается из ключа, без второго источника. */
function keyOf(d: ToothDraft): string {
  const sfst: Record<string, string> = {}
  for (const k of Object.keys(d.sfst).filter((x) => d.sfst[x]).sort()) sfst[k] = d.sfst[k]!
  return JSON.stringify({ state: d.state, sfst, marks: [...d.marks].sort(), doctor: d.doctor, note: d.note })
}

/** Зуб записи (и предпросмотра): поля записи зуба — намерение явным полем, как
 *  было у записи по одному (`state0` — каким зуб показан), плюс `base`. */
function itemOf(n: number, base: ToothDraft, d: ToothDraft): TeethItem {
  return {
    n, state: d.state, state0: base.state, note: d.note, doctor: d.doctor, surfaces: d.sfst, marks: d.marks,
    base: { state: base.state, sfst: base.sfst, marks: base.marks, doctor: base.doctor, note: base.note },
  }
}

interface Box { base: ToothDraft; d: ToothDraft }
interface Preview { base: string; key: string; info: ToothInfo }
interface Pending { n: number; base: ToothDraft; d: ToothDraft }

export interface ChartApi {
  view: View
  setView: (v: View) => void
  selected: number | null
  /** Модель выбранного зуба. */
  info: ToothInfo | undefined
  select: (n: number | null) => void
  sel: string
  setSel: (letter: string) => void
  /** Кисть (11.10): состояние поверхности, которым красит клик — `carie`,
   *  `obturatie` или null (клик только выбирает). Липкая: держится между
   *  зубами, снимается повтором, Esc или сама — когда состояний поверхностей
   *  у зуба быть не может (коронка, имплант, удалён, отсутствует). */
  brush: string | null
  setBrush: (k: string | null) => void
  /** Клик по поверхности на рисунке, в сцене, по полю крупного зуба панели или
   *  по строке списка поверхностей: выбирает
   *  зуб и поверхность; с кистью — ставит её состояние на поверхность, по уже
   *  такой же — снимает. */
  pickSurface: (n: number, letter: string) => void
  /** Черновик выбранного зуба (модель, пока его не правили). */
  draft: ToothDraft | null
  /** У выбранного зуба есть незаписанная правка. */
  dirty: boolean
  /** Все зубы с незаписанной правкой — для пометки на дуге. */
  dirtyTeeth: ReadonlySet<number>
  /** Те же зубы по возрастанию — подвал, вопросы, запись. */
  pending: readonly number[]
  /** Что рисуют виды (3D, дуга, карта): сохранённая модель с зубами черновиков
   *  в предпросмотре сервера. Панель, меню и счётчик записанного читают
   *  сохранённую модель. */
  shown: Odontogram | null
  edit: (patch: Partial<ToothDraft>) => void
  /** Состояние зуба из контекстного меню: выбирает зуб и правит черновик. */
  setState: (n: number, state: string) => void
  /** Отметка зуба из контекстного меню («În tratament», «Nerv extras»):
   *  переключает её в черновике и выбирает зуб — запись, как у состояния. */
  toggleMark: (n: number, mark: string) => void
  /** Сброс черновика выбранного зуба (Esc, «Renunță»). */
  discard: () => void
  busy: boolean
  /** Запись черновиков ВСЕХ зубов («Salvează tot», Enter): записанные номера
   *  или null (нечего писать, отказ). */
  saveAll: () => Promise<number[] | null>
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
  /** Хвост адреса записи (`chart.saveTeeth`): фиша просит им себя в ответ. */
  saveQuery = '',
): ChartApi {
  const [view, setViewState] = useState<View>(() => savedView())
  const [selected, setSelected] = useState<number | null>(initial)
  const [pick, setPick] = useState<{ n: number; sel: string } | null>(null)
  const [boxes, setBoxes] = useState<Record<number, Box>>({})
  const [previews, setPreviews] = useState<Record<number, Preview>>({})
  const [busy, setBusy] = useState(false)
  const [brush, setBrushState] = useState<string | null>(null)
  const setBrush = useCallback((k: string | null) => setBrushState((cur) => (k === null || k === cur ? null : k)), [])

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

  /* грязные зубы и вид экрана — от модели, черновиков и предпросмотров: без
     них вид — та же модель (тот же объект, сцене нечего перекрашивать) */
  const { pending, shown, want } = useMemo(() => {
    const out: Pending[] = []
    for (const k of Object.keys(boxes)) {
      const n = Number(k)
      const t = model?.teeth[k]
      const b = boxes[n]
      if (!t || !b) continue
      const base = draftOf(t)
      if (sameDraft(b.base, base) && !sameDraft(b.d, base)) out.push({ n, base, d: b.d })
    }
    out.sort((a, b) => a.n - b.n)
    let teeth: Record<string, ToothInfo> | null = null
    const ask: [number, string, string][] = []
    for (const p of out) {
      const bk = keyOf(p.base)
      const dk = keyOf(p.d)
      const pv = previews[p.n]
      if (pv && pv.base === bk) {
        teeth ??= { ...model!.teeth }
        teeth[String(p.n)] = pv.info
      }
      if (!pv || pv.base !== bk || pv.key !== dk) ask.push([p.n, bk, dk])
    }
    return {
      pending: out,
      shown: model && teeth ? { ...model, teeth } : model,
      want: ask.length ? JSON.stringify(ask) : '',
    }
  }, [model, boxes, previews])
  const dirtyTeeth = useMemo(() => new Set(pending.map((p) => p.n)), [pending])
  const pendingNums = useMemo(() => pending.map((p) => p.n), [pending])

  /* предпросмотр: зубы, чей черновик сервер ещё не рисовал, — одним запросом;
     новый черновик обрывает прежний запрос, ответ снятого — не применяется */
  useEffect(() => {
    if (!want) return
    const rows = JSON.parse(want) as [number, string, string][]
    const ctl = new AbortController()
    const items = rows.map(([n, bk, dk]) => {
      const it = itemOf(n, JSON.parse(bk) as ToothDraft, JSON.parse(dk) as ToothDraft)
      delete it.base                              // предпросмотру сверять нечего
      return it
    })
    /* предпросмотр — не главное: что бы с ним ни случилось, экран остаётся
       (виды рисуют сохранённое, черновик отмечен кольцом и в панели) */
    Promise.resolve().then(() => chart.preview(pid, items, ctl.signal)).then((r) => {
      if (ctl.signal.aborted) return
      const fresh = rows.filter(([n]) => r.data.teeth[String(n)])
      if (!fresh.length) return
      setPreviews((prev) => {
        const next = { ...prev }
        for (const [n, bk, dk] of fresh) next[n] = { base: bk, key: dk, info: r.data.teeth[String(n)]! }
        return next
      })
    }).catch(() => {})
    return () => ctl.abort()
  }, [pid, want])

  /** Черновики этих зубов сняты: предпросмотр забыть — к следующему черновику
   *  того же зуба он не прилипнет. */
  const forget = (ns: readonly number[]) => {
    setPreviews((prev) => {
      if (!ns.some((n) => n in prev)) return prev
      const next = { ...prev }
      for (const n of ns) delete next[n]
      return next
    })
  }

  const put = (n: number, base: ToothDraft, d: ToothDraft) => {
    const clean = sameDraft(d, base)          // правка вернула зуб к записанному
    if (clean) forget([n])
    setBoxes((prev) => {
      const next: Record<number, Box> = {}
      for (const k of Object.keys(prev)) {           // протухшие (зуб в модели сменился) — долой
        const t = model?.teeth[k]
        const b = prev[Number(k)]
        if (t && b && sameDraft(b.base, draftOf(t))) next[Number(k)] = b
      }
      if (clean) delete next[n]
      else next[n] = { base, d }
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
  const toggleMark = (n: number, mark: string) => {
    const x = draftFor(n)
    if (!x) return
    setSelected(n)
    const on = x.d.marks.includes(mark)
    put(n, x.base, { ...x.d, marks: on ? x.d.marks.filter((m) => m !== mark) : [...x.d.marks, mark] })
  }
  const pickSurface = (n: number, letter: string) => {
    setSelected(n)
    setPick({ n, sel: letter })
    if (!brush || !model || !model.surface_states.includes(brush)) return
    const x = draftFor(n)
    if (!x) return
    // кисть красит только там, где у поверхностей бывает состояние: под
    // коронкой, имплантом, удалённым и отсутствующим зубом клик — выбор
    if (!(x.d.state === 'ok' || model.surface_states.includes(x.d.state))) return
    const sfst = { ...x.d.sfst }
    if (sfst[letter] === brush) delete sfst[letter]
    else sfst[letter] = brush
    put(n, x.base, { ...x.d, sfst })
  }
  const discard = () => {
    if (selected === null) return
    const n = selected
    forget([n])
    setBoxes((prev) => {
      if (!(n in prev)) return prev
      const next = { ...prev }
      delete next[n]
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

  const saveAll = async (): Promise<number[] | null> => {
    if (!pending.length) return null
    const ns = pending.map((p) => p.n)
    const items = pending.map((p) => itemOf(p.n, p.base, p.d))
    setBusy(true)
    try {
      const r = await chart.saveTeeth(pid, items, saveQuery)
      // записанное снимает черновики само (base сменился), но и явно: зуб, чья
      // запись совпала с прежней строкой (заметка из одних пробелов), иначе
      // остался бы «несохранённым» навсегда
      forget(ns)
      setBoxes((prev) => {
        const next = { ...prev }
        for (const n of ns) delete next[n]
        return next
      })
      replace(r.data)
      if (r.text) say({ tone: r.tone, text: r.text })
      return ns
    } catch (e) {
      const err = asApiError(e)
      fail(err)
      // зуб изменили на другом компьютере: свежая модель — черновики прочих
      // переживают, черновик этого зуба уходит как устаревший (плашка его назвала)
      if (err.code === 'odo_conflict') {
        try {
          replace((await chart.get(pid)).data)
        } catch {
          /* не перечиталась — плашка конфликта уже на экране */
        }
      }
      return null
    } finally {
      setBusy(false)
    }
  }

  return {
    view, setView, selected, info, select, sel, setSel, brush, setBrush, pickSurface,
    draft, dirty, dirtyTeeth, pending: pendingNums, shown, edit, setState, toggleMark, discard, busy, saveAll,
    addBridge: (body) => act(() => chart.addBridge(pid, body)),
    delBridge: (bid) => act(() => chart.delBridge(pid, bid)),
  }
}
