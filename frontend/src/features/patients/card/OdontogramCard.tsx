import { useEffect, useRef, useState } from 'react'
import { asApiError } from '../../../services/api'
import { patientCard } from './card'

/*
 * ⚠️ ТОЧКА ИНТЕГРАЦИИ до C21. Компактная одонтограмма приходит куском
 * разметки старой страницы (GET /api/patients/{pid}/teeth — тот же
 * odontogram.card: обе дуги, оба вида, подсказка зуба, диалог зуба, мосты)
 * и вставляется как есть. У куска свои <script>: innerHTML их не исполняет,
 * поэтому каждый пересоздаётся по порядку — так оживают openTooth,
 * подсказка и переключатель вида. Форма зуба остаётся формой старого
 * маршрута: сохранение уходит POST-ом и возвращает страницу с ?msg=, как и
 * раньше. React-одонтограмма с данными вместо разметки — этап C21.
 */
const T = {
  loading: 'Se încarcă formula dentară…',
  failed: 'Formula dentară nu s-a încărcat.',
  open: 'Deschide formula detaliată',
} as const

interface Props {
  pid: number
  onFail: (e: unknown) => void
}

/** Вставить кусок сервера и исполнить его скрипты в порядке следования. */
export function mountFragment(host: HTMLElement, html: string) {
  host.innerHTML = html
  host.querySelectorAll('script').forEach((old) => {
    const s = document.createElement('script')
    s.textContent = old.textContent
    old.replaceWith(s)
  })
}

export function OdontogramCard({ pid, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  /* состояние привязано к фише: пока ответ не пришёл — «едет», без
     сброса в эффекте (правило хуков) */
  const [got, setGot] = useState<{ pid: number; status: 'ready' | 'failed' } | null>(null)
  const state = got && got.pid === pid ? got.status : 'loading'

  useEffect(() => {
    const ctl = new AbortController()
    patientCard.teeth(pid, ctl.signal).then(
      (r) => {
        if (ctl.signal.aborted || !host.current) return
        mountFragment(host.current, r.data.html)
        setGot({ pid, status: 'ready' })
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        setGot({ pid, status: 'failed' })
        onFail(asApiError(e))
      },
    )
    return () => ctl.abort()
  }, [pid, onFail])

  return (
    <>
      {state === 'loading' && <div className="fcard dp-odo-wait" aria-busy="true"><p className="hint dp-m0">{T.loading}</p></div>}
      {state === 'failed' && (
        <div className="fcard">
          <p className="hint dp-m0">{T.failed} <a href={`/admin/patient/${pid}/odontograma`}>{T.open}</a></p>
        </div>
      )}
      <div ref={host} className="dp-odo-host" />
    </>
  )
}
