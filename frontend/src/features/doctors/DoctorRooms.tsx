import { Icon } from '../../components/Icon'

/* Кабинеты врача в его фише: имена по порядку, первый — основной (туда ложится
   запись без выбора кабинета). Имя, совпавшее с уже известным, — тот же
   кабинет, его делят с другим врачом. */

const T = {
  room: 'Cabinet',
  group: 'Cabinete',
  main: 'principal',
  add: 'Adaugă cabinet',
  up: 'Mută mai sus',
  down: 'Mută mai jos',
  del: 'Scoate cabinetul',
  hint: (n: number) =>
    `Primul cabinet este cel principal. Cu mai multe cabinete, medicul poate avea programări în același timp — câte una în fiecare (cel mult ${n}).`,
} as const

interface Props {
  value: string[]
  known: string[]
  max: number
  invalid: boolean
  disabled: boolean
  onChange: (rooms: string[]) => void
}

export function DoctorRooms({ value, known, max, invalid, disabled, onChange }: Props) {
  const rows = value.length ? value : ['']
  const many = rows.length > 1
  const put = (i: number, name: string) => onChange(rows.map((x, j) => (j === i ? name : x)))
  const swap = (i: number, j: number) => {
    const next = [...rows]
    const a = next[i]
    const b = next[j]
    if (a === undefined || b === undefined) return
    next[i] = b
    next[j] = a
    onChange(next)
  }
  return (
    <div className="dp-rooms" role="group" aria-label={T.group}>
      {rows.map((name, i) => (
        <div className="dp-rooms-row" key={i}>
          <input
            value={name}
            onChange={(e) => put(i, e.target.value)}
            placeholder={T.room}
            aria-label={many ? `${T.room} ${i + 1}${i === 0 ? ` (${T.main})` : ''}` : T.room}
            maxLength={30}
            list="dp-rooms-known"
            aria-invalid={invalid || undefined}
            disabled={disabled}
          />
          {many ? (
            <>
              <button type="button" className="dp-rooms-b" title={T.up} aria-label={`${T.up}: ${name}`}
                disabled={disabled || i === 0} onClick={() => swap(i, i - 1)}>
                <Icon name="caret-u" />
              </button>
              <button type="button" className="dp-rooms-b" title={T.down} aria-label={`${T.down}: ${name}`}
                disabled={disabled || i === rows.length - 1} onClick={() => swap(i, i + 1)}>
                <Icon name="caret-d" />
              </button>
              <button type="button" className="dp-rooms-b" title={T.del} aria-label={`${T.del}: ${name}`}
                disabled={disabled} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
                <Icon name="trash" />
              </button>
            </>
          ) : null}
        </div>
      ))}
      <datalist id="dp-rooms-known">
        {known.map((n) => <option key={n} value={n} />)}
      </datalist>
      {rows.length < max ? (
        <button type="button" className="dp-rooms-add" disabled={disabled}
          onClick={() => onChange([...rows, ''])}>
          <Icon name="plus" /> {T.add}
        </button>
      ) : null}
      {many ? <small className="hint">{T.hint(max)}</small> : null}
    </div>
  )
}
