import { useCallback, useState, type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { catApi, dmy, type Catalog, type Item, type Lamp, type Program } from './registre'

/* Setări › Registre sanitare (10.11.2026): каталог, из которого форма записи
   делает кнопки, — стерилизаторы с программами, лампы с ресурсом, помещения
   с частотой генеральной уборки, растворы, предметы и упаковка, нормативы
   титула 257/e, «Personal pentru registre» — кто делает и кто проверяет
   (registre-people, 10.11: учётка им не нужна, имя выбирают в окне).
   Право — `PERM_SETTINGS` (директор); проверяет сервер.
   Строку каталога не удаляют, а выключают («Nu se mai folosește»): записи
   журналов несут её имя снимком, а план и ресурс считаются по id. */

type Kind = Item['kind']

const T = {
  crumb: 'Setări', title: 'Registre sanitare',
  lead: 'Din aceste liste se fac butoanele registrelor — asistenta alege, nu scrie.',
  open: 'Deschide registrele',
  sec: {
    ster: ['Sterilizatoare', '257/e'], lamp: ['Lămpi bactericide', '501/e'], room: ['Încăperi și curățenia generală', '502/e'],
    solution: ['Soluții dezinfectante', '502/e'], article: ['Articole sterilizate', '257/e'], pack: ['Ambalaje', '257/e'],
    staff: ['Personal pentru registre', '257/e · 502/e · 501/e'],
  } as Record<Kind, [string, string]>,
  staffLead: 'Cine face sterilizarea, curățenia, pornește lămpile — și cine verifică. Cont în program nu le trebuie: numele se alege în fereastra registrului, semnătura se pune de mână pe foaia tipărită. Un nume nou scris în fereastră („Alt nume”) apare aici singur.',
  staffEmpty: 'Lista e goală — ferestrele registrelor cer numele scris o dată, apoi îl arată ca buton.',
  func: 'Funcția', funcHint: 'infirmieră, asistentă medicală…', sup: 'Verifică curățenia (A supervizat, 502/e)',
  supTag: 'verifică curățenia',
  add: 'Adaugă', edit: 'Modifică', save: 'Salvează', cancel: 'Renunță',
  name: 'Denumirea', nr: 'Numărul', room: 'Încăperea', type: 'Tipul', abur: 'cu abur (autoclav)', aer: 'cu aer',
  programs: 'Programe', pLabel: 'Program', pTemp: '°C', pPress: 'bar', pMin: 'min', pAdd: 'Program', pDel: 'Șterge programul',
  m3: 'Cubatura, m³', hours: 'Resursa, ore (instrucțiunea producătorului)', base: 'Ore lucrate până acum', since: 'În funcțiune din',
  screened: 'Ecranată (se poate porni în prezența persoanelor)',
  every: 'Curățenia generală la fiecare', days: 'zile',
  active: 'Se folosește', off: 'Nu se mai folosește',
  left: 'ore rămase din', lampNew: 'Lampă nouă',
  lampNewAsk: (n: string) => `Lampa „${n}” a fost schimbată azi? Data schimbării se scrie în registru, iar orele se numără de la zero.`,
  norms: 'Documentația normativă pe foaia 257/e', normsHint: 'Se tipărește sub titlul registrului de sterilizare.',
  offline: 'Programul nu răspunde. Reîncercați.',
}

const KINDS: Kind[] = ['staff', 'ster', 'lamp', 'room', 'solution', 'article', 'pack']

interface Draft {
  id?: number | undefined; kind: Kind; name: string; nr: string; room: string; active: boolean
  type: 'abur' | 'aer'; programs: Program[]; m3: string; hours: string; base: string; since: string; screened: boolean; every: string
  func: string; sup: boolean
}

function draftOf(kind: Kind, it?: Item, today = ''): Draft {
  const d = it?.data ?? {}
  return {
    id: it?.id, kind, name: it?.name ?? '', nr: it?.nr ?? '', room: it?.room ?? '', active: it?.active ?? true,
    type: d.type ?? 'abur',
    programs: d.programs?.length ? d.programs : [{ label: 'Universal 134 °C', temp: '134', pressure: '2,1', min: 5 }],
    m3: String(d.m3 ?? ''), hours: String(d.hours ?? '8000'), base: String(d.base ?? 0), since: d.since ?? today,
    screened: d.screened ?? false, every: String(d.every ?? 7),
    func: d.func ?? '', sup: d.sup ?? false,
  }
}

function bodyOf(f: Draft): Record<string, unknown> {
  const data = f.kind === 'ster' ? { type: f.type, programs: f.programs }
    : f.kind === 'lamp' ? { m3: Number(f.m3) || 0, hours: Number(f.hours) || 0, base: Number(f.base) || 0, since: f.since, screened: f.screened }
      : f.kind === 'room' ? { every: Number(f.every) || 7 }
        : f.kind === 'staff' ? { func: f.func, sup: f.sup } : {}
  return { id: f.id, kind: f.kind, name: f.name, nr: f.nr, room: f.room, active: f.active, data }
}

interface Props { navigate?: (url: string) => void }

export function RegistreSettingsScreen({ navigate = defaultNavigate }: Props) {
  const load = useCallback((signal: AbortSignal) => catApi.get(signal), [])
  const { state, retry, replace, leaveIfSignedOut } = useLoad<Catalog>(load, navigate)
  const [edit, setEdit] = useState<Draft | null>(null)
  const [norms, setNorms] = useState<string | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [field, setField] = useState('')

  if (state.status === 'leaving') return null
  if (state.status === 'failed') return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  if (state.status === 'loading') return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  const c = state.data
  const today = new Date().toISOString().slice(0, 10)

  async function run(fn: () => Promise<{ text: string; tone: ToastState['tone'] }>, after?: () => void) {
    setBusy(true)
    setField('')
    try {
      const r = await fn()
      if (r.text) setToast({ tone: r.tone, text: r.text })
      after?.()
      replace((await catApi.get()).data)
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setField(err.field ?? '')
      setToast({ tone: 'err', text: err.text || T.offline })
    } finally {
      setBusy(false)
    }
  }

  async function lampNew(l: Lamp) {
    if (!await ask({ text: T.lampNewAsk(`${l.name}${l.nr ? ` nr. ${l.nr}` : ''}`), ok: T.lampNew })) return
    await run(() => catApi.lampNew(l.id))
  }

  return (
    <section className="dp-react-root rg rg-set">
      <div className="fcard rg-head">
        <div className="rg-ttl"><span className="rg-crumb"><AppLink href="/admin/settings">{T.crumb}</AppLink> › {T.title}</span>
          <b>{T.title}</b><small>{T.lead}</small></div>
        <AppLink className="rg-btn" href="/admin/registre"><Icon name="shield" /> {T.open}</AppLink>
      </div>
      <div className="rg-set-grid">
        {KINDS.map((k) => (
          <div key={k} className={`fcard rg-card${k === 'staff' ? ' wide' : ''}`} data-kind={k}>
            <div className="rg-card-h"><b>{T.sec[k][0]}</b><small>{T.sec[k][1]}</small>
              <button type="button" className="rg-btn sm" disabled={busy} onClick={() => setEdit(draftOf(k, undefined, today))}>
                <Icon name="plus" /> {T.add}</button></div>
            {k === 'staff' && <p className="hint rg-lead">{c.items.staff.length ? T.staffLead : `${T.staffLead} ${T.staffEmpty}`}</p>}
            {edit && edit.kind === k && !edit.id && <Editor f={edit} set={setEdit} busy={busy} field={field}
              save={() => void run(() => catApi.save(bodyOf(edit)), () => setEdit(null))} />}
            {(c.items[k] as (Item | Lamp)[]).map((it) => (edit?.id === it.id
              ? <Editor key={it.id} f={edit} set={setEdit} busy={busy} field={field}
                  save={() => void run(() => catApi.save(bodyOf(edit)), () => setEdit(null))} />
              : <Row key={it.id} it={it} busy={busy} onEdit={() => setEdit(draftOf(k, it, today))}
                  onLampNew={k === 'lamp' ? () => void lampNew(it as Lamp) : undefined} />))}
          </div>
        ))}
        <div className="fcard rg-card wide">
          <div className="rg-card-h"><b>{T.norms}</b></div>
          <textarea className="dp-fld" rows={3} value={norms ?? c.norms.text} onChange={(e) => setNorms(e.target.value)} aria-label={T.norms} />
          <div className="rg-card-f"><small className="hint">{T.normsHint}</small>
            <button type="button" className="dp-btn pri" disabled={busy || norms === null}
              onClick={() => void run(() => catApi.save({ kind: 'norms', data: { text: norms ?? '' } }), () => setNorms(null))}>
              <Icon name="save" /> {T.save}</button></div>
        </div>
      </div>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={() => setToast(null)} />}
    </section>
  )
}

function Row({ it, busy, onEdit, onLampNew }: { it: Item | Lamp; busy: boolean; onEdit: () => void; onLampNew?: (() => void) | undefined }) {
  const d = it.data
  const lamp = 'rest' in it ? it : null
  let sub = ''
  if (it.kind === 'ster') sub = [it.nr && `nr. ${it.nr}`, d.type === 'aer' ? T.aer : T.abur, it.room].filter(Boolean).join(' · ')
  if (it.kind === 'lamp') sub = [it.nr && `nr. ${it.nr}`, it.room, d.m3 ? `${d.m3} m³` : '', d.screened ? 'ecranată' : 'deschisă', `din ${dmy(d.since ?? '')}`].filter(Boolean).join(' · ')
  if (it.kind === 'room') sub = `${T.every} ${d.every ?? 7} ${T.days}`
  if (it.kind === 'staff') sub = d.func ?? ''
  return (
    <div className={`rg-item${lamp?.low ? ' low' : ''}${it.active ? '' : ' off'}${it.kind === 'staff' ? ' staff' : ''}`} data-item={it.id}>
      <div><b>{it.name}</b>{sub && <small>{sub}</small>}{!it.active && <small>{T.off}</small>}</div>
      {it.kind === 'ster' && <div className="rg-tags">{(d.programs ?? []).map((p, i) =>
        <span key={i} className="chip mute">{p.label}{p.pressure ? ` · ${p.pressure} bar` : ''}{p.min ? ` · ${p.min} min` : ''}</span>)}</div>}
      {it.kind === 'staff' && <div className="rg-tags">{d.sup ? <span className="chip info">{T.supTag}</span> : null}</div>}
      {lamp ? (
        <div className="rg-res"><span className="rg-prog"><i style={{ width: `${Math.min(100, Math.round(100 * lamp.used / Math.max(1, d.hours ?? 1)))}%` }} /></span>
          <small>{lamp.rest} {T.left} {d.hours}</small>
          {onLampNew && <button type="button" className={`rg-btn sm${lamp.low ? ' pri' : ''}`} disabled={busy} onClick={onLampNew}>{T.lampNew}</button>}</div>
      ) : it.kind !== 'ster' && it.kind !== 'staff' ? <span /> : null}
      <button type="button" className="rg-ib" aria-label={`${T.edit} ${it.name}`} disabled={busy} onClick={onEdit}><Icon name="pen" /></button>
    </div>
  )
}

function L({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return <label className={`rg-f${wide ? ' wide' : ''}`}><span className="rg-fl">{label}</span>{children}</label>
}

function Editor({ f, set, busy, field, save }: { f: Draft; set: (d: Draft | null) => void; busy: boolean; field: string; save: () => void }) {
  const up = (p: Partial<Draft>) => set({ ...f, ...p })
  const bad = (k: string) => (field === k ? ' bad' : '')
  const setP = (i: number, p: Partial<Program>) => up({ programs: f.programs.map((x, j) => (j === i ? { ...x, ...p } : x)) })
  const simple = f.kind === 'solution' || f.kind === 'article' || f.kind === 'pack'
  return (
    <div className="rg-edit">
      <div className="rg-edit-g">
        <L label={f.kind === 'staff' ? 'Numele, prenumele' : T.name} wide={simple}><input className={`dp-fld${bad('name')}`} value={f.name}
          maxLength={f.kind === 'staff' ? 80 : 120} onChange={(e) => up({ name: e.target.value })} /></L>
        {f.kind === 'staff' && <>
          <L label={T.func}><input className="dp-fld" value={f.func} maxLength={60} placeholder={T.funcHint} onChange={(e) => up({ func: e.target.value })} /></L>
          <label className="rg-check wide"><input type="checkbox" checked={f.sup} onChange={(e) => up({ sup: e.target.checked })} /> {T.sup}</label>
        </>}
        {(f.kind === 'ster' || f.kind === 'lamp') && <>
          <L label={T.nr}><input className="dp-fld" value={f.nr} maxLength={40} onChange={(e) => up({ nr: e.target.value })} /></L>
          <L label={T.room}><input className="dp-fld" value={f.room} maxLength={120} onChange={(e) => up({ room: e.target.value })} /></L>
        </>}
        {f.kind === 'ster' && <L label={T.type}>
          <select className="dp-sel" value={f.type} onChange={(e) => up({ type: e.target.value as Draft['type'] })}>
            <option value="abur">{T.abur}</option><option value="aer">{T.aer}</option></select></L>}
        {f.kind === 'lamp' && <>
          <L label={T.m3}><input className="dp-fld" inputMode="numeric" value={f.m3} onChange={(e) => up({ m3: e.target.value.replace(/\D/g, '') })} /></L>
          <L label={T.hours}><input className={`dp-fld${bad('hours')}`} inputMode="numeric" value={f.hours} onChange={(e) => up({ hours: e.target.value.replace(/\D/g, '') })} /></L>
          <L label={T.base}><input className="dp-fld" inputMode="numeric" value={f.base} onChange={(e) => up({ base: e.target.value.replace(/\D/g, '') })} /></L>
          <L label={T.since}><input className={`dp-fld${bad('since')}`} type="date" value={f.since} onChange={(e) => up({ since: e.target.value })} /></L>
          <label className="rg-check wide"><input type="checkbox" checked={f.screened} onChange={(e) => up({ screened: e.target.checked })} /> {T.screened}</label>
        </>}
        {f.kind === 'room' && <L label={`${T.every} (${T.days})`}>
          <input className="dp-fld" inputMode="numeric" value={f.every} onChange={(e) => up({ every: e.target.value.replace(/\D/g, '') })} /></L>}
      </div>
      {f.kind === 'ster' && <div className={`rg-progs${bad('programs')}`}>
        <span className="rg-fl">{T.programs}</span>
        {f.programs.map((p, i) => (
          <div key={i} className="rg-prow">
            <input className="dp-fld" aria-label={T.pLabel} value={p.label} onChange={(e) => setP(i, { label: e.target.value })} />
            <input className="dp-fld sm" aria-label={T.pTemp} placeholder={T.pTemp} value={p.temp} onChange={(e) => setP(i, { temp: e.target.value })} />
            <input className="dp-fld sm" aria-label={T.pPress} placeholder={T.pPress} value={p.pressure} onChange={(e) => setP(i, { pressure: e.target.value })} />
            <input className="dp-fld sm" aria-label={T.pMin} placeholder={T.pMin} inputMode="numeric" value={p.min || ''}
              onChange={(e) => setP(i, { min: Number(e.target.value.replace(/\D/g, '')) || 0 })} />
            <button type="button" className="rg-ib" aria-label={T.pDel} onClick={() => up({ programs: f.programs.filter((_, j) => j !== i) })}><Icon name="trash" /></button>
          </div>
        ))}
        <button type="button" className="rg-btn sm" onClick={() => up({ programs: [...f.programs, { label: '', temp: '', pressure: '', min: 0 }] })}>
          <Icon name="plus" /> {T.pAdd}</button>
      </div>}
      <div className="rg-card-f">
        {f.id && <label className="rg-check"><input type="checkbox" checked={f.active} onChange={(e) => up({ active: e.target.checked })} /> {T.active}</label>}
        <button type="button" className="rg-btn" onClick={() => set(null)}>{T.cancel}</button>
        <button type="button" className="dp-btn pri" disabled={busy || !f.name.trim()} onClick={save}><Icon name="save" /> {T.save}</button>
      </div>
    </div>
  )
}
