import { useCountUp } from '../utils/fx'

/**
 * Цифра плитки. ⛔ Истина — `value`; хук решает только, что показать в первые
 * 620 мс. Приехало новое значение — оно и стоит, без счёта.
 * ⚠️ `data-count` печатается и здесь: по нему читают проверки (у легаси это
 * КОНТРАКТ — тесты разбирают атрибут, а не текст), и расхождение текста с
 * атрибутом означало бы, что анимация стала источником правды.
 */
export function Count({ value, live, suffix = '' }:
{ value: number; live: boolean; suffix?: string }) {
  const shown = useCountUp(value, live)
  return <b data-count={value}>{shown}{suffix}</b>
}
