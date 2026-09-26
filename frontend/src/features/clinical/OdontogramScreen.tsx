import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import {
  intParam, searchChangeKeepsData, useRouteLoad, type RouteLoad, type ScreenData,
} from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { OdontogramWorkbench } from './OdontogramWorkbench'
import { chart, type Odontogram } from './chart'

/* Детальная одонтограмма (C21) на всю ширину: сайдбар узкий — рамку с rail=True
   даёт сервер. Сам инструмент (дуга, инспектор, мосты, клавиатура) — в
   `OdontogramWorkbench`, он же стоит во вкладке Odontogramă фиши (B6, шаг 2).
   Здесь только загрузка, зуб из адреса и плашки. */
const T = {
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  pid: number
  navigate?: (url: string) => void
}

/**
 * Данные экрана грузит роутер (B2.2), App.tsx › LOADS. ⭐ Смена query на том
 * же пути (`?t=` — зуб в фокус) загрузчик НЕ перезапускает (B4.3): карта та же,
 * а повторный GET лишь гонял бы ту же одонтограмму по кругу на каждый фокус.
 */
export const loadOdontogram: ScreenData = {
  load: ((signal, params) => chart.get(Number(params.pid), signal)) satisfies RouteLoad<Odontogram>,
  shouldRevalidate: searchChangeKeepsData,
}

export function OdontogramScreen({ pid, navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<Odontogram>(navigate)
  /* Зуб в фокус — из АДРЕСА (`?t=`), а не из узла документа (B4.3): узел
     описывает адрес первой загрузки, и после перехода без перезагрузки он
     остался бы от чужого адреса. Выбор переживает перезагрузку, как и раньше. */
  const [q] = useSearchParams()
  const t = intParam(q, 't')
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const say = useCallback((x: ToastState) => setToast(x), [])
  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])
  const model = state.status === 'ready' ? state.data : null

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }
  if (!model) return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>

  return (
    <section className="dp-react-root">
      <OdontogramWorkbench pid={pid} model={model} replace={replace} fail={fail} say={say} initial={t} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
