import { useId, useState } from 'react'
import { Icon } from '../../components/Icon'
import { JAW_RO, bridgeOf, type Odontogram } from './chart'
import { DiagnosticTab } from './panel/DiagnosticTab'
import { PanelTabs, type Tab } from './panel/PanelTabs'
import { SurfacesTab } from './panel/SurfacesTab'
import { TreatmentTab } from './panel/TreatmentTab'
import type { ToothDraft } from './useChart'

/* Панель зуба «Dintele N» (24.10, макет B Олега; до того — секции одна под
   другой по макету 08.10, ещё раньше — инспектор `ToothInspector` + форма
   `ToothForm`): шапка с крупным номером, названием и стороной (слова
   сервера), вкладки Suprafețe / Diagnostic / Tratament / Notițe / Istoric и
   «Salvează» со строкой состояния внизу — на ЛЮБОЙ вкладке. Содержимое то же,
   что было секциями (`panel/*`); новое — крупный зуб вместо креста MODVL и
   позиции плана этого зуба (`model.plan`, только чтение).
   Модалки здесь нет НАМЕРЕННО: она закрывает собой карту, а смысл экрана —
   видеть зуб и соседей сразу. Всё, что умеет контекстное меню, есть и
   здесь. Форма КОНТРОЛИРУЕМАЯ (C22): черновик живёт в useChart — его правят
   ещё клик по зубу в сцене, на дуге, по крупному зубу и меню, а форма его
   только показывает и меняет через onEdit; поэтому смена вкладки ничего не
   теряет (вкладки размонтируются, черновик — нет). Намерение уезжает явно
   (карта поверхностей и список отметок всегда, state0 — как показали).
   Пальцем (B7 · планшет) панель — шторка поверх карты: классы `insp`,
   `insp-close` держат те же правила app.css, что и раньше. */
const T = {
  title: 'Dintele',
  pick: 'Alege un dinte',
  close: 'Închide',
  doctor: 'Medic',
  doctorNone: 'Medic —',
  note: 'Notiță (opțional)',
  noHistory: '— fără înregistrări —',
  save: 'Salvează',
  saveAll: 'Salvează tot ({n})',
  discard: 'Renunță',
  unsaved: 'Modificări nesalvate',
  also1: 'și dintele {t}',
  alsoN: 'și dinții {t}',
  pend1: 'Nesalvat: dintele {t}',
  pendN: 'Nesalvat: dinții {t}',
  saved1: 'Salvat: dintele {t}',
  savedN: 'Salvat: dinții {t}',
} as const

/** «dintele 16» или «dinții 16, 21» — по числу зубов */
const teethWords = (one: string, many: string, t: readonly number[]) =>
  (t.length === 1 ? one : many).replace('{t}', t.join(', '))

interface Props {
  model: Odontogram
  n: number | null
  busy: boolean
  /** Выбранная поверхность — состояние рабочего стола (её выбирают и из сцены). */
  sel: string
  /** Клик по полю крупного зуба или по строке списка: выбрать поверхность; с кистью — покрасить её. */
  onSurface: (n: number, letter: string) => void
  /** Кисть (11.10): состояние, которым красят поверхности, и её переключатель. */
  brush: string | null
  onBrush: (k: string | null) => void
  draft: ToothDraft | null
  dirty: boolean
  onEdit: (patch: Partial<ToothDraft>) => void
  /** Все зубы с несохранённой правкой (по возрастанию): подвал пишет их разом. */
  pending: readonly number[]
  /** Запись ВСЕХ черновиков («Salvează tot», волна 2). */
  onSave: () => void
  /** Сброс черновика выбранного зуба. */
  onDiscard: () => void
  onDelBridge: (bid: number) => void
  onBridgeFrom?: ((n: number) => void) | undefined
  /** позиция плана с этого зуба (01.10): то же, что в меню зуба */
  onPlan?: ((n: number) => void) | undefined
  /** Закрыть панель (пальцем она — шторка поверх карты); мышью кнопки не видно. */
  onClose?: (() => void) | undefined
  /** Зубы, записанные последним нажатием «Salvează», — для строки состояния. */
  saved: readonly number[] | null
}

export function ToothPanel({
  model, n, busy, sel, onSurface, brush, onBrush, draft: d, dirty, onEdit: edit, pending, onSave, onDiscard, onDelBridge,
  onBridgeFrom, onPlan, onClose, saved,
}: Props) {
  /* вкладка — свойство экрана: держится, пока врач ходит от зуба к зубу */
  const [tab, setTab] = useState<Tab>('sf')
  const id = useId()
  const info = n !== null ? model.teeth[String(n)] : undefined
  const inBr = n !== null ? bridgeOf(model, n) : null
  const hist = n !== null ? (model.history[String(n)] ?? []) : []
  const cur = info && sel in model.surfaces ? sel : 'O'
  /* состояние про весь зуб (коронка, имплант…) — поверхности не красятся */
  const whole = Boolean(d && d.state !== 'ok' && d.state in model.tooth_states)
  /* счётчики: у «Tratament» — позиции, что ещё ждут работы (активные —
     перечислением сервера), у «Istoric» — строки летописи */
  const counts = {
    tr: n !== null ? (model.plan?.[String(n)] ?? []).filter((it) => it.active).length : 0,
    is: hist.length,
  }

  return (
    <div className="dp-card insp dp-tp" aria-label={n !== null ? `${T.title} ${n}` : T.title} data-tab={tab}>
      <div className="dp-tp-head">
        {info && n !== null ? (
          <>
            <b className="dp-tp-num">{n}</b>
            <div className="dp-tp-who">
              <span className="dp-lbl">{T.title} {n}</span>
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

      {info && n !== null && d && (
        <form className="dp-tp-form" onSubmit={(e) => { e.preventDefault(); onSave() }}>
          <PanelTabs tab={tab} onTab={setTab} counts={counts} id={id} />
          <div className="dp-tp-sec dp-tp-body" role="tabpanel" id={`${id}-p`} aria-labelledby={`${id}-t-${tab}`}>
            {tab === 'sf' && (
              <SurfacesTab model={model} n={n} info={info} d={d} sel={cur} brush={brush} busy={busy} whole={whole}
                onSurface={onSurface} onBrush={onBrush} onEdit={edit} />
            )}
            {tab === 'dg' && <DiagnosticTab model={model} n={n} jaw={info.jaw} d={d} busy={busy} whole={whole} onEdit={edit} />}
            {tab === 'tr' && (
              <TreatmentTab model={model} n={n} milk={info.milk} busy={busy} inBr={inBr}
                onPlan={onPlan} onBridgeFrom={onBridgeFrom} onDelBridge={onDelBridge} />
            )}
            {tab === 'nt' && (
              <>
                <label className="dp-lbl" htmlFor={`dp-doc-${n}`}>{T.doctor}</label>
                <select id={`dp-doc-${n}`} className="dp-fld" value={d.doctor} onChange={(e) => edit({ doctor: e.target.value })}>
                  <option value="">{T.doctorNone}</option>
                  {model.doctors.map((doc) => <option key={doc} value={doc}>{doc}</option>)}
                </select>
                <label className="dp-lbl" htmlFor={`dp-note-${n}`}>{T.note}</label>
                <textarea id={`dp-note-${n}`} className="dp-fld" rows={4} maxLength={120} value={d.note}
                  onChange={(e) => edit({ note: e.target.value })} />
              </>
            )}
            {tab === 'is' && (
              <div className="thist dp-tp-log">
                {hist.length
                  ? hist.map((h, i) => <div key={i} className="th-r"><span>{h.at}</span>{h.text}</div>)
                  : <p className="hint dp-m0">{T.noHistory}</p>}
              </div>
            )}
          </div>
          <Foot n={n} busy={busy} dirty={dirty} pending={pending} saved={saved} onDiscard={onDiscard} />
        </form>
      )}
      {n === null && <div className="dp-tp-empty"><Icon name="tooth" /></div>}
      {/* зуб не выбран (шторку закрыли), а черновики есть — записать их можно и так */}
      {n === null && pending.length > 0 && (
        <Foot n={n} busy={busy} dirty={false} pending={pending} saved={saved} onDiscard={onDiscard} onSave={onSave} />
      )}
    </div>
  )
}

/* Подвал панели (волна 2, 25.10; Олег: «сначала всю работу и потом
   сохранить»): одна кнопка пишет черновики ВСЕХ зубов — «Salvează» при одном,
   «Salvează tot (N)» при нескольких; поштучной записи нет. Без черновиков
   кнопка выключена (как Enter рабочего стола): сервер пишет строку летописи на
   КАЖДУЮ запись зуба, и пустое пересохранение оставляло бы «Dinte N: …» ни о
   чём. «Renunță» — черновик выбранного зуба (как Esc); прочие несохранённые
   зубы названы рядом. В форме кнопка — submit; без выбранного зуба (`onSave`)
   — обычная кнопка. */
function Foot({ n, busy, dirty, pending, saved, onDiscard, onSave }: {
  n: number | null
  busy: boolean
  dirty: boolean
  pending: readonly number[]
  saved: readonly number[] | null
  onDiscard: () => void
  onSave?: () => void
}) {
  const others = pending.filter((x) => x !== n)
  return (
    <div className="dp-tp-sec dp-tp-foot">
      <button className="dp-btn pri" type={onSave ? 'button' : 'submit'} disabled={busy || !pending.length} onClick={onSave}>
        <Icon name="save" /> {pending.length > 1 ? T.saveAll.replace('{n}', String(pending.length)) : T.save}
      </button>
      <div className="dp-tp-status" aria-live="polite">
        {dirty && (
          <>
            <span className="dp-draft">{T.unsaved}</span>
            <button type="button" className="dp-link" onClick={onDiscard}>{T.discard}</button>
          </>
        )}
        {others.length > 0 && (
          <span className="dp-draft dp-tp-also">{dirty ? teethWords(T.also1, T.alsoN, others) : teethWords(T.pend1, T.pendN, others)}</span>
        )}
        {!pending.length && saved?.length ? <span className="dp-saved">{teethWords(T.saved1, T.savedN, saved)}</span> : null}
      </div>
    </div>
  )
}
