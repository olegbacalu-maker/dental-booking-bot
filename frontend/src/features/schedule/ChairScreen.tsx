import { useCallback, useEffect, useRef, useState } from 'react'
import { AppLink, useAppNavigate } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { OdontogramTab } from '../clinical/OdontogramTab'
import { chair, type ChairData, type ChairItem } from './chair'
import type { StatusAction } from './day'

/* Экран «у кресла» (docs/dentpilot-2/chair-mode.md). Олег 26.09: планшет
   врача над креслом — «он включил программу и быстро записал данные по
   одонтограмме». Поэтому порядок экрана — порядок работы у кресла: кто
   сидит, его зубы сразу, дальше очередь. Кто в кресле, решает СЕРВЕР
   (`schedule/chair.py`); экран только рисует ответ и шлёт исходы визита.

   ⭐ Регистратура переводит пациента «în cabinet» на панели — планшет видит
   это опросом (POLL_MS): свежий ответ подменяет данные через `replace`, без
   кадра загрузки, и только если что-то изменилось — одинаковый ответ экран
   не перерисовывает (мигание на каждый опрос уже лечили в журнале 08-20).
   Одонтограмма — общий рабочий стол фиши (`OdontogramTab`, B6/B7): под палец
   его делает B7, экран кресла встраивает как есть. */
const T = {
  pick: 'Al cui cabinet? Alegeți medicul.',
  doctor: 'Medicul',
  now: 'În cabinet acum',
  empty: 'Nimeni în cabinet. Când pacientul intră, atingeți «În cabinet» în lista de mai jos.',
  queue: 'Azi urmează',
  queueEmpty: 'Nimeni nu mai așteaptă azi.',
  stale: 'Nefinalizat:',
  card: 'Fișa pacientului',
  visit: 'Fișa vizitei',
  noPatient: 'Programare fără fișă de pacient — formula dentară nu are unde se scrie.',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

/** Опрос кресла. Регистратура перевела пациента — планшет видит за ≤15 с. */
export const POLL_MS = 15000

export const loadChair: RouteLoad<ChairData> = (signal, _params, search) =>
  chair.get(search.get('doctor') ?? '', signal)

interface Props {
  navigate?: (url: string) => void
}

const noop = () => {}

export function ChairScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<ChairData>(navigate)
  const go = useAppNavigate(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])
  const data = state.status === 'ready' ? state.data : null
  const dk = data?.doctor?.dk ?? ''
  /* Отпечаток показанного: опрос с тем же ответом не трогает экран. */
  const shown = useRef('')
  useEffect(() => { if (data) shown.current = JSON.stringify(data) }, [data])

  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])

  const refresh = useCallback(async () => {
    try {
      const r = await chair.get(dk)
      const next = JSON.stringify(r.data)
      if (next !== shown.current) {
        shown.current = next
        replace(r.data)
      }
    } catch (e) {
      // опрос молчит о сети: плашка каждые 15 с про уснувший сервер — шум;
      // уход на вход при 401 — не шум
      leaveIfSignedOut(asApiError(e))
    }
  }, [dk, replace, leaveIfSignedOut])

  useEffect(() => {
    if (!dk) return undefined
    const t = window.setInterval(() => { void refresh() }, POLL_MS)
    return () => window.clearInterval(t)
  }, [dk, refresh])

  async function act(item: ChairItem, a: StatusAction) {
    if (a.confirm && !window.confirm(a.confirm)) return
    setBusy(true)
    try {
      await chair.status(item.id, a.to)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const buttons = (item: ChairItem, only?: (a: StatusAction) => boolean) =>
    (data?.actions[item.status] ?? []).filter(only ?? (() => true)).map((a) => (
      <button key={a.to} type="button" className={`bstat ${a.cls}`} disabled={busy}
        onClick={() => { void act(item, a) }}>{a.label}</button>
    ))

  if (state.status === 'leaving') return null
  /* Заголовок экрана — у оболочки («Programări», подпись «cabinet»): второй
     заголовок здесь съедал высоту, и в альбомной ориентации дуга уезжала
     к нижнему краю (стенд tablet_shots, 26.09). */

  if (state.status === 'failed') {
    return (
      <section className="dp-react-root chair">
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }
  if (!data) return <section className="dp-react-root chair" aria-busy="true" />

  if (!data.doctor) {
    return (
      <section className="dp-react-root chair">
        <p>{T.pick}</p>
        <div className="chair-docs">
          {data.doctors.map((d) => (
            <AppLink key={d.dk} className="pl-btn" href={`/admin/cabinet?doctor=${d.dk}`}>
              <Icon name="user" /> {d.name}
            </AppLink>
          ))}
        </div>
      </section>
    )
  }

  const c = data.chair
  return (
    <section className="dp-react-root chair">
      <div className="chair-head">
        {data.doctors.length > 1 && (
          <label>
            {T.doctor}{' '}
            <select value={dk} onChange={(e) => go(`/admin/cabinet?doctor=${e.target.value}`)}>
              {data.doctors.map((d) => <option key={d.dk} value={d.dk}>{d.name}</option>)}
            </select>
          </label>
        )}
      </div>

      {c ? (
        <div className="chair-now">
          <div className="chair-lbl">{T.now}</div>
          <div className="who">{c.name}</div>
          <div className="what">{c.time} · {c.service}</div>
          <div className="chair-acts">
            {c.patient_id !== null && (
              <AppLink className="pl-btn" href={`/admin/patient/${c.patient_id}`}>
                <Icon name="user" /> {T.card}
              </AppLink>
            )}
            <AppLink className="pl-btn" href={`/admin/visit/${c.id}`}>
              <Icon name="note" /> {T.visit}
            </AppLink>
            {/* ⛔ Только «Finalizat»: отмена визита — дело регистратуры, а
                большая «Anulează» под пальцем у кресла — случайная отмена. */}
            {buttons(c, (a) => a.to === 'done')}
          </div>
        </div>
      ) : (
        <p className="chair-empty">{T.empty}</p>
      )}

      {data.stale.map((s) => (
        <div key={s.id} className="chair-stale">
          <span>{T.stale} <b>{s.time} {s.name}</b></span>
          {buttons(s, (a) => a.to === 'done')}
        </div>
      ))}

      {c && (c.patient_id !== null ? (
        <OdontogramTab key={c.patient_id} pid={c.patient_id} views={false}
          say={setToast} onFail={fail} onChanged={noop} />
      ) : <p className="hint">{T.noPatient}</p>)}

      <h3 className="chair-qh">{T.queue}</h3>
      {data.queue.length === 0 ? <p className="hint">{T.queueEmpty}</p> : (
        <ul className="chair-queue">
          {data.queue.map((q) => (
            <li key={q.id}>
              <span className="t">{q.time}</span>
              <span className="n"><b>{q.name}</b> · {q.service}</span>
              <span className={`pl-badge ${q.badge.cls}`}>{q.badge.label}</span>
              {buttons(q, (a) => a.to === 'arrived')}
            </li>
          ))}
        </ul>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
