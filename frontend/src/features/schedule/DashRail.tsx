import { useState } from 'react'
import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { clinicNow, clinicTz, waitLabel } from './dashFx'
import { DeskCard } from './DeskCard'
import { flowOf, type Flow } from './flow'
import { FlowBar, FlowList, flowLabels, type FlowLabels, type FlowTab, type FlowTo } from './FlowTabs'
import { freeSlots } from './free'
import { dm } from '../../utils/date'
import type { DashActions, DashAgenda, DashCanvasModel, DashMiniCal } from './dash'
import type { CallResult, Desk } from './desk'

/* Правая колонка панели: мини-календарь, повестка, «Primul loc liber», списки
   стойки — по макету Олега (08.10, design/redesign-2026-10, промпт 1).

   ⛔ Порядок блоков — решение Олега (28.09 на показ: «поменял бы местами с
   Agenda zilei, поставил бы наверх»): календарь, повестка, потом стойка.
   Строка статистики дня снята (промпт: «единственное место со статистикой —
   Agenda zilei»): цифры живут в подзаголовке страницы и на плитке «Toate».
   ⭐ Списки стойки (De încasat, De confirmat, Plan fără programare) ОСТАЮТСЯ,
   хотя в макете их нет: это рабочие списки регистратуры (Олег 28.09: «очень
   нравится»), пустые не рисуются — в тихий день колонка ровно как макет.
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
  one: 'programare',
  many: 'programări',
  free: 'Primul loc liber',
  book: 'Programează',
  noFree: 'Fără intervale libere',
  today: 'azi',
  cash: 'Casa azi',
  casa: 'Raport de casă',
  mdl: 'MDL',
  prevMonth: 'Luna precedentă',
  nextMonth: 'Luna următoare',
  withAppts: 'are programări',
} as const

interface Props {
  minical: DashMiniCal
  agenda: DashAgenda
  /** Канва дня — из неё «Primul loc liber» и цвета врачей. */
  canvas: DashCanvasModel
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
  /** «Programează» у первого свободного часа — тот же диалог, что у ячейки. */
  onSlot: (dk: string, name: string, hour: string) => void
}

export function DashRail(
  { minical, agenda, canvas, desk, date, waitTick, busy, onCard, onCardMenu, onCall, fresh, onFlow,
    actions, onSlot }: Props,
) {
  // поток — только у СЕГОДНЯ: в чужом дне «опаздывает» и «ждёт» не значат ничего
  const flow = agenda.today ? flowOf(agenda.items, waitTick) : null
  const labels = flowLabels(actions)
  return (
    <>
      <MiniCal cal={minical} />
      <Agenda agenda={agenda} date={date} waitTick={waitTick} onCard={onCard}
        onCardMenu={onCardMenu} fresh={fresh} flow={flow} labels={labels}
        busy={busy} onFlow={onFlow} />
      <FreeCard canvas={canvas} today={agenda.today} date={date} waitTick={waitTick}
        desk={desk} busy={busy} onSlot={onSlot} />
      <DeskCard desk={desk} busy={busy} onCall={onCall} />
    </>
  )
}

/**
 * Месяц полными неделями Пн–Вс.
 *
 * ⛔ Четыре метки НЕЗАВИСИМЫ и складываются: `oth tdy` — законное сочетание,
 * сегодняшний день в хвосте прошлого месяца; точка `busy` (08.10) — у любого
 * из них. Склей их в одно поле — и такой день перестанет подсвечиваться.
 * ⚠️ Стрелки — литералы `‹`/`›` (U+2039/U+203A), а не иконки: так на старой
 * странице, оба знака в вшитом подмножестве Inter, и замена на `chev-l`
 * развела бы два экрана визуально. Это решение, а не недосмотр.
 */
function MiniCal({ cal }: { cal: DashMiniCal }) {
  return (
    <div className="mcal">
      <div className="mhead">
        <AppLink href={cal.prev.href} aria-label={T.prevMonth}>{T.prev}</AppLink>
        <b>{cal.title}</b>
        <AppLink href={cal.next.href} aria-label={T.nextMonth}>{T.next}</AppLink>
      </div>
      <table>
        <tbody>
          <tr>{cal.weekdays.map((w) => <th key={w}>{w}</th>)}</tr>
          {cal.weeks.map((week) => (
            <tr key={week[0]!.date}>
              {week.map((c) => (
                <td key={c.date}>
                  <AppLink className={[c.other && 'oth', c.today && 'tdy', c.selected && 'seld']
                    .filter(Boolean).join(' ')} href={c.href}
                    aria-current={c.selected ? 'date' : undefined}
                    title={c.busy ? `${c.date} · ${T.withAppts}` : c.date}>
                    {c.day}{c.busy && <i className="dot" />}
                  </AppLink>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Следующий шаг визита в списке «Toate» — та же стрелка, что у вкладок потока:
 *  записан → пришёл → в кабинете → завершён. ⛔ Слово кнопки — из матрицы
 *  сервера (`labels`), второго словаря статусов здесь нет. */
const NEXT_OF: Record<string, FlowTo> = { confirmed: 'waiting', waiting: 'arrived', arrived: 'done' }

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
      <div className="ag-h">
        <b>{T.agenda}</b>
        <span>{agenda.count} {agenda.count === 1 ? T.one : T.many}</span>
      </div>
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
          /* кнопка следующего шага — только СЕГОДНЯ: в чужом дне «пришёл»
             не значит ничего, там исходы ставят из карточки визита */
          const to = flow ? NEXT_OF[it.status] : undefined
          return (
            <div key={it.id}
              className={`ag-i${it.state === 'past' ? ' past' : ''}`
                + (fresh.has(it.id) ? ' fresh' : '')}
              data-appt={it.id} style={{ borderLeftColor: it.bar }}
              onClick={() => onCard(it.id)}
              onContextMenu={(e) => { e.preventDefault(); onCardMenu?.(it.id, e.clientX, e.clientY) }}>
              <div className="ag-r">
                <span className="ag-t">{it.time}</span>
                <div className="ag-b">
                  {/* значок «есть комментарий» (03.10, просьба Олега), текст — подсказкой */}
                  <b>{it.name}{it.comment && (
                    <> <span className="ag-cmt" title={`${T.comment}: ${it.comment}`}>
                      <Icon name="chat" /></span></>
                  )}</b>
                  <small>{it.service}</small>
                  <div className="ag-chips">
                    {/* срочность — чип со значком, не только цветом (макет);
                        слово и класс плашки — с сервера */}
                    {it.badge.cls === 'bad'
                      ? <span className="chip urg"><Icon name="excl" />{it.badge.label}</span>
                      : <span className={`pl-badge ${it.badge.cls}`}>{it.badge.label}</span>}
                    {wait && <span className={`wait-min${wait.long ? ' long' : ''}`}>{wait.text}</span>}
                  </div>
                </div>
              </div>
              {/* ⛔ Кнопка одонтограммы — только у визита С ПАЦИЕНТОМ: у
                  легаси-строки без него ссылка вела бы на `/None/`.
                  ⛔ Обе кнопки останавливают всплытие: строка кликабельна
                  целиком, и без этого одно нажатие делало бы два действия. */}
              {(to || it.patient_id !== null) && (
                <div className="ag-acts">
                  {to && (
                    <button type="button" className="savebtn ag-next" disabled={busy}
                      aria-label={`${labels[to]}: ${it.name}`}
                      onClick={(e) => { e.stopPropagation(); onFlow(it.id, to) }}>
                      {labels[to]}
                    </button>
                  )}
                  {it.patient_id !== null && (
                    <AppLink className="ag-odo" href={`/admin/patient/${it.patient_id}/odontograma`}
                      onClick={(e) => e.stopPropagation()}>
                      <Icon name="tooth" />{T.odo}
                    </AppLink>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <AppLink className="ag-all" href={`/admin/all?date=${date}`}>{T.all}</AppLink>
    </div>
  )
}

/**
 * «Primul loc liber» (макет): по врачу — ближайший свободный целый час
 * показанного дня и кнопка «Programează», которая открывает ТОТ ЖЕ диалог,
 * что ячейка сетки, с врачом и часом. Внизу — касса дня (только тому, кому
 * положены деньги: `collect` иначе `null`).
 * ⚠️ Считается по канве на экране (`free.ts`), сегодня — от следующего
 * целого часа по часам КЛИНИКИ (`clinicNow`), а не устройства.
 */
function FreeCard({ canvas, today, date, waitTick, desk, busy, onSlot }: {
  canvas: DashCanvasModel; today: boolean; date: string; waitTick: number; desk: Desk; busy: boolean
  onSlot: (dk: string, name: string, hour: string) => void
}) {
  const now = today ? clinicNow(clinicTz(), new Date(waitTick)) : null
  const rows = canvas.empty ? [] : freeSlots(canvas, now)
  const cash = desk.collect
  if (!rows.length && !cash) return null
  return (
    <div className="dp-free">
      {rows.length > 0 && <h2>{T.free}</h2>}
      {rows.map((r) => (
        <div key={r.dk} className="dp-free-row">
          <span className="av sm" style={{ borderColor: r.hue }}>{r.initials}</span>
          <div className="dp-free-b">
            <b>{r.name}</b>
            <small>{r.hour === null ? T.noFree : `${today ? T.today : dm(date)} ${r.hour}`}</small>
          </div>
          <button type="button" className="dp-free-btn" disabled={busy || r.hour === null}
            aria-label={`${T.book} ${r.name} ${r.hour ?? ''}`.trim()}
            onClick={() => { if (r.hour !== null) onSlot(r.dk, r.name, r.hour) }}>
            {T.book}
          </button>
        </div>
      ))}
      {cash && (
        <div className="dk-cash">
          <span>{T.cash}: <b>{cash.cash.total_s} {T.mdl}</b>
            {cash.cash.parts.length > 0 && (
              <small> · {cash.cash.parts.map((p) => `${p.method} ${p.sum_s}`).join(' · ')}</small>
            )}
          </span>
          <AppLink className="dk-lnk" href={cash.casa_href}>{T.casa} ›</AppLink>
        </div>
      )}
    </div>
  )
}
