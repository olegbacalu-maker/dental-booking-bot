import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/icons'
import type { DashActions } from './dash'
import { dur, JUST_CAME_MIN, type Flow, type FlowKind, type FlowRow } from './flow'

/* Поток пациента над «Agenda zilei» (03.10, вариант A по слову Олега: «вариант А
   как ты сказал, делаем»): вкладки `Toate · Întârzie · A venit · În cabinet` с
   цифрами. Строка — человек и ОДНО следующее действие, как в «De confirmat»;
   клик по строке открывает ту же карточку визита, где живут «Nu a venit» и
   остальные исходы.
   ⛔ Слова СТАТУСОВ — с сервера: имя вкладки «A venit»/«În cabinet» и подпись
   кнопки — это подпись кнопки, ВЕДУЩЕЙ в этот статус, из матрицы `actions`
   (`core/visits._ACT_BUTTONS`). Второго словаря статусов в браузере нет — он
   разводился дважды (08-12, 08-16). «Toate» и «Întârzie» — слова ВИДА, не
   статусы, и живут здесь.
   ⛔ Цвета — смысла, не темы: фиолетовый «a venit» и синий «în cabinet» те же,
   что у плашек повестки; красное — ждёт или опаздывает от 15 минут; янтарное —
   опоздание и приём сверх плана. */

export type FlowTo = 'waiting' | 'arrived' | 'done'
export type FlowTab = 'all' | FlowKind

const W = {
  all: 'Toate',
  late: 'Întârzie',
  now: 'acum',
  left: (m: number) => (m > 0 ? `încă ${dur(m)}` : 'se termină'),
  over: (m: number) => `+${dur(m)}`,
  until: (t: string) => `până la ${t}`,
  free: 'medicul e liber',
  busy: (t: string) => `medicul e ocupat până la ${t}`,
  busyOver: (m: number) => `medicul depășește cu ${dur(m)}`,
  nextWaits: (n: string, t: string, m: number) => `${n} (${t}) așteaptă deja ${dur(m)}`,
  nextWill: (n: string, t: string) => `${n} (${t}) va aștepta`,
  noNext: 'nu mai are pacienți azi',
  empty: { late: 'Nimeni nu întârzie', waiting: 'Nimeni nu așteaptă', incab: 'Nimeni în cabinet' },
} as const

const TO_ICON: Record<FlowTo, IconName> = { waiting: 'checkin', arrived: 'door', done: 'check' }

/** Следующий шаг вкладки — та же стрелка, что у кнопок карточки. */
const NEXT: Record<FlowKind, FlowTo> = { late: 'waiting', waiting: 'arrived', incab: 'done' }

export type FlowLabels = Record<FlowTo, string>

/** Подписи статусов из матрицы кнопок: подпись кнопки, ВЕДУЩЕЙ в статус.
 *  ⚠️ Запасное значение — код статуса: матрица его всегда несёт (её держит
 *  прогон), а пустая вкладка была бы хуже кода. */
export function flowLabels(actions: DashActions): FlowLabels {
  const find = (to: FlowTo) => {
    for (const btns of Object.values(actions)) {
      const b = btns.find((x) => x.to === to)
      if (b) return b.label
    }
    return to
  }
  return { waiting: find('waiting'), arrived: find('arrived'), done: find('done') }
}

interface BarProps {
  tab: FlowTab
  onTab: (t: FlowTab) => void
  flow: Flow
  /** Сколько записей у дня — цифра вкладки «Toate». */
  total: number
  labels: FlowLabels
}

export function FlowBar({ tab, onTab, flow, total, labels }: BarProps) {
  const tone = (rows: FlowRow[], base: string, alarm: (r: FlowRow) => boolean, hot: string) =>
    rows.some(alarm) ? hot : rows.length ? base : ''
  const tabs: { id: FlowTab; label: string; n: number; tone: string }[] = [
    { id: 'all', label: W.all, n: total, tone: '' },
    { id: 'late', label: W.late, n: flow.late.length, tone: tone(flow.late, 'amber', (r) => r.long, 'red') },
    { id: 'waiting', label: labels.waiting, n: flow.waiting.length,
      tone: tone(flow.waiting, 'violet', (r) => r.long, 'red') },
    { id: 'incab', label: labels.arrived, n: flow.incab.length,
      tone: tone(flow.incab, 'blue', (r) => r.min > 0, 'amber') },
  ]
  return (
    <div className="fl-tabs" role="tablist">
      {tabs.map((t) => (
        /* плитка (макет 08.10): число крупно над подписью */
        <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
          aria-label={`${t.label} ${t.n}`}
          className={`fl-tab${tab === t.id ? ' on' : ''}`} onClick={() => onTab(t.id)}>
          <b className={t.tone}>{t.n}</b>
          <span>{t.label}</span>
        </button>
      ))}
    </div>
  )
}

interface ListProps {
  kind: FlowKind
  rows: FlowRow[]
  labels: FlowLabels
  busy: boolean
  onCard: (id: number) => void
  onFlow: (id: number, to: FlowTo) => void
}

export function FlowList({ kind, rows, labels, busy, onCard, onFlow }: ListProps) {
  if (!rows.length) return <p className="fl-empty">{W.empty[kind]}</p>
  return (
    <div className="fl-list">
      {rows.map((r) => (
        <Row key={r.it.id} kind={kind} r={r} labels={labels} busy={busy} onCard={onCard} onFlow={onFlow} />
      ))}
    </div>
  )
}

function Row({ kind, r, labels, busy, onCard, onFlow }: { kind: FlowKind; r: FlowRow } & Omit<ListProps, 'kind' | 'rows'>) {
  const { it } = r
  const to = NEXT[kind]
  let chip: { text: string; cls: string }
  let sub: string
  let note: { text: string; cls: string; icon?: IconName } | null = null
  if (kind === 'late') {
    // слово «întârzie» уже на вкладке — на плашке только минуты
    chip = { text: dur(r.min), cls: r.long ? 'red' : 'amber' }
    sub = [it.doctor, it.phone].filter(Boolean).join(' · ')
  } else if (kind === 'waiting') {
    chip = r.min < JUST_CAME_MIN ? { text: W.now, cls: 'violet' } : { text: dur(r.min), cls: r.long ? 'red' : 'violet' }
    sub = it.doctor
    note = !r.busy ? { text: W.free, cls: 'free' }
      : r.busy.over > 0 ? { text: W.busyOver(r.busy.over), cls: 'warn', icon: 'alarm' }
        : { text: W.busy(r.busy.until), cls: '' }
  } else {
    chip = r.min > 0 ? { text: W.over(r.min), cls: 'amber' } : { text: W.left(r.left), cls: 'blue' }
    sub = [it.doctor, it.in_at ? `${it.in_at}–${it.end}` : W.until(it.end)].join(' · ')
    if (r.min > 0) {
      note = {
        cls: 'warn', icon: 'alarm',
        text: r.next
          ? (r.next.waiting !== null ? W.nextWaits(r.next.name, r.next.time, r.next.waiting)
            : W.nextWill(r.next.name, r.next.time))
          : W.noNext,
      }
    }
  }
  const over = kind === 'incab' && r.min > 0
  return (
    <div className={`fl-row${over ? ' over' : ''}`} data-appt={it.id} onClick={() => onCard(it.id)}>
      <span className="dk-t">{it.time}</span>
      <div className="fl-b">
        <div className="fl-l1">
          {it.patient_id !== null
            ? <AppLink href={`/admin/patient/${it.patient_id}`} onClick={(e) => e.stopPropagation()}>
                <b>{it.name}</b></AppLink>
            : <b>{it.name}</b>}
          <span className={`fl-chip ${chip.cls}`}>{chip.text}</span>
        </div>
        <small>{sub}</small>
        {note && (
          <small className={`fl-note ${note.cls}`}>
            {note.icon && <><Icon name={note.icon} />{' '}</>}{note.text}
          </small>
        )}
      </div>
      <span className="dk-act">
        <button type="button" className={`dk-btn fl-${to}`} title={labels[to]}
          aria-label={`${labels[to]}: ${it.name}`} disabled={busy}
          onClick={(e) => { e.stopPropagation(); onFlow(it.id, to) }}>
          <Icon name={TO_ICON[to]} />
        </button>
      </span>
    </div>
  )
}
