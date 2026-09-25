import { useCallback, type AnchorHTMLAttributes, type MouseEvent } from 'react'
import { Link, matchRoutes, useInRouterContext, useNavigate } from 'react-router'
import { ROUTES } from '../app/routes'
import { defaultNavigate } from '../hooks/useLoad'

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

/**
 * Простой щелчок — тот, который перехватывает и `Link` роутера: левая кнопка
 * без модификаторов, у ссылки нет своей цели (`target`), и никто выше не
 * отменил действие. Всё остальное (Ctrl, средняя кнопка, «открыть в новой
 * вкладке») остаётся браузеру, как у обычной ссылки.
 */
export function isPlainClick(e: MouseEvent<HTMLElement>, target: string | null = null): boolean {
  return e.button === 0 && !e.defaultPrevented
    && !(target && target !== '_self')
    && !(e.metaKey || e.altKey || e.ctrlKey || e.shiftKey)
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
 * ⚠️ Вне дерева роутера (кусок экрана, открытый в проверке сам по себе) —
 * тоже обычная ссылка: `Link` без роутера бросает, а ссылка документом —
 * ровно то, что было до B4.
 */
export function AppLink({ href, ...rest }: Props) {
  const routed = useInRouterContext()
  return routed && isAppHref(href) ? <Link to={href} {...rest} /> : <a href={href} {...rest} />
}

/**
 * Переход ПОСЛЕ ДЕЙСТВИЯ (новый врач → его карточка, стёртая фиша → список):
 * адрес экрана — роутером, как `AppLink`; всё остальное (файл, печатный лист,
 * вход) — документом через `fallback`. ⚠️ `navigate` экрана остаётся входу:
 * 401 обязан уводить документом, и здесь он не подменяется.
 */
export function useAppNavigate(fallback: (url: string) => void = defaultNavigate): (url: string) => void {
  const navigate = useNavigate()
  return useCallback((url: string) => {
    if (isAppHref(url)) void navigate(url)
    else fallback(url)
  }, [navigate, fallback])
}

/**
 * Ссылки в серверной ПРОЗЕ — баннерах и плашках, которые приезжают готовой
 * разметкой (`frame.msg`, `frame.update`, сигналы): `AppLink` туда не
 * поставить, а переход по ним обязан быть тем же, что у ссылки приложения.
 * Обработчик вешается на контейнер прозы; правило то же: экран из карты и
 * простой щелчок — роутером, остальное — браузеру.
 */
export function useProseLinks(): (e: MouseEvent<HTMLElement>) => void {
  const navigate = useNavigate()
  return useCallback((e: MouseEvent<HTMLElement>) => {
    const a = (e.target as HTMLElement).closest('a')
    if (!a || !e.currentTarget.contains(a)) return
    const href = a.getAttribute('href')
    if (!href || !isPlainClick(e, a.getAttribute('target')) || !isAppHref(href)) return
    e.preventDefault()
    void navigate(href)
  }, [navigate])
}
