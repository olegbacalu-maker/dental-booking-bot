/**
 * Форма румынского существительного при числе (09.11: «restul ajunge pentru ~1 zile»).
 *
 *   one  — ровно 1: «1 zi»
 *   few  — 0, 2–19 и всё, что кончается на 01–19: «2 zile», «105 zile»
 *   many — от 20, кроме окончаний 01–19: «20 de zile», «100 de zile», «120 de zile»
 *
 * Слова остаются в словаре экрана (`t()`): здесь только выбор формы.
 */
export type RoForm = 'one' | 'few' | 'many'

export function roForm(n: number): RoForm {
  const a = Math.abs(Math.trunc(n))
  if (a === 1) return 'one'
  const tail = a % 100
  return a >= 20 && (tail === 0 || tail >= 20) ? 'many' : 'few'
}

/** Строка нужной формы; `{n}` в ней заменяется числом. */
export function roCount(n: number, forms: Record<RoForm, string>): string {
  return forms[roForm(n)].replace('{n}', String(n))
}
