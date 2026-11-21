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
  assign, chooseDoctor, hasName, hasVisits, MODEL_HREF, NO_DOCTOR, num, pimportApi, saveBlob,
  type PiCheck, type PiGroup, type PiHome, type PiImport, type PiOpts, type PiRow, type PiRun,
  type PiUndoPhase, type PiVisitGroup,
} from './pimport'

/* Импорт пациентов из .xlsx / .csv мастером в три шага. Файл остаётся в
   браузере и уходит телом каждого запроса; проверка и запись — один разбор
   на сервере, поэтому экран хранит только выбор человека и последний ответ. */
const T = {
  steps: ['Fișier', 'Coloane', 'Verificare'],
  stepsDocs: ['Fișier', 'Coloane', 'Medici', 'Verificare'],
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
  toDocs: 'Înapoi la medici',
  docsLead: 'Programul a căutat medicii din fișier printre medicii clinicii. Verificați și alegeți acolo unde nu i-a '
    + 'recunoscut. Medicul ales devine „Medic curant” în fișa pacientului; o alegere se aplică tuturor rândurilor '
    + 'cu aceeași scriere.',
  docsUnknown: { one: '{n} scriere nerecunoscută', few: '{n} scrieri nerecunoscute', many: '{n} de scrieri nerecunoscute' },
  docsUnknownTail: ' — rândurile intră fără medic, iar numele din fișier rămâne în notițe.',
  docsVisits: ' Același medic primește și programările din fișier; „Fără medic” — rândul intră fără programare, '
    + 'data rămâne în notițe.',
  docsUnknownVisits: ' — rândurile intră fără medic și fără programare; numele și data rămân în notițe.',
  inFile: 'În fișier',
  rows: 'Rânduri',
  doctor: 'Medic în DentPilot',
  docState: 'Cum',
  docAuto: 'recunoscut',
  docChosen: 'ales de dvs.',
  docNone: 'fără medic',
  docUnknown: 'nu recunosc',
  docPick: '— alegeți medicul —',
  noDoctor: 'Fără medic',
  noDoctorVisits: 'Fără medic — nu programa',
  inactive: 'inactiv',
  docInactive: 'medic inactiv în clinică',
  docCands: 'se potrivesc: {names}',
  docsGo: 'Continuă',
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
  nVisits: { one: '{n} programare', few: '{n} programări', many: '{n} de programări' },
  nPastIn: ' ({n} în istoric)',
  and: ' și ',
  visitsTitle: 'Programări din fișier',
  visitsLead: 'Rândurile cu dată, oră și medic devin programări în agendă, la fișa pacientului. Fără oră sau fără '
    + 'medic nu se programează nimic: data rămâne în notițele fișei. Nimic nu se scrie până la „Importă”.',
  pastVisits: 'Importă și vizitele trecute — ca finalizate, în istoric',
  pastHint: 'Dau „Ultima vizită” în fișă și pot umple lista „Rechemări” cu pacienții care nu au mai venit.',
  sms: 'Trimite SMS de reamintire pentru programările importate',
  smsHint: 'Oprit — pacienții nu primesc SMS pentru programările din fișier. Programările puse de mână primesc SMS ca de obicei.',
  svc: 'Procedura, când în fișier nu este sau nu se recunoaște',
  vWhen: 'Data și ora',
  vDoctor: 'Medic',
  vService: 'Procedură',
  askVisitsNoSms: ' Pentru programările din fișier nu se trimit SMS.',
  doneVisits: { one: '{n} programare pusă', few: '{n} programări puse', many: '{n} de programări puse' },
  doneVisitsNo: { one: '{n} nepusă', few: '{n} nepuse', many: '{n} de nepuse' },
  doneVisitsHint: 'De ce nu s-au pus unele programări — în raport, coloana „Programare”.',
  recall: { one: '{n} pacient a intrat în „Rechemări”', few: '{n} pacienți au intrat în „Rechemări”',
    many: '{n} de pacienți au intrat în „Rechemări”' },
  recallGo: 'Deschide Rechemări',
  nCards: { one: '{n} fișă', few: '{n} fișe', many: '{n} de fișe' },
  importBtn: 'Importă',
  fillBtn: 'Completează',
  nothing: 'Nimic nou de importat: toți pacienții din fișier există deja sau nu intră.',
  nothingVisits: 'Nimic nou de importat: pacienții există deja, iar programările din fișier nu se pot pune.',
  askImport: 'Importați {what} din „{file}”? Fișele noi apar imediat în lista de pacienți.',
  askFill: ' La {n} se completează câmpurile goale.',
  askOnlyFill: 'Completați câmpurile goale la {n} din „{file}”? Fișe noi nu se creează.',
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
  askUndoVisits: 'Anulați importul din „{file}”? Se șterg programările puse de acest import, dacă nu s-a lucrat cu ele, '
    + 'și fișele create de import în care nu s-a lucrat de atunci. Ce s-a schimbat de mână rămâne.',
  removedVisits: { one: 'S-a șters {n} programare.', few: 'S-au șters {n} programări.', many: 'S-au șters {n} de programări.' },
  keptVisits: { one: '{n} programare a rămas — s-a lucrat cu ea.', few: '{n} programări au rămas — s-a lucrat cu ele.',
    many: '{n} de programări au rămas — s-a lucrat cu ele.' },
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

/** «Pacienți» со списком только фиш этого импорта. */
const listOf = (id: number): string => `/admin/search?imp=${id}`

type Step = 'file' | 'cols' | 'docs' | 'check' | 'run' | 'done'
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
  const [last, setLast] = useState<PiRun | null>(null)
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
      /* без колонки врача шагу «Medici» нечего показать */
      if (to === 'docs' && !r.data.doctors.length) to = 'check'
      if (to) setStep((to === 'check' || to === 'docs') && !r.data.ready ? 'cols' : to)
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
    setLast(null)
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
          setLast(r.data)
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
    const filling = opts.fill && n.fill > 0
    const v = visitsIn(check)
    const what = [n.create ? cnt(n.create, T.nPatients) : '', v.total ? visitWords(v.total, v.past) : '']
      .filter(Boolean).join(T.and)
    const text = n.create || v.total
      ? T.askImport.replace('{what}', what).replace('{file}', file.name)
        + (filling ? T.askFill.replace('{n}', cnt(n.fill, T.nCards)) : '')
        + (v.future && !opts.sms ? T.askVisitsNoSms : '')
      : T.askOnlyFill.replace('{n}', cnt(n.fill, T.nCards)).replace('{file}', file.name)
    if (!await ask({ text, ok: n.create || v.total ? T.importBtn : T.fillBtn })) return
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
    const text = (run.visits ? T.askUndoVisits : T.askUndo).replace('{file}', run.file)
    if (!await ask({ text, ok: T.undo, danger: true })) return
    setUndoing(run.id)
    try {
      /* сперва визиты импорта, потом фиши: фишу держит визит, который остался */
      let phase: PiUndoPhase = 'v'
      let after = 0
      let removed = 0
      let vRemoved = 0
      for (;;) {
        const r = await pimportApi.undo(run.id, phase, after)
        if (!alive.current) return
        removed += r.data.removed
        vRemoved += r.data.visits_removed
        phase = r.data.phase
        after = r.data.after
        if (r.data.done) {
          const { kept, visits_kept: vKept } = r.data
          const said = [cnt(removed, T.removed), ...(run.visits ? [cnt(vRemoved, T.removedVisits)] : []),
            ...(kept > 0 ? [cnt(kept, T.kept)] : []), ...(vKept > 0 ? [cnt(vKept, T.keptVisits)] : [])]
          setToast(kept > 0 || vKept > 0 || run.visits
            ? { tone: kept > 0 || vKept > 0 ? 'warn' : r.tone, text: said.join(' ') }
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
  const hasDocs = Boolean(check?.doctors.length)
  const vIn = check ? visitsIn(check) : { total: 0, past: 0, future: 0 }
  const canGo = Boolean(check?.counts && (check.counts.create > 0 || (opts?.fill && check.counts.fill) || vIn.total > 0))
  const steps = hasDocs ? T.stepsDocs : T.steps
  const at = step === 'file' ? 0 : step === 'cols' ? 1 : step === 'docs' ? 2 : steps.length - 1
  const working = busy || step === 'run'

  return (
    <section className="dp-react-root pi" aria-busy={busy}>
      {toast ? <Toast {...toast} onClose={closeToast} /> : null}
      <ol className="pi-steps" aria-label="Pași">
        {steps.map((label, i) => (
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
                 onVerify={() => { void verify(file, opts, 'docs') }} />
      ) : null}

      {file && check && opts && step === 'docs' ? (
        <Doctors check={check} busy={busy} visits={hasVisits(opts.cols)}
                 onPick={(key, value) => { void verify(file, { ...opts, docs: chooseDoctor(opts.docs, key, value) }, null) }}
                 onBack={() => setStep('cols')} onNext={() => setStep('check')} />
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
          {check.visits ? (
            <Visits check={check} opts={opts} busy={busy}
                    onOpts={(next) => { void verify(file, { ...opts, ...next }, null) }} />
          ) : null}
          {!canGo ? (
            <div className="banner warn" role="status">{check.visits ? T.nothingVisits : T.nothing}</div>
          ) : null}
          <div className="pi-acts">
            <button type="button" className="rc-btn" disabled={busy} onClick={() => setStep(hasDocs ? 'docs' : 'cols')}>
              <Icon name="chev-l" /> {hasDocs ? T.toDocs : T.toCols}
            </button>
            <button type="button" className="rc-btn" disabled={busy} title={T.reportHint}
                    onClick={() => { void report() }}>
              <Icon name="download" /> {T.report}
            </button>
            <button type="button" className="dp-btn pri pi-go" onClick={() => { void start() }}
                    disabled={busy || !canGo}>
              <Icon name="upload" /> {check.counts.create || vIn.total
                ? `${T.importBtn} ${[check.counts.create ? cnt(check.counts.create, T.nPatients) : '',
                  vIn.total ? cnt(vIn.total, T.nVisits) : ''].filter(Boolean).join(T.and)}`
                : opts.fill && check.counts.fill ? `${T.fillBtn} ${cnt(check.counts.fill, T.nCards)}` : T.importBtn}
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
          {result.visits || result.visits_skipped ? (
            <p className="pi-done-n">
              {[cnt(result.visits, T.doneVisits) + (result.visits_past ? T.nPastIn.replace('{n}', num(result.visits_past)) : ''),
                ...(result.visits_skipped ? [cnt(result.visits_skipped, T.doneVisitsNo)] : [])].join(' · ')}
            </p>
          ) : null}
          {last?.recall ? (
            <p className="pi-done-n">
              {cnt(last.recall, T.recall)} · <AppLink className="dp-link" href="/admin/rechemari">{T.recallGo}</AppLink>
            </p>
          ) : null}
          {result.visits_skipped ? <p className="hint">{T.doneVisitsHint}</p> : null}
          <div className="pi-acts">
            <button type="button" className="rc-btn" disabled={busy} title={T.reportHint}
                    onClick={() => { void report(result.id) }}>
              <Icon name="download" /> {T.report}
            </button>
            <AppLink className="rc-btn pri" href={result.created > result.removed ? listOf(result.id) : '/admin/search'}>
              <Icon name="pat" /> {T.toPatients}
            </AppLink>
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
                    {r.visits ? ` · ${cnt(r.visits, T.doneVisits)}` : ''}
                    {r.undone ? <> · <b>{T.undone}</b>{r.created - r.removed > 0
                      ? ` — ${cnt(r.created - r.removed, T.left)}` : ''}</> : null}
                  </td>
                  <td className="pi-td-act">
                    {r.created > r.removed ? (
                      <AppLink className="rc-btn" href={listOf(r.id)}><Icon name="pat" /> {T.toPatients}</AppLink>
                    ) : null}
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

interface DoctorsProps {
  check: PiCheck
  busy: boolean
  /** В файле есть дата записи: «Fără medic» значит и «не программа». */
  visits: boolean
  onPick: (key: string, value: string) => void
  onBack: () => void
  onNext: () => void
}

function Doctors({ check, busy, visits, onPick, onBack, onNext }: DoctorsProps) {
  const byId = new Map(check.clinic_doctors.map((d) => [d.id, d]))
  const unknown = check.doctors.filter((d) => !d.auto && !d.choice).length
  return (
    <div className="fcard pi-cols pi-docs">
      <p className="hint">{T.docsLead}{visits ? T.docsVisits : ''}</p>
      {unknown ? (
        <div className="banner warn" role="status">
          {cnt(unknown, T.docsUnknown)}{visits ? T.docsUnknownVisits : T.docsUnknownTail}
        </div>
      ) : null}
      <div className="pi-scroll">
        <table className="pi-table">
          <thead>
            <tr><th>{T.inFile}</th><th>{T.rows}</th><th>{T.doctor}</th><th>{T.docState}</th></tr>
          </thead>
          <tbody>
            {check.doctors.map((d) => {
              const value = d.choice || d.auto
              const picked = value && value !== NO_DOCTOR ? byId.get(value) : undefined
              const state = d.choice === NO_DOCTOR ? T.docNone : d.choice ? T.docChosen : d.auto ? T.docAuto : T.docUnknown
              const cands = d.cands.map((id) => byId.get(id)?.name).filter(Boolean)
              return (
                <tr key={d.key} className={value ? '' : 'pi-doc-unknown'}>
                  <td>{d.value}</td>
                  <td className="pi-ln">{num(d.rows)}</td>
                  <td>
                    <select className="dp-sel" aria-label={`${T.doctor}: ${d.value}`} disabled={busy} value={value}
                            onChange={(e) => onPick(d.key, e.target.value)}>
                      {value ? null : <option value="">{T.docPick}</option>}
                      {check.clinic_doctors.map((c) => (
                        <option key={c.id} value={c.id}>{c.active ? c.name : `${c.name} (${T.inactive})`}</option>
                      ))}
                      <option value={NO_DOCTOR}>{visits ? T.noDoctorVisits : T.noDoctor}</option>
                    </select>
                  </td>
                  <td>
                    <div className="pi-said">
                      <span>{state}</span>
                      {picked && !picked.active ? <small className="dp-muted">{T.docInactive}</small> : null}
                      {!value && cands.length ? <small className="dp-muted">{T.docCands.replace('{names}', cands.join(', '))}</small> : null}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="pi-acts">
        <button type="button" className="rc-btn" disabled={busy} onClick={onBack}>
          <Icon name="chev-l" /> {T.toCols}
        </button>
        <button type="button" className="dp-btn pri pi-go" disabled={busy} onClick={onNext}>
          <Icon name="check" /> {T.docsGo}
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

/** Визиты файла, которые встанут: всего и сколько из них прошлых. */
function visitsIn(c: PiCheck): { total: number; past: number; future: number } {
  const n = c.visits?.counts
  return n ? { total: n.v_new + n.v_past, past: n.v_past, future: n.v_new } : { total: 0, past: 0, future: 0 }
}

const visitWords = (total: number, past: number): string =>
  cnt(total, T.nVisits) + (past ? T.nPastIn.replace('{n}', num(past)) : '')

const OPEN_VISITS = new Set(['v_no'])

interface VisitsProps {
  check: PiCheck
  opts: PiOpts
  busy: boolean
  /** Галочки и процедура по умолчанию: та же проверка заново. */
  onOpts: (next: Partial<PiOpts>) => void
}

/* Галочки — сверху, над группами: ответ проверки меняет группы под ними, а не место галочки. */
function Visits({ check, opts, busy, onOpts }: VisitsProps) {
  const v = check.visits
  if (!v) return null
  return (
    <>
      <div className="fcard pi-fill pi-visits">
        <h3>{T.visitsTitle}</h3>
        <p className="hint">{T.visitsLead}</p>
        <label>
          <input type="checkbox" checked={opts.past} disabled={busy} onChange={(e) => onOpts({ past: e.target.checked })} />
          <span>{T.pastVisits}</span>
        </label>
        <p className="hint">{T.pastHint}</p>
        {check.sms_on ? (
          <>
            <label>
              <input type="checkbox" checked={opts.sms} disabled={busy} onChange={(e) => onOpts({ sms: e.target.checked })} />
              <span>{T.sms}</span>
            </label>
            {opts.sms ? null : <p className="hint">{T.smsHint}</p>}
          </>
        ) : null}
        {check.services.length ? (
          <label className="pi-svc">{T.svc}
            <select className="dp-sel" value={opts.svc} disabled={busy} onChange={(e) => onOpts({ svc: e.target.value })}>
              {check.services.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
        ) : null}
        <ul className="pi-counts">
          {v.groups.map((g) => (
            <li key={g.id} className={`pi-count ${g.id}${g.count ? '' : ' zero'}`}><b>{num(g.count)}</b> {g.label}</li>
          ))}
        </ul>
      </div>
      {v.groups.filter((g) => g.count > 0).map((g) => <VisitGroup key={g.id} g={g} />)}
    </>
  )
}

function VisitGroup({ g }: { g: PiVisitGroup }) {
  return (
    <details className={`fcard pi-group ${g.id}`} open={OPEN_VISITS.has(g.id)}>
      <summary><Icon name="chev-r" /><b>{g.label}</b> <span className="pi-badge">{num(g.count)}</span></summary>
      <div className="pi-scroll">
        <table className="pi-table">
          <thead>
            <tr><th>{T.line}</th><th>{T.name}</th><th>{T.vWhen}</th><th>{T.vDoctor}</th><th>{T.vService}</th><th>{T.notes}</th></tr>
          </thead>
          <tbody>
            {g.rows.map((r) => (
              <tr key={r.line}>
                <td className="pi-ln">{r.line}</td>
                <td>{r.name}</td>
                <td className="pi-when">{r.when}</td>
                <td>{r.doctor}</td>
                <td>{r.service}</td>
                <td className="pi-said">
                  {[r.reason, ...r.notes].filter(Boolean).map((x) => <span key={x}>{x}</span>)}
                  {r.patient ? <AppLink href={`/admin/patient/${r.patient}`} target="_blank" rel="noreferrer">{T.card} ›</AppLink> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {g.more > 0 ? <p className="hint">{cnt(g.more, T.more)}</p> : null}
    </details>
  )
}
