import { useLocation } from 'react-router'
import { Icon } from '../../components/Icon'
import {
  filtersToQuery, isDirty, type Filters, type PatientRow, type PatientsPage,
  type PatientsSummary,
} from './patients'

/* Таблица списка, пустые виды и страницы — те же классы и слова, что у старой
   страницы «Pacienți» (panel.css .pl-*). Цифры и статусы — с сервера. */
const T = {
  patient: 'Pacient',
  phone: 'Telefon',
  birth: 'Data nașterii',
  doctor: 'Medic',
  last: 'Ultima vizită',
  sold: 'Sold',
  status: 'Status',
  noPhone: 'Fără telefon',
  years: 'ani',
  next: 'Următoarea vizită',
  derivedDoctor: 'Medicul ultimei vizite — în fișă nu este setat un medic curant',
  advance: 'avans',
  mdl: 'MDL',
  preview: 'Previzualizare',
  openCard: 'Deschide fișa',
  nothing: 'Nimic găsit',
  nothingHint: 'Încercați alt nume, telefon sau scoateți filtrele.',
  seeAll: 'Vezi toți pacienții',
  allArchived: 'Toți pacienții sunt în arhivă',
  archivedOne: 'fișă arhivată',
  archivedMany: 'fișe arhivate',
  nobodyLeft: 'În listă nu rămâne nimeni:',
  showArchive: 'Arată arhiva',
  noPatients: 'Încă niciun pacient',
  noPatientsHint: 'Fișele apar aici odată cu prima programare — din registru sau din bot.',
  addFirst: '＋ Adaugă primul pacient',
  showing: 'Afișare',
  of: 'din',
  patients: 'pacienți',
  hiddenOne: 'arhivat',
  hiddenMany: 'arhivați',
  show: 'arată',
  perPage: '/ pagină',
} as const

/** 2550 → «2 550» — разделитель тысяч, как `_pl_money`. */
export function money(n: number): string {
  return String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

interface Props {
  page: PatientsPage
  summary: PatientsSummary
  filters: Filters
  selected: number | null
  onFilters: (f: Filters) => void
  onPeek: (id: number) => void
  onAdd: () => void
}

export function PatientsTable({ page, summary, filters, selected, onFilters, onPeek, onAdd }: Props) {
  const statuses = new Map(summary.statuses.map((s) => [s.id, s]))
  const channels = new Map(summary.channels.map((c) => [c.id, c.label]))
  // ⛔ Адрес — у роутера (B2.3), а не `window.location`: второй источник
  // адреса разошёлся бы с первым при первом же переходе без перезагрузки.
  const { pathname } = useLocation()

  function go(next: Partial<Filters>) {
    onFilters({ ...filters, ...next })
  }

  /* Ссылки остаются настоящими адресами (средняя кнопка мыши открывает тот же
     список во вкладке); обычный клик перехватывается и не перезагружает страницу. */
  function link(next: Partial<Filters>, withPage = true) {
    const f = { ...filters, ...next }
    return {
      href: `${pathname}${filtersToQuery(f, withPage)}`,
      onClick: (e: React.MouseEvent) => {
        e.preventDefault()
        onFilters(f)
      },
    }
  }

  function head(key: string, label: string) {
    return (
      <th>
        <a {...link({ sort: key, page: 1 })}>
          {label}{filters.sort === key && <> <Icon name="caret-d" /></>}
        </a>
      </th>
    )
  }

  function sold(debt: number) {
    if (!debt) return <span className="dim">—</span>
    if (debt > 0) return <span className="pl-badge bad">{money(debt)} {T.mdl}</span>
    return <span className="pl-badge act">{T.advance} {money(debt)}</span>
  }

  function doctor(p: PatientRow) {
    if (!p.doctor) return '—'
    if (p.doctor_own) return p.doctor
    return <span className="dim" title={T.derivedDoctor}>{p.doctor}</span>
  }

  function row(p: PatientRow) {
    const st = statuses.get(p.status)
    return (
      <tr
        key={p.id}
        id={`plr${p.id}`}
        className={selected === p.id ? 'on' : undefined}
        onClick={() => onPeek(p.id)}
      >
        <td>
          <div className="pl-who">
            <span className="pl-av">{p.initials}</span>
            <div className="pl-nm">
              <b>{p.name || '—'}</b>
              {p.email
                ? <small>{p.email}</small>
                : <small className="dim">{channels.get(p.channel) ?? p.channel}</small>}
            </div>
          </div>
        </td>
        <td>
          {p.phone || <span className="pl-notel" title={T.noPhone}><Icon name="phone-off" /></span>}
        </td>
        <td className="pl-hide">
          {p.birth || '—'}{p.age ? <small> · {p.age} {T.years}</small> : null}
        </td>
        <td>{doctor(p)}</td>
        <td>
          {p.last || '—'}
          {p.next && <small className="nx" title={T.next}>› {p.next}</small>}
        </td>
        <td>{sold(p.debt)}</td>
        <td><span className={`pl-badge ${st?.cls ?? ''}`}>{st?.label ?? p.status}</span></td>
        <td className="pl-acts">
          <button
            type="button"
            title={T.preview}
            onClick={(e) => { e.stopPropagation(); onPeek(p.id) }}
          >
            <Icon name="eye" />
          </button>
          <a
            href={`/admin/patient/${p.id}`}
            title={T.openCard}
            onClick={(e) => e.stopPropagation()}
          >
            <Icon name="id" />
          </a>
        </td>
      </tr>
    )
  }

  let table
  if (page.rows.length) {
    table = (
      <div className="pl-scroll">
        <table className="pl-tbl">
          <thead>
            <tr>
              {head('name', T.patient)}
              <th>{T.phone}</th>
              <th className="pl-hide">{T.birth}</th>
              <th>{T.doctor}</th>
              {head('last', T.last)}
              {head('debt', T.sold)}
              <th>{T.status}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>{page.rows.map(row)}</tbody>
        </table>
      </div>
    )
  } else if (isDirty(filters)) {
    table = (
      <div className="pl-empty">
        <Icon name="search" />
        <b>{T.nothing}</b>
        <span>{T.nothingHint}</span>
        <a className="pl-btn" href={pathname} onClick={(e) => {
          e.preventDefault()
          onFilters({ ...filters, q: '', med: '', st: '', ch: '', dat: '', page: 1 })
        }}>{T.seeAll}</a>
      </div>
    )
  } else if (page.n_arh) {
    // все живые фиши в архиве: «картотека пуста» здесь была бы неправдой
    table = (
      <div className="pl-empty">
        <Icon name="box" />
        <b>{T.allArchived}</b>
        <span>
          {T.nobodyLeft} {page.n_arh} {page.n_arh === 1 ? T.archivedOne : T.archivedMany}.
        </span>
        <a className="pl-btn" {...link({ st: 'arhivat', page: 1 })}>{T.showArchive}</a>
      </div>
    )
  } else {
    table = (
      <div className="pl-empty">
        <Icon name="users" />
        <b>{T.noPatients}</b>
        <span>{T.noPatientsHint}</span>
        <button type="button" className="pl-btn primary" onClick={onAdd}>{T.addFirst}</button>
      </div>
    )
  }

  let pager = null
  if (page.total) {
    const first = (page.page - 1) * page.per + 1
    const lastN = Math.min(page.page * page.per, page.total)
    const nums: React.ReactNode[] = []
    let gap = false
    for (let n = 1; n <= page.pages; n++) {
      if (n === 1 || n === page.pages || Math.abs(n - page.page) <= 1) {
        nums.push(
          <a key={n} className={n === page.page ? 'pl-pg on' : 'pl-pg'} {...link({ page: n })}>
            {n}
          </a>,
        )
        gap = false
      } else if (!gap) {
        nums.push(<span key={`g${n}`} className="pl-gap">…</span>)
        gap = true
      }
    }
    pager = (
      <div className="pl-pag">
        <span>
          {T.showing} {first}–{lastN} {T.of} {page.total} {T.patients}
          {page.hidden_arh > 0 && (
            <>
              {' · '}<Icon name="box" /> {page.hidden_arh}{' '}
              {page.hidden_arh === 1 ? T.hiddenOne : T.hiddenMany}{' '}
              <a {...link({ st: 'arhivat', page: 1 })}>{T.show}</a>
            </>
          )}
        </span>
        <div className="pl-pgs">
          {page.page > 1
            ? <a className="pl-pg" {...link({ page: page.page - 1 })}>‹</a>
            : <span className="pl-pg off">‹</span>}
          {nums}
          {page.page < page.pages
            ? <a className="pl-pg" {...link({ page: page.page + 1 })}>›</a>
            : <span className="pl-pg off">›</span>}
        </div>
        <form onSubmit={(e) => e.preventDefault()}>
          <select
            aria-label={T.perPage}
            value={filters.per}
            onChange={(e) => go({ per: Number(e.target.value), page: 1 })}
          >
            {summary.per.map((n) => <option key={n} value={n}>{n} {T.perPage}</option>)}
          </select>
        </form>
      </div>
    )
  }

  return <>{table}{pager}</>
}
