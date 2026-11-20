import { useEffect, useRef, useState } from 'react'
import { hideDialog, showDialog, useDialogLeave } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import type { ApiError } from '../../types/api'
import { tarifeApi, type ImAct, type ImCheck, type ImRow, type TarifeData } from './tarife'

/* Импорт прайса из Excel: файл остаётся в браузере и уходит телом каждого запроса (как у склада); сервер
   разбирает и сравнивает с прайсом, экран показывает «nou / preț schimbat / neschimbat» и только по кнопке
   запускает. Ничего не удаляется: строки, которых нет в файле, остаются как были. */

const GROUPS: [ImAct, string][] = [
  ['new', 'Noi'], ['changed', 'Schimbate'], ['same', 'Neschimbate'], ['bad', 'Cu greșeli'],
]
const WHAT: Record<ImRow['what'][number], string> = { price: 'preț', cat: 'categorie', ru: 'denumire RU', plan: 'intră în plan' }
const ERR: Record<Exclude<ImRow['err'], ''>, string> = {
  name: 'denumire goală sau prea lungă', price: 'preț prea lung', dup: 'denumirea se repetă',
}

export function ImportDialog({ onClose, onDone, onSignedOut }: {
  onClose: () => void
  onDone: (d: TarifeData, text: string) => void
  onSignedOut: (e: ApiError) => boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const { leave } = useDialogLeave(ref, onClose)
  const [file, setFile] = useState<File | null>(null)
  const [check, setCheck] = useState<ImCheck | null>(null)
  const [tab, setTab] = useState<ImAct>('new')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])

  async function verify(f: File) {
    setBusy(true)
    setErr('')
    try {
      const r = await tarifeApi.importCheck(f, f.name)
      setCheck(r.data)
      const c = r.data.counts
      setTab(c.new ? 'new' : c.changed ? 'changed' : c.bad ? 'bad' : 'same')
    } catch (e) {
      const er = asApiError(e)
      if (onSignedOut(er)) return
      setCheck(null)
      setErr(er.text || 'Fișierul nu s-a citit.')
    } finally {
      setBusy(false)
    }
  }
  function pick(f: File | undefined) {
    if (!f) return
    setFile(f)
    void verify(f)
  }
  async function run() {
    if (!file || !check) return
    setBusy(true)
    setErr('')
    try {
      const r = await tarifeApi.importRun(file, file.name, check.token)
      onDone(r.data, r.text)
      leave()
    } catch (e) {
      const er = asApiError(e)
      if (onSignedOut(er)) return
      setErr(er.text || 'Importul nu s-a făcut.')
      /* прайс поменялся после проверки — показать свежее сравнение */
      if (er.code === 'tarife_import_stale') void verify(file)
    } finally {
      setBusy(false)
    }
  }

  const c = check?.counts
  const todo = c ? c.new + c.changed : 0
  const rows = check ? check.rows.filter((r) => r.act === tab) : []

  return (
    <dialog ref={ref} className="rg-dlg wide tf-dlg tf-imp" onClose={leave} aria-label="Importă din Excel">
      <div className="dlg-head">
        <span><Icon name="upload" /> Importă prețurile din Excel</span>
        <button type="button" className="rg-x" onClick={leave} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b" aria-busy={busy || undefined}>
        <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden data-testid="tf-file"
          onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
        {!check && (
          <div className="tf-imp-pick">
            <p className="hint">Primul rând — antetul: <b>Categoria</b>, <b>Denumire</b>, <b>Preț</b>; opțional <b>Denumire RU</b>.
              Același format îl dă butonul «Exportă»: descărcați lista, o corectați în Excel și o aduceți înapoi.</p>
            <p className="hint">Întâi programul arată ce se schimbă; nimic nu se scrie până nu apăsați «Importă».
              Serviciile care lipsesc din fișier rămân cum sunt — nu se șterge nimic.</p>
            <button type="button" className="dp-btn pri" disabled={busy} onClick={() => fileRef.current?.click()}>
              <Icon name="upload" /> Alege fișierul (.xlsx sau .csv)</button>
          </div>
        )}
        {check && (
          <>
            <div className="tf-imp-file"><Icon name="file" /><span><b>{check.file.name}</b> · {check.rows.length} rânduri</span>
              <button type="button" className="rg-btn sm" disabled={busy} onClick={() => fileRef.current?.click()}><Icon name="upload" /> Alt fișier</button>
            </div>
            <div className="dp-seg tf-imp-tabs" role="group" aria-label="Ce se întâmplă">
              {GROUPS.map(([k, label]) => (
                <button key={k} type="button" className={tab === k ? 'on' : ''} aria-pressed={tab === k} onClick={() => setTab(k)}>
                  {label} <b>{check.counts[k]}</b>
                </button>
              ))}
            </div>
            {check.cats_new.length > 0 && (
              <p className="st-note"><Icon name="folder" /> Categorii noi: {check.cats_new.join(', ')}</p>
            )}
            <div className="tf-imp-scroll">
              {rows.length === 0 ? <p className="hint tf-imp-none">Niciun rând aici.</p> : (
                <table className="rg-tbl tf-imp-tbl">
                  <thead><tr><th>Rând</th><th>Categoria</th><th>Denumire</th><th className="num">Preț</th>
                    {(tab === 'changed' || tab === 'bad') && <th>{tab === 'bad' ? 'Greșeala' : 'Se schimbă'}</th>}</tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.line}>
                        <td className="num">{r.line}</td>
                        <td>{r.cat || <span className="st-mute">—</span>}</td>
                        <td>{r.ro}{r.ru && r.ru !== r.ro && <small>{r.ru}</small>}</td>
                        <td className="num">
                          {tab === 'changed' && r.what.includes('price')
                            ? <><s className="st-mute">{r.old_price || '—'}</s> <b>{r.price || '—'}</b></>
                            : r.price}
                        </td>
                        {tab === 'changed' && <td>{r.what.map((w) => WHAT[w]).join(', ')}</td>}
                        {tab === 'bad' && <td className="st-errt">{r.err ? ERR[r.err] : ''}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
        <p className="st-err" role="alert">{err}</p>
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn" onClick={leave}>Renunță</button>
        {check && (
          <button type="button" className="dp-btn pri" disabled={busy || todo === 0} onClick={() => { void run() }}>
            <Icon name="check" /> {todo === 0 ? 'Nimic de importat' : `Importă: ${c!.new} noi, ${c!.changed} schimbate`}
          </button>
        )}
      </div>
    </dialog>
  )
}
