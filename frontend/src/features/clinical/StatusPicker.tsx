/* Состояние зуба — сетка кнопок с цветом палитры (08.10, макет): по одной на
   состояние сервера, кроме «здоров» — он и есть «ничего не нажато».
   Повторное нажатие на выбранном снимает состояние (→ `ok`). Одна и та же
   сетка мышью и пальцем: до 08.10 мышью был выпадающий список, пальцем —
   крупные кнопки; два вида одного поля разошлись бы на первой же правке.
   ⛔ Слова и порядок — сервера (`model.states`), цвета — его же палитра. */
const T = { group: 'Starea dintelui' } as const

interface Props {
  states: Record<string, string>
  palette?: Record<string, string> | undefined
  value: string
  disabled?: boolean
  onChange: (state: string) => void
}

export function StatusPicker({ states, palette, value, disabled = false, onChange }: Props) {
  return (
    <div className="dp-st" role="group" aria-label={T.group}>
      {Object.entries(states).filter(([k]) => k !== 'ok').map(([k, v]) => {
        const on = value === k
        return (
          <button key={k} type="button" data-state={k} className={`dp-stb${on ? ' on' : ''}`}
            aria-pressed={on} disabled={disabled} onClick={() => onChange(on ? 'ok' : k)}>
            <i style={{ background: palette?.[k] ?? 'currentColor' }} />
            <span>{v}</span>
          </button>
        )
      })}
    </div>
  )
}
