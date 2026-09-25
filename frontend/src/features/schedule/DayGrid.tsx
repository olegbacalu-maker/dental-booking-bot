import type { DragEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { DayCell, DayItem, DayModel } from './day'
import { dragOf, halfAt, type Drag, type Target } from './move'

/* Таблица дня: часы рядами, врачи колонками (C25.5a), с записью, карточкой и
   перетаскиванием (C25.5b).

   Классы те же, что у старой страницы (.gridwrap, .grid, .hrow, .hour, .appt,
   .free, .goff, .stat, .dropzone), поэтому panel.css красит таблицу без
   единого нового правила, включая тему клиники.

   ⛔ Мишень броска — сама ячейка (`cell.drop`), а тащится карточка
   (`item.movable`), и это РАЗНЫЕ вопросы. Визит, оказавшийся в закрытом часу
   (обед или график сузили после брони), тащить можно, а бросить в тот же час
   нельзя — асимметрия намеренная, её считает сервер.
   ⚠️ Получас берётся из места броска ВНУТРИ ячейки: верх — :00, низ — :30.
   Без этого «09:30 → 10:00» и «09:30 → 10:30» стали бы одним и тем же. */
const T = {
  pause: 'pauză',
  closed: 'închis',
  busy: 'ocupat',
  hint: 'Trageți o programare pentru a o muta la altă oră sau alt medic; '
    + 'click pe «+» — programare nouă sau notiță.',
} as const

interface Props {
  model: DayModel
  /** Начало броска: null — бросок кончился. */
  drag: Drag | null
  /** Подсвеченная ячейка: «колонка|час». */
  hover: string
  onDrag: (d: Drag | null) => void
  onHover: (key: string) => void
  onDrop: (t: Target) => void
  onPlus: (dk: string, name: string, hour: string) => void
  onCard: (id: number) => void
}

export function DayGrid({ model, drag, hover, onDrag, onHover, onDrop, onPlus, onCard }: Props) {
  return (
    <>
      <div className="gridwrap">
        <table className="grid">
          <tbody>
            <tr>
              <th className="gh-t" />
              {model.doctors.map((dc) => (
                <th key={dc.id}>
                  <AppLink className="dh-n" href={`/admin/doctor/${dc.id}?date=${model.date}`}>{dc.name}</AppLink>
                  <span className="dh-s">{dc.spec}</span>
                </th>
              ))}
            </tr>
            {model.hours.map((row) => (
              <tr key={row.h} className={`hrow${row.closed ? ' off' : ''}${row.now ? ' now' : ''}`}>
                <td className={`hour${row.closed ? ' off' : ''}${row.now ? ' now' : ''}`}>
                  {row.label}
                  {row.closed ? <small>{row.closed === 'pauza' ? T.pause : T.closed}</small> : null}
                </td>
                {row.cells.map((cell, i) => {
                  const dc = model.doctors[i]
                  const key = `${dc?.id ?? i}|${row.h}`
                  return (
                    <Cell key={key} cell={cell} dk={dc?.id ?? ''} name={dc?.name ?? ''}
                          hour={row.h} drag={drag} hovered={hover === key}
                          onDrag={onDrag} onHover={onHover} onDrop={onDrop}
                          onPlus={onPlus} onCard={onCard} />
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">{T.hint}</p>
    </>
  )
}

interface CellProps {
  cell: DayCell
  dk: string
  name: string
  hour: number
  drag: Drag | null
  hovered: boolean
  onDrag: (d: Drag | null) => void
  onHover: (key: string) => void
  onDrop: (t: Target) => void
  onPlus: (dk: string, name: string, hour: string) => void
  onCard: (id: number) => void
}

function Cell({ cell, dk, name, hour, drag, hovered, onDrag, onHover, onDrop,
  onPlus, onCard }: CellProps) {
  const label = `${String(hour).padStart(2, '0')}:00`
  /* Мишень только у приёмного часа, и только пока что-то тащат: без
     preventDefault браузер не отдаст событие drop вовсе. */
  const target = (e: DragEvent<HTMLTableCellElement>): Target => ({
    dk, min: hour * 60 + halfAt(e.clientY, e.currentTarget.getBoundingClientRect()),
  })
  const zone = cell.drop && drag
    ? {
        onDragOver: (e: DragEvent<HTMLTableCellElement>) => {
          e.preventDefault()
          // как в panel.js: объект переноса бывает недоступен (и его нет у
          // события, синтезированного проверкой) — подсветка важнее курсора
          if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
          onHover(`${dk}|${hour}`)
        },
        onDragLeave: () => onHover(''),
        onDrop: (e: DragEvent<HTMLTableCellElement>) => {
          e.preventDefault()
          onDrop(target(e))
        },
      }
    : {}
  const cls = hovered ? 'dropzone' : undefined

  if (cell.kind === 'off') return <td className="goff" />
  if (cell.kind === 'busy') {
    return (
      <td className={cls} {...zone}>
        <div className="appt busy"><Icon name="hourglass" /> {T.busy}</div>
      </td>
    )
  }
  if (cell.kind === 'free') {
    return (
      <td className={cls} {...zone}>
        <AppLink className="free" href="#addform"
           onClick={(e) => { e.preventDefault(); onPlus(dk, name, label) }}>+</AppLink>
      </td>
    )
  }
  return (
    <td className={cls} {...zone}>
      {cell.items.map((x) => (
        <Appt key={x.id} item={x} dk={dk} dragging={drag?.id === x.id}
              onDrag={onDrag} onCard={onCard} />
      ))}
    </td>
  )
}

interface ApptProps {
  item: DayItem
  dk: string
  dragging: boolean
  onDrag: (d: Drag | null) => void
  onCard: (id: number) => void
}

function Appt({ item, dk, dragging, onDrag, onCard }: ApptProps) {
  /* data-mv остаётся атрибутом: по нему panel.css гасит тащимую карточку
     (`[data-mv].dragging`), и правило одно на обе страницы. */
  const move = item.movable
    ? {
        draggable: true,
        'data-mv': '1',
        onDragStart: (e: DragEvent<HTMLDivElement>) => {
          e.dataTransfer.effectAllowed = 'move'
          try { e.dataTransfer.setData('text/plain', String(item.id)) } catch { /* jsdom */ }
          onDrag(dragOf(item, dk))
        },
        onDragEnd: () => onDrag(null),
      }
    : {}
  const cls = dragging ? ' dragging' : ''

  if (item.kind === 'note') {
    return (
      <div className={`appt note${cls}`} data-appt={item.id} {...move}>
        <Icon name="note" /> {item.time} {item.text}
      </div>
    )
  }
  return (
    <div className={`appt ${item.status}${item.urgent ? ' urgent' : ''}`
      + `${item.clickable ? ' clickable' : ''}${cls}`}
         data-appt={item.id} {...move}
         onClick={item.clickable ? () => onCard(item.id) : undefined}>
      <b>{item.time} · {item.name}</b>
      {item.age ? <small className="dp-age"> {item.age} a.</small> : null}{' '}
      <Icon name={item.source === 'bot' ? 'bot' : 'pen'} />
      <br />
      {item.urgent ? <><Icon name="sos" /> </> : null}{item.service}{' '}
      <small>({item.dur}′)</small>
      <br /><small>{item.phone}</small>
      {item.status !== 'confirmed' && (
        <div className="stw"><span className={`stat s-${item.status}`}>{item.status_label}</span></div>
      )}
      {item.comment_cut && <div className="cmt"><Icon name="chat" /> {item.comment_cut}</div>}
    </div>
  )
}
