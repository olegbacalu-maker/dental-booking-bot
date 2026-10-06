import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Tooth } from './Tooth'
import { ToothForm } from './ToothForm'
import { JAW_RO, bridgeOf, surfaceLetter, type Jaw, type Odontogram, type PerioLayer, type PerioLayerRow, type View } from './chart'
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
  confirmDel: 'Ștergeți puntea {span}? Dinții rămân cu starea lor.',
  bridgeFrom: 'Punte nouă de la acest dinte',
  plan: 'Adaugă în plan',
  history: 'Istoric',
  noHistory: '— fără înregistrări —',
  perio: 'Parodontogramă',
  openPerio: 'Deschide examenul',
  site: 'Punct',
  bop: 'Sângerare la sondare',
  noBop: 'fără sângerare',
  notMeasured: 'nemăsurat',
  mob: 'Mobilitate',
  furc: 'Furcație',
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
  /** позиция плана с этого зуба (01.10): то же, что в меню зуба */
  onPlan?: (n: number) => void
  /** Закрыть инспектор (пальцем он — шторка поверх дуги); мышью кнопки не видно. */
  onClose?: () => void
}

/** Шесть точек зуба таблицей (06.10): глубина, рецессия, CAL, кровоточивость.
 *  ⛔ Ничего не считается: CAL и пороги — с сервера (`perio_layer`), ноль —
 *  «не измеряли», а не «0 мм» (шапка perio.py), поэтому показывается точкой. */
function PerioTable({ row, layer, jaw }: { row: PerioLayerRow; layer: PerioLayer; jaw: Jaw }) {
  const L = surfaceLetter('L', jaw)
  const codes = ['MV', 'V', 'DV', `M${L}`, L, `D${L}`]
  const mm = (v: number | undefined) => (v ? String(v) : '·')
  const band = (v: number) => (v >= layer.limits.severe ? 'sev' : v >= layer.limits.deep ? 'deep' : '')
  const grade = (kind: 'mob' | 'furc', v: number) => (v ? `${kind === 'mob' ? T.mob : T.furc} ${layer.grades[kind][String(v)] ?? v}` : '')
  const extra = [grade('mob', row.mob), grade('furc', row.furc)].filter(Boolean).join(' · ')
  return (
    <>
      <table className="i-ptab">
        <thead>
          <tr><th scope="col">{T.site}</th><th scope="col">PD</th><th scope="col">REC</th><th scope="col">CAL</th><th scope="col">BOP</th></tr>
        </thead>
        <tbody>
          {codes.map((code, i) => {
            const pd = row.pd[i] ?? 0
            const bleed = row.bop[i] === '1'
            return (
              <tr key={code} data-site={layer.sites[i]?.key}>
                <th scope="row" title={layer.sites[i]?.label}>{code}</th>
                <td className={band(pd)} title={pd ? undefined : T.notMeasured}>{mm(pd)}</td>
                <td>{mm(row.rec[i])}</td>
                <td>{mm(row.cal[i])}</td>
                <td>{bleed ? <i className="i-bop" title={T.bop} aria-label={T.bop} /> : <span title={T.noBop}>–</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {extra && <b>{extra}</b>}
    </>
  )
}

export function ToothInspector({ model, n, view, busy, sel, onSel, onSurface, draft, dirty, onEdit, onSave, onDiscard, onDelBridge, onBridgeFrom, onPlan, onClose }: Props) {
  const info = n !== null ? model.teeth[String(n)] : undefined
  const inBr = n !== null ? bridgeOf(model, n) : null
  const hist = n !== null ? (model.history[String(n)] ?? []) : []
  // замер пародонта у ЭТОГО зуба: у одонтограммы и пародонтограммы один зуб,
  // и врачу не надо уходить со страницы, чтобы вспомнить глубину кармана
  const perio = n !== null ? model.perio?.[String(n)] : undefined
  // те же точки числами (06.10): таблица вместо строки, когда сервер прислал слой
  const layer = model.perio_layer ?? null
  const prow = n !== null ? layer?.rows[String(n)] : undefined
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
          <form onSubmit={(e) => {
            e.preventDefault()
            const span = `${inBr.bridge.teeth[0]?.[0]}-${inBr.bridge.teeth[inBr.bridge.teeth.length - 1]?.[0]}`
            void ask({ text: T.confirmDel.replace('{span}', span), danger: true })
              .then((yes) => { if (yes) onDelBridge(inBr.bridge.id) })
          }}>
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
          {prow && layer && info ? <PerioTable row={prow} layer={layer} jaw={info.jaw} /> : <b>{perio.text}</b>}
          <AppLink href={`/admin/patient/${model.patient.id}/parodontograma?exam=${perio.exam}`}>
            {T.openPerio}
          </AppLink>
        </div>
      )}
      {info && n !== null && (onPlan || (!inBr && !info.milk && onBridgeFrom)) && (
        <div className="dp-insp-acts">
          {onPlan && (
            <button type="button" className="pl-btn dp-plan" disabled={busy} onClick={() => onPlan(n)}>
              <Icon name="clipboard" /> {T.plan}
            </button>
          )}
          {!inBr && !info.milk && onBridgeFrom && (
            <button type="button" className="pl-btn dp-brfrom" disabled={busy} onClick={() => onBridgeFrom(n)}>
              <Icon name="plus" /> {T.bridgeFrom}
            </button>
          )}
        </div>
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
