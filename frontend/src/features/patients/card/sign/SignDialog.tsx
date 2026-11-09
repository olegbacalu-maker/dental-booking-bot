import { useEffect, useRef, useState } from 'react'
import { ask } from '../../../../components/confirm'
import { Icon } from '../../../../components/Icon'
import type { CardActions } from '../actions'
import { patientCard, type Form, type PatientCard, type SignBody } from '../card'
import { hideDialog, showDialog } from '../dialog'
import { signPreviewHref } from '../print'
import { SignPad, type SignPadHandle } from './SignPad'

/* Окно подписи бланка на экране (09.11; Олег выбрал раскладку A — кадры и
   разбор в `design\semnare\`). Лист слева — предпросмотр сервера «как будет
   подписан», справа: кто подписывает (пациент или законный представитель с
   именем), у Informare 195 два необязательных согласия DA/NU, поле подписи
   пациента, у согласия к плану — поле врача. Узкое окно (iPad в портрете) —
   колонка под листом.
   «Salvează» отправляет ТОЛЬКО картинки PNG и выборы; сервер делает PDF
   (~1 с) и кладёт документом в категорию бланка, ответ — свежая фиша, как у
   всех действий (`a.act`). Повторный щелчок не шлётся: каждый POST — новый
   документ. Отказ показывается В ОКНЕ: модальное окно лежит поверх плашки
   экрана, и её текст не был бы виден. Контракт — `sign-contract.md` (sign-pdf). */

const T = {
  sign: 'Semnează',
  close: 'Închide',
  cancel: 'Renunță',
  save: 'Salvează semnat',
  saving: 'Se salvează…',
  clear: 'Șterge',
  who: 'Cine semnează',
  patient: 'Pacientul',
  rep: 'Reprezentant legal',
  repName: 'Numele reprezentantului legal',
  repPh: 'Nume, prenume',
  padPatient: 'Semnătura pacientului',
  padRep: 'Semnătura reprezentantului legal',
  padDoctor: 'Semnătura medicului',
  ph: 'Semnați aici — cu degetul, stiloul sau mouse-ul',
  where: 'Se salvează ca PDF în Documente, categoria',
  opts: 'Acorduri opționale (Legea 195)',
  optMkt: 'Mesaje despre oferte și noutăți (marketing)',
  optPhoto: 'Fotografii ale tratamentului (înainte / după)',
  yes: 'DA',
  no: 'NU',
  askLeave: 'Renunțați la semnătură? Ce s-a desenat nu se salvează.',
  askOk: 'Renunță',
  askKeep: 'Continuă semnarea',
  failed: 'Documentul nu s-a salvat. Încercați din nou.',
} as const

type Opt = boolean | null

interface Props {
  card: PatientCard
  form: Form
  a: CardActions
  onClose: () => void
}

export function SignDialog({ card, form, a, onClose }: Props) {
  const dlg = useRef<HTMLDialogElement>(null)
  const pPad = useRef<SignPadHandle>(null)
  const dPad = useRef<SignPadHandle>(null)
  const [signer, setSigner] = useState<SignBody['signer']>('pacient')
  const [repName, setRepName] = useState('')
  const [pEmpty, setPEmpty] = useState(true)
  const [dEmpty, setDEmpty] = useState(true)
  const [opts, setOpts] = useState<{ mkt: Opt; photo: Opt }>({ mkt: null, photo: null })
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState('')
  const needDoctor = form.key === 'acord_plan'
  const cat = card.options.doc_categories.find((c) => c.id === form.category)?.label ?? form.category
  const name = repName.trim()
  const ready = !pEmpty && (!needDoctor || !dEmpty) && (signer === 'pacient' || name.length >= 2)

  useEffect(() => { showDialog(dlg.current) }, [])

  function close() {
    hideDialog(dlg.current)
    onClose()
  }

  /* нарисованное не теряется молча: крестик, «Renunță» и Esc спрашивают */
  async function leave() {
    if (sending) return
    if ((!pEmpty || !dEmpty) && !await ask({ text: T.askLeave, ok: T.askOk, cancel: T.askKeep })) return
    close()
  }

  async function save() {
    if (!ready || sending) return
    const sigP = pPad.current?.png()
    const sigD = needDoctor ? dPad.current?.png() : null
    if (!sigP || (needDoctor && !sigD)) return
    const body: SignBody = { signer, sig_patient: sigP }
    if (signer === 'reprezentant') body.signer_name = name
    if (sigD) body.sig_doctor = sigD
    if (form.key === 'acord195') body.consents = opts
    setSending(true)
    setErr('')
    const e = await a.act(() => patientCard.signForm(a.pid, a.views, form.key, body))
    if (!e) { close(); return }
    setSending(false)
    if (e.failure.kind !== 'unauthenticated') setErr(e.text || T.failed)
  }

  const optRow = (k: 'mkt' | 'photo', text: string) => (
    <div className="sg-opt">
      <span>{text}</span>
      <div className="dp-seg" role="group" aria-label={text}>
        {([true, false] as const).map((v) => (
          <button key={String(v)} type="button" className={opts[k] === v ? 'on' : ''} aria-pressed={opts[k] === v}
            onClick={() => setOpts({ ...opts, [k]: opts[k] === v ? null : v })}>{v ? T.yes : T.no}</button>
        ))}
      </div>
    </div>
  )

  const pTitle = signer === 'pacient' ? T.padPatient : T.padRep
  return (
    <dialog ref={dlg} className="dp-sign" aria-label={`${T.sign}: ${form.title}`}
      onCancel={(e) => { e.preventDefault(); void leave() }}>
      <div className="sg-wrap">
        <div className="dlg-head">
          <span><Icon name="pen" /> {T.sign} · {form.title} <small>· {card.name}</small></span>
          <button type="button" className="sg-x" onClick={() => { void leave() }} aria-label={T.close} disabled={sending}>
            <Icon name="close" />
          </button>
        </div>
        <div className="sg-body">
          <div className="sg-left">
            <iframe className="sg-sheet" title={form.title} src={signPreviewHref(card.id, form.key)} />
          </div>
          <div className="sg-right" aria-busy={sending}>
            <div className="sg-who">
              <div className="dp-seg" role="group" aria-label={T.who}>
                {(['pacient', 'reprezentant'] as const).map((s) => (
                  <button key={s} type="button" className={signer === s ? 'on' : ''} aria-pressed={signer === s}
                    onClick={() => setSigner(s)}>{s === 'pacient' ? T.patient : T.rep}</button>
                ))}
              </div>
              {signer === 'reprezentant' && (
                <label className="sg-rep">
                  <span>{T.repName}</span>
                  <input value={repName} onChange={(e) => setRepName(e.target.value)} placeholder={T.repPh}
                    autoComplete="off" maxLength={80} />
                </label>
              )}
            </div>
            {form.key === 'acord195' && (
              <div className="sg-opts">
                <b>{T.opts}</b>
                {optRow('mkt', T.optMkt)}
                {optRow('photo', T.optPhoto)}
              </div>
            )}
            <SignPad ref={pPad} title={pTitle} sub={signer === 'pacient' ? card.name : name}
              placeholder={T.ph} clearLabel={T.clear} onChange={setPEmpty} />
            {needDoctor && (
              <SignPad ref={dPad} title={T.padDoctor} placeholder={T.ph} clearLabel={T.clear} onChange={setDEmpty} />
            )}
            <div className="sg-foot">
              {err
                ? <p className="sg-err" role="alert"><Icon name="excl" /> {err}</p>
                : <small className="sg-where"><Icon name="file" /> {T.where} «{cat}»</small>}
              <button type="button" className="pl-btn" onClick={() => { void leave() }} disabled={sending}>{T.cancel}</button>
              <button type="button" className="savebtn" disabled={!ready || sending} onClick={() => { void save() }}>
                <Icon name="check" /> {sending ? T.saving : T.save}
              </button>
            </div>
          </div>
        </div>
      </div>
    </dialog>
  )
}
