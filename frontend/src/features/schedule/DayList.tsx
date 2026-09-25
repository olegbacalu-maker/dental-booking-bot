import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import type { DayListRow, DayModel } from './day'

/* «Lista zilei» (C25.5c): все записи дня строками, с кнопками исхода.

   ⛔ Это НЕ сетка. Список показывает ОТМЕНЁННЫЕ записи (в сетке их нет) и
   заметки стойки, и только отсюда заметку можно убрать и вернуть: карточки
   визита у неё нет по замыслу.
   ⛔ Кнопки берутся с сервера — `actions` для записи, `note_actions` для
   заметки. Свой список в браузере разошёлся бы молча с тем, что печатает
   старая страница.
   ⚠️ Комментарий здесь приезжает уже обрезанным до 80 знаков. Править его
   нельзя: полный текст живёт в карточке визита (`cards`), и сохранение
   обрезанного укоротило бы его без единой правки. */
const T = {
  title: 'Lista zilei',
  empty: '— nicio programare —',
  all: 'arată tot',
  head: ['#', 'Ora', 'Pacient', 'Telefon', 'Serviciu', 'Medic', 'Sursă',
    'Status', 'Acțiuni'],
  reminded: 'Reminder trimis',
  rec: 'Consultație completată',
} as const

interface Props {
  model: DayModel
  busy: boolean
  /** Открыть карточку визита (у заметки её нет). */
  onCard: (id: number) => void
  onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
  onStatus: (id: number, to: string) => void
  /** Выйти из отбора плитки. */
  onAll: () => void
}

export function DayList({ model, busy, onCard, onCardMenu, onStatus, onAll }: Props) {
  const f = model.filter
  const title = f
    ? `${f.label} — ${model.date.split('-').reverse().join('.')}`
    : T.title

  return (
    <>
      {f ? (
        <div className="banner ok">
          Filtru: <b>{f.label}</b> — {f.count} programări{' · '}
          <AppLink href={`/admin/all?date=${model.date}`}
             onClick={(e) => { e.preventDefault(); onAll() }}>
            {T.all} <Icon name="close" />
          </AppLink>
        </div>
      ) : null}
      <h2>{title}</h2>
      <table className="list">
        <tbody>
          <tr>{T.head.map((h) => <th key={h}>{h}</th>)}</tr>
          {model.list.length === 0 ? (
            <tr><td colSpan={9} className="dp-empty">{T.empty}</td></tr>
          ) : model.list.map((row) => (
            <Row key={row.id} row={row} busy={busy}
                 actions={(row.is_note ? model.note_actions : model.actions)[row.status] ?? []}
                 clickable={!row.is_note && !!model.cards[String(row.id)]}
                 onCard={onCard} onCardMenu={onCardMenu} onStatus={onStatus} />
          ))}
        </tbody>
      </table>
    </>
  )
}

interface RowProps {
  row: DayListRow
  actions: { to: string; cls: string; label: string; confirm: string }[]
  clickable: boolean
  busy: boolean
  onCard: (id: number) => void
  onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
  onStatus: (id: number, to: string) => void
}

function Row({ row, actions, clickable, busy, onCard, onCardMenu, onStatus }: RowProps) {
  return (
    <tr className={row.status}>
      <td>{row.id}</td>
      <td>{row.time}</td>
      <td>
        {clickable ? (
          <>
            <AppLink className="plink" href="#addform"
               onClick={(e) => { e.preventDefault(); onCard(row.id) }}
               onContextMenu={(e) => { e.preventDefault(); onCardMenu?.(row.id, e.clientX, e.clientY) }}>{row.name}</AppLink>
            {row.age ? <small className="dp-age"> ({row.age} ani)</small> : null}
          </>
        ) : row.name}
      </td>
      <td>{row.phone}</td>
      <td>
        {row.is_note ? <><Icon name="note" /> </>
          : row.urgent ? <><Icon name="sos" /> </> : null}
        {row.service}
        {row.comment_cut ? (
          <><br /><small className="dp-cmt"><Icon name="chat" /> {row.comment_cut}</small></>
        ) : null}
      </td>
      <td>{row.doctor}</td>
      <td>
        <Icon name={row.is_note ? 'note' : row.source === 'bot' ? 'bot' : 'pen'} />
        {' '}{row.source_label}
      </td>
      <td>
        <span className={`stat s-${row.status}`}>{row.status_label}</span>
        {row.reminded ? (
          <span className="rem-mark" title={T.reminded}><Icon name="bell" /></span>
        ) : null}
        {row.rec ? (
          <span className="rec-mark" title={T.rec}><Icon name="med" /></span>
        ) : null}
      </td>
      <td>
        {actions.map((a) => (
          <form key={a.to} className="act" onSubmit={(e) => {
            e.preventDefault()
            if (a.confirm && !window.confirm(a.confirm)) return
            onStatus(row.id, a.to)
          }}>
            <button className={a.cls} disabled={busy}>
              {a.cls === 'b-reopen' ? <><Icon name="undo" /> </> : null}{a.label}
            </button>
          </form>
        ))}
      </td>
    </tr>
  )
}
