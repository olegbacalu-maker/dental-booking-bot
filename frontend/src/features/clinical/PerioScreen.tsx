import { useCallback, useState } from 'react'
import { useNavigate, useNavigation } from 'react-router'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { PerioWorkbench } from './PerioWorkbench'
import { examOf, perio, type PerioModel } from './perio'
import { usePerio } from './usePerio'

/* Пародонтограмма (C23) на всю ширину: сайдбар узкий — рамку даёт сервер. Сам
   лист (дуги, ввод диктовкой, итог, шапка с осмотрами) — в `PerioWorkbench`,
   он же стоит во вкладке Parodontogramă фиши (B6, шаг 3). Здесь — загрузка,
   осмотр из адреса, «уход» к другому осмотру и плашки. */
const T = {
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  pid: number
  navigate?: (url: string) => void
}

/**
 * Данные грузит роутер (B2.3): фишу — из пути, осмотр — из `?exam=` ТЕКУЩЕГО
 * адреса. Владелец «какой осмотр» — адрес, и больше никто; на экране — эхо
 * сервера (`model.exam`): чужой или несуществующий номер он сводит к свежему.
 */
export const loadPerio: RouteLoad<PerioModel> = (signal, params, q) =>
  perio.get(Number(params.pid), examOf(q), signal)

export function PerioScreen({ pid, navigate = defaultNavigate }: Props) {
  const { state, pending, retry, replace, leaveIfSignedOut } = useRouteLoad<PerioModel>(navigate)
  const to = useNavigate()
  const target = useNavigation().location
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const say = useCallback((x: ToastState) => setToast(x), [])
  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])
  const data = state.status === 'ready' ? state.data : null
  /* ⛔ Переход к ДРУГОМУ осмотру ждёт загрузчика, а роутер тем временем держит
     прежний. Его не показывать: набранная в этот миг цифра ушла бы в запись,
     которую человек только что покинул. Ответ POST (новый или оставшийся
     осмотр) уже И ЕСТЬ тот, куда ведёт адрес, — он остаётся на экране, как и
     до роутера. */
  const leaving = pending && data !== null
    && examOf(new URLSearchParams(target?.search ?? '')) !== (data.exam?.id ?? null)
  const model = leaving ? null : data
  const c = usePerio(pid, model, replace, fail, say)

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }
  if (!model) {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const base = `/admin/patient/${pid}`

  /** Адрес листа: осмотр виден в ссылке, поэтому F5 и «открыть ещё раз»
   *  возвращают туда же, а не к самому свежему. Пишет его РОУТЕР, и загрузчик
   *  читает уже новый адрес. `replace`, как и было: смена осмотра не копит
   *  шаги «Назад». Query — заново: `msg` прошлого адреса повторил бы плашку. */
  const goTo = (id: number | null, now = false) => {
    void to(`${base}/parodontograma${id ? `?exam=${id}` : ''}`, { replace: true, flushSync: now })
  }

  const goExam = (id: number) => {
    // ⛔ Сначала В ЗАГРУЗКУ, потом запрос: иначе прежний осмотр висит на экране
    // весь ответ, а набранная в этот миг цифра уходит в него — в запись,
    // которую человек только что покинул. Загрузку рисует `leaving`, а
    // `flushSync` ставит её на экран ещё в этом событии, как это делал reset().
    goTo(id, true)
  }

  /* После POST ответ уже на экране (`replace`); адрес ведёт к ЕГО осмотру по
     номеру, и загрузчик перечитывает именно его, а не «самый свежий», который
     могло тем временем завести второе рабочее место. */
  const afterExam = (m: PerioModel | null) => {
    if (m) goTo(m.exam?.id ?? null)
  }

  return (
    <section className="dp-react-root">
      <PerioWorkbench pid={pid} model={model} c={c} goExam={goExam} afterExam={afterExam} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
