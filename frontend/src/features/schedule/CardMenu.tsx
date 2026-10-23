import { useRef } from 'react'
import { AppLink } from '../../components/AppLink'
import { when } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { placeMenu, useMenuDismiss } from '../../components/menu'
import { splitActions } from './CardDialog'
import type { StatusAction, VisitCardView } from './day'
import { CALL_WORDS, type CallResult } from './desk'

/*
 * Контекстное меню карточки визита — правая кнопка по записи в сетке, в
 * повестке и в списке дня (просьба клиники 25.09: как у зуба в одонтограмме).
 *
 * ⛔ Кнопки исхода — С СЕРВЕРА (`actions[status]`), той же матрицей, что у
 * диалога карточки и у списка дня: свой список здесь разошёлся бы молча —
 * закрытая запись получила бы «A venit» в меню и не получила бы в диалоге.
 * Вопрос подтверждения — тоже серверный, по классу действия.
 * ⛔ Меню — не единственный путь: то же есть в диалоге по левому клику (touch,
 * клавиатура, читалка). Закрывается кликом мимо, Esc, прокруткой, размером.
 * ⭐ Фиша — ссылкой (`AppLink`, переход без перезагрузки), а не командой:
 * средняя кнопка и Ctrl открывают её в новой вкладке, как у любой ссылки.
 */
const T = {
  fisa: 'Fișa pacientului',
  odo: 'Deschide odontograma',
} as const

export interface CardMenuAt {
  id: number
  x: number
  y: number
}

interface Props {
  at: CardMenuAt
  card: VisitCardView
  actions: StatusAction[]
  busy: boolean
  onStatus: (to: string) => Promise<boolean>
  /** Отметка звонка (12.10) — те же слова и то же правило `callable`, что у
   *  диалога карточки; меню после пункта закрывается, как после статуса. */
  onCall?: (result: CallResult) => Promise<boolean>
  onClose: () => void
}

const WIDTH = 240
const ROW = 32

export function CardMenu({ at, card, actions, busy, onStatus, onCall, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useMenuDismiss(ref, onClose)
  const fisa = card.pid !== null
  const { steps, neg, reopen } = splitActions(actions)
  const calls: { result: CallResult; label: string; icon: 'check' | 'phone-off' | 'undo' }[] =
    card.callable && onCall
      ? [
          ...(card.call !== 'ok' ? [{ result: 'ok' as const, label: CALL_WORDS.ok, icon: 'check' as const }] : []),
          ...(!card.call ? [{ result: 'noanswer' as const, label: CALL_WORDS.no, icon: 'phone-off' as const }] : []),
          ...(card.call ? [{ result: '' as const, label: CALL_WORDS.undo, icon: 'undo' as const }] : []),
        ]
      : []
  /* фиша и одонтограмма (08.10, макет списка дня) — два пункта под чертой;
     звонок (12.10) — своей группой под исходами */
  const height = 40 + actions.length * ROW + (neg.length && steps.length ? 9 : 0)
    + (calls.length ? ROW * calls.length + 9 : 0)
    + (fisa ? ROW * 2 + 9 : 0) + 12
  const { left, top } = placeMenu(at.x, at.y, WIDTH, height)
  return (
    <div ref={ref} className="dp-cmenu" role="menu" aria-label={`${card.time} — ${card.name}`}
      style={{ left, top, width: WIDTH }}>
      <div className="dp-cmenu-h">{card.time} — {card.name}</div>
      {/* Тот же порядок, что в ряду окна (23.10): ступени — первой жирно
          следующий шаг, исключения «Nu a venit»/«Anulează» — приглушённо под
          чертой. Состав и порядок внутри групп — серверные. */}
      {steps.map((a, i) => (
        <button
          key={a.to}
          type="button"
          role="menuitem"
          className={`dp-cmenu-i dp-cmenu-${a.cls}${i === 0 ? ' dp-cmenu-next' : ''}`}
          disabled={busy}
          onClick={() => { void when(a.confirm, () => { void onStatus(a.to) }) }}
        >
          {a.label}
        </button>
      ))}
      {reopen && (
        <button type="button" role="menuitem" className="dp-cmenu-i dp-cmenu-b-reopen" disabled={busy}
          onClick={() => { void when(reopen.confirm, () => { void onStatus(reopen.to) }) }}>
          <Icon name="undo" /> {reopen.label}
        </button>
      )}
      {neg.length > 0 && (
        <>
          {steps.length > 0 && <div className="dp-cmenu-sep" />}
          {neg.map((a) => (
            <button
              key={a.to}
              type="button"
              role="menuitem"
              className={`dp-cmenu-i dp-cmenu-${a.cls} dp-cmenu-neg`}
              disabled={busy}
              onClick={() => { void when(a.confirm, () => { void onStatus(a.to) }) }}
            >
              {a.label}
            </button>
          ))}
        </>
      )}
      {calls.length > 0 && onCall && (
        <>
          {actions.length > 0 && <div className="dp-cmenu-sep" />}
          {calls.map((c) => (
            <button key={c.result || 'undo'} type="button" role="menuitem"
              className={`dp-cmenu-i dp-cmenu-call${c.result ? ` ${c.result}` : ''}`} disabled={busy}
              onClick={() => { void onCall(c.result); onClose() }}>
              <Icon name={c.icon} /> {c.label}
            </button>
          ))}
        </>
      )}
      {fisa && (
        <>
          {(actions.length > 0 || calls.length > 0) && <div className="dp-cmenu-sep" />}
          <AppLink role="menuitem" className="dp-cmenu-i" href={`/admin/patient/${card.pid}/odontograma`} onClick={onClose}>
            <Icon name="tooth" /> {T.odo}
          </AppLink>
          <AppLink role="menuitem" className="dp-cmenu-i" href={`/admin/patient/${card.pid}`} onClick={onClose}>
            <Icon name="id" /> {T.fisa}
          </AppLink>
        </>
      )}
    </div>
  )
}
