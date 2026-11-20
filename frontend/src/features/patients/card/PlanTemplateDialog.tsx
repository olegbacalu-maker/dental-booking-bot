import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../../components/AppLink'
import { ask } from '../../../components/confirm'
import { Icon } from '../../../components/Icon'
import { roCount } from '../../../utils/plural'
import type { ApiError } from '../../../types/api'
import { patientCard, type PlanFromTpl, type PlanTplCatalog, type PlanTplRow } from './card'
import { showDialog, useDialogLeave } from './dialog'
import { PriceNote, type ServiceOption } from './planService'

/* «Adaugă din șablon»: набор процедур клиники встаёт в план пациента одним
   действием. Слева шаблоны с поиском, справа — что именно уйдёт в план: зуб на
   весь шаблон (у строки можно свой; строка «без зуба» зуба не получает), врач
   (медик курант, можно сменить), строки с галочкой и ценой. Цена строки — своя
   цена шаблона, иначе цена прайса, когда она в прайсе одним числом; из диапазона
   цену выбирает человек (`planService`). Шаблон от этих правок не меняется.
   Что вставить и какие ключи поставить, решает сервер; окно шлёт номера строк и
   то, что человек видел в полях. Отказ показывается в окне: модальное окно
   лежит поверх плашки экрана.
   Окно одно на два места — план фиши и окно «Adaugă în plan» с зуба одонтограммы,
   поэтому о фише оно не знает: справочники и запись ему даёт владелец. */
const T = {
  title: 'Adaugă din șablon',
  close: 'Închide',
  search: 'Caută șablon…',
  list: 'Șabloanele clinicii',
  loading: 'Se încarcă șabloanele…',
  failed: 'Nu am putut încărca șabloanele.',
  retry: 'Reîncearcă',
  none: 'Clinica nu are încă șabloane de plan.',
  noneCan: 'Faceți primul șablon în Setări › Șabloane',
  noneWho: 'Șabloanele le fac directorul și recepția, în Setări › Șabloane.',
  noMatch: 'Niciun șablon cu acest nume.',
  manage: 'Modifică șabloanele',
  rows: { one: '{n} procedură', few: '{n} proceduri', many: '{n} de proceduri' },
  tooth: 'Dinte (pentru tot șablonul)',
  noTooth: '— fără dinte —',
  milk: 'Dinți de lapte',
  doctor: 'Medic',
  noDoctor: '— fără medic —',
  primary: 'medicul curant',
  colProc: 'Procedură',
  colTooth: 'Dinte',
  colPrice: 'Preț, MDL',
  rowTooth: 'Dintele procedurii',
  rowPrice: 'Prețul procedurii',
  fromTpl: 'prețul din șablon',
  off: 'nu se adaugă',
  missing: {
    one: 'Dinte neales: 1 procedură intră în plan fără dinte.',
    few: 'Dinte neales: {n} proceduri intră în plan fără dinte.',
    many: 'Dinte neales: {n} de proceduri intră în plan fără dinte.',
  },
  say: 'Șablonul nu se schimbă — modificările rămân doar în planul acestui pacient.',
  cancel: 'Renunță',
  go: { one: 'Adaugă 1 procedură în plan', few: 'Adaugă {n} proceduri în plan', many: 'Adaugă {n} de proceduri în plan' },
  goNone: 'Adaugă în plan',
  askLeave: 'Renunțați la șablon? Procedurile nu se adaugă în plan.',
  askOk: 'Renunță',
  askKeep: 'Continuă',
} as const

const SETTINGS = '/admin/settings/templates?tab=plan'

interface Props {
  pid: number
  /** Прайс с ценами — тот же, что у формы плана. */
  services: ServiceOption[]
  teeth: number[]
  milk: number[]
  doctors: string[]
  /** Медик курант пациента — окно подписывает им врача по умолчанию. */
  primary: string
  /** Вошедший правит шаблоны: ему окно показывает ссылку на «Setări › Șabloane». */
  canTemplate: boolean
  /** Зуб, с которого окно открыли (одонтограмма); из плана фиши — пусто. */
  tooth?: string
  busy: boolean
  /** Запись набора: null — удача, иначе отказ сервера (окно покажет его словами). */
  submit: (body: PlanFromTpl) => Promise<ApiError | null>
  /** В окне правили строку — владелец спросит перед уходом с экрана. */
  onTouched?: (on: boolean) => void
  onClose: () => void
}

/** Что человек изменил у строки против того, что предлагает шаблон. */
interface RowEdit { off?: boolean; tooth?: string; price?: string }

const fold = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('ro').trim()

/** Цена, с которой строка открывается: своя цена шаблона, иначе сумма прайса, если она одна. */
function startPrice(services: ServiceOption[], r: PlanTplRow): string {
  if (r.price !== null) return String(r.price)
  const listed = r.service_id ? services.find((s) => s.id === r.service_id)?.price : null
  return listed != null ? String(listed) : ''
}

export function PlanTemplateDialog({
  pid, services, teeth: teethList, milk, doctors, primary, canTemplate, tooth: preset = '', busy, submit, onTouched, onClose,
}: Props) {
  const dlg = useRef<HTMLDialogElement>(null)
  const [cat, setCat] = useState<PlanTplCatalog | null>(null)
  const [loadErr, setLoadErr] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [q, setQ] = useState('')
  const [pick, setPick] = useState('')
  const [tooth, setTooth] = useState(preset)
  /* null — врача не трогали: стоит тот, кого назвал сервер (медик курант) */
  const [doctorPick, setDoctorPick] = useState<string | null>(null)
  const [edit, setEdit] = useState<{ tid: string; rows: Record<number, RowEdit> }>({ tid: '', rows: {} })
  const [err, setErr] = useState('')
  const { leave: close, leaving } = useDialogLeave(dlg, onClose)

  useEffect(() => { showDialog(dlg.current) }, [])
  useEffect(() => {
    const ctl = new AbortController()
    patientCard.planTemplates(pid, ctl.signal).then(
      (r) => {
        if (ctl.signal.aborted) return
        setCat(r.data)
        setLoadErr(false)
      },
      () => { if (!ctl.signal.aborted) setLoadErr(true) },
    )
    return () => ctl.abort()
  }, [pid, attempt])

  const all = cat?.templates ?? []
  const shown = all.filter((t) => fold(t.name).includes(fold(q)))
  const cur = shown.find((t) => t.id === pick) ?? shown[0] ?? null
  /* правки строк принадлежат шаблону, у которого сделаны: другой шаблон открывается как записан */
  const rows = cur && edit.tid === cur.id ? edit.rows : {}
  const doctor = doctorPick ?? cat?.doctor ?? ''
  const view = (cur?.rows ?? []).map((r, i) => {
    const e = rows[i] ?? {}
    return { i, r, on: !e.off, tooth: r.tooth ? (e.tooth ?? tooth) : '', price: e.price ?? startPrice(services, r) }
  })
  const picked = view.filter((v) => v.on)
  const missing = picked.filter((v) => v.r.tooth && !v.tooth).length
  /* закрытое окно доигрывает переход: несохранённого в нём уже нет */
  const touched = Object.keys(rows).length > 0 && !leaving
  useEffect(() => { onTouched?.(touched) }, [onTouched, touched])
  useEffect(() => () => onTouched?.(false), [onTouched])

  const patch = (i: number, p: RowEdit) => {
    if (!cur) return
    setErr('')
    setEdit({ tid: cur.id, rows: { ...rows, [i]: { ...rows[i], ...p } } })
  }

  async function leave() {
    if (touched && !await ask({ text: T.askLeave, ok: T.askOk, cancel: T.askKeep })) return
    close()
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!cur || picked.length === 0) return
    setErr('')
    const failed = await submit({
      template_id: cur.id, tooth, doctor,
      rows: picked.map((v) => ({ i: v.i, procedure: v.r.procedure, ...(v.r.tooth ? { tooth: v.tooth } : {}), price: v.price })),
    })
    if (failed) {
      setErr(failed.text)
      /* шаблон переписали или удалили, пока окно стояло открытым: строки на экране уже не его */
      const f = failed.failure
      if (f.kind === 'conflict' || (f.kind === 'server' && f.status === 404)) {
        setEdit({ tid: '', rows: {} })
        setAttempt((n) => n + 1)
      }
      return
    }
    close()
  }

  const teeth = (
    <>
      <option value="">{T.noTooth}</option>
      {teethList.map((n) => <option key={n} value={n}>{n}</option>)}
      <optgroup label={T.milk}>
        {milk.map((n) => <option key={n} value={n}>{n}</option>)}
      </optgroup>
    </>
  )

  return (
    <dialog ref={dlg} className="dp-plan-tpl" aria-label={T.title}
      onCancel={(e) => { e.preventDefault(); void leave() }}>
      {/* высоту держит обёртка: окно одного размера при загрузке, с любым шаблоном и с любой строкой подвала */}
      <div className="tp-win">
      <div className="dlg-head">
        <span><Icon name="clipboard" /> {T.title}</span>
        <button type="button" onClick={() => { void leave() }} aria-label={T.close}><Icon name="close" /></button>
      </div>
      {cat === null ? (
        <div className="tp-wait" aria-busy={!loadErr}>
          {loadErr
            ? <><p className="tp-err" role="alert"><Icon name="excl" /> {T.failed}</p>
                <button type="button" className="dp-btn" onClick={() => { setLoadErr(false); setAttempt((n) => n + 1) }}>{T.retry}</button></>
            : <p className="hint dp-m0">{T.loading}</p>}
        </div>
      ) : all.length === 0 ? (
        <div className="tp-wait">
          <p className="hint dp-m0">{T.none}</p>
          {canTemplate
            ? <AppLink className="dp-btn" href={SETTINGS}>{T.noneCan}</AppLink>
            : <p className="hint dp-m0">{T.noneWho}</p>}
        </div>
      ) : (
        <form onSubmit={onSubmit}>
          <div className="tp-body">
            <nav className="tp-list" aria-label={T.list}>
              {/* Enter в поиске — не «добавить в план»: поле стоит внутри формы окна */}
              <input className="dp-fld" type="search" value={q} onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') e.preventDefault() }}
                placeholder={T.search} aria-label={T.search} />
              {shown.length === 0 && <p className="hint dp-m0">{T.noMatch}</p>}
              {shown.map((t) => (
                <button key={t.id} type="button" className={`tp-item${t.id === cur?.id ? ' on' : ''}`}
                  aria-current={t.id === cur?.id ? 'true' : undefined} onClick={() => { setPick(t.id); setErr('') }}>
                  <b>{t.name}</b>
                  <small>{roCount(t.rows.length, T.rows)}{t.note ? ` · ${t.note}` : ''}</small>
                </button>
              ))}
              {canTemplate && <AppLink className="tp-manage" href={SETTINGS}>{T.manage}</AppLink>}
            </nav>
            <div className="tp-main">
              <div className="tp-fields">
                <label className="tp-lab">{T.tooth}
                  <select className="dp-fld" value={tooth} onChange={(e) => { setTooth(e.target.value); setErr('') }}>{teeth}</select>
                </label>
                <label className="tp-lab">
                  <span>{T.doctor}{doctor && doctor === primary && <small> · {T.primary}</small>}</span>
                  <select className="dp-fld" value={doctor} onChange={(e) => setDoctorPick(e.target.value)}>
                    <option value="">{T.noDoctor}</option>
                    {doctor && !doctors.includes(doctor) && <option value={doctor}>{doctor}</option>}
                    {doctors.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
              </div>
              {cur && (
                <table className="tp-table">
                  <thead>
                    <tr><th scope="col">{T.colProc}</th><th scope="col">{T.colTooth}</th><th scope="col">{T.colPrice}</th></tr>
                  </thead>
                  <tbody>
                    {view.map((v) => (
                      <tr key={`${cur.id}:${v.i}`} className={v.on ? '' : 'off'}>
                        <td>
                          <label className="tp-proc">
                            <input type="checkbox" checked={v.on} onChange={(e) => patch(v.i, { off: !e.target.checked })} />
                            <span>{v.r.procedure}</span>
                          </label>
                        </td>
                        <td>
                          {v.r.tooth
                            ? <select className="dp-fld tp-tooth" value={v.tooth} disabled={!v.on}
                                aria-label={`${T.rowTooth}: ${v.r.procedure}`}
                                onChange={(e) => patch(v.i, { tooth: e.target.value })}>{teeth}</select>
                            : <span className="tp-dash" title={T.noTooth}>—</span>}
                        </td>
                        <td>
                          {v.on ? (
                            <>
                              <input className="dp-fld tp-price" inputMode="numeric" value={v.price} maxLength={7}
                                aria-label={`${T.rowPrice}: ${v.r.procedure}`}
                                onChange={(e) => patch(v.i, { price: e.target.value.replace(/\D/g, '') })} />
                              {v.r.price !== null && v.price === String(v.r.price)
                                ? <span className="dp-price-note">{T.fromTpl}</span>
                                : <PriceNote id={`tp-price-${v.i}`} services={services} procedure={v.r.procedure} price={v.price} />}
                            </>
                          ) : <span className="dp-price-note">{T.off}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
          <div className="tp-foot">
            <div className="tp-notes">
              <p className="tp-say">{T.say}</p>
              {/* вторая строка занята всегда: предупреждение о зубе и отказ встают на готовое место, окно от них не растёт */}
              {err
                ? <p className="tp-err" role="alert"><Icon name="excl" /> {err}</p>
                : <p className="tp-warn" aria-hidden={missing === 0 || undefined}>{missing > 0 ? roCount(missing, T.missing) : ' '}</p>}
            </div>
            <button type="button" className="dp-btn" onClick={() => { void leave() }}>{T.cancel}</button>
            <button className="dp-btn pri" disabled={busy || picked.length === 0}>
              <Icon name="plus" /> {picked.length ? roCount(picked.length, T.go) : T.goNone}
            </button>
          </div>
        </form>
      )}
      </div>
    </dialog>
  )
}
