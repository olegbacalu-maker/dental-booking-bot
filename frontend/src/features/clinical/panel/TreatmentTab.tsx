import { AppLink } from '../../../components/AppLink'
import { ask } from '../../../components/confirm'
import { Icon } from '../../../components/Icon'
import { mdl } from '../../patients/card/card'
import type { Bridge, Odontogram, ToothPlanItem } from '../chart'

/* Вкладка «Tratament» (24.10): позиции плана ЭТОГО зуба, «Adaugă în plan» и
   мост. Позиции — ТОЛЬКО чтение: строка та же, что у плана фиши (подпись
   статуса, срок с просрочкой, дата закрытия, врач, цена, причина отказа —
   сервер), а переходы (Începe, Finalizează, Refuz…) живут во вкладке фиши
   «Plan și plăți» — туда ведёт ссылка. Второй таблицы переходов здесь нет.
   Позиции приезжают в модели одонтограммы (`model.plan`), а не открытием
   фиши: GET фиши пишет «Fișa deschisă» в журнал доступа (закон 195). */
const T = {
  plan: 'Planul dintelui',
  none: 'Nimic planificat pentru acest dinte',
  add: 'Adaugă în plan',
  full: 'Planul complet în fișă',
  overdue: 'Termen depășit',
  due: 'termen',
  mdl: 'MDL',
  bridge: 'Punte',
  role: 'rol',
  delBridge: 'Șterge puntea',
  confirmDel: 'Ștergeți puntea {span}? Dinții rămân cu starea lor.',
  bridgeFrom: 'Punte nouă de la acest dinte',
} as const

function PlanRow({ it }: { it: ToothPlanItem }) {
  const when = it.done
    ? <span><Icon name={it.status === 'finalizat' ? 'check' : 'ban'} /> {it.done}</span>
    : it.overdue
      ? <span className="dp-overdue" title={T.overdue}><Icon name="sos" /> {it.due}</span>
      : it.due ? <span>{T.due} {it.due}</span> : null
  const facts = [it.doctor, it.price ? `${mdl(it.price)} ${T.mdl}` : ''].filter(Boolean)
  return (
    <li className={`dp-tpl-r${it.active ? '' : ' off'}`} data-plan={it.id}>
      <span className="pr">{it.procedure}</span>
      <span className={`pbadge ${it.status}`}>{it.label}</span>
      {(when || facts.length > 0) && (
        <span className="mt">{when}{when && facts.length > 0 && ' · '}{facts.join(' · ')}</span>
      )}
      {it.motiv && <em className="pmotiv">{it.motiv}</em>}
    </li>
  )
}

interface Props {
  model: Odontogram
  n: number
  milk: boolean
  busy: boolean
  /** мост, в котором стоит зуб, и его роль там */
  inBr: { bridge: Bridge; role: string } | null
  onPlan?: ((n: number) => void) | undefined
  onBridgeFrom?: ((n: number) => void) | undefined
  onDelBridge: (bid: number) => void
}

export function TreatmentTab({ model, n, milk, busy, inBr, onPlan, onBridgeFrom, onDelBridge }: Props) {
  const rows = model.plan?.[String(n)] ?? []
  const span = inBr ? `${inBr.bridge.teeth[0]?.[0]}-${inBr.bridge.teeth[inBr.bridge.teeth.length - 1]?.[0]}` : ''
  return (
    <>
      <span className="dp-lbl">{T.plan}</span>
      {rows.length
        ? <ul className="dp-tpl">{rows.map((it) => <PlanRow key={it.id} it={it} />)}</ul>
        : <p className="hint dp-m0">{T.none}</p>}
      {onPlan && (
        <button type="button" className="dp-btn dp-plan" disabled={busy} onClick={() => onPlan(n)}>
          <Icon name="clipboard" /> {T.add}
        </button>
      )}
      <AppLink className="dp-tpl-full" href={`/admin/patient/${model.patient.id}?tab=plan`}>{T.full}</AppLink>
      {inBr ? (
        <div className="dp-tp-br">
          <span>
            {T.bridge} {span}{inBr.bridge.material ? ` (${inBr.bridge.material})` : ''} - {T.role}: {model.bridge_roles[inBr.role] ?? inBr.role}
          </span>
          <button type="button" className="pl-btn" disabled={busy} onClick={() => {
            void ask({ text: T.confirmDel.replace('{span}', span), danger: true })
              .then((yes) => { if (yes) onDelBridge(inBr.bridge.id) })
          }}>{T.delBridge}</button>
        </div>
      ) : !milk && onBridgeFrom && (
        <button type="button" className="dp-btn ghost dp-brfrom" disabled={busy} onClick={() => onBridgeFrom(n)}>
          <Icon name="plus" /> {T.bridgeFrom}
        </button>
      )}
    </>
  )
}
