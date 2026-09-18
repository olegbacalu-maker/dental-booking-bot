import { useRef, useState } from 'react'
import { Icon, iconName } from '../../../components/Icon'
import { hideDialog, showDialog } from './dialog'
import { mdl, type PatientCard, type PlanItem, type Visit } from './card'

/* Слова шапки и пяти цифр — те же, что на старой странице; сами цифры,
   пилюли, «последний» и «следующий» визит посчитаны на сервере. */
const T = {
  years: 'ani',
  dosar: 'dosar',
  since: 'Pacient din',
  idTitle:
    'Numărul intern al fișei în program (adresa paginii, copiile de siguranță, suport). Click = copiază',
  copied: 'copiat',
  call: 'Sună',
  mail: 'E-mail',
  book: 'Programează',
  fisa: 'Fișa 043/e',
  last: 'Ultima vizită',
  noVisits: 'încă fără vizite',
  doctor: 'Medic curant',
  ownDoctor: 'din fișa pacientului',
  noDoctor: 'nesetat',
  kpi: {
    visits: ['Vizite în total', 'din'],
    active: ['Proceduri active', 'în planul de tratament'],
    last: ['Ultima vizită'],
    next: ['Următoarea vizită', 'neprogramat'],
    done: ['Proceduri finalizate', 'istoric complet'],
  },
  today: 'azi',
  days: 'zile',
  ago: 'acum',
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
}

/** Давность последнего визита словами старой страницы: «azi» / «N zile». */
export function daysLabel(days: number | null): string {
  if (days === null) return '—'
  return days ? `${days} ${T.days}` : T.today
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

export function HeroKpi({ card, onBook }: Props) {
  const { profile: p, hero, kpi, plan } = card
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
    p.channel,
    p.file_no ? `${T.dosar} ${p.file_no}` : '',
    `${T.since} ${p.year}`,
  ].filter(Boolean)

  const live = card.visits.live
  const active = plan.items.filter((it) => card.options.tab_states.act?.includes(it.status))
  const done = plan.items.filter((it) => it.status === 'finalizat')
  const lastRow = live.find((v) => hero.last && v.when.startsWith(hero.last.date)) ?? null
  const nextRow = live.find((v) => v.is_next) ?? null

  const kpis: { key: PanelKey; icon: string; value: string; label: string; sub: string }[] = [
    { key: 'visits', icon: 'clipboard', value: String(kpi.visits), label: T.kpi.visits[0], sub: `${T.kpi.visits[1]} ${p.year}` },
    { key: 'active', icon: 'tooth', value: String(kpi.active), label: T.kpi.active[0], sub: T.kpi.active[1] },
    { key: 'last', icon: 'clock', value: hero.last ? daysLabel(hero.days_ago) : '—', label: T.kpi.last[0], sub: hero.last ? hero.last.date : '—' },
    { key: 'next', icon: 'cal', value: hero.next ? hero.next.date.slice(0, 5) : '—', label: T.kpi.next[0], sub: hero.next ? hero.next.time : T.kpi.next[1] },
    { key: 'done', icon: 'check', value: String(kpi.done), label: T.kpi.done[0], sub: T.kpi.done[1] },
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
        <a className="lmore" href="#plan" onClick={close}>{T.openPlan} ›</a>
      </>
    )
  } else if (panel === 'last') {
    body = lastRow ? (
      <>
        <VisitRow v={lastRow} />
        <p className="hint">{hero.days_ago ? `${T.ago} ${hero.days_ago} ${T.days}` : T.today}</p>
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
          <h2>{card.name || '—'}</h2>
          <div className="hero-meta">
            {meta.map((m) => <span key={m}>{m}</span>)}
            <span>
              <span className="idchip" role="button" tabIndex={0} title={T.idTitle} onClick={copyId}>
                {copied ? T.copied : `ID #${card.id}`}
              </span>
            </span>
          </div>
          <div className="hero-badges">
            {hero.pills.map((pl, i) => (
              <span key={i} className={`pill ${pl.tone}`}><Icon name={iconName(pl.icon)} /> {pl.text}</span>
            ))}
          </div>
          <div className="hero-acts">
            {p.phone && <a href={`tel:${p.phone}`}><Icon name="phone" /> {T.call}</a>}
            {p.email && <a href={`mailto:${p.email}`}><Icon name="mail" /> {T.mail}</a>}
            <button type="button" onClick={onBook}><Icon name="cal" /> {T.book}</button>
            <a href={`/admin/patient/${card.id}/fisa043`}><Icon name="file" /> {T.fisa}</a>
          </div>
        </div>
        <div className="hero-side">
          <div className="hs">
            <span>{T.last}</span>
            <b>{hero.last ? hero.last.date : '—'}</b>
            <div className="dp-hs-sub">{hero.last ? hero.last.service : T.noVisits}</div>
          </div>
          <div className="hs">
            <span>{T.doctor}</span>
            <b>{p.primary_doctor || '—'}</b>
            <div className="dp-hs-sub">{p.primary_doctor ? T.ownDoctor : T.noDoctor}</div>
          </div>
        </div>
      </div>
      <div className="kpi5">
        {kpis.map((k) => (
          <button key={k.key} type="button" className="kpi" title={`${k.label} — ${T.clickHint}`} onClick={() => open(k.key)}>
            <span className="ki"><Icon name={iconName(k.icon)} /></span>
            <div className="dp-kpi-body">
              <b>{k.value}</b>
              <span>{k.label}</span>
              <small>{k.sub}</small>
            </div>
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
