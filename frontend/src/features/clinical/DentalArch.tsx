import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { Legend } from './Legend'
import { Tooth } from './Tooth'
import type { Bridge, Odontogram, View } from './chart'

/* Обе дуги, молочный ряд и легенда — та же разметка, что у старой страницы
   (.arch-wrap, .arch, .arch-mid, details.milk, .tleg). Показывается ОДИН
   вид: переключает состояние экрана, а не CSS по data-view — второй набор
   из 52 SVG в дереве не нужен, данные обоих видов уже в модели.
   Скобки мостов меряются по кнопкам ВИДИМОГО ряда после раскладки. */
const T = {
  upper: 'Maxilar',
  lower: 'Mandibular',
  milk: 'Dentiție temporară (dinți de lapte)',
  occHint: 'Suprafața vestibulară este spre exteriorul arcadei; cea linguală/palatinală — spre mijloc.',
  bridge: 'punte',
  bridgeTitle: 'Punte',
} as const

interface Bracket {
  key: number
  left: number
  width: number
  top: number
  label: string
  title: string
}

function sameBrackets(a: Bracket[], b: Bracket[]): boolean {
  return a.length === b.length && a.every((x, i) => {
    const y = b[i]
    return Boolean(y) && x.key === y!.key && x.left === y!.left && x.width === y!.width
      && x.top === y!.top && x.label === y!.label
  })
}

interface RowProps {
  model: Odontogram
  teeth: number[]
  arcs: number[]
  view: View
  lower: boolean
  milk: boolean
  selected: number | null
  picked: ReadonlySet<number>
  dirty: ReadonlySet<number>
  onSelect: (n: number) => void
  onSurface?: (n: number, letter: string) => void
  onHover?: (n: number, el: HTMLElement | null) => void
  onMenu?: (n: number, x: number, y: number) => void
}

/** Мосты, все зубы которых стоят в этом ряду. */
function bridgesIn(model: Odontogram, teeth: number[]): Bridge[] {
  return model.bridges.filter((b) => b.teeth.every((t) => teeth.includes(t[0])))
}

function ArchRow({ model, teeth, arcs, view, lower, milk, selected, picked, dirty, onSelect, onSurface, onHover, onMenu }: RowProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [brackets, setBrackets] = useState<Bracket[]>([])
  const mine = useMemo(() => (milk ? [] : bridgesIn(model, teeth)), [model, teeth, milk])
  const occ = view === 'ocluzal'

  /* Скобка (acoladă): по кнопкам ряда, как drawBridges старой страницы.
     ⚠️ Место под скобку (.br-room) даёт CSS до замера: класс стоит в
     разметке, а не навешивается после — иначе padding сдвинул бы offsetTop
     уже после того, как его прочли. --arc двигает зуб transform-ом, которого
     offsetTop не видит, — поправка та же. */
  useLayoutEffect(() => {
    const row = ref.current
    if (!row || !mine.length) {
      setBrackets((cur) => (cur.length ? [] : cur))
      return
    }
    const measure = () => {
      const btn: Record<string, HTMLElement> = {}
      row.querySelectorAll<HTMLElement>('.tooth-btn').forEach((b) => { btn[b.dataset.n ?? ''] = b })
      const out: Bracket[] = []
      for (const br of mine) {
        const bs = br.teeth.map((t) => btn[String(t[0])]).filter((b): b is HTMLElement => Boolean(b))
        if (bs.length !== br.teeth.length) continue
        const L = Math.min(...bs.map((b) => b.offsetLeft))
        const R = Math.max(...bs.map((b) => b.offsetLeft + b.offsetWidth))
        if (R - L < 8) continue
        const arcOf = (b: HTMLElement) => {
          const v = parseFloat(b.style.getPropertyValue('--arc'))
          return Number.isNaN(v) ? 0 : v
        }
        const top = lower
          ? Math.max(...bs.map((b) => b.offsetTop + b.offsetHeight + arcOf(b))) + 2
          : Math.min(...bs.map((b) => b.offsetTop + arcOf(b))) - 14
        const first = br.teeth[0]?.[0] ?? 0
        const last = br.teeth[br.teeth.length - 1]?.[0] ?? 0
        out.push({
          key: br.id, left: L, width: R - L, top,
          label: br.material || T.bridge,
          title: `${T.bridgeTitle} ${first}-${last}${br.material ? ` (${br.material})` : ''}`,
        })
      }
      setBrackets((cur) => (sameBrackets(cur, out) ? cur : out))
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(row)
    return () => ro?.disconnect()
  }, [mine, lower, view])

  return (
    <div ref={ref} className={`arch${occ ? ' occ' : ''}${lower ? ' lower' : ''}${mine.length ? ' br-room' : ''}`}>
      {teeth.map((n, i) => {
        const info = model.teeth[String(n)]
        if (!info) return null
        return (
          <Tooth
            key={n}
            n={n}
            info={info}
            view={view}
            lower={lower}
            arc={occ ? (arcs[i] ?? 0) : 0}
            selected={selected === n}
            picked={picked.has(n)}
            dirty={dirty.has(n)}
            onSelect={onSelect}
            {...(onSurface ? { onSurface } : {})}
            {...(onHover ? { onHover } : {})}
            {...(onMenu ? { onMenu } : {})}
          />
        )
      })}
      {brackets.map((b) => (
        <div
          key={b.key}
          className={`br-arc${lower ? ' lo' : ''}`}
          style={{ left: b.left, width: b.width, top: b.top }}
          title={b.title}
        >
          <span>{b.label}</span>
        </div>
      ))}
    </div>
  )
}

interface Props {
  model: Odontogram
  view: View
  selected: number | null
  /** Зубы, отмеченные в режиме «Punte nouă». */
  picked?: ReadonlySet<number>
  /** Зубы с незаписанной правкой. */
  dirty?: ReadonlySet<number>
  onSelect: (n: number) => void
  onSurface?: (n: number, letter: string) => void
  onHover?: (n: number, el: HTMLElement | null) => void
  onMenu?: (n: number, x: number, y: number) => void
  legend?: boolean
}

const NONE: ReadonlySet<number> = new Set()

export function DentalArch({ model, view, selected, picked = NONE, dirty = NONE, onSelect, onSurface, onHover, onMenu, legend = true }: Props) {
  const occ = view === 'ocluzal'
  const rowProps = {
    model, view, selected, picked, dirty, onSelect,
    ...(onSurface ? { onSurface } : {}), ...(onHover ? { onHover } : {}), ...(onMenu ? { onMenu } : {}),
  }
  return (
    <>
      <div className={`odo-view v-${view}`}>
        <div className="arch-wrap">
          <ArchRow {...rowProps} teeth={model.arches.upper} arcs={model.arc.upper} lower={false} milk={false} />
          <div className="arch-mid"><b>{T.upper}</b><i></i><b>{T.lower}</b></div>
          <ArchRow {...rowProps} teeth={model.arches.lower} arcs={model.arc.lower} lower milk={false} />
        </div>
        {occ && <p className="hint occ-hint">{T.occHint}</p>}
      </div>
      <details className="milk" open={model.milk_open}>
        <summary><Icon name="milk" /> {T.milk}</summary>
        <div className={`odo-view v-${view}`}>
          <div className="arch-wrap">
            <ArchRow {...rowProps} teeth={model.arches.milk_upper} arcs={model.arc.milk_upper} lower={false} milk />
            <div className="arch-mid"><b>{T.upper}</b><i></i><b>{T.lower}</b></div>
            <ArchRow {...rowProps} teeth={model.arches.milk_lower} arcs={model.arc.milk_lower} lower milk />
          </div>
        </div>
      </details>
      {legend && (
        <div className={`tleg odo-view v-${view}`}>
          <Legend items={occ ? model.legend.occlusal : model.legend.frontal} />
        </div>
      )}
    </>
  )
}
