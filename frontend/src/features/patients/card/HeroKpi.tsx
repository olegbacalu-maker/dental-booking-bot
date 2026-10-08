import { useRef, useState } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon, iconName } from '../../../components/Icon'
import { hideDialog, showDialog } from './dialog'
import { mdl, type PatientCard, type PlanItem, type Visit } from './card'
import { printHref } from './print'

/* Шапка фиши по макету Олега (08.10, промпт 2): карточка с аватаром 80px,
   имя и плашки, строка «41 ani · canal: recepție · pacient din 2026 · ID #5»,
   кнопки «Sună», «Programează», «Fișa 043/e»; справа «Ultima vizită» и
   «Medic curant» («Setează medicul», когда не задан). Под шапкой — баннер
   «Anamneza nu a fost completată…» (role=alert) или полоса рисков; ниже пять
   карточек-цифр без значков. Слова — те же, что на старой странице; сами
   цифры, пилюли, «последний» и «следующий» визит посчитаны на сервере. */
const T = {
  years: 'ani',
  channel: 'canal:',
  dosar: 'dosar',
  since: 'pacient din',
  idTitle:
    'Numărul intern al fișei în program (adresa paginii, copiile de siguranță, suport). Click = copiază',
  copied: 'copiat',
  call: 'Sună',
  mail: 'E-mail',
  book: 'Programează',
  fisa: 'Fișa 043/e',
  anamneza: 'Anamneză',
  riskLabel: 'Riscuri medicale',
  noneA: 'Anamneza nu a fost completată.',
  noneB: 'Întrebați pacientul înainte de tratament.',
  fill: 'Completează anamneza',
  last: 'Ultima vizită',
  noVisits: 'încă fără vizite',
  doctor: 'Medic curant',
  ownDoctor: 'din fișa pacientului',
  setDoctor: 'Setează medicul',
  kpi: {
    visits: ['Vizite în total', 'din'],
    active: ['Proceduri active', 'în planul de tratament'],
    last: ['Ultima vizită'],
    next: ['Următoarea vizită', 'neprogramat'],
    done: ['Proceduri finalizate', 'istoric complet'],
  },
  today: 'azi',
  yesterday: 'ieri',
  ago: 'acum',
  days: 'zile',
  clickHint: 'click pentru detalii',
  panels: {
    visits: 'Toate vizitele',
    active: 'Proceduri active',
    last: 'Ultima vizită',
    next: 'Următoarea vizită',
    done: 'Proceduri finalizate',
  },
  cancelled: 'anulate (nu se numără)',
  emptyVisits: 'încă fără vizite',
  emptyPlan: 'planul este gol',
  emptyDone: 'încă nimic finalizat',
  noNext: 'nicio vizită programată',
  openPlan: 'Deschide planul de tratament',
  bookNow: 'Programează acum',
  tooth: 'dinte',
  close: 'Închide',
} as const

type PanelKey = 'visits' | 'active' | 'last' | 'next' | 'done'

interface Props {
  card: PatientCard
  onBook: () => void
  /** «Deschide planul» из окна активных позиций — вкладка плана (B6) */
  onPlan: () => void
  /** «Completează anamneza» / «Anamneză ›»: вкладка «Date pacient», опросник раскрыт. */
  onAnamneza: () => void
  /** «Setează medicul» — вкладка «Date pacient», форма профиля раскрыта. */
  onDoctor: () => void
  /** Адрес фиши с текущей вкладкой — «назад» на печатном листе. */
  back: string
}

/** Давность последнего визита словами: «azi» / «ieri» / «acum N zile».
 *  ⚠️ Дни считает сервер по КАЛЕНДАРЮ клиники (card.days_ago): визит вчера
 *  вечером — «ieri», а не «azi», сколько бы часов ни прошло. */
export function daysLabel(days: number | null): string {
  if (days === null) return '—'
  if (days === 0) return T.today
  if (days === 1) return T.yesterday
  return `${T.ago} ${days} ${T.days}`
}

function VisitRow({ v }: { v: Visit }) {
  return (
    <div className="lrow">
      <span className="lk">{v.when.replace(' ', ' · ')}</span>
      <b>{v.service}</b>
      <small>{v.doctor} · {v.status_label}</small>
    </div>
  )
}

function PlanRow({ it, labels }: { it: PlanItem; labels: Record<string, string> }) {
  return (
    <div className="lrow">
      <span className="lk">{it.tooth ? `${T.tooth} ${it.tooth}` : '—'}</span>
      <b>{it.procedure}</b>
      <small>
        {it.doctor || '—'} · {labels[it.status] ?? it.status} · {it.price ? `${mdl(it.price)} MDL` : '—'}
      </small>
    </div>
  )
}

export function HeroKpi({ card, onBook, onPlan, onAnamneza, onDoctor, back }: Props) {
  const { profile: p, hero, kpi, plan } = card
  /* ⭐ Риски — ОДНОЙ полосой под шапкой, на всех вкладках (01.10). До B6
     анамнез стоял под предупреждениями на одной длинной странице; с вкладками
     аллергия, записанная в анамнезе, была видна только в «Date pacient», а
     «Atenționări» на Rezumat говорили «fără atenționări». Порядок: явные
     предупреждения, галочки опросника, свободные поля (там чаще всего и
     живёт аллергия). */
  const risks = [
    ...card.alerts.map((al) => `${al.label}: ${al.text}`),
    ...card.anamneza.marked,
    ...card.anamneza.free.map((f) => `${f.short}: ${f.text}`),
  ]
  const dlg = useRef<HTMLDialogElement>(null)
  const [panel, setPanel] = useState<PanelKey | null>(null)
  const [copied, setCopied] = useState(false)

  function open(k: PanelKey) {
    setPanel(k)
    showDialog(dlg.current)
  }
  function close() {
    hideDialog(dlg.current)
    setPanel(null)
  }
  function copyId() {
    if (navigator.clipboard) void navigator.clipboard.writeText(String(card.id))
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }

  const meta = [
    p.age ? `${p.age} ${T.years}` : '',
    p.channel ? `${T.channel} ${p.channel}` : '',
    p.file_no ? `${T.dosar} ${p.file_no}` : '',
    `${T.since} ${p.year}`,
  ].filter(Boolean)

  const live = card.visits.live
  const active = plan.items.filter((it) => card.options.tab_states.act?.includes(it.status))
  const done = plan.items.filter((it) => it.status === 'finalizat')
  const lastRow = live.find((v) => hero.last && v.when.startsWith(hero.last.date)) ?? null
  const nextRow = live.find((v) => v.is_next) ?? null

  /* «Ultima vizită» — ДАТОЙ, давность словом под ней (макет 08.10: «azi» при
     дате вчерашнего дня читалось как ошибка). */
  const kpis: { key: PanelKey; value: string; label: string; sub: string }[] = [
    { key: 'visits', value: String(kpi.visits), label: T.kpi.visits[0], sub: `${T.kpi.visits[1]} ${p.year}` },
    { key: 'active', value: String(kpi.active), label: T.kpi.active[0], sub: T.kpi.active[1] },
    { key: 'last', value: hero.last ? hero.last.date : '—', label: T.kpi.last[0], sub: hero.last ? daysLabel(hero.days_ago) : T.noVisits },
    { key: 'next', value: hero.next ? hero.next.date.slice(0, 5) : '—', label: T.kpi.next[0], sub: hero.next ? hero.next.time : T.kpi.next[1] },
    { key: 'done', value: String(kpi.done), label: T.kpi.done[0], sub: T.kpi.done[1] },
  ]

  let body = null
  if (panel === 'visits') {
    body = (
      <>
        {live.length ? live.map((v) => <VisitRow key={v.id} v={v} />) : <p className="hint dp-m0">— {T.emptyVisits} —</p>}
        {kpi.canc > 0 && <p className="hint">+ {kpi.canc} {T.cancelled}</p>}
      </>
    )
  } else if (panel === 'active') {
    body = (
      <>
        {active.length ? active.map((it) => <PlanRow key={it.id} it={it} labels={card.options.plan_labels} />) : <p className="hint dp-m0">— {T.emptyPlan} —</p>}
        <button type="button" className="lmore" onClick={() => { close(); onPlan() }}>{T.openPlan} ›</button>
      </>
    )
  } else if (panel === 'last') {
    body = lastRow ? (
      <>
        <VisitRow v={lastRow} />
        <p className="hint">{daysLabel(hero.days_ago)}</p>
      </>
    ) : <p className="hint dp-m0">— {T.emptyVisits} —</p>
  } else if (panel === 'next') {
    body = nextRow ? <VisitRow v={nextRow} /> : (
      <>
        <p className="hint dp-m0">— {T.noNext} —</p>
        <button type="button" className="lbtn" onClick={() => { close(); onBook() }}>
          <Icon name="cal" /> {T.bookNow}
        </button>
      </>
    )
  } else if (panel === 'done') {
    body = done.length ? done.map((it) => <PlanRow key={it.id} it={it} labels={card.options.plan_labels} />) : <p className="hint dp-m0">— {T.emptyDone} —</p>
  }

  return (
    <>
      <div className="hero">
        <div className="hero-av">{card.initials}</div>
        <div className="hero-id">
          <div className="hero-title">
            <h2>{card.name || '—'}</h2>
            <div className="hero-badges">
              {hero.pills.map((pl, i) => (
                <span key={i} className={`pill ${pl.tone}`}><Icon name={iconName(pl.icon)} /> {pl.text}</span>
              ))}
            </div>
          </div>
          <div className="hero-meta">
            {meta.map((m) => <span key={m}>{m}</span>)}
            <span>
              <span className="idchip" role="button" tabIndex={0} title={T.idTitle} onClick={copyId}>
                {copied ? T.copied : `ID #${card.id}`}
              </span>
            </span>
          </div>
          {/* «Anamneză» из шапки снята (08.10): за неё отвечают баннер под
              шапкой и полоса рисков */}
          <div className="hero-acts">
            {p.phone && <AppLink href={`tel:${p.phone}`}><Icon name="phone" /> {T.call}</AppLink>}
            <button type="button" className="pri" onClick={onBook}><Icon name="cal" /> {T.book}</button>
            <AppLink href={printHref(card.id, 'fisa043', back)}><Icon name="file" /> {T.fisa}</AppLink>
            {p.email && <AppLink href={`mailto:${p.email}`}><Icon name="mail" /> {T.mail}</AppLink>}
          </div>
        </div>
        <dl className="hero-side">
          <div>
            <dt>{T.last}</dt>
            <dd className="v num">{hero.last ? hero.last.date : '—'}</dd>
            <dd className="s">{hero.last ? hero.last.service : T.noVisits}</dd>
          </div>
          <div>
            <dt>{T.doctor}</dt>
            <dd className="v">{p.primary_doctor || '—'}</dd>
            <dd className="s">
              {p.primary_doctor
                ? T.ownDoctor
                : <button type="button" className="dp-link" onClick={onDoctor}>{T.setDoctor}</button>}
            </dd>
          </div>
        </dl>
      </div>
      {risks.length > 0 ? (
        <div className="hero-risk" role="note" aria-label={T.riskLabel}>
          <Icon name="sos" />
          <span className="hero-risk-list">{risks.map((r, i) => <span key={i}>{r}</span>)}</span>
          <button type="button" className="hero-risk-go" onClick={onAnamneza}>{T.anamneza} ›</button>
        </div>
      ) : card.anamneza.state === 'none' ? (
        /* баннер-предупреждение (макет 08.10): анамнез не собирали */
        <div className="dp-abanner" role="alert">
          <Icon name="excl" />
          <span><b>{T.noneA}</b> {T.noneB}</span>
          <button type="button" className="dp-btn" onClick={onAnamneza}>{T.fill}</button>
        </div>
      ) : null}
      <div className="kpi5">
        {kpis.map((k) => (
          <button key={k.key} type="button" className="kpi" title={`${k.label} — ${T.clickHint}`} onClick={() => open(k.key)}>
            <span className="kpi-l">{k.label}</span>
            <b>{k.value}</b>
            <small>{k.sub}</small>
          </button>
        ))}
      </div>
      <dialog ref={dlg} className="wide" onClose={() => setPanel(null)}>
        <div className="dlg-head">
          <span>{panel ? T.panels[panel] : '—'}</span>
          <button type="button" onClick={close} aria-label={T.close}><Icon name="close" /></button>
        </div>
        <div className="lbody">{body}</div>
      </dialog>
    </>
  )
}
