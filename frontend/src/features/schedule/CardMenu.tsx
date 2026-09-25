import { useRef } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { placeMenu, useMenuDismiss } from '../../components/menu'
import type { StatusAction, VisitCardView } from './day'

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
  onClose: () => void
}

const WIDTH = 240
const ROW = 32

export function CardMenu({ at, card, actions, busy, onStatus, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useMenuDismiss(ref, onClose)
  const fisa = card.pid !== null
  const height = 40 + actions.length * ROW + (fisa ? ROW + 9 : 0) + 12
  const { left, top } = placeMenu(at.x, at.y, WIDTH, height)
  return (
    <div ref={ref} className="dp-cmenu" role="menu" aria-label={`${card.time} — ${card.name}`}
      style={{ left, top, width: WIDTH }}>
      <div className="dp-cmenu-h">{card.time} — {card.name}</div>
      {actions.map((a) => (
        <button
          key={a.to}
          type="button"
          role="menuitem"
          className={`dp-cmenu-i dp-cmenu-${a.cls}`}
          disabled={busy}
          onClick={() => {
            if (a.confirm && !window.confirm(a.confirm)) return
            void onStatus(a.to)
          }}
        >
          {a.cls === 'b-reopen' ? <><Icon name="undo" /> </> : null}{a.label}
        </button>
      ))}
      {fisa && (
        <>
          {actions.length > 0 && <div className="dp-cmenu-sep" />}
          <AppLink role="menuitem" className="dp-cmenu-i" href={`/admin/patient/${card.pid}`} onClick={onClose}>
            <Icon name="id" /> {T.fisa}
          </AppLink>
        </>
      )}
    </div>
  )
}
