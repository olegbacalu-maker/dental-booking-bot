import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import type { ApiError } from '../../types/api'
import { useLingering } from '../../utils/motion'
import { roCount } from '../../utils/plural'
import {
  dayTitle, gcalApi, shortDay, type GcalAutomove, type GcalGoogle, type GcalList, type GcalMove,
  type GcalPreview, type GcalPreviewRow, type GcalRow, type GcalWhere,
} from './gcal'

/* Перенос в журнал пачкой и автоматом. Что переносится и почему нет — решает сервер
   (gcal_auto.py): экран печатает его причины и счёт, своего правила у него нет. */
export const W = {
  barIdle: '{go} din {all} au dată, oră, medic și pacient recunoscuți — se pot muta în jurnal deodată.',
  barNone: 'Niciun eveniment din listă nu are medic și pacient recunoscuți — mutați-le una câte una.',
  barAuto: 'Mutarea automată este pornită. Rămân {n}: programul nu le poate muta singur — vedeți motivul.',
  barAutoNone: 'Mutarea automată este pornită: evenimentele cu medic și pacient recunoscuți ajung singure în jurnal.',
  barStop: 'Mutarea automată stă cât timp verificarea Google este oprită. Evenimentele din listă se pot muta deodată.',
  barDone: '{n} mutate în jurnal{fresh}. Rămân {stay} — mutați-le una câte una.',
  freshN: { one: ', {n} fișă nouă', few: ', {n} fișe noi', many: ', {n} de fișe noi' },
  batch: 'Mută în jurnal toate cu medic',
  undo: 'Anulează mutarea',
  close: 'Închide',
  dlgTitle: 'Mută în jurnal evenimentele cu medic',
  dlgAuto: 'Pornește mutarea automată',
  lead: 'Din lista afișată ({where}): {all}. Se mută cele cu dată, oră, medic și pacient recunoscuți — fiecare devine o '
    + 'programare obișnuită în jurnal. Celelalte rămân în «De mutat», cu motivul.',
  leadAuto: 'De acum, la fiecare verificare (din 10 în 10 minute), evenimentele noi care îndeplinesc aceleași condiții '
    + 'se mută singure în jurnal. Oprirea — aceeași bifă, oricând.',
  loading: 'Se verifică ce se mută…',
  svc: 'Procedura',
  svcHint: 'durata rămâne cea din Google',
  sms: 'SMS de reamintire pentru programările din Google',
  smsOn: '{n} — după regulile obișnuite; primele pleacă azi, până la 21:00.',
  smsOnN: { one: '{n} pacient va primi SMS', few: '{n} pacienți vor primi SMS', many: '{n} de pacienți vor primi SMS' },
  smsOff: 'Pentru programările mutate din Google nu se trimit SMS.',
  smsNext: 'Se aplică programărilor mutate de acum înainte.',
  goN: 'se mută',
  freshCount: { one: 'fișă nouă', few: 'fișe noi', many: 'de fișe noi' },
  stayN: 'rămân în listă',
  goT: 'Se mută',
  stayT: 'Rămân în «De mutat»',
  cWhen: 'Ziua și ora',
  cWhat: 'Din Google',
  cWho: 'Pacient',
  cDoc: 'Medic',
  cWhy: 'De ce rămâne',
  card: 'fișă',
  fresh: 'fișă nouă',
  linked: 'există deja în jurnal',
  run: { one: 'Mută {n} programare', few: 'Mută {n} programări', many: 'Mută {n} de programări' },
  runAuto: 'Mută {n} și pornește',
  runAuto0: 'Pornește',
  cancel: 'Renunță',
  evN: { one: '{n} eveniment', few: '{n} evenimente', many: '{n} de evenimente' },
  allDays: 'De mutat · toate zilele',
  oneDay: 'De mutat · {d}',
  query: ', căutare „{q}”',
  autoL: 'Mută automat în jurnal evenimentele cu medic',
  autoOff: 'La pornire vedeți mai întâi ce se mută acum.',
  autoLast: 'Ultima: {when} — {n}.',
  autoNone: 'Pornită. Nimic nu s-a mutat încă.',
  autoStop: 'Stă cât timp legătura este oprită; bifa rămâne.',
  autoRemote: 'Se schimbă doar de pe calculatorul programului.',
  apptN: { one: '{n} programare', few: '{n} programări', many: '{n} de programări' },
  history: 'Istoricul mutărilor',
  hTitle: 'Mutări din Google în jurnal',
  hAuto: 'automat',
  hBatch: 'din listă',
  hUndone: 'anulată',
  hRemoved: '{n} șterse',
  hHint: 'Anularea șterge din jurnal doar programările pe care nu le-a schimbat nimeni (ora, medicul, starea, plata, fișa de '
    + 'tratament, SMS trimis) și fișele noi rămase goale. Evenimentele revin în «De mutat» și nu se mai mută singure.',
  hEmpty: 'Încă nu s-a mutat nimic deodată.',
  undoAsk: 'Anulați mutarea din {when}? Se șterg din jurnal {n}, dacă nu le-a schimbat nimeni, și fișele noi rămase goale. '
    + 'Evenimentele revin în «De mutat» și nu se mai mută singure.',
  stayPill: 'nu se mută singur: {why}',
  autoPill: 'mutat automat',
  follow: 'Mută și programarea',
  cancelAppt: 'Anulează programarea',
  keep: 'Lasă cum e',
  dpChanged: 'programarea a fost schimbată în DentPilot',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const cnt = (n: number, forms: Parameters<typeof roCount>[1]) => roCount(n, forms)

/* ---------------- полоса над «De mutat» ---------------- */

export interface BatchDone { key: string; n: number; fresh: number }

interface BarProps {
  a: GcalAutomove
  /** Автоперенос включён и связь работает. */
  auto: boolean
  /** Автоперенос включён, но стоит (Basic, режим чтения, пауза). */
  stopped: boolean
  done: BatchDone | null
  busy: boolean
  onOpen: () => void
  onUndo: (key: string) => void
  onClose: () => void
}

/* Одна строка во всех видах: итог пачки, автоперенос, подсказка — текст меняется, высота нет
   (полоса стоит под шапкой списка, и опрос не должен двигать строки под ней). */
export function BatchBar({ a, auto, stopped, done, busy, onOpen, onUndo, onClose }: BarProps) {
  const left = Math.max(0, a.batch.all - a.batch.go)
  let text: string
  let kind = 'idle'
  if (done) {
    kind = 'done'
    text = W.barDone.replace('{n}', cnt(done.n, W.apptN))
      .replace('{fresh}', done.fresh ? cnt(done.fresh, W.freshN) : '').replace('{stay}', String(a.batch.all))
  } else if (stopped) {
    text = W.barStop
  } else if (auto) {
    kind = 'auto'
    text = left ? W.barAuto.replace('{n}', cnt(left, W.evN)) : W.barAutoNone
  } else {
    text = a.batch.go ? W.barIdle.replace('{go}', String(a.batch.go)).replace('{all}', cnt(a.batch.all, W.evN))
      : W.barNone
  }
  return (
    <div className="fcard gcb-bar" data-bar={kind}>
      <span className={`gcb-ico${done ? ' ok' : ''}`}><Icon name={done ? 'check' : kind === 'auto' ? 'refresh' : 'layers'} /></span>
      <p className="gcb-t">{text}</p>
      <div className="gcb-a">
        {done ? (
          <>
            {a.batch.can ? (
              <button type="button" className="rc-btn" disabled={busy} onClick={() => onUndo(done.key)}>
                <Icon name="undo" /> {W.undo}
              </button>
            ) : null}
            <button type="button" className="gc-x" onClick={onClose} aria-label={W.close}><Icon name="close" /></button>
          </>
        ) : a.batch.can ? (
          <button type="button" className="rc-btn pri" disabled={busy || !a.batch.go} onClick={onOpen}>
            <Icon name="layers" /> {W.batch}
          </button>
        ) : null}
      </div>
    </div>
  )
}

/* ---------------- окно предпросмотра ---------------- */

export interface BatchRequest { auto: boolean; seq: number }

interface DialogProps {
  req: BatchRequest | null
  where: GcalWhere
  services: { key: string; label: string }[]
  /** Ответ команды списка (процедура, SMS): экран кладёт свежий список. */
  onList: (list: GcalList) => void
  onDone: (r: { data: GcalList; text: string; tone: 'ok' | 'warn' | 'err' }, auto: boolean) => void
  onAuthLost: (e: ApiError) => boolean
  onClose: () => void
}

export function BatchDialog({ req, where, services, onList, onDone, onAuthLost, onClose }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const [got, setGot] = useState<{ seq: number; pv: GcalPreview } | null>(null)
  const [err, setErr] = useState<{ seq: number; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [turn, setTurn] = useState(0)
  /* окно гаснет за ступень: заголовок и тело стоят до конца, не пустеют */
  const { shown } = useLingering(req)
  const seq = req?.seq ?? -1
  /* отбор и выход по 401 — на момент запроса, а не на момент отрисовки: объект отбора новый на каждой
     отрисовке экрана, и зависимость от него перезапрашивала бы предпросмотр без конца */
  const at = useRef(where)
  const lost = useRef(onAuthLost)
  useLayoutEffect(() => {
    at.current = where
    lost.current = onAuthLost
  })

  useEffect(() => {
    if (req) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [req])

  useEffect(() => {
    if (!req) return
    let live = true
    gcalApi.batch.check(req.auto, at.current).then(
      (r) => { if (live) setGot({ seq: req.seq, pv: r.data.preview }) },
      (e: unknown) => {
        const a = asApiError(e)
        if (live && !lost.current(a)) setErr({ seq: req.seq, text: a.text || W.offline })
      },
    )
    return () => { live = false }
    // перечитать — при новом открытии и после смены процедуры или SMS (turn)
  }, [req, turn])

  const pv = got && got.seq === (req?.seq ?? got.seq) ? got.pv : null
  const fail = err && err.seq === seq ? err.text : ''
  const auto = shown?.auto ?? false

  async function act(call: () => Promise<{ data: GcalList }>) {
    setBusy(true)
    try {
      onList((await call()).data)
      setTurn((t) => t + 1)
    } catch (e) {
      const a = asApiError(e)
      if (!lost.current(a)) setErr({ seq, text: a.text || W.offline })
    } finally {
      setBusy(false)
    }
  }

  async function go() {
    if (!pv) return
    setBusy(true)
    try {
      const r = await gcalApi.batch.run(pv.token, auto, at.current)
      onDone({ data: r.data, text: r.text, tone: r.tone }, auto)
    } catch (e) {
      const a = asApiError(e)
      if (lost.current(a)) return
      setErr({ seq, text: a.text || W.offline })
      // список изменился между предпросмотром и запуском — показать новый
      if (a.failure.kind === 'conflict') setTurn((t) => t + 1)
    } finally {
      setBusy(false)
    }
  }

  const place = (where.date ? W.oneDay.replace('{d}', dayTitle(where.date)) : W.allDays)
    + (where.q ? W.query.replace('{q}', where.q) : '')
  const when = (x: GcalPreviewRow) => `${x.date ? shortDay(x.date) : ''} ${x.time}`.trim()
  return (
    <dialog ref={ref} className="rg-dlg wide gcb-dlg" onClose={onClose} aria-label={auto ? W.dlgAuto : W.dlgTitle}>
      <div className="dlg-head">
        <span><Icon name={auto ? 'refresh' : 'layers'} /> {auto ? W.dlgAuto : W.dlgTitle}</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label={W.close}><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b gcb-body" aria-busy={!pv}>
        {!pv ? <p className="hint gcb-wait">{fail || W.loading}</p> : (
          <>
            <p className="hint gcb-lead">{W.lead.replace('{where}', place).replace('{all}', cnt(pv.counts.all, W.evN))}</p>
            {auto ? <p className="gcb-autolead"><Icon name="refresh" /> {W.leadAuto}</p> : null}
            <div className="gcb-opts">
              <label className="gcb-svc">{W.svc}
                <select className="dp-sel" value={pv.service} disabled={busy}
                        onChange={(e) => { const v = e.target.value; void act(() => gcalApi.service(v, at.current)) }}>
                  {services.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                </select>
                <small className="hint">{W.svcHint}</small>
              </label>
              {pv.sms.show ? (
                <div className="gcb-sms">
                  <label>
                    <input type="checkbox" checked={pv.sms.on} disabled={busy}
                           onChange={(e) => { const on = e.target.checked; void act(() => gcalApi.sms(on, at.current)) }} />
                    <span>{W.sms}</span>
                  </label>
                  <small className="hint">
                    {pv.sms.on ? W.smsOn.replace('{n}', cnt(pv.counts.go, W.smsOnN)) : `${W.smsOff} ${W.smsNext}`}
                  </small>
                </div>
              ) : null}
            </div>
            {fail ? <p className="banner err" role="alert">{fail}</p> : null}
            <ul className="gcb-counts">
              <li className="go"><b>{pv.counts.go}</b> {W.goN}</li>
              <li><b>{pv.counts.fresh}</b> {roCount(pv.counts.fresh, W.freshCount).replace(/^\d+ /, '')}</li>
              <li className="stay"><b>{pv.counts.stay}</b> {W.stayN}</li>
            </ul>
            {pv.go.length ? (
              <details className="gcb-group" open>
                <summary><Icon name="chev-r" /><b>{W.goT}</b> <span className="gcb-badge">{pv.go.length}</span></summary>
                <table className="gcb-table">
                  <thead><tr><th>{W.cWhen}</th><th>{W.cWhat}</th><th>{W.cWho}</th><th>{W.cDoc}</th></tr></thead>
                  <tbody>
                    {pv.go.map((x) => (
                      <tr key={x.id}>
                        <td className="gcb-when">{when(x)}</td>
                        <td className="gcb-what">{x.title}</td>
                        <td>
                          {x.fresh ? <span className="rc-pill green">{W.fresh}</span> : <span className="hint">{W.card}:</span>}
                          {' '}{x.patient}{x.fresh && x.phone ? ` · ${x.phone}` : ''}
                          {x.link ? <span className="hint"> · {W.linked}</span> : null}
                        </td>
                        <td>{x.doctor}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ) : null}
            {pv.stay.length ? (
              <details className="gcb-group" open>
                <summary><Icon name="chev-r" /><b>{W.stayT}</b> <span className="gcb-badge">{pv.stay.length}</span></summary>
                <table className="gcb-table">
                  <thead><tr><th>{W.cWhen}</th><th>{W.cWhat}</th><th>{W.cWhy}</th></tr></thead>
                  <tbody>
                    {pv.stay.map((x) => (
                      <tr key={x.id}>
                        <td className="gcb-when">{when(x)}</td>
                        <td className="gcb-what">{x.title || '—'}</td>
                        <td className="gcb-why">{x.why?.text}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ) : null}
          </>
        )}
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn pri" disabled={busy || !pv || (!auto && !pv.counts.go)}
                onClick={() => { void go() }}>
          <Icon name={auto ? 'refresh' : 'layers'} />{' '}
          {auto ? (pv?.counts.go ? W.runAuto.replace('{n}', String(pv.counts.go)) : W.runAuto0)
            : cnt(pv?.counts.go ?? 0, W.run)}
        </button>
        <button type="button" className="rc-btn" disabled={busy} onClick={onClose}>{W.cancel}</button>
      </div>
    </dialog>
  )
}

/* ---------------- строка автопереноса в блоке аккаунта ---------------- */

interface AutoProps {
  g: GcalGoogle
  a: GcalAutomove
  busy: boolean
  onAuto: (on: boolean) => void
  onSms: (on: boolean) => void
  onHistory: () => void
}

/* Место под обе строки занято во всех спокойных состояниях связи: опрос меняет текст «Ultima: …»,
   а не высоту полосы. Ссылка истории прижата вправо — за меняющимся текстом она ехала бы вбок. */
export function AutoRow({ g, a, busy, onAuto, onSms, onHistory }: AutoProps) {
  const auto = g.auto
  if (!auto) return null
  const remote = !!g.remote
  let hint: string
  if (remote) hint = W.autoRemote
  else if (auto.on && auto.stopped) hint = W.autoStop
  else if (!auto.on) hint = W.autoOff
  else if (a.last) hint = W.autoLast.replace('{when}', a.last.when).replace('{n}', cnt(a.last.n, W.apptN))
  else hint = W.autoNone
  const canToggle = auto.on ? auto.can_off : auto.can_on
  return (
    <div className="gl-auto" data-auto={auto.on ? 'on' : 'off'}>
      <div className="gl-autoc">
        <label className="gl-chk">
          <input type="checkbox" checked={auto.on} disabled={busy || !canToggle}
                 onChange={(e) => onAuto(e.target.checked)} />
          <span>{W.autoL}</span>
        </label>
        <small className="gl-autoh">
          <span className="gl-autot">{hint}</span>
          {auto.on || a.moves.length
            ? <button type="button" className="dp-link gl-hist" onClick={onHistory}>{W.history} ›</button> : null}
        </small>
      </div>
      {a.sms.show && g.state !== 'plus' ? (
        <div className="gl-autoc">
          <label className="gl-chk">
            <input type="checkbox" checked={a.sms.on} disabled={busy || remote || g.state === 'readonly'}
                   onChange={(e) => onSms(e.target.checked)} />
            <span>{W.sms}</span>
          </label>
          <small className="gl-autoh"><span className="gl-autot">{a.sms.on ? W.smsNext : W.smsOff}</span></small>
        </div>
      ) : null}
    </div>
  )
}

/* ---------------- история мутаций ---------------- */

interface HistoryProps {
  open: boolean
  moves: GcalMove[]
  can: boolean
  busy: boolean
  onUndo: (m: GcalMove) => void
  onClose: () => void
}

export function HistoryDialog({ open, moves, can, busy, onUndo, onClose }: HistoryProps) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])
  return (
    <dialog ref={ref} className="rg-dlg wide gcb-dlg" onClose={onClose} aria-label={W.hTitle}>
      <div className="dlg-head">
        <span><Icon name="clock" /> {W.hTitle}</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label={W.close}><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        {moves.length ? (
          <ul className="gcb-hist">
            {moves.map((m) => (
              <li key={m.key} className={m.undone ? 'undone' : ''}>
                <span className={`gcb-ico${m.how === 'auto' ? '' : ' batch'}`}>
                  <Icon name={m.how === 'auto' ? 'refresh' : 'layers'} />
                </span>
                <span className="gcb-hw">
                  <span><b>{m.when}</b> · {m.how === 'auto' ? W.hAuto : `${m.by}, ${W.hBatch}`}</span>
                  <small>
                    {cnt(m.n, W.apptN)}{m.fresh ? `, ${roCount(m.fresh, W.freshCount)}` : ''}
                    {m.undone ? ` · ${W.hUndone}: ${W.hRemoved.replace('{n}', String(m.undone.removed))}` : ''}
                  </small>
                </span>
                {m.undone ? <span className="rc-pill grey">{W.hUndone}</span> : can ? (
                  <button type="button" className="rc-btn" disabled={busy} onClick={() => onUndo(m)}>
                    <Icon name="undo" /> {W.undo}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : <p className="hint">{W.hEmpty}</p>}
        <p className="hint gcb-hhint"><Icon name="info" /> {W.hHint}</p>
      </div>
    </dialog>
  )
}

export function undoAsk(m: GcalMove): string {
  return W.undoAsk.replace('{when}', m.when).replace('{n}', cnt(m.n, W.apptN))
}

/* ---------------- строки ---------------- */

export function StayPill({ r }: { r: GcalRow }) {
  const why = r.state === 'nou' ? r.auto?.why : null
  return why ? <span className="rc-pill grey gcb-stay"><Icon name="info" /> {W.stayPill.replace('{why}', why.text)}</span> : null
}

interface ChangedProps {
  r: GcalRow
  busy: boolean
  onFollow: () => void
  onCancel: () => void
  onKeep: () => void
}

export function ChangedActs({ r, busy, onFollow, onCancel, onKeep }: ChangedProps) {
  if (!r.changed || !r.can.keep) return null
  return (
    <>
      {r.auto?.dp ? <span className="hint gcb-dp">{W.dpChanged}</span> : null}
      {r.can.follow ? (
        <button type="button" className="rc-btn pri" disabled={busy} onClick={onFollow}>
          <Icon name="clock" /> {W.follow}
        </button>
      ) : null}
      {r.can.cancel_appt ? (
        <button type="button" className="rc-btn gcb-danger" disabled={busy} onClick={onCancel}>
          <Icon name="ban" /> {W.cancelAppt}
        </button>
      ) : null}
      <button type="button" className="rc-btn" disabled={busy} onClick={onKeep}>{W.keep}</button>
    </>
  )
}
