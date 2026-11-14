import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { DurField, durOk, durRule } from '../schedule/DurPick'
import { ReplaceDialog, TechCardDialog } from '../stock/TechCard'
import { stockApi, type TechCards } from '../stock/stock'
import { settings, type ServiceEntry, type ServicesData } from './settings'

const T = {
  title: 'Servicii',
  cols: { ro: 'Denumire (RO)', ru: 'Denumire (RU)', price: 'Preț', dur: 'Durată',
    color: 'Culoare', docs: 'Medici', recall: 'Rechemare' },
  noRecall: '—',
  months: 'luni',
  hintR: 'Coloana «Rechemare»: după cât timp pacientul cu serviciul finalizat apare în '
    + '«Rechemări» (de sunat sau de scris). «—» = serviciul nu se urmărește.',
  auto: 'auto',
  allDocs: 'gol = toți',
  add: '+ Adaugă serviciu',
  hintA: 'Coloana «Medici»: bifați medicii care fac serviciul; niciunul bifat = toți medicii. ',
  hintB: ' = flux urgent (fără alegerea medicului, sloturi din ziua curentă).',
  save: 'Salvează serviciile',
  remove: 'Șterge rândul',
  phRo: 'Serviciu',
  phRu: 'Услуга',
  phPrice: '500 MDL',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const EMPTY: ServiceEntry = { id: '', ro: '', ru: '', price: '', duration: 60, color: '', urgent: false, docs: [], recall: 0 }

interface Props {
  navigate?: (url: string) => void
}

type ServicesModel = ServicesData & { techcards?: TechCards | null }

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS; техкарты склада — тем же загрузчиком,
 *  отказ склада экран услуг не роняет (колонки «Materiale» просто нет). */
export const loadServicesSettings: RouteLoad<ServicesModel> = async (signal) => {
  const [r, techcards] = await Promise.all([
    settings.services(signal),
    Promise.resolve().then(() => stockApi.techcards(signal)).then((x) => ('items' in x.data && 'services' in x.data ? x.data : null)).catch(() => null),
  ])
  return { ...r, data: { ...r.data, techcards } }
}

/**
 * Таблица услуг — те же колонки и то же тело запроса, что у старой страницы;
 * дубли подписей и всё прочее проверяет сервер (_val_services), а правки при
 * отказе не пропадают: они живут в состоянии экрана, не в перерисованной форме.
 */
export function ServicesSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<ServicesModel>(navigate)
  /* техкарты приходят только с загрузкой; ответ сохранения прайса их не несёт — держим прежние */
  const loadedTc = state.status === 'ready' ? state.data.techcards : undefined
  const [tc, setTc] = useState<TechCards | null>(null)
  if (loadedTc !== undefined && loadedTc !== tc) setTc(loadedTc)
  const [tcOpen, setTcOpen] = useState<{ svc: string; name: string } | null>(null)
  const [replacing, setReplacing] = useState(false)
  const cardOf = (svc: string) => tc?.services.find((x) => x.id === svc)?.lines ?? []
  const [rows, setRows] = useState<ServiceEntry[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const data: ServicesModel | null = state.status === 'ready' ? state.data : null
  const list = rows ?? data?.services ?? []
  const patch = (i: number, p: Partial<ServiceEntry>) =>
    setRows(list.map((r, k) => (k === i ? { ...r, ...p } : r)))
  const remove = (i: number) => setRows(list.filter((_, k) => k !== i))
  const add = () => setRows([...list, { ...EMPTY }])
  const toggleDoc = (i: number, dk: string) => {
    const r = list[i] as ServiceEntry
    patch(i, { docs: r.docs.includes(dk) ? r.docs.filter((x) => x !== dk) : [...r.docs, dk] })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const r = await settings.servicesSave(list)
      replace(r.data)
      setRows(r.data.services)
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      const apiErr = asApiError(err)
      if (leaveIfSignedOut(apiErr)) return
      setToast({ tone: 'err', text: apiErr.text || T.offline })
    } finally {
      setSaving(false)
    }
  }

  const rule = durRule(data ?? {})
  /* сервер откажет всему списку из-за одной длительности не по правилу */
  const badDur = list.some((r) => r.ro.trim() !== '' && !durOk(r.duration, rule))

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="tooth" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      <form onSubmit={onSubmit}>
        <table className="set set-wide">
          <thead>
            <tr>
              <th>{T.cols.ro}</th><th>{T.cols.ru}</th><th style={{ width: 150 }}>{T.cols.price}</th>
              <th style={{ width: 120 }}>{T.cols.dur}</th><th style={{ width: 100 }}>{T.cols.recall}</th>
              <th style={{ width: 100 }}>{T.cols.color}</th>
              <th style={{ width: 40 }}><Icon name="sos" /></th><th style={{ width: 140 }}>{T.cols.docs}</th>
              {tc && <th style={{ width: 70 }} title="Materiale care se scad la finalizare">Materiale</th>}<th />
            </tr>
          </thead>
          <tbody>
            {data && list.map((s, i) => (
              <tr key={s.id || `new-${i}`}>
                <td><input type="text" value={s.ro} placeholder={T.phRo} aria-label={`${T.cols.ro} ${i + 1}`}
                  maxLength={60} disabled={saving} onChange={(e) => patch(i, { ro: e.target.value })} /></td>
                <td><input type="text" value={s.ru} placeholder={T.phRu} aria-label={`${T.cols.ru} ${i + 1}`}
                  maxLength={60} disabled={saving} onChange={(e) => patch(i, { ru: e.target.value })} /></td>
                <td><input type="text" value={s.price} placeholder={T.phPrice} aria-label={`${T.cols.price} ${i + 1}`}
                  maxLength={60} disabled={saving} onChange={(e) => patch(i, { price: e.target.value })} /></td>
                <td>
                  <DurField rule={rule} value={s.duration} label={`${T.cols.dur} ${i + 1}`}
                    disabled={saving} onPick={(n) => patch(i, { duration: n })} />
                </td>
                <td>
                  {/* кадр К6: заданный срок — бирюзой; белый список — сервера */}
                  <select value={s.recall ?? 0} aria-label={`${T.cols.recall} ${i + 1}`} disabled={saving}
                    className={s.recall ? 'dp-rc-set' : ''}
                    onChange={(e) => patch(i, { recall: Number(e.target.value) })}>
                    {data.recalls.map((m) => <option key={m} value={m}>{m ? `${m} ${T.months}` : T.noRecall}</option>)}
                  </select>
                </td>
                <td>
                  <select value={s.color} aria-label={`${T.cols.color} ${i + 1}`} disabled={saving}
                    onChange={(e) => patch(i, { color: e.target.value })}>
                    <option value="">{T.auto}</option>
                    {Object.entries(data.palette).map(([k, name]) => <option key={k} value={k}>{name}</option>)}
                  </select>
                </td>
                <td style={{ textAlign: 'center' }}>
                  <input type="checkbox" checked={s.urgent} aria-label={`urgent ${i + 1}`} disabled={saving}
                    onChange={(e) => patch(i, { urgent: e.target.checked })} />
                </td>
                <td>
                  <div className="dp-svc-docs">
                    {data.doctors.map((d) => (
                      <label key={d.id}>
                        <input type="checkbox" checked={s.docs.includes(d.id)} disabled={saving}
                          onChange={() => toggleDoc(i, d.id)} />
                        {d.name}
                      </label>
                    ))}
                    {s.docs.length === 0 && <small>{T.allDocs}</small>}
                  </div>
                </td>
                {tc && (
                  <td>
                    <button type="button" className="dp-svc-mat" disabled={!s.id || saving}
                      aria-label={cardOf(s.id).length ? `${cardOf(s.id).length} materiale: ${s.ro}` : `Adaugă materiale: ${s.ro}`}
                      title={s.id ? 'Materialele care se scad la finalizarea serviciului' : 'Salvați serviciul întâi'}
                      onClick={() => setTcOpen({ svc: s.id, name: s.ro || s.id })}>
                      <Icon name="box" /> {cardOf(s.id).length || <Icon name="plus" />}
                      {cardOf(s.id).some((l) => !l.active) && <i className="st-dot" title="un material e în arhivă" />}
                    </button>
                  </td>
                )}
                <td>
                  <button type="button" className="rowdel" aria-label={`${T.remove} ${i + 1}`} disabled={saving}
                    onClick={() => remove(i)}><Icon name="close" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="addrow" onClick={add} disabled={data === null || saving}>{T.add}</button>
        <p className="hint">{T.hintA}<Icon name="sos" />{T.hintB}</p>
        <p className="hint">{T.hintR}</p>
        {tc && (
          <p className="hint dp-svc-tc">Coloana «Materiale»: ce se scade din stoc la «Finalizată» în planul pacientului.
            {tc.services.some((x) => x.lines.length) && (
              <button type="button" className="dp-link" onClick={() => setReplacing(true)}>Înlocuiește materialul în toate serviciile</button>
            )}
          </p>
        )}
        <button className="savebtn" disabled={data === null || saving || badDur}><Icon name="save" /> {T.save}</button>
      </form>
      {tc && tcOpen && <TechCardDialog key={tcOpen.svc} svc={tcOpen.svc} name={tcOpen.name} tc={tc} onClose={() => setTcOpen(null)}
        onSaved={(lines, text) => {
          const has = tc.services.some((x) => x.id === tcOpen.svc)
          const services = has ? tc.services.map((x) => (x.id === tcOpen.svc ? { ...x, lines, warn: lines.filter((l) => !l.active).length } : x))
            : [...tc.services, { id: tcOpen.svc, name: tcOpen.name, lines, warn: lines.filter((l) => !l.active).length }]
          setTc({ ...tc, services })
          setToast({ tone: 'ok', text })
        }} />}
      {tc && replacing && <ReplaceDialog tc={tc} onClose={() => setReplacing(false)} onDone={(text) => { setToast({ tone: 'ok', text }); retry() }} />}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
