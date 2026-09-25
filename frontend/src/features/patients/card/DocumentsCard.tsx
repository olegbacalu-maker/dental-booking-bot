import { useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon, iconName } from '../../../components/Icon'
import { asApiError } from '../../../services/api'
import type { CardActions } from './actions'
import { hideDialog, showDialog } from './dialog'
import { patientCard, type Doc, type PatientCard } from './card'

/* Документы: снимки и PDF открываются тут же, остальное — программой
   Windows через движок, а если тот не может (не локально, чужое
   расширение) — скачиванием, как откатывался старый скрипт. Файл отдаёт
   старый маршрут /admin/doc/{id} (обычная ссылка). */
const T = {
  title: 'Documente și imagini',
  max: 'max',
  empty: '— fără documente —',
  del: 'Șterge',
  confirmDel: 'Ștergeți documentul?',
  pick: 'Alege fișierul',
  noFile: 'niciun fișier ales',
  upload: 'Încarcă document',
  category: 'Categorie',
  hint:
    'Click pe fișier — pozele și PDF-urile se deschid aici, restul în programul potrivit (Word, Excel). Fișierele rămân local, în folderul programului (data\\files).',
  openExt: 'Deschide în alt program',
  save: 'Salvează pe disc',
  close: 'Închide',
} as const

interface Props {
  card: PatientCard
  a: CardActions
  onFail: (e: unknown) => void
  /** Скачивание — уход по адресу файла (в проверках подменяется). */
  navigate: (url: string) => void
}

export function DocumentsCard({ card, a, onFail, navigate }: Props) {
  const cats = card.options.doc_categories
  const [file, setFile] = useState<File | null>(null)
  const [category, setCategory] = useState('alt')
  const [viewing, setViewing] = useState<Doc | null>(null)
  const dlg = useRef<HTMLDialogElement>(null)
  const inputId = `docfile-${card.id}`

  async function onUpload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    const err = await a.act(() => patientCard.uploadDoc(a.pid, a.views, file, category))
    if (!err) setFile(null)
  }

  async function sysOpen(id: number) {
    try {
      const r = await patientCard.openDoc(id)
      if (!r.data.opened) navigate(`/admin/doc/${id}`)
    } catch (err) {
      const ae = asApiError(err)
      if (ae.failure.kind === 'unauthenticated') { onFail(err); return }
      navigate(`/admin/doc/${id}`)
    }
  }

  function open(d: Doc) {
    if (d.view === 'ext') { void sysOpen(d.id); return }
    setViewing(d)
    showDialog(dlg.current)
  }

  function closeViewer() {
    hideDialog(dlg.current)
    setViewing(null)
  }

  async function del(d: Doc) {
    if (!window.confirm(T.confirmDel)) return
    await a.act(() => patientCard.delDoc(a.pid, a.views, d.id))
  }

  return (
    <div className="fcard" id="docs">
      <h3>{T.title} <small>· {T.max} {card.options.max_doc_mb} MB</small></h3>
      {card.documents.length ? (
        <div className="docgrid">
          {card.documents.map((d) => (
            <div key={d.id} className="doccard">
              <AppLink href={`/admin/doc/${d.id}`} title={d.filename} onClick={(e) => { e.preventDefault(); open(d) }}>
                <div className="thumb">
                  {d.view === 'img'
                    ? <img src={`/admin/doc/${d.id}?thumb=1`} alt="" loading="lazy" />
                    : <Icon name={iconName(d.icon)} />}
                </div>
                <div className="dmeta"><b>{d.filename}</b><small>{d.when} · {d.size}</small></div>
              </AppLink>
              <div className="del">
                <form onSubmit={(e) => { e.preventDefault(); void del(d) }}>
                  <button title={T.del} aria-label={`${T.del}: ${d.filename}`} disabled={a.busy}><Icon name="close" /></button>
                </form>
              </div>
            </div>
          ))}
        </div>
      ) : <p className="hint dp-m08">{T.empty}</p>}
      <form className="fform" onSubmit={onUpload}>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label={T.category}>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <div className="filepick">
          <input type="file" id={inputId} onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={a.busy} />
          <label htmlFor={inputId}><Icon name="clip" /> {T.pick}</label>
          <span className={`fname${file ? ' on' : ''}`}>{file ? file.name : T.noFile}</span>
        </div>
        <button disabled={a.busy || !file}><Icon name="upload" /> {T.upload}</button>
      </form>
      <p className="hint dp-mt8">{T.hint}</p>
      <dialog ref={dlg} className="wide" onClose={() => setViewing(null)}>
        <div className="dlg-head">
          <span>{viewing?.filename ?? '—'}</span>
          <button type="button" onClick={closeViewer} aria-label={T.close}><Icon name="close" /></button>
        </div>
        <div className="dvbody">
          {viewing?.view === 'img' && <img src={`/admin/doc/${viewing.id}?inline=1`} alt="" />}
          {viewing?.view === 'pdf' && <iframe title={viewing.filename} src={`/admin/doc/${viewing.id}?inline=1`} />}
        </div>
        <div className="dvacts">
          {viewing && (
            <button type="button" onClick={() => { void sysOpen(viewing.id) }}><Icon name="monitor" /> {T.openExt}</button>
          )}
          {viewing && <AppLink href={`/admin/doc/${viewing.id}`}><Icon name="download" /> {T.save}</AppLink>}
        </div>
      </dialog>
    </div>
  )
}
