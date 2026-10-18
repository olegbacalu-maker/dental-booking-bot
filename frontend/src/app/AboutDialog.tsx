import { useEffect, useRef, useState } from 'react'
import { AppLink } from '../components/AppLink'
import { hideDialog, showDialog } from '../components/dialog'
import { Icon } from '../components/Icon'
import { shellNow, shellVersion, useCommand } from './bridge'

/* «Despre DentPilot» (Т7, пункт `act:about` меню «Ajutor»): окно страницы,
   только в окне оболочки Tauri — `App` ставит его, когда стоит мост.
   ⭐ Всё, что здесь написано, — ФАКТЫ модели оболочки: версия программы
   (`runtime.version`), клиника, папка данных из того же места, куда программа
   пишет (`layout.data_folder()`), срок файла лицензии — как «Valabil până la»
   на её странице. Версию оболочки называет сама оболочка (`dpShell.version`).
   Пустое поле (облако, исходники, лицензия не проверяется) не рисуется. */
const T = {
  title: 'Despre DentPilot',
  close: 'Închide',
  program: 'Versiunea programului',
  shell: 'Versiunea ferestrei',
  clinic: 'Clinica',
  data: 'Dosarul cu datele',
  license: 'Licența valabilă până la',
  site: 'Site',
} as const

export function AboutHost() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDialogElement>(null)
  useCommand('act:about', () => setOpen(true))

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  const m = open ? shellNow() : null
  const close = () => setOpen(false)
  return (
    <dialog ref={ref} className="dp-about" aria-labelledby="dp-about-t" onClose={close}>
      <div className="dlg-head">
        <span id="dp-about-t">{T.title}</span>
        <button type="button" onClick={close} aria-label={T.close}><Icon name="close" /></button>
      </div>
      {m && (
        <dl className="dp-about-dl">
          <dt>{T.program}</dt><dd>{m.runtime.version}</dd>
          <dt>{T.shell}</dt><dd>{shellVersion()}</dd>
          <dt>{T.clinic}</dt><dd>{m.clinic.name}</dd>
          {m.about.data && <><dt>{T.data}</dt><dd>{m.about.data}</dd></>}
          {m.about.license_until && <><dt>{T.license}</dt><dd>{m.about.license_until}</dd></>}
          {/* ⛔ сайт — только target=_blank: окно отдаёт такую ссылку системному
              браузеру (как уголок сайдбара), обычная увела бы само окно */}
          <dt>{T.site}</dt>
          <dd>
            <AppLink href={m.frame.site.href} target="_blank" rel="noopener">
              {m.frame.site.href.replace(/^https:\/\//, '')}
            </AppLink>
          </dd>
        </dl>
      )}
      <div className="dp-ask-btns">
        <button type="button" className="savebtn" onClick={close}>{T.close}</button>
      </div>
    </dialog>
  )
}
