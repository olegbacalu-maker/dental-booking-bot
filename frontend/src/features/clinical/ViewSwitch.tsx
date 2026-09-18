import type { View } from './chart'

/* Переключатель вида — та же разметка (.viewsw), что у старой страницы. */
const T = { frontal: 'Vedere frontală', ocluzal: 'Vedere ocluzală', group: 'Vedere' } as const

export function ViewSwitch({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="viewsw" role="group" aria-label={T.group}>
      {(['frontal', 'ocluzal'] as const).map((v) => (
        <button key={v} type="button" data-v={v} className={view === v ? 'on' : ''} aria-pressed={view === v} onClick={() => onChange(v)}>
          {T[v]}
        </button>
      ))}
    </div>
  )
}
