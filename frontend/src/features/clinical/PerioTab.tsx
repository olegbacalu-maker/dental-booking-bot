import { startTransition, useCallback, useEffect, useRef, useState } from 'react'
import type { ToastState } from '../../components/Toast'
import { asApiError } from '../../services/api'
import { PerioWorkbench } from './PerioWorkbench'
import { perio, type PerioModel } from './perio'
import { usePerio } from './usePerio'

/* Пародонтограмма во вкладке фиши (B6, шаг 3). Лист тот же, что на странице
   (`PerioWorkbench`); владелец осмотра — АДРЕС фиши (`?tab=perio&exam=`), как
   на странице владеет `?exam=`. Загрузчик фиши осмотр не носит (смена query на
   том же пути его не перезапускает — и не должна: полный GET фиши пишет
   «Fișa deschisă» в журнал доступа), поэтому лист грузит себя сам: по монтажу
   и при смене осмотра в адресе. ⛔ Пока едет ДРУГОЙ осмотр, прежний лист снят
   с экрана: набранная в этот миг цифра ушла бы в запись, которую человек
   только что покинул (то же правило, что `leaving` на странице). Черновики
   живут в `usePerio` у владельца и переживают эту смену. */
const T = {
  loading: 'Se încarcă parodontograma…',
  failed: 'Parodontograma nu s-a încărcat.',
} as const

interface Props {
  pid: number
  /** осмотр из адреса фиши; null — самый свежий */
  exam: number | null
  /** сменить осмотр в адресе (replace); null — свежий */
  onExam: (id: number | null) => void
  say: (t: ToastState) => void
  onFail: (e: unknown) => void
}

export function PerioTab({ pid, exam, onExam, say, onFail }: Props) {
  /* `req` — осмотр, ДЛЯ КОТОРОГО модель на экране (запрошенный или отвечённый
     записью); расхождение с адресом = загрузка, и лист снят с экрана */
  const [got, setGot] = useState<{ pid: number; req: number | null; model: PerioModel | null; failed: boolean } | null>(null)
  const mine = got && got.pid === pid ? got : null
  const fresh = mine !== null && mine.req === exam
  const model = fresh ? mine.model : null
  const failed = fresh && Boolean(mine?.failed)
  /* Ответ POST (запись, новый осмотр, снятие пустого) — на экран, и адрес вслед
     за ним, к ЕГО осмотру по номеру. ⚠️ ОДНОЙ отрисовкой: переход роутера React
     рисует переходом (transition), а подмену модели — обычным обновлением, и
     между ними был бы кадр «модель нового осмотра при старом адресе» — эффект
     принял бы его за смену осмотра и послал лишний GET (то же правило, что у
     переключателя ленты в фише). */
  const replace = useCallback((m: PerioModel) => {
    const id = m.exam?.id ?? null
    startTransition(() => {
      setGot({ pid, req: id, model: m, failed: false })
      if (id !== exam) onExam(id)
    })
  }, [pid, exam, onExam])
  /* отказ — через ref: личность `onFail` меняется вслед за адресом (хук
     загрузки фиши), а перезапуск эффекта по ней обрывал бы запрос и слал
     второй — лист ехал дважды на каждую смену осмотра */
  const onFailRef = useRef(onFail)
  useEffect(() => { onFailRef.current = onFail }, [onFail])
  const fail = useCallback((e: unknown) => onFailRef.current(asApiError(e)), [])
  const c = usePerio(pid, model, replace, fail, say)

  useEffect(() => {
    if (fresh) return
    const ctl = new AbortController()
    perio.get(pid, exam, ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setGot({ pid, req: exam, model: r.data, failed: false }) },
      (e: unknown) => {
        if (!ctl.signal.aborted) { setGot({ pid, req: exam, model: null, failed: true }); onFailRef.current(asApiError(e)) }
      },
    )
    return () => ctl.abort()
  }, [pid, exam, fresh])

  const afterExam = () => undefined   // адрес уже сменил `replace`, той же отрисовкой

  if (failed) return <div className="fcard"><p className="hint dp-m0">{T.failed}</p></div>
  if (!model) return <div className="fcard dp-odo-wait" aria-busy="true"><p className="hint dp-m0">{T.loading}</p></div>
  return <PerioWorkbench pid={pid} model={model} c={c} goExam={onExam} afterExam={afterExam} embedded />
}
