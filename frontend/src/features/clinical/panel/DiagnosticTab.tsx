import { AppLink } from '../../../components/AppLink'
import { StatusPicker } from '../StatusPicker'
import { surfaceLetter, type Jaw, type Odontogram, type PerioLayer, type PerioLayerRow } from '../chart'
import type { ToothDraft } from '../useChart'

/* Вкладка «Diagnostic» (24.10): состояние зуба сеткой (только про ВЕСЬ зуб —
   `tooth_states` сервера; кариес и пломба — кистью на «Suprafețe»), отметки
   переключателями («În tratament», «Nerv extras» — набор сервера, поверх любой
   находки) и последний пародонтальный замер ЭТОГО зуба: у одонтограммы и
   пародонтограммы зуб один, и врачу не надо уходить со страницы, чтобы
   вспомнить глубину кармана. */
const T = {
  state: 'Starea dintelui',
  stateOn: 'Apasă din nou pentru a șterge',
  stateOff: 'Sănătos / fără stare',
  marks: 'Semne',
  perio: 'Parodontogramă',
  openPerio: 'Deschide examenul',
  site: 'Punct',
  bop: 'Sângerare la sondare',
  noBop: 'fără sângerare',
  notMeasured: 'nemăsurat',
  mob: 'Mobilitate',
  furc: 'Furcație',
  noPerio: 'Dintele nu are încă măsurători parodontale',
} as const

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

interface Props {
  model: Odontogram
  n: number
  jaw: Jaw
  d: ToothDraft
  busy: boolean
  /** в черновике состояние про весь зуб */
  whole: boolean
  onEdit: (patch: Partial<ToothDraft>) => void
}

export function DiagnosticTab({ model, n, jaw, d, busy, whole, onEdit }: Props) {
  const perio = model.perio?.[String(n)]
  const layer = model.perio_layer ?? null
  const prow = layer?.rows[String(n)]
  return (
    <>
      <div className="dp-tp-row">
        <span className="dp-lbl">{T.state}</span>
        <span className="dp-tp-note">{whole ? T.stateOn : T.stateOff}</span>
      </div>
      <StatusPicker states={model.tooth_states} palette={model.palette} value={d.state} disabled={busy}
        onChange={(state) => onEdit({ state })} />
      <span className="dp-lbl">{T.marks}</span>
      <div className="dp-tp-sw">
        {Object.entries(model.marks).map(([k, v]) => (
          <label key={k} className="dp-sw">
            <span>{v}</span>
            <input type="checkbox" role="switch" checked={d.marks.includes(k)} disabled={busy}
              onChange={(e) => onEdit({ marks: e.target.checked ? [...d.marks, k] : d.marks.filter((x) => x !== k) })} />
          </label>
        ))}
      </div>
      {perio ? (
        <div className="i-perio dp-tp-perio">
          <span className="dp-lbl">{T.perio} · {perio.at}</span>
          {prow && layer ? <PerioTable row={prow} layer={layer} jaw={jaw} /> : <b>{perio.text}</b>}
          <AppLink href={`/admin/patient/${model.patient.id}/parodontograma?exam=${perio.exam}`}>{T.openPerio}</AppLink>
        </div>
      ) : (
        <span className="dp-tp-note">{T.noPerio}</span>
      )}
    </>
  )
}
