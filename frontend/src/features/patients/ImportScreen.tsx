import { useCallback, useEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Notice } from '../../components/Notice'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import type { ApiError } from '../../types/api'
import { roForm, type RoForm } from '../../utils/plural'
import {
  assign, hasName, MODEL_HREF, num, pimportApi, saveBlob,
  type PiCheck, type PiGroup, type PiHome, type PiImport, type PiOpts, type PiRow,
} from './pimport'

/* Импорт пациентов из .xlsx / .csv мастером в три шага. Файл остаётся в
   браузере и уходит телом каждого запроса; проверка и запись — один разбор
   на сервере, поэтому экран хранит только выбор человека и последний ответ. */
const T = {
  steps: ['Fișier', 'Coloane', 'Verificare'],
  lead: 'Aduceți lista pacienților dintr-un tabel Excel sau CSV. Nimic nu se scrie în evidență până la ultimul pas.',
  pick: 'Alege fișierul (.xlsx sau .csv)',
  reading: 'Se citește fișierul…',
  limit: 'Fișier .xlsx sau .csv, cel mult {mb} MB și {rows} de rânduri.',
  tooBig: 'Fișierul este prea mare (peste {mb} MB) — împărțiți-l în două.',
  model: 'Descarcă modelul',
  modelHint: 'un tabel gol cu antetul pe care programul îl recunoaște singur',
  how: 'Cum salvez lista din Excel sau Google Sheets',
  help: [
    'Excel: Fișier › Salvare ca › tipul „Registru Excel (.xlsx)”. Fișierele vechi .xls se deschid în Excel și se salvează din nou ca .xlsx.',
    'Google Sheets: Fișier › Descărcare › „Microsoft Excel (.xlsx)”.',
    'Alt program: exportați lista ca .csv sau .xlsx. Primul rând al tabelului să fie antetul: Nume, Telefon, Data nașterii…',
  ],
  file: 'Fișier',
  other: 'Alt fișier',
  sheet: 'Foaia',
  sheetRows: { one: '{n} rând', few: '{n} rânduri', many: '{n} de rânduri' },
  enc: 'Codificarea',
  delim: 'Separatorul',
  tab: 'tab',
  header: 'Antetul este pe rândul',
  headerHint: '0 — tabelul nu are antet',
  colsLead: 'Deasupra fiecărei coloane alegeți ce conține. Ce a recunoscut programul este deja ales.',
  colField: 'Ce conține coloana',
  line: 'Rând',
  noName: 'Alegeți coloana cu numele pacientului.',
  noRows: 'Sub antet nu sunt rânduri cu date.',
  verify: 'Verifică',
  verifying: 'Se verifică…',
  toCols: 'Înapoi la coloane',
  total: { one: '{n} rând cu date', few: '{n} rânduri cu date', many: '{n} de rânduri cu date' },
  name: 'Nume',
  phone: 'Telefon',
  birth: 'Data nașterii',
  idnp: 'IDNP',
  notes: 'Observații',
  card: 'fișa',
  canFill: 'se pot completa',
  force: 'nu este același pacient — importă',
  forced: 'Rânduri importate la cererea dvs.',
  unforce: 'Renunță la alegere',
  more: { one: 'și încă {n} rând — lista completă este în raport', few: 'și încă {n} rânduri — lista completă este în raport',
    many: 'și încă {n} de rânduri — lista completă este în raport' },
  family: { one: '{n} fișă nouă are același telefon ca alt pacient', few: '{n} fișe noi au același telefon ca alt pacient',
    many: '{n} de fișe noi au același telefon ca alt pacient' },
  familyTail: ' — număr de familie; se creează fișe separate.',
  fill: 'Completează câmpurile goale la pacienții care există deja',
  fillN: { one: '{n} fișă are ce completa', few: '{n} fișe au ce completa', many: '{n} de fișe au ce completa' },
  fillHint: 'Se scrie doar acolo unde câmpul este gol: data nașterii, gen, IDNP, e-mail, adresă, asigurare, nr. dosar. '
    + 'Anularea importului nu șterge ce s-a completat aici.',
  nPatients: { one: '{n} pacient', few: '{n} pacienți', many: '{n} de pacienți' },
  nCards: { one: '{n} fișă', few: '{n} fișe', many: '{n} de fișe' },
  importBtn: 'Importă',
  fillBtn: 'Completează',
  nothing: 'Nimic nou de importat: toți pacienții din fișier există deja sau nu intră.',
  askImport: 'Importați {what} din „{file}”? Fișele noi apar imediat în lista de pacienți.',
  askFill: ' La {n} se completează câmpurile goale.',
  running: 'Se importă…',
  of: 'din',
  keepOpen: 'Nu închideți fereastra. Programările se pot face în continuare de pe celelalte calculatoare.',
  broken: 'Importul s-a întrerupt. Ce s-a scris rămâne în evidență; continuarea nu creează dubluri.',
  resume: 'Continuă',
  doneTitle: 'Import finalizat',
  created: { one: '{n} fișă nouă', few: '{n} fișe noi', many: '{n} de fișe noi' },
  filled: { one: '{n} completată', few: '{n} completate', many: '{n} de completate' },
  skipped: { one: '{n} rând omis', few: '{n} rânduri omise', many: '{n} de rânduri omise' },
  report: 'Descarcă raportul',
  reportHint: 'ce nu a intrat și ce are observații',
  toPatients: 'Vezi pacienții',
  source: 'Fișierul sursă rămâne pe calculator, cu datele pacienților. După ce ați verificat importul, ștergeți-l sau păstrați-l într-un loc sigur.',
  past: 'Importuri anterioare',
  pastEmpty: '— încă nu s-a făcut niciun import —',
  when: 'Data',
  who: 'Cine',
  result: 'Rezultat',
  undone: 'anulat',
  left: { one: 'a rămas {n} fișă', few: 'au rămas {n} fișe', many: 'au rămas {n} de fișe' },
  undo: 'Anulează importul',
  undoing: 'Se anulează…',
  askUndo: 'Anulați importul din „{file}”? Se șterg doar fișele create de acest import în care nu s-a lucrat de atunci. '
    + 'Fișele cu programări sau cu date medicale rămân.',
  removed: { one: 'S-a șters {n} fișă.', few: 'S-au șters {n} fișe.', many: 'S-au șters {n} de fișe.' },
  kept: { one: '{n} fișă a rămas — are deja programări sau date medicale.',
    few: '{n} fișe au rămas — au deja programări sau date medicale.',
    many: '{n} de fișe au rămas — au deja programări sau date medicale.' },
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const REPORT_NAME = 'raport-import-pacienti.xlsx'
const OPEN_GROUPS = new Set(['dup', 'bad'])

/** Слово при числе, как `roCount`, но разряды числа — пробелом. */
const cnt = (n: number, forms: Record<RoForm, string>): string => forms[roForm(n)].replace('{n}', num(n))

type Step = 'file' | 'cols' | 'check' | 'run' | 'done'
interface Progress { part: number; parts: number; importId: number; broken: boolean }

export const loadPimport: RouteLoad<PiHome> = (signal) => pimportApi.home(signal)

interface Props {
  navigate?: (url: string) => void
}

export function ImportScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<PiHome>(navigate)
  const [step, setStep] = useState<Step>('file')
  const [file, setFile] = useState<File | null>(null)
  const [check, setCheck] = useState<PiCheck | null>(null)
  const [opts, setOpts] = useState<PiOpts | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [result, setResult] = useState<PiImport | null>(null)
  const [undoing, setUndoing] = useState(0)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const fileRef = useRef<HTMLInputElement>(null)
  /* импорт идёт порциями и переживает отрисовки: после ухода с экрана ответ не пишется в состояние */
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])

  const fail = useCallback((e: unknown): ApiError | null => {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return null
    setToast({ tone: err.code === 'pi_stale' ? 'warn' : 'err', text: err.text || T.offline })
    return err
  }, [leaveIfSignedOut])

  const refreshHome = useCallback(async () => {
    try {
      const r = await pimportApi.home()
      if (alive.current) replace(r.data)
    } catch { /* список прошлых импортов обновится при следующем открытии */ }
  }, [replace])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  }
  if (state.status === 'loading') {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }
  const home = state.data
  const mb = Math.round(home.limits.bytes / 1048576)

  /* Проверка: тот же запрос на шагах «Coloane» и «Verificare». */
  async function verify(f: File, next: Partial<PiOpts>, to: Step | null): Promise<void> {
    setBusy(true)
    try {
      const r = await pimportApi.check(f, next)
      if (!alive.current) return
      setCheck(r.data)
      setOpts(r.data.opts)
      if (to) setStep(to === 'check' && !r.data.ready ? 'cols' : to)
    } catch (e) {
      fail(e)
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  function pick(f: File | undefined) {
    if (fileRef.current) fileRef.current.value = ''
    if (!f) return
    if (f.size > home.limits.bytes) {
      setToast({ tone: 'err', text: T.tooBig.replace('{mb}', String(mb)) })
      return
    }
    setToast(null)
    setFile(f)
    setCheck(null)
    setOpts(null)
    setResult(null)
    setStep('file')
    void verify(f, {}, 'cols')
  }

  function restart() {
    setFile(null)
    setCheck(null)
    setOpts(null)
    setResult(null)
    setProgress(null)
    setStep('file')
  }

  /* Порции по очереди: между ними сервер свободен для журнала. Повтор порции
     безвреден, поэтому после обрыва продолжаем с той же. */
  async function runFrom(f: File, o: PiOpts, c: PiCheck, from: Progress): Promise<void> {
    let { part, importId } = from
    setStep('run')
    setProgress({ ...from, broken: false })
    while (part < from.parts) {
      try {
        const r = await pimportApi.run(f, o, c.token, part, importId)
        if (!alive.current) return
        importId = r.data.import
        part += 1
        setProgress({ part, parts: from.parts, importId, broken: false })
        if (r.data.done) {
          setResult(r.data.total)
          setStep('done')
          void refreshHome()
          return
        }
      } catch (e) {
        if (!alive.current) return
        const err = fail(e)
        if (err && (err.code === 'pi_stale' || err.code === 'pi_gone')) {
          setProgress(null)
          void verify(f, o, 'check')
          void refreshHome()
        } else {
          setProgress({ part, parts: from.parts, importId, broken: true })
        }
        return
      }
    }
  }

  async function start() {
    if (!file || !opts || !check?.counts) return
    const n = check.counts
    const text = T.askImport.replace('{what}', cnt(n.create, T.nPatients)).replace('{file}', file.name)
      + (opts.fill && n.fill ? T.askFill.replace('{n}', cnt(n.fill, T.nCards)) : '')
    if (!await ask({ text, ok: T.importBtn })) return
    await runFrom(file, opts, check, { part: 0, parts: Math.max(check.parts ?? 1, 1), importId: 0, broken: false })
  }

  async function report(importId = 0) {
    if (!file || !opts) return
    setBusy(true)
    try {
      saveBlob(await pimportApi.report(file, opts, importId), REPORT_NAME)
    } catch (e) {
      fail(e)
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  async function undo(run: PiImport) {
    if (!await ask({ text: T.askUndo.replace('{file}', run.file), ok: T.undo, danger: true })) return
    setUndoing(run.id)
    try {
      let after = 0
      let removed = 0
      for (;;) {
        const r = await pimportApi.undo(run.id, after)
        if (!alive.current) return
        removed += r.data.removed
        after = r.data.after
        if (r.data.done) {
          const kept = r.data.kept
          setToast(kept > 0
            ? { tone: 'warn', text: `${cnt(removed, T.removed)} ${cnt(kept, T.kept)}` }
            : { tone: r.tone, text: r.text })
          break
        }
      }
    } catch (e) {
      fail(e)
    } finally {
      if (alive.current) setUndoing(0)
      void refreshHome()
    }
  }

  const fileInput = (
    <input ref={fileRef} type="file" hidden aria-label={T.pick}
           accept=".xlsx,.csv,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
           onChange={(e) => pick(e.target.files?.[0])} />
  )
  const at = step === 'file' ? 0 : step === 'cols' ? 1 : 2
  const working = busy || step === 'run'

  return (
    <section className="dp-react-root pi" aria-busy={busy}>
      {toast ? <Toast {...toast} onClose={closeToast} /> : null}
      <ol className="pi-steps" aria-label="Pași">
        {T.steps.map((label, i) => (
          <li key={label} className={i === at ? 'on' : i < at ? 'past' : ''} aria-current={i === at ? 'step' : undefined}>
            <span>{i + 1}</span> {label}
          </li>
        ))}
      </ol>

      {home.remote ? <Notice n={home.remote} /> : null}

      {!home.remote && step === 'file' ? (
        <div className="fcard pi-pick">
          <span className="rc-empty-ico"><Icon name="upload" /></span>
          <p className="hint">{T.lead}</p>
          {fileInput}
          <button type="button" className="dp-btn pri" disabled={busy} onClick={() => fileRef.current?.click()}>
            <Icon name="upload" /> {busy ? T.reading : T.pick}
          </button>
          <p className="hint">{T.limit.replace('{mb}', String(mb)).replace('{rows}', num(home.limits.rows))}</p>
          <p className="pi-model">
            <AppLink className="dp-link" href={MODEL_HREF} download>{T.model}</AppLink>
            <small className="dp-muted"> — {T.modelHint}</small>
          </p>
          <details className="pi-how">
            <summary>{T.how}</summary>
            <ul>{T.help.map((x) => <li key={x}>{x}</li>)}</ul>
          </details>
        </div>
      ) : null}

      {file && check && opts && step !== 'file' ? (
        <div className="fcard pi-file">
          <Icon name="file" />
          <span>{T.file} <b>„{file.name}”</b>
            {check.counts ? <> · {cnt(check.counts.rows, T.total)}</> : null}</span>
          {fileInput}
          <button type="button" className="rc-btn" disabled={working} onClick={() => fileRef.current?.click()}>
            <Icon name="upload" /> {T.other}
          </button>
        </div>
      ) : null}

      {file && check && opts && step === 'cols' ? (
        <Columns home={home} check={check} opts={opts} busy={busy}
                 onOpts={setOpts}
                 onReread={(next) => { void verify(file, next, null) }}
                 onVerify={() => { void verify(file, opts, 'check') }} />
      ) : null}

      {file && check?.counts && opts && step === 'check' ? (
        <div className="pi-check">
          <ul className="pi-counts">
            {check.groups.map((g) => (
              <li key={g.id} className={`pi-count ${g.id}${g.count ? '' : ' zero'}`}><b>{num(g.count)}</b> {g.label}</li>
            ))}
          </ul>
          {check.counts.family ? (
            <p className="hint">{cnt(check.counts.family, T.family)}{T.familyTail}</p>
          ) : null}
          {check.groups.filter((g) => g.count > 0).map((g) => (
            <Group key={g.id} g={g} force={opts.force} disabled={busy}
                   onForce={(line) => { void verify(file, { ...opts, force: [...opts.force, line] }, null) }} />
          ))}
          {opts.force.length ? (
            <p className="hint">
              {T.forced}: {opts.force.join(', ')}{' · '}
              <button type="button" className="dp-link" disabled={busy}
                      onClick={() => { void verify(file, { ...opts, force: [] }, null) }}>{T.unforce}</button>
            </p>
          ) : null}
          <div className="fcard pi-fill">
            <label>
              <input type="checkbox" checked={opts.fill} disabled={busy || (!check.counts.fill && !opts.fill)}
                     onChange={(e) => { void verify(file, { ...opts, fill: e.target.checked }, null) }} />
              <span>{T.fill}{check.counts.exists ? ` (${cnt(check.counts.fill, T.fillN)})` : ''}</span>
            </label>
            <p className="hint">{T.fillHint}</p>
          </div>
          {check.counts.create === 0 && !(opts.fill && check.counts.fill) ? (
            <div className="banner warn" role="status">{T.nothing}</div>
          ) : null}
          <div className="pi-acts">
            <button type="button" className="rc-btn" disabled={busy} onClick={() => setStep('cols')}>
              <Icon name="chev-l" /> {T.toCols}
            </button>
            <button type="button" className="rc-btn" disabled={busy} title={T.reportHint}
                    onClick={() => { void report() }}>
              <Icon name="download" /> {T.report}
            </button>
            <button type="button" className="dp-btn pri pi-go" onClick={() => { void start() }}
                    disabled={busy || (check.counts.create === 0 && !(opts.fill && check.counts.fill))}>
              <Icon name="upload" /> {check.counts.create
                ? `${T.importBtn} ${cnt(check.counts.create, T.nPatients)}`
                : `${T.fillBtn} ${cnt(check.counts.fill, T.nCards)}`}
            </button>
          </div>
        </div>
      ) : null}

      {file && check?.counts && opts && progress && step === 'run' ? (
        <div className="fcard pi-run" role="status">
          <b>{T.running}</b>
          <progress max={progress.parts} value={progress.part} />
          <span className="pi-run-n">
            {num(Math.min(progress.part * home.limits.batch, check.counts.rows))} {T.of} {num(check.counts.rows)}
          </span>
          {progress.broken ? (
            <>
              <div className="banner warn" role="alert">{T.broken}</div>
              <button type="button" className="dp-btn pri pi-go"
                      onClick={() => { void runFrom(file, opts, check, progress) }}>
                <Icon name="refresh" /> {T.resume}
              </button>
            </>
          ) : <p className="hint">{T.keepOpen}</p>}
        </div>
      ) : null}

      {result && step === 'done' ? (
        <div className="fcard pi-done">
          <span className="rc-empty-ico ok"><Icon name="check" /></span>
          <b>{T.doneTitle}</b>
          <p className="pi-done-n">
            {[cnt(result.created, T.created),
              ...(result.filled ? [cnt(result.filled, T.filled)] : []),
              ...(result.skipped ? [cnt(result.skipped, T.skipped)] : [])].join(' · ')}
          </p>
          <div className="pi-acts">
            <button type="button" className="rc-btn" disabled={busy} title={T.reportHint}
                    onClick={() => { void report(result.id) }}>
              <Icon name="download" /> {T.report}
            </button>
            <AppLink className="rc-btn pri" href="/admin/search"><Icon name="pat" /> {T.toPatients}</AppLink>
            <button type="button" className="rc-btn" onClick={restart}><Icon name="upload" /> {T.other}</button>
          </div>
          <p className="hint">{T.source}</p>
        </div>
      ) : null}

      <div className="fcard pi-past">
        <h3>{T.past}</h3>
        {home.imports.length === 0 ? <p className="hint">{T.pastEmpty}</p> : (
          <table className="pi-table">
            <thead><tr><th>{T.when}</th><th>{T.who}</th><th>{T.file}</th><th>{T.result}</th><th /></tr></thead>
            <tbody>
              {home.imports.map((r) => (
                <tr key={r.id} className={r.undone ? 'dim' : ''}>
                  <td>{r.at}</td>
                  <td>{r.actor}</td>
                  <td className="pi-fname">{r.file}</td>
                  <td>
                    {cnt(r.created, T.created)}
                    {r.filled ? ` · ${cnt(r.filled, T.filled)}` : ''}
                    {r.undone ? <> · <b>{T.undone}</b>{r.created - r.removed > 0
                      ? ` — ${cnt(r.created - r.removed, T.left)}` : ''}</> : null}
                  </td>
                  <td className="pi-td-act">
                    {r.can_undo && !r.undone && !home.remote ? (
                      <button type="button" className="rc-btn" disabled={working || undoing !== 0}
                              onClick={() => { void undo(r) }}>
                        <Icon name="undo" /> {undoing === r.id ? T.undoing : T.undo}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

interface ColumnsProps {
  home: PiHome
  check: PiCheck
  opts: PiOpts
  busy: boolean
  onOpts: (o: PiOpts) => void
  /** Лист, шапка, кодировка или разделитель: колонки программа угадывает заново. */
  onReread: (next: Partial<PiOpts>) => void
  onVerify: () => void
}

function Columns({ home, check, opts, busy, onOpts, onReread, onVerify }: ColumnsProps) {
  const f = check.file
  const base = { sheet: opts.sheet, enc: opts.enc, delim: opts.delim, fill: opts.fill }
  const named = hasName(opts.cols)
  return (
    <div className="fcard pi-cols">
      <div className="pi-opts">
        {f.sheets.length > 1 ? (
          <label>{T.sheet}
            <select className="dp-sel" value={opts.sheet} disabled={busy}
                    onChange={(e) => onReread({ ...base, sheet: Number(e.target.value) })}>
              {f.sheets.map((s, i) => (
                <option key={s.name} value={i}>{s.name} ({cnt(s.rows, T.sheetRows)})</option>
              ))}
            </select>
          </label>
        ) : null}
        {f.kind === 'csv' ? (
          <>
            <label>{T.enc}
              <select className="dp-sel" value={opts.enc} disabled={busy}
                      onChange={(e) => onReread({ ...base, enc: e.target.value })}>
                {home.encodings.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </label>
            <label>{T.delim}
              <select className="dp-sel" value={opts.delim} disabled={busy}
                      onChange={(e) => onReread({ ...base, delim: e.target.value })}>
                {home.delimiters.map((x) => <option key={x} value={x}>{x === '\t' ? T.tab : x}</option>)}
              </select>
            </label>
          </>
        ) : null}
        <label title={T.headerHint}>{T.header}
          <input type="number" className="pi-num" min={0} max={9999} value={opts.header} disabled={busy}
                 onChange={(e) => onReread({ ...base, header: Math.max(0, Math.trunc(Number(e.target.value) || 0)) })} />
        </label>
      </div>
      <p className="hint">{T.colsLead}</p>
      <div className="pi-scroll">
        <table className="pi-table pi-preview">
          <thead>
            <tr>
              <th>{T.line}</th>
              {check.columns.map((c) => (
                <th key={c.index} className={opts.cols[String(c.index)] ? 'on' : ''}>
                  <select className="dp-sel" aria-label={`${T.colField} ${c.letter}`} disabled={busy}
                          value={opts.cols[String(c.index)] ?? ''}
                          onChange={(e) => onOpts({ ...opts, cols: assign(opts.cols, c.index, e.target.value) })}>
                    {home.fields.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                  </select>
                  <small>{c.letter}{c.title ? ` · ${c.title}` : ''}</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {check.preview.map((r) => (
              <tr key={r.line}>
                <td className="pi-ln">{r.line}</td>
                {check.columns.map((c) => (
                  <td key={c.index} className={opts.cols[String(c.index)] ? '' : 'off'}>{r.cells[c.index] ?? ''}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {check.preview.length === 0 ? <div className="banner warn" role="status">{T.noRows}</div> : null}
      <div className="pi-acts">
        {named ? null : <span className="pi-need" role="note">{T.noName}</span>}
        <button type="button" className="dp-btn pri pi-go" disabled={busy || !named} onClick={onVerify}>
          <Icon name="check" /> {busy ? T.verifying : T.verify}
        </button>
      </div>
    </div>
  )
}

interface GroupProps {
  g: PiGroup
  force: number[]
  disabled: boolean
  onForce: (line: number) => void
}

function Group({ g, force, disabled, onForce }: GroupProps) {
  return (
    <details className={`fcard pi-group ${g.id}`} open={OPEN_GROUPS.has(g.id)}>
      <summary><Icon name="chev-r" /><b>{g.label}</b> <span className="pi-badge">{num(g.count)}</span></summary>
      <div className="pi-scroll">
        <table className="pi-table">
          <thead>
            <tr><th>{T.line}</th><th>{T.name}</th><th>{T.phone}</th><th>{T.birth}</th><th>{T.idnp}</th><th>{T.notes}</th></tr>
          </thead>
          <tbody>
            {g.rows.map((r) => <Row key={r.line} r={r} forced={force.includes(r.line)} disabled={disabled} onForce={onForce} />)}
          </tbody>
        </table>
      </div>
      {g.more > 0 ? <p className="hint">{cnt(g.more, T.more)}</p> : null}
    </details>
  )
}

function Row({ r, forced, disabled, onForce }: { r: PiRow; forced: boolean; disabled: boolean; onForce: (line: number) => void }) {
  const said = [r.reason, ...r.notes].filter(Boolean)
  return (
    <tr>
      <td className="pi-ln">{r.line}</td>
      <td>{r.name}</td>
      <td>{r.phone}</td>
      <td>{r.birth}</td>
      <td>{r.idnp}</td>
      <td className="pi-said">
        {said.map((x) => <span key={x}>{x}</span>)}
        {r.match ? <AppLink href={`/admin/patient/${r.match.id}`} target="_blank" rel="noreferrer">{T.card} ›</AppLink> : null}
        {r.fill.length ? <small className="dp-muted">{T.canFill}: {r.fill.join(', ')}</small> : null}
        {r.forceable && !forced ? (
          <label className="pi-force">
            <input type="checkbox" disabled={disabled} checked={false} onChange={() => onForce(r.line)} /> {T.force}
          </label>
        ) : null}
      </td>
    </tr>
  )
}
