import type { ReactNode } from 'react'
import { Icon } from './Icon'

/** Пункт меню раздела: ключ, подпись, значок, счётчик и его тон (`bad` — красный). */
export interface SideItem<K extends string> {
  key: K
  label: string
  icon: Parameters<typeof Icon>[0]['name']
  count?: number | undefined
  tone?: '' | 'bad' | 'warn' | undefined
}

/**
 * Раздел с меню слева и содержимым справа — раскладка «Stoc» (вариант B склада) и «Laborator».
 * Уже 1100 px меню ложится строкой над содержимым, на телефоне — одной полосой со своей прокруткой:
 * страница вбок не едет.
 */
export function SideMenu<K extends string>({ label, items, value, onPick, children }: {
  label: string
  items: SideItem<K>[]
  value: K
  onPick: (k: K) => void
  children: ReactNode
}) {
  return (
    <div className="dp-split">
      <nav className="fcard dp-rail" aria-label={label}>
        {items.map((it) => (
          <button key={it.key} type="button" className={`dp-ri${value === it.key ? ' on' : ''}`}
            aria-current={value === it.key ? 'page' : undefined} onClick={() => onPick(it.key)}>
            <Icon name={it.icon} /><span>{it.label}</span>
            {it.count != null && <span className={`rg-n${it.tone && it.count ? ` ${it.tone}` : ''}`}>{it.count}</span>}
          </button>
        ))}
      </nav>
      <div className="dp-split-main">{children}</div>
    </div>
  )
}
