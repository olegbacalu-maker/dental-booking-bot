import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { Tooth } from './Tooth'
import { ToothForm } from './ToothForm'
import { JAW_RO, bridgeOf, surfaceLetter, type Odontogram, type View } from './chart'
import type { ToothDraft } from './useChart'

/* Постоянный инспектор детальной страницы (.insp): номер и челюсть, мост,
   рисунок выбранного зуба (тот же серверный SVG, клик по поверхности
   выбирает её в форме, повторный — крутит состояние), форма, история.
   Модалки здесь нет НАМЕРЕННО: она закрывает собой дугу, а смысл экрана —
   видеть зуб и соседей сразу. Всё, что умеет контекстное меню, есть и
   здесь (состояние — в форме, мост — кнопкой): меню не единственный путь. */
const T = {
  title: 'Dinte selectat',
  bridge: 'Punte',
  role: 'rol',
  delBridge: 'Șterge puntea',
  confirmDel: 'Ștergeți puntea?',
  bridgeFrom: 'Punte nouă de la acest dinte',
  history: 'Istoric',
  noHistory: '— fără înregistrări —',
  perio: 'Parodontogramă',
  openPerio: 'Deschide examenul',
  close: 'Închide',
} as const

interface Props {
  model: Odontogram
  n: number | null
  view: View
  busy: boolean
  sel: string
  onSel: (letter: string) => void
  onSurface: (n: number, letter: string) => void
  draft: ToothDraft | null
  dirty: boolean
  onEdit: (patch: Partial<ToothDraft>) => void
  onSave: () => void
  onDiscard: () => void
  onDelBridge: (bid: number) => void
  onBridgeFrom?: (n: number) => void
  /** Закрыть инспектор (пальцем он — шторка поверх дуги); мышью кнопки не видно. */
  onClose?: () => void
}

export function ToothInspector({ model, n, view, busy, sel, onSel, onSurface, draft, dirty, onEdit, onSave, onDiscard, onDelBridge, onBridgeFrom, onClose }: Props) {
  const info = n !== null ? model.teeth[String(n)] : undefined
  const inBr = n !== null ? bridgeOf(model, n) : null
  const hist = n !== null ? (model.history[String(n)] ?? []) : []
  // замер пародонта у ЭТОГО зуба: у одонтограммы и пародонтограммы один зуб,
  // и врачу не надо уходить со страницы, чтобы вспомнить глубину кармана
  const perio = n !== null ? model.perio?.[String(n)] : undefined
  return (
    <div className="fcard insp">
      <div className="insp-t">{T.title}
        {onClose && n !== null && (
          <button type="button" className="insp-close" aria-label={T.close} title={T.close} onClick={onClose}><Icon name="close" /></button>
        )}
      </div>
      <div className="insp-n"><b>{n ?? '—'}</b><span>{info ? JAW_RO[info.jaw] : ''}</span></div>
      {inBr && (
        <div className="i-bridge">
          <span>
            {T.bridge} {inBr.bridge.teeth[0]?.[0]}-{inBr.bridge.teeth[inBr.bridge.teeth.length - 1]?.[0]}
            {inBr.bridge.material ? ` (${inBr.bridge.material})` : ''} - {T.role}: {model.bridge_roles[inBr.role] ?? inBr.role}
          </span>
          <form onSubmit={(e) => { e.preventDefault(); if (window.confirm(T.confirmDel)) onDelBridge(inBr.bridge.id) }}>
            <button className="pl-btn" disabled={busy}>{T.delBridge}</button>
          </form>
        </div>
      )}
      <div className="insp-pic" data-jaw={info?.jaw} data-mez={info?.mez}>
        <span className="lb lb-v">V</span>
        <span className="lb lb-l">{info ? surfaceLetter('L', info.jaw) : 'L'}</span>
        <span className="lb lb-m">M</span>
        <span className="lb lb-d">D</span>
        {info && n !== null && (
          <Tooth n={n} info={info} view={view} onSurface={onSurface} onSelect={() => undefined} />
        )}
      </div>
      {info && n !== null && draft && (
        <ToothForm
          model={model}
          n={n}
          info={info}
          busy={busy}
          sel={sel}
          onSel={onSel}
          draft={draft}
          dirty={dirty}
          onEdit={onEdit}
          onSave={onSave}
          onDiscard={onDiscard}
        />
      )}
      {perio && (
        <div className="i-perio">
          <span>{T.perio} · {perio.at}</span>
          <b>{perio.text}</b>
          <AppLink href={`/admin/patient/${model.patient.id}/parodontograma?exam=${perio.exam}`}>
            {T.openPerio}
          </AppLink>
        </div>
      )}
      {info && n !== null && !inBr && !info.milk && onBridgeFrom && (
        <button type="button" className="pl-btn dp-brfrom" disabled={busy} onClick={() => onBridgeFrom(n)}>
          <Icon name="plus" /> {T.bridgeFrom}
        </button>
      )}
      <div className="thist">
        {n !== null && (hist.length ? (
          <>
            <div className="th-t">{T.history}</div>
            {hist.map((h, i) => <div key={i} className="th-r"><span>{h.at}</span>{h.text}</div>)}
          </>
        ) : <p className="hint dp-m0">{T.noHistory}</p>)}
      </div>
      {n === null && <Icon name="tooth" />}
    </div>
  )
}
