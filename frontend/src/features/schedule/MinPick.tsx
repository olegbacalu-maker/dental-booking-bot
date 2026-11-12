import { hourMinutes } from './slot'

/* Минута старта внутри часа — один ряд кнопок на окно свободного часа, окно
   «Programare nouă» и окно переноса: три своих выбора разошлись бы молча.

   Занятые минуты — подсказка по канве (их считает хозяин окна тем же
   `clashAmong`, что помеху переносу): заведомо занятый старт не нажать.
   Правду говорит сервер под своим замком — пока окно открыто, время мог
   занять второй администратор. */

const T = { group: 'Minute', taken: 'ocupat' } as const

interface Props {
  /** Час «HH» — кнопка подписана полным временем для читающих с экрана. */
  hh: string
  value: number
  step?: number
  /** Минуты часа, занятые по канве; нет — подсказки нет. */
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
