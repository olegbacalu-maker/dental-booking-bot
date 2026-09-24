import { fireEvent } from '@testing-library/react'

/**
 * Щелчок по ссылке в проверке; ответ — пошёл бы браузер по ссылке САМ
 * (действие не отменено) или переход забрал роутер. Слушатель окна стоит
 * ПОСЛЕ корня React: видит решение роутера и отменяет действие сам, чтобы
 * jsdom не пытался грузить документ.
 */
export function nativeClick(el: HTMLElement, init: MouseEventInit = {}): boolean {
  let native = true
  const spy = (e: Event) => { native = !e.defaultPrevented; e.preventDefault() }
  window.addEventListener('click', spy)
  try {
    fireEvent.click(el, { button: 0, ...init })
  } finally {
    window.removeEventListener('click', spy)
  }
  return native
}
