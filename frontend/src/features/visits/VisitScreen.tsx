import { useCallback, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { VisitWorkbench } from './VisitWorkbench'
import { visits, type VisitForm, type VisitPage } from './visits'

/* Дневник визита (C19) как страница — из журнала, с «Înapoi» по `?back=`.
   Сам дневник (шапка визита, графы, шаблоны, позиции плана) — в
   `VisitWorkbench`, он же стоит во вкладке Vizite фиши (B6, шаг 4). Здесь —
   загрузка, ожидание при переходе на другой визит, запись и плашки. */
const T = {
  back: 'Înapoi',
  card: 'Fișa pacientului',
  notFound: 'Vizita nu există sau este o notă fără pacient.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  /** Номер визита — параметр пути `appt_id`, его разбирает роутер. */
  aid: number
  navigate?: (url: string) => void
}

/**
 * Данные грузит роутер (B2.3): номер — из пути, «Înapoi» — `?back=` ТЕКУЩЕГО
 * адреса, и больше ниоткуда (не из узла: тот описывает документ). Значение
 * уходит серверу как есть, а экран показывает и шлёт ТОЛЬКО эхо сервера
 * `page.back`: проверяет адрес возврата один `_visit_back`, и чужой
 * `?back=http://…` не станет живой ссылкой. Сам экран адрес не пишет.
 */
export const loadVisit: RouteLoad<VisitPage> = (signal, p, q) =>
  visits.get(Number(p.appt_id), queryParam(q, 'back'), signal)

export function VisitScreen({ aid, navigate = defaultNavigate }: Props) {
  const { state, pending, retry, replace, leaveIfSignedOut } = useRouteLoad<VisitPage>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [saving, setSaving] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])

  if (state.status === 'leaving') return null

  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }

  /* ⚠️ Переход роутером на другой визит: пока ответа нет, форма НЕ
     показывается — иначе правили бы запись, которую уже покидают. То же
     ожидание, что и при открытии визита. */
  if (state.status === 'loading' || pending) {
    return <section className="dp-react-root" aria-busy="true"><div className="vwrap"><div className="fcard" /></div></section>
  }

  const page = state.data
  const onSave = async (form: VisitForm) => {
    setSaving(true)
    try {
      const r = await visits.save(aid, form)
      replace(r.data)
      if (r.text) setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      const ae = asApiError(err)
      if (!leaveIfSignedOut(ae)) setToast({ tone: 'err', text: ae.text || T.offline })
    } finally {
      setSaving(false)
    }
  }
  const a = page.appt

  return (
    <section className="dp-react-root" aria-busy={saving || undefined}>
      <p className="dp-vnav">
        <AppLink href={page.back}><Icon name="chev-l" /> {T.back}</AppLink>
        {' '}&nbsp;·&nbsp;{' '}
        <AppLink href={`/admin/patient/${a.patient_id}`}><Icon name="id" /> {T.card}</AppLink>
      </p>
      <VisitWorkbench page={page} saving={saving} onSave={onSave} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
