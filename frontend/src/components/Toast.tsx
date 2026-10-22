import { useEffect } from 'react'
import type { Tone } from '../types/api'
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
  useEffect(() => {
    if (tone !== 'ok') return
    const timer = window.setTimeout(onClose, 6000)
    return () => window.clearTimeout(timer)
  }, [tone, onClose])

  /* Тёмная плашка справа внизу (макет 08.10) — оформление в panel.css
     `.toastbox`; галочка у успеха — значком, тон говорит и цветом, и формой. */
  return (
    <div className="toastbox" data-kind={tone} role={tone === 'err' ? 'alert' : 'status'}
      aria-live={tone === 'err' ? undefined : 'polite'}>
      <div className={`banner ${tone}`}>
        {tone === 'ok' && <Icon name="check" />}
        {text}
        {/* плашка — flex с зазором: ссылка отдельным элементом и одной
            строкой, сжимается текст, а не «Vezi în / jurnal ›» */}
        {link
          ? <AppLink href={link.href} onClick={onClose} style={{ whiteSpace: 'nowrap' }}>{link.label}</AppLink>
          : null}
        <button className="t-x" type="button" aria-label="Închide" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
    </div>
  )
}
