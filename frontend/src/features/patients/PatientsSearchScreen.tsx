import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon, iconName } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import type { ApiResult } from '../../services/api'
import { NewPatientDialog } from './NewPatientDialog'
import { PatientPeek, type PeekState } from './PatientPeek'
import { PatientsTable } from './PatientsTable'
import {
  filtersFromParams, filtersToQuery, isDirty, patients, sameFilters,
  type Filters, type PatientsPage, type PatientsSummary,
} from './patients'

/* Подписи экрана — те же слова, что на старой странице «Pacienți». Числа
   карточек, подписи под ними, врачи и каналы фильтра, статусы — с сервера. */
const T = {
  title: 'Pacienți',
  sub: 'Gestionează și caută pacienții clinicii',
  search: 'Caută pacient, telefon, e-mail…',
  allDoctors: 'Toți medicii',
  noDoctor: '— fără medic —',
  allStatuses: 'Toate statusurile',
  allChannels: 'Toate canalele',
  anySold: 'Orice sold',
  debtOnly: 'Doar cu datorie',
  advanceOnly: 'Doar cu avans',
  find: 'Caută',
  reset: 'Resetează',
  resetTitle: 'Scoate toate filtrele',
  exportBtn: 'Exportă',
  exportTitle: 'Lista filtrată, ca registru Excel',
  add: '＋ Adaugă pacient',
  tiles: ['Total pacienți', 'Pacienți noi (luna aceasta)', 'Programări (luna aceasta)'],
  peekGone: 'Fișa nu mai există.',
  peekFail: 'Nu am putut încărca fișa.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Data {
  summary: PatientsSummary
  page: PatientsPage
}

interface Props {
  /** Отбор из адреса (data-params узла): q, med, st, ch, dat, sort, page, per. */
  params?: Record<string, string>
  navigate?: (url: string) => void
  /** Пауза после буквы в поиске, мс; в проверках — 0. */
  debounceMs?: number
}

export function PatientsSearchScreen({ params = {}, navigate = defaultNavigate, debounceMs = 250 }: Props) {
  const [filters, setFilters] = useState<Filters>(() => filtersFromParams(params))
  // отбор, с которым шла ПОСЛЕДНЯЯ загрузка (первая — вместе со сводкой)
  const loadedRef = useRef<Filters | null>(null)
  const filtersRef = useRef(filters)
  // эффект объявлен ДО useLoad: его загрузка читает свежий отбор при повторе
  useEffect(() => { filtersRef.current = filters }, [filters])

  const load = useCallback(async (signal: AbortSignal): Promise<ApiResult<Data>> => {
    const f = filtersRef.current
    const [s, p] = await Promise.all([patients.summary(signal), patients.page(f, signal)])
    loadedRef.current = { ...f, page: p.data.page }
    return { ...p, data: { summary: s.data, page: p.data } }
  }, [])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)

  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [peek, setPeek] = useState<PeekState | null>(null)
  const [adding, setAdding] = useState(false)
  const peekSeq = useRef(0)
  const flushRef = useRef<(() => void) | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])

  /* Адрес страницы повторяет отбор: перезагрузка и «варианта clasică»
     (?ui=legacy) открывают тот же список — имена параметров те же. */
  useEffect(() => {
    window.history.replaceState(null, '', `${window.location.pathname}${filtersToQuery(filters)}`)
  }, [filters])

  /* Смена отбора после первой загрузки: только страница списка, сводка
     остаётся. Буква в поиске ждёт паузу, выбор в фильтре идёт сразу. */
  const summary = state.status === 'ready' ? state.data.summary : null
  useEffect(() => {
    if (!summary || !loadedRef.current) return
    const prev = loadedRef.current
    if (sameFilters(prev, filters)) return
    const ctl = new AbortController()
    const run = async () => {
      flushRef.current = null
      loadedRef.current = filters
      setBusy(true)
      try {
        const r = await patients.page(filters, ctl.signal)
        if (ctl.signal.aborted) return
        // сервер мог схлопнуть страницу за пределом на последнюю
        loadedRef.current = { ...filters, page: r.data.page }
        replace({ summary, page: r.data })
        if (r.data.page !== filters.page) setFilters((f) => ({ ...f, page: r.data.page }))
      } catch (e) {
        if (!ctl.signal.aborted) fail(e)
      } finally {
        if (!ctl.signal.aborted) setBusy(false)
      }
    }
    const wait = filters.q !== prev.q ? debounceMs : 0
    const timer = window.setTimeout(() => { void run() }, wait)
    flushRef.current = () => { window.clearTimeout(timer); void run() }
    return () => {
      window.clearTimeout(timer)
      ctl.abort()
    }
  }, [filters, summary, debounceMs, replace, fail])

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') setPeek(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  async function openPeek(id: number) {
    const seq = ++peekSeq.current
    setPeek({ id, html: null, error: '' })
    try {
      const r = await patients.peek(id)
      if (seq !== peekSeq.current) return
      setPeek({ id, html: r.data.html, error: '' })
    } catch (e) {
      if (seq !== peekSeq.current) return
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      const gone = err.failure.kind === 'server' && err.failure.status === 404
      setPeek({ id, html: null, error: gone ? T.peekGone : T.peekFail })
    }
  }

  function set(next: Partial<Filters>) {
    setFilters((f) => ({ ...f, ...next, page: next.page ?? 1 }))
  }

  function onSearch(e: FormEvent) {
    e.preventDefault()
    flushRef.current?.()
  }

  if (state.status === 'leaving') return null

  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }

  const data = state.status === 'ready' ? state.data : null
  const dirty = isDirty(filters) || filters.sort !== 'last' || filters.per !== 20
  const exportUrl = `/admin/patients.xlsx${filtersToQuery(filters, false)}`

  return (
    <section className="dp-react-root" aria-busy={data === null || busy}>
      {toast && <Toast {...toast} onClose={closeToast} />}
      <div className="pl-head">
        <div>
          <h2>{T.title}</h2>
          <p>{T.sub}</p>
        </div>
      </div>
      <form className="pl-bar" onSubmit={onSearch}>
        <label className="pl-search">
          <Icon name="search" />
          <input
            name="q"
            value={filters.q}
            onChange={(e) => set({ q: e.target.value.slice(0, 60) })}
            placeholder={T.search}
            aria-label={T.search}
          />
        </label>
        <select aria-label={T.allDoctors} value={filters.med} onChange={(e) => set({ med: e.target.value })}>
          <option value="">{T.allDoctors}</option>
          <option value="-">{T.noDoctor}</option>
          {(data?.summary.doctors ?? []).map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <select aria-label={T.allStatuses} value={filters.st} onChange={(e) => set({ st: e.target.value })}>
          <option value="">{T.allStatuses}</option>
          {(data?.summary.statuses ?? []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        <select aria-label={T.allChannels} value={filters.ch} onChange={(e) => set({ ch: e.target.value })}>
          <option value="">{T.allChannels}</option>
          {(data?.summary.channels ?? []).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <select aria-label={T.anySold} value={filters.dat} onChange={(e) => set({ dat: e.target.value })}>
          <option value="">{T.anySold}</option>
          <option value="da">{T.debtOnly}</option>
          <option value="avans">{T.advanceOnly}</option>
        </select>
        <button className="pl-btn">{T.find}</button>
        {dirty && (
          <a
            className="pl-btn"
            href={window.location.pathname}
            title={T.resetTitle}
            onClick={(e) => { e.preventDefault(); setFilters(filtersFromParams({})) }}
          >
            <Icon name="close" /> {T.reset}
          </a>
        )}
        <span style={{ flex: 1 }}></span>
        <a className="pl-btn" href={exportUrl} title={T.exportTitle}>
          <Icon name="download" /> {T.exportBtn}
        </a>
        <button type="button" className="pl-btn primary" onClick={() => setAdding(true)}>
          {T.add}
        </button>
      </form>
      {data && (
        <div className="pl-tiles">
          {data.summary.tiles.map((t, i) => {
            const inner = (
              <>
                <span className={`ico ${t.tone}`}><Icon name={iconName(t.icon)} /></span>
                <div className="pl-tv">
                  <span>{T.tiles[i] ?? ''}</span>
                  <b>{t.value}</b>
                  <small dangerouslySetInnerHTML={{ __html: t.foot }} />
                </div>
              </>
            )
            return t.href
              ? <a key={i} className="pl-tile" href={t.href}>{inner}</a>
              : <div key={i} className="pl-tile">{inner}</div>
          })}
        </div>
      )}
      <div className="pl-grid">
        <div className="pl-card">
          {data && (
            <PatientsTable
              page={data.page}
              summary={data.summary}
              filters={filters}
              selected={peek?.id ?? null}
              onFilters={setFilters}
              onPeek={(id) => { void openPeek(id) }}
              onAdd={() => setAdding(true)}
            />
          )}
        </div>
        <PatientPeek peek={peek} onClose={() => setPeek(null)} />
      </div>
      <NewPatientDialog
        open={adding}
        doctors={data?.summary.clinic_doctors ?? []}
        onClose={() => setAdding(false)}
        navigate={navigate}
        leaveIfSignedOut={leaveIfSignedOut}
      />
    </section>
  )
}
