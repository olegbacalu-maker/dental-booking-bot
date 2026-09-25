import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { Icon, iconName } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import {
  queryParam, searchChangeKeepsData, useRouteLoad, type RouteLoad, type ScreenData,
} from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { NewPatientDialog } from './NewPatientDialog'
import { PatientPeek, type PeekState } from './PatientPeek'
import { PatientsTable } from './PatientsTable'
import {
  DEFAULT_FILTERS, filtersFromParams, filtersToQuery, isDirty, patients, sameFilters,
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
  /** Отбор, на который ОТВЕЧАЕТ `page` (номер страницы — как его поправил сервер). */
  filters: Filters
}

interface Props {
  navigate?: (url: string) => void
  /** Пауза после буквы в поиске, мс; в проверках — 0. */
  debounceMs?: number
}

const KEYS = ['q', 'med', 'st', 'ch', 'dat', 'sort', 'page', 'per'] as const

/**
 * Отбор из АДРЕСА — правилом страницы сервера: повтор ключа — последний,
 * `q` обрезан. ⛔ Адрес — единственный владелец отбора (B2.3): своей копии у
 * экрана нет, иначе после перехода она разошлась бы с адресом.
 */
export function filtersOf(q: URLSearchParams): Filters {
  const p: Record<string, string> = Object.fromEntries(KEYS.map((k) => [k, queryParam(q, k)]))
  return filtersFromParams({ ...p, q: (p.q ?? '').trim().slice(0, 60) })
}

const loadPatients: RouteLoad<Data> = async (signal, _p, q) => {
  const f = filtersOf(q)
  // ⭐ Оба запроса РАЗОМ, и загрузчик ждёт оба: экран без сводки не рисуется
  const [s, p] = await Promise.all([patients.summary(signal), patients.page(f, signal)])
  return { ...p, data: { summary: s.data, page: p.data, filters: { ...f, page: p.data.page } } }
}

/**
 * Данные грузит роутер (B2.2) на открытии, F5 и повторе — сводку и список.
 * ⭐ Смена ОТБОРА (одного query) загрузчик НЕ перезапускает: сводка — «один
 * раз на открытие экрана» (`/api/patients/summary`), а список по новому
 * отбору экран дочитывает сам — как и до роутера.
 */
export const loadPatientsSearch: ScreenData = { load: loadPatients, shouldRevalidate: searchChangeKeepsData }

export function PatientsSearchScreen({ navigate = defaultNavigate, debounceMs = 250 }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<Data>(navigate)
  const [params] = useSearchParams()
  const filters = useMemo(() => filtersOf(params), [params])
  const { pathname } = useLocation()
  const to = useNavigate()
  /* Набранное в поиске, но ещё не ушедшее в адрес (ждёт паузу). Это черновик
     ПОЛЯ, а не отбор: отбор — в адресе. `null` — черновика нет. */
  const [draft, setDraft] = useState<string | null>(null)
  const typed = draft === null ? null : draft.trim().slice(0, 60)
  /* Отказ дочитки: чтобы «занято» не висело после ошибки. */
  const [failedFor, setFailedFor] = useState<string | null>(null)

  const [toast, setToast] = useState<ToastState | null>(null)
  const [peek, setPeek] = useState<PeekState | null>(null)
  const [adding, setAdding] = useState(false)
  const peekSeq = useRef(0)
  const closeToast = useCallback(() => setToast(null), [])

  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])

  /* Отбор уходит в адрес РОУТЕРОМ: F5 и «varianta clasică» (?ui=legacy)
     открывают тот же список — имена параметров те же. `replace`, как и было:
     буквы и фильтры не копят шагов «Назад»; query — заново (без ?msg=). */
  const go = useCallback((f: Filters) => {
    void to(`${pathname}${filtersToQuery(f)}`, { replace: true })
  }, [to, pathname])

  /* Новая фиша открывается ПЕРЕХОДОМ по адресу сервера (B4), а не документом:
     плашку «Pacient adăugat» несёт `?msg=` в адресе, её рисует оболочка. */
  const openCreated = useCallback((url: string) => { void to(url) }, [to])

  /* Любой переход несёт и набранное, но не ушедшее: щелчок по сортировке за
     миг до паузы не должен терять буквы. Явная смена q (сброс в таблице) —
     главнее набранного. */
  const commit = useCallback((next: Filters) => {
    if (next.q !== filters.q) {
      setDraft(null)
      go(next)
      return
    }
    go(typed === null ? next : { ...next, q: typed })
  }, [filters.q, typed, go])

  /* Буква ждёт паузу, потом — в адрес; выбор в фильтре идёт сразу (commit). */
  useEffect(() => {
    if (typed === null || typed === filters.q) return
    const timer = window.setTimeout(() => go({ ...filters, q: typed, page: 1 }), debounceMs)
    return () => window.clearTimeout(timer)
  }, [typed, filters, debounceMs, go])

  /* Адрес сменился, а список на экране отвечает прежнему отбору — дочитать
     ТОЛЬКО страницу списка; сводка остаётся. Прошлый запрос отменяется. */
  const data = state.status === 'ready' ? state.data : null
  const key = filtersToQuery(filters)
  useEffect(() => {
    if (!data || sameFilters(data.filters, filters)) return
    const ctl = new AbortController()
    patients.page(filters, ctl.signal).then((r) => {
      if (ctl.signal.aborted) return
      if (r.data.page !== filters.page) {
        // сервер схлопнул страницу за пределом на последнюю — адрес за ним,
        // а список дочитается уже по поправленному адресу
        go({ ...filters, page: r.data.page })
        return
      }
      replace({ summary: data.summary, page: r.data, filters })
    }, (e: unknown) => {
      if (ctl.signal.aborted) return
      setFailedFor(key)
      fail(e)
    })
    return () => ctl.abort()
  }, [data, filters, key, replace, fail, go])
  const busy = data !== null && !sameFilters(data.filters, filters) && failedFor !== key

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
    commit({ ...filters, ...next, page: next.page ?? 1 })
  }

  function onSearch(e: FormEvent) {
    e.preventDefault()
    if (typed !== null && typed !== filters.q) go({ ...filters, q: typed, page: 1 })
  }

  if (state.status === 'leaving') return null

  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }

  // Что видит человек: отбор адреса плюс набранное в поле
  const cur = typed === null ? filters : { ...filters, q: typed }
  const dirty = isDirty(cur) || cur.sort !== 'last' || cur.per !== 20
  const exportUrl = `/admin/patients.xlsx${filtersToQuery(cur, false)}`

  return (
    <section className="dp-react-root" aria-busy={data === null || busy}>
      {toast && <Toast {...toast} onClose={closeToast} />}
      {/* ⭐ Фильтры — ПЕРВЫЙ `.nav` узла React: сетка `.content` кладёт его в ряд
          с заголовком, как шапку дня на панели (Олег 25.09: «наверху теряем
          место»). Своего заголовка «Pacienți» у экрана больше нет — раздел
          называют сайдбар и подпись оболочки, а строка h2 стоила 60 px. */}
      <form className="nav pl-bar" aria-label={T.title} onSubmit={onSearch}>
        <label className="pl-search">
          <Icon name="search" />
          <input
            name="q"
            value={draft ?? filters.q}
            onChange={(e) => setDraft(e.target.value.slice(0, 60))}
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
          <AppLink
            className="pl-btn"
            href={pathname}
            title={T.resetTitle}
            onClick={(e) => { e.preventDefault(); setDraft(null); go(DEFAULT_FILTERS) }}
          >
            <Icon name="close" /> {T.reset}
          </AppLink>
        )}
        {/* две правые кнопки — одной группой: в ряду с заголовком бар переносится,
            и группа уходит на вторую строку целиком, к правому краю */}
        <span className="pl-end">
          <AppLink className="pl-btn" href={exportUrl} title={T.exportTitle}>
            <Icon name="download" /> {T.exportBtn}
          </AppLink>
          <button type="button" className="pl-btn primary" onClick={() => setAdding(true)}>
            {T.add}
          </button>
        </span>
      </form>
      <div className="pl-grid">
        {/* ⭐ Плитки — в правую колонку ПОД предпросмотр (шире 1400px), таблица
            начинается выше; в разметке они первыми, чтобы на узком окне, где
            колонка одна и предпросмотр — ящик, остаться НАД таблицей, как были. */}
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
                ? <AppLink key={i} className="pl-tile" href={t.href}>{inner}</AppLink>
                : <div key={i} className="pl-tile">{inner}</div>
            })}
          </div>
        )}
        <div className="pl-card">
          {data && (
            <PatientsTable
              page={data.page}
              summary={data.summary}
              filters={filters}
              selected={peek?.id ?? null}
              onFilters={commit}
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
        navigate={openCreated}
        leaveIfSignedOut={leaveIfSignedOut}
      />
    </section>
  )
}
