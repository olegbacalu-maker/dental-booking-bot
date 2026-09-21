import { groupThousands, useCountUp } from '../utils/fx'

/**
 * Цифра плитки. ⛔ Истина — `value`; хук решает только, что показать в первые
 * 620 мс. Приехало новое значение — оно и стоит, без счёта.
 * ⚠️ `data-count` печатается и здесь: по нему читают проверки (у легаси это
 * КОНТРАКТ — тесты разбирают атрибут, а не текст), и расхождение текста с
 * атрибутом означало бы, что анимация стала источником правды.
 * ⚠️ `group` — разделитель тысяч у денег. Он обязан ехать с КАЖДЫМ кадром, а
 * не только с последним: счётчик пишет текст целиком, и без него последний
 * кадр показывал «2550» вместо «2 550 MDL» (скрин Олега 08-07). Ровно это и
 * делает `data-suffix` у `panel.js`.
 */
export function Count({ value, live, suffix = '', group = false }:
{ value: number; live: boolean; suffix?: string; group?: boolean }) {
  const shown = useCountUp(value, live)
  return <b data-count={value}>{group ? groupThousands(shown) : shown}{suffix}</b>
}
