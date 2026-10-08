import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { when } from '../../components/confirm'
import type { DayListRow, DayModel } from './day'

/* «Lista zilei» (C25.5c): все записи дня строками, с кнопками исхода.
   Вид — по макету Олега (08.10, промпт 2): карточка с заголовком и
   счётчиком, колонки Ora · Pacient (ссылка на фишу + возраст) · Telefon ·
   Serviciu (чип «Urgent» вместо значка) · Medic · Status (плашка) · Acțiuni
   (кнопка следующего шага + «⋯» 44px). Колонки «#» больше нет.

   ⛔ Это НЕ сетка. Список показывает ОТМЕНЁННЫЕ записи (в сетке их нет) и
   заметки стойки, и только отсюда заметку можно убрать и вернуть: карточки
   визита у неё нет по замыслу.
   ⛔ Кнопки берутся с сервера — `actions` для записи, `note_actions` для
   заметки. Свой список в браузере разошёлся бы молча с тем, что печатает
   старая страница.
   ⚠️ Комментарий здесь приезжает уже обрезанным до 80 знаков. Править его
   нельзя: полный текст живёт в карточке визита (`cards`), и сохранение
   обрезанного укоротило бы его без единой правки.
   ⭐ (06.10, Олег) В строке визита — ОДНА кнопка, следующий шаг (первое
   действие матрицы сервера), остальное — в меню «⋯»: то же меню исходов, что
   по правой кнопке, с теми же вопросами подтверждения, фишей и одонтограммой.
   ⭐ «Sursă» — только у клиники с ботом (`source_col`): без бота там везде
   «manual», и колонка ничего не различала. Заметку и так видно по значку в
   «Serviciu». */
const T = {
  title: 'Lista zilei',
  empty: 'Nicio programare în această zi.',
  all: 'arată tot',
  head: ['Ora', 'Pacient', 'Telefon', 'Serviciu', 'Medic', 'Sursă', 'Status', 'Acțiuni'],
  source: 'Sursă',
  more: 'Mai multe acțiuni',
  reminded: 'Reminder trimis',
  rec: 'Consultație completată',
  urgent: 'Urgent',
  noPhone: 'Fără telefon',
  years: 'ani',
  one: 'programare',
  many: 'programări',
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
  const head = model.source_col ? T.head : T.head.filter((h) => h !== T.source)
  const n = model.list.filter((r) => !r.is_note).length

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
      <section className="dp-card dp-dl">
        <div className="dp-dl-h">
          <h2>{title}</h2>
          <span className="dp-dl-n">{n} {n === 1 ? T.one : T.many}</span>
        </div>
        <div className="dp-dl-scroll">
          <table className="list">
            <tbody>
              <tr>{head.map((h) => <th key={h} className={h === 'Acțiuni' ? 'dp-dl-acts' : undefined}>{h}</th>)}</tr>
              {model.list.length === 0 ? (
                <tr><td colSpan={head.length} className="dp-empty">{T.empty}</td></tr>
              ) : model.list.map((row) => (
                <Row key={row.id} row={row} busy={busy} source={model.source_col}
                     actions={(row.is_note ? model.note_actions : model.actions)[row.status] ?? []}
                     clickable={!row.is_note && !!model.cards[String(row.id)]}
                     onCard={onCard} onCardMenu={onCardMenu} onStatus={onStatus} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

interface RowProps {
  row: DayListRow
  actions: { to: string; cls: string; label: string; confirm: string }[]
  clickable: boolean
  busy: boolean
  /** Колонка «Sursă» показана (у клиники с ботом). */
  source: boolean
  onCard: (id: number) => void
  onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
  onStatus: (id: number, to: string) => void
}

function Row({ row, actions, clickable, busy, source, onCard, onCardMenu, onStatus }: RowProps) {
  /* У визита с карточкой — следующий шаг и «⋯»; у заметки (и у строки без
     карточки, которой быть не должно) — её кнопки как есть: у заметки их одна. */
  const compact = clickable && !!onCardMenu
  const shown = compact ? actions.slice(0, 1) : actions
  return (
    <tr className={row.status}>
      <td className="dp-dl-time">{row.time}</td>
      <td>
        {clickable ? (
          <AppLink className="plink" href="#addform"
             onClick={(e) => { e.preventDefault(); onCard(row.id) }}
             onContextMenu={(e) => { e.preventDefault(); onCardMenu?.(row.id, e.clientX, e.clientY) }}>{row.name}</AppLink>
        ) : row.name}
        {row.age ? <small className="dp-age"> {row.age} {T.years}</small> : null}
      </td>
      <td className="dp-dl-phone">{row.phone || <i className="dp-nophone">{T.noPhone}</i>}</td>
      <td>
        <span className="dp-dl-svc">
          {row.is_note ? <Icon name="note" /> : null}
          {row.urgent ? <span className="chip urg"><Icon name="excl" />{T.urgent}</span> : null}
          {row.service}
        </span>
        {row.comment_cut ? (
          <small className="dp-cmt"><Icon name="chat" /> {row.comment_cut}</small>
        ) : null}
      </td>
      <td>{row.doctor}</td>
      {source ? (
        <td>
          <Icon name={row.is_note ? 'note' : row.source === 'bot' ? 'bot' : 'pen'} />
          {' '}{row.source_label}
        </td>
      ) : null}
      <td>
        {/* вид, а не код: «confirmată» даёт звонок-подтверждение (03.10) */}
        <span className={`stat s-${row.status_view}`}>{row.status_label}</span>
        {row.reminded ? (
          <span className="rem-mark" title={T.reminded}><Icon name="bell" /></span>
        ) : null}
        {row.rec ? (
          <span className="rec-mark" title={T.rec}><Icon name="med" /></span>
        ) : null}
      </td>
      <td className="dp-acts dp-dl-acts">
        {shown.map((a) => (
          <form key={a.to} className="act" onSubmit={(e) => {
            e.preventDefault()
            void when(a.confirm, () => onStatus(row.id, a.to))
          }}>
            <button className={`${a.cls} dp-next`} disabled={busy}>
              {a.cls === 'b-reopen' ? <><Icon name="undo" /> </> : null}{a.label}
            </button>
          </form>
        ))}
        {compact ? (
          /* ⛔ Меню ТО ЖЕ, что по правой кнопке (`CardMenu` экрана): исходы
             сервера, его вопросы подтверждения, фиша и одонтограмма. Место —
             под кнопкой. */
          <button type="button" className="dp-more dp-ibtn" title={T.more} aria-label={T.more}
                  aria-haspopup="menu" disabled={busy}
                  onClick={(e) => {
                    const r = e.currentTarget.getBoundingClientRect()
                    onCardMenu?.(row.id, r.left, r.bottom + 4)
                  }}>
            <Icon name="more" />
          </button>
        ) : null}
      </td>
    </tr>
  )
}
