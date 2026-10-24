import { useMemo, useRef, type KeyboardEvent } from 'react'
import { modeCount, type ChartMode, type Odontogram } from './chart'

/* Режимы рабочего стола вкладками шапки (Олег 24.10, макет B — на месте
   прежних «Stare dinți | Parodont»). Словарь, подписи и ключи — сервера
   (`model.modes`), цвет метки — его палитра (у «perio» — цвета полосы
   кармана). Число у вкладки — сколько зубов на экране про режим (`modeCount`),
   ноль не печатается, у «Examinare» числа нет: сколько записано — в шапке.
   «Parodonțiu» без осмотра с измерениями выключен и говорит почему.

   Клавиатура: Tab до вкладки, стрелки и Home/End — по вкладкам, Enter/Space —
   выбрать. ⛔ Эти клавиши дальше не идут: рабочий стол ловит стрелки (сосед
   зуба) и Enter (запись черновика) на всём .odop, и без остановки стрелка
   двигала бы выбор зуба, а Enter не нажимал бы вкладку. Горячих букв у
   режимов нет: M O D V L — поверхности. */
const T = {
  label: 'Ce arată vederea',
  all: 'Toți dinții, cu toate înregistrările',
  keys: 'Arată dinții cu: ',
  bridges: 'punte',
  paroNone: 'Pacientul nu are încă o parodontogramă cu măsurători',
  paroTitle: 'Parodontograma din {at} pe gingie: recesiune, pungi, sângerare',
} as const

const MOVE = new Set(['ArrowLeft', 'ArrowRight', 'Home', 'End'])

interface Props {
  model: Odontogram
  /** ключ режима, который экран показывает сейчас */
  value: string
  onPick: (key: string) => void
}

export function ModeTabs({ model, value, onPick }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const modes = useMemo(() => model.modes ?? [], [model.modes])
  const counts = useMemo(() => modes.map((m) => modeCount(model, m)), [model, modes])
  const layer = model.perio_layer ?? null
  if (!modes.length) return null

  const names = (m: ChartMode) => [
    ...m.keys.map((k) => model.states[k] ?? model.marks[k] ?? k),
    ...(m.bridges ? [T.bridges] : []),
  ].join(', ')
  const titleOf = (m: ChartMode) => (m.kind === 'all' ? T.all
    : m.kind === 'perio' ? (layer ? T.paroTitle.replace('{at}', layer.exam.at) : T.paroNone)
      : T.keys + names(m))
  const swatches = (m: ChartMode): string[] => (m.kind === 'perio'
    ? (layer ? [layer.colors.deep, layer.colors.severe] : [])
    : [...new Set(m.keys.map((k) => model.palette?.[k] ?? ''))].filter(Boolean))

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); return }
    if (!MOVE.has(e.key)) return
    e.preventDefault()
    e.stopPropagation()
    const btns = Array.from(box.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
    if (!btns.length) return
    const i = btns.indexOf(document.activeElement as HTMLButtonElement)
    const to = e.key === 'Home' ? 0 : e.key === 'End' ? btns.length - 1
      : (i < 0 ? 0 : (i + (e.key === 'ArrowRight' ? 1 : -1) + btns.length) % btns.length)
    const b = btns[to]
    if (!b) return
    // без прокрутки страницы: ряд вкладок сдвигается сам, по горизонтали
    b.focus({ preventScroll: true })
    const row = box.current
    if (row) {
      if (b.offsetLeft < row.scrollLeft) row.scrollLeft = b.offsetLeft
      else if (b.offsetLeft + b.offsetWidth > row.scrollLeft + row.clientWidth) row.scrollLeft = b.offsetLeft + b.offsetWidth - row.clientWidth
    }
  }

  return (
    <div ref={box} className="dp-tabs dp-odo-modes" role="group" aria-label={T.label} onKeyDown={onKey}>
      {modes.map((m, i) => {
        const on = m.key === value
        const n = counts[i] ?? null
        const sw = swatches(m)
        return (
          <button key={m.key} type="button" data-mode={m.key} className={`dp-tab${on ? ' on' : ''}`} aria-pressed={on}
            disabled={m.kind === 'perio' && layer === null} title={titleOf(m)} onClick={() => onPick(m.key)}>
            {sw.length > 0 && (
              <span className="dp-mode-sw" aria-hidden="true">{sw.map((c) => <i key={c} style={{ background: c }} />)}</span>
            )}
            {m.label}
            {/* пробел — для имени кнопки («Carii 1»); во flex-ряду он не рисуется */}
            {n !== null && n > 0 && <>{' '}<b className="dp-mode-n">{n}</b></>}
          </button>
        )
      })}
    </div>
  )
}
