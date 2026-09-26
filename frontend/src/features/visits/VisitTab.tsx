import { useCallback, useEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import type { ToastState } from '../../components/Toast'
import { asApiError } from '../../services/api'
import type { ApiError } from '../../types/api'
import { VisitWorkbench } from './VisitWorkbench'
import { visits, type VisitForm, type VisitPage } from './visits'

/* Дневник визита во вкладке Vizite фиши (B6, шаг 4): тот же дневник, что на
   странице (`VisitWorkbench`); визит — АДРЕСОМ фиши (`?tab=vizite&visit=`), и
   загрузчик фиши его не носит (полный GET фиши = «Fișa deschisă» в журнале
   доступа) — вкладка грузит дневник сама по номеру визита. `?back=` серверу —
   адрес этой вкладки: страница «Pe tot ecranul» вернётся сюда, а форма шлёт
   эхо сервера `page.back`, как и страница. Пока едет ДРУГОЙ визит, прежняя
   форма снята: правили бы запись, которую уже покинули. */
const T = {
  back: 'Vizite',
  full: 'Pe tot ecranul',
  notFound: 'Vizita nu există sau este o notă fără pacient.',
} as const

interface Props {
  pid: number
  aid: number
  /** закрыть дневник — вкладка Vizite без визита в адресе */
  onClose: () => void
  say: (t: ToastState) => void
  onFail: (e: unknown) => void
}

export function VisitTab({ pid, aid, onClose, say, onFail }: Props) {
  const back = `/admin/patient/${pid}?tab=vizite`
  const [got, setGot] = useState<{ aid: number; page: VisitPage | null; error: ApiError | null } | null>(null)
  const [saving, setSaving] = useState(false)
  const [tick, setTick] = useState(0)
  const mine = got && got.aid === aid ? got : null
  /* отказ — через ref: личность `onFail` меняется вслед за адресом, запрос от неё не зависит */
  const onFailRef = useRef(onFail)
  useEffect(() => { onFailRef.current = onFail }, [onFail])

  useEffect(() => {
    const ctl = new AbortController()
    visits.get(aid, back, ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setGot({ aid, page: r.data, error: null }) },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        const ae = asApiError(e)
        setGot({ aid, page: null, error: ae })
        onFailRef.current(ae)
      },
    )
    return () => ctl.abort()
  }, [aid, back, tick])

  const onSave = useCallback(async (form: VisitForm) => {
    setSaving(true)
    try {
      const r = await visits.save(aid, form)
      setGot({ aid, page: r.data, error: null })
      if (r.text) say({ tone: r.tone, text: r.text })
    } catch (e) {
      onFailRef.current(asApiError(e))
    } finally {
      setSaving(false)
    }
  }, [aid, say])

  const nav = (
    <p className="dp-vnav">
      <button type="button" onClick={onClose}><Icon name="chev-l" /> {T.back}</button>
      {' '}&nbsp;·&nbsp;{' '}
      <AppLink href={`/admin/visit/${aid}?back=${encodeURIComponent(back)}`}><Icon name="eye" /> {T.full}</AppLink>
    </p>
  )
  if (mine?.error) {
    const notFound = mine.error.failure.kind === 'server' && mine.error.failure.status === 404
    return <>{nav}<LoadFailed error={mine.error} onRetry={() => setTick((n) => n + 1)} {...(notFound ? { text: T.notFound } : {})} /></>
  }
  if (!mine?.page) return <>{nav}<div className="vwrap" aria-busy="true"><div className="fcard" /></div></>
  return (
    <div aria-busy={saving || undefined}>
      {nav}
      <VisitWorkbench page={mine.page} saving={saving} onSave={onSave} embedded />
    </div>
  )
}
