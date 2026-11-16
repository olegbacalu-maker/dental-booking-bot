import { useCallback, useEffect, useRef } from 'react'
import { shellOn, useCommand } from '../app/bridge'
import { ask } from '../components/confirm'
import { defaultNavigate } from './useLoad'
import { defaultReload } from './useLive'

const T = {
  reload: 'Reîncărcați pagina fără să le salvați?',
  reloadOk: 'Reîncarcă',
  leave: 'Părăsește',
} as const

/**
 * Несохранённое на экране, которое умирает вместе с ДОКУМЕНТОМ: блокер роутера
 * его не видит, потому что перехода роутера нет. `what` — первая фраза вопроса
 * («… are modificări nesalvate.»), `null` — спрашивать не о чем.
 * - F5 и «Reîncarcă» в окне оболочки — команда страницы (`act:reload`): в окне
 *   оболочки F5 — эта команда, а не перезагрузка браузера; спрашивает своим окном.
 * - Без оболочки (браузер второго ПК, телефон) — `beforeunload`. В окне
 *   оболочки не ставится: её собственные переходы (прятание к часам на общем
 *   ПК) диалогом будить нельзя.
 * - Уход документом по ссылке (печатный лист) — `leaveTo(href, question)`:
 *   вопрос своим окном; согласие снимает `beforeunload`, иначе браузер
 *   спросил бы второй раз.
 * Уход роутером (вкладка, меню, другая фиша) охраняет блокер ВЛАДЕЛЬЦА — у
 * роутера он один на всех, и второй здесь молча выключил бы чужой вопрос.
 */
export function useUnsavedPage(what: string | null): (href: string, question: string) => void {
  const agreed = useRef(false)
  useCommand('act:reload', what !== null && (() => {
    void ask({ text: `${what} ${T.reload}`, ok: T.reloadOk, danger: true })
      .then((yes) => { if (yes) defaultReload() })
  }))
  const on = what !== null
  useEffect(() => {
    if (!on || shellOn()) return
    agreed.current = false
    const stay = (e: BeforeUnloadEvent) => {
      if (agreed.current) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', stay)
    return () => window.removeEventListener('beforeunload', stay)
  }, [on])
  return useCallback((href: string, question: string) => {
    if (what === null) {
      defaultNavigate(href)
      return
    }
    void ask({ text: `${what} ${question}`, ok: T.leave, danger: true }).then((yes) => {
      if (!yes) return
      agreed.current = true
      defaultNavigate(href)
    })
  }, [what])
}
