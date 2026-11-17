import { CONTROL, hasControl, type Room } from './move'

/* Выбор кабинета — общий на окна записи, переноса и визита. Рисуется только
   у врача с несколькими кабинетами: хозяин окна решает это по длине списка. */

const T = {
  room: 'Cabinet',
  lane: 'Coloana',
  control: 'Control (în paralel)',
  auto: 'primul cabinet liber',
  shared: (name: string) =>
    `Atenție: în cabinetul ${name} are programare și alt medic la această oră.`,
} as const

export function sharedWarn(rooms: readonly Room[], id: string): string {
  return T.shared(rooms.find((r) => r.id === id)?.name ?? id)
}

interface Props {
  rooms: readonly Room[]
  /** Ключ кабинета; `''` при `auto` — выбирает сервер. */
  value: string
  onPick: (id: string) => void
  /** Первая строка «primul cabinet liber»: у окна нет канвы, чтобы назвать его. */
  auto?: boolean
}

export function RoomSelect({ rooms, value, onPick, auto = false }: Props) {
  const ctl = hasControl(rooms)
  /* у врача без кабинетов основная дорожка — id «»: она и есть «первый свободный» */
  const blank = rooms.some((r) => r.id === '')
  return (
    <label className={`dlab dp-hourpick dp-roompick${value === CONTROL ? ' dp-ctlpick' : ''}`}>{ctl && blank ? T.lane : T.room}
      <select value={value} onChange={(e) => onPick(e.target.value)}>
        {auto && !blank ? <option value="">{T.auto}</option> : null}
        {rooms.map((r) => <option key={r.id} value={r.id}>
          {r.control ? T.control : r.name}</option>)}
      </select>
    </label>
  )
}

/** Кнопка в отказе «основная занята»: та же запись — в дорожку Control; с `next` —
 *  вторая кнопка «Alege HH:MM» (ближайшее свободное время основной колонки). */
export function AsControl({ onClick, disabled, next, onNext, label = 'Adaugă ca control' }: {
  onClick: () => void; disabled?: boolean; next?: string | null; onNext?: (t: string) => void
  /** Слово кнопки: у переноса — «Mută în Control». */
  label?: string
}) {
  return (
    <div className="dp-asctl">
      <div className="dp-asctl-b">
        <button type="button" className="btn-ctl" onClick={onClick} disabled={disabled}>{label}</button>
        {next && onNext
          ? <button type="button" className="btn-next" onClick={() => onNext(next)}>Alege {next}</button> : null}
      </div>
      <small className="hint">Control — programare scurtă în coloana îngustă a medicului, în paralel cu cea existentă.</small>
    </div>
  )
}
