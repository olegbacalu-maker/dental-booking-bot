import type { CSSProperties } from 'react'
import { surfaceLetter, surfaceName, type Odontogram, type ToothInfo } from '../chart'
import type { ToothDraft } from '../useChart'
import { BigTooth } from './BigTooth'

/* Вкладка «Suprafețe» (24.10): крупный зуб, рядом список пяти поверхностей с
   состоянием из черновика, под ними кисть. Список — то, чем был крест MODVL
   (C22, 08.10): кнопка выбирает поверхность, с кистью красит её, повтор той же
   кистью снимает; имя кнопки — буква и название («M mezial»), состояние —
   словом сервера рядом (подсказкой — тоже). Буквы M/O/D/V/L заняты
   поверхностями и на клавиатуре — их ловит рабочий стол.
   Кисть (11.10): кариес и пломба ставятся ТОЛЬКО по поверхностям; список
   состояний — сервера (`surface_states`), цвета — его палитра. Зуб с
   состоянием на весь зуб (коронка, имплант…) поверхностей не красит; старая
   запись «carie/obturatie без поверхностей» — строкой с выбором. */
const T = {
  surfaces: 'Suprafețe',
  brush: 'Pensulă',
  inHand: 'în mână',
  brushOff: 'Apasă „Carie” sau „Obturație” — pensula rămâne în mână până o lași',
  brushOn: 'Pensula „{s}” este în mână: apasă pe suprafețele dintelui (aici, pe desen sau în 3D) — pune, a doua apăsare scoate. Esc sau încă o apăsare pe buton — lasă pensula',
  brushNo: 'Dintele are o stare pe tot dintele — suprafețele nu se marchează',
  old: '{s} pe tot dintele, din evidența veche (fără suprafețe)',
  remark: 'Remarchează pe suprafețe',
  del: 'Șterge',
  none: '—',
} as const

interface Props {
  model: Odontogram
  n: number
  info: ToothInfo
  d: ToothDraft
  /** выбранная поверхность рабочего стола */
  sel: string
  brush: string | null
  busy: boolean
  /** состояние про весь зуб — поверхности не красятся */
  whole: boolean
  onSurface: (n: number, letter: string) => void
  onBrush: (k: string | null) => void
  onEdit: (patch: Partial<ToothDraft>) => void
}

export function SurfacesTab({ model, n, info, d, sel, brush, busy, whole, onSurface, onBrush, onEdit }: Props) {
  const oldWhole = model.surface_states.includes(d.state) && Object.keys(d.sfst).length === 0
  return (
    <>
      <div className="dp-sf2">
        <BigTooth model={model} n={n} info={info} sel={sel} sfst={d.sfst} state={d.state} onSurface={onSurface} />
        <div className="dp-sfl" role="group" aria-label={T.surfaces}>
          {Object.keys(model.surfaces).map((k) => {
            const st = d.sfst[k] ?? ''
            const on = k === sel
            const name = surfaceName(k, info.jaw, model.surfaces)
            const word = st ? (model.states[st] ?? st) : ''
            return (
              <button key={k} type="button" data-sf={k}
                className={`dp-sfl-r${on ? ' on' : ''}${st ? ` has sf-${st}` : ''}`}
                aria-pressed={on} title={word ? `${name} · ${word}` : name} onClick={() => onSurface(n, k)}>
                <span className="l" style={st ? { background: model.palette?.[st] } : undefined}>{surfaceLetter(k, info.jaw)}</span>
                {' '}
                <span className="n">{name}</span>
                <span className="s" aria-hidden="true" style={st ? { color: model.palette?.[st] } : undefined}>{word || T.none}</span>
              </button>
            )
          })}
        </div>
      </div>
      <span className="dp-lbl">{T.brush}</span>
      <div className="dp-st dp-brush" role="group" aria-label={T.brush}>
        {model.surface_states.map((s) => {
          const on = brush === s
          const color = model.palette?.[s] ?? 'currentColor'
          return (
            <button key={s} type="button" data-brush={s} className={`dp-stb${on ? ' on' : ''}`}
              style={{ '--brush': color } as CSSProperties}
              aria-pressed={on} disabled={busy || whole} onClick={() => onBrush(s)}>
              <i style={{ background: on ? '#fff' : color }} />
              <span>{on ? `${model.states[s] ?? s} — ${T.inHand}` : model.states[s] ?? s}</span>
            </button>
          )
        })}
      </div>
      {whole
        ? <span className="dp-tp-note">{T.brushNo}</span>
        : brush
          ? <b className="dp-tp-note dp-brush-on" style={{ color: model.palette?.[brush] }}>{T.brushOn.replace('{s}', model.states[brush] ?? brush)}</b>
          : <span className="dp-tp-note">{T.brushOff}</span>}
      {oldWhole && (
        <div className="dp-tp-old" data-old={d.state}>
          <span>{T.old.replace('{s}', model.states[d.state] ?? d.state)}</span>
          <span className="dp-tp-old-acts">
            <button type="button" className="dp-link" onClick={() => onBrush(d.state)}>{T.remark}</button>
            <button type="button" className="dp-link" onClick={() => onEdit({ state: 'ok' })}>{T.del}</button>
          </span>
        </div>
      )}
    </>
  )
}
