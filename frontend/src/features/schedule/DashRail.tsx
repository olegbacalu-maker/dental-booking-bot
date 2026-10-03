import { useState } from 'react'
import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { waitLabel } from './dashFx'
import { DeskCard } from './DeskCard'
import { flowOf, type Flow } from './flow'
import { FlowBar, FlowList, flowLabels, type FlowLabels, type FlowTab, type FlowTo } from './FlowTabs'
import type { DashActions, DashAgenda, DashMiniCal, DashOccupancy, DashTile } from './dash'
import type { CallResult, Desk } from './desk'

/* Правая колонка панели: мини-календарь, повестка, «La recepție».

   ⛔ Порядок блоков — решение Олега (28.09 на показ: «поменял бы местами с
   Agenda zilei, поставил бы наверх»): календарь, повестка, списки стойки.
   Карточка «Azi» с плитками-аналитикой снята 01.10 — её цифры живут одной
   строкой в шапке «La recepție», подробности — в Statistici.
   ⛔ Колокольчика и «Programări noi din bot» тут НЕТ: оба за `tg_configured()`,
   живого grandfather нет ни у кого, и в конверте их тоже нет. */

const T = {
  agenda: 'Agenda zilei',
  empty: '— nicio programare —',
  all: 'Vezi toate programările ›',
  odo: 'Odontogramă',
  comment: 'Comentariu',
  prev: '‹',
  next: '›',
} as const

interface Props {
  minical: DashMiniCal
  agenda: DashAgenda
  tiles: DashTile[]
  occupancy: DashOccupancy
  desk: Desk
  /** День экрана: ссылка «смотреть все» ведёт в список ЭТОГО дня. */
  date: string
  /** Метка времени для минут ожидания; меняется раз в минуту. */
  waitTick: number
  busy: boolean
  onCard: (id: number) => void
  /** Правая кнопка по строке повестки: то же меню, что у блока в сетке. */
  onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
  /** Отметка звонка в «De confirmat» — команда панели. */
  onCall: (id: number, result: CallResult) => void
  /** Что приехало прямо сейчас: этим строкам ставится `fresh` (C26.5.4). */
  fresh: ReadonlySet<number>
  /** Поток пациента (03.10): следующий статус одной кнопкой — команда панели. */
  onFlow: (id: number, to: FlowTo) => void
  /** Матрица кнопок исхода: из неё — слова статусов на вкладках потока. */
  actions: DashActions
}

export function DashRail(
  { minical, agenda, tiles, occupancy, desk, date, waitTick, busy, onCard, onCardMenu, onCall, fresh, onFlow,
    actions }: Props,
) {
  // поток — только у СЕГОДНЯ: в чужом дне «опаздывает» и «ждёт» не значат ничего
  const flow = agenda.today ? flowOf(agenda.items, waitTick) : null
  return (
    <>
      <MiniCal cal={minical} />
      <Agenda agenda={agenda} date={date} waitTick={waitTick} onCard={onCard}
        onCardMenu={onCardMenu} fresh={fresh} flow={flow} labels={flowLabels(actions)}
        busy={busy} onFlow={onFlow} />
      <DeskCard desk={desk} tiles={tiles} occupancy={occupancy} busy={busy} onCall={onCall} />
    </>
  )
}

/**
 * Месяц полными неделями Пн–Вс.
 *
 * ⛔ Три метки НЕЗАВИСИМЫ и складываются: `oth tdy` — законное сочетание,
 * сегодняшний день в хвосте прошлого месяца. Склей их в одно поле — и такой
 * день перестанет подсвечиваться как сегодняшний.
 * ⚠️ Стрелки — литералы `‹`/`›` (U+2039/U+203A), а не иконки: так на старой
 * странице, оба знака в вшитом подмножестве Inter, и замена на `chev-l`
 * развела бы два экрана визуально. Это решение, а не недосмотр.
 */
function MiniCal({ cal }: { cal: DashMiniCal }) {
  return (
    <div className="mcal">
      <div className="mhead">
        <AppLink href={cal.prev.href}>{T.prev}</AppLink>
        <b>{cal.title}</b>
        <AppLink href={cal.next.href}>{T.next}</AppLink>
      </div>
      <table>
        <tbody>
          <tr>{cal.weekdays.map((w) => <th key={w}>{w}</th>)}</tr>
          {cal.weeks.map((week) => (
            <tr key={week[0]!.date}>
              {week.map((c) => (
                <td key={c.date}>
                  <AppLink className={[c.other && 'oth', c.today && 'tdy', c.selected && 'seld']
                    .filter(Boolean).join(' ')} href={c.href}>{c.day}</AppLink>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Пустой день — ДРУГОЕ дерево, а не пустой список: без счётчика, без списка
 *  и без ссылки «смотреть все». */
function Agenda(
  { agenda, date, waitTick, onCard, onCardMenu, fresh, flow, labels, busy, onFlow }: {
    agenda: DashAgenda; date: string; waitTick: number
    onCard: (id: number) => void; onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
    fresh: ReadonlySet<number>
    /** Вкладки потока над повесткой; null — чужой день, вкладок нет. */
    flow: Flow | null; labels: FlowLabels; busy: boolean; onFlow: (id: number, to: FlowTo) => void
  },
) {
  const [tab, setTab] = useState<FlowTab>('all')
  if (!agenda.items.length) {
    return (
      <div className="agenda">
        <div className="ag-h"><b>{T.agenda}</b></div>
        <p className="hint dp-ag-empty">{T.empty}</p>
      </div>
    )
  }
  const t: FlowTab = flow ? tab : 'all'
  return (
    <div className="agenda">
      <div className="ag-h"><b>{T.agenda}</b>{!flow && <span>{agenda.count} programări</span>}</div>
      {flow && <FlowBar tab={t} onTab={setTab} flow={flow} total={agenda.count} labels={labels} />}
      {flow && t !== 'all' && (
        <FlowList kind={t} rows={flow[t]} labels={labels} busy={busy} onCard={onCard} onFlow={onFlow} />
      )}
      {/* ⛔ `.ag-l` — СТАБИЛЬНЫЙ узел с ключами по id: список прокручивается
          (max-height), и пересоздание контейнера роняло бы прокрутку при
          каждом ответе канала. Старая страница возвращала scrollTop руками
          именно потому, что подмена innerHTML его теряла.
          ⚠️ На вкладке потока узел ПРЯЧЕТСЯ, а не снимается — по той же
          причине: прокрутка «Toate» переживает и переключение вкладок. */}
      <div className="ag-l" hidden={t !== 'all'}>
        {agenda.items.map((it) => {
          const wait = it.wait_since ? waitLabel(it.wait_since, waitTick) : null
          return (
            <div key={it.id}
              className={`ag-i${it.state === 'past' ? ' past' : ''}`
                + (fresh.has(it.id) ? ' fresh' : '')}
              data-appt={it.id} style={{ borderLeftColor: it.bar }}
              onClick={() => onCard(it.id)}
              onContextMenu={(e) => { e.preventDefault(); onCardMenu?.(it.id, e.clientX, e.clientY) }}>
              <span className="ag-t">{it.time}</span>
              <div className="ag-b">
                {/* значок «есть комментарий» (03.10, просьба Олега), текст — подсказкой */}
                <b>{it.name}{it.comment && (
                  <> <span className="ag-cmt" title={`${T.comment}: ${it.comment}`}>
                    <Icon name="chat" /></span></>
                )}</b>
                <small>{it.service}</small>
                {wait && <small className={`wait-min${wait.long ? ' long' : ''}`}>{wait.text}</small>}
                {/* ⛔ Кнопка одонтограммы — только у визита С ПАЦИЕНТОМ: у
                    легаси-строки без него ссылка вела бы на `/None/`.
                    ⛔ И всплытие клика она останавливает: строка кликабельна
                    целиком, и без этого одно нажатие делало бы два действия —
                    открывало карточку ЗАОДНО с одонтограммой. */}
                {it.patient_id !== null && (
                  <AppLink className="ag-odo" href={`/admin/patient/${it.patient_id}/odontograma`}
                    onClick={(e) => e.stopPropagation()}>
                    <Icon name="tooth" />{T.odo}
                  </AppLink>
                )}
              </div>
              <span className={`pl-badge ${it.badge.cls}`}>{it.badge.label}</span>
            </div>
          )
        })}
      </div>
      <AppLink className="ag-all" href={`/admin/all?date=${date}`}>{T.all}</AppLink>
    </div>
  )
}
