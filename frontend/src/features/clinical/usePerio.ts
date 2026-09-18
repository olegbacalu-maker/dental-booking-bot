import { useCallback, useState } from 'react'
import type { ToastState } from '../../components/Toast'
import { asApiError, type ApiResult } from '../../services/api'
import {
  EMPTY_ROW, hasData, perio, rowOf, sameRow, summarize,
  type PerioEdit, type PerioModel, type PerioSave, type PerioSummary,
} from './perio'

/* Состояние листа пародонтограммы: черновик ОСМОТРА целиком, действия и
   предпросмотр итога.

   Черновик здесь на весь лист, а не на зуб (как в одонтограмме): осмотр
   записывается одной кнопкой, потому что и измеряют его подряд — шесть точек
   на зуб, тридцать два зуба. Привязка та же, что у `useChart`: коробка
   помнит, каким осмотр приехал с сервера (`base`), и отпадает сама, когда
   сервер прислал другое — после удачной записи или смены осмотра. Отказ
   сервера модель не трогает, поэтому ввод остаётся на экране.
   ⚠️ Коробка живёт ПО ОСМОТРАМ: переключился на прошлый и вернулся — черновик
   на месте. Старая страница теряла его, потому что уходила перезагрузкой. */

interface Box {
  base: Record<number, PerioEdit>
  d: Record<number, PerioEdit>
  doctor: string
  note: string
}

export type Kind = 'pd' | 'rec'
export type Grade = 'mob' | 'furc'

export interface PerioApi {
  /** Зубы листа по порядку дуг. ⚠️ При записи уезжают не они, а ТРОНУТЫЕ
   *  (`covers`): лист показывает все 32 всегда, и «показали» о намерении не
   *  говорит ничего. */
  shown: number[]
  row: (n: number) => PerioEdit
  /** Итог: серверный, пока черновика нет, и предпросмотр, пока он есть. */
  summary: PerioSummary
  dirty: boolean
  doctor: string
  note: string
  setDoctor: (v: string) => void
  setNote: (v: string) => void
  setCell: (n: number, kind: Kind, i: number, value: number) => void
  toggleBop: (n: number, i: number) => void
  setGrade: (n: number, kind: Grade, value: number) => void
  discard: () => void
  busy: boolean
  save: () => Promise<boolean>
  /** Новый осмотр: отдаёт свежую карту (её id нужен адресу) или null. */
  newExam: () => Promise<PerioModel | null>
  dropExam: (eid: number) => Promise<PerioModel | null>
}

function baseRows(model: PerioModel, shown: number[]): Record<number, PerioEdit> {
  const out: Record<number, PerioEdit> = {}
  for (const n of shown) out[n] = rowOf(model, n)
  return out
}

function sameRows(a: Record<number, PerioEdit>, b: Record<number, PerioEdit>): boolean {
  const ka = Object.keys(a)
  if (ka.length !== Object.keys(b).length) return false
  return ka.every((k) => {
    const x = a[Number(k)]
    const y = b[Number(k)]
    return Boolean(x && y && sameRow(x, y))
  })
}

export function usePerio(
  pid: number,
  model: PerioModel | null,
  replace: (m: PerioModel) => void,
  fail: (e: unknown) => void,
  say: (t: ToastState) => void,
): PerioApi {
  const [boxes, setBoxes] = useState<Record<number, Box>>({})
  const [busy, setBusy] = useState(false)

  const shown = model ? [...model.arches.upper, ...model.arches.lower] : []
  const examId = model?.exam?.id ?? 0
  const base = model ? baseRows(model, shown) : {}
  const box = boxes[examId]
  const fresh: Box = {
    base,
    d: base,
    doctor: model?.exam?.doctor ?? '',
    note: model?.exam?.note ?? '',
  }
  // коробка протухла, если осмотр приехал с сервера другим: запись прошла,
  // и черновик обязан отпасть сам — без эффекта и без счётчика сохранений
  const cur: Box = box && sameRows(box.base, base) ? box : fresh
  const dirty = !sameRows(cur.d, cur.base)
    || cur.doctor !== fresh.doctor || cur.note !== fresh.note

  const put = (patch: Partial<Box>) => {
    if (!model || !examId) return
    setBoxes((prev) => ({ ...prev, [examId]: { ...cur, ...patch } }))
  }

  const row = (n: number): PerioEdit =>
    cur.d[n] ?? (model ? rowOf(model, n) : { ...EMPTY_ROW, tooth: n })

  const editRow = (n: number, patch: Partial<PerioEdit>) => {
    const r = row(n)
    put({ d: { ...cur.d, [n]: { ...r, ...patch } } })
  }

  const setCell = (n: number, kind: Kind, i: number, value: number) => {
    const r = row(n)
    const next = [...r[kind]]
    next[i] = value
    editRow(n, { [kind]: next })
  }

  const toggleBop = (n: number, i: number) => {
    const r = row(n)
    const flags = r.bop.split('')
    flags[i] = flags[i] === '1' ? '0' : '1'
    editRow(n, { bop: flags.join('') })
  }

  const setGrade = (n: number, kind: Grade, value: number) => editRow(n, { [kind]: value })

  const discard = () => {
    setBoxes((prev) => {
      if (!(examId in prev)) return prev
      const next = { ...prev }
      delete next[examId]
      return next
    })
  }

  const act = useCallback(async (
    run: () => Promise<ApiResult<PerioModel>>,
  ): Promise<PerioModel | null> => {
    setBusy(true)
    try {
      const r = await run()
      replace(r.data)
      if (r.text) say({ tone: r.tone, text: r.text })
      return r.data
    } catch (e) {
      fail(asApiError(e))
      return null
    } finally {
      setBusy(false)
    }
  }, [replace, fail, say])

  /**
   * Пересадить черновик на осмотр, который вернул сервер.
   *
   * ⛔ Не «выбросить черновик»: пока шёл запрос, ассистент продолжал диктовать
   * (поля ввода не заперты, и запирать их на полсекунды посреди диктовки —
   * хуже), и эти цифры уже лежат в коробке. Выброси её — они исчезнут молча,
   * потому что на экран приедет запись сервера. Поэтому меняется БАЗА, а ввод
   * остаётся: что сервер записал — перестаёт быть правкой само, что набрали
   * после — остаётся «Nesalvat».
   * ⚠️ Врач и заметка берутся у сервера: он их обрезает (`note.strip()`), и
   * «reevaluare » против «reevaluare» держало бы лист вечно несохранённым.
   */
  const rebase = (m: PerioModel) => {
    const nb = baseRows(m, [...m.arches.upper, ...m.arches.lower])
    const id = m.exam?.id ?? 0
    setBoxes((prev) => {
      const b = prev[id]
      if (!b) return prev
      // ⛔ Зуб, которого МЫ не трогали, берётся у сервера: пока лист был
      // открыт, его могло измерить второе рабочее место, и ответ привёз его
      // сюда. Оставь черновик как есть — колонка показала бы пустоту, лист
      // висел бы «несохранённым», а следующая запись назвала бы этот зуб
      // тронутым и стёрла бы чужую работу.
      const d: Record<number, PerioEdit> = { ...b.d }
      for (const key of Object.keys(nb)) {
        const n = Number(key)
        const mine = b.d[n]
        const was = b.base[n]
        const fromServer = nb[n]
        if (fromServer && mine && was && sameRow(mine, was)) d[n] = fromServer
      }
      return {
        ...prev,
        [id]: { base: nb, d, doctor: m.exam?.doctor ?? '', note: m.exam?.note ?? '' },
      }
    })
  }

  const save = async (): Promise<boolean> => {
    if (!model || !examId) return false
    // ⛔ Сообщаем ТОЛЬКО о тронутом. `covers` называет зубы, изменённые на
    // этом экране, `teeth` везёт их измерения; зуб без показаний в `teeth` не
    // едет, но назван в `covers` — так стирается тот, у кого измерения
    // убрали. Зуб вне `covers` сервер не пишет и не стирает: его могло
    // измерить второе рабочее место, пока лист был открыт (08-16 и 18.09 —
    // потери данных на одном различии «не сообщали» против «стереть»).
    const teeth: Record<string, PerioEdit> = {}
    const covers: number[] = []
    for (const n of shown) {
      const r = row(n)
      if (sameRow(r, cur.base[n] ?? rowOf(model, n))) continue
      covers.push(n)
      if (hasData(r)) teeth[String(n)] = r
    }
    // ⚠️ Подпись и заметка — тем же правилом: уезжают, только если их меняли.
    // Поля нет — «не сообщали», и стала́я вкладка не стирает чужую подпись.
    const body: PerioSave = { teeth, covers, rev: model.rev }
    if (cur.doctor !== fresh.doctor) body.doctor = cur.doctor
    if (cur.note !== fresh.note) body.note = cur.note
    const saved = await act(() => perio.save(pid, examId, body))
    if (!saved) return false
    rebase(saved)
    return true
  }

  const preview = summarize(shown.map(row), model?.limits ?? {
    mm_max: 15, mob_max: 3, furc_max: 3, deep: 4, severe: 6,
  })

  return {
    shown,
    row,
    summary: dirty ? preview : (model?.summary ?? preview),
    dirty,
    doctor: cur.doctor,
    note: cur.note,
    setDoctor: (v) => put({ doctor: v }),
    setNote: (v) => put({ note: v }),
    setCell,
    toggleBop,
    setGrade,
    discard,
    busy,
    save,
    newExam: () => act(() => perio.newExam(pid)),
    dropExam: (eid: number) => act(() => perio.dropExam(pid, eid)),
  }
}
