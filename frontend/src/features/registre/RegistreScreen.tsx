import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError, type ApiResult } from '../../services/api'
import {
  dayLabel, dur, excelUrl, minutesSince, monthLabel, printUrl, regApi,
  type Art, type Bio, type CleanRow, type CycleRow, type RegData, type RegKey, type Test, type UvRow,
} from './registre'

/* «Registre» (10.11.2026, вариант B — слово Олега): санитарные регистры
   257/e (автоклав), 502/e (генеральная уборка), 501/e (УФ-лампы).
   «Azi» — плитки оборудования у кресла: одно касание до нужного окна;
   «Istoric și tipar» — журналы за месяц колонками бланка, лист и Excel.
   Подпись строки (вошедший и время) ставит сервер; исправление — новой
   строкой с причиной; удаляет только директор (право — `can.delete`).
   Экран не живой поверхности: после команды перечитывает `GET /api/registre`
   (без кадра загрузки — прежние данные стоят до ответа). Минуты идущего цикла
   и включённой лампы считает браузер по отметке сервера. */

const T = {
  today: 'Azi',
  history: 'Istoric și tipar',
  regs: { '257': 'Sterilizare', '502': 'Curățenie generală', '501': 'Lămpi bactericide' } as Record<RegKey, string>,
  forms: { '257': '257/e', '502': '502/e', '501': '501/e' } as Record<RegKey, string>,
  titles: {
    '257': 'Registru de evidență a controlului lucrului sterilizatoarelor cu aer, cu aburi (autoclav)',
    '502': 'Registru de evidență a efectuării curățeniei generale',
    '501': 'Registru de evidență a utilizării lămpilor bactericide pentru dezinfecție',
  } as Record<RegKey, string>,
  orders: {
    '257': 'Formular 257/e · aprobat prin Ordinul MS nr. 828 din 31.10.2011',
    '502': 'Formular 502/e · aprobat prin Ordinul MS nr. 630 din 08.08.2016 · se păstrează 3 ani',
    '501': 'Formular 501/e · aprobat prin Ordinul MS nr. 630 din 08.08.2016 · se păstrează 3 ani',
  } as Record<RegKey, string>,
  sub: 'Fiecare înregistrare poartă numele celui autentificat și ora programului. Corectarea — înregistrare nouă, cea veche rămâne.',
  print: 'Tipărește', excel: 'Excel', prevM: 'Luna trecută', nextM: 'Luna următoare',
  newCycle: 'Ciclu nou', finish: 'Încheie ciclul', start: 'Pornește ciclul', running: 'În curs',
  free: 'Liber', lastCycle: 'ultimul ciclu', none: 'încă niciun ciclu',
  uvOn: 'Pornește lampa', uvOff: 'Oprește', lampOff: 'Oprită', lampOnAt: 'Pornită',
  hoursLeft: 'ore rămase din', change: 'schimbați lampa',
  cleanDone: 'Efectuată', due: 'azi', late: 'întârziată', every: 'la', days: 'zile', lastClean: 'ultima', never: 'niciodată',
  wait: 'așteaptă verificarea', supDo: 'Am verificat', supSelf: 'verifică altă persoană',
  bioWait: 'Teste biologice în incubare', bioNeg: 'Negativ (steril)', bioPos: 'Pozitiv',
  feed: 'Azi în registre', feedEmpty: 'Încă nimic azi.',
  fix: 'Corectează', del: 'Șterge', fixed: 'corectată prin nr.', fixes: 'corectează nr.',
  delAsk: (f: string, n: number) => `Ștergeți înregistrarea nr. ${n} din registrul ${f}? Rămâne în baza de date, marcată ca ștearsă; din registru și de pe foaie dispare.`,
  signed: 'Semnează', signedHint: 'numele și ora le pune programul',
  cancel: 'Renunță', save: 'Salvează', close: 'Închide',
  sterilizer: 'Sterilizator', program: 'Program (regimul)', programHint: 'presiunea și temperatura vin din program',
  arts: 'Articole sterilizate', qty: 'Cantitatea',
  chem: 'Test chimic', term: 'Test termic', bio: 'Test biologic', bioHint: 'rezultatul după incubare se scrie la „Azi”',
  testOk: 'Corect', testFail: 'Incorect', notDone: 'nu s-a făcut', bioSet: 'Pus la incubare',
  failWarn: 'Un test greșit rămâne în registru marcat roșu: instrumentarul se resterilizează.',
  startHint: 'Începutul: ora programului, la „Pornește ciclul”.',
  room: 'Încăperea', solution: 'Soluția dezinfectantă', plan: 'Data planificării',
  lamp: 'Lampa', cond: 'Condițiile', fara: 'fără persoane', prezenta: 'în prezența persoanelor',
  notScreened: 'lampa nu este ecranată — numai fără persoane',
  why: 'Motivul corectării (obligatoriu)', startT: 'Începutul', endT: 'Sfârșitul', minutes: 'Durata, minute',
  keep: 'rămâne în registru tăiată, cu trimitere la corectare',
  emptyTitle: 'Registrele nu au încă echipamente',
  emptyHint: 'Directorul adaugă sterilizatoarele, lămpile bactericide și încăperile în Setări › Registre sanitare — din ele se fac butoanele de aici.',
  emptyGo: 'Deschide Setări › Registre sanitare',
  offline: 'Programul nu răspunde. Reîncercați.',
  noRows: '— nicio înregistrare în luna aceasta —',
  equip: 'Echipamente',
  /* 2.14.1 (канарейка 2.14.0): пустой список — не тупик */
  ownArt: 'Alt articol', ownSol: 'Altă soluție', own: 'Adaugă', ownHint: 'se scrie doar în această înregistrare',
  noArts: 'Lista de articole este goală.', noSols: 'Lista de soluții este goală.',
  addIn: 'Adăugați în Setări › Registre sanitare', askDir: 'Directorul le adaugă în Setări › Registre sanitare.',
  missing: 'Încă nu sunt adăugate:', missSter: 'sterilizatoarele (257/e)',
  missLamp: 'lămpile bactericide (501/e)', missRoom: 'încăperile (502/e)',
}

type Dlg =
  | { kind: 'new'; ster: number }
  | { kind: 'finish'; row: CycleRow }
  | { kind: 'clean'; room: number }
  | { kind: 'uv'; lamp: number }
  | { kind: 'fix'; reg: RegKey; row: CycleRow | CleanRow | UvRow }
  | null

type Act = (run: () => Promise<ApiResult<null>>, after?: () => void) => Promise<boolean>

const q = (k: string) => new URLSearchParams(window.location.search).get(k) ?? ''
const short = (ster: string) => ster.split(' nr.')[0] ?? ster

interface Props { navigate?: (url: string) => void }

export function RegistreScreen({ navigate = defaultNavigate }: Props) {
  const [view, setView] = useState<'azi' | 'istoric'>(q('v') === 'istoric' ? 'istoric' : 'azi')
  const [reg, setReg] = useState<RegKey>((['257', '502', '501'].includes(q('r')) ? q('r') : '257') as RegKey)
  const [month, setMonth] = useState(/^\d{4}-\d{2}$/.test(q('m')) ? q('m') : '')
  const load = useCallback((signal: AbortSignal) => regApi.get(month, signal), [month])
  const { state, retry, replace, leaveIfSignedOut } = useLoad<RegData>(load, navigate)
  const [dlg, setDlg] = useState<Dlg>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30000)
    return () => window.clearInterval(t)
  }, [])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  if (state.status === 'loading') return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  const d = state.data

  /** Команда → плашка сервера → перечитать без кадра загрузки. */
  const act: Act = async (run, after) => {
    setBusy(true)
    try {
      const r = await run()
      if (r.text) setToast({ tone: r.tone, text: r.text })
      after?.()
      const fresh = await regApi.get(month)
      replace(fresh.data)
      return true
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return false
      setToast({ tone: 'err', text: err.text || T.offline })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function remove(r: RegKey, id: number) {
    if (!await ask({ title: T.del, text: T.delAsk(T.forms[r], id), danger: true, ok: T.del })) return
    await act(() => regApi.del(r, id))
  }

  const body = d.empty ? <Empty can={d.can.settings} />
    : view === 'azi'
      ? <Azi d={d} now={now} busy={busy} open={setDlg} act={act} history={(r) => { setReg(r); setView('istoric') }} />
      : <History d={d} reg={reg} setReg={setReg} setMonth={setMonth} back={() => setView('azi')} open={setDlg} remove={remove} />
  return (
    <section className="dp-react-root rg rg-B">
      {body}
      <Dialogs d={d} dlg={dlg} busy={busy} close={() => setDlg(null)} act={act} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={() => setToast(null)} />}
    </section>
  )
}

function Empty({ can }: { can: boolean }) {
  return (
    <div className="fcard rg-empty">
      <span className="rg-empty-ico"><Icon name="shield" /></span>
      <b>{T.emptyTitle}</b>
      <p className="hint">{T.emptyHint}</p>
      {can && <AppLink className="rg-btn pri" href="/admin/settings/registre">{T.emptyGo}</AppLink>}
    </div>
  )
}

/* ---------- «Azi» ---------- */
function Azi({ d, now, busy, open, act, history }: {
  d: RegData; now: number; busy: boolean; open: (x: Dlg) => void; act: Act; history: (r: RegKey) => void
}) {
  const bioWait = d.rows['257'].filter((r) => r.bio === 'wait' && !r.fixed_by)
  return (
    <>
      <div className="fcard rg-head">
        <div className="rg-ttl"><b>{T.today}, {dayLabel(d.today)}</b><small>{d.me.name}</small></div>
        <div className="rg-tools">
          {d.can.settings && <AppLink className="rg-btn" href="/admin/settings/registre"><Icon name="set" /> {T.equip}</AppLink>}
          <button type="button" className="rg-btn" onClick={() => history('257')}><Icon name="clipboard" /> {T.history}</button>
        </div>
      </div>

      {(() => {
        /* вид каталога пуст — секции нет вовсе; говорим, ЧЕГО нет и где завести */
        const miss = [!d.sters.length && T.missSter, !d.lamps.length && T.missLamp, !d.rooms.length && T.missRoom].filter(Boolean)
        return miss.length ? <EmptyList text={`${T.missing} ${miss.join(', ')}.`} can={d.can.settings} /> : null
      })()}
      {d.sters.length > 0 && <>
        <h3 className="rg-h">{T.regs['257']} <small>{T.forms['257']}</small></h3>
        <div className="rg-tiles">
          {d.sters.map((s) => {
            const run = s.running
            return (
              <div key={s.id} className={`fcard rg-tile${run ? ' busy' : ''}`} data-ster={s.id}>
                <div className="rg-tile-h"><Icon name="hourglass" /><b>{s.name}</b>
                  <small>{s.nr ? `nr. ${s.nr} · ` : ''}{s.data.type === 'aer' ? 'cu aer' : 'cu abur'}</small></div>
                {run ? (
                  <>
                    <p className="rg-big">{run.program} · pornit {run.start}</p>
                    <p className="hint">{dur(minutesSince(run.started_at, now))} · {run.arts.map((a) => `${a.name} ${a.qty}`).join(', ')}</p>
                    <button type="button" className="dp-btn pri rg-tap" disabled={busy} onClick={() => open({ kind: 'finish', row: run })}>
                      <Icon name="check" /> {T.finish}</button>
                  </>
                ) : (
                  <>
                    <p className="rg-big mute">{T.free}</p>
                    <p className="hint">{s.last ? `${T.lastCycle}: ${s.last.date} ${s.last.end} · ${s.last.program}` : T.none}</p>
                    <button type="button" className="dp-btn rg-tap" disabled={busy} onClick={() => open({ kind: 'new', ster: s.id })}>
                      <Icon name="play" /> {T.newCycle}</button>
                  </>
                )}
              </div>
            )
          })}
        </div>
      </>}

      {bioWait.length > 0 && <>
        <h3 className="rg-h">{T.bioWait} <small>{T.forms['257']}</small></h3>
        <div className="fcard rg-plan">
          {bioWait.map((c) => (
            <div key={c.id} className="rg-plan-r bio" data-bio={c.id}>
              <b>Nr. {c.id} · {short(c.ster)}</b><small>{c.date} {c.start}–{c.end} · {c.program}</small>
              <button type="button" className="dp-btn rg-tap sm" disabled={busy} onClick={() => void act(() => regApi.bio(c.id, 'ok'))}>
                <Icon name="check" /> {T.bioNeg}</button>
              <button type="button" className="dp-btn rg-tap sm" disabled={busy} onClick={() => void act(() => regApi.bio(c.id, 'fail'))}>
                <Icon name="close" /> {T.bioPos}</button>
            </div>
          ))}
        </div>
      </>}

      {d.lamps.length > 0 && <>
        <h3 className="rg-h">{T.regs['501']} <small>{T.forms['501']}</small></h3>
        <div className="rg-tiles">
          {d.lamps.map((l) => (
            <div key={l.id} className={`fcard rg-tile${l.on ? ' busy' : ''}${l.low ? ' low' : ''}`} data-lamp={l.id}>
              <div className="rg-tile-h"><Icon name="power" /><b>{l.room || l.name}</b><small>{l.name}{l.nr ? ` nr. ${l.nr}` : ''}</small></div>
              {l.on ? <p className="rg-big">{T.lampOnAt} {l.on.on} · {dur(minutesSince(l.on.on_at, now))}</p>
                : <p className="rg-big mute">{T.lampOff}</p>}
              <p className="hint lamp-rest">{l.rest} {T.hoursLeft} {l.data.hours}{l.low ? ` — ${T.change}` : ''}</p>
              {l.on
                ? <button type="button" className="dp-btn pri rg-tap" disabled={busy} onClick={() => { const on = l.on; if (on) void act(() => regApi.uvOff(on.id)) }}>
                    <Icon name="power" /> {T.uvOff}</button>
                : <button type="button" className="dp-btn rg-tap" disabled={busy} onClick={() => open({ kind: 'uv', lamp: l.id })}>
                    <Icon name="power" /> {T.uvOn}</button>}
            </div>
          ))}
        </div>
      </>}

      {(d.rooms.length > 0 || d.waiting.length > 0) && <>
        <h3 className="rg-h">{T.regs['502']} <small>{T.forms['502']}</small></h3>
        <div className="fcard rg-plan">
          {d.rooms.map((r) => (
            <div key={r.id} className={`rg-plan-r${r.due ? ' due' : ''}`} data-room={r.id}>
              <b>{r.name}</b>
              <small>{T.every} {r.data.every} {T.days} · {T.lastClean} {r.last || T.never}</small>
              <span className={`chip ${r.late ? 'bad' : r.due ? 'warn' : 'mute'}`}>{r.late ? `${T.late} · ${r.next}` : r.due ? T.due : r.next}</span>
              <button type="button" className={`dp-btn rg-tap sm${r.due ? ' pri' : ''}`} disabled={busy} onClick={() => open({ kind: 'clean', room: r.id })}>
                <Icon name="check" /> {T.cleanDone}</button>
            </div>
          ))}
          {d.waiting.map((w) => {
            const self = w.actor_id !== '' && w.actor_id === d.me.id
            return (
              <div key={`w${w.id}`} className="rg-plan-r wait" data-sup={w.id}>
                <b>{w.room}</b><small>{w.done} · {w.actor} · {w.solution}</small>
                <span className="chip warn">{T.wait}</span>
                <button type="button" className="dp-btn rg-tap sm" disabled={busy || self} title={self ? T.supSelf : ''}
                  onClick={() => void act(() => regApi.sup(w.id))}><Icon name="shield" /> {self ? T.supSelf : T.supDo}</button>
              </div>
            )
          })}
        </div>
      </>}

      <h3 className="rg-h">{T.feed}</h3>
      <div className="fcard rg-feed">
        {d.feed.length ? d.feed.map((x) => <FeedRow key={`${x.reg}-${x.id}`} x={x} />) : <p className="hint">{T.feedEmpty}</p>}
      </div>
    </>
  )
}

function feedLine(x: CycleRow | CleanRow | UvRow): [string, string, string] {
  if (x.reg === '257') {
    const c = x as CycleRow
    const bad = c.chem === 'fail' || c.term === 'fail' || c.bio === 'fail'
    return [c.start, `Nr. ${c.id} · ${short(c.ster)} · ${c.program}${c.open ? ` · ${T.running.toLowerCase()}` : ` · ${c.start}–${c.end}`}`,
      c.open ? 'run' : bad ? 'bad' : '']
  }
  if (x.reg === '501') {
    const u = x as UvRow
    return [u.on, `${u.room || u.lamp} · ${u.cond}${u.open ? ` · ${T.running.toLowerCase()}` : ` · ${u.minutes ?? 0} min`}`, u.open ? 'run' : '']
  }
  const c = x as CleanRow
  return [c.at.slice(-5), `${T.regs['502']} · ${c.room}${c.sup_actor ? ` · verificat ${c.sup_actor}` : ` · ${T.wait}`}`, '']
}

function FeedRow({ x }: { x: CycleRow | CleanRow | UvRow }) {
  const [when, what, cls] = feedLine(x)
  return <div className={`rg-feed-r ${cls}`}><span className="num">{when}</span><span>{what}</span><small>{x.actor}</small></div>
}

/* ---------- «Istoric și tipar» ---------- */
function History({ d, reg, setReg, setMonth, back, open, remove }: {
  d: RegData; reg: RegKey; setReg: (r: RegKey) => void; setMonth: (m: string) => void
  back: () => void; open: (x: Dlg) => void; remove: (r: RegKey, id: number) => Promise<void>
}) {
  const n = d.rows[reg].length
  return (
    <>
      <div className="fcard rg-head">
        <button type="button" className="rg-back" onClick={back}><Icon name="chev-l" /> {T.today}</button>
        <div className="rg-tabs" role="tablist">
          {(['257', '502', '501'] as RegKey[]).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={reg === k} className={`rg-tab${reg === k ? ' on' : ''}`} onClick={() => setReg(k)}>
              {T.regs[k]} <small>{T.forms[k]}</small> <span className="rg-n">{d.rows[k].length}</span>
            </button>
          ))}
        </div>
        <div className="rg-tools">
          <span className="rg-month">
            <button type="button" aria-label={T.prevM} onClick={() => setMonth(d.prev)}><Icon name="chev-l" /></button>
            <b>{monthLabel(d.month)}</b>
            <button type="button" aria-label={T.nextM} onClick={() => setMonth(d.next)}><Icon name="chev-r" /></button>
          </span>
          <AppLink className="rg-btn" href={printUrl(reg, d.month)}><Icon name="print" /> {T.print}</AppLink>
          <AppLink className="rg-btn" href={excelUrl(reg, d.month)}><Icon name="download" /> {T.excel}</AppLink>
        </div>
      </div>
      <div className="fcard rg-body">
        <div className="rg-bar"><div className="rg-ttl"><b>{T.titles[reg]}</b><small>{T.orders[reg]}</small></div></div>
        {!n ? <p className="hint rg-none">{T.noRows}</p>
          : reg === '257' ? <T257 rows={d.rows['257']} can={d.can.delete} open={open} remove={remove} />
            : reg === '502' ? <T502 rows={d.rows['502']} can={d.can.delete} open={open} remove={remove} />
              : <T501 rows={d.rows['501']} can={d.can.delete} open={open} remove={remove} />}
        <p className="hint rg-foot"><Icon name="shield" /> {T.sub}</p>
      </div>
    </>
  )
}

function TestMark({ v }: { v: Test | Bio }) {
  if (v === 'ok') return <span className="rg-t ok" title={T.testOk}><Icon name="check" /></span>
  if (v === 'fail') return <span className="rg-t bad" title={T.testFail}><Icon name="close" /></span>
  if (v === 'wait') return <span className="rg-t wait" title={T.bioSet}><Icon name="hourglass" /></span>
  return <span className="rg-t none">—</span>
}

function FixNote({ r }: { r: { fixed_by: number | null; fixes: number | null; why: string } }) {
  return <>
    {r.fixed_by ? <em className="rg-fix">{T.fixed} {r.fixed_by}</em> : null}
    {r.fixes ? <em className="rg-fix new">{T.fixes} {r.fixes}: {r.why}</em> : null}
  </>
}

function RowActs({ reg, r, closed, can, open, remove }: {
  reg: RegKey; r: CycleRow | CleanRow | UvRow; closed: boolean; can: boolean
  open: (x: Dlg) => void; remove: (r: RegKey, id: number) => Promise<void>
}) {
  return (
    <span className="rg-rm">
      {closed && !r.fixed_by && <button type="button" className="rg-ib" aria-label={`${T.fix} nr. ${r.id}`} title={T.fix}
        onClick={() => open({ kind: 'fix', reg, row: r })}><Icon name="pen" /></button>}
      {can && <button type="button" className="rg-ib bad" aria-label={`${T.del} nr. ${r.id}`} title={T.del}
        onClick={() => void remove(reg, r.id)}><Icon name="trash" /></button>}
    </span>
  )
}

interface TProps<R> { rows: R[]; can: boolean; open: (x: Dlg) => void; remove: (r: RegKey, id: number) => Promise<void> }

function T257({ rows, can, open, remove }: TProps<CycleRow>) {
  return (
    <div className="rg-scroll">
      <table className="rg-tbl">
        <thead>
          <tr><th rowSpan={2}>Nr.</th><th rowSpan={2}>Data</th><th rowSpan={2}>Sterilizator</th>
            <th colSpan={3}>Articole sterilizate</th><th colSpan={2}>Timpul</th><th colSpan={2}>Regimul</th>
            <th colSpan={3}>Test-control</th><th rowSpan={2}>Semnătura, data</th><th rowSpan={2} /></tr>
          <tr><th>Denumirea</th><th>Cant.</th><th>Ambalaj</th><th>Început</th><th>Sfârșit</th>
            <th>bar</th><th>°C</th><th>Biol.</th><th>Term.</th><th>Chim.</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const bad = c.chem === 'fail' || c.term === 'fail' || c.bio === 'fail'
            return (
              <tr key={c.id} className={`rg-row${c.fixed_by ? ' old' : c.open ? ' run' : bad ? ' fail' : ''}`} data-row={c.id}>
                <td className="num">{c.id}</td><td className="num">{c.date}</td>
                <td><b>{short(c.ster)}</b><small>{c.program}</small></td>
                <td className="rg-arts-c">{c.arts.map((a, i) => <div key={i}>{a.name}</div>)}<FixNote r={c} /></td>
                <td className="num">{c.arts.map((a, i) => <div key={i}>{a.qty}</div>)}</td>
                <td>{c.arts.map((a, i) => <div key={i}>{a.pack}</div>)}</td>
                <td className="num">{c.start}</td>
                <td className="num">{c.open ? <span className="chip info">{T.running}</span> : c.end}</td>
                <td className="num">{c.pressure || '—'}</td><td className="num">{c.temp || '—'}</td>
                <td><TestMark v={c.bio} /></td><td><TestMark v={c.term} /></td><td><TestMark v={c.chem} /></td>
                <td><span className="rg-who"><b>{c.actor}</b><small>{c.at}</small>
                  {c.end_actor && c.end_actor !== c.actor ? <small>încheiat: {c.end_actor}</small> : null}</span></td>
                <td><RowActs reg="257" r={c} closed={!c.open} can={can} open={open} remove={remove} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function T502({ rows, can, open, remove }: TProps<CleanRow>) {
  return (
    <div className="rg-scroll">
      <table className="rg-tbl">
        <thead>
          <tr><th rowSpan={2}>Nr.</th><th rowSpan={2}>Încăperea</th><th rowSpan={2}>Data planificării</th>
            <th rowSpan={2}>Data efectuării</th><th rowSpan={2}>Soluția dezinfectantă</th>
            <th colSpan={2}>A efectuat</th><th colSpan={2}>A supervizat</th><th rowSpan={2} /></tr>
          <tr><th>Numele</th><th>Semnătura</th><th>Numele</th><th>Semnătura</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} className={`rg-row${c.fixed_by ? ' old' : ''}`} data-row={c.id}>
              <td className="num">{c.id}</td><td><b>{c.room}</b><FixNote r={c} /></td>
              <td className="num">{c.plan}</td><td className="num">{c.done}</td><td>{c.solution}</td>
              <td><b>{c.actor}</b></td><td><small className="rg-sig">{c.at}</small></td>
              {c.sup_actor ? <><td><b>{c.sup_actor}</b></td><td><small className="rg-sig">{c.sup_at}</small></td></>
                : <td colSpan={2}><span className="chip warn">{T.wait}</span></td>}
              <td><RowActs reg="502" r={c} closed can={can} open={open} remove={remove} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function T501({ rows, can, open, remove }: TProps<UvRow>) {
  return (
    <div className="rg-scroll">
      <table className="rg-tbl">
        <thead>
          <tr><th rowSpan={2}>Nr.</th><th rowSpan={2}>Data</th><th rowSpan={2}>Încăperea iradiată</th><th rowSpan={2}>Condițiile</th>
            <th colSpan={2}>Ora</th><th rowSpan={2}>Durata</th><th rowSpan={2}>Ore rămase</th>
            <th rowSpan={2}>Persoana responsabilă</th><th rowSpan={2}>Semnătura</th><th rowSpan={2} /></tr>
          <tr><th>conectării</th><th>deconectării</th></tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.id} className={`rg-row${u.fixed_by ? ' old' : u.open ? ' run' : ''}`} data-row={u.id}>
              <td className="num">{u.id}</td><td className="num">{u.date}</td>
              <td><b>{u.room || u.lamp}</b><small>{u.lamp}</small><FixNote r={u} /></td>
              <td>{u.cond}</td><td className="num">{u.on}</td>
              <td className="num">{u.open ? <span className="chip info">{T.running}</span> : u.off}</td>
              <td className="num">{u.minutes ? `${u.minutes} min` : '—'}</td>
              <td className="num">{u.rest ?? '—'}</td>
              <td><b>{u.actor}</b>{u.off_actor && u.off_actor !== u.actor ? <small>oprit: {u.off_actor}</small> : null}</td>
              <td><small className="rg-sig">{u.at}</small></td>
              <td><RowActs reg="501" r={u} closed={!u.open} can={can} open={open} remove={remove} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ---------- окна ---------- */
function Dlg({ open, title, icon, onClose, children, foot }: {
  open: boolean; title: string; icon: Parameters<typeof Icon>[0]['name']; onClose: () => void
  children: ReactNode; foot: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { if (open) showDialog(ref.current); else hideDialog(ref.current) }, [open])
  return (
    <dialog ref={ref} className="rg-dlg wide" onClose={onClose}>
      <div className="dlg-head"><span><Icon name={icon} /> {title}</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label={T.close}><Icon name="close" /></button></div>
      {open && <div className="rg-dlg-b">{children}</div>}
      <div className="rg-dlg-f">{foot}</div>
    </dialog>
  )
}

function Chips<V extends string | number>({ items, value, label, onPick, off }: {
  items: readonly V[]; value: V | null; label: (v: V) => ReactNode; onPick: (v: V) => void; off?: (v: V) => boolean
}) {
  return (
    <div className="rg-chips">
      {items.map((v) => (
        <button key={String(v)} type="button" className={`rg-chip${value === v ? ' on' : ''}`} aria-pressed={value === v}
          disabled={off?.(v)} onClick={() => onPick(v)}>{label(v)}</button>
      ))}
    </div>
  )
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string | undefined }) {
  return <div className="rg-f"><span className="rg-fl">{label}</span>{children}{hint && <small className="hint">{hint}</small>}</div>
}

function Signer({ name }: { name: string }) {
  return <div className="rg-signer"><Icon name="user" /><span><b>{T.signed}: {name}</b><small>{T.signedHint}</small></span></div>
}

/** Пустой список каталога: что делать и куда идти (ссылка — только с правом). */
function EmptyList({ text, can }: { text: string; can: boolean }) {
  return (
    <p className="rg-warn rg-empty-list"><Icon name="info" /><span>{text}{' '}
      {can ? <AppLink href="/admin/settings/registre">{T.addIn}</AppLink> : T.askDir}</span></p>
  )
}

/** Своё слово прямо в окне: только в эту запись, в каталог не попадает.
 *  Длина — как у сервера (`core/registre.NAME_MAX` режет 120, здесь 80). */
function OwnText({ label, onAdd }: { label: string; onAdd: (v: string) => void }) {
  const [v, setV] = useState('')
  const t = v.replace(/\s+/g, ' ').trim()
  return (
    <div className="rg-own">
      <input className="dp-fld" aria-label={label} placeholder={label} value={v} maxLength={80}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && t) { e.preventDefault(); onAdd(t); setV('') } }} />
      <button type="button" className="rg-btn" disabled={!t} onClick={() => { onAdd(t); setV('') }}><Icon name="plus" /> {T.own}</button>
    </div>
  )
}

function ArtsEdit({ arts, set, catalog, packs, can }: {
  arts: Art[]; set: (a: Art[]) => void; catalog: string[]; packs: string[]; can: boolean
}) {
  const upd = (i: number, p: Partial<Art>) => set(arts.map((a, j) => (j === i ? { ...a, ...p } : a)))
  const left = catalog.filter((x) => !arts.some((a) => a.name === x))
  const add = (name: string) => {
    const i = arts.findIndex((a) => a.name === name)
    if (i >= 0) upd(i, { qty: Math.min(999, (arts[i]?.qty ?? 0) + 1) })
    else set([...arts, { name, qty: 1, pack: packs[0] ?? '' }])
  }
  return (
    <div className="rg-arts">
      {!catalog.length && <EmptyList text={T.noArts} can={can} />}
      {arts.map((a, i) => (
        <div key={a.name} className="rg-art">
          <b>{a.name}</b>
          <span className="rg-step">
            <button type="button" aria-label={a.qty > 1 ? 'minus' : T.del}
              onClick={() => (a.qty > 1 ? upd(i, { qty: a.qty - 1 }) : set(arts.filter((_, j) => j !== i)))}>
              <Icon name={a.qty > 1 ? 'minus' : 'trash'} /></button>
            <input inputMode="numeric" aria-label={T.qty} value={a.qty}
              onChange={(e) => { const n = Number(e.target.value.replace(/\D/g, '')); upd(i, { qty: Math.min(999, Math.max(1, n || 1)) }) }} />
            <button type="button" aria-label="plus" onClick={() => upd(i, { qty: Math.min(999, a.qty + 1) })}><Icon name="plus" /></button>
          </span>
          {packs.length > 0 && <Chips items={packs} value={a.pack} label={(v) => v} onPick={(v) => upd(i, { pack: v })} />}
        </div>
      ))}
      {left.length > 0 && <Chips items={left} value={null} label={(v) => <><Icon name="plus" /> {v}</>} onPick={add} />}
      <OwnText label={T.ownArt} onAdd={add} />
      <small className="hint">{T.ownArt}: {T.ownHint}</small>
    </div>
  )
}

/** Раствор: кнопки каталога + свой раствор словом (только в эту запись). */
function SolPick({ d, sol, set }: { d: RegData; sol: string | null; set: (v: string) => void }) {
  const own = sol && !d.solutions.includes(sol) ? sol : null
  return (
    <>
      {!d.solutions.length && <EmptyList text={T.noSols} can={d.can.settings} />}
      <Chips items={own ? [...d.solutions, own] : d.solutions} value={sol} label={(v) => v} onPick={set} />
      <OwnText label={T.ownSol} onAdd={set} />
    </>
  )
}

function Dialogs({ d, dlg, busy, close, act }: { d: RegData; dlg: Dlg; busy: boolean; close: () => void; act: Act }) {
  return (
    <>
      <NewCycle d={d} dlg={dlg?.kind === 'new' ? dlg : null} busy={busy} close={close} act={act} />
      <Finish d={d} dlg={dlg?.kind === 'finish' ? dlg : null} busy={busy} close={close} act={act} />
      <Clean d={d} dlg={dlg?.kind === 'clean' ? dlg : null} busy={busy} close={close} act={act} />
      <UvOn d={d} dlg={dlg?.kind === 'uv' ? dlg : null} busy={busy} close={close} act={act} />
      <Fix d={d} dlg={dlg?.kind === 'fix' ? dlg : null} busy={busy} close={close} act={act} />
    </>
  )
}

interface DProps<X> { d: RegData; dlg: X | null; busy: boolean; close: () => void; act: Act }

function NewCycle({ d, dlg, busy, close, act }: DProps<{ kind: 'new'; ster: number }>) {
  const [ster, setSter] = useState<number | null>(null)
  const [prog, setProg] = useState(0)
  const [arts, setArts] = useState<Art[]>([])
  const [seen, setSeen] = useState<typeof dlg>(null)
  if (dlg !== seen) {
    setSeen(dlg)
    if (dlg) {
      setSter(dlg.ster); setProg(0)
      setArts(d.articles[0] ? [{ name: d.articles[0], qty: 1, pack: d.packs[0] ?? '' }] : [])
    }
  }
  const s = d.sters.find((x) => x.id === ster)
  const progs = s?.data.programs ?? []
  return (
    <Dlg open={!!dlg} title={`${T.newCycle} · 257/e`} icon="play" onClose={close}
      foot={<><Signer name={d.me.name} /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
        <button type="button" className="dp-btn pri rg-tap" disabled={busy || !s || !arts.length}
          onClick={() => { if (s) void act(() => regApi.start({ ster_id: s.id, program: prog, arts }), close) }}>
          <Icon name="play" /> {T.start}</button></>}>
      <Field label={T.sterilizer}>
        <Chips items={d.sters.map((x) => x.id)} value={ster} label={(id) => d.sters.find((x) => x.id === id)?.name ?? ''}
          off={(id) => !!d.sters.find((x) => x.id === id)?.running} onPick={(id) => { setSter(id); setProg(0) }} /></Field>
      <Field label={T.program} hint={T.programHint}>
        <Chips items={progs.map((_, i) => i)} value={prog} onPick={setProg}
          label={(i) => {
            const x = progs[i]
            return x ? <>{x.label}<small>{x.pressure ? ` · ${x.pressure} bar` : ''}{x.min ? ` · ${x.min} min` : ''}</small></> : ''
          }} /></Field>
      <Field label={T.arts}><ArtsEdit arts={arts} set={setArts} catalog={d.articles} packs={d.packs} can={d.can.settings} /></Field>
      <p className="hint">{T.startHint}</p>
    </Dlg>
  )
}

function TestChips({ value, set, bio }: { value: string; set: (v: string) => void; bio?: boolean }) {
  const items = bio ? ['', 'wait', 'ok', 'fail'] : ['ok', 'fail', '']
  const word: Record<string, ReactNode> = bio
    ? { '': T.notDone, wait: T.bioSet, ok: T.bioNeg, fail: T.bioPos }
    : { ok: <><Icon name="check" /> {T.testOk}</>, fail: <><Icon name="close" /> {T.testFail}</>, '': T.notDone }
  return <Chips items={items} value={value} label={(v) => word[v]} onPick={set} />
}

function Finish({ d, dlg, busy, close, act }: DProps<{ kind: 'finish'; row: CycleRow }>) {
  const [chem, setChem] = useState('ok')
  const [term, setTerm] = useState('ok')
  const [bio, setBio] = useState('')
  const [seen, setSeen] = useState<typeof dlg>(null)
  if (dlg !== seen) { setSeen(dlg); setChem('ok'); setTerm('ok'); setBio('') }
  const r = dlg?.row
  const bad = chem === 'fail' || term === 'fail' || bio === 'fail'
  return (
    <Dlg open={!!dlg} title={r ? `${T.finish} nr. ${r.id} · ${short(r.ster)}` : T.finish} icon="check" onClose={close}
      foot={<><Signer name={d.me.name} /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
        <button type="button" className="dp-btn pri rg-tap" disabled={busy || !r}
          onClick={() => { if (r) void act(() => regApi.finish(r.id, { chem: chem as Test, term: term as Test, bio: bio as Bio }), close) }}>
          <Icon name="check" /> {T.finish}</button></>}>
      {r && <p className="rg-sum">{r.program} · pornit {r.start} · {r.arts.map((a) => `${a.name} ${a.qty}`).join(', ')}</p>}
      <Field label={T.chem}><TestChips value={chem} set={setChem} /></Field>
      <Field label={T.term}><TestChips value={term} set={setTerm} /></Field>
      <Field label={T.bio} hint={T.bioHint}><TestChips value={bio} set={setBio} bio /></Field>
      {bad && <p className="rg-warn"><Icon name="excl" /> {T.failWarn}</p>}
    </Dlg>
  )
}

function Clean({ d, dlg, busy, close, act }: DProps<{ kind: 'clean'; room: number }>) {
  const [room, setRoom] = useState<number | null>(null)
  const [sol, setSol] = useState<string | null>(null)
  const [seen, setSeen] = useState<typeof dlg>(null)
  if (dlg !== seen) { setSeen(dlg); if (dlg) { setRoom(dlg.room); setSol(d.solutions[0] ?? null) } }
  const r = d.rooms.find((x) => x.id === room)
  return (
    <Dlg open={!!dlg} title={`${T.regs['502']} ${T.cleanDone.toLowerCase()} · 502/e`} icon="check" onClose={close}
      foot={<><Signer name={d.me.name} /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
        <button type="button" className="dp-btn pri rg-tap" disabled={busy || !r || !sol}
          onClick={() => { if (r && sol) void act(() => regApi.clean({ room_id: r.id, solution: sol }), close) }}>
          <Icon name="save" /> {T.save}</button></>}>
      <Field label={T.room}><Chips items={d.rooms.map((x) => x.id)} value={room} label={(id) => d.rooms.find((x) => x.id === id)?.name ?? ''} onPick={setRoom} /></Field>
      {r && <Field label={T.plan}><b className="num">{r.next}</b></Field>}
      <Field label={T.solution}><SolPick d={d} sol={sol} set={setSol} /></Field>
    </Dlg>
  )
}

function UvOn({ d, dlg, busy, close, act }: DProps<{ kind: 'uv'; lamp: number }>) {
  const [lamp, setLamp] = useState<number | null>(null)
  const [cond, setCond] = useState<'fara' | 'prezenta'>('fara')
  const [seen, setSeen] = useState<typeof dlg>(null)
  if (dlg !== seen) { setSeen(dlg); if (dlg) { setLamp(dlg.lamp); setCond('fara') } }
  const l = d.lamps.find((x) => x.id === lamp)
  return (
    <Dlg open={!!dlg} title={`${T.uvOn} · 501/e`} icon="power" onClose={close}
      foot={<><Signer name={d.me.name} /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
        <button type="button" className="dp-btn pri rg-tap" disabled={busy || !l}
          onClick={() => { if (l) void act(() => regApi.uvOn({ lamp_id: l.id, cond }), close) }}>
          <Icon name="power" /> {T.uvOn}</button></>}>
      <Field label={T.lamp}>
        <Chips items={d.lamps.map((x) => x.id)} value={lamp} off={(id) => !!d.lamps.find((x) => x.id === id)?.on}
          label={(id) => {
            const x = d.lamps.find((y) => y.id === id)
            return x ? <>{x.room || x.name}<small> · {x.name}{x.nr ? ` nr. ${x.nr}` : ''}</small></> : ''
          }}
          onPick={(id) => { setLamp(id); if (!d.lamps.find((x) => x.id === id)?.data.screened) setCond('fara') }} /></Field>
      <Field label={T.cond} hint={l && !l.data.screened ? T.notScreened : undefined}>
        <Chips items={['fara', 'prezenta'] as const} value={cond} label={(v) => T[v]} onPick={setCond}
          off={(v) => v === 'prezenta' && !l?.data.screened} /></Field>
      {l?.low && <p className="rg-warn"><Icon name="excl" /> {l.room || l.name}: {l.rest} {T.hoursLeft} {l.data.hours} — {T.change}.</p>}
    </Dlg>
  )
}

function Fix({ d, dlg, busy, close, act }: DProps<{ kind: 'fix'; reg: RegKey; row: CycleRow | CleanRow | UvRow }>) {
  const [why, setWhy] = useState('')
  const [arts, setArts] = useState<Art[]>([])
  const [chem, setChem] = useState('')
  const [term, setTerm] = useState('')
  const [bio, setBio] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [sol, setSol] = useState<string | null>(null)
  const [minutes, setMinutes] = useState('')
  const [seen, setSeen] = useState<typeof dlg>(null)
  if (dlg !== seen) {
    setSeen(dlg); setWhy('')
    if (dlg?.reg === '257') {
      const c = dlg.row as CycleRow
      setArts(c.arts); setChem(c.chem); setTerm(c.term); setBio(c.bio); setStart(c.start); setEnd(c.end)
    } else if (dlg?.reg === '502') setSol((dlg.row as CleanRow).solution)
    else if (dlg?.reg === '501') setMinutes(String((dlg.row as UvRow).minutes ?? ''))
  }
  const r = dlg?.row
  function body(): Record<string, unknown> {
    if (dlg?.reg === '257') return { why, arts, chem, term, bio, start, end }
    if (dlg?.reg === '502') return { why, solution: sol }
    return { why, minutes: Number(minutes) }
  }
  return (
    <Dlg open={!!dlg} title={r && dlg ? `${T.fix} nr. ${r.id} · ${T.forms[dlg.reg]}` : T.fix} icon="pen" onClose={close}
      foot={<><Signer name={d.me.name} /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
        <button type="button" className="dp-btn pri" disabled={busy || !r || !why.trim()}
          onClick={() => { if (r && dlg) void act(() => regApi.fix(dlg.reg, r.id, body()), close) }}>
          <Icon name="save" /> {T.save}</button></>}>
      {r && <p className="rg-sum">Nr. {r.id} · {r.actor} {r.at} — {T.keep}.</p>}
      {dlg?.reg === '257' && <>
        <Field label={T.arts}><ArtsEdit arts={arts} set={setArts} catalog={d.articles} packs={d.packs} can={d.can.settings} /></Field>
        <div className="rg-two">
          <Field label={T.startT}><input className="dp-fld" type="time" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label={T.endT}><input className="dp-fld" type="time" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        <Field label={T.chem}><TestChips value={chem} set={setChem} /></Field>
        <Field label={T.term}><TestChips value={term} set={setTerm} /></Field>
        <Field label={T.bio}><TestChips value={bio} set={setBio} bio /></Field>
      </>}
      {dlg?.reg === '502' && <Field label={T.solution}><SolPick d={d} sol={sol} set={setSol} /></Field>}
      {dlg?.reg === '501' && <Field label={T.minutes}><input className="dp-fld rg-min" inputMode="numeric" value={minutes}
        onChange={(e) => setMinutes(e.target.value.replace(/\D/g, '').slice(0, 4))} /></Field>}
      <Field label={T.why}><input className="dp-fld" value={why} maxLength={200} onChange={(e) => setWhy(e.target.value)} /></Field>
    </Dlg>
  )
}
