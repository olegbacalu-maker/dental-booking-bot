/* Строка «когда» в шапке окна записи: день, начало–конец. Считается из полей окна,
   а не из ответа сервера, чтобы меняться на каждый щелчок по минуте и длительности. */

const WEEKDAYS = ['duminică', 'luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă'] as const

const T = { pick: 'alegeți ora', next: '+1 zi' } as const

const pad = (n: number) => String(n).padStart(2, '0')
const clock = (min: number) => `${pad(Math.floor(min / 60) % 24)}:${pad(min % 60)}`

/** «sâmbătă, 14.11» из голой даты (день недели считается по календарю, не по поясу браузера);
 *  кривая дата — пустая строка. */
export function dayShort(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return ''
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const at = new Date(Date.UTC(y, mo - 1, d))
  if (at.getUTCMonth() !== mo - 1 || at.getUTCDate() !== d) return ''
  return `${WEEKDAYS[at.getUTCDay()]}, ${pad(d)}.${pad(mo)}`
}

/** `hour` — «HH» или «HH:00», пусто — час не выбран; `dur` ≤ 0 — длительности нет (поле не по
 *  правилу): тогда только начало. Конец за полночь — с пометкой, а не обрезанный по модулю. */
export function whenLine(date: string, hour: string, minute: number, dur: number): string {
  const hh = Number(hour.split(':')[0])
  if (!hour || Number.isNaN(hh)) return T.pick
  const start = hh * 60 + minute
  const span = dur > 0 ? `${clock(start)}–${clock(start + dur)}${start + dur >= 1440 ? ` (${T.next})` : ''}` : clock(start)
  const day = dayShort(date)
  return day ? `${day} · ${span}` : span
}
