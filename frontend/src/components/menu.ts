import { useEffect, type RefObject } from 'react'

/**
 * Общее у контекстных меню (зуб в одонтограмме, карточка визита): как меню
 * закрывается и как вписывается в окно. Два меню с двумя копиями этого
 * разошлись бы молча — одно закрывалось бы прокруткой, другое нет.
 */

/** Закрыть по клику мимо, Esc, прокрутке и смене размера окна. */
export function useMenuDismiss(ref: RefObject<HTMLElement | null>, onClose: () => void): void {
  useEffect(() => {
    /* ⚠️ Закрывает НАЖАТИЕ мимо — pointerdown, а не mousedown. Меню, открытое
       долгим нажатием пальцем (B7 · планшет): отпускание пальца рождает у
       браузера совместимые mousedown/mouseup/click, и по mousedown меню
       закрывалось в тот же миг (замер в эмуляции iPad 26.09: открылось на
       +511 мс, закрылось на отпускании). Отпускание не даёт pointerdown. */
    const down = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key)
    window.addEventListener('resize', onClose)
    window.addEventListener('scroll', onClose, true)
    return () => {
      document.removeEventListener('pointerdown', down)
      document.removeEventListener('keydown', key)
      window.removeEventListener('resize', onClose)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [ref, onClose])
}

/** Место меню: у курсора, но целиком в окне. */
export function placeMenu(x: number, y: number, width: number, height: number): { left: number; top: number } {
  return {
    left: Math.max(4, Math.min(x, window.innerWidth - width - 4)),
    top: Math.max(4, Math.min(y, window.innerHeight - height - 4)),
  }
}
