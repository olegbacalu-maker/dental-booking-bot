import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { roCount } from '../../utils/plural'
import { settings, type TemplatesData, type TemplatesForm, type TplFieldId } from './settings'

const T = {
  title: 'Șabloane consultație',
  intro: 'Textele șabloanelor le scrie clinica, pentru fiecare serviciu din listă. În jurnalul '
    + 'consultației, butonul «Din șablon» le pune în câmpurile goale — ce a scris medicul nu se '
    + 'schimbă. Mai multe servicii la o vizită: textele se adună pe câmpuri.',
  marks: 'În text se pot folosi:',
  tooth: 'numărul dintelui din procedura bifată în plan',
  date: 'data vizitei',
  empty: 'gol',
  filled: { one: '{n} câmp completat', few: '{n} câmpuri completate', many: '{n} de câmpuri completate' },
  edited: 'modificat',
  example: 'Exemplu',
  exampleHint: 'pune un text-exemplu în câmpurile goale — de editat',
  none: 'Lista de servicii e goală — adăugați serviciile în Setări › Servicii.',
  save: 'Salvează șabloanele',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadTemplatesSettings: RouteLoad<TemplatesData> = (signal) => settings.templates(signal)

/**
 * Шаблоны дневника визита по услуге (10.11). Правка живёт в состоянии экрана
 * ПО ГРАФАМ: на запись уходит только тронутое (`TemplatesForm`), так что
 * пересохранение без правки ничего не меняет, а вкладка, открытая рядом,
 * не затирает чужую графу. Тексты, метки и заглушка — с сервера.
 */
export function TemplatesSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<TemplatesData>(navigate)
  const [touched, setTouched] = useState<TemplatesForm>({})
  const [open, setOpen] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const data: TemplatesData | null = state.status === 'ready' ? state.data : null
  const value = (sid: string, k: TplFieldId): string =>
    touched[sid]?.[k] ?? data?.services.find((s) => s.id === sid)?.tpl[k] ?? ''
  const setField = (sid: string, k: TplFieldId, v: string) =>
    setTouched((t) => ({ ...t, [sid]: { ...t[sid], [k]: v } }))
  const toggle = (sid: string) =>
    setOpen((o) => (o.includes(sid) ? o.filter((x) => x !== sid) : [...o, sid]))
  const fillExample = (sid: string) => {
    if (!data) return
    for (const f of data.fields) {
      const ex = data.example[f.id]
      if (ex && !value(sid, f.id).trim()) setField(sid, f.id, ex)
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const r = await settings.templatesSave(touched)
      replace(r.data)
      setTouched({})
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      const apiErr = asApiError(err)
      if (leaveIfSignedOut(apiErr)) return
      setToast({ tone: 'err', text: apiErr.text || T.offline })
    } finally {
      setSaving(false)
    }
  }

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="note" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }
  const dirty = Object.keys(touched).length > 0

  return (
    <section className="dp-react-root dp-tpls" aria-busy={data === null}>
      {head}
      <p className="hint">{T.intro}</p>
      {data && (
        <p className="hint">
          {T.marks} <b className="tpl-mark">{data.marks.tooth}</b> — {T.tooth}; <b className="tpl-mark">{data.marks.date}</b> — {T.date}.
        </p>
      )}
      {data && data.services.length === 0 && <p className="hint">{T.none}</p>}
      <form onSubmit={onSubmit}>
        <div className="tpl-list">
          {data?.services.map((s) => {
            const isOpen = open.includes(s.id)
            const n = data.fields.filter((f) => value(s.id, f.id).trim()).length
            const allEmpty = n === 0
            return (
              <div key={s.id} className="fcard tpl-card">
                <button type="button" className="tpl-head" aria-expanded={isOpen}
                  aria-controls={`tpl_${s.id}`} onClick={() => toggle(s.id)}>
                  <Icon name={isOpen ? 'caret-u' : 'caret-d'} />
                  <b>{s.label}</b>
                  <small className={n ? 'tpl-n on' : 'tpl-n'}>
                    {n ? roCount(n, T.filled) : T.empty}{touched[s.id] ? ` · ${T.edited}` : ''}
                  </small>
                </button>
                {isOpen && (
                  <div id={`tpl_${s.id}`}>
                    <div className="fform">
                      {data.fields.map((f) => (
                        <label key={f.id} className="dlab" htmlFor={`tpl_${s.id}_${f.id}`}>
                          {f.label}
                          <textarea id={`tpl_${s.id}_${f.id}`} rows={f.rows} maxLength={data.max}
                            value={value(s.id, f.id)} disabled={saving}
                            onChange={(e) => setField(s.id, f.id, e.target.value)} />
                        </label>
                      ))}
                    </div>
                    {allEmpty && (
                      <div className="tplrow">
                        <button type="button" disabled={saving} onClick={() => fillExample(s.id)}>{T.example}</button>
                        <small className="hint dp-m0">{T.exampleHint}</small>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <button className="savebtn" disabled={data === null || saving || !dirty}><Icon name="save" /> {T.save}</button>
      </form>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
