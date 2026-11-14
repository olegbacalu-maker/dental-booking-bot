import { useCallback, useRef, useState } from 'react'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { dmy, num, stockApi, type ImCheck, type ImHome, type ImOpts, type ImRow } from './stock'
import { useBindRetry, useStockCtx } from './StockScreen'

/* Импорт каталога и начальных остатков — по образцу импорта пациентов: файл остаётся в браузере и уходит телом
   каждого запроса; разбор и проверка — на сервере, экран хранит только выбор человека и последний ответ. */

type Step = 'file' | 'cols' | 'check' | 'done'

const ACT: Record<ImRow['act'], string> = { new: 'nou', exists: 'există — se sare', merged: 'unit cu un rând de mai sus', error: 'greșeală' }

export function ImportView() {
  const { navigate, say, refresh, go } = useStockCtx()
  const load = useCallback((signal: AbortSignal) => stockApi.importHome(signal), [])
  const { state, retry } = useLoad<ImHome>(load, navigate)
  useBindRetry(retry)
  const fileRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<Step>('file')
  const [file, setFile] = useState<File | null>(null)
  const [opts, setOpts] = useState<ImOpts>({})
  const [check, setCheck] = useState<ImCheck | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [done, setDone] = useState<{ id: number; created: number; rests: number; skipped: number } | null>(null)

  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  if (state.status !== 'ready') return <div className="fcard rg-body" aria-busy="true" />
  const home = state.data

  async function verify(f: File, o: ImOpts, to: Step) {
    setBusy(true)
    setErr('')
    try {
      const r = await stockApi.importCheck(f, f.name, o)
      setCheck(r.data)
      setOpts({ ...o, sheet: r.data.opts.sheet, header: r.data.opts.header, cols: r.data.opts.cols })
      setStep(to)
    } catch (e) {
      setErr(asApiError(e).text || 'Fișierul nu s-a citit.')
    } finally {
      setBusy(false)
    }
  }
  function pick(f: File | undefined) {
    if (!f) return
    setFile(f)
    setOpts({})
    void verify(f, {}, 'cols')
  }
  async function run() {
    if (!file || !check) return
    setBusy(true)
    try {
      const r = await stockApi.importRun(file, file.name, opts, check.token)
      setDone(r.data)
      setStep('done')
      refresh()
      retry()
    } catch (e) {
      const er = asApiError(e)
      setErr(er.text || 'Importul nu s-a făcut.')
      if (er.code === 'stock_import_stale') void verify(file, opts, 'check')
    } finally {
      setBusy(false)
    }
  }
  async function undo(id: number, name: string) {
    if (!(await ask({ text: `Anulați importul „${name}”? Materialele create de el și resturile lor de pornire ies din stoc.`, danger: true, ok: 'Anulează importul' }))) return
    try {
      await stockApi.importUndo(id)
      refresh()
      retry()
      if (done?.id === id) { setDone(null); setStep('file'); setFile(null) }
      say('Importul anulat.')
    } catch (e) { say(asApiError(e).text || 'Nu se poate anula.', 'err') }
  }
  const restart = () => { setStep('file'); setFile(null); setCheck(null); setOpts({}); setErr('') }
  const choose = (line: number, c: 'same' | 'new') => {
    if (!file) return
    const next = { ...opts, choices: { ...(opts.choices ?? {}), [String(line)]: c } }
    void verify(file, next, 'check')
  }
  const at = step === 'file' ? 0 : step === 'cols' ? 1 : 2
  const fieldOf = (i: number) => opts.cols?.[String(i)] ?? check?.columns.find((c) => c.index === i)?.field ?? ''
  const groups: [string, ImRow[]][] = check ? [
    ['Se importă', check.rows.filter((r) => r.act === 'new' || r.act === 'merged')],
    ['Există deja în catalog — se sar (restul se corectează la inventariere)', check.rows.filter((r) => r.act === 'exists')],
    ['Cu greșeli — se sar', check.rows.filter((r) => r.act === 'error')],
  ] : []

  return (
    <div className="pi st-imp" aria-busy={busy || undefined}>
      <ol className="pi-steps" aria-label="Pași">
        {['Fișier', 'Coloane', 'Verificare'].map((label, i) => (
          <li key={label} className={i === at ? 'on' : i < at ? 'past' : ''} aria-current={i === at ? 'step' : undefined}><span>{i + 1}</span>{label}</li>
        ))}
      </ol>
      <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
      {err && <div className="banner warn" role="alert">{err}</div>}

      {step === 'file' && (
        <div className="fcard pi-pick">
          <span className="rc-empty-ico"><Icon name="upload" /></span>
          <p className="hint">Aduceți catalogul materialelor și ce e acum pe raft dintr-un tabel Excel sau CSV — o singură dată, la început.
            Nimic nu se scrie în stoc până la ultimul pas, iar importul se poate anula.</p>
          {home.remote ? <div className={`banner ${home.remote.tone}`} role="status">{home.remote.text}</div> : (
            <button type="button" className="dp-btn pri" disabled={busy} onClick={() => fileRef.current?.click()}><Icon name="upload" /> Alege fișierul (.xlsx sau .csv)</button>
          )}
          <p className="hint">Primul rând — antetul: Denumire, Categorie, UM, Ambalaj, Buc./g în ambalaj, Stoc, Stoc minim, Preț, Valabil până la, Lot, Furnizor, Raft.
            Cel mult {num(home.limits.rows * 1000, 0)} de rânduri.</p>
        </div>
      )}

      {file && check && step !== 'file' && step !== 'done' && (
        <div className="fcard pi-file"><Icon name="file" /><span><b>{check.file.name}</b>{check.file.sheets.length > 1 ? ` · ${check.file.sheets.length} foi` : ''} · {check.rows.length} rânduri</span>
          <button type="button" className="rc-btn" disabled={busy} onClick={() => fileRef.current?.click()}><Icon name="upload" /> Alt fișier</button></div>
      )}

      {check && step === 'cols' && (
        <div className="fcard pi-cols">
          <div className="pi-opts">
            {check.file.sheets.length > 1 && (
              <label>Foaia
                <select className="dp-sel" value={opts.sheet ?? 0} disabled={busy} onChange={(e) => { const o = { ...opts, sheet: Number(e.target.value), cols: {} }; void verify(file!, o, 'cols') }}>
                  {check.file.sheets.map((s, i) => <option key={s.name} value={i}>{s.name} ({s.rows})</option>)}
                </select>
              </label>
            )}
            <label>Antetul este pe rândul
              <input type="number" className="pi-num" min={0} max={9999} value={opts.header ?? 1} disabled={busy}
                onChange={(e) => { const o = { ...opts, header: Number(e.target.value) || 0, cols: {} }; void verify(file!, o, 'cols') }} />
            </label>
          </div>
          <p className="hint">Deasupra fiecărei coloane alegeți ce conține. Ce a recunoscut programul este deja ales. Restul pe raft — în unitatea de consum (carpule, grame, ml), nu în ambalaje.</p>
          <div className="pi-scroll">
            <table className="pi-table pi-preview">
              <thead>
                <tr><th>Rând</th>{check.columns.map((c) => (
                  <th key={c.index} className={fieldOf(c.index) ? 'on' : ''}>
                    <select className="dp-sel" aria-label={`Ce conține coloana ${c.letter}`} value={fieldOf(c.index)} disabled={busy}
                      onChange={(e) => {
                        const cols: Record<string, string> = { ...(opts.cols ?? check.opts.cols) }
                        for (const [k, v] of Object.entries(cols)) if (v === e.target.value && e.target.value) cols[k] = ''
                        cols[String(c.index)] = e.target.value
                        void verify(file!, { ...opts, cols }, 'cols')
                      }}>
                      <option value="">— nu se importă —</option>
                      {home.fields.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                    </select>
                    <small>{c.title || c.letter}</small>
                  </th>
                ))}</tr>
              </thead>
              <tbody>
                {check.rows.slice(0, 6).map((r) => (
                  <tr key={r.line}><td className="pi-ln">{r.line}</td>{check.columns.map((c) => <td key={c.index} className={fieldOf(c.index) ? '' : 'off'}>{cell(r, fieldOf(c.index))}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pi-acts">
            {!check.ready && <span className="pi-need" role="note">Alegeți coloanele cu denumirea și unitatea.</span>}
            <button type="button" className="dp-btn pri pi-go" disabled={busy || !check.ready} onClick={() => setStep('check')}><Icon name="check" /> Verifică</button>
          </div>
        </div>
      )}

      {check && step === 'check' && (
        <div className="pi-check">
          <ul className="pi-counts">
            <li className={`pi-count new${check.counts.new ? '' : ' zero'}`}><b>{check.counts.new}</b> materiale noi în catalog</li>
            <li className={`pi-count dup${check.counts.exists ? '' : ' zero'}`}><b>{check.counts.exists}</b> există deja — se sar</li>
            <li className={`pi-count noted${check.counts.similar ? '' : ' zero'}`}><b>{check.counts.similar}</b> seamănă cu altele — alegeți</li>
            <li className={`pi-count bad${check.counts.errors ? '' : ' zero'}`}><b>{check.counts.errors}</b> rânduri cu greșeli — se sar</li>
            <li className="pi-count"><b>{check.counts.rests}</b> resturi de pornire</li>
          </ul>
          {check.dup && <div className="banner warn" role="status">Acest fișier a fost deja importat {dmy(check.dup.at)} — anulați importul de atunci dacă vreți să-l aduceți din nou.</div>}
          {groups.map(([title, rows]) => rows.length > 0 && (
            <details key={title} className={`fcard pi-group${title.startsWith('Cu') ? ' bad' : title.startsWith('Există') ? ' dup' : ' new'}`} open={!title.startsWith('Există')}>
              <summary><Icon name="chev-r" /><b>{title}</b> <span className="pi-badge">{rows.length}</span></summary>
              <div className="pi-scroll">
                <table className="pi-table">
                  <thead><tr><th>Rând</th><th>Denumirea</th><th>Categoria</th><th>Ambalaj</th><th>Rest</th><th>Prag</th><th>Valabil</th><th>Ce se face</th></tr></thead>
                  <tbody>{rows.map((r) => (
                    <tr key={r.line}>
                      <td className="pi-ln">{r.line}</td><td><b>{r.name || '—'}</b></td><td>{r.cat || '—'}</td>
                      <td>{r.pack_name || '—'} <small className="dp-muted">({num(r.pack_qty_milli)} {r.unit})</small></td>
                      <td>{num(r.qty_milli)} {r.unit}</td><td>{r.min_milli === null ? '—' : `${num(r.min_milli)} ${r.unit}`}</td><td>{dmy(r.exp_on)}</td>
                      <td className="pi-said">
                        {r.act === 'error' ? <span className="st-errt">{r.err_text}</span> : <span>{ACT[r.act]}</span>}
                        {r.similar && (
                          <span className="st-sim">seamănă cu <b>{r.similar.name}</b>{r.similar.kind === 'row' ? ` (rândul ${r.similar.line})` : ' (în catalog)'}
                            <span className="dp-seg st-seg" role="group" aria-label={`Rândul ${r.line}`}>
                              <button type="button" className={r.choice === 'same' ? 'on' : ''} disabled={busy} onClick={() => choose(r.line, 'same')}>același</button>
                              <button type="button" className={r.choice === 'new' ? 'on' : ''} disabled={busy} onClick={() => choose(r.line, 'new')}>material nou</button>
                            </span>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </details>
          ))}
          <p className="hint">Rândurile cu greșeli se pot îndrepta în Excel și importa apoi doar pe ele. Locul de păstrare din coloana „Raft” ajunge în fișa materialului.</p>
          <div className="pi-acts">
            <button type="button" className="rc-btn" disabled={busy} onClick={() => setStep('cols')}>Înapoi la coloane</button>
            <button type="button" className="dp-btn pri pi-go" disabled={busy || !check.counts.new || !!check.dup} onClick={() => { void run() }}>
              <Icon name="download" /> Importă {check.counts.new} materiale
            </button>
          </div>
        </div>
      )}

      {done && step === 'done' && (
        <div className="fcard pi-done">
          <span className="rc-empty-ico ok"><Icon name="check" /></span>
          <p className="pi-done-n"><b>{done.created}</b> materiale noi în catalog și {done.rests} resturi de pornire{done.skipped ? `; ${done.skipped} rânduri sărite` : ''}.
            În mișcări — ca „Inventariere · din Excel”.</p>
          <div className="pi-acts">
            <button type="button" className="rc-btn" onClick={() => { void undo(done.id, file?.name ?? '') }}><Icon name="undo" /> Anulează importul</button>
            <button type="button" className="rc-btn pri" onClick={() => go('stoc')}><Icon name="box" /> La stoc</button>
            <button type="button" className="rc-btn" onClick={restart}><Icon name="upload" /> Alt fișier</button>
          </div>
          <p className="hint">Pragurile și furnizorii se pot completa apoi în fișa fiecărui material.</p>
        </div>
      )}

      <div className="fcard pi-past">
        <h3>Importuri făcute</h3>
        {home.imports.length === 0 ? <p className="hint">Încă niciunul.</p> : (
          <table className="pi-table">
            <thead><tr><th>Când</th><th>Fișierul</th><th>Materiale noi</th><th>Resturi</th><th>Cine</th><th /></tr></thead>
            <tbody>{home.imports.map((r) => (
              <tr key={r.id} className={r.undone ? 'dim' : ''}><td>{dmy(r.at)}</td><td className="pi-fname">{r.file}</td><td>{r.created}</td><td>{r.rests}</td><td>{r.actor}</td>
                <td className="pi-td-act">{r.undone ? <span className="st-mute">anulat</span> : r.can_undo
                  ? <button type="button" className="rc-btn" onClick={() => { void undo(r.id, r.file) }}><Icon name="undo" /> Anulează</button>
                  : <span className="st-mute" title="Materialele au deja alte mișcări — restul se corectează la inventariere">nu se mai anulează</span>}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/** Что показать в ячейке предпросмотра: поле строки сервера, уже разобранное. */
function cell(r: ImRow, field: string): string {
  switch (field) {
    case 'name': return r.name
    case 'cat': return r.cat
    case 'unit': return r.unit
    case 'pack': return r.pack_name
    case 'pack_qty': return num(r.pack_qty_milli)
    case 'qty': return num(r.qty_milli)
    case 'min': return r.min_milli === null ? '' : num(r.min_milli)
    case 'price': return r.price_bani == null ? '' : num(r.price_bani * 10)
    case 'exp': return dmy(r.exp_on)
    case 'lot': return r.lot
    case 'supplier': return r.supplier
    case 'raft': return r.raft
    default: return ''
  }
}
