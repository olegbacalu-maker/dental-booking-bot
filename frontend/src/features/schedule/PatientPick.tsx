import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import { api } from '../../services/api'

/* Выбор существующей фиши в окнах записи журнала: повторного пациента не вписывают заново и не
   плодят двойников. Поле «Nume pacient» ищет по картотеке тем же поиском, что
   список «Pacienți» (`/api/patients?q=`: имя в любом порядке, номер в любом виде, № дела, IDNP);
   пустое поле — «Recenți» с сервера. Выбор кладёт на место поля плашку фиши той же высоты, визит
   уходит в фишу по номеру (`pid`). Не выбрали — запись как раньше, по имени и телефону; совпавшие
   номер или имя подсказаны кнопкой внутри поля, а не строкой: окно не меняет высоту.
   Ничего не подставляется само: фиша экрана стоит первой в «Recenți», выбирает человек — записывают
   часто другого.
   Список открывают щелчок, набор и ↓ — не фокус: фокус приходит и сам («Alt pacient», Tab), а открытый
   список ложится на поле телефона, и щелчок по телефону выбрал бы строку.
   Список — в верхнем слое (`popover`), как `ServicePicker`: в окне Sticlă `fixed` считался бы от окна. */

const T = {
  ph: 'Nume, telefon sau nr. fișei',
  recent: 'Recenți',
  here: 'fișa deschisă',
  none: 'Nicio fișă găsită — se creează una nouă.',
  newOne: (q: string) => `+ Pacient nou „${q}”`,
  other: 'Alt pacient',
  dosar: 'dosar',
  born: 'n.',
  last: 'ultima:',
  noVisits: 'fără vizite',
  byPhone: (n: string) => `Fișă existentă: ${n}`,
  byName: (n: string) => `Există fișa: ${n}`,
  manyNames: (k: number) => `${k} fișe cu acest nume`,
} as const

/** Строка подсказки: те же поля отдают `/api/patients` и `/api/schedule/pick/*`. */
export interface PickRow {
  id: number
  name: string
  phone: string
  year: string
  file_no: string
  last: string
}

interface Match { phone: PickRow | null; name: PickRow[] }

const TOP_LAYER = typeof HTMLElement !== 'undefined' && 'showPopover' in HTMLElement.prototype
const SHOW = 6
const digitsOf = (s: string) => s.replace(/\D/g, '')
/* ответ без строк (старый сервер, чужой ответ) — пустой список, а не падение окна */
const rowsOf = (d: { rows?: PickRow[] } | undefined): PickRow[] => (Array.isArray(d?.rows) ? d.rows : [])

/** Номер, набранный в поле имени: ищем по нему, а у нового пациента он переезжает в «Telefon». */
export function splitDigits(q: string): { name: string; phone: string } {
  const m = q.match(/\+?\d[\d\s().-]{4,}\d/)
  if (!m || digitsOf(m[0]).length < 6) return { name: q.trim(), phone: '' }
  return { name: q.replace(m[0], ' ').replace(/\s+/g, ' ').trim(), phone: m[0].trim() }
}

export function pickSub(r: PickRow): string {
  return [r.phone, r.year ? `${T.born} ${r.year}` : '', r.last ? `${T.last} ${r.last}` : T.noVisits]
    .filter(Boolean).join(' · ')
}

/** Фиша подсказки вкладки Google (`AddPerson`) — строка выбора без года и визита. */
export const personRow = (x: { id: number; name: string; phone: string }): PickRow =>
  ({ id: x.id, name: x.name, phone: x.phone, year: '', file_no: '', last: '' })

const initials = (n: string) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()

/** Состояние выбора на окно: набранное имя, выбранная фиша и совпадения номера и имени. */
export function usePatientPick(phone: string, noPhone: boolean, seed: PickRow | null = null, seedName = '') {
  const [name, setName] = useState(seedName)
  const [picked, setPicked] = useState<PickRow | null>(seed)
  const [match, setMatch] = useState<{ key: string; m: Match } | null>(null)
  const tel = noPhone ? '' : phone
  const key = `${digitsOf(tel)}|${name.trim()}`
  const want = !picked && (digitsOf(tel).length >= 6 || name.trim().length >= 3)

  useEffect(() => {
    if (!want) return
    const ctl = new AbortController()
    const t = window.setTimeout(() => {
      api.post<Match>('/schedule/pick/match', { phone: tel, name: name.trim() }, { signal: ctl.signal }).then(
        (r) => {
          if (!ctl.signal.aborted) setMatch({ key, m: { phone: r.data?.phone ?? null, name: r.data?.name ?? [] } })
        },
        () => {},
      )
    }, 250)
    return () => { window.clearTimeout(t); ctl.abort() }
  }, [want, key, tel, name])

  /* совпадение — только для того, что набрано сейчас: старый ответ не показывается */
  const m = want && match?.key === key ? match.m : null
  return { name, setName, picked, setPicked, phoneHit: m?.phone ?? null, nameHits: m?.name ?? [] }
}

export type PatientPickState = ReturnType<typeof usePatientPick>

interface Props {
  pick: PatientPickState
  /** Фиша экрана, поверх которой открыто окно: первая строка «Recenți». */
  here?: number | undefined
  /** «+ Pacient nou» с номером в поле имени — номер уходит в «Telefon». */
  onPhone: (phone: string) => void
  required?: boolean
}

/** Поле «Nume pacient» с поиском по картотеке; выбрана фиша — плашка на его месте. */
export function PatientName({ pick, here, onPhone, required }: Props) {
  const uid = useId()
  const input = useRef<HTMLInputElement>(null)
  const wrap = useRef<HTMLSpanElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [found, setFound] = useState<{ q: string; rows: PickRow[] } | null>(null)
  const [recent, setRecent] = useState<PickRow[] | null>(null)
  const q = pick.name.trim()
  const searching = q.length >= 2

  useEffect(() => {
    if (!open || !searching) return
    const ctl = new AbortController()
    const t = window.setTimeout(() => {
      api.get<{ rows: PickRow[] }>(`/patients?q=${encodeURIComponent(q)}&per=10`, { signal: ctl.signal }).then(
        (r) => { if (!ctl.signal.aborted) setFound({ q, rows: rowsOf(r.data).slice(0, SHOW) }) },
        () => { if (!ctl.signal.aborted) setFound({ q, rows: [] }) },
      )
    }, 150)
    return () => { window.clearTimeout(t); ctl.abort() }
  }, [open, searching, q])

  useEffect(() => {
    if (!open || searching || recent !== null) return
    const ctl = new AbortController()
    api.post<{ rows: PickRow[] }>('/schedule/pick/recent', here ? { here } : {}, { signal: ctl.signal }).then(
      (r) => { if (!ctl.signal.aborted) setRecent(rowsOf(r.data)) },
      () => { if (!ctl.signal.aborted) setRecent([]) },
    )
    return () => ctl.abort()
  }, [open, searching, recent, here])

  /* пока ответ в пути — прежние строки: список не мигает пустотой на каждой букве */
  const rows = searching ? (found?.rows ?? []) : (recent ?? [])
  const waiting = searching ? found?.q !== q && !found : recent === null
  const items = searching ? rows.length + 1 : rows.length
  const shown = open && !pick.picked && (searching || rows.length > 0)
  const cur = Math.min(active, items - 1)

  useLayoutEffect(() => {
    if (!shown) return
    const place = () => {
      const r = wrap.current?.getBoundingClientRect()
      const el = listRef.current
      if (!r || !el) return
      const vw = window.innerWidth, vh = window.innerHeight
      const width = Math.min(r.width, vw - 16)
      const below = vh - r.bottom - 8, above = r.top - 8
      const up = below < 220 && above > below
      el.style.left = `${Math.max(8, Math.min(r.left, vw - width - 8))}px`
      el.style.width = `${width}px`
      el.style.maxHeight = `${Math.max(140, Math.min(380, up ? above : below))}px`
      el.style.top = up ? '' : `${r.bottom + 4}px`
      el.style.bottom = up ? `${vh - r.top + 4}px` : ''
    }
    const el = listRef.current
    if (el && TOP_LAYER && !el.matches(':popover-open')) el.showPopover()
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [shown])

  useLayoutEffect(() => {
    const list = listRef.current
    if (!shown || cur < 0 || !list) return
    const el = list.querySelector<HTMLElement>(`[data-i="${cur}"]`)
    if (!el) return
    if (el.offsetTop < list.scrollTop) list.scrollTop = el.offsetTop
    else if (el.offsetTop + el.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = el.offsetTop + el.offsetHeight - list.clientHeight
    }
  }, [shown, cur])

  function choose(r: PickRow) {
    setOpen(false)
    pick.setPicked(r)
  }

  function newOne() {
    setOpen(false)
    const s = splitDigits(pick.name)
    if (s.phone) {
      pick.setName(s.name)
      onPhone(s.phone)
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) { setOpen(true); setActive(0); return }
      if (items) setActive((cur + (e.key === 'ArrowDown' ? 1 : items - 1)) % items)
    } else if (e.key === 'Enter' && shown) {
      /* Enter на фише выбирает её и не отправляет окно; на «+ Pacient nou» — отправляет, как
         до списка: новый пациент записывается тем же движением, что всегда */
      setOpen(false)
      const r = rows[cur]
      if (r) {
        e.preventDefault()
        choose(r)
      }
    } else if (e.key === 'Escape' && shown) {
      /* Esc закрывает список, а не окно, в котором стоит поле */
      e.preventDefault()
      e.stopPropagation()
      setOpen(false)
    }
  }

  function unpick() {
    pick.setPicked(null)
    pick.setName('')
    window.setTimeout(() => input.current?.focus(), 0)
  }

  if (pick.picked) {
    const p = pick.picked
    return (
      <div className="dp-pick-chip" role="group" aria-label={p.name}
           onKeyDown={(e) => { if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); unpick() } }}>
        <span className="dp-pick-av" aria-hidden="true">{initials(p.name)}</span>
        <span className="dp-pick-tx">
          <b className="dp-pick-nm">{p.name}</b>
          <span className="dp-pick-sb">{[p.phone, p.year ? `${T.born} ${p.year}` : '', p.file_no ? `${T.dosar} ${p.file_no}` : '']
            .filter(Boolean).join(' · ')}</span>
        </span>
        <button type="button" className="dp-pick-x" onClick={unpick}><Icon name="close" /> {T.other}</button>
      </div>
    )
  }

  const names = pick.nameHits.filter((r) => r.id !== pick.phoneHit?.id)
  const nameHit = !open && names.length
    ? <MatchPill onClick={() => {
        if (names.length === 1 && names[0]) pick.setPicked(names[0])
        else { setOpen(true); setActive(0); input.current?.focus() }
      }}>{names.length === 1 && names[0] ? T.byName(names[0].name) : T.manyNames(names.length)}</MatchPill>
    : null
  const optId = (n: number) => `${uid}-o${n}`
  return (
    <span ref={wrap} className={`dp-pick${nameHit ? ' has-pill' : ''}`}>
      <input ref={input} value={pick.name} placeholder={T.ph} required={required} autoComplete="off" spellCheck={false}
        role="combobox" aria-autocomplete="list" aria-expanded={shown} aria-controls={`${uid}-list`}
        aria-activedescendant={shown && cur >= 0 ? optId(cur) : undefined}
        onChange={(e) => { pick.setName(e.target.value); setOpen(true); setActive(0) }}
        onClick={() => { if (!open) { setOpen(true); setActive(0) } }}
        onKeyDown={onKey} onBlur={() => setOpen(false)} />
      {nameHit}
      {shown && (
        <div ref={listRef} id={`${uid}-list`} role="listbox" className="dp-svc-list dp-pick-list"
          popover={TOP_LAYER ? 'manual' : undefined}
          /* щелчок по списку не снимает фокус с поля: иначе blur закрыл бы список раньше выбора */
          onMouseDown={(e) => e.preventDefault()}>
          {!searching ? <div className="dp-pick-head" aria-hidden="true">{T.recent}</div> : null}
          {searching && !rows.length && !waiting ? <p className="dp-pick-none">{T.none}</p> : null}
          {rows.map((r, n) => (
            <div key={r.id} id={optId(n)} data-i={n} role="option" aria-selected={n === cur}
              className={`dp-pick-opt${n === cur ? ' on' : ''}`}
              onMouseMove={() => { if (n !== cur) setActive(n) }} onClick={() => choose(r)}>
              <span className="dp-pick-av" aria-hidden="true">{initials(r.name)}</span>
              <span className="dp-pick-tx">
                <span className="dp-pick-nm">{r.name}</span>
                <span className="dp-pick-sb">{pickSub(r)}</span>
              </span>
              <span className="dp-pick-no">
                {!searching && here === r.id ? T.here : r.file_no ? `${T.dosar} ${r.file_no}` : ''}
              </span>
            </div>
          ))}
          {searching ? (
            <div id={optId(rows.length)} data-i={rows.length} role="option" aria-selected={cur === rows.length}
              className={`dp-pick-new${cur === rows.length ? ' on' : ''}`}
              onMouseMove={() => { if (cur !== rows.length) setActive(rows.length) }} onClick={newOne}>
              {T.newOne(q)}
            </div>
          ) : null}
        </div>
      )}
    </span>
  )
}

function MatchPill({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" className="dp-pick-pill" onClick={onClick} title={typeof children === 'string' ? children : undefined}>
      <span>{children}</span> ›
    </button>
  )
}

/** Подсказка в поле телефона: номер уже есть у фиши, а её не выбрали — визит ляжет туда же. */
export function PhoneHit({ pick }: { pick: PatientPickState }) {
  const r = pick.picked ? null : pick.phoneHit
  if (!r) return null
  return <MatchPill onClick={() => pick.setPicked(r)}>{T.byPhone(r.name)}</MatchPill>
}
