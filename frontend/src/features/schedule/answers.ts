import type { DeskAnswer, DeskConfirm } from './desk'

/**
 * Плашка «пациент ответил» на главной (Premium, вид A): ответ ссылкой из напоминания всплывает
 * тёмной строкой внизу справа, нажатие открывает окно визита.
 *
 * ⛔ «Новое» — только из разницы двух конвертов живого канала, как `fresh` и `moved`: в конверте
 * нет ни одного «сейчас», сервер отдаёт список ответов как он есть (`desk.answers`), а что из него
 * появилось с прошлого опроса, решает экран по паре `id` + `answer_at` + `call`. Смена ответа
 * («Vin» → «Nu pot veni») — новая пара и новая плашка.
 * ⚠️ Первый показ (открыли главную, вернулись с другого экрана, утро) не всплывает НИЧЕМ: ответы,
 * пришедшие, пока программа была закрыта, видны в окне визита и в «De confirmat» — пачка плашек
 * утром была бы не сигналом, а шумом (Олег 27.11, вопрос 21).
 * ⚠️ `answers === null` — плашек нет вовсе (нет права, ссылки или галочки «Anunță pe ecran»); и
 * память сбрасывается: включённая галочка не выплеснет старые ответы разом.
 */

/** Сколько висит плашка «Vin» (мс). «Nu poate veni» висит до крестика. */
export const ANSWER_MS = 8000
/** Плашек в стопке не больше: новая снизу, у угла; лишняя сверху уходит. */
export const ANSWER_MAX = 3

/** Плашка на экране: ответ и ключ его пары. */
export interface AnswerPlate { key: string; a: DeskAnswer }

export function answerKey(a: DeskAnswer): string {
  return `${a.id}|${a.answer_at}|${a.call}`
}

/** Ключи ответов конверта; `null` — плашки выключены (память забывается). */
export function answerKeys(now: readonly DeskAnswer[] | null | undefined): Set<string> | null {
  return now ? new Set(now.map(answerKey)) : null
}

/** Что появилось с прошлого конверта. `prev === null` — первый показ: пусто. */
export function newAnswers(
  prev: ReadonlySet<string> | null, now: readonly DeskAnswer[] | null | undefined,
): DeskAnswer[] {
  if (prev === null || !now) return []
  return now.filter((a) => !prev.has(answerKey(a)))
}

/** Стопка после прихода новых: прежняя плашка того же визита уступает новой (ответ сменили),
 *  новые — снизу, лишние сверху уходят. */
export function stackAnswers(shown: readonly AnswerPlate[], got: readonly DeskAnswer[]): AnswerPlate[] {
  if (!got.length) return [...shown]
  const ids = new Set(got.map((a) => a.id))
  const next = [...shown.filter((p) => !ids.has(p.a.id)), ...got.map((a) => ({ key: answerKey(a), a }))]
  return next.slice(-ANSWER_MAX)
}

/** День визита ответа (ISO) — из списков обзвона, откуда сервер его и собрал; нет — `null`. */
export function answerDay(a: DeskAnswer, lists: readonly DeskConfirm[]): string | null {
  for (const l of lists) {
    if (l.items.some((it) => it.id === a.id)) return l.date
  }
  return null
}
