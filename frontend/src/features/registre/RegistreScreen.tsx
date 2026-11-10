import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../../components/dialog'
import {
  ARTICLES, CLEANS, CYCLES, DIRECTOR, LAMPS, ME, NOW, PACKS, REGS, ROOMS, SOLUTIONS, STERILIZERS, SUPERVISORS, UVS,
  lampLow, lampOf, lampRest, progOf, sterOf, type Art, type Cycle, type RegKey, type Test,
} from './mock'

/* «Registre» — МАКЕТ этапа 1 (10.11.2026, san-registers). Три раскладки:
   A — «Registre pe file»: вкладки по бланкам, таблица за месяц, запись окном;
   B — «Azi» (под планшет у кресла): плитки оборудования, старт/стоп одной
       кнопкой, лента дня; история и печать — вторым экраном;
   C — «Ca pe hârtie»: слева подшивка бланков, справа таблица колонками бланка
       с первой строкой-вводом.
   Раскладку выбирает `?look=` или `localStorage.dp_reg_look` (пусто — A).
   ⚠️ Ничего не сохраняется: кнопки макета только открывают окна. */

type Look = 'A' | 'B' | 'C'
type Dlg = '' | 'new' | 'finish' | 'fix' | 'clean' | 'sup' | 'uv' | 'print'

const T = {
  title: 'Registre sanitare',
  sub: 'Înregistrările poartă numele celui autentificat și ora programului. Corectarea — înregistrare nouă, cea veche rămâne.',
  month: 'Noiembrie 2026',
  print: 'Tipărește',
  excel: 'Excel',
  newCycle: 'Ciclu nou',
  newClean: 'Curățenie efectuată',
  newUv: 'Pornește lampa',
  running: 'În curs',
  finish: 'Încheie ciclul',
  stop: 'Oprește',
  fix: 'Corectează',
  del: 'Șterge',
  fixed: 'corectată prin nr.',
  fixes: 'corectează nr.',
  signed: 'Semnează',
  signedHint: 'numele și ora le pune programul',
  save: 'Salvează',
  start: 'Pornește ciclul',
  cancel: 'Renunță',
  close: 'Închide',
  equip: 'Echipamente',
  history: 'Istoric și tipar',
  today: 'Azi',
  sup: 'Verificat',
  supWait: 'așteaptă verificarea',
  supDo: 'Am verificat',
  lampChange: 'schimbați lampa',
  hoursLeft: 'ore rămase',
  noBio: 'nu s-a făcut',
  wait: 'în incubare',
}

function useLook(): Look {
  const q = new URLSearchParams(window.location.search).get('look')
  let v = q ?? ''
  if (!v) { try { v = localStorage.getItem('dp_reg_look') ?? '' } catch { v = '' } }
  return v === 'B' || v === 'C' ? v : 'A'
}
const param = (k: string) => new URLSearchParams(window.location.search).get(k) ?? ''
const isDir = () => param('as') === 'dir'

export function RegistreScreen() {
  const look = useLook()
  const [reg, setReg] = useState<RegKey>((['257', '502', '501'].includes(param('r')) ? param('r') : '257') as RegKey)
  const [dlg, setDlg] = useState<Dlg>(param('dlg') as Dlg)
  const [view, setView] = useState(param('v') || 'azi')
  const open = (d: Dlg) => setDlg(d)
  /* подписант читается из шапки оболочки, а она встаёт тем же коммитом —
     второй проход после монтирования (только макет) */
  const [, setTick] = useState(0)
  useEffect(() => { const t = window.setTimeout(() => setTick(1), 0); return () => window.clearTimeout(t) }, [])
  const body = look === 'B' ? (view === 'istoric'
    ? <LookA reg={reg} setReg={setReg} open={open} back={() => setView('azi')} />
    : <LookB open={open} history={(r) => { setReg(r); setView('istoric') }} />)
    : look === 'C' ? <LookC reg={reg} setReg={setReg} open={open} />
      : <LookA reg={reg} setReg={setReg} open={open} />
  return (
    <section className={`dp-react-root rg rg-${look}`} data-look={look}>
      {body}
      <Dialogs dlg={dlg} reg={reg} look={look} close={() => setDlg('')} />
    </section>
  )
}

/* ---------- A: вкладки + таблица ---------- */
function LookA({ reg, setReg, open, back }: { reg: RegKey; setReg: (r: RegKey) => void; open: (d: Dlg) => void; back?: () => void }) {
  const r = REGS.find((x) => x.key === reg)!
  const n = { '257': CYCLES.length, '502': CLEANS.length, '501': UVS.length }
  return (
    <>
      <div className="fcard rg-head">
        {back && <button type="button" className="rg-back" onClick={back}><Icon name="chev-l" /> {T.today}</button>}
        <div className="rg-tabs" role="tablist">
          {REGS.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={reg === x.key}
              className={`rg-tab${reg === x.key ? ' on' : ''}`} onClick={() => setReg(x.key)}>
              {x.short} <small>{x.form}</small> <span className="rg-n">{n[x.key]}</span>
            </button>
          ))}
        </div>
        <div className="rg-tools">
          <span className="rg-month"><button type="button" aria-label="Luna trecută"><Icon name="chev-l" /></button>
            <b>{T.month}</b><button type="button" aria-label="Luna următoare"><Icon name="chev-r" /></button></span>
          <button type="button" className="rg-btn" onClick={() => open('print')}><Icon name="print" /> {T.print}</button>
          <button type="button" className="rg-btn"><Icon name="download" /> {T.excel}</button>
        </div>
      </div>
      <div className="fcard rg-body">
        <div className="rg-bar">
          <div className="rg-ttl"><b>{r.title}</b><small>Formular {r.form} · {r.order} · se păstrează {r.keep}</small></div>
          <button type="button" className="dp-btn pri rg-add" onClick={() => open(reg === '257' ? 'new' : reg === '502' ? 'clean' : 'uv')}>
            <Icon name="plus" /> {reg === '257' ? T.newCycle : reg === '502' ? T.newClean : T.newUv}</button>
        </div>
        <Running reg={reg} open={open} />
        {reg === '257' ? <Table257 /> : reg === '502' ? <Table502 open={open} /> : <Table501 />}
        <p className="hint rg-foot"><Icon name="shield" /> {T.sub}</p>
      </div>
    </>
  )
}

function Running({ reg, open }: { reg: RegKey; open: (d: Dlg) => void }) {
  if (reg === '257') {
    const c = CYCLES.find((x) => x.running)
    if (!c) return null
    const s = sterOf(c.ster); const p = progOf(s, c.prog)
    return (
      <div className="rg-run">
        <span className="rg-dot" /><b>{T.running}: {s.name}</b>
        <span>{p.label} · pornit {c.start} · gata ~12:05</span>
        <span className="rg-prog"><i style={{ width: '49%' }} /></span>
        <button type="button" className="rg-btn pri" onClick={() => open('finish')}><Icon name="check" /> {T.finish}</button>
      </div>
    )
  }
  if (reg === '501') {
    const u = UVS.find((x) => x.running)
    if (!u) return null
    const l = lampOf(u.lamp)
    return (
      <div className="rg-run">
        <span className="rg-dot" /><b>{T.running}: {l.name} nr. {l.nr}</b>
        <span>{l.room} · {u.cond} · pornită {u.on} · 3 h 42 min</span>
        <button type="button" className="rg-btn pri"><Icon name="power" /> {T.stop}</button>
      </div>
    )
  }
  return null
}

function TestMark({ v }: { v: Test | 'wait' }) {
  if (v === 'ok') return <span className="rg-t ok"><Icon name="check" /></span>
  if (v === 'fail') return <span className="rg-t bad"><Icon name="close" /></span>
  if (v === 'wait') return <span className="rg-t wait" title={T.wait}><Icon name="hourglass" /></span>
  return <span className="rg-t none">—</span>
}

function Who({ by, at }: { by: string; at: string }) {
  return <span className="rg-who"><b>{by}</b><small>{at}</small></span>
}

function RowMenu() {
  return (
    <span className="rg-rm">
      <button type="button" className="rg-ib" aria-label={T.fix} title={T.fix}><Icon name="pen" /></button>
      {isDir() && <button type="button" className="rg-ib bad" aria-label={T.del} title={T.del}><Icon name="trash" /></button>}
    </span>
  )
}

function Table257({ numbered }: { numbered?: boolean }) {
  return (
    <div className="rg-scroll">
      <table className="rg-tbl">
        <thead>
          <tr>
            <th rowSpan={2}>Nr.</th><th rowSpan={2}>Data</th><th rowSpan={2}>Sterilizator</th>
            <th colSpan={3}>Articole sterilizate</th><th colSpan={2}>Timpul</th><th colSpan={2}>Regimul</th>
            <th colSpan={3}>Test-control</th><th rowSpan={2}>Semnătura, data</th><th rowSpan={2} />
          </tr>
          <tr>
            <th>Denumirea</th><th>Cant.</th><th>Ambalaj</th><th>Început</th><th>Sfârșit</th>
            <th>bar</th><th>°C</th><th>Biol.</th><th>Term.</th><th>Chim.</th>
          </tr>
          {numbered && <tr className="rg-num">{[...Array(14)].map((_, i) => <th key={i}>{i < 13 ? i + 1 : ''}</th>)}</tr>}
        </thead>
        <tbody>
          {CYCLES.map((c) => <Row257 key={c.nr} c={c} />)}
        </tbody>
      </table>
    </div>
  )
}

function Row257({ c }: { c: Cycle }) {
  const s = sterOf(c.ster)
  const cls = c.fixedBy ? ' old' : c.running ? ' run' : c.chem === 'fail' ? ' fail' : ''
  return (
    <tr className={`rg-row${cls}`}>
      <td className="num">{c.nr}</td>
      <td className="num">{c.date}</td>
      <td><b>{s.name}</b><small>nr. {s.nr}</small></td>
      <td className="rg-arts-c">{c.arts.map((a) => <div key={a.name}>{a.name}</div>)}
        {c.fixedBy ? <em className="rg-fix">{T.fixed} {c.fixedBy}</em> : null}
        {c.fixes ? <em className="rg-fix new">{T.fixes} {c.fixes}: {c.why}</em> : null}</td>
      <td className="num">{c.arts.map((a) => <div key={a.name}>{a.qty}</div>)}</td>
      <td>{c.arts.map((a) => <div key={a.name}>{a.pack}</div>)}</td>
      <td className="num">{c.start}</td>
      <td className="num">{c.running ? <span className="chip info">{T.running}</span> : c.end}</td>
      <td className="num">{c.p}</td>
      <td className="num">{c.t}</td>
      <td><TestMark v={c.bio} /></td><td><TestMark v={c.term} /></td><td><TestMark v={c.chem} /></td>
      <td><Who by={c.by} at={c.at} /></td>
      <td>{!c.running && !c.fixedBy && <RowMenu />}</td>
    </tr>
  )
}

function Table502({ open, numbered }: { open: (d: Dlg) => void; numbered?: boolean }) {
  return (
    <div className="rg-scroll">
      <table className="rg-tbl">
        <thead>
          <tr><th rowSpan={2}>Nr.</th><th rowSpan={2}>Încăperea</th><th rowSpan={2}>Data planificării</th>
            <th rowSpan={2}>Data efectuării</th><th rowSpan={2}>Soluția dezinfectantă (denumire, concentrație, expoziție)</th>
            <th colSpan={2}>A efectuat</th><th colSpan={2}>A supervizat</th><th rowSpan={2} /></tr>
          <tr><th>Numele</th><th>Semnătura</th><th>Numele</th><th>Semnătura</th></tr>
          {numbered && <tr className="rg-num">{[...Array(10)].map((_, i) => <th key={i}>{i < 9 ? i + 1 : ''}</th>)}</tr>}
        </thead>
        <tbody>
          {CLEANS.map((c) => (
            <tr key={c.nr} className="rg-row">
              <td className="num">{c.nr}</td><td><b>{c.room}</b></td>
              <td className="num">{c.plan}</td><td className="num">{c.done}</td><td>{c.sol}</td>
              <td><b>{c.by}</b></td><td><small className="rg-sig">{c.at}</small></td>
              {c.sup ? <><td><b>{c.sup}</b></td><td><small className="rg-sig">{c.supAt}</small></td></>
                : <td colSpan={2}><span className="chip warn">{T.supWait}</span>{' '}
                  <button type="button" className="rg-btn sm" onClick={() => open('sup')}>{T.supDo}</button></td>}
              <td><RowMenu /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Table501({ numbered }: { numbered?: boolean }) {
  return (
    <>
      <div className="rg-lamps">
        {LAMPS.map((l) => (
          <div key={l.id} className={`rg-lamp${lampLow(l) ? ' low' : ''}`}>
            <b>{l.name} nr. {l.nr}</b>
            <small>{l.room} · {l.m3} m³ · din {l.since}</small>
            <span className="rg-prog"><i style={{ width: `${Math.round(100 * l.used / l.hours)}%` }} /></span>
            <small>{lampRest(l)} {T.hoursLeft} din {l.hours}{lampLow(l) ? ` — ${T.lampChange}` : ''}</small>
          </div>
        ))}
      </div>
      <div className="rg-scroll">
        <table className="rg-tbl">
          <thead>
            <tr><th rowSpan={2}>Data</th><th rowSpan={2}>Încăperea iradiată</th><th rowSpan={2}>Condițiile</th>
              <th colSpan={2}>Ora</th><th rowSpan={2}>Durata</th><th rowSpan={2}>Ore rămase</th>
              <th rowSpan={2}>Persoana responsabilă</th><th rowSpan={2}>Semnătura</th><th rowSpan={2} /></tr>
            <tr><th>conectării</th><th>deconectării</th></tr>
            {numbered && <tr className="rg-num">{[...Array(10)].map((_, i) => <th key={i}>{i < 9 ? i + 1 : ''}</th>)}</tr>}
          </thead>
          <tbody>
            {UVS.map((u) => {
              const l = lampOf(u.lamp)
              return (
                <tr key={u.nr} className={`rg-row${u.running ? ' run' : ''}`}>
                  <td className="num">{u.date}</td><td><b>{l.room}</b><small>{l.name} nr. {l.nr}</small></td>
                  <td>{u.cond}</td><td className="num">{u.on}</td>
                  <td className="num">{u.running ? <span className="chip info">{T.running}</span> : u.off}</td>
                  <td className="num">{u.running ? '—' : `${u.min} min`}</td>
                  <td className={`num${u.rest < 50 ? ' bad' : ''}`}>{u.rest}</td>
                  <td><b>{u.by}</b></td><td><small className="rg-sig">{u.at}</small></td>
                  <td>{!u.running && <RowMenu />}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

/* ---------- B: «Azi» у кресла ---------- */
function LookB({ open, history }: { open: (d: Dlg) => void; history: (r: RegKey) => void }) {
  const run = CYCLES.find((c) => c.running)
  return (
    <>
      <div className="fcard rg-head">
        <div className="rg-ttl"><b>{T.today}, 10 noiembrie</b><small>{ME.name} · {ME.role}</small></div>
        <div className="rg-tools">
          <button type="button" className="rg-btn" onClick={() => history('257')}><Icon name="clipboard" /> {T.history}</button>
        </div>
      </div>
      <h3 className="rg-h">Sterilizare <small>257/e</small></h3>
      <div className="rg-tiles">
        {STERILIZERS.map((s) => {
          const busy = run && run.ster === s.id
          return (
            <div key={s.id} className={`fcard rg-tile${busy ? ' busy' : ''}`}>
              <div className="rg-tile-h"><Icon name="hourglass" /><b>{s.name}</b><small>nr. {s.nr} · {s.kind === 'abur' ? 'cu abur' : 'cu aer'}</small></div>
              {busy ? (
                <>
                  <p className="rg-big">{progOf(s, run.prog).label} · pornit {run.start}</p>
                  <span className="rg-prog lg"><i style={{ width: '49%' }} /></span>
                  <p className="hint">rămân ~23 min · {run.arts.map((a) => `${a.name} ${a.qty}`).join(', ')}</p>
                  <button type="button" className="dp-btn pri rg-tap" onClick={() => open('finish')}><Icon name="check" /> {T.finish}</button>
                </>
              ) : (
                <>
                  <p className="rg-big mute">Liber</p>
                  <p className="hint">ultimul ciclu: 07.11 · Aer 180 °C · teste OK</p>
                  <button type="button" className="dp-btn rg-tap" onClick={() => open('new')}><Icon name="play" /> {T.newCycle}</button>
                </>
              )}
            </div>
          )
        })}
      </div>
      <h3 className="rg-h">Lămpi bactericide <small>501/e</small></h3>
      <div className="rg-tiles">
        {LAMPS.map((l) => {
          const on = UVS.find((u) => u.running && u.lamp === l.id)
          return (
            <div key={l.id} className={`fcard rg-tile${on ? ' busy' : ''}${lampLow(l) ? ' low' : ''}`}>
              <div className="rg-tile-h"><Icon name="power" /><b>{l.room}</b><small>{l.name} nr. {l.nr}</small></div>
              {on ? <p className="rg-big">Pornită {on.on} · 3 h 42 min</p> : <p className="rg-big mute">Oprită</p>}
              <p className={`hint${lampLow(l) ? ' bad' : ''}`}>{lampRest(l)} {T.hoursLeft} din {l.hours}{lampLow(l) ? ` — ${T.lampChange}` : ''}</p>
              {on ? <button type="button" className="dp-btn pri rg-tap"><Icon name="power" /> {T.stop}</button>
                : <button type="button" className="dp-btn rg-tap" onClick={() => open('uv')}><Icon name="power" /> {T.newUv}</button>}
            </div>
          )
        })}
      </div>
      <h3 className="rg-h">Curățenie generală <small>502/e</small></h3>
      <div className="fcard rg-plan">
        {ROOMS.map((r) => {
          const due = r.next === NOW.date
          return (
            <div key={r.id} className={`rg-plan-r${due ? ' due' : ''}`}>
              <b>{r.name}</b><small>la {r.every} zile · ultima {r.last}</small>
              <span className={`chip ${due ? 'warn' : 'mute'}`}>{due ? 'azi' : r.next}</span>
              {due ? <button type="button" className="dp-btn pri rg-tap sm" onClick={() => open('clean')}><Icon name="check" /> Efectuată</button> : <span />}
            </div>
          )
        })}
        <div className="rg-plan-r"><b>Sala de sterilizare</b><small>07.11 · Maria Lungu</small>
          <span className="chip warn">{T.supWait}</span>
          <button type="button" className="dp-btn rg-tap sm" onClick={() => open('sup')}>{T.supDo}</button></div>
      </div>
      <h3 className="rg-h">Azi în registre</h3>
      <div className="fcard rg-feed">
        {[['11:20', 'Ciclu nr. 8 pornit · Melag · 134 °C', 'Ana Rusu', 'run'],
          ['09:16', 'Ciclu nr. 7 · Melag · 134 °C · chimic, termic OK · biologic în incubare', 'Ana Rusu', ''],
          ['08:20', 'Lampa Cabinet 1 · 30 min · 38 h rămase', 'Ana Rusu', 'bad'],
          ['08:00', 'Lampa Cabinet 2 pornită · în prezența persoanelor', 'Ana Rusu', 'run']].map(([t, w, b, k]) => (
          <div key={t} className={`rg-feed-r ${k}`}><span className="num">{t}</span><span>{w}</span><small>{b}</small></div>
        ))}
      </div>
    </>
  )
}

/* ---------- C: «ca pe hârtie» ---------- */
function LookC({ reg, setReg, open }: { reg: RegKey; setReg: (r: RegKey) => void; open: (d: Dlg) => void }) {
  const r = REGS.find((x) => x.key === reg)!
  return (
    <div className="rg-c">
      <aside className="fcard rg-binder">
        {REGS.map((x) => (
          <button key={x.key} type="button" className={`rg-bk${reg === x.key ? ' on' : ''}`} onClick={() => setReg(x.key)}>
            <span className="rg-bk-f">{x.form}</span><b>{x.short}</b>
            <small>{x.key === '257' ? '8 înregistrări · 1 în curs' : x.key === '502' ? '4 · 1 neverificată' : '4 · 1 lampă de schimbat'}</small>
          </button>
        ))}
        <AppLink className="rg-bk eq" href="/admin/settings/registre"><Icon name="set" /> {T.equip}</AppLink>
      </aside>
      <div className="fcard rg-paper">
        <div className="rg-paper-h">
          <small>Formular nr. {r.form} · {r.order}</small>
          <b>{r.title.toUpperCase()}</b>
          <div className="rg-tools">
            <span className="rg-month"><button type="button" aria-label="Luna trecută"><Icon name="chev-l" /></button>
              <b>{T.month}</b><button type="button" aria-label="Luna următoare"><Icon name="chev-r" /></button></span>
            <button type="button" className="rg-btn" onClick={() => open('print')}><Icon name="print" /> {T.print}</button>
            <button type="button" className="rg-btn"><Icon name="download" /> {T.excel}</button>
          </div>
        </div>
        {reg === '257' && <InlineRow257 />}
        {reg === '257' ? <Table257 numbered /> : reg === '502' ? <Table502 numbered open={open} /> : <Table501 numbered />}
        <p className="hint rg-foot"><Icon name="shield" /> {T.sub}</p>
      </div>
    </div>
  )
}

function InlineRow257() {
  return (
    <div className="rg-inl">
      <span className="rg-inl-l">Rând nou</span>
      <select className="dp-sel" defaultValue="a1" aria-label="Sterilizator">{STERILIZERS.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
      <select className="dp-sel" defaultValue="p134" aria-label="Program">{STERILIZERS[0]!.programs.map((p) => <option key={p.id} value={p.id}>{p.label}{p.p !== '—' ? ` · ${p.p} bar` : ''}</option>)}</select>
      <select className="dp-sel" defaultValue={ARTICLES[0]} aria-label="Articole">{ARTICLES.map((a) => <option key={a}>{a}</option>)}</select>
      <input className="dp-fld rg-qty" defaultValue="10" aria-label="Cantitatea" />
      <select className="dp-sel" defaultValue="Pungă" aria-label="Ambalaj">{PACKS.map((a) => <option key={a}>{a}</option>)}</select>
      <input className="dp-fld rg-time" defaultValue={NOW.time} aria-label="Început" />
      <button type="button" className="dp-btn pri rg-add"><Icon name="play" /> {T.start}</button>
    </div>
  )
}

/* ---------- окна ---------- */
function Dlg({ open, title, icon, wide, onClose, children, foot }: {
  open: boolean; title: string; icon: Parameters<typeof Icon>[0]['name']; wide?: boolean; onClose: () => void
  children: ReactNode; foot: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { if (open) showDialog(ref.current); else hideDialog(ref.current) }, [open])
  return (
    <dialog ref={ref} className={`rg-dlg${wide ? ' wide' : ''}`} onClose={onClose}>
      <div className="dlg-head"><span><Icon name={icon} /> {title}</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label={T.close}><Icon name="close" /></button></div>
      <div className="rg-dlg-b">{children}</div>
      <div className="rg-dlg-f">{foot}</div>
    </dialog>
  )
}

function Chips<V extends string>({ items, value, label }: { items: readonly V[] | V[]; value: V | V[]; label?: (v: V) => ReactNode }) {
  const on = (v: V) => (Array.isArray(value) ? value.includes(v) : value === v)
  return <div className="rg-chips">{items.map((v) => <button key={v} type="button" className={`rg-chip${on(v) ? ' on' : ''}`}>{label ? label(v) : v}</button>)}</div>
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <div className="rg-f"><span className="rg-fl">{label}</span>{children}{hint && <small className="hint">{hint}</small>}</div>
}

function Signer({ extra }: { extra?: string }) {
  return (
    <div className="rg-signer"><Icon name="user" /><span><b>{T.signed}: {ME.name}</b><small>{ME.role} · ora programului{extra ? ` · ${extra}` : ''}</small></span></div>
  )
}

function Stepper({ v }: { v: number }) {
  return <span className="rg-step"><button type="button" aria-label="minus"><Icon name="minus" /></button><b>{v}</b><button type="button" aria-label="plus"><Icon name="plus" /></button></span>
}

function ArtRows({ arts }: { arts: Art[] }) {
  return (
    <div className="rg-arts">
      {arts.map((a) => (
        <div key={a.name} className="rg-art"><b>{a.name}</b><Stepper v={a.qty} /><Chips items={PACKS} value={a.pack} /></div>
      ))}
      <Chips items={ARTICLES.filter((x) => !arts.some((a) => a.name === x))} value={[]} label={(v) => <><Icon name="plus" /> {v}</>} />
    </div>
  )
}

function Dialogs({ dlg, reg, look, close }: { dlg: Dlg; reg: RegKey; look: Look; close: () => void }) {
  const run = CYCLES.find((c) => c.running)!
  const s = STERILIZERS[0]!
  const wide = look !== 'B'
  return (
    <>
      <Dlg open={dlg === 'new'} title="Ciclu nou de sterilizare · 257/e" icon="play" wide={wide} onClose={close}
        foot={<><Signer /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri rg-tap"><Icon name="play" /> {T.start}</button></>}>
        <Field label="Sterilizator"><Chips items={STERILIZERS.map((x) => x.id)} value="a1" label={(id) => sterOf(id).name} /></Field>
        <Field label="Program (regimul)" hint="presiunea și temperatura vin din program; se pot schimba">
          <Chips items={s.programs.map((p) => p.id)} value="p134" label={(id) => { const p = progOf(s, id); return <>{p.label}<small>{p.p !== '—' ? ` · ${p.p} bar` : ''} · {p.min} min</small></> }} /></Field>
        <Field label="Articole sterilizate"><ArtRows arts={[{ name: 'Instrumentar stomatologic', qty: 10, pack: 'Pungă' }]} /></Field>
        <Field label="Începutul" hint="ora programului — se scrie la „Pornește”"><b className="rg-now num">{NOW.time}</b></Field>
      </Dlg>
      <Dlg open={dlg === 'finish'} title={`Încheie ciclul nr. ${run.nr} · ${sterOf(run.ster).name}`} icon="check" wide={wide} onClose={close}
        foot={<><Signer extra={`sfârșit ${NOW.time}`} /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri rg-tap"><Icon name="check" /> {T.finish}</button></>}>
        <p className="rg-sum">{progOf(sterOf(run.ster), run.prog).label} · {run.p} bar · pornit {run.start} · {run.arts.map((a) => `${a.name} ${a.qty}`).join(', ')}</p>
        <Field label="Test chimic"><Chips items={['ok', 'fail'] as const} value="ok" label={(v) => v === 'ok' ? <><Icon name="check" /> Virat corect</> : <><Icon name="close" /> Nu a virat</>} /></Field>
        <Field label="Test termic"><Chips items={['ok', 'fail', 'none'] as const} value="ok" label={(v) => v === 'ok' ? 'Corect' : v === 'fail' ? 'Incorect' : T.noBio} /></Field>
        <Field label="Test biologic" hint="rezultatul se adaugă după incubare, tot ca înregistrare nouă">
          <Chips items={['none', 'wait', 'ok', 'fail'] as const} value="none" label={(v) => v === 'none' ? T.noBio : v === 'wait' ? 'Pus la incubare' : v === 'ok' ? 'Negativ (steril)' : 'Pozitiv'} /></Field>
        <p className="rg-warn"><Icon name="excl" /> Dacă un test a ieșit greșit, ciclul rămâne în registru marcat roșu: instrumentarul se resterilizează.</p>
      </Dlg>
      <Dlg open={dlg === 'fix'} title="Corectează înregistrarea nr. 3" icon="pen" wide={wide} onClose={close}
        foot={<><Signer /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri"><Icon name="save" /> Salvează corectarea</button></>}>
        <p className="rg-sum">Nr. 3 · 05.11.2026 · Melag · 08:35–09:20 · Ana Rusu 05.11.2026 09:21 — rămâne în registru tăiată, cu trimitere la corectare.</p>
        <Field label="Articole sterilizate"><ArtRows arts={[{ name: 'Instrumentar stomatologic', qty: 15, pack: 'Pungă' }, { name: 'Piese de mână', qty: 3, pack: 'Pungă' }]} /></Field>
        <Field label="Motivul corectării (obligatoriu)"><input className="dp-fld" defaultValue="Piese de mână: 3, nu 4" /></Field>
      </Dlg>
      <Dlg open={dlg === 'clean'} title="Curățenie generală efectuată · 502/e" icon="check" wide={wide} onClose={close}
        foot={<><Signer extra="a efectuat" /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri rg-tap"><Icon name="save" /> {T.save}</button></>}>
        <Field label="Încăperea"><Chips items={ROOMS.map((r) => r.name)} value="Cabinet 1" /></Field>
        <Field label="Data planificării" hint="din planul de curățenie (la 7 zile)"><b className="num">10.11.2026</b></Field>
        <Field label="Soluția dezinfectantă"><Chips items={SOLUTIONS} value={SOLUTIONS[0]!} /></Field>
        <Field label="Cine verifică" hint="verificatorul confirmă cu contul său — numele și ora le pune programul">
          <Chips items={SUPERVISORS} value={DIRECTOR} /></Field>
      </Dlg>
      <Dlg open={dlg === 'sup'} title="Verificarea curățeniei generale" icon="shield" wide={wide} onClose={close}
        foot={<><Signer extra="a supervizat" /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri rg-tap"><Icon name="check" /> {T.supDo}</button></>}>
        <p className="rg-sum">Nr. 4 · Sala de sterilizare · 07.11.2026 · Dezactiv-M 1 % · 30 min · a efectuat Maria Lungu (07.11.2026 18:55)</p>
        <p className="hint">Verifică {DIRECTOR} sau Maria Lungu (asistentă-șefă). Cel care a făcut curățenia nu se poate verifica singur.</p>
      </Dlg>
      <Dlg open={dlg === 'uv'} title="Pornește lampa bactericidă · 501/e" icon="power" wide={wide} onClose={close}
        foot={<><Signer extra="ora conectării" /><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri rg-tap"><Icon name="power" /> {T.newUv}</button></>}>
        <Field label="Lampa"><Chips items={LAMPS.map((l) => l.id)} value="l1" label={(id) => { const l = lampOf(id); return <>{l.room}<small> · {l.name} nr. {l.nr}</small></> }} /></Field>
        <Field label="Condițiile"><Chips items={['fără persoane', 'în prezența persoanelor']} value="fără persoane" /></Field>
        <p className="rg-warn"><Icon name="excl" /> Lampa din Cabinet 1 mai are 38 de ore din 8000 — planificați schimbarea.</p>
        <p className="hint">La „Oprește” programul scrie ora deconectării, durata și orele rămase.</p>
      </Dlg>
      <Dlg open={dlg === 'print'} title="Tipărește registrul" icon="print" onClose={close}
        foot={<><button type="button" className="rg-btn" onClick={close}>{T.cancel}</button>
          <button type="button" className="dp-btn pri"><Icon name="print" /> {T.print}</button></>}>
        <Field label="Registrul"><Chips items={REGS.map((r) => r.key)} value={reg} label={(k) => { const r = REGS.find((x) => x.key === k)!; return <>{r.short}<small> · {r.form}</small></> }} /></Field>
        <Field label="Perioada"><Chips items={['Luna aceasta', 'Luna trecută', 'Alege…']} value="Luna aceasta" /></Field>
        <p className="hint">Foaia are coloanele formularului și, jos, locurile pentru semnătura responsabilului și a conducătorului (L.Ș.).</p>
      </Dlg>
    </>
  )
}
