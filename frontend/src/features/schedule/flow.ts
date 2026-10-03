import type { DashAgendaItem } from './dash'
import { WAIT_LONG_MIN, WAIT_SHOW_MIN } from './dashFx'

/* Поток пациента на главной (03.10; прототип в песочнице — «вариант А, делаем»).
   Слова Олега: «Întârzie интересно»; «A venit: сколько ждёт (после ~15 минут
   красным)»; «În cabinet: с какого времени и плановый конец… янтарная пометка
   „следующий пациент Dr. X будет ждать“ — этого сейчас нигде нет».

   ⛔ Всё считается ЗДЕСЬ, по отметкам повестки и тику браузера: сервер шлёт
   только время (start_ms, end_ms, wait_since), а не «N min» — иначе отпечаток
   живого канала менялся бы каждую минуту и экран мигал бы на каждом опросе.
   ⭐ Состояния — те же коды, что у кнопок карточки: confirmed → waiting
   («a venit») → arrived («în cabinet») → done. Своего словаря статусов тут нет. */

export type FlowKind = 'late' | 'waiting' | 'incab'

/** С какой минуты опоздания запись попадает в «Întârzie». */
export const LATE_AFTER_MIN = 5
/** Красное: опоздание и ожидание от стольких минут (слово Олега — «~15»).
 *  ⛔ Тот же порог, что у «așteaptă N min» повестки и сетки — не свой. */
export const LONG_MIN = WAIT_LONG_MIN
/** Меньше — «a venit acum»: тот же порог тишины, что у повестки. */
export const JUST_CAME_MIN = WAIT_SHOW_MIN

export interface FlowNext {
  name: string
  time: string
  /** уже ждёт в приёмной — сколько минут; null — ещё не пришёл */
  waiting: number | null
}

export interface FlowRow {
  it: DashAgendaItem
  /** минуты: опоздания (late), ожидания (waiting), сверх плана (incab) */
  min: number
  long: boolean
  /** «A venit»: врач занят — до какого часа по плану и на сколько уже сверх
   *  него; null — свободен, можно звать в кабинет */
  busy: { until: string; over: number } | null
  /** «În cabinet»: сколько минут до планового конца (0 — сверх плана) */
  left: number
  /** «În cabinet»: приём затянулся — кого он задержит */
  next: FlowNext | null
}

export interface Flow {
  late: FlowRow[]
  waiting: FlowRow[]
  incab: FlowRow[]
}

const mins = (ms: number) => Math.floor(ms / 60_000)
const docOf = (it: DashAgendaItem) => it.doctor_id || it.doctor

export function flowOf(items: DashAgendaItem[], now: number): Flow {
  const late: FlowRow[] = []
  const waiting: FlowRow[] = []
  const incab: FlowRow[] = []
  for (const it of items) {
    if (it.status === 'confirmed') {
      const m = mins(now - it.start_ms)
      if (m >= LATE_AFTER_MIN) late.push({ it, min: m, long: m >= LONG_MIN, busy: null, left: 0, next: null })
    } else if (it.status === 'waiting') {
      const m = it.wait_since ? Math.max(0, mins(now - it.wait_since)) : 0
      const cab = items.find((x) => x.status === 'arrived' && docOf(x) === docOf(it))
      const busy = cab ? { until: cab.end, over: Math.max(0, mins(now - cab.end_ms)) } : null
      waiting.push({ it, min: m, long: m >= LONG_MIN, busy, left: 0, next: null })
    } else if (it.status === 'arrived') {
      const over = mins(now - it.end_ms)
      let next: FlowNext | null = null
      if (over > 0) {
        // кого задержит: ближайшая следующая запись того же врача, ещё не начатая
        const n = items
          .filter((x) => x.id !== it.id && docOf(x) === docOf(it) && x.start_ms >= it.start_ms
            && (x.status === 'confirmed' || x.status === 'waiting'))
          .sort((a, b) => a.start_ms - b.start_ms)[0]
        if (n) {
          next = {
            name: n.name, time: n.time,
            waiting: n.status === 'waiting' && n.wait_since ? Math.max(0, mins(now - n.wait_since)) : null,
          }
        }
      }
      incab.push({ it, min: Math.max(0, over), long: false, busy: null,
        left: Math.max(0, mins(it.end_ms - now)), next })
    }
  }
  late.sort((a, b) => b.min - a.min)
  waiting.sort((a, b) => b.min - a.min)
  // затянувшиеся — первыми: это то, ради чего вкладка
  incab.sort((a, b) => (b.min > 0 ? 1 : 0) - (a.min > 0 ? 1 : 0) || a.it.end_ms - b.it.end_ms)
  return { late, waiting, incab }
}

/** «12 min», «1 h 05 min» — длительность словами клиники. */
export function dur(m: number): string {
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h} h ${String(r).padStart(2, '0')} min` : `${h} h`
}
