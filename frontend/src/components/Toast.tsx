import { useCallback, useEffect, useRef, useState } from 'react'
import type { Tone } from '../types/api'
import { motionOk, stepMs } from '../utils/motion'
import { AppLink } from './AppLink'
import { Icon } from './Icon'

export interface ToastState {
  tone: Tone
  text: string
  /** Куда смотреть результат (22.10: запись из окна шапки — «Vezi în jurnal ›»).
   *  Переход — `AppLink`, без перезагрузки; щелчок по ссылке закрывает плашку:
   *  она живёт в оболочке и иначе приехала бы на новый экран. */
  link?: { href: string; label: string }
}

interface ToastProps extends ToastState {
  onClose: () => void
}

/**
 * Плавающий ответ на действие — та же разметка и те же классы, что у серверной
 * плашки (layout.msg_banner + panel.css .toastbox), и то же поведение из
 * panel.js: крестик; успех закрывается сам через 6 секунд, отказ и
 * предупреждение висят, пока их не закроют — их читают.
 * ⚠️ Без id="dp_toast": так зовётся серверная плашка (?msg= после 303), и
 * panel.js вешает обработчики только на неё. Две плашки с одним id спорили бы.
 */
export function Toast({ tone, text, link, onClose }: ToastProps) {
  /* Уход (07.11, вторая волна): плашка сперва гаснет (класс `out`, переход
     `.toastbox` в panel.css) и только потом просит родителя её снять. Новый
     текст на той же плашке отменяет уход — иначе пришедший следом ответ
     исчез бы вместе с прежним. Без движения — сразу, как было. */
  const [out, setOut] = useState(false)
  const going = useRef<number | null>(null)
  const [shownText, setShownText] = useState(text)
  if (shownText !== text) {
    setShownText(text)
    setOut(false)
  }
  const leave = useCallback(() => {
    if (!motionOk()) { onClose(); return }
    setOut(true)
    if (going.current !== null) window.clearTimeout(going.current)
    going.current = window.setTimeout(onClose, stepMs('--dur'))
  }, [onClose])
  useEffect(() => () => { if (going.current !== null) window.clearTimeout(going.current) }, [])
  useEffect(() => {
    if (shownText !== text) return
    if (going.current !== null) { window.clearTimeout(going.current); going.current = null }
  }, [text, shownText])
  useEffect(() => {
    if (tone !== 'ok') return
    const timer = window.setTimeout(leave, 6000)
    return () => window.clearTimeout(timer)
  }, [tone, leave, text])

  /* Тёмная плашка справа внизу (макет 08.10) — оформление в panel.css
     `.toastbox`; галочка у успеха — значком, тон говорит и цветом, и формой. */
  return (
    <div className={`toastbox${out ? ' out' : ''}`} data-kind={tone} role={tone === 'err' ? 'alert' : 'status'}
      aria-live={tone === 'err' ? undefined : 'polite'}>
      <div className={`banner ${tone}`}>
        {tone === 'ok' && <Icon name="check" />}
        {text}
        {/* плашка — flex с зазором: ссылка отдельным элементом и одной
            строкой, сжимается текст, а не «Vezi în / jurnal ›» */}
        {link
          ? <AppLink href={link.href} onClick={leave} style={{ whiteSpace: 'nowrap' }}>{link.label}</AppLink>
          : null}
        <button className="t-x" type="button" aria-label="Închide" onClick={leave}>
          <Icon name="close" />
        </button>
      </div>
    </div>
  )
}
