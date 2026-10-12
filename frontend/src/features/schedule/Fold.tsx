import { useState, type ReactNode } from 'react'
import { Icon } from '../../components/Icon'

/* Сворачиваемый блок правой колонки главной (12.10, слово Олега): «Agenda
   zilei», «Primul loc liber» и списки стойки. Свёрнутое ЗАПОМИНАЕТСЯ на этом
   компьютере (localStorage — удобство места, не данные клиники: пусто или
   недоступно — блок открыт).

   ⛔ Прыжок при сворачивании (замер 12.10 на песочнице): сетка дня тянется к
   высоте колонки только до 96 px на час, поэтому в загруженный день длину
   страницы задаёт ПРАВАЯ колонка — 2639 px против 970 у сетки. Свернул блок
   у низа страницы — документ короче на высоту списка, браузер обязан поджать
   прокрутку, и заголовок уезжал из-под мыши (238 px). Поэтому в момент
   сворачивания колонка держит прежнюю высоту (`holdColumn`), а лишнее
   отпускается, когда освобождённая полоса уйдёт за экран или страница и без
   неё длиннее колонки — тогда документ укорачивается невидимо.
   ⚠️ Высота ставится в `onClick` по summary — ДО действия браузера: событие
   `toggle` приходит задачей позже, и кадр со сжатым документом мог успеть. */

const KEY = 'dp_fold:'

function storedOpen(id: string): boolean {
  try {
    return localStorage.getItem(KEY + id) !== '0'
  } catch {
    return true
  }
}

function remember(id: string, open: boolean): void {
  try {
    if (open) localStorage.removeItem(KEY + id)
    else localStorage.setItem(KEY + id, '0')
  } catch {
    /* приватный режим: просто без памяти */
  }
}

/** Колонка, которую держим, и её проверка «можно отпускать». */
const held = new WeakMap<HTMLElement, () => void>()

/** Отпустить удержанную высоту, если от этого ничего не сдвинется на экране:
 *  освобождённая полоса целиком ниже окна, или страницу и так держит соседняя
 *  колонка (сетка длиннее). Иначе — ждать прокрутки. */
function settle(col: HTMLElement): boolean {
  const last = col.lastElementChild ?? col
  const natural = last.getBoundingClientRect().bottom
  const heldEnd = col.getBoundingClientRect().bottom
  const others = Array.from(col.parentElement?.children ?? [])
    .filter((c) => c !== col)
    .reduce((m, c) => Math.max(m, c.getBoundingClientRect().bottom), -Infinity)
  if (natural >= window.innerHeight - 1 || others >= heldEnd - 1) {
    col.style.minHeight = ''
    return true
  }
  return false
}

export function holdColumn(from: Element): void {
  const col = from.closest<HTMLElement>('.rail')
  if (!col) return
  const prev = held.get(col)
  if (prev) {
    window.removeEventListener('scroll', prev)
    window.removeEventListener('resize', prev)
  }
  col.style.minHeight = `${col.offsetHeight}px`
  const check = (): void => {
    if (!settle(col)) return
    window.removeEventListener('scroll', check)
    window.removeEventListener('resize', check)
    held.delete(col)
  }
  held.set(col, check)
  window.addEventListener('scroll', check, { passive: true })
  window.addEventListener('resize', check)
  // сразу после сворачивания: вверху страницы отпускается тут же, невидимо
  requestAnimationFrame(check)
}

interface Props {
  /** Ключ памяти: `agenda`, `free`, `desk:confirm`… */
  id: string
  className: string
  /** Классы заголовка-summary (у повестки — `ag-h`). */
  headClass?: string
  head: ReactNode
  children: ReactNode
}

export function Fold({ id, className, headClass = '', head, children }: Props) {
  const [open, setOpen] = useState(() => storedOpen(id))
  return (
    <details className={`${className} dp-fold`} open={open} data-fold={id}
      onToggle={(e) => {
        const now = e.currentTarget.open
        if (now === open) return
        setOpen(now)
        remember(id, now)
      }}>
      <summary className={headClass} onClick={(e) => { if (open) holdColumn(e.currentTarget) }}>
        {head}
        <span className="dp-fold-c" aria-hidden="true"><Icon name="chev-r" /></span>
      </summary>
      {children}
    </details>
  )
}
