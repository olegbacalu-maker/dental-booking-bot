import { createContext, useContext } from 'react'
import type { ShellModel } from '../layouts/shell'

/**
 * Замок журнала (B4.4, смена человека без перезагрузки).
 *
 * «Ieșire din cont» в шапке не уводит документом на страницу входа: кука уже
 * снята сервером, и корень клиента (`App`) показывает экран PIN ВМЕСТО
 * журнала — дерево роутера размонтировано целиком, данных прошлого человека
 * в окне нет, живой канал не опрашивает. После верного PIN документ панели
 * перечитывается, и журнал нового человека встаёт одним кадром.
 *
 * Контекст, а не проп: шапку рисует `AppShell` глубоко внутри дерева
 * роутера, а замок держит `App` снаружи него. Вне провайдера (кусок оболочки
 * в проверке) — `null`, и кнопка остаётся ссылкой на `/admin/logout`.
 */
export type Lock = (m: ShellModel) => void

export const LockContext = createContext<Lock | null>(null)

export function useLock(): Lock | null {
  return useContext(LockContext)
}
