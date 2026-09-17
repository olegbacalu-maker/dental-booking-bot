import { ICONS, type IconName } from './icons'

/** Имя иконки, пришедшее строкой с сервера; неизвестное — общий значок. */
export function iconName(name: string): IconName {
  return (name in ICONS ? name : 'info') as IconName
}

/**
 * Значок = иконка из layout._I, идущая currentColor: цвет клиники она берёт
 * сама (правило карты «ничего графического от Windows»). Атрибуты те же, что
 * у серверного _ic(), поэтому рядом с серверной разметкой она неотличима.
 * innerHTML здесь безопасен: разметка — константа сборки из нашего же
 * источника (icons.ts генерируется из layout.py), а не данные пользователя.
 */
export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  )
}
