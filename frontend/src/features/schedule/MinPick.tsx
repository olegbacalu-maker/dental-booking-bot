import { hourMinutes } from './slot'

/* Час и минута старта — общие на окна записи и переноса. Занятые минуты —
   подсказка по канве; правду говорит сервер под своим замком. */

const T = { group: 'Minute', taken: 'ocupat', hour: 'Ora' } as const

interface HourProps {
  hours: string[]
  value: string
  onPick: (hour: string) => void
}

export function HourSelect({ hours, value, onPick }: HourProps) {
  return (
    <label className="dlab dp-hourpick">{T.hour}
      <select value={value} onChange={(e) => onPick(e.target.value)}>
        {hours.map((t) => <option key={t} value={t}>{t.split(':')[0]}</option>)}
      </select>
    </label>
  )
}

interface Props {
  /** Час «HH» — кнопка подписана полным временем для читающих с экрана. */
  hh: string
  value: number
  step?: number
  taken?: ReadonlySet<number>
  onPick: (minute: number) => void
}

export function MinPick({ hh, value, step = 5, taken, onPick }: Props) {
  return (
    <div className="dp-minpick" role="group" aria-label={T.group}>
      {hourMinutes(step).map((m) => {
        const mm = String(m).padStart(2, '0')
        const off = taken?.has(m) ?? false
        return (
          <button type="button" key={m} disabled={off} aria-pressed={value === m}
                  className={`mp${value === m ? ' on' : ''}${off ? ' taken' : ''}`}
                  aria-label={`${hh}:${mm}`} title={off ? `${hh}:${mm} · ${T.taken}` : `${hh}:${mm}`}
                  onClick={() => onPick(m)}>
            :{mm}
          </button>
        )
      })}
    </div>
  )
}
