import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../../components/AppLink'
import { ask } from '../../../components/confirm'
import { Icon, iconName } from '../../../components/Icon'
import { asApiError } from '../../../services/api'
import type { CardActions } from './actions'
import { hideDialog, showDialog } from './dialog'
import { patientCard, scan, type Doc, type Form, type PatientCard, type ScanStatus } from './card'
import { printHref } from './print'
import { ScanBox, type ScanJob } from './ScanBox'
import { SignDialog } from './sign/SignDialog'
import { useLingering } from '../../../utils/motion'

/* Документы: снимки и PDF открываются тут же, остальное — программой
   Windows через движок, а если тот не может (не локально, чужое
   расширение) — скачиванием, как откатывался старый скрипт. Файл отдаёт
   старый маршрут /admin/doc/{id} (обычная ссылка).
   ⭐ С 01.10 вкладка — ЦЕНТР всех бумаг (слово Олега): сверху бланки
   программы со статусом «tipărit → semnat ✓», ниже загруженные файлы.
   «Semnat» = загруженный скан своей категории; галочки без бумаги нет.
   С 09.11 — и подпись на экране («Semnează», `sign/SignDialog`): её итог —
   тот же документ (PDF) той же категории, статус считается так же. */
const T = {
  title: 'Documente și imagini',
  forms: 'Formulare',
  formsHint: 'tipărește, dă la semnat, încarcă exemplarul semnat',
  max: 'max',
  empty: '— fără documente —',
  del: 'Șterge',
  confirmDel: 'Ștergeți documentul „{name}"? Fișierul se șterge de pe disc.',
  pick: 'Alege fișierul',
  noFile: 'niciun fișier ales',
  upload: 'Încarcă document',
  category: 'Categorie',
  hint:
    'Click pe fișier — pozele și PDF-urile se deschid aici, restul în programul potrivit (Word, Excel). Fișierele rămân local, pe acest calculator.',
  openExt: 'Deschide în alt program',
  save: 'Salvează pe disc',
  close: 'Închide',
  scan: 'Scanează',
  scanSigned: 'Scanează semnat',
  scanner: 'Scaner:',
  noScanner: 'niciun scaner găsit pe acest calculator',
  print: 'Tipărește',
  reprint: 'Tipărește din nou',
  uploadSigned: 'Încarcă semnat',
  sign: 'Semnează',
  printed: 'tipărit',
  notPrinted: 'netipărit',
  signed: 'semnat',
  notSigned: 'nesemnat',
  filled: 'completat în program',
  notFilled: 'necompletat',
  stale: 'plan modificat după semnare',
  covers: 'proceduri',
  mdl: 'MDL',
} as const

export interface DocsPick {
  category: string
  /** метка просьбы: та же категория дважды — тоже просьба */
  k: number
}

interface Props {
  card: PatientCard
  a: CardActions
  onFail: (e: unknown) => void
  /** Скачивание — уход по адресу файла (в проверках подменяется). */
  navigate: (url: string) => void
  /** Просьба с другой вкладки («Încarcă exemplarul semnat» в плане): категория выбрана, поле файла в фокусе. */
  pick?: DocsPick | null
}

const mdl = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

export function DocumentsCard({ card, a, onFail, navigate, pick = null }: Props) {
  const cats = card.options.doc_categories
  const [file, setFile] = useState<File | null>(null)
  const [category, setCategory] = useState('alt')
  const [viewing, setViewing] = useState<Doc | null>(null)
  /* окно гаснет за ступень (07.11): снимок и подпись стоят до конца */
  const { shown: viewed } = useLingering(viewing)
  const dlg = useRef<HTMLDialogElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const inputId = `docfile-${card.id}`
  /* просьба с другой вкладки применяется ПРИ ОТРИСОВКЕ (категория), без
     эффекта — так велит правило хуков; эффект ниже только двигает фокус */
  const [seen, setSeen] = useState<DocsPick | null>(null)
  if (pick !== seen) {
    setSeen(pick)
    if (pick) setCategory(pick.category)
  }
  useEffect(() => {
    if (!pick) return
    const el = fileRef.current
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'center' })
    el?.focus()
  }, [pick])
  /* сканер есть? — спрашиваем при показе вкладки; «Scanează» без сканера не
     рисуется, а подпись говорит, что его нет (01.10) */
  const [scanner, setScanner] = useState<ScanStatus | null>(null)
  const [job, setJob] = useState<ScanJob | null>(null)
  /* окно подписи на экране (09.11): бланк, который подписывают */
  const [signing, setSigning] = useState<Form | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    scan.status(ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setScanner(r.data) },
      () => { if (!ctl.signal.aborted) setScanner({ ok: false, name: '' }) },
    )
    return () => ctl.abort()
  }, [])
  const label = (cat: string) => cats.find((c) => c.id === cat)?.label ?? cat

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
    if (!await ask({ text: T.confirmDel.replace('{name}', d.filename), danger: true })) return
    await a.act(() => patientCard.delDoc(a.pid, a.views, d.id))
  }

  function wantSigned(cat: string) {
    setCategory(cat)
    fileRef.current?.focus()
  }

  /* статус бланка словами: что напечатано, что введено, что подписано */
  function status(f: Form) {
    const chips: { tone: string; text: string; doc?: number }[] = []
    if (f.key === 'chestionar') {
      chips.push(f.filled ? { tone: 'green', text: `${T.filled} ${f.filled}` } : { tone: 'red', text: T.notFilled })
    }
    chips.push(f.printed ? { tone: 'grey', text: `${T.printed} ${f.printed}` } : { tone: 'grey', text: T.notPrinted })
    if (f.key !== 'fisa043') {
      chips.push(f.signed
        ? { tone: 'green', text: `${T.signed} ${f.signed.when}`, doc: f.signed.doc_id }
        : { tone: 'orange', text: T.notSigned })
    }
    if (f.key === 'acord_plan' && f.stale) chips.push({ tone: 'orange', text: T.stale })
    return chips
  }

  return (
    <div className="fcard" id="docs">
      <h3>{T.forms} <small>· {T.formsHint}</small></h3>
      <div className="dp-forms">
        {card.forms.map((f) => (
          <div key={f.key} className="dp-form" data-form={f.key}>
            <span className="ico"><Icon name={f.key === 'fisa043' ? 'print' : f.key === 'chestionar' ? 'note' : 'clipboard'} /></span>
            <div className="ttl">
              <b>{f.title}</b>
              <span className="st">
                {f.key === 'acord_plan' && f.n_active !== undefined && (
                  <span className="pill sm grey">{f.n_active} {T.covers} · {mdl(f.total ?? 0)} {T.mdl}</span>
                )}
                {status(f).map((c, i) => c.doc !== undefined ? (
                  <button key={i} type="button" className={`pill sm ${c.tone} lnk`}
                    onClick={() => { const d = card.documents.find((x) => x.id === c.doc); if (d) open(d) }}>
                    <Icon name="check" /> {c.text}
                  </button>
                ) : <span key={i} className={`pill sm ${c.tone}`}>{c.text}</span>)}
              </span>
            </div>
            <span className="acts">
              <AppLink className="pl-btn" href={printHref(card.id, f.sheet, a.back)}>
                <Icon name="print" /> {f.printed ? T.reprint : T.print}
              </AppLink>
              {f.sign && (
                <button type="button" className="pl-btn primary" onClick={() => setSigning(f)}>
                  <Icon name="pen" /> {T.sign}
                </button>
              )}
              {f.key !== 'fisa043' && scanner?.ok && (
                <button type="button" className="pl-btn" disabled={job !== null}
                  onClick={() => setJob({ category: f.category, categoryLabel: label(f.category), title: f.title })}>
                  <Icon name="print" /> {T.scanSigned}
                </button>
              )}
              {f.key !== 'fisa043' && (
                <button type="button" className="pl-btn" onClick={() => wantSigned(f.category)}>
                  <Icon name="upload" /> {T.uploadSigned}
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
      {signing && <SignDialog card={card} form={signing} a={a} onClose={() => setSigning(null)} />}
      {job && <ScanBox a={a} job={job} onFail={onFail} onDone={() => setJob(null)} />}
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
                <div className="dmeta">
                  <b>{d.filename}</b>
                  <small>{d.when} · {d.size}</small>
                  {d.category_label && <small className="dcat">{d.category_label}</small>}
                </div>
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
          <input ref={fileRef} type="file" id={inputId} onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={a.busy} />
          <label htmlFor={inputId}><Icon name="clip" /> {T.pick}</label>
          <span className={`fname${file ? ' on' : ''}`}>{file ? file.name : T.noFile}</span>
        </div>
        <button disabled={a.busy || !file}><Icon name="upload" /> {T.upload}</button>
        {scanner?.ok && (
          <button type="button" className="pl-btn" disabled={a.busy || job !== null}
            onClick={() => setJob({ category, categoryLabel: label(category), title: label(category).split(' — ')[0] ?? category })}>
            <Icon name="print" /> {T.scan}
          </button>
        )}
      </form>
      <p className="hint dp-mt8">
        {T.hint}
        {scanner && <> {T.scanner} {scanner.ok ? scanner.name : T.noScanner}.</>}
      </p>
      <dialog ref={dlg} className="wide" onClose={() => setViewing(null)}>
        <div className="dlg-head">
          <span>{viewed?.filename ?? '—'}</span>
          <button type="button" onClick={closeViewer} aria-label={T.close}><Icon name="close" /></button>
        </div>
        <div className="dvbody">
          {viewed?.view === 'img' && <img src={`/admin/doc/${viewed.id}?inline=1`} alt="" />}
          {viewed?.view === 'pdf' && <iframe title={viewed.filename} src={`/admin/doc/${viewed.id}?inline=1`} />}
        </div>
        <div className="dvacts">
          {viewed && (
            <button type="button" onClick={() => { void sysOpen(viewed.id) }}><Icon name="monitor" /> {T.openExt}</button>
          )}
          {viewed && <AppLink href={`/admin/doc/${viewed.id}`}><Icon name="download" /> {T.save}</AppLink>}
        </div>
      </dialog>
    </div>
  )
}
