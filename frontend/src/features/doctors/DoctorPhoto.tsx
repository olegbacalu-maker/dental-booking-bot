import { useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import type { ApiResult } from '../../services/api'
import { doctors } from './doctors'

const T = {
  pick: 'Alege fotografia',
  noFile: 'niciun fișier ales',
  upload: 'Încarcă fotografia',
  local: 'Rămâne local, în folderul programului; pacienții nu o văd.',
  remove: 'Șterge fotografia',
  confirm: 'Ștergeți fotografia?',
} as const

interface Props {
  dk: string
  photo: string
  maxMb: number
  onDone: (photo: string, r: ApiResult<unknown>) => void
  onFail: (e: unknown) => void
}

/** Фото врача: выбор файла, загрузка multipart, удаление с подтверждением.
 *  Тип и размер проверяет сервер по содержимому (_store_photo). */
export function DoctorPhoto({ dk, photo, maxMb, onDone, onFail }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const inputId = `docphoto-${dk}`

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    try {
      const r = await doctors.uploadPhoto(dk, file)
      setFile(null)
      onDone(r.data.photo, r)
    } catch (err) {
      onFail(err)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!window.confirm(T.confirm)) return
    setBusy(true)
    try {
      const r = await doctors.deletePhoto(dk)
      onDone(r.data.photo, r)
    } catch (err) {
      onFail(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <form className="fform" onSubmit={upload} style={{ marginTop: 10 }}>
        <div className="filepick">
          <input
            type="file"
            id={inputId}
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
          <label htmlFor={inputId}><Icon name="clip" /> {T.pick}</label>
          <span className="fname">{file ? file.name : T.noFile}</span>
        </div>
        <button disabled={busy || !file}><Icon name="camera" /> {T.upload}</button>
      </form>
      <p className="hint" style={{ margin: '6px 0 0' }}>
        JPEG / PNG / WebP, max {maxMb} MB. {T.local}
      </p>
      {photo && (
        <button type="button" className="rowdel dp-photo-del" onClick={remove} disabled={busy}>
          <Icon name="trash" /> {T.remove}
        </button>
      )}
    </>
  )
}
