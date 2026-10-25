import { Icon } from '../../components/Icon'
import type { Odontogram } from './chart'
import type { CompareState } from './useCompare'

/* Колонка «Comparație cu vizita» (волна 2, 25.10) — на месте панели зуба, пока
   открыто сравнение (`useCompare`): выбор визита, «Era / Acum» (что рисуют
   виды), список изменившихся зубов было → стало словами сервера. Щелчок по
   строке подсвечивает зуб в видах; правки здесь нет — пока сравнение открыто,
   рабочий стол её выключает. Визит без истории зубов (до обновления) —
   «нет данных», а не догадка. */
const T = {
  title: 'Comparație cu vizita',
  visit: 'Vizita',
  noData: ' — fără date',
  shows: 'Ce arată formula',
  was: 'Era',
  now: 'Acum',
  loading: 'Se încarcă…',
  none: (d: string, since: string) => since
    ? `Nu există date despre starea dinților la ${d}: istoricul formulei dentare se păstrează din ${since}.`
    : `Nu există date despre starea dinților la ${d}.`,
  same: (d: string) => `Nicio modificare a dinților față de vizita din ${d}.`,
  changed: (k: number, d: string) => `${k === 1 ? 'Un dinte modificat' : `${k} dinți modificați`} de la vizita din ${d}`,
  readOnly: 'Cât timp comparați, formula nu se modifică.',
  close: 'Închide comparația',
} as const

interface Props {
  model: Odontogram
  cmp: CompareState
}

export function ComparePanel({ model, cmp }: Props) {
  const visits = model.visits ?? []
  const d = cmp.data
  const date = d?.visit.date ?? visits.find((v) => v.id === cmp.visit)?.date ?? ''
  return (
    <div className="dp-card insp dp-tp dp-cmp" aria-label={T.title}>
      <div className="dp-tp-head">
        <b className="dp-tp-num dp-cmp-ic"><Icon name="clock" /></b>
        <div className="dp-tp-who">
          <label className="dp-lbl" htmlFor="dp-cmp-visit">{T.title}</label>
          <select id="dp-cmp-visit" className="dp-fld" aria-label={T.visit} value={cmp.visit ?? ''}
            onChange={(e) => cmp.pick(Number(e.target.value))}>
            {visits.map((v) => <option key={v.id} value={v.id}>{v.label}{v.known ? '' : T.noData}</option>)}
          </select>
        </div>
      </div>
      {d?.known && d.changes.length > 0 && (
        <div className="dp-tp-sec dp-cmp-side">
          <div className="dp-seg" role="group" aria-label={T.shows}>
            <button type="button" className={cmp.side === 'was' ? 'on' : ''} aria-pressed={cmp.side === 'was'}
              onClick={() => cmp.setSide('was')}>{T.was} · {date}</button>
            <button type="button" className={cmp.side === 'now' ? 'on' : ''} aria-pressed={cmp.side === 'now'}
              onClick={() => cmp.setSide('now')}>{T.now}</button>
          </div>
        </div>
      )}
      <div className="dp-tp-sec dp-tp-body dp-cmp-body" aria-live="polite" aria-busy={cmp.busy}>
        {!d ? <p className="hint dp-m0">{T.loading}</p>
          : !d.known ? <p className="dp-cmp-none">{T.none(date, d.since)}</p>
            : !d.changes.length ? <p className="hint dp-m0">{T.same(date)}</p>
              : (
                <>
                  <p className="dp-lbl dp-m0">{T.changed(d.changes.length, date)}</p>
                  <ul className="dp-cmp-list">
                    {d.changes.map((x) => (
                      <li key={x.n}>
                        <button type="button" className="dp-cmp-row" data-n={x.n} aria-current={cmp.focus === x.n ? 'true' : undefined}
                          onClick={() => cmp.setFocus(cmp.focus === x.n ? null : x.n)}>
                          <b className="dp-cmp-n">{x.n}</b>
                          <span className="dp-cmp-was">{x.was}</span>
                          <Icon name="chev-r" />
                          <span className="dp-cmp-now">{x.now}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
      </div>
      <div className="dp-tp-sec dp-tp-foot dp-cmp-foot">
        <button type="button" className="dp-btn" onClick={cmp.close}><Icon name="close" /> {T.close}</button>
        <span className="hint dp-m0">{T.readOnly}</span>
      </div>
    </div>
  )
}
