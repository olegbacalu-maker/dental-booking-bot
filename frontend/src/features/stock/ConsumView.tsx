import { useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { dmy, lei, qtyText, type ConsumBy, type ConsumData } from './stock'
import { Empty } from './parts'

const BY: [ConsumBy, string][] = [['doctor', 'Medic'], ['service', 'Serviciu'], ['patient', 'Pacient']]

/** «Consum»: что ушло по факту работы — по врачу, услуге или пациенту за период; деньги — только с правом. */
export function ConsumView({ data }: { data: ConsumData | null }) {
  /* группировка и период — в адресе: от них зависят данные загрузчика маршрута */
  const [q, setQ] = useSearchParams()
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(q)
    if (v) p.set(k, v)
    else p.delete(k)
    setQ(p, { replace: true })
  }
  if (!data) return <div className="fcard rg-body" aria-busy="true" />
  const money = data.can.money
  return (
    <div className="fcard rg-body">
      <div className="st-filters">
        <span className="dp-seg st-seg" role="group" aria-label="Grupare">
          {BY.map(([k, label]) => (
            <button key={k} type="button" className={data.by === k ? 'on' : ''} aria-pressed={data.by === k} onClick={() => set('by', k === 'doctor' ? '' : k)}>{label}</button>
          ))}
        </span>
        <span className="st-qrow st-period"><input className="dp-fld st-date" type="date" value={data.from} max={data.to} aria-label="De la" onChange={(e) => set('from', e.target.value)} />
          <span className="st-mute">–</span><input className="dp-fld st-date" type="date" value={data.to} min={data.from} aria-label="Până la" onChange={(e) => set('to', e.target.value)} /></span>
      </div>
      {data.groups.length === 0 ? (
        <Empty ico="stat" title="Nimic consumat în această perioadă">
          <p className="hint">Aici se adună ce s-a scăzut pe pacienți: la „Finalizată” în plan (după fișa serviciului) și cu „Scoate din stoc › Pe pacient”.</p>
        </Empty>
      ) : (
        <div className="rg-scroll">
          <table className="rg-tbl st-tbl">
            <thead><tr><th>{BY.find(([k]) => k === data.by)![1]}</th><th className="num">Scăderi</th><th>Materiale</th>{money && <th className="num">Cost</th>}</tr></thead>
            <tbody>
              {data.groups.map((g) => (
                <tr key={g.key}>
                  <td><b>{g.label}</b></td>
                  <td className="num">{g.moves}</td>
                  <td className="st-cons-items">{g.items.map((it) => (
                    <span key={it.item_id}>{it.item} <b>{qtyText(it.qty_milli, it.unit)}</b>{money && it.cost_bani ? <small> · {lei(it.cost_bani)}</small> : null}</span>
                  ))}</td>
                  {money && <td className="num">{g.cost_bani ? lei(g.cost_bani) : '—'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.groups.length > 0 && (
        <p className="hint rg-foot"><Icon name="info" /> {dmy(data.from)} – {dmy(data.to)}{money && data.total_bani ? ` · cost total ${lei(data.total_bani)} (la prețul mediu din momentul scăderii)` : ''}.
          Scăderile anulate nu intră.</p>
      )}
    </div>
  )
}
