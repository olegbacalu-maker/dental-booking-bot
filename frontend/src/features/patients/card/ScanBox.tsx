import { useState } from 'react'
import { ask } from '../../../components/confirm'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { scan, type ScanPages } from './card'

/* Сканирование в фишу (01.10): лист со сканера сервера → страница в сессии,
   превью на экране → «Încă o pagină» / «Salvează» (один PDF в Documente с
   выбранной категорией) / «Anulează». Сканер один на программу, сессия — по
   пациенту: страницы ждут на сервере, не в браузере. */
const T = {
  title: 'Scanare',
  scanning: 'Se scanează… puneți foaia în scaner',
  pages: 'pagini',
  page: 'pagină',
  more: 'Încă o pagină',
  save: 'Salvează în fișă',
  cancel: 'Anulează',
  confirmCancel: 'Renunțați la paginile scanate? Scanarea se va relua de la zero.',
  as: 'ca',
} as const

export interface ScanJob {
  category: string
  categoryLabel: string
  title: string
}

interface Props {
  a: CardActions
  job: ScanJob
  onFail: (e: unknown) => void
  onDone: () => void
}

export function ScanBox({ a, job, onFail, onDone }: Props) {
  const [pages, setPages] = useState<ScanPages | null>(null)
  const [busy, setBusy] = useState(false)
  const [started, setStarted] = useState(false)

  async function more() {
    setBusy(true)
    try {
      const r = await scan.page(a.pid)
      setPages(r.data)
    } catch (e) {
      onFail(e)
    } finally {
      setBusy(false)
    }
  }

  /* первый лист — сразу при открытии, без второго щелчка; при отрисовке, не
     эффектом (правило хуков): состояние «начали» хранится, запрос один */
  if (!started) {
    setStarted(true)
    void more()
  }

  async function save() {
    setBusy(true)
    try {
      const err = await a.act(() => scan.finish(a.pid, a.views, job.category, job.title))
      if (!err) onDone()
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (pages && pages.pages > 0 && !await ask({ text: T.confirmCancel, ok: T.cancel })) return
    try { await scan.cancel(a.pid) } catch { /* сессия и так уйдёт с перезапуском */ }
    onDone()
  }

  const n = pages?.pages ?? 0
  return (
    <div className="dp-scan" role="region" aria-label={T.title}>
      <div className="dp-scan-h">
        <Icon name="print" />
        <b>{T.title}</b>
        <span className="dp-scan-as">{T.as} «{job.categoryLabel}»</span>
        <span className="dp-scan-n">{n ? `${n} ${n === 1 ? T.page : T.pages}` : ''}</span>
      </div>
      {busy && !pages && <p className="hint dp-m0">{T.scanning}</p>}
      {pages && pages.previews.length > 0 && (
        <div className="dp-scan-pages">
          {pages.previews.map((src, i) => (
            <figure key={i}><img src={src} alt={`${T.page} ${i + 1}`} /><figcaption>{i + 1}</figcaption></figure>
          ))}
        </div>
      )}
      {busy && pages && <p className="hint dp-m0">{T.scanning}</p>}
      <div className="dp-scan-acts">
        <button type="button" className="pl-btn" disabled={busy} onClick={() => { void more() }}>
          <Icon name="plus" /> {T.more}
        </button>
        <button type="button" className="savebtn" disabled={busy || n === 0} onClick={() => { void save() }}>
          <Icon name="save" /> {T.save}
        </button>
        <button type="button" className="pl-btn" disabled={busy} onClick={() => { void cancel() }}>
          {T.cancel}
        </button>
      </div>
    </div>
  )
}
