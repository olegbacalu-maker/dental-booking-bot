import type { Room } from './move'

/* Выбор кабинета — общий на окна записи, переноса и визита. Рисуется только
   у врача с несколькими кабинетами: хозяин окна решает это по длине списка. */

const T = {
  room: 'Cabinet',
  auto: 'primul cabinet liber',
  shared: (name: string) =>
    `Atenție: în cabinetul ${name} are programare și alt medic la această oră.`,
} as const

/** Слово предупреждения: кабинет в это время занят записью другого врача. */
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
  return (
    <label className="dlab dp-hourpick dp-roompick">{T.room}
      <select value={value} onChange={(e) => onPick(e.target.value)}>
        {auto ? <option value="">{T.auto}</option> : null}
        {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
    </label>
  )
}
