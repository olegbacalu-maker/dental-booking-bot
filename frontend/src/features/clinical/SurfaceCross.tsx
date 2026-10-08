import { surfaceLetter, surfaceName, type Odontogram, type ToothInfo } from './chart'

/* Крест поверхностей 3×3 (08.10, макет «Stare dinți»): V сверху, O в центре,
   снизу P у верхней челюсти / L у нижней, M и D по бокам — M ВСЕГДА со
   стороны средней линии (`info.mez` считает сервер по квадранту, как у
   подписей рисунка зуба). Клик — та же пара жестов, что у рисунка: выбрать
   поверхность, повторный клик по выбранной крутит её состояние
   (`onSurface` → `useChart.pickSurface`). Бейдж буквы красится состоянием
   ЭТОЙ поверхности из черновика цветом палитры сервера; «выбрано» — рамкой
   и подложкой: два признака, два смысла. Справа — название и пояснение. */
const T = {
  group: 'Suprafețe',
  hint: {
    V: 'Fața dinspre obraz și buze.',
    M: 'Fața dinspre linia mediană.',
    O: 'Suprafața de masticație.',
    D: 'Fața opusă liniei mediane.',
    L: 'Fața dinspre limbă.',
    P: 'Fața dinspre palat.',
  } as Record<string, string>,
} as const

interface Props {
  model: Odontogram
  n: number
  info: ToothInfo
  /** выбранная поверхность — состояние рабочего стола (её выбирают и с рисунка) */
  sel: string
  /** состояния поверхностей из черновика */
  sfst: Record<string, string>
  onSurface: (n: number, letter: string) => void
}

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)

export function SurfaceCross({ model, n, info, sel, sfst, onSurface }: Props) {
  const mezLeft = info.mez === 'left'
  const area: Record<string, string> = {
    V: '1 / 2', O: '2 / 2', L: '3 / 2',
    M: mezLeft ? '2 / 1' : '2 / 3', D: mezLeft ? '2 / 3' : '2 / 1',
  }
  const order = Object.keys(model.surfaces)
  const cur = sel in model.surfaces ? sel : 'O'
  const curSt = sfst[cur] ?? ''
  return (
    <div className="dp-sfx">
      <div className="dp-sfx-grid" role="group" aria-label={T.group}>
        {order.map((k) => {
          const st = sfst[k] ?? ''
          const on = k === cur
          const name = surfaceName(k, info.jaw, model.surfaces)
          return (
            <button key={k} type="button" data-s={k}
              className={`dp-sf${on ? ' on' : ''}${st ? ` has sf-${st}` : ''}`}
              style={{ gridArea: area[k] ?? 'auto' }}
              aria-pressed={on} title={st ? `${name} · ${model.states[st] ?? st}` : name}
              onClick={() => onSurface(n, k)}>
              <span className="l" style={st ? { background: model.palette?.[st] } : undefined}>{surfaceLetter(k, info.jaw)}</span>
              {' '}
              <span className="n">{name}</span>
            </button>
          )
        })}
      </div>
      <div className="dp-sfx-info">
        <b>{cap(surfaceName(cur, info.jaw, model.surfaces))}</b>
        <span>{T.hint[surfaceLetter(cur, info.jaw)] ?? ''}</span>
        {curSt && <em style={{ color: model.palette?.[curSt] }}>{model.states[curSt] ?? curSt}</em>}
      </div>
    </div>
  )
}
