import { useEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { DashMiniCal } from './dash'

/* Мини-календарь месяца — ОДИН на правую колонку главной и на шапку дня
   врача (22.10, вариант H Олега: дата в подзаголовке открывает его). Месяц,
   точки и ссылки строит сервер (`panel.minical`): у главной ссылки ведут на
   `/admin`, у дня врача — на `/admin/doctor/{dk}`, и точки там только его.
   ⛔ Второго календаря не заводить: две копии разойдутся в метках молча. */

const T = {
  prev: '‹',
  next: '›',
  prevMonth: 'Luna precedentă',
  nextMonth: 'Luna următoare',
  withAppts: 'are programări',
  pick: 'Alege data',
} as const

/**
 * Месяц полными неделями Пн–Вс.
 *
 * ⛔ Четыре метки НЕЗАВИСИМЫ и складываются: `oth tdy` — законное сочетание,
 * сегодняшний день в хвосте прошлого месяца; точка `busy` (08.10) — у любого
 * из них. Склей их в одно поле — и такой день перестанет подсвечиваться.
 * ⚠️ Стрелки — литералы `‹`/`›` (U+2039/U+203A), а не иконки: так на старой
 * странице, оба знака в вшитом подмножестве Inter, и замена на `chev-l`
 * развела бы два экрана визуально. Это решение, а не недосмотр.
 */
export function MiniCal({ cal }: { cal: DashMiniCal }) {
  return (
    <div className="mcal">
      <div className="mhead">
        <AppLink href={cal.prev.href} aria-label={T.prevMonth}>{T.prev}</AppLink>
        <b>{cal.title}</b>
        <AppLink href={cal.next.href} aria-label={T.nextMonth}>{T.next}</AppLink>
      </div>
      <table>
        <tbody>
          <tr>{cal.weekdays.map((w) => <th key={w}>{w}</th>)}</tr>
          {cal.weeks.map((week) => (
            <tr key={week[0]!.date}>
              {week.map((c) => (
                <td key={c.date}>
                  <AppLink className={[c.other && 'oth', c.today && 'tdy', c.selected && 'seld']
                    .filter(Boolean).join(' ')} href={c.href}
                    aria-current={c.selected ? 'date' : undefined}
                    title={c.busy ? `${c.date} · ${T.withAppts}` : c.date}>
                    {c.day}{c.busy && <i className="dot" />}
                  </AppLink>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Дата в подзаголовке дня врача — кнопка (22.10, вариант H Олега): по
 * нажатию под ней всплывает `MiniCal` этого врача. День в календаре —
 * ссылка роутера на `/admin/doctor/{dk}?date=`, и выбор закрывает окно;
 * стрелки месяца листают, не закрывая. Закрывают ещё Esc и щелчок мимо.
 * ⛔ Окно поверх страницы, фокус в него не переводится: страница не
 * прокручивается и не прыгает (Олег 14.10, «без прыжков»).
 */
export function CalButton({ label, cal }: { label: string; cal: DashMiniCal }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement | null>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape'
        : !box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', off)
    document.addEventListener('keydown', off)
    return () => {
      document.removeEventListener('pointerdown', off)
      document.removeEventListener('keydown', off)
    }
  }, [open])
  return (
    <span className="dp-calbtn" ref={box}>
      <button type="button" aria-expanded={open} aria-haspopup="dialog" title={T.pick}
        onClick={() => setOpen((v) => !v)}>
        <Icon name="cal" /><b className="dp-daysub-date">{label}</b><Icon name="caret-d" />
      </button>
      {open && (
        <span className="dp-calpop" role="dialog" aria-label={T.pick}
          onClick={(e) => { if ((e.target as HTMLElement).closest('td a')) setOpen(false) }}>
          <MiniCal cal={cal} />
        </span>
      )}
    </span>
  )
}
