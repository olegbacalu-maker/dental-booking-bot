import { Icon } from '../../components/Icon'
import { dmy, num, type PatientMove } from './stock'

/** Фиша › «Plan și plăți»: что со склада ушло этому пациенту — материал, количество, лот, когда и кто.
 *  Видят все, кто видит фишу (врачу нужен лот импланта при отзыве партии); пусто — блока нет. */
export function StockOutBlock({ rows }: { rows: PatientMove[] | null | undefined }) {
  if (!rows?.length) return null
  return (
    <div className="fcard st-pat" aria-label="Materiale pe pacient">
      <h3><Icon name="box" /> Materiale pe pacient <small>lotul ajută la rechemarea unui lot de implanturi sau membrane</small></h3>
      <div className="rg-scroll">
        <table className="rg-tbl st-pat-tbl">
          <thead><tr><th>Data</th><th>Material</th><th className="num">Cantitate</th><th>Lot</th><th>Cine</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.undone ? 'st-off-r' : ''}>
                <td className="num">{dmy(r.on)}</td>
                <td><b>{r.item}</b>{r.note && <small>{r.note}</small>}{r.undone && <small className="st-warnt">anulat</small>}</td>
                <td className="num">{num(Math.abs(r.qty_milli))} {r.unit}</td>
                <td>{r.lot || <span className="st-mute">—</span>}{r.exp_on && <small>valabil până la {dmy(r.exp_on)}</small>}</td>
                <td>{r.actor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
