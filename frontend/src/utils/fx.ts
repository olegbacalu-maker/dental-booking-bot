/**
 * Входные анимации экрана: считающая цифра и вопрос «можно ли сейчас».
 *
 * Переехали сюда из `features/schedule/dashFx` в тот момент, когда цифры
 * понадобились ВТОРОМУ экрану (аналитика, C15): у плитки панели и у плитки
 * статистики это одно и то же поведение с одной и той же длительностью, и
 * вторая копия разошлась бы с первой ровно так же молча, как расходятся
 * словари статусов.
 */
import { useEffect, useRef, useState } from 'react'

/** Длительность счёта от нуля — та же, что в `panel.js`. */
export const COUNT_MS = 620

/**
 * Можно ли проигрывать входную анимацию ПРЯМО СЕЙЧАС.
 *
 * ⛔ Два условия, и оба чужие. Класс `anim` ставит каркас (`core/layout`) и
 * снимает его повтор после действия: «человек пришёл на страницу» против
 * «страницу перепоказали». Просьба системы уменьшить движение — это просьба, а
 * не пожелание, и оформление её уже уважает
 * (`@media (prefers-reduced-motion:reduce)` в panel.css).
 * ⚠️ РАСХОЖДЕНИЕ С ЛЕГАСИ, названное вслух: там счётчик живёт в JS и про
 * `prefers-reduced-motion` не знает — шесть цифр считают вверх даже у того,
 * кто попросил тишины. Повторять этот промах в новом коде не стал; чинить
 * легаси по дороге — нельзя (это отдельное решение).
 * ⚠️ `matchMedia` в jsdom нет вовсе, поэтому вызов в try.
 */
export function canAnimate(): boolean {
  try {
    if (typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  } catch { /* движок без matchMedia */ }
  return document.documentElement.classList.contains('anim')
}

/**
 * Цифра, считающая от нуля при ПЕРВОМ показе (перенос `data-count`).
 *
 * ⛔ Истина — `value`, всегда. Хук решает только, ЧТО ПОКАЗАТЬ в первые
 * 620 мс; всё остальное время он отдаёт значение как есть, а приехавшее
 * конвертом новое значение показывается СРАЗУ и без счёта — ровно как у
 * легаси, где живая подмена счётчик не перезапускает и не могла бы:
 * `apply()` снимает `anim` до неё. Анимация здесь представление, а не
 * состояние, и обратного пути у неё нет.
 * ⚠️ Ноль и единица не считаются (`value < 2`): «счёт» от нуля до единицы —
 * это мигание, а не движение. Условие взято у легаси дословно.
 */
export function useCountUp(value: number, active: boolean): number {
  const [shown, setShown] = useState(() => (active && value >= 2 ? 0 : value))
  const done = useRef(!active || value < 2)
  useEffect(() => {
    if (done.current) {
      setShown(value)                    // данные победили: показываем их
      return
    }
    done.current = true
    let raf = 0
    const t0 = performance.now()
    /* ⚠️ Время берётся у `performance.now()` и в начале, и в кадре, а НЕ из
       аргумента `requestAnimationFrame`: часы у них разные (в jsdom — заметно
       разные), и разность двух шкал даёт бессмысленную долю. Легаси считал по
       аргументу и был прав у себя; здесь важнее, чтобы обе точки были с одних
       часов. */
    const step = () => {
      const p = Math.min((performance.now() - t0) / COUNT_MS, 1)
      /* та же кривая, что в panel.js: cubic ease-out */
      setShown(Math.round(value * (1 - Math.pow(1 - p, 3))))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return shown
}


/**
 * Разделитель тысяч — неразрывного пробела здесь НЕТ, ровно как у сервера
 * (`stats._fmt_mdl`) и у `panel.js`.
 *
 * ⚠️ Формат живёт в двух местах, и это не недосмотр: строку с деньгами
 * форматирует СЕРВЕР (она же уходит в печатный отчёт кассы), но счётчик
 * переписывает текст на каждом кадре и формата у сервера спросить не может.
 * У легаси ровно та же пара — `_fmt_mdl` в Python и `fmt` в `panel.js`.
 * Разойдутся они молча, поэтому совпадение с серверной строкой проверяется.
 */
export function groupThousands(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}
