import { useCallback, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { visits, type VisitPage } from './visits'

/* «Consultație» — дневник визита (C19): те же слова, графы и кнопки, что у
   старой страницы. Шаблон заполняет ТОЛЬКО пустые графы (клик не должен
   стереть вписанное руками); отмеченные позиции плана сервер финализирует
   на этом визите. Отменённому/неявившемуся форма не даётся — запись, если
   успела появиться, показывается для чтения. */
const T = {
  back: 'Înapoi',
  card: 'Fișa pacientului',
  title: 'Consultație',
  visit: 'vizita',
  rows: { patient: 'Pacient', service: 'Serviciu', doctor: 'Medic', status: 'Status', comment: 'Comentariu recepție' },
  diary: 'Jurnalul consultației',
  diarySub: 'partea de jurnal a fișei 043/e',
  tplHint: 'Șablonul completează doar câmpurile goale',
  linked: 'Efectuate la această vizită',
  openTitle: 'Proceduri din plan efectuate la această vizită',
  openHint: '— bifate devin «Finalizat» în plan și se leagă de vizită',
  inLucru: '— în lucru',
  save: 'Salvează consultația',
  created: 'Înregistrat:',
  updated: 'actualizat:',
  by: 'de',
  notFound: 'Vizita nu există sau este o notă fără pacient.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

const FIELD_IDS = ['acuze', 'examen', 'diagnostic', 'tratament', 'recomandari'] as const
type FieldId = (typeof FIELD_IDS)[number]
type Vals = Record<FieldId, string>

function valsOf(p: VisitPage): Vals {
  const r = p.record
  return { acuze: r?.acuze ?? '', examen: r?.examen ?? '', diagnostic: r?.diagnostic ?? '',
    tratament: r?.tratament ?? '', recomandari: r?.recomandari ?? '' }
}

function meta(p: VisitPage): string {
  const r = p.record
  if (!r) return ''
  return `${T.created} ${r.created}${r.updated ? ` · ${T.updated} ${r.updated}` : ''} · ${T.by} ${r.author || '—'}`
}

interface Draft {
  page: VisitPage
  vals: Vals
  done: number[]
}

interface Props {
  /** Номер визита — параметр пути `appt_id`, его разбирает роутер. */
  aid: number
  navigate?: (url: string) => void
}

/**
 * Данные грузит роутер (B2.3): номер — из пути, «Înapoi» — `?back=` ТЕКУЩЕГО
 * адреса, и больше ниоткуда (не из узла: тот описывает документ). Значение
 * уходит серверу как есть, а экран показывает и шлёт ТОЛЬКО эхо сервера
 * `page.back`: проверяет адрес возврата один `_visit_back`, и чужой
 * `?back=http://…` не станет живой ссылкой. Сам экран адрес не пишет.
 */
export const loadVisit: RouteLoad<VisitPage> = (signal, p, q) =>
  visits.get(Number(p.appt_id), queryParam(q, 'back'), signal)

export function VisitScreen({ aid, navigate = defaultNavigate }: Props) {
  const { state, pending, retry, replace, leaveIfSignedOut } = useRouteLoad<VisitPage>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [saving, setSaving] = useState(false)
  /* черновик привязан к странице, с которой начат: свежая страница после
     сохранения даёт форме свои значения, отказ ввод не трогает */
  const [draft, setDraft] = useState<Draft | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  if (state.status === 'leaving') return null

  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }

  /* ⚠️ Переход роутером на другой визит: пока ответа нет, форма НЕ
     показывается — иначе правили бы запись, которую уже покидают. То же
     ожидание, что и при открытии визита. */
  if (state.status === 'loading' || pending) {
    return <section className="dp-react-root" aria-busy="true"><div className="vwrap"><div className="fcard" /></div></section>
  }

  const page = state.data
  const cur: Draft = draft && draft.page === page ? draft : { page, vals: valsOf(page), done: [] }
  const edit = (patch: Partial<Draft>) =>
    setDraft((d) => ({ ...(d && d.page === page ? d : { page, vals: valsOf(page), done: [] }), ...patch }))
  const setVal = (k: FieldId, v: string) => edit({ vals: { ...cur.vals, [k]: v } })

  function applyTpl(id: string) {
    const t = page.templates.find((x) => x.id === id)
    if (!t) return
    const next = { ...cur.vals }
    for (const k of FIELD_IDS) {
      if (!next[k].trim() && t.values[k]) next[k] = t.values[k]
    }
    edit({ vals: next })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const r = await visits.save(aid, { ...cur.vals, done: cur.done, back: page.back })
      replace(r.data)
      if (r.text) setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      const ae = asApiError(err)
      if (!leaveIfSignedOut(ae)) setToast({ tone: 'err', text: ae.text || T.offline })
    } finally {
      setSaving(false)
    }
  }

  const a = page.appt
  const metaLine = meta(page)
  const fieldOf = (id: string) => page.fields.find((f) => f.id === id)

  return (
    <section className="dp-react-root" aria-busy={saving || undefined}>
      <p className="dp-vnav">
        <AppLink href={page.back}><Icon name="chev-l" /> {T.back}</AppLink>
        {' '}&nbsp;·&nbsp;{' '}
        <AppLink href={`/admin/patient/${a.patient_id}`}><Icon name="id" /> {T.card}</AppLink>
      </p>
      <div className="vwrap">
        <div className="fcard">
          <h3>{T.title} <small>· {a.when} · {T.visit} #{a.id}</small></h3>
          <div className="frow"><span>{T.rows.patient}</span><span className="v"><AppLink href={`/admin/patient/${a.patient_id}`}>{a.patient || '—'}</AppLink></span></div>
          <div className="frow"><span>{T.rows.service}</span><span className="v">{a.service}</span></div>
          <div className="frow"><span>{T.rows.doctor}</span><span className="v">{a.doctor}</span></div>
          <div className="frow"><span>{T.rows.status}</span><span className="v">{a.status_label}</span></div>
          {a.comment && (
            <div className="frow"><span>{T.rows.comment}</span><span className="v"><Icon name="chat" /> {a.comment}</span></div>
          )}
        </div>
        {page.editable ? (
          <div className="fcard">
            <h3>{T.diary} <small>· {T.diarySub}</small></h3>
            <div className="tplrow">
              {page.templates.map((t) => (
                <button key={t.id} type="button" onClick={() => applyTpl(t.id)}>{t.label}</button>
              ))}
            </div>
            <small className="hint dp-tpl-hint">{T.tplHint}</small>
            <form className="fform" onSubmit={onSubmit}>
              {FIELD_IDS.map((k) => {
                const f = fieldOf(k)
                return (
                  <label key={k} className="dlab" htmlFor={`vf_${k}`}>
                    {f?.label ?? k}
                    <textarea id={`vf_${k}`} rows={f?.rows ?? 2} maxLength={2000} placeholder={f?.placeholder ?? ''}
                              value={cur.vals[k]} onChange={(e) => setVal(k, e.target.value)} />
                  </label>
                )
              })}
              {page.plan.linked.length > 0 && (
                <>
                  <div className="vsec"><b>{T.linked}</b></div>
                  {page.plan.linked.map((it) => <div key={it.id} className="vdone"><Icon name="check" /> {it.text}</div>)}
                </>
              )}
              {page.plan.open.length > 0 && (
                <>
                  <div className="vsec"><b>{T.openTitle}</b> <small className="hint dp-m0">{T.openHint}</small></div>
                  <div className="vchk">
                    {page.plan.open.map((it) => (
                      <label key={it.id}>
                        <input type="checkbox" checked={cur.done.includes(it.id)}
                               onChange={(e) => edit({ done: e.target.checked ? [...cur.done, it.id] : cur.done.filter((x) => x !== it.id) })} />
                        <span>{it.text}{it.in_lucru && <> <small>{T.inLucru}</small></>}</span>
                      </label>
                    ))}
                  </div>
                </>
              )}
              <button className="savebtn" disabled={saving}><Icon name="save" /> {T.save}</button>
              {metaLine && <div className="vmeta">{metaLine}</div>}
            </form>
          </div>
        ) : (
          <div className="fcard">
            <h3>{T.diary}</h3>
            <div className="banner warn">{page.note}</div>
            {FIELD_IDS.filter((k) => cur.vals[k]).map((k) => (
              <p key={k} className="vsec">
                <b>{fieldOf(k)?.label ?? k}:</b><br />
                {cur.vals[k].split('\n').map((line, i) => <span key={i}>{i > 0 && <br />}{line}</span>)}
              </p>
            ))}
            {metaLine && <div className="vmeta">{metaLine}</div>}
          </div>
        )}
      </div>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
