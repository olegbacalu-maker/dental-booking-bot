import { useCallback, useState } from 'react'
import { Count } from '../../components/Count'
import { Icon, iconName } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Spark } from '../../components/Spark'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { canAnimate } from '../../utils/fx'
import { t } from '../../utils/i18n'
import { Donut, Gauge, LineDays } from './StatsCharts'
import { stats, type StatsData, type Trend as TrendModel } from './stats'

/* Подписи экрана. Всё, что несёт ЦИФРУ или её объяснение (тренды, суммы,
   период, подписи источников), приходит с сервера: деньги форматирует он же,
   и второй форматировщик разошёлся бы с печатным отчётом кассы. */
const T = t('stats', {
  sources: 'Surse programări',
  total: 'Total',
  occupancy: 'Grad de ocupare',
  doctors: 'Performanța medicilor',
  services: 'Top servicii',
  activity: 'Activitate recentă',
  noServices: '— încă fără programări —',
  noActivity: '— încă nimic —',
  colDoctor: 'Medic',
  colAppts: 'Programări',
  colCame: 'Au venit',
  colPresence: 'Rata prezenței',
  colBusy: 'Ocupare',
  totalAppts: 'Total programări',
  presence: 'Rata de prezență',
  noshow: 'Neprezentări',
  wait: 'Așteptare medie',
  inactive: '· inactiv',
  excel: 'Export Excel',
  panel: 'Panou',
  apply: 'OK',
  unchanged: 'neschimbat',
  fromLabel: 'De la',
  toLabel: 'Până la',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const)

/**
 * Сравнение с предыдущим периодом. ⛔ Цвет берётся из `dir`, а НЕ из знака
 * числа: рост неявок — стрелка вверх и КРАСНЫЙ, и вычисли цвет из знака, он
 * позеленел бы ровно там, где всё плохо.
 */
function Trend({ trend }: { trend: TrendModel }) {
  if (!trend.dir) {
    return <span className="trend">{T.unchanged} {trend.label}</span>
  }
  return (
    <span className="trend">
      <span className={trend.dir}>
        {trend.icon && <><Icon name={iconName(trend.icon)} /> </>}
        {trend.value}
      </span>
      {' '}{trend.label}{trend.note}
    </span>
  )
}

/** Доля полоской: число слева, шкала справа — как на старой странице. */
function Bar({ pct }: { pct: number }) {
  return (
    <div className="an-bar">
      <span>{pct}%</span>
      <div className="statbar"><div style={{ width: `${Math.min(pct, 100)}%` }} /></div>
    </div>
  )
}

interface Props {
  from?: string
  to?: string
  navigate?: (url: string) => void
}

export function StatsScreen({ from = '', to = '', navigate = defaultNavigate }: Props) {
  const [span, setSpan] = useState({ from, to })
  const load = useCallback(
    (signal: AbortSignal) => stats.get(span.from, span.to, signal), [span])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [draft, setDraft] = useState<{ from: string; to: string } | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const live = canAnimate()

  /* Адрес повторяет отбор — как у старой страницы: перезагрузка, закладка и
     `?ui=legacy` открывают ТОТ ЖЕ период. */
  function remember(f: string, t2: string) {
    const url = f && t2 ? `/admin/stats?from=${f}&to=${t2}` : '/admin/stats'
    try { window.history.replaceState(null, '', url) } catch { /* jsdom */ }
  }

  function go(f: string, t2: string) {
    setSpan({ from: f, to: t2 })
    setDraft(null)
    remember(f, t2)
  }

  async function apply(f: string, t2: string) {
    /* ⛔ Негодный период НЕ сбрасывает экран на «последние 7 дней», как делал
       редирект старой страницы: человек промахнулся по сегменту года, и
       ответом обязан быть отказ с названной причиной, а не молча другой
       период под теми же цифрами в полях. */
    try {
      const r = await stats.get(f, t2)
      replace(r.data)
      setSpan({ from: f, to: t2 })
      setDraft(null)
      remember(f, t2)
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    }
  }

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }
  if (state.status === 'loading') {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const d: StatsData = state.data
  const pick = draft ?? { from: d.period.from, to: d.period.to }
  return (
    <section className="dp-react-root">
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
      <div className="nav">
        <b>{d.period.label}</b>
        {d.presets.map((p) => (
          <a
            key={p.key}
            href={`/admin/stats?from=${p.from}&to=${p.to}`}
            onClick={(e) => { e.preventDefault(); go(p.from, p.to) }}
          >{p.label}</a>
        ))}
        <form
          className="dpickf"
          onSubmit={(e) => { e.preventDefault(); void apply(pick.from, pick.to) }}
        >
          <input
            className="dpick" type="date" value={pick.from} aria-label={T.fromLabel}
            onChange={(e) => setDraft({ ...pick, from: e.target.value })}
          />
          <input
            className="dpick" type="date" value={pick.to} aria-label={T.toLabel}
            onChange={(e) => setDraft({ ...pick, to: e.target.value })}
          />
          <button className="searchf dp-ok-btn">{T.apply}</button>
        </form>
        <a href={d.export_url}><Icon name="download" /> {T.excel}</a>
        <a href="/admin"><Icon name="home" /> {T.panel}</a>
      </div>

      <div className="tiles">
        {d.tiles.map((tl) => (
          <div key={tl.key} className={`tile sp${tl.bad ? ' bad' : ''}`}>
            <span className="ico" style={{ background: tl.soft, color: tl.tone }}>
              <Icon name={iconName(tl.icon)} />
            </span>
            <div>
              <Count value={tl.value} live={live} />
              <span>{tl.label}</span>
              <Trend trend={tl.trend} />
            </div>
            <Spark series={tl.series} tone={tl.tone} />
          </div>
        ))}
      </div>

      <div className="an-grid">
        <div className="an-main">
          <div className="fcard an-chart">
            <h3>{d.chart.title} <small>{d.chart.sub}</small></h3>
            <LineDays labels={d.chart.labels} values={d.chart.values} tone="var(--teal)" />
            <div className="an-foot">
              <div>
                <span>{T.totalAppts}</span><b>{d.chart.total}</b>
                <Trend trend={d.chart.total_trend} />
              </div>
              <div>
                <span>{T.presence}</span><b>{d.chart.present_pct}%</b>
                <div className="statbar">
                  <div style={{ width: `${d.chart.present_pct}%` }} />
                </div>
              </div>
              <div>
                <span>{T.noshow}</span><b>{d.chart.noshow}</b>
                <small>{d.chart.loss}</small>
              </div>
              <div>
                <span>{T.wait}</span><b data-wait="">{d.chart.wait.text}</b>
                <small>{d.chart.wait.sub}</small>
              </div>
            </div>
          </div>

          <div className="fcard">
            <h3>{T.doctors}</h3>
            <table className="list an-tbl">
              <thead>
                <tr>
                  <th>{T.colDoctor}</th><th>{T.colAppts}</th><th>{T.colCame}</th>
                  <th>{T.colPresence}</th><th>{T.colBusy}</th>
                </tr>
              </thead>
              <tbody>
                {d.doctors.map((doc) => (
                  <tr key={doc.name}>
                    <td>
                      {doc.name}
                      {doc.off && <small className="dp-muted"> {T.inactive}</small>}
                    </td>
                    <td>{doc.n}</td>
                    <td>{doc.came}</td>
                    <td><Bar pct={doc.pres} /></td>
                    <td><Bar pct={doc.pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="an-side">
          {d.sources.show && (
            <div className="fcard">
              <h3>{T.sources}</h3>
              <div className="an-donut">
                <Donut label={T.total} parts={d.sources.parts} />
                <div className="an-legend">
                  {d.sources.parts.map((p) => (
                    <div key={p.label} className="an-src">
                      <i style={{ background: p.color }} />{p.label}
                      <b>{p.value}</b><small>{p.pct}%</small>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="fcard an-gauge">
            <h3>{T.occupancy}</h3>
            <Gauge pct={d.occupancy.pct} tone="var(--teal)" label={T.occupancy} />
            <small>{d.occupancy.note}</small>
          </div>

          {d.money.map((m) => (
            <div key={m.key} className="fcard an-money">
              <h3>{m.title} <small>{m.sub}</small></h3>
              <Count value={m.value} live={live} suffix={m.suffix} group />
              <Trend trend={m.trend} />
              <small>
                {m.note.map((n, i) => (
                  <span key={i}>
                    {i > 0 && ' · '}
                    {n.icon && <><Icon name={iconName(n.icon)} /> </>}{n.t}
                  </span>
                ))}
              </small>
              {m.link && (
                <a className="ag-all" href={m.link.href}>
                  <Icon name={iconName(m.link.icon)} /> {m.link.label}
                </a>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="an-grid2">
        <div className="fcard">
          <h3>{T.services}</h3>
          {d.services.length === 0
            ? <p className="hint">{T.noServices}</p>
            : d.services.map((s) => (
              <div key={s.label} className="an-svc">
                <div className="an-svc-t">
                  <b>{s.label}</b><span>{s.cnt} prog. · {s.val}</span>
                </div>
                <div className="statbar"><div style={{ width: `${s.pct}%` }} /></div>
              </div>
            ))}
        </div>
        <div className="fcard">
          <h3>{T.activity}</h3>
          {d.activity.length === 0
            ? <p className="hint">{T.noActivity}</p>
            : d.activity.map((a, i) => (
              <div key={i} className="an-act">
                <div className="an-act-b">
                  <b>{a.text}</b>
                  <small>
                    {a.patient_id !== null
                      ? <a href={`/admin/patient/${a.patient_id}`}>{a.name}</a>
                      : a.name} · {a.who}
                  </small>
                </div>
                <span>{a.at}</span>
              </div>
            ))}
        </div>
      </div>

      <p className="hint">{d.hint}</p>
    </section>
  )
}
