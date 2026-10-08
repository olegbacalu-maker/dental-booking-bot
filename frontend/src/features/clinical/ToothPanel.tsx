import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { StatusPicker } from './StatusPicker'
import { SurfaceCross } from './SurfaceCross'
import { JAW_RO, bridgeOf, surfaceLetter, type Jaw, type Odontogram, type PerioLayer, type PerioLayerRow } from './chart'
import type { ToothDraft } from './useChart'

/* Панель выбранного зуба (08.10, макет «Stare dinți»; до того — инспектор
   `ToothInspector` + форма `ToothForm`): крупный номер с названием и
   стороной (слова сервера), крест поверхностей, состояние сеткой кнопок,
   отметки переключателями, врач, заметка, «Salvează» со строкой состояния,
   замер пародонта, действия с зуба и история под шторкой.
   Модалки здесь нет НАМЕРЕННО: она закрывает собой карту, а смысл экрана —
   видеть зуб и соседей сразу. Всё, что умеет контекстное меню, есть и
   здесь. Форма КОНТРОЛИРУЕМАЯ (C22): черновик живёт в useChart — его правят
   ещё клик по кресту, по зубу в сцене и меню, а форма его только показывает
   и меняет через onEdit. Намерение уезжает явно (карта поверхностей и список
   отметок всегда, state0 — как показали).
   Пальцем (B7 · планшет) панель — шторка поверх карты: классы `insp`,
   `insp-close` держат те же правила app.css, что и раньше. */
const T = {
  title: 'Dinte selectat',
  pick: 'Alege un dinte',
  bridge: 'Punte',
  role: 'rol',
  delBridge: 'Șterge puntea',
  confirmDel: 'Ștergeți puntea {span}? Dinții rămân cu starea lor.',
  bridgeFrom: 'Punte nouă de la acest dinte',
  plan: 'Adaugă în plan',
  history: 'Istoric',
  noHistory: '— fără înregistrări —',
  perio: 'Parodontogramă',
  openPerio: 'Deschide examenul',
  site: 'Punct',
  bop: 'Sângerare la sondare',
  noBop: 'fără sângerare',
  notMeasured: 'nemăsurat',
  mob: 'Mobilitate',
  furc: 'Furcație',
  close: 'Închide',
  surfaces: 'Suprafețe',
  surfaceState: 'Starea suprafeței',
  none: '— fără leziune',
  state: 'Starea dintelui',
  stateOn: 'Apasă din nou pentru a șterge',
  stateOff: 'Sănătos / fără stare',
  doctor: 'Medic',
  doctorNone: 'Medic —',
  note: 'Notiță (opțional)',
  save: 'Salvează',
  discard: 'Renunță',
  unsaved: 'Modificări nesalvate',
  saved: 'Salvat pentru dintele',
} as const

interface Props {
  model: Odontogram
  n: number | null
  busy: boolean
  /** Выбранная поверхность — состояние рабочего стола (её выбирают и из сцены). */
  sel: string
  /** Клик по клетке креста: выбрать поверхность, повторный — крутить её состояние. */
  onSurface: (n: number, letter: string) => void
  draft: ToothDraft | null
  dirty: boolean
  onEdit: (patch: Partial<ToothDraft>) => void
  onSave: () => void
  onDiscard: () => void
  onDelBridge: (bid: number) => void
  onBridgeFrom?: ((n: number) => void) | undefined
  /** позиция плана с этого зуба (01.10): то же, что в меню зуба */
  onPlan?: ((n: number) => void) | undefined
  /** Закрыть панель (пальцем она — шторка поверх карты); мышью кнопки не видно. */
  onClose?: (() => void) | undefined
  /** Зуб, записанный последним нажатием «Salvează», — для строки состояния. */
  saved: number | null
}

/** Шесть точек зуба таблицей (06.10): глубина, рецессия, CAL, кровоточивость.
 *  ⛔ Ничего не считается: CAL и пороги — с сервера (`perio_layer`), ноль —
 *  «не измеряли», а не «0 мм» (шапка perio.py), поэтому показывается точкой. */
function PerioTable({ row, layer, jaw }: { row: PerioLayerRow; layer: PerioLayer; jaw: Jaw }) {
  const L = surfaceLetter('L', jaw)
  const codes = ['MV', 'V', 'DV', `M${L}`, L, `D${L}`]
  const mm = (v: number | undefined) => (v ? String(v) : '·')
  const band = (v: number) => (v >= layer.limits.severe ? 'sev' : v >= layer.limits.deep ? 'deep' : '')
  const grade = (kind: 'mob' | 'furc', v: number) => (v ? `${kind === 'mob' ? T.mob : T.furc} ${layer.grades[kind][String(v)] ?? v}` : '')
  const extra = [grade('mob', row.mob), grade('furc', row.furc)].filter(Boolean).join(' · ')
  return (
    <>
      <table className="i-ptab">
        <thead>
          <tr><th scope="col">{T.site}</th><th scope="col">PD</th><th scope="col">REC</th><th scope="col">CAL</th><th scope="col">BOP</th></tr>
        </thead>
        <tbody>
          {codes.map((code, i) => {
            const pd = row.pd[i] ?? 0
            const bleed = row.bop[i] === '1'
            return (
              <tr key={code} data-site={layer.sites[i]?.key}>
                <th scope="row" title={layer.sites[i]?.label}>{code}</th>
                <td className={band(pd)} title={pd ? undefined : T.notMeasured}>{mm(pd)}</td>
                <td>{mm(row.rec[i])}</td>
                <td>{mm(row.cal[i])}</td>
                <td>{bleed ? <i className="i-bop" title={T.bop} aria-label={T.bop} /> : <span title={T.noBop}>–</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {extra && <b>{extra}</b>}
    </>
  )
}

export function ToothPanel({
  model, n, busy, sel, onSurface, draft: d, dirty, onEdit: edit, onSave, onDiscard, onDelBridge,
  onBridgeFrom, onPlan, onClose, saved,
}: Props) {
  const info = n !== null ? model.teeth[String(n)] : undefined
  const inBr = n !== null ? bridgeOf(model, n) : null
  const hist = n !== null ? (model.history[String(n)] ?? []) : []
  // замер пародонта у ЭТОГО зуба: у одонтограммы и пародонтограммы один зуб,
  // и врачу не надо уходить со страницы, чтобы вспомнить глубину кармана
  const perio = n !== null ? model.perio?.[String(n)] : undefined
  const layer = model.perio_layer ?? null
  const prow = n !== null ? layer?.rows[String(n)] : undefined
  const cur = info && sel in model.surfaces ? sel : 'O'
  const selState = d?.sfst[cur] ?? ''
  const canBridge = Boolean(info && n !== null && !inBr && !info.milk && onBridgeFrom)

  return (
    <div className="dp-card insp dp-tp" aria-label={T.title}>
      <div className="dp-tp-head">
        {info && n !== null ? (
          <>
            <b className="dp-tp-num">{n}</b>
            <div className="dp-tp-who">
              <span className="dp-lbl">{T.title}</span>
              <span className="dp-tp-name">{info.name ?? ''}</span>
              <small><span>{JAW_RO[info.jaw]}</span>{info.side && <> · <span>{info.side}</span></>}</small>
            </div>
          </>
        ) : (
          <div className="dp-tp-who dp-tp-none">
            <span className="dp-lbl">{T.title}</span>
            <span className="dp-tp-name">{T.pick}</span>
          </div>
        )}
        {onClose && n !== null && (
          <button type="button" className="insp-close" aria-label={T.close} title={T.close} onClick={onClose}><Icon name="close" /></button>
        )}
      </div>

      {inBr && (
        <div className="dp-tp-sec i-bridge">
          <span>
            {T.bridge} {inBr.bridge.teeth[0]?.[0]}-{inBr.bridge.teeth[inBr.bridge.teeth.length - 1]?.[0]}
            {inBr.bridge.material ? ` (${inBr.bridge.material})` : ''} - {T.role}: {model.bridge_roles[inBr.role] ?? inBr.role}
          </span>
          <form onSubmit={(e) => {
            e.preventDefault()
            const span = `${inBr.bridge.teeth[0]?.[0]}-${inBr.bridge.teeth[inBr.bridge.teeth.length - 1]?.[0]}`
            void ask({ text: T.confirmDel.replace('{span}', span), danger: true })
              .then((yes) => { if (yes) onDelBridge(inBr.bridge.id) })
          }}>
            <button className="pl-btn" disabled={busy}>{T.delBridge}</button>
          </form>
        </div>
      )}

      {info && n !== null && d && (
        <form className="dp-tp-form" onSubmit={(e) => { e.preventDefault(); onSave() }}>
          <section className="dp-tp-sec">
            <span className="dp-lbl">{T.surfaces}</span>
            <SurfaceCross model={model} n={n} info={info} sel={cur} sfst={d.sfst} onSurface={onSurface} />
            {/* состояние ВЫБРАННОЙ поверхности — тот же выбор, что крутит
                повторный клик по клетке; список сервера (`surface_states`) */}
            <label className="dp-tp-sfst">
              <span>{T.surfaceState} <b>{surfaceLetter(cur, info.jaw)}</b></span>
              <select className="dp-fld" value={selState} onChange={(e) => {
                const next = { ...d.sfst }
                if (e.target.value) next[cur] = e.target.value
                else delete next[cur]
                edit({ sfst: next })
              }}>
                <option value="">{T.none}</option>
                {model.surface_states.map((s) => <option key={s} value={s}>{model.states[s] ?? s}</option>)}
              </select>
            </label>
          </section>

          <section className="dp-tp-sec">
            <div className="dp-tp-row">
              <span className="dp-lbl">{T.state}</span>
              <span className="dp-tp-note">{d.state !== 'ok' ? T.stateOn : T.stateOff}</span>
            </div>
            <StatusPicker states={model.states} palette={model.palette} value={d.state} disabled={busy}
              onChange={(state) => edit({ state })} />
            <div className="dp-tp-sw">
              {Object.entries(model.marks).map(([k, v]) => (
                <label key={k} className="dp-sw">
                  <span>{v}</span>
                  <input type="checkbox" role="switch" checked={d.marks.includes(k)} disabled={busy}
                    onChange={(e) => edit({ marks: e.target.checked ? [...d.marks, k] : d.marks.filter((x) => x !== k) })} />
                </label>
              ))}
            </div>
          </section>

          <section className="dp-tp-sec">
            <label className="dp-lbl" htmlFor={`dp-doc-${n}`}>{T.doctor}</label>
            <select id={`dp-doc-${n}`} className="dp-fld" value={d.doctor} onChange={(e) => edit({ doctor: e.target.value })}>
              <option value="">{T.doctorNone}</option>
              {model.doctors.map((doc) => <option key={doc} value={doc}>{doc}</option>)}
            </select>
            <label className="dp-lbl" htmlFor={`dp-note-${n}`}>{T.note}</label>
            <textarea id={`dp-note-${n}`} className="dp-fld" rows={2} maxLength={120} value={d.note}
              onChange={(e) => edit({ note: e.target.value })} />
            <button className="dp-btn pri" disabled={busy}><Icon name="save" /> {T.save}</button>
            <div className="dp-tp-status" aria-live="polite">
              {dirty ? (
                <>
                  <span className="dp-draft">{T.unsaved}</span>
                  <button type="button" className="dp-link" onClick={onDiscard}>{T.discard}</button>
                </>
              ) : saved === n ? <span className="dp-saved">{T.saved} {n}</span> : null}
            </div>
          </section>
        </form>
      )}

      {perio && (
        <section className="dp-tp-sec i-perio">
          <span>{T.perio} · {perio.at}</span>
          {prow && layer && info ? <PerioTable row={prow} layer={layer} jaw={info.jaw} /> : <b>{perio.text}</b>}
          <AppLink href={`/admin/patient/${model.patient.id}/parodontograma?exam=${perio.exam}`}>
            {T.openPerio}
          </AppLink>
        </section>
      )}

      {info && n !== null && (onPlan || canBridge) && (
        <section className="dp-tp-sec dp-tp-acts dp-insp-acts">
          {onPlan && (
            <button type="button" className="dp-btn dp-plan" disabled={busy} onClick={() => onPlan(n)}>
              <Icon name="clipboard" /> {T.plan}
            </button>
          )}
          {canBridge && onBridgeFrom && (
            <button type="button" className="dp-btn ghost dp-brfrom" disabled={busy} onClick={() => onBridgeFrom(n)}>
              <Icon name="plus" /> {T.bridgeFrom}
            </button>
          )}
        </section>
      )}

      {n !== null && (
        <details className="dp-tp-hist thist">
          <summary><span className="dp-lbl">{T.history}</span><Icon name="chev-r" /></summary>
          {hist.length
            ? hist.map((h, i) => <div key={i} className="th-r"><span>{h.at}</span>{h.text}</div>)
            : <p className="hint dp-m0">{T.noHistory}</p>}
        </details>
      )}
      {n === null && <div className="dp-tp-empty"><Icon name="tooth" /></div>}
    </div>
  )
}
