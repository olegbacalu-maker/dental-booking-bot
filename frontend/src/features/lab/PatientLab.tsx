import { useCallback, useState, type ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import { useLoad } from '../../hooks/useLoad'
import type { PatientCard, PlanItem } from '../patients/card/card'
import { useLabHost } from './host'
import { dm, isLabWork, isOpen, labApi, type PatientData } from './lab'
import { Appt, Due, RowActs, StatusPill, teethText, TONE, UrgentTag } from './parts'

const planOpen = (it: PlanItem) => it.status === 'planificat' || it.status === 'in_lucru'

/** Заказы одной фиши: своя загрузка (вкладки фишу не перечитывают), окна и значок для строки плана. */
export function usePatientLab(card: PatientCard, say: (text: string, tone: 'ok' | 'err') => void) {
  const pid = card.id
  const load = useCallback((signal: AbortSignal) => labApi.patient(pid, signal), [pid])
  const { state, retry } = useLoad<PatientData>(load)
  const host = useLabHost(retry, say)
  const data = state.status === 'ready' ? state.data : null
  const badge = (id: number) => data?.plan[String(id)]
  const free = card.plan.items.filter((it) => planOpen(it) && isLabWork(it.procedure) && !badge(it.id))

  /** Значок под процедурой плана: срок и стадия работы — или кнопка заказать. */
  function chip(it: PlanItem): ReactNode {
    if (!data) return null
    const b = badge(it.id)
    if (b) {
      const word = b.late ? 'întârziat' : b.status === 'trimis' ? `termen ${dm(b.due_on)}` : b.status_label.toLowerCase()
      return (
        <button type="button" className={`lb-chip ${b.late ? 'bad' : TONE[b.status]}`} title={`Comanda nr. ${b.nr}`} onClick={() => host.open(b.order_id)}>
          <Icon name="box" /> Laborator · {word}
        </button>
      )
    }
    if (planOpen(it) && isLabWork(it.procedure)) {
      return (
        <button type="button" className="lb-chip add" onClick={() => host.create(pid, it.id)}>
          <Icon name="plus" /> Comandă la laborator
        </button>
      )
    }
    return null
  }
  return { state, retry, data, free, chip, host, pid }
}

export type PatientLabModel = ReturnType<typeof usePatientLab>

/** Блок «Lucrări de laborator» под планом лечения. */
export function LabBlock({ lab: L }: { lab: PatientLabModel }) {
  const [pick, setPick] = useState(false)
  const [done, setDone] = useState(false)
  if (L.state.status === 'failed') {
    return (
      <div className="fcard lb-block" id="laborator">
        <h3>Lucrări de laborator</h3>
        <p className="hint">Comenzile nu s-au încărcat. <button type="button" className="lnk" onClick={L.retry}>Reîncearcă</button></p>
      </div>
    )
  }
  const orders = L.data?.orders ?? []
  const open = orders.filter(isOpen)
  const closed = orders.filter((o) => !isOpen(o))
  const shown = done ? orders : open
  const late = open.filter((o) => o.late).length
  return (
    <div className="fcard lb-block" id="laborator" aria-busy={L.state.status === 'loading' || undefined}>
      <h3>
        Lucrări de laborator
        <small> · {open.length ? `${open.length} în lucru` : 'nimic în lucru'}</small>
        {late > 0 && <span className="pill red">{late === 1 ? '1 întârziată' : `${late} întârziate`}</span>}
        <button type="button" className="lb-add" onClick={() => (L.free.length ? setPick(!pick) : L.host.create(L.pid))} aria-expanded={pick}>
          <Icon name="plus" /> Comandă nouă</button>
      </h3>
      {pick && (
        <div className="lb-pick">
          <span className="rg-fl">Pentru ce poziție din plan?</span>
          <div className="rg-chips">
            {L.free.map((it) => (
              <button key={it.id} type="button" className="rg-chip" onClick={() => { setPick(false); L.host.create(L.pid, it.id) }}>
                {it.tooth ? <b>{it.tooth}</b> : null} {it.procedure}
              </button>
            ))}
            <button type="button" className="rg-chip" onClick={() => { setPick(false); L.host.create(L.pid) }}>
              <Icon name="plus" /> Lucrare fără poziție în plan
            </button>
          </div>
        </div>
      )}
      {L.data && orders.length === 0 && !pick && (
        <p className="hint lb-none">Nicio comandă pentru acest pacient. Comanda se face de la poziția din plan — coroană, punte, proteză,
          alignere — și pleacă la laborator cu fișa de comandă tipărită.</p>
      )}
      {shown.length > 0 && (
        <div className="lb-rows">
          <div className="lb-row lb-head" aria-hidden="true">
            <span>Dinți</span><span>Lucrarea</span><span>Laborator</span><span>Termen</span><span>Programare</span><span>Stare</span><span />
          </div>
          {shown.map((o) => (
            <div key={o.id} className={`lb-row${isOpen(o) ? '' : ' done'}`} data-st={o.status}>
              <span className="lb-tt">{teethText(o.teeth)}</span>
              <span className="lb-w"><b>{o.work}</b>{o.urgent && <UrgentTag />}<small>nr. {o.nr} · {dm(o.sent_on)}</small></span>
              <span className="lb-l">{o.lab}</span>
              <Due o={o} />
              <Appt a={isOpen(o) ? o.next_appt : null} warn={o.visit_wait} />
              <StatusPill o={o} />
              <RowActs o={o} host={L.host} />
            </div>
          ))}
        </div>
      )}
      {closed.length > 0 && (
        <button type="button" className="lnk lb-more" onClick={() => setDone(!done)}>
          {done ? 'Ascunde finalizatele' : `Arată și finalizatele / anulatele (${closed.length})`}
        </button>
      )}
    </div>
  )
}

/** Карточка «Rezumat»: что сейчас у техника и к какому сроку. */
export function LabSummary({ lab: L, onOpen }: { lab: PatientLabModel; onOpen: () => void }) {
  const open = (L.data?.orders ?? []).filter(isOpen)
  if (!open.length) return null
  return (
    <div className="fcard lb-sum">
      <h3>Laborator <button type="button" className="lnk" onClick={onOpen}>Toate ›</button></h3>
      {open.map((o) => (
        <button key={o.id} type="button" className="lb-sum-r" onClick={() => L.host.open(o.id)}>
          <span><b>{o.work}</b><small>{o.lab}</small></span>
          <Due o={o} />
          <StatusPill o={o} />
        </button>
      ))}
    </div>
  )
}
