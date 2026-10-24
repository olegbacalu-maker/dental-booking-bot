import type { CSSProperties, MouseEvent } from 'react'
import { surfaceLetter, type Odontogram, type ToothInfo } from '../chart'

/* Крупный зуб панели (24.10, макет B; Олег: «схему MODVL заменяет крупный
   зуб»). Рисунок — тот же SVG сервера вида сверху, что у карты и дуги
   (`info.svg.occlusal`, с целями поверхностей `data-s`): второго рисовальщика
   зуба в клиенте нет, клик по полю — та же пара жестов, что у рисунка на дуге
   (`onSurface` → `useChart.pickSurface`: выбрать, с кистью — покрасить).
   ⭐ Рисунок сервера — СОХРАНЁННОЕ состояние, а кисть правит ЧЕРНОВИК. Поле,
   у которого черновик разошёлся с записью, красится поверх цветом палитры
   сервера (или «стёрто», если состояние снято): цель `data-s` — это ровно
   поле сервера, обтравленное контуром, поэтому заливка ложится в его форму.
   Цвет едет переменной (`--bt-M`…), правило — в app.css: своей геометрии и
   своих цветов здесь нет. Совпадающие с записью поля не трогаются — рисунок
   без правки выглядит ровно как на карте.
   Буквы по сторонам — как стоит рисунок: вид сверху у сервера — щёчной
   стороной вверх, нижняя дуга перевёрнута (`teeth_svg._occ_wrap`; держит
   `test_odontogram_api.suite_panel`), мезиальная — `info.mez` сервера.
   Рисунок — цель мыши и пальца; клавиатура идёт списком поверхностей рядом
   (у него те же действия), поэтому сам рисунок скрыт от чтеца экрана. */
const T = {
  stale: 'Desenul arată starea salvată. După „Salvează”: {s}',
} as const

interface Props {
  model: Odontogram
  n: number
  info: ToothInfo
  /** выбранная поверхность — состояние рабочего стола (её выбирают и в сцене) */
  sel: string
  /** состояния поверхностей из черновика */
  sfst: Record<string, string>
  /** состояние зуба в черновике — если оно не то, что нарисовано, рисунок гаснет */
  state: string
  onSurface: (n: number, letter: string) => void
}

export function BigTooth({ model, n, info, sel, sfst, state, onSurface }: Props) {
  const vTop = info.jaw === 'sus'
  const mLeft = info.mez === 'left'
  const side: Record<string, string> = {
    V: vTop ? 't' : 'b', L: vTop ? 'b' : 't', M: mLeft ? 'l' : 'r', D: mLeft ? 'r' : 'l',
  }
  /* поле, где черновик разошёлся с записью: цвет состояния или «стёрто» */
  const vars: Record<string, string> = {}
  for (const k of Object.keys(model.surfaces)) {
    const now = sfst[k] ?? ''
    if (now === (info.sfst[k] ?? '')) continue
    vars[`--bt-${k}`] = now ? (model.palette?.[now] ?? 'currentColor') : 'var(--bt-clear)'
    vars[`--bt-${k}-o`] = now ? 'var(--bt-paint-o)' : 'var(--bt-clear-o)'
  }
  const stale = state !== info.state
  const onPick = (e: MouseEvent<HTMLDivElement>) => {
    const t = e.target as Element
    const letter = typeof t.closest === 'function' ? t.closest('[data-s]')?.getAttribute('data-s') : null
    if (letter) onSurface(n, letter)
  }
  return (
    <div className={`dp-bt${stale ? ' stale' : ''}`} data-sel={sel} data-n={n} style={vars as CSSProperties}>
      {(['V', 'L', 'M', 'D'] as const).map((k) => (
        <span key={k} className={`dp-bt-l ${side[k]}`} aria-hidden="true">{surfaceLetter(k, info.jaw)}</span>
      ))}
      {/* рисунок сервера — константа движка, не данные пользователя (как у карты зубов) */}
      <div className="dp-bt-pic" aria-hidden="true" onClick={onPick} dangerouslySetInnerHTML={{ __html: info.svg.occlusal }} />
      {stale && <span className="dp-bt-stale">{T.stale.replace('{s}', model.states[state] ?? state)}</span>}
    </div>
  )
}
