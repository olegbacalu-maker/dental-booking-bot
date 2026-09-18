import { mm1, type PerioLimits, type PerioSummary } from './perio'

/*
 * Итог осмотра: числа, которыми пародонтолог описывает рот. Пять плашек той
 * же сетки, что у старой страницы (.psum); пятая — средний уровень
 * прикрепления, который старая страница только объясняла словами.
 *
 * ⚠️ Знаменатель у всех — ИЗМЕРЕННЫЕ точки, а не 192: глубина 0 значит «не
 * измеряли», и половина рта, оставленная пустой, разбавляла бы BOP вдвое —
 * лечение выглядело бы успешнее, чем оно есть. Считает это правило сервер
 * (`perio.summary`); пока осмотр не записан, те же формулы показывают
 * черновик (`summarize`), и сохранённые числа приезжают им на смену.
 */
interface Props {
  summary: PerioSummary
  limits: PerioLimits
}

function Box({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="psum-i">
      <span>{label}</span>
      <b>{value}</b>
      {sub ? <small>{sub}</small> : null}
    </div>
  )
}

export function PerioSummaryCard({ summary: s, limits }: Props) {
  return (
    <aside className="fcard pside">
      <h3>Rezultatul examenului</h3>
      <div className="psum">
        <Box label="BOP" value={`${s.bop}%`} sub="sângerare la sondare" />
        <Box label="Adâncime medie" value={`${mm1(s.pd_mean)} mm`} sub="puncte măsurate" />
        <Box
          label={`Pungi ${limits.deep}+ mm`}
          value={s.deep}
          sub={`din care ${limits.severe}+ mm: ${s.severe}`}
        />
        <Box label="Dinți măsurați" value={s.teeth} sub={`${s.sites} puncte`} />
        <Box label="Atașament mediu" value={`${mm1(s.cal_mean)} mm`} sub="CAL = adâncime + recesiune" />
      </div>
      <p className="hint">
        Nivelul de atașament (CAL) se calculează, nu se introduce. Mobilitatea și furcația
        se notează la dinte, sub coloana lui.
      </p>
    </aside>
  )
}
