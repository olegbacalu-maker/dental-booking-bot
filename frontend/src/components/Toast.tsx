import { useEffect } from 'react'
import type { Tone } from '../types/api'
import { Icon } from './Icon'

export interface ToastState {
  tone: Tone
  text: string
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
export function Toast({ tone, text, onClose }: ToastProps) {
  useEffect(() => {
    if (tone !== 'ok') return
    const timer = window.setTimeout(onClose, 6000)
    return () => window.clearTimeout(timer)
  }, [tone, onClose])

  return (
    <div className="toastbox" data-kind={tone} role={tone === 'err' ? 'alert' : 'status'}>
      <div className={`banner ${tone}`}>
        {text}
        <button className="t-x" type="button" aria-label="Închide" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
    </div>
  )
}
