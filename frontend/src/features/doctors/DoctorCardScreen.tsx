import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Avatar } from '../../components/Avatar'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { DoctorGoogle } from './DoctorGoogle'
import { DoctorPhoto } from './DoctorPhoto'
import { DoctorProfileForm } from './DoctorProfileForm'
import { DoctorServices } from './DoctorServices'
import { DoctorWeek } from './DoctorWeek'
import { doctors, type DoctorCard, type ServiceRow } from './doctors'
import { gdoc, viewOf, type GdocReply, type GdocView } from './gdoc'

/* Подписи фиши — слова старой страницы; предупреждение об услугах, подписи
   состояний и все числа приходят с сервера. */
const T = {
  all: 'Toți medicii',
  day: 'Ziua medicului',
  panel: 'Panou',
  contact: 'Date de contact și program',
  hintA: 'Programul «—» = ca al clinicii. Culoarea se folosește în calendarul zilei. ',
  hintB: 'Arhivarea e posibilă doar fără programări viitoare (acum: ',
  services: 'Servicii pe care le face',
  servicesHint:
    'Serviciul fără bife explicite se oferă la toți medicii activi. Dacă scoateți bifa ' +
    'de la un astfel de serviciu, lista lui devine explicită — un medic nou va trebui bifat manual.',
  last30: 'Ultimele 30 de zile',
  rows: { n: 'Programări', pct: 'Ocupare', noshow: 'Neprezentări', future: 'Programări viitoare' },
  statsLink: 'Statistica întregii clinici',
  notFound: 'Medicul nu există sau a fost șters din profilul clinicii.',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

/** Пока браузер Windows не вернулся со входа врача: окно программы о нём само не узнаёт. */
const WAIT_MS = 3000

interface Props {
  dk: string
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadDoctorCard: RouteLoad<DoctorCard> = (signal, params) => doctors.card(params.dk ?? '', signal)

export function DoctorCardScreen({ dk, navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<DoctorCard>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])
  const [gBusy, setGBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  /* Блок Google живёт внутри модели карточки: ответ команды и опрос подменяют только его, а формы
     карточки читают модель один раз при монтировании и правок не теряют. */
  const card0 = state.status === 'ready' ? state.data : null
  const latest = useRef(card0)
  useLayoutEffect(() => { latest.current = card0 })
  const putView = useCallback((v: GdocView | null) => {
    const c = latest.current
    if (c) replace({ ...c, google: v })
  }, [replace])
  /* номер команды: опрос, начатый до неё, не перепишет её ответ прежним видом */
  const turn = useRef(0)
  const waiting = !!card0?.google?.waiting

  const reread = useCallback(async () => {
    const mine = turn.current
    try {
      const r = await gdoc.view(dk)
      if (turn.current === mine) putView(r.data ?? null)
    } catch (e) {
      leaveIfSignedOut(asApiError(e))
    }
  }, [dk, leaveIfSignedOut, putView])

  useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(() => { void reread() }, WAIT_MS)
    /* вернулись в окно — вход в браузере мог закончиться */
    const back = () => { if (!document.hidden) void reread() }
    window.addEventListener('focus', back)
    document.addEventListener('visibilitychange', back)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', back)
      document.removeEventListener('visibilitychange', back)
    }
  }, [waiting, reread])

  const fail = useCallback(
    (e: unknown) => {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    },
    [leaveIfSignedOut],
  )
  const said = useCallback((r: ApiResult<unknown>) => setToast({ tone: r.tone, text: r.text }), [])

  /**
   * Исход визита из списка сегодняшнего дня (C14+).
   *
   * ⭐ Команда состояния НЕ возвращает: у фиши врача своя модель, и день
   * журнала ей не подходит. Поэтому после удачи экран перечитывает СЕБЯ —
   * и заодно видит, что за это время сделали со второго рабочего места.
   * ⚠️ Удача здесь МОЛЧАЛИВА: у смены статуса нет кода сообщения ни на
   * одной странице, и ответ человеку — сама изменившаяся строка.
   */
  const onStatus = useCallback((id: number, to: string) => {
    setBusy(true)
    doctors.status(id, to).then(
      (r) => {
        if (r.text) said(r)
        setBusy(false)
        retry()
      },
      (e: unknown) => {
        setBusy(false)
        fail(e)
      },
    )
  }, [fail, retry, said])

  /* Команда блока: вид после неё — и в ответе-отказе (409), там сервер кладёт его тоже. */
  const gRun = useCallback(async (call: () => Promise<ApiResult<GdocReply>>) => {
    turn.current += 1
    setGBusy(true)
    try {
      const r = await call()
      putView(r.data.view ?? null)
      if (r.text) setToast({ tone: r.tone, text: r.text })
      return r
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return null
      const v = viewOf('data' in err.failure ? err.failure.data : undefined)
      if (v !== undefined) putView(v)
      setToast({ tone: 'err', text: err.text || T.offline })
      return null
    } finally {
      setGBusy(false)
    }
  }, [leaveIfSignedOut, putView])

  if (state.status === 'leaving') return null

  const nav = (
    <div className="nav">
      <AppLink href="/admin/medici"><Icon name="med" /> {T.all}</AppLink>
      <AppLink href={`/admin/doctor/${encodeURIComponent(dk)}`}><Icon name="cal" /> {T.day}</AppLink>
      <AppLink href="/admin"><Icon name="home" /> {T.panel}</AppLink>
    </div>
  )

  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        {nav}
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }

  if (state.status === 'loading') {
    return (
      <section className="dp-react-root" aria-busy="true">
        {nav}
        <div className="fisa med"><div className="fcol-l"><div className="fcard" /></div></div>
      </section>
    )
  }

  const card = state.data
  const onPhoto = (photo: string, r: ApiResult<unknown>) => {
    replace({ ...card, photo })
    said(r)
  }
  const onServices = (services: ServiceRow[], r: ApiResult<unknown>) => {
    replace({ ...card, services })
    said(r)
  }
  const onSaved = (r: ApiResult<DoctorCard>) => {
    replace(r.data)
    said(r)
  }
  const g = card.google ?? null
  async function connect() {
    const r = await gRun(() => gdoc.connect(dk))
    // новым окном: оболочка отдаёт чужой адрес браузеру Windows, окно программы остаётся
    if (r?.data.url) window.open(r.data.url, '_blank', 'noopener')
  }
  async function checkNow() {
    setChecking(true)
    await gRun(() => gdoc.check(dk))
    setChecking(false)
  }
  async function disconnect() {
    if (!g || !await ask({ text: g.words.disconnect_ask, ok: g.words.disconnect, danger: true })) return
    await gRun(() => gdoc.disconnect(dk))
  }

  return (
    <section className="dp-react-root">
      {nav}
      {card.warning && <div className="banner err">{card.warning}</div>}
      <div className="fisa med">
        <div className="fcol-l">
          <div className="fcard">
            <div className="fhead">
              <Avatar color={card.color} initials={card.initials} photo={card.photo} big />
              <div style={{ minWidth: 0 }}>
                <b>{card.name}</b>
                <small>{card.spec || '—'}</small>
                <span className={`dbadge ${card.status}`} style={{ display: 'inline-block', marginTop: 6 }}>
                  {card.states[card.status]?.label ?? card.status}
                </span>
              </div>
            </div>
            <DoctorPhoto dk={dk} photo={card.photo} maxMb={card.max_photo_mb} onDone={onPhoto} onFail={fail} />
          </div>
          {g ? (
            /* ключ — состояние: новое проявляется заново, а смена строк опросом — на месте */
            <DoctorGoogle key={`${g.state}${g.waiting ? '.w' : ''}`} g={g} busy={gBusy} checking={checking}
              onConnect={() => { void connect() }}
              onCancel={() => { void gRun(() => gdoc.cancel(dk)) }}
              onCheck={() => { void checkNow() }}
              onDisconnect={() => { void disconnect() }} />
          ) : null}
          <div className="fcard">
            <h3>{T.contact}</h3>
            <DoctorProfileForm card={card} onSaved={onSaved} onFail={fail} />
            <p className="hint" style={{ margin: '8px 0 0' }}>
              {T.hintA}{T.hintB}<b>{card.future}</b>).
            </p>
          </div>
        </div>
        <div className="fcol-c">
          <DoctorWeek dk={dk} week={card.week} today={card.today}
            actions={card.actions} noteActions={card.note_actions}
            busy={busy} onStatus={onStatus} />
        </div>
        <div className="fcol-r">
          <div className="fcard">
            <h3>{T.services}</h3>
            <DoctorServices
              key={card.services.map((s) => `${s.id}:${s.checked ? 1 : 0}`).join(',')}
              dk={dk}
              services={card.services}
              onSaved={onServices}
              onFail={fail}
            />
            <p className="hint" style={{ margin: '8px 0 0' }}>{T.servicesHint}</p>
          </div>
          <div className="fcard">
            <h3>{T.last30}</h3>
            <div className="frow"><span>{T.rows.n}</span><span className="v">{card.stats.n}</span></div>
            <div className="frow"><span>{T.rows.pct}</span><span className="v">{card.stats.pct}%</span></div>
            <div className="frow"><span>{T.rows.noshow}</span><span className="v">{card.stats.noshow}</span></div>
            <div className="frow"><span>{T.rows.future}</span><span className="v">{card.future}</span></div>
            <p className="hint" style={{ margin: '8px 0 0' }}>
              <AppLink href="/admin/stats">{T.statsLink} <Icon name="out" /></AppLink>
            </p>
          </div>
        </div>
      </div>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
