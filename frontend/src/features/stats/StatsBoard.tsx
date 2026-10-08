import { useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Count } from '../../components/Count'
import { Icon, iconName } from '../../components/Icon'
import { Spark } from '../../components/Spark'
import { t } from '../../utils/i18n'
import { CategoryBar, Columns, Meter } from './StatsCharts'
import type { Badge, Kpi, StatsData, Trend } from './stats'

/* Раскладка «Statistici» (B8, 27.09; вид по макету Олега 08.10, промпт 2): по
   образцу открытых SaaS-шаблонов (shadcn/ui dashboard-01 — MIT, Tremor
   Dashboard OSS — Apache-2.0). В шапке — период и «comparat cu …», справа
   «Exportă»; четыре карточки показателей (название, чип изменения, число,
   прошлый период, спарклайн или шкала, подвал через линию); график по дням с
   переключателем, «Bani», «Medici», «Top servicii» и лента событий.
   Порядок чтения директора: деньги → поток пациентов → явка → загрузка, потом
   «почему» (график, врачи, услуги) и только в конце — лента событий.
   ⛔ Все цифры и суммы — с сервера (`board` модели): здесь только раскладка,
   второй форматировщик денег разошёлся бы с печатным отчётом кассы. */

const T = t('stats', {
  period: 'Perioadă',
  interval: 'Interval',
  excel: 'Exportă',
  compared: 'comparat cu',
  metric: 'Indicator',
  byDays: 'pe zile',
  byWeeks: 'pe săptămâni',
  hover: 'treceți cu cursorul peste o coloană',
  mAppts: 'Programări',
  mIncome: 'Încasări',
  unit: 'programări',
  total: 'Total',
  avg: 'Medie pe zi lucrătoare',
  bestDay: 'Cea mai bună zi',
  bestWeek: 'Cea mai bună săptămână',
  emptyChart: '— nimic în perioada aleasă —',
  money: 'Bani',
  moneySub: 'real și estimat',
  cash: 'Încasat (real)',
  estimated: 'Estimat după lista de prețuri',
  loss: 'Pierdut din neprezentări',
  today: 'Azi · încasat / estimat',
  doctors: 'Medici',
  doctorsSub: 'prezență și ocupare',
  colDoctor: 'Medic',
  colAppts: 'Prog.',
  colCame: 'Au venit',
  colPresence: 'Prezență',
  colBusy: 'Ocupare',
  inactive: 'inactiv',
  services: 'Top servicii',
  servicesSub: 'după numărul de programări',
  noServices: '— încă fără programări —',
  activity: 'Activitate recentă',
  activitySub: 'ultimele evenimente din clinică',
  noActivity: '— încă nimic —',
  unchanged: 'neschimbat',
  apply: 'Aplică',
  fromLabel: 'De la',
  toLabel: 'Până la',
} as const)

/** Цвета способов оплаты (макет 08.10): палитра проверена на цветовую
 *  слепоту; это цвета СМЫСЛА, теме не отдаются. Неизвестный способ — цветом
 *  сервера. */
const PAY_COLORS: Record<string, string> = { numerar: '#0a8ea0', card: '#c8691a', transfer: '#8a5cd6' }

/** Метка в углу карточки. ⛔ Цвет — из `dir` (хорошо/плохо), а не из знака:
 *  рост отмен — стрелка вверх, но красная. */
function BadgeView({ b }: { b: Badge }) {
  return (
    <span className={b.dir ? `stx-badge ${b.dir}` : 'stx-badge'}>
      {b.icon && <Icon name={iconName(b.icon)} />}
      {b.text}
    </span>
  )
}

/** Строка сравнения. «Неизменно» — СЛОВО, а не нулевой процент. */
function TrendLine({ t: tr }: { t: Trend }) {
  if (!tr.dir) return <span className="stx-trend">{T.unchanged} {tr.label}</span>
  return (
    <span className="stx-trend">
      <span className={tr.dir}>{tr.value}</span> {tr.label}{tr.note}
    </span>
  )
}

/**
 * Карточка показателя (макет 08.10): название, чип изменения, число 32/700,
 * значение прошлого периода (приём Tremor «from X»), спарклайн у сумм и
 * количеств или шкала у процентов, и одна строка разбора под линией.
 */
function KpiCard({ k, live, prevName }: { k: Kpi; live: boolean; prevName: string }) {
  const money = k.key === 'incasari'
  return (
    <div className="fcard stx-kpi" data-kpi={k.key}>
      <div className="stx-kpi-h">
        <h3 className="stx-kpi-l">{k.label}</h3>
        <BadgeView b={k.badge} />
      </div>
      <div className="stx-kpi-v">
        {money
          ? <Count value={k.value} live={live} suffix=" MDL" group />
          : <Count value={k.value} live={live} suffix={k.pct !== undefined ? '%' : ''} />}
      </div>
      <span className="stx-prev">{prevName}: <b>{k.prev}</b></span>
      <div className="stx-kpi-f">
        {k.series && <Spark series={k.series} tone="var(--teal)" />}
        {k.pct !== undefined && <Meter pct={k.pct} tone="var(--teal)" />}
      </div>
      <p className="stx-kpi-sub">{k.sub}</p>
    </div>
  )
}

interface Props {
  d: StatsData
  live: boolean
  /** Набранный в полях период — состояние формы экрана, а не адреса. */
  pick: { from: string; to: string }
  onPick: (from: string, to: string) => void
  onPreset: (from: string, to: string) => void
  onApply: () => void
  periodUrl: (from: string, to: string) => string
}

export function StatsBoard({ d, live, pick, onPick, onPreset, onApply, periodUrl }: Props) {
  const board = d.board
  const [metric, setMetric] = useState<'appts' | 'income'>('appts')
  const preset = d.presets.find((p) => p.from === d.period.from && p.to === d.period.to)
  const [open, setOpen] = useState(false)
  const s = board.series
  const sum = metric === 'appts' ? board.summary.appts : board.summary.income
  const m = board.money
  const byWeek = s.bucket === 'week'
  const metricName = metric === 'appts' ? T.mAppts : T.mIncome
  /* День недели для подписи оси («Vi / 02.10») — из подсказки дня сервера
     («Vi, 02.10.2026»); у недельных корзин подписи нет. */
  const wdays = byWeek ? undefined : s.hints.map((h) => h.split(',')[0] ?? '')
  return (
    <>
      {/* ⭐ Первый `.nav` узла встаёт в шапку рядом с заголовком, `.sub` — под
          него (сетка .content): период и «comparat cu …» — подпись раздела. */}
      <div className="nav stx-head">
        <div className="stx-seg" role="group" aria-label={T.period}>
          {d.presets.map((p) => {
            const on = p === preset
            return (
              <AppLink
                key={p.key}
                className={on ? 'on' : undefined}
                aria-current={on ? 'true' : undefined}
                href={periodUrl(p.from, p.to)}
                onClick={(e) => { e.preventDefault(); setOpen(false); onPreset(p.from, p.to) }}
              >{p.label}</AppLink>
            )
          })}
          <button
            type="button"
            className={!preset || open ? 'on' : undefined}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          ><Icon name="cal" />{T.interval}{!preset && d.period.short && <em>{d.period.short}</em>}</button>
        </div>
        <AppLink className="dp-btn" href={d.export_url}><Icon name="download" /> {T.excel}</AppLink>
      </div>
      <div className="sub stx-period"><b>{d.period.label}</b> · {T.compared} {board.prev_name}</div>

      <div className="stx">
        {open && (
          <form className="stx-range" onSubmit={(e) => { e.preventDefault(); onApply() }}>
            <label>{T.fromLabel}
              <input type="date" value={pick.from} onChange={(e) => onPick(e.target.value, pick.to)} />
            </label>
            <label>{T.toLabel}
              <input type="date" value={pick.to} onChange={(e) => onPick(pick.from, e.target.value)} />
            </label>
            <button className="dp-ok-btn">{T.apply}</button>
          </form>
        )}

        <div className="stx-kpis">
          {board.kpis.map((k) => (
            <KpiCard key={k.key} k={k} live={live} prevName={board.prev_name} />
          ))}
        </div>

        <div className="stx-row stx-row-a">
          <div className="fcard stx-chart">
            <div className="stx-card-h">
              <div>
                <h3>{metricName} {byWeek ? T.byWeeks : T.byDays}</h3>
                <span className="stx-sub">{d.period.short} · {T.hover}</span>
              </div>
              <div className="stx-seg stx-seg-s" role="group" aria-label={T.metric}>
                <button type="button" aria-pressed={metric === 'appts'}
                  className={metric === 'appts' ? 'on' : undefined}
                  onClick={() => setMetric('appts')}>{T.mAppts}</button>
                <button type="button" aria-pressed={metric === 'income'}
                  className={metric === 'income' ? 'on' : undefined}
                  onClick={() => setMetric('income')}>{T.mIncome}</button>
              </div>
            </div>
            <Columns
              labels={s.labels}
              hints={s.hints}
              wdays={wdays}
              values={metric === 'appts' ? s.appts : s.income}
              texts={metric === 'income' ? s.income_text : undefined}
              unit={T.unit}
              ariaLabel={`${metricName} ${byWeek ? T.byWeeks : T.byDays}`}
              empty={T.emptyChart}
            />
            <div className="stx-sum">
              <div><span>{T.total}</span><b>{sum.total}</b></div>
              <div><span>{T.avg}</span><b>{sum.avg}</b></div>
              <div><span>{byWeek ? T.bestWeek : T.bestDay}</span><b>{sum.best}</b></div>
            </div>
          </div>

          <div className="fcard stx-money">
            <div className="stx-card-h">
              <div><h3>{T.money}</h3><span className="stx-sub">{T.moneySub} · {d.period.short}</span></div>
            </div>
            <dl className="stx-dl">
              <div className="top"><dt>{T.cash}</dt><dd>{m.cash}</dd></div>
            </dl>
            <CategoryBar parts={board.parts.map((p) => ({ ...p, color: PAY_COLORS[p.key] ?? p.color }))} />
            <dl className="stx-dl">
              <div>
                <dt>{T.estimated}</dt>
                <dd>{m.estimated}<small><TrendLine t={m.estimated_trend} /></small></dd>
              </div>
              <div className={m.noshow ? 'bad' : undefined}>
                <dt>{T.loss} ({m.noshow})</dt><dd>{m.loss}</dd>
              </div>
              <div>
                <dt>{T.today}</dt>
                <dd>{m.today_cash} / {m.today_estimated}</dd>
              </div>
            </dl>
            {/* лист кассы — за СЕГОДНЯ: касса сходится за смену, а не за период */}
            <AppLink className="stx-link" href={m.link.href}>
              <Icon name={iconName(m.link.icon)} /> {m.link.label} ›
            </AppLink>
          </div>
        </div>

        <div className="stx-row stx-row-b">
          <div className="fcard stx-docs">
            <div className="stx-card-h">
              <div><h3>{T.doctors}</h3><span className="stx-sub">{T.doctorsSub} · {d.period.short}</span></div>
            </div>
            <div className="stx-scroll">
              <table className="stx-tbl">
                <thead>
                  <tr>
                    <th>{T.colDoctor}</th>
                    <th className="num">{T.colAppts}</th>
                    <th className="num">{T.colCame}</th>
                    <th>{T.colPresence}</th>
                    <th>{T.colBusy}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.doctors.map((doc) => (
                    <tr key={doc.id}>
                      <td>
                        <span className="stx-doc">
                          {/* кольцо цветом врача — тем же, что в календаре */}
                          <span className="dp-ring" style={{ borderColor: doc.color }}>
                            {doc.photo ? <img src={doc.photo} alt="" /> : doc.initials}
                          </span>
                          <span>
                            <b>{doc.name}</b>
                            <small>{doc.off ? T.inactive : doc.spec}</small>
                          </span>
                        </span>
                      </td>
                      <td className="num">{doc.n}</td>
                      <td className="num">{doc.came}</td>
                      <td>
                        <span className="stx-pct"><Meter pct={doc.pres} tone="var(--green)" /><em>{doc.pres}%</em></span>
                      </td>
                      <td>
                        <span className="stx-pct"><Meter pct={doc.pct} tone="var(--teal)" /><em>{doc.pct}%</em></span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="fcard stx-svc">
            <div className="stx-card-h">
              <div><h3>{T.services}</h3><span className="stx-sub">{T.servicesSub}</span></div>
            </div>
            {d.services.length === 0
              ? <p className="hint">{T.noServices}</p>
              : (
                <ul className="stx-barlist">
                  {d.services.map((sv) => (
                    <li key={sv.label}>
                      <span className="stx-bl-bar" style={{ width: `${sv.pct}%` }} />
                      <span className="stx-bl-l">{sv.label}</span>
                      <span className="stx-bl-v">
                        {sv.val_n > 0 && <small>{sv.val}</small>}
                        {sv.cnt}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
          </div>
        </div>

        <div className="fcard stx-act">
          <div className="stx-card-h">
            <div><h3>{T.activity}</h3><span className="stx-sub">{T.activitySub}</span></div>
          </div>
          {d.activity.length === 0
            ? <p className="hint">{T.noActivity}</p>
            : (
              <ul className="stx-feed">
                {d.activity.slice(0, 6).map((a, i) => (
                  <li key={i}>
                    <span className="stx-feed-t">{a.at}</span>
                    <span>
                      <b>{a.text}</b>
                      <small>
                        {a.patient_id !== null
                          ? <AppLink href={`/admin/patient/${a.patient_id}`}>{a.name}</AppLink>
                          : a.name} · {a.who}
                      </small>
                    </span>
                  </li>
                ))}
              </ul>
            )}
        </div>

        <p className="hint stx-note">{d.hint}</p>
      </div>
    </>
  )
}
