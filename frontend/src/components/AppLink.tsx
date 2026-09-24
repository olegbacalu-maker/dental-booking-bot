import type { AnchorHTMLAttributes } from 'react'
import { Link, matchRoutes } from 'react-router'
import { ROUTES } from '../app/routes'

/* Таблица путей — та же, по которой выбирает экран роутер (routes.ts, производная
   от серверной карты): своей здесь нет. */
const TABLE = ROUTES.map((r) => ({ path: r.path }))

/**
 * Ведёт ли адрес на экран приложения — то есть можно ли перейти без
 * перезагрузки. ⛔ Не экран (выгрузка, печать, вход) и `?ui=legacy` — нет:
 * такой адрес открывает документ, как и раньше.
 */
export function isAppHref(href: string): boolean {
  let u: URL
  try {
    u = new URL(href, window.location.href)
  } catch {
    return false
  }
  if (u.origin !== window.location.origin) return false
  if (u.searchParams.getAll('ui').includes('legacy')) return false
  return matchRoutes(TABLE, u.pathname) !== null
}

type Props = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { href: string }

/**
 * Ссылка между экранами (B4 перехода к SPA): переход роутером, без
 * перезагрузки документа, — сайдбар и шапка остаются на месте.
 *
 * ⭐ В разметке это тот же `<a href>`: Ctrl, средняя кнопка и «открыть в новой
 * вкладке» работают, как у обычной ссылки, — `Link` роутера перехватывает
 * только простой щелчок. ⛔ Адрес не из карты маршрутов остаётся обычной
 * ссылкой: иначе переход привёл бы к экрану «такого экрана нет», а не к
 * странице, которую сервер по этому адресу отдаёт.
 */
export function AppLink({ href, ...rest }: Props) {
  return isAppHref(href) ? <Link to={href} {...rest} /> : <a href={href} {...rest} />
}
