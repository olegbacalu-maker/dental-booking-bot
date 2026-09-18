import { useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { hideDialog, showDialog } from './dialog'
import { mdl, patientCard, type PatientCard, type PlanForm, type PlanItem } from './card'

/* План лечения — те же слова, кнопки и порядок, что у старой карточки.
   Переходы направленные: кнопку следующего шага, возможность отказа и
   удаления называет сервер у каждой позиции (PLAN_EDGES). Отказ требует
   ТЕКСТ (ст. 13(5) Legea 263/2005) — сервер отбивает пустой. */
const T = {
  title: 'Plan de tratament',
  active: 'plan activ:',
  acord: 'Acord informat',
  acordTitle: 'Acord informat la plan — pentru semnătura pacientului și a medicului (art. 13 Legea nr. 263/2005)',
  finalized: 'finalizate',
  refused: 'refuzate',
  tabs: { act: 'Active', finalizat: 'Finalizate', refuzat: 'Refuzate', all: 'Toate' },
  empty: '— plan gol —',
  total: 'Total plan activ',
  totalDone: 'finalizate:',
  overdue: 'Termen depășit',
  doneDate: 'Data finalizării',
  refuzDate: 'Data refuzului',
  openTooth: 'Deschide dintele în formulă',
  next: {
    planificat: ['Începe', 'Trece procedura în lucru'],
    in_lucru: ['Finalizează', 'Marchează ca finalizată'],
    refuzat: ['Reia', 'Pacientul a revenit — înapoi în plan'],
    finalizat: ['Redeschide', 'Redeschide — înapoi în lucru'],
  } as Record<string, [string, string]>,
  confirmReia: 'Pacientul a revenit asupra refuzului? Procedura se întoarce în plan.',
  confirmReopen: 'Redeschideți procedura (înapoi în lucru)?',
  refuz: 'Refuz',
  refuzTitle: 'Pacientul refuză procedura — se consemnează în fișă',
  del: 'Șterge poziția (doar cât nu a fost începută)',
  confirmDel: 'Ștergeți poziția din plan?',
  milk: 'Dinți de lapte',
  ph: { proc: 'Procedură (ex. Coroană zirconiu)', price: 'Preț MDL', due: 'Termen planificat', doctor: 'Medic —' },
  dueHint: 'termen (opțional)',
  add: '+ Adaugă în plan',
  refuzDlg: 'Refuzul pacientului',
  refuzProc: 'Procedura:',
  refuzLabel: 'Motivul refuzului și consecințele explicate pacientului',
  refuzPh: 'Ex.: pacientul refuză extracția; i s-au explicat riscul de infecție și pierderea dinților vecini',
  refuzHint:
    'Se consemnează în fișă și apare în Fișa 043/e și în acordul informat, conform art. 13 alin. (5) din Legea nr. 263/2005. Foaia tipărită se semnează de pacient și de medic.',
  refuzGo: 'Înregistrează refuzul',
  close: 'Închide',
  mdl: 'MDL',
} as const

interface Props {
  card: PatientCard
  a: CardActions
  /** Клик по номеру зуба: диалог одонтограммы (точка интеграции) или
      детальная страница, если куска на экране нет. */
  onTooth: (n: number) => void
}

export function PlanCard({ card, a, onTooth }: Props) {
  const plan = card.plan
  const tabs = card.options.tab_states
  /* вкладка: выбор человека живёт, пока сервер не сменил вкладку по
     умолчанию (кончилось активное — открывается непустая), как на старой
     странице после перезагрузки; выводится при отрисовке, без эффекта */
  const [tabPick, setTabPick] = useState({ def: plan.default_tab, tab: plan.default_tab })
  const tab = tabPick.def === plan.default_tab ? tabPick.tab : plan.default_tab
  const setTab = (t: string) => setTabPick({ def: plan.default_tab, tab: t })
  const [form, setForm] = useState<PlanForm>({ tooth: '', procedure: '', doctor: '', price: '', due_date: '' })
  const [invalid, setInvalid] = useState(false)
  const set = (patch: Partial<PlanForm>) => setForm((f) => ({ ...f, ...patch }))
  const refuzDlg = useRef<HTMLDialogElement>(null)
  const [refuz, setRefuz] = useState<PlanItem | null>(null)
  const [motiv, setMotiv] = useState('')
  const [motivBad, setMotivBad] = useState(false)

  async function onAdd(e: FormEvent) {
    e.preventDefault()
    setInvalid(false)
    const err = await a.act(() => patientCard.addPlan(a.pid, a.views, form))
    if (err?.field) setInvalid(true)
    else if (!err) setForm({ tooth: '', procedure: '', doctor: '', price: '', due_date: '' })
  }

  async function step(it: PlanItem) {
    if (it.status === 'refuzat' && !window.confirm(T.confirmReia)) return
    if (it.status === 'finalizat' && !window.confirm(T.confirmReopen)) return
    await a.act(() => patientCard.planStatus(a.pid, a.views, it.id, it.next))
  }

  function openRefuz(it: PlanItem) {
    setRefuz(it)
    setMotiv('')
    setMotivBad(false)
    showDialog(refuzDlg.current)
  }

  async function onRefuz(e: FormEvent) {
    e.preventDefault()
    if (!refuz) return
    setMotivBad(false)
    const err = await a.act(() => patientCard.planStatus(a.pid, a.views, refuz.id, 'refuzat', motiv))
    if (err?.field) setMotivBad(true)
    else if (!err) hideDialog(refuzDlg.current)
  }

  async function del(it: PlanItem) {
    if (!window.confirm(T.confirmDel)) return
    await a.act(() => patientCard.delPlan(a.pid, a.views, it.id))
  }

  const shown = plan.items.filter((it) => tab === 'all' || (tabs[tab] ?? []).includes(it.status))
  const closedStates = [...(tabs.finalizat ?? []), ...(tabs.refuzat ?? [])]

  return (
    <div className="fcard" id="plan">
      <h3>
        {T.title} <small>· {T.active} {mdl(plan.total)} {T.mdl}</small>
        {plan.items.length > 0 && (
          <a className="pacord" href={`/admin/patient/${card.id}/plan-acord`} title={T.acordTitle}>
            <Icon name="clipboard" /> {T.acord}
          </a>
        )}
      </h3>
      {plan.items.length > 0 && (
        <div className="plan-prog">
          <div className="statbar"><div style={{ width: `${plan.pct_done}%` }}></div></div>
          <small>
            {plan.counts.finalizat}/{plan.n_track} {T.finalized}
            {plan.counts.refuzat ? ` · ${plan.counts.refuzat} ${T.refused}` : ''}
          </small>
        </div>
      )}
      <div className="tabs">
        <button type="button" className={tab === 'act' ? 'on' : ''} onClick={() => setTab('act')}>{T.tabs.act} ({plan.n_act})</button>
        <button type="button" className={tab === 'finalizat' ? 'on' : ''} onClick={() => setTab('finalizat')}>{T.tabs.finalizat} ({plan.counts.finalizat})</button>
        {plan.counts.refuzat ? (
          <button type="button" className={tab === 'refuzat' ? 'on' : ''} onClick={() => setTab('refuzat')}>{T.tabs.refuzat} ({plan.counts.refuzat})</button>
        ) : null}
        <button type="button" className={tab === 'all' ? 'on' : ''} onClick={() => setTab('all')}>{T.tabs.all} ({plan.items.length})</button>
      </div>
      {plan.items.length === 0 && <p className="hint dp-m6">{T.empty}</p>}
      {shown.map((it) => {
        const [word, title] = T.next[it.status] ?? ['', '']
        const closed = closedStates.includes(it.status)
        const nextCls = it.status === 'planificat' ? 'pgo' : it.status === 'in_lucru' ? 'pgo fin' : 'pre'
        const nextIcon = it.status === 'planificat' ? 'play' : it.status === 'in_lucru' ? 'check' : 'undo'
        return (
          <div key={it.id} className={`plan-row${closed ? ' done' : ''}`} data-st={it.status}>
            {it.tooth
              ? <button type="button" className="pt" title={T.openTooth} onClick={() => onTooth(it.tooth as number)}>{it.tooth}</button>
              : <span className="pt">—</span>}
            <span className="pp">
              {it.procedure}
              {it.motiv && <em className="pmotiv">{it.motiv}</em>}
            </span>
            <span className="pd">{it.doctor || '—'}</span>
            {closed && it.done
              ? <span className="pdone" title={it.status === 'finalizat' ? T.doneDate : T.refuzDate}>
                  <Icon name={it.status === 'finalizat' ? 'check' : 'ban'} /> {it.done}
                </span>
              : <span className="pdue">
                  {it.overdue
                    ? <span className="dp-overdue" title={T.overdue}><Icon name="sos" /> {it.due}</span>
                    : (it.due || '—')}
                </span>}
            <span className={`pbadge ${it.status}`}>{it.label}</span>
            <span className="pm">{it.price ? `${mdl(it.price)} ${T.mdl}` : '—'}</span>
            <span className="pact">
              {word && (
                <button type="button" className={nextCls} title={title} disabled={a.busy} onClick={() => { void step(it) }}>
                  <Icon name={nextIcon} /> {word}
                </button>
              )}
              {it.refusable && (
                <button type="button" className="pref" title={T.refuzTitle} disabled={a.busy} onClick={() => openRefuz(it)}>
                  <Icon name="ban" /> {T.refuz}
                </button>
              )}
              {it.deletable && (
                <button type="button" className="pdel" title={T.del} aria-label={`${T.del}: ${it.procedure}`} disabled={a.busy} onClick={() => { void del(it) }}>
                  <Icon name="close" />
                </button>
              )}
            </span>
          </div>
        )
      })}
      <div className="ptotal">
        <span>{T.total}</span><b>{mdl(plan.total)} {T.mdl}</b>
        {plan.total_done > 0 && <span className="pt-done"> · {T.totalDone} {mdl(plan.total_done)} {T.mdl}</span>}
      </div>
      <form className="fform dp-mt10" onSubmit={onAdd}>
        <div className="r2">
          <select value={form.tooth} onChange={(e) => set({ tooth: e.target.value })} style={{ width: 90 }} aria-label="Dinte">
            <option value="">—</option>
            {card.options.teeth.map((n) => <option key={n} value={n}>{n}</option>)}
            <optgroup label={T.milk}>
              {card.options.milk.map((n) => <option key={n} value={n}>{n}</option>)}
            </optgroup>
          </select>
          <input value={form.procedure} onChange={(e) => set({ procedure: e.target.value })} placeholder={T.ph.proc}
                 aria-label={T.ph.proc} maxLength={120} required aria-invalid={invalid || undefined} />
        </div>
        <div className="r2">
          <select value={form.doctor} onChange={(e) => set({ doctor: e.target.value })} aria-label={T.ph.doctor}>
            <option value="">{T.ph.doctor}</option>
            {card.options.doctors.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input type="number" min={0} max={1000000} value={form.price} onChange={(e) => set({ price: e.target.value })}
                 placeholder={T.ph.price} aria-label={T.ph.price} style={{ width: 130 }} />
        </div>
        <div className="r2">
          <input type="date" value={form.due_date} onChange={(e) => set({ due_date: e.target.value })} title={T.ph.due} aria-label={T.ph.due} />
          <span className="dp-due-hint">{T.dueHint}</span>
        </div>
        <button disabled={a.busy}>{T.add}</button>
      </form>
      <dialog ref={refuzDlg} onClose={() => setRefuz(null)}>
        <div className="dlg-head">
          <span><Icon name="ban" /> {T.refuzDlg}</span>
          <button type="button" onClick={() => hideDialog(refuzDlg.current)} aria-label={T.close}><Icon name="close" /></button>
        </div>
        <form className="dlg-form" onSubmit={onRefuz}>
          <p className="hint dp-m0">{T.refuzProc} <b>{refuz?.procedure ?? '—'}</b></p>
          <label className="dlab">{T.refuzLabel}
            <textarea value={motiv} onChange={(e) => setMotiv(e.target.value)} rows={3} maxLength={300} required
                      placeholder={T.refuzPh} aria-invalid={motivBad || undefined} />
          </label>
          <p className="hint dp-m0">{T.refuzHint}</p>
          <button disabled={a.busy}><Icon name="ban" /> {T.refuzGo}</button>
        </form>
      </dialog>
    </div>
  )
}
