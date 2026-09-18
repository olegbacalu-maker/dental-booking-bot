import { Icon } from '../../components/Icon'
import { Tooth } from './Tooth'
import { ToothForm } from './ToothForm'
import { JAW_RO, bridgeOf, surfaceLetter, type Odontogram, type ToothSave, type View } from './chart'

/* Постоянный инспектор детальной страницы (.insp): номер и челюсть, мост,
   рисунок выбранного зуба (тот же серверный SVG, клик по поверхности
   выбирает её в форме), форма, история. Модалки здесь нет НАМЕРЕННО: она
   закрывает собой дугу, а смысл экрана — видеть зуб и соседей сразу. */
const T = {
  title: 'Dinte selectat',
  bridge: 'Punte',
  role: 'rol',
  delBridge: 'Șterge puntea',
  confirmDel: 'Ștergeți puntea?',
  history: 'Istoric',
  noHistory: '— fără înregistrări —',
} as const

interface Props {
  model: Odontogram
  n: number | null
  view: View
  busy: boolean
  /** Ключ формы: зуб и счётчик сохранений — свежая модель даёт свежую форму. */
  formKey: string
  sel: string
  onSel: (letter: string) => void
  onSave: (n: number, body: ToothSave) => void
  onDelBridge: (bid: number) => void
}

export function ToothInspector({ model, n, view, busy, formKey, sel, onSel, onSave, onDelBridge }: Props) {
  const info = n !== null ? model.teeth[String(n)] : undefined
  const inBr = n !== null ? bridgeOf(model, n) : null
  const hist = n !== null ? (model.history[String(n)] ?? []) : []
  return (
    <div className="fcard insp">
      <div className="insp-t">{T.title}</div>
      <div className="insp-n"><b>{n ?? '—'}</b><span>{info ? JAW_RO[info.jaw] : ''}</span></div>
      {inBr && (
        <div className="i-bridge">
          <span>
            {T.bridge} {inBr.bridge.teeth[0]?.[0]}-{inBr.bridge.teeth[inBr.bridge.teeth.length - 1]?.[0]}
            {inBr.bridge.material ? ` (${inBr.bridge.material})` : ''} - {T.role}: {model.bridge_roles[inBr.role] ?? inBr.role}
          </span>
          <form onSubmit={(e) => { e.preventDefault(); if (window.confirm(T.confirmDel)) onDelBridge(inBr.bridge.id) }}>
            <button className="pl-btn" disabled={busy}>{T.delBridge}</button>
          </form>
        </div>
      )}
      <div className="insp-pic" data-jaw={info?.jaw} data-mez={info?.mez}>
        <span className="lb lb-v">V</span>
        <span className="lb lb-l">{info ? surfaceLetter('L', info.jaw) : 'L'}</span>
        <span className="lb lb-m">M</span>
        <span className="lb lb-d">D</span>
        {info && n !== null && (
          <Tooth n={n} info={info} view={view} onSurface={(_n, letter) => onSel(letter)} onSelect={() => undefined} />
        )}
      </div>
      {info && n !== null && (
        <ToothForm key={formKey} model={model} n={n} info={info} busy={busy} sel={sel} onSel={onSel} onSave={onSave} />
      )}
      <div className="thist">
        {n !== null && (hist.length ? (
          <>
            <div className="th-t">{T.history}</div>
            {hist.map((h, i) => <div key={i} className="th-r"><span>{h.at}</span>{h.text}</div>)}
          </>
        ) : <p className="hint dp-m0">{T.noHistory}</p>)}
      </div>
      {n === null && <Icon name="tooth" />}
    </div>
  )
}
