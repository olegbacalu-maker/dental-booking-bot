import { useCallback, useEffect, useRef, useState } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon, iconName } from '../../../components/Icon'
import { placeMenu, useMenuDismiss } from '../../../components/menu'
import type { ApiError } from '../../../types/api'
import { roCount } from '../../../utils/plural'
import type { PatientCard } from './card'
import { printHref } from './print'

/* Шапка фиши: аватар, имя и пилюли сервера, строка «41 ani · 069… · canal · pacient din 2026 · ID #5», кнопки
   «Sună», «Programează», «Fișa 043/e», «Adaugă» (меню того, что раньше было «Acțiuni rapide» Rezumat, — теперь
   из любого раздела) и печать; справа «Următoarea vizită» и «Medic curant» (выбор прямо здесь). Последний визит
   и счётчики «сколько» живут в Rezumat: на 1366×768 шапка с пятью плитками занимала две трети экрана над каждым
   разделом. Под шапкой — одна из трёх плашек анамнеза (риски / не собран / «neagă») и строка отзыва.
   Цифры, пилюли и «следующий» визит считает сервер. */
const T = {
  years: 'ani',
  channel: 'canal:',
  dosar: 'dosar',
  since: 'pacient din',
  idTitle:
    'Numărul intern al fișei în program (adresa paginii, copiile de siguranță, suport). Click = copiază',
  copied: 'copiat',
  telTitle: 'Click = copiază numărul',
  call: 'Sună',
  mail: 'E-mail',
  book: 'Programează',
  fisa: 'Fișa 043/e',
  add: 'Adaugă',
  addMenu: 'Adaugă în fișă',
  print: 'Printează fișa',
  anamneza: 'Anamneză',
  riskLabel: 'Riscuri medicale',
  denies: 'Neagă afecțiunile din chestionar',
  filledOn: 'completat',
  noneA: 'Anamneza nu a fost completată.',
  noneB: 'Întrebați pacientul înainte de tratament.',
  fill: 'Completează anamneza',
  next: 'Următoarea vizită',
  notBooked: 'neprogramat',
  doctor: 'Medic curant',
  ownDoctor: 'din fișa pacientului',
  setDoctor: 'Setează medicul',
  pickDoctor: 'Alege medicul curant',
  noDoctor: 'Fără medic curant',
  today: 'azi',
  yesterday: 'ieri',
  ago: 'acum',
  days: 'zile',
  // строка срока «Rechemări» (29.10, кадр К5)
  rcLast: 'ultima',
  rcNext: 'următoarea',
  rcOff: 'nu reamintim',
  rcUndo: 'Anulează',
  rcGo: 'Rechemări',
  bar: 'Pacientul fișei',
  risks: { one: '1 risc', few: '{n} riscuri', many: '{n} de riscuri' },
  noAnam: 'Anamneză lipsă',
} as const

/** Что добавить из меню «Adaugă»: экран решает, куда это ведёт. */
export type AddKind = 'visit' | 'plan' | 'pay' | 'doc' | 'note' | 'alert'
const ADD: { k: AddKind; icon: Parameters<typeof Icon>[0]['name']; label: string }[] = [
  { k: 'visit', icon: 'cal', label: 'Vizită nouă' },
  { k: 'plan', icon: 'tooth', label: 'Procedură în plan' },
  { k: 'pay', icon: 'money', label: 'Plată' },
  { k: 'doc', icon: 'upload', label: 'Document' },
  { k: 'note', icon: 'note', label: 'Notiță' },
  { k: 'alert', icon: 'sos', label: 'Atenționare medicală' },
]

interface Props {
  card: PatientCard
  onBook: () => void
  /** Пункт меню «Adaugă». */
  onAdd: (k: AddKind) => void
  /** «Completează anamneza» / «Anamneză ›»: вкладка «Date pacient», опросник раскрыт. */
  onAnamneza: () => void
  /** Медик курант выбран в шапке: действие фиши, отказ — ошибкой (выбор откатывается). */
  onDoctor: (name: string) => Promise<ApiError | null>
  /** Идёт действие фиши — выбор врача ждёт. */
  busy: boolean
  /** Адрес фиши с текущей вкладкой — «назад» на печатном листе. */
  back: string
  /** «Anulează» у строки «nu reamintim» (Rechemări): снять отметку stop. */
  onRecallClear: (service_id: string) => void
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

/** Меню «Adaugă»: то же устройство, что меню строки плана (закрытие — `useMenuDismiss`). */
function AddMenu({ x, y, onPick, onClose }: { x: number; y: number; onPick: (k: AddKind) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useMenuDismiss(ref, onClose)
  const { left, top } = placeMenu(x, y, 230, 40 + 34 * ADD.length)
  return (
    <div ref={ref} className="dp-cmenu" role="menu" aria-label={T.addMenu} style={{ left, top, width: 230 }}>
      {ADD.map((it) => (
        <button key={it.k} type="button" role="menuitem" className="dp-cmenu-i" onClick={() => { onClose(); onPick(it.k) }}>
          <Icon name={it.icon} /> {it.label}
        </button>
      ))}
    </div>
  )
}

export function HeroKpi({ card, onBook, onAdd, onAnamneza, onDoctor, busy, back, onRecallClear }: Props) {
  const { profile: p, hero } = card
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
  const [copied, setCopied] = useState<'' | 'id' | 'tel'>('')
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  /* Выбор врача, ушедший на сервер, виден, пока не приехала свежая фиша:
     привязан к фише, с которой начат (свежая показывает своё), отказ его
     снимает — в шапке снова прежний врач. */
  /* Шапка ушла под верхнюю панель — над разделом встаёт полоса с тем, кто перед врачом: имя, риски, долг,
     визит, «Programează». Полоса живёт в узле нулевой высоты (`.hero-stick`) и раскладку не трогает: ни
     прыжка при появлении, ни второго экземпляра кнопок, пока шапка видна. */
  const heroRef = useRef<HTMLDivElement>(null)
  const [stuck, setStuck] = useState(false)
  useEffect(() => {
    const el = heroRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const top = Math.round(document.querySelector('.main .top')?.getBoundingClientRect().height ?? 0)
    const io = new IntersectionObserver(([e]) => {
      if (e) setStuck(!e.isIntersecting && e.boundingClientRect.top < top)
    }, { rootMargin: `-${top}px 0px 0px 0px` })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  const [pick, setPick] = useState<{ card: PatientCard; v: string } | null>(null)
  const doc = pick && pick.card === card ? pick.v : p.primary_doctor
  const docs = card.options.doctors
  async function chooseDoctor(v: string) {
    setPick({ card, v })
    if (await onDoctor(v)) setPick(null)
  }

  function copy(what: 'id' | 'tel', text: string) {
    if (navigator.clipboard) void navigator.clipboard.writeText(text)
    setCopied(what)
    window.setTimeout(() => setCopied(''), 1200)
  }

  const meta = [
    p.age ? `${p.age} ${T.years}` : '',
    p.channel ? `${T.channel} ${p.channel}` : '',
    p.file_no ? `${T.dosar} ${p.file_no}` : '',
    `${T.since} ${p.year}`,
  ].filter(Boolean)
  const n = hero.next

  return (
    <>
      <div ref={heroRef} className="hero">
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
            {meta.slice(0, 1).map((m) => <span key={m}>{m}</span>)}
            {/* номер — текстом: стойка диктует и сверяет его, а кнопка «Sună» его не показывает */}
            {p.phone && (
              <span>
                <span className="hero-tel" role="button" tabIndex={0} title={T.telTitle} onClick={() => copy('tel', p.phone)}>
                  {copied === 'tel' ? T.copied : p.phone}
                </span>
              </span>
            )}
            {meta.slice(1).map((m) => <span key={m}>{m}</span>)}
            <span>
              <span className="idchip" role="button" tabIndex={0} title={T.idTitle} onClick={() => copy('id', String(card.id))}>
                {copied === 'id' ? T.copied : `ID #${card.id}`}
              </span>
            </span>
          </div>
          <div className="hero-acts">
            {p.phone && <AppLink href={`tel:${p.phone}`}><Icon name="phone" /> {T.call}</AppLink>}
            <button type="button" className="pri" onClick={onBook}><Icon name="cal" /> {T.book}</button>
            <AppLink href={printHref(card.id, 'fisa043', back)}><Icon name="file" /> {T.fisa}</AppLink>
            {p.email && <AppLink href={`mailto:${p.email}`}><Icon name="mail" /> {T.mail}</AppLink>}
            <button type="button" aria-haspopup="menu" aria-expanded={menu ? true : undefined}
              onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMenu(menu ? null : { x: r.left, y: r.bottom + 4 }) }}>
              <Icon name="plus" /> {T.add} <i className="dp-chev" aria-hidden="true" />
            </button>
            <button type="button" className="hero-ico" title={T.print} aria-label={T.print} onClick={() => window.print()}>
              <Icon name="print" />
            </button>
          </div>
        </div>
        <dl className="hero-side">
          <div>
            <dt>{T.next}</dt>
            <dd className="v num">{n ? `${n.date.slice(0, 5)} · ${n.time}` : '—'}</dd>
            <dd className="s">{n ? [n.service, n.doctor].filter(Boolean).join(' · ') : T.notBooked}</dd>
          </div>
          <div>
            <dt>{T.doctor}</dt>
            {/* Список выглядит значением, а не полем: имя врача и есть выбор.
                Врач, которого клиника убрала из списка, остаётся первым — иначе
                шапка показала бы чужое имя или пустоту. */}
            <dd className="v">
              <select className={`dp-hero-doc${doc ? '' : ' unset'}`} aria-label={T.pickDoctor}
                value={doc} disabled={busy} onChange={(e) => { void chooseDoctor(e.target.value) }}>
                {!doc && <option value="">{T.setDoctor}</option>}
                {doc && !docs.includes(doc) && <option value={doc}>{doc}</option>}
                {docs.map((d) => <option key={d} value={d}>{d}</option>)}
                {doc && <option value="">{T.noDoctor}</option>}
              </select>
            </dd>
            {doc && <dd className="s">{T.ownDoctor}</dd>}
          </div>
        </dl>
      </div>
      {menu && <AddMenu x={menu.x} y={menu.y} onPick={onAdd} onClose={closeMenu} />}
      <div className="hero-stick">
        {stuck && (
          <div className="hero-bar" role="region" aria-label={T.bar}>
            <span className="hero-bar-av" aria-hidden="true">{card.initials}</span>
            <b className="hero-bar-n">{card.name || '—'}</b>
            <span className="hero-bar-m">{[meta[0], p.phone].filter(Boolean).join(' · ')}</span>
            {risks.length > 0
              ? <span className="pill red" title={risks.join(' · ')}><Icon name="sos" /> {roCount(risks.length, T.risks)}</span>
              : card.anamneza.state === 'none' && <span className="pill orange"><Icon name="excl" /> {T.noAnam}</span>}
            {hero.pills.filter((pl) => pl.icon === 'money').map((pl) => (
              <span key={pl.text} className={`pill ${pl.tone}`}><Icon name="money" /> {pl.text}</span>
            ))}
            {n && <span className="hero-bar-next"><Icon name="cal" /> {n.date.slice(0, 5)} · {n.time}</span>}
            <span className="hero-bar-acts">
              <button type="button" className="pri" onClick={onBook}><Icon name="cal" /> {T.book}</button>
              <AppLink href={printHref(card.id, 'fisa043', back)}><Icon name="file" /> {T.fisa}</AppLink>
            </span>
          </div>
        )}
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
      ) : card.anamneza.denies ? (
        /* третье состояние (23.10): собран, рисков нет, пациент заявил, что
           ничем из списка не болеет — серым, с датой опроса */
        <div className="hero-risk none" role="note" aria-label={T.anamneza}>
          <Icon name="check" />
          <span className="hero-risk-list"><span>{T.denies}</span><span>{T.filledOn} {card.anamneza.when}</span></span>
          <button type="button" className="hero-risk-go" onClick={onAnamneza}>{T.anamneza} ›</button>
        </div>
      ) : null}
      {card.recall.length > 0 && (
        /* строка срока отзыва (кадр К5): по каждой услуге со сроком; слова
           просрочки — сервера; «nu reamintim · Anulează» — только с правом */
        <div className="hero-rc" role="note" aria-label={T.rcGo}>
          <Icon name="refresh" />
          {card.recall.map((r) => (
            <span key={r.service_id} className={r.stop ? 'off' : r.late_days > 0 ? 'late' : ''}>
              <b>{r.service}</b>: {T.rcLast} {r.last} · {T.rcNext} ~{r.next}
              {r.stop
                ? <em> · {T.rcOff}{r.can_clear && <> · <button type="button" className="hero-rc-undo" disabled={busy}
                    onClick={() => onRecallClear(r.service_id)}>{T.rcUndo}</button></>}</em>
                : r.late_days > -15 ? <em> · {r.late}</em> : null}
            </span>
          ))}
        </div>
      )}
    </>
  )
}
