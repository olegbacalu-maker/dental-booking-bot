import type { KeyboardEvent, ReactNode, Ref } from 'react'
import { Icon } from './Icon'

/** Пункт меню раздела: ключ, подпись, значок, счётчик и его тон (`bad` — красный). */
export interface SideItem<K extends string> {
  key: K
  label: string
  icon: Parameters<typeof Icon>[0]['name']
  count?: number | undefined
  tone?: '' | 'bad' | 'warn' | undefined
  /** Строка под подписью: то, что одно число не говорит («900 MDL de achitat»). */
  hint?: string | undefined
  /** Точка вместо числа: несохранённое в этом разделе. */
  dot?: boolean | undefined
  /** Черта перед пунктом: группы меню (клиника | бумаги). */
  sep?: boolean | undefined
  /** Подсказка при наведении вместо подписи (что именно не сохранено). */
  note?: string | undefined
}

/** Меню как полоса вкладок (фиша): пункты — `role=tab`, содержимое — один `tabpanel`. */
export interface SideTabs<K extends string> {
  id: (k: K) => string
  controls: string
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
}

/**
 * Раздел с меню слева и содержимым справа — раскладка «Stoc» (вариант B склада), «Laborator» и фиша пациента.
 * Уже 1100 px меню ложится строкой над содержимым, на телефоне — одной полосой со своей прокруткой:
 * страница вбок не едет. `narrow` — меню одними значками (фиша на одонтограмме: рабочему столу нужна ширина).
 */
export function SideMenu<K extends string>({ label, items, value, onPick, children, tabs, narrow, rootRef }: {
  label: string
  items: SideItem<K>[]
  value: K
  onPick: (k: K) => void
  children: ReactNode
  tabs?: SideTabs<K> | undefined
  narrow?: boolean | undefined
  rootRef?: Ref<HTMLDivElement> | undefined
}) {
  return (
    <div ref={rootRef} className={`dp-split${narrow ? ' narrow' : ''}`}>
      <nav className="fcard dp-rail" aria-label={label}
        {...(tabs ? { role: 'tablist', 'aria-orientation': 'vertical' as const, onKeyDown: tabs.onKeyDown } : {})}>
        {items.map((it) => {
          const on = value === it.key
          /* у вкладки имя — только подпись: число и подсказка видны глазу, читалке и проверкам — нет */
          const role = tabs
            ? { role: 'tab', id: tabs.id(it.key), 'aria-selected': on, 'aria-controls': tabs.controls,
                'aria-label': it.label, tabIndex: on ? 0 : -1 }
            : { 'aria-current': on ? ('page' as const) : undefined }
          return [
            it.sep ? <span key={`${it.key}-sep`} className="dp-ri-sep" role="presentation" /> : null,
            <button key={it.key} type="button" className={`dp-ri${on ? ' on' : ''}`} title={it.note ?? it.label}
              {...role} onClick={() => onPick(it.key)}>
              <Icon name={it.icon} />
              <span className="dp-ri-l">
                {it.label}
                {it.hint && <small aria-hidden="true">{it.hint}</small>}
              </span>
              {it.dot
                ? <i className="rg-n dot" aria-hidden="true" />
                : it.count != null && <span className={`rg-n${it.tone && it.count ? ` ${it.tone}` : ''}`} aria-hidden={tabs ? true : undefined}>{it.count}</span>}
            </button>,
          ]
        })}
      </nav>
      <div className="dp-split-main">{children}</div>
    </div>
  )
}
