import { useCallback, useEffect, useMemo, useState } from 'react'
import { Icon } from '../../components/Icon'
import { ask } from '../../components/confirm'
import { Toast, type ToastState } from '../../components/Toast'
import { asApiError } from '../../services/api'
import type { ApiError } from '../../types/api'
import { roCount } from '../../utils/plural'
import {
  settings, type PlanTemplate, type PlanTemplatesData, type PlanTemplatesForm, type PlanTplRowForm,
} from './settings'

const T = {
  intro: 'Un șablon este un set de proceduri care se adaugă în planul pacientului dintr-o singură '
    + 'fereastră. Dintele se alege la adăugare, iar planul se modifică apoi doar la acel pacient — '
    + 'șablonul rămâne cum l-ați salvat.',
  price: 'Prețul necompletat se ia din lista de servicii în ziua în care adăugați șablonul în plan.',
  noServices: 'Lista de servicii e goală — o completează directorul în Setări › Servicii.',
  list: 'Șabloanele clinicii',
  empty: 'Încă nu aveți șabloane de plan.',
  add: 'Șablon nou',
  pick: 'Alegeți un șablon din listă sau faceți unul nou.',
  unnamed: 'Fără nume',
  rows: { one: '{n} procedură', few: '{n} proceduri', many: '{n} de proceduri' },
  noRows: 'fără proceduri',
  isNew: 'nou',
  edited: 'modificat',
  name: 'Nume',
  note: 'Notă (nu e obligatorie)',
  notePh: 'de exemplu: pentru molari',
  colProc: 'Procedură',
  colTooth: 'Dinte',
  colPrice: 'Preț, MDL',
  colOrder: 'Ordine',
  proc: 'Procedura rândului',
  pickProc: 'Alegeți procedura…',
  offList: ' — nu este în lista de servicii',
  tooth: 'Dintele rândului',
  withTooth: 'cu dinte',
  noTooth: 'fără dinte',
  rowPrice: 'Prețul rândului',
  fromList: 'din listă',
  noPrice: 'fără preț',
  inList: 'în listă:',
  up: 'Mută mai sus',
  down: 'Mută mai jos',
  delRow: 'Șterge rândul',
  addRow: 'Rând nou',
  copy: 'Copiază șablonul',
  copyOf: '(copie)',
  del: 'Șterge șablonul',
  delOk: 'Șterge',
  save: 'Salvează șabloanele',
  badName: 'Scrieți numele șablonului.',
  badRows: 'Șablonul are nevoie de cel puțin o procedură.',
  badProc: 'Alegeți procedura la fiecare rând sau ștergeți rândul gol.',
  dupName: 'Există deja un șablon cu acest nume — alegeți alt nume.',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const delAsk = (name: string) => `Ștergeți șablonul „${name}”? Planurile pacienților în care a fost deja `
  + 'adăugat nu se schimbă.'

/** значение `<select>` у строки свободным текстом (услуги с таким текстом в прайсе нет) */
const TEXT = '~text'

interface RowDraft {
  key: number
  procedure: string
  service_id: string
  tooth: boolean
  price: string
}

interface Draft {
  name: string
  note: string
  rows: RowDraft[]
}

type BadField = 'name' | 'rows' | 'proc'

let rowKey = 0
const newRow = (): RowDraft => ({ key: ++rowKey, procedure: '', service_id: '', tooth: true, price: '' })
const toDraft = (t: Pick<PlanTemplate, 'name' | 'note' | 'rows'>): Draft => ({
  name: t.name, note: t.note,
  rows: t.rows.map((r) => ({ key: ++rowKey, procedure: r.procedure, service_id: r.service_id, tooth: r.tooth,
    price: r.price === null ? '' : String(r.price) })),
})
const rowForm = (r: RowDraft): PlanTplRowForm => ({
  ...(r.service_id ? { service_id: r.service_id } : { procedure: r.procedure }),
  tooth: r.tooth, price: r.price ? Number(r.price) : null,
})
const fold = (s: string) => s.trim().replace(/\s+/g, ' ')

/** Что изменилось против сохранённого — только эти поля уйдут на запись; null — ничего. */
function changes(base: Draft, d: Draft): NonNullable<PlanTemplatesForm['templates']>[string] | null {
  const out: NonNullable<PlanTemplatesForm['templates']>[string] = {}
  if (fold(d.name) !== fold(base.name)) out.name = fold(d.name)
  if (fold(d.note) !== fold(base.note)) out.note = fold(d.note)
  const rows = d.rows.map(rowForm)
  if (JSON.stringify(rows) !== JSON.stringify(base.rows.map(rowForm))) out.rows = rows
  return Object.keys(out).length ? out : null
}

function firstBad(d: Draft): BadField | null {
  if (!fold(d.name)) return 'name'
  if (d.rows.length === 0) return 'rows'
  if (d.rows.some((r) => !r.service_id && !r.procedure)) return 'proc'
  return null
}

interface Props {
  /** данные вкладки из загрузчика экрана; null — ещё грузятся */
  data: PlanTemplatesData | null
  /** свежие данные после записи — экран подменяет ими ответ загрузчика */
  onSaved: (data: PlanTemplatesData) => void
  leaveIfSignedOut: (err: ApiError) => boolean
  /** есть несохранённая правка — экран метит вкладку */
  onDirty: (dirty: boolean) => void
}

/**
 * Вкладка «Plan de tratament»: шаблоны плана лечения клиники. Слева список,
 * справа редактор выбранного. Правка копится в состоянии вкладки и уходит одной
 * записью — только тронутые поля тронутых шаблонов и новые шаблоны; удаление
 * сохранённого шаблона — сразу, после вопроса. В шаблоне нет ничего о пациенте:
 * зуб, врача и срок выбирают при вставке в план.
 */
export function PlanTemplatesTab({ data, onSaved, leaveIfSignedOut, onDirty }: Props) {
  const [edits, setEdits] = useState<Record<string, Draft>>({})
  const [fresh, setFresh] = useState<{ id: string; draft: Draft }[]>([])
  const [sel, setSel] = useState('')
  const [bad, setBad] = useState<{ id: string; field: BadField | 'dup' } | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const saved = useMemo(() => new Map((data?.templates ?? []).map((t) => [t.id, toDraft(t)])), [data])
  const items = useMemo(() => [
    ...(data?.templates ?? []).map((t) => {
      const base = saved.get(t.id)!
      const draft = edits[t.id] ?? base
      return { id: t.id, draft, isNew: false, changed: changes(base, draft) }
    }),
    ...fresh.map((f) => ({ id: f.id, draft: f.draft, isNew: true, changed: null })),
  ], [data, saved, edits, fresh])
  const dirty = items.some((it) => it.isNew || it.changed)
  useEffect(() => { onDirty(dirty) }, [dirty, onDirty])

  const cur = items.find((it) => it.id === sel) ?? items[0] ?? null
  const full = data !== null && items.length >= data.max.templates

  const patch = (id: string, f: (d: Draft) => Draft) => {
    setBad(null)
    if (fresh.some((x) => x.id === id)) {
      setFresh((list) => list.map((x) => (x.id === id ? { ...x, draft: f(x.draft) } : x)))
    } else {
      setEdits((e) => ({ ...e, [id]: f(e[id] ?? saved.get(id)!) }))
    }
  }
  const patchRow = (id: string, key: number, f: (r: RowDraft) => RowDraft) =>
    patch(id, (d) => ({ ...d, rows: d.rows.map((r) => (r.key === key ? f(r) : r)) }))
  const move = (id: string, i: number, by: -1 | 1) => patch(id, (d) => {
    const rows = [...d.rows]
    const j = i + by
    if (j < 0 || j >= rows.length) return d
    ;[rows[i], rows[j]] = [rows[j]!, rows[i]!]
    return { ...d, rows }
  })
  const addTemplate = (draft: Draft) => {
    const id = `new-${++rowKey}`
    setFresh((list) => [...list, { id, draft }])
    setSel(id)
    setBad(null)
  }

  const fail = (err: unknown) => {
    const apiErr = asApiError(err)
    if (leaveIfSignedOut(apiErr)) return
    setToast({ tone: 'err', text: apiErr.text || T.offline })
  }

  async function save() {
    const todo = items.filter((it) => it.isNew || it.changed)
    for (const it of todo) {
      const field = firstBad(it.draft)
      const twin = items.some((o) => o.id !== it.id
        && fold(o.draft.name).toLocaleLowerCase('ro') === fold(it.draft.name).toLocaleLowerCase('ro'))
      if (field || twin) {
        setSel(it.id)
        setBad({ id: it.id, field: field ?? 'dup' })
        setToast({ tone: 'err', text: field === 'name' ? T.badName : field === 'rows' ? T.badRows
          : field === 'proc' ? T.badProc : T.dupName })
        return
      }
    }
    const form: PlanTemplatesForm = {}
    const touched = todo.filter((it) => !it.isNew)
    if (touched.length) form.templates = Object.fromEntries(touched.map((it) => [it.id, it.changed!]))
    if (fresh.length) {
      form.new = fresh.map((f) => ({ name: fold(f.draft.name), note: fold(f.draft.note), rows: f.draft.rows.map(rowForm) }))
    }
    setSaving(true)
    try {
      const r = await settings.planTemplatesSave(form)
      const i = fresh.findIndex((f) => f.id === cur?.id)
      onSaved(r.data)
      setEdits({})
      setFresh([])
      if (i >= 0 && r.data.created[i]) setSel(r.data.created[i])
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      fail(err)
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string, name: string, isNew: boolean) {
    if (!await ask({ text: delAsk(fold(name) || T.unnamed), ok: T.delOk, danger: true })) return
    setBad(null)
    if (isNew) {
      setFresh((list) => list.filter((x) => x.id !== id))
      setSel('')
      return
    }
    setSaving(true)
    try {
      const r = await settings.planTemplatesSave({ deleted: [id] })
      onSaved(r.data)
      setEdits((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k !== id)))
      setSel('')
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      fail(err)
    } finally {
      setSaving(false)
    }
  }

  const badHere = (field: BadField | 'dup') => bad !== null && bad.id === cur?.id && bad.field === field
  const listPrice = (sid: string) => data?.services.find((s) => s.id === sid)?.price ?? ''

  return (
    <>
      <p className="hint">{T.intro} {T.price}</p>
      {data && data.services.length === 0 && <p className="hint">{T.noServices}</p>}
      {data && (
        <div className="pt-wrap">
          <nav className="fcard pt-list" aria-label={T.list}>
            {items.length === 0 && <p className="hint dp-m0">{T.empty}</p>}
            {items.map((it) => (
              <button key={it.id} type="button" className={`pt-item${it.id === cur?.id ? ' on' : ''}`}
                aria-current={it.id === cur?.id ? 'true' : undefined} onClick={() => { setSel(it.id); setBad(null) }}>
                <b>{fold(it.draft.name) || T.unnamed}</b>
                <small>
                  {it.draft.rows.length ? roCount(it.draft.rows.length, T.rows) : T.noRows}
                  {it.isNew ? ` · ${T.isNew}` : it.changed ? ` · ${T.edited}` : ''}
                </small>
              </button>
            ))}
            <button type="button" className="dp-btn pt-add" disabled={saving || full}
              onClick={() => addTemplate({ name: '', note: '', rows: [newRow()] })}>
              <Icon name="plus" /> {T.add}
            </button>
          </nav>
          {cur === null ? (
            <div className="fcard pt-edit"><p className="hint dp-m0">{T.pick}</p></div>
          ) : (
            <div className="fcard pt-edit">
              <div className="pt-fields">
                <label className="pt-lab" htmlFor="pt_name">
                  {T.name}
                  <input id="pt_name" className="dp-fld" value={cur.draft.name} maxLength={data.max.name}
                    disabled={saving} aria-invalid={badHere('name') || badHere('dup') || undefined}
                    onChange={(e) => patch(cur.id, (d) => ({ ...d, name: e.target.value }))} />
                </label>
                <label className="pt-lab" htmlFor="pt_note">
                  {T.note}
                  <input id="pt_note" className="dp-fld" value={cur.draft.note} maxLength={data.max.note}
                    placeholder={T.notePh} disabled={saving}
                    onChange={(e) => patch(cur.id, (d) => ({ ...d, note: e.target.value }))} />
                </label>
              </div>
              <table className="pt-table">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">{T.colProc}</th>
                    <th scope="col">{T.colTooth}</th>
                    <th scope="col">{T.colPrice}</th>
                    <th scope="col">{T.colOrder}</th>
                    <th scope="col" aria-label={T.delRow} />
                  </tr>
                </thead>
                <tbody>
                  {cur.draft.rows.map((r, i) => {
                    const n = i + 1
                    const lp = r.service_id && !r.price ? listPrice(r.service_id) : ''
                    return (
                      <tr key={r.key}>
                        <td className="pt-n">{n}</td>
                        <td>
                          <select className="dp-fld" aria-label={`${T.proc} ${n}`} disabled={saving}
                            aria-invalid={(badHere('proc') && !r.service_id && !r.procedure) || undefined}
                            value={r.service_id || (r.procedure ? TEXT : '')}
                            onChange={(e) => {
                              const sid = e.target.value
                              if (sid && sid !== TEXT) patchRow(cur.id, r.key, (x) => ({ ...x, service_id: sid, procedure: '' }))
                            }}>
                            {!r.service_id && !r.procedure && <option value="">{T.pickProc}</option>}
                            {!r.service_id && r.procedure && <option value={TEXT}>{r.procedure}{T.offList}</option>}
                            {data.services.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                          </select>
                        </td>
                        <td>
                          <span className="dp-seg pt-seg" role="group" aria-label={`${T.tooth} ${n}`}>
                            {([[true, T.withTooth], [false, T.noTooth]] as const).map(([v, label]) => (
                              <button key={label} type="button" className={r.tooth === v ? 'on' : ''}
                                aria-pressed={r.tooth === v} disabled={saving}
                                onClick={() => patchRow(cur.id, r.key, (x) => ({ ...x, tooth: v }))}>{label}</button>
                            ))}
                          </span>
                        </td>
                        <td>
                          <input className="dp-fld pt-price" inputMode="numeric" aria-label={`${T.rowPrice} ${n}`}
                            value={r.price} placeholder={r.service_id ? T.fromList : T.noPrice} disabled={saving}
                            maxLength={String(data.max.price).length}
                            onChange={(e) => {
                              const digits = e.target.value.replace(/\D/g, '')
                              const v = digits && Number(digits) > data.max.price ? String(data.max.price) : digits
                              patchRow(cur.id, r.key, (x) => ({ ...x, price: v }))
                            }} />
                          {lp && <small className="pt-lp">{T.inList} {lp}</small>}
                        </td>
                        <td className="pt-ord">
                          <button type="button" className="pt-ib" aria-label={`${T.up}: ${n}`} title={T.up}
                            disabled={saving || i === 0} onClick={() => move(cur.id, i, -1)}><Icon name="caret-u" /></button>
                          <button type="button" className="pt-ib" aria-label={`${T.down}: ${n}`} title={T.down}
                            disabled={saving || i === cur.draft.rows.length - 1} onClick={() => move(cur.id, i, 1)}><Icon name="caret-d" /></button>
                        </td>
                        <td>
                          <button type="button" className="pt-ib" aria-label={`${T.delRow}: ${n}`} title={T.delRow}
                            disabled={saving}
                            onClick={() => patch(cur.id, (d) => ({ ...d, rows: d.rows.filter((x) => x.key !== r.key) }))}>
                            <Icon name="trash" />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {badHere('rows') && <p className="pt-err" role="alert">{T.badRows}</p>}
              <button type="button" className="dp-btn pt-row-add" disabled={saving || cur.draft.rows.length >= data.max.rows}
                onClick={() => patch(cur.id, (d) => ({ ...d, rows: [...d.rows, newRow()] }))}>
                <Icon name="plus" /> {T.addRow}
              </button>
              <div className="pt-foot">
                <button type="button" className="dp-btn" disabled={saving || full}
                  onClick={() => addTemplate({
                    name: `${fold(cur.draft.name)} ${T.copyOf}`.trim().slice(0, data.max.name),
                    note: cur.draft.note, rows: cur.draft.rows.map((r) => ({ ...r, key: ++rowKey })) })}>
                  <Icon name="clipboard" /> {T.copy}
                </button>
                <button type="button" className="dp-btn pt-del" disabled={saving}
                  onClick={() => { void remove(cur.id, cur.draft.name, cur.isNew) }}>
                  <Icon name="trash" /> {T.del}
                </button>
                <button type="button" className="dp-btn pri pt-save" disabled={saving || !dirty}
                  onClick={() => { void save() }}>
                  <Icon name="save" /> {T.save}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </>
  )
}
