import { useCallback, useEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError, loginUrl } from '../../services/api'
import { roCount } from '../../utils/plural'
import { AddDialog } from '../schedule/AddDialog'
import { day, type DayForm, type NewAppt } from '../schedule/day'
import {
  dayTitle, gcalApi, minutesOf, presetOf, shortWhen, spanOf,
  type GcalFilter, type GcalList, type GcalLoad, type GcalRow,
} from './gcal'

/* Вкладка «Google Calendar»: события общего календаря клиники списком и
   перенос в журнал обычным окном записи. Правила, слова фильтров, причин и
   отказов — сервера; экран держит только отбор, поиск и окна.
   Список после каждой команды приходит в её ответе — второго запроса нет. */
const T = {
  title: 'Evenimentele din Google Calendar',
  lead: 'Încărcați calendarul clinicii și mutați programările în jurnal, una câte una, cu fereastra obișnuită de programare.',
  how: 'Cum obțin fișierul',
  pick: 'Alege fișierul (.ics sau .zip)',
  again: 'Încarcă din nou',
  reading: 'Se citește fișierul…',
  limit: 'Fișier .ics sau .zip, cel mult {n} MB. Se păstrează doar evenimentele viitoare, până la 12 luni.',
  src: 'Fișier .ics',
  cal: 'calendarul',
  loadedAt: 'încărcat',
  by: 'de',
  loadTitle: 'Fișierul a fost citit',
  taken: 'Primite',
  left: 'Lăsate deoparte',
  nNew: { one: '{n} eveniment nou', few: '{n} evenimente noi', many: '{n} de evenimente noi' },
  nUpdated: { one: '{n} actualizat', few: '{n} actualizate', many: '{n} actualizate' },
  nSame: { one: '{n} neschimbat', few: '{n} neschimbate', many: '{n} neschimbate' },
  nPast: { one: '{n} trecut', few: '{n} trecute', many: '{n} trecute' },
  nAllDay: { one: '{n} pe toată ziua', few: '{n} pe toată ziua', many: '{n} pe toată ziua' },
  nCancelled: { one: '{n} anulat în Google', few: '{n} anulate în Google', many: '{n} anulate în Google' },
  nBeyond: { one: '{n} peste 12 luni', few: '{n} peste 12 luni', many: '{n} peste 12 luni' },
  nUnparsed: { one: '{n} nerecunoscut', few: '{n} nerecunoscute', many: '{n} nerecunoscute' },
  nGone: { one: '{n} dispărut din calendar', few: '{n} dispărute din calendar', many: '{n} dispărute din calendar' },
  nChanged: { one: '{n} mutat deja s-a schimbat în Google', few: '{n} mutate deja s-au schimbat în Google',
    many: '{n} mutate deja s-au schimbat în Google' },
  nothing: 'nimic',
  refused: 'Calendar necitit',
  search: 'Caută în evenimente',
  total: { one: '{n} eveniment', few: '{n} evenimente', many: '{n} de evenimente' },
  empty: '— niciun eveniment aici —',
  emptyNew: 'Toate evenimentele au fost mutate sau lăsate deoparte.',
  undated: 'Fără dată',
  allDay: 'toată ziua',
  min: 'min',
  series: 'serie',
  rounded: 'ora rotunjită',
  details: 'Detalii',
  maybe: 'posibil',
  card: 'fișă',
  exists: 'Există deja în jurnal',
  link: 'Leagă',
  move: 'Mută în jurnal',
  skip: 'Nu muta',
  back: 'Readu în listă',
  sNew: 'nemutat',
  sMoved: 'mutat',
  sSkipped: 'omis',
  byHand: 'de dvs.',
  sUnparsed: 'nerecunoscut',
  changed: 's-a schimbat în Google',
  inGoogle: 'în Google acum',
  inJournal: 'în jurnal',
  noAppt: 'programarea nu mai este în jurnal',
  see: 'Vezi în jurnal ›',
  from: 'Din Google',
  keep: 'Evenimentele sunt păstrate doar în programul clinicii, pe calculatorul ei — nu sunt trimise nicăieri. '
    + 'Textul unui eveniment se șterge după mutare și la {n} zile după data lui.',
  clear: 'Șterge tot din Google',
  clearAsk: 'Ștergeți toate evenimentele din Google Calendar din program? Programările deja mutate rămân în jurnal. '
    + 'Evenimentele nemutate dispar din listă.',
  clearOk: 'Șterge',
  close: 'Închide',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const SEARCH_MS = 300

export const loadGcal: RouteLoad<GcalList> = (signal) => gcalApi.list('', '', signal)

interface Props {
  navigate?: (url: string) => void
}

export function GcalScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, leaveIfSignedOut } = useRouteLoad<GcalList>(navigate)
  const [over, setOver] = useState<GcalList | null>(null)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<GcalLoad | null>(null)
  const [moving, setMoving] = useState<GcalRow | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const fileRef = useRef<HTMLInputElement>(null)
  /* поздний ответ старого поиска не перекрывает свежий */
  const seq = useRef(0)
  /* вкладка, выбранная последней: отложенный поиск спрашивает её, а не ту,
     что стояла при наборе */
  const tab = useRef<GcalFilter | null>(null)

  const loaded = state.status === 'ready' ? state.data : null
  const d = over ?? loaded
  const f = d?.f ?? 'nou'

  const run = useCallback(async (call: () => ReturnType<typeof gcalApi.list>, quiet = false) => {
    const mine = ++seq.current
    setBusy(true)
    try {
      const r = await call()
      if (mine === seq.current) setOver(r.data)
      if (!quiet && r.text) setToast({ tone: r.tone, text: r.text })
      return r
    } catch (e) {
      const err = asApiError(e)
      if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
      return null
    } finally {
      setBusy(false)
    }
  }, [leaveIfSignedOut])

  /* поиск — после паузы в наборе, тем же отбором */
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    const timer = window.setTimeout(() => { void run(() => gcalApi.list(tab.current ?? f, query), true) }, SEARCH_MS)
    return () => window.clearTimeout(timer)
    // отбор меняет щелчок по вкладке сам; здесь — только набор текста
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, run])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  }
  if (!d) {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const pickFile = () => fileRef.current?.click()
  async function upload(file: File | undefined) {
    if (!file) return
    const r = await run(() => gcalApi.file(file, f, query), true)
    if (fileRef.current) fileRef.current.value = ''
    if (r) setReport(r.data.load ?? null)
  }
  const fileInput = (
    <input ref={fileRef} type="file" accept=".ics,.zip,text/calendar,application/zip" hidden
           aria-label={T.pick} onChange={(e) => { void upload(e.target.files?.[0]) }} />
  )

  async function clearAll() {
    if (!await ask({ text: T.clearAsk, ok: T.clearOk, danger: true })) return
    setReport(null)
    setQuery('')
    await run(() => gcalApi.clear())
  }

  if (!d.source) {
    return (
      <section className="dp-react-root gc">
        <div className="fcard gc-empty">
          <span className="rc-empty-ico"><Icon name="cal" /></span>
          <b>{T.title}</b>
          <p className="hint">{T.lead}</p>
          <ol className="gc-help">{d.help.map((line) => <li key={line}>{line}</li>)}</ol>
          {fileInput}
          <button type="button" className="rc-btn pri" disabled={busy} onClick={pickFile}>
            <Icon name="upload" /> {busy ? T.reading : T.pick}
          </button>
          <p className="hint">{T.limit.replace('{n}', String(d.max_mb))}</p>
        </div>
        {toast ? <Toast {...toast} onClose={closeToast} /> : null}
      </section>
    )
  }

  const src = d.source
  const rows = d.days.reduce((n, x) => n + x.rows.length, 0) + d.undated.length
  const act = (r: GcalRow) => ({
    onMove: () => setMoving(r),
    onSkip: (on: boolean) => { void run(() => gcalApi.skip(r.id, on, f, query)) },
    onLink: (apptId: number) => { void run(() => gcalApi.link(r.id, apptId, f, query)) },
  })
  return (
    <section className="dp-react-root rc gc">
      <div className="fcard gc-src">
        <div className="gc-src-l">
          <Icon name="cal" />
          <span>
            {T.src}{src.name ? <> · {T.cal} <b>„{src.name}”</b></> : null}
            {src.loaded_at ? ` · ${T.loadedAt} ${src.loaded_at}` : ''}
            {src.loaded_by ? ` ${T.by} ${src.loaded_by}` : ''}
          </span>
        </div>
        {fileInput}
        <button type="button" className="rc-btn" disabled={busy} onClick={pickFile}>
          <Icon name="upload" /> {busy ? T.reading : T.again}
        </button>
        <details className="gc-how">
          <summary>{T.how}</summary>
          <ol className="gc-help">{d.help.map((line) => <li key={line}>{line}</li>)}</ol>
        </details>
      </div>

      {report ? <LoadReport load={report} onClose={() => setReport(null)} /> : null}

      <div className="fcard rc-head">
        <div className="rc-tabs" role="tablist">
          {d.filters.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={f === x.key}
                    className={`rc-tab${f === x.key ? ' on' : ''}`}
                    onClick={() => { tab.current = x.key; void run(() => gcalApi.list(x.key, query), true) }}>
              {x.label} <span className={`rc-n${x.key === 'nou' && x.n ? ' hot' : ''}`}>{x.n}</span>
            </button>
          ))}
        </div>
        <div className="rc-tools">
          <span className="hint gc-total">{roCount(d.total, T.total)}</span>
          <input type="search" className="gc-q" value={query} placeholder={T.search} aria-label={T.search}
                 onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {!rows ? (
        <div className="fcard rc-empty">
          {f === 'nou' && !d.q
            ? <><span className="rc-empty-ico"><Icon name="check" /></span><b>{T.emptyNew}</b></>
            : <p className="hint">{T.empty}</p>}
        </div>
      ) : null}
      {d.days.map((g) => (
        <div key={g.date} className="fcard gc-day">
          <h3 className="gc-day-h">{dayTitle(g.date)}</h3>
          {g.rows.map((r) => <Row key={r.id} r={r} busy={busy} {...act(r)} />)}
        </div>
      ))}
      {d.undated.length ? (
        <div className="fcard gc-day">
          <h3 className="gc-day-h">{T.undated}</h3>
          {d.undated.map((r) => <Row key={r.id} r={r} busy={busy} {...act(r)} />)}
        </div>
      ) : null}

      <div className="gc-foot">
        <p className="hint"><Icon name="shield" /> {T.keep.replace('{n}', String(d.keep_days))}</p>
        {d.can.clear ? (
          <button type="button" className="rc-btn gc-clear" disabled={busy} onClick={() => { void clearAll() }}>
            <Icon name="trash" /> {T.clear}
          </button>
        ) : null}
      </div>

      {moving ? (
        <MoveWindow key={moving.id} row={moving} f={f} q={query} navigate={navigate}
                    onClose={() => setMoving(null)}
                    onStale={() => { void run(() => gcalApi.list(f, query), true) }}
                    onDone={(list, t) => { setOver(list); setToast(t) }} />
      ) : null}
      {toast ? <Toast {...toast} onClose={closeToast} /> : null}
    </section>
  )
}

/** Итог загрузки словами: что принято и что оставлено в стороне, с причиной. */
function LoadReport({ load, onClose }: { load: GcalLoad; onClose: () => void }) {
  const part = (n: number, forms: Parameters<typeof roCount>[1]) => (n ? [roCount(n, forms)] : [])
  const taken = [...part(load.new, T.nNew), ...part(load.updated, T.nUpdated), ...part(load.same, T.nSame)]
  const left = [...part(load.past, T.nPast), ...part(load.all_day, T.nAllDay),
    ...part(load.cancelled, T.nCancelled), ...part(load.beyond, T.nBeyond),
    ...part(load.unparsed, T.nUnparsed), ...part(load.gone, T.nGone)]
  return (
    <div className="fcard gc-report" role="status">
      <div className="gc-report-b">
        <b><Icon name="check" /> {T.loadTitle}</b>
        <span>{T.taken}: {taken.join(', ') || T.nothing}.</span>
        <span>{T.left}: {left.join(', ') || T.nothing}.</span>
        {load.changed ? <span className="gc-warn">{roCount(load.changed, T.nChanged)}.</span> : null}
        {load.refused.map((x) => (
          <span key={x.name + x.code} className="gc-warn">{T.refused}: {x.name || x.code}</span>
        ))}
      </div>
      <button type="button" className="gc-x" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
    </div>
  )
}

interface RowProps {
  r: GcalRow
  busy: boolean
  onMove: () => void
  onSkip: (on: boolean) => void
  onLink: (apptId: number) => void
}

function Row({ r, busy, onMove, onSkip, onLink }: RowProps) {
  const moved = r.state === 'mutat'
  const span = moved ? '' : spanOf(r)
  const minutes = moved ? 0 : minutesOf(r)
  const why = r.why?.text ?? ''
  const skippedSelf = r.state === 'omis' && !!why && ['all_day', 'cancelled', 'gone'].includes(r.why?.code ?? '')
  return (
    <div className={`gc-row${r.state === 'omis' ? ' dim' : ''}`} data-id={r.id} data-state={r.state}>
      <div className="gc-time">
        {moved
          ? <b className="num">{r.appt ? shortWhen(r.appt.when).split(' ')[1] : r.time}</b>
          : <b className="num">{span || (r.date ? T.allDay : '—')}</b>}
        {minutes ? <small>{minutes} {T.min}</small> : null}
      </div>
      <div className="gc-what">
        {moved ? (
          r.appt
            ? <AppLink href={r.appt.day_href}><b>{r.appt.patient}</b> · {r.appt.doctor} · {shortWhen(r.appt.when)}</AppLink>
            : <span className="hint">{T.noAppt}</span>
        ) : <b className="gc-title">{r.title || '—'}</b>}
        <div className="rc-notes">
          {r.round ? <span className="rc-pill grey">{T.rounded} {r.round.from} › {r.round.to}</span> : null}
          {r.series ? <span className="rc-pill grey">{T.series}</span> : null}
          {r.hint?.doctor ? <span className="rc-pill blue">{T.maybe} {r.hint.doctor.name}</span> : null}
          {r.hint?.patients.map((p) => (
            <span key={p.id} className="rc-pill blue">{T.card}: {p.name}</span>
          ))}
          {!moved && why && !skippedSelf ? <span className="rc-pill amber">{why}</span> : null}
          {moved && r.changed ? (
            <span className="rc-pill amber">
              <Icon name="excl" /> {T.changed}
              {r.gstatus ? ` — ${why}` : r.when ? ` — ${T.inGoogle} ${shortWhen(r.when)}` : ''}
            </span>
          ) : null}
        </div>
        {r.hint?.exists ? (
          <p className="gc-exists">
            <Icon name="info" /> {T.exists}: {r.hint.exists.text}{' '}
            <button type="button" className="rc-btn" disabled={busy}
                    onClick={() => onLink(r.hint?.exists?.appt_id ?? 0)}>{T.link}</button>
          </p>
        ) : null}
        {r.body ? (
          <details className="gc-body">
            <summary>{T.details}</summary>
            <pre>{r.body}</pre>
          </details>
        ) : null}
      </div>
      <div className="gc-state">
        {moved ? <span className="rc-pill green"><Icon name="check" /> {T.sMoved}</span> : null}
        {r.state === 'nou' ? <span className="rc-pill grey">{T.sNew}</span> : null}
        {r.state === 'nerecunoscut' ? <span className="rc-pill amber">{T.sUnparsed}</span> : null}
        {r.state === 'omis'
          ? <span className="rc-pill grey">{T.sSkipped} — {skippedSelf ? why : T.byHand}</span> : null}
      </div>
      <div className="rc-acts">
        {r.can.move ? (
          <button type="button" className="rc-btn pri" disabled={busy} onClick={onMove}>
            <Icon name="plus" /> {T.move}
          </button>
        ) : null}
        {r.can.skip
          ? <button type="button" className="rc-btn" disabled={busy} onClick={() => onSkip(true)}>{T.skip}</button>
          : null}
        {r.can.back ? (
          <button type="button" className="rc-btn" disabled={busy} onClick={() => onSkip(false)}>
            <Icon name="undo" /> {T.back}
          </button>
        ) : null}
      </div>
    </div>
  )
}

interface MoveProps {
  row: GcalRow
  f: GcalFilter
  q: string
  navigate: (url: string) => void
  onClose: () => void
  /** Событие уже не то, что на экране (перенёс сосед): перечитать список. */
  onStale: () => void
  onDone: (list: GcalList, toast: ToastState) => void
}

/** Окно записи журнала над строкой события. Форму дня события даёт журнал —
 *  тот же построитель, что у «Programare nouă». */
function MoveWindow({ row, f, q, navigate, onClose, onStale, onDone }: MoveProps) {
  const [got, setGot] = useState<{ date: string; form: DayForm } | null>(null)
  const [busy, setBusy] = useState(false)
  const date = row.preset?.date ?? ''

  useEffect(() => {
    const ctl = new AbortController()
    day.get(date, '', '', ctl.signal).then(
      (r) => {
        if (ctl.signal.aborted) return
        if (r.data.form) setGot({ date: r.data.date, form: r.data.form })
        else onClose()
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        const err = asApiError(e)
        if (err.failure.kind === 'unauthenticated') navigate(loginUrl())
        onClose()
      },
    )
    return () => ctl.abort()
  }, [date, navigate, onClose])

  const add = async (body: NewAppt & { pid?: number }, fail: (text: string) => void): Promise<boolean> => {
    setBusy(true)
    try {
      const r = await gcalApi.move(row.id, body, f, q)
      onDone(r.data, { tone: r.tone, text: r.text, link: { href: `/admin/all?date=${body.date}`, label: T.see } })
      return true
    } catch (e) {
      const err = asApiError(e)
      if (err.failure.kind === 'unauthenticated') navigate(loginUrl())
      else fail(err.text || T.offline)
      if (err.failure.kind === 'conflict' && err.failure.code.startsWith('gc_')) onStale()
      return false
    } finally {
      setBusy(false)
    }
  }

  if (!got) return null
  const when = [row.date ? dayTitle(row.date) : '', row.round?.from ?? spanOf(row)].filter(Boolean).join(', ')
  const note = `${T.from}: ${[when, row.title].filter(Boolean).join(' · ')}`
  return (
    <AddDialog open form={got.form} date={got.date} of="" busy={busy} onClose={onClose} onAdd={add}
               preset={presetOf(row)} note={note} people={row.hint?.patients} askDoctor />
  )
}
