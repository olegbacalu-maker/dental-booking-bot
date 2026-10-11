import type { Odontogram, ToothInfo } from './chart'
import { useLongPress } from './touch'

/* «Harta dinților» (08.10, макет; коронки — 11.10): плоская карта зубов
   кнопками под вьюпортом — верхний ряд 18…11 | 21…28, нижний 48…41 | 31…38,
   по середине разделитель; молочный ряд, когда он раскрыт, — своими рядами
   между ними. Она решает то, чего не решает 3D: номера 14/15/16 на дуге
   наезжают друг на друга, а здесь каждый зуб — своя кнопка.
   Кнопка — маленькая коронка с окклюзионной стороны и номер со стороны корней
   (сверху у верхних, снизу у нижних, как в панораме 2D). Рисунок — ТОТ ЖЕ SVG
   сервера, что в виде «2D» (`info.svg.occlusal`): поверхности окрашены по
   своим состояниям, целый зуб — по состоянию зуба, коронка и имплант своим
   рисунком, отсутствующий — пунктиром, отметки — ореолом и устьями каналов;
   второго рисовальщика зуба здесь нет (контракт clinical-chart.md). Выбор,
   черновик, гашение фильтром и выбор для моста — теми же классами, что у
   кнопки дуги. Клик — ТОТ ЖЕ выбор, что клик в сцене (`onSelect` рабочего
   стола, в режиме моста — набор опор); цели поверхностей внутри рисунка
   здесь НЕ различаются — поверхность выбирают на дуге, в сцене и крестом
   панели; правая кнопка и долгое нажатие — меню зуба.
   ⚠️ Один и тот же SVG стоит в документе дважды, когда открыт вид «ocluzal»
   (дуга и карта): его `id` градиента и обтравки повторяются, браузер берёт
   первый — у одного зуба в одном состоянии они одинаковы, поэтому рисунок
   верен. Рисунок с другим содержимым под тем же id сломал бы это молча.
   ⛔ Цвета — палитра сервера; ряды — `model.arches` (порядок экрана, справа
   пациента — слева), подпись кнопки — `title` сервера. */
const T = {
  title: 'Harta dinților',
  hint: 'Alege un dinte pentru a-l edita',
  right: 'Dreapta pacientului',
  left: 'Stânga pacientului',
  upper: 'Maxilar',
  lower: 'Mandibular',
  milk: 'Dinți de lapte',
} as const

interface Props {
  model: Odontogram
  selected: number | null
  /** набранные для моста (режим «Punte nouă») */
  picked: ReadonlySet<number>
  dirty: ReadonlySet<number>
  dim: ReadonlySet<number>
  onSelect: (n: number) => void
  onMenu?: ((n: number, x: number, y: number) => void) | undefined
}

function MapButton({ n, info, upper, sel, picked, dirty, dim, onSelect, onMenu }: {
  n: number; info: ToothInfo; upper: boolean; sel: boolean; picked: boolean; dirty: boolean; dim: boolean
  onSelect: (n: number) => void
  onMenu?: ((n: number, x: number, y: number) => void) | undefined
}) {
  const press = useLongPress(onMenu ? (x, y) => onMenu(n, x, y) : undefined)
  const cls = `dp-tm-btn${upper ? ' up' : ' low'}${sel ? ' sel' : ''}${picked ? ' pick' : ''}`
    + `${dirty ? ' dirty' : ''}${dim ? ' dim' : ''}${info.state === 'lipsa' ? ' miss' : ''}`
  return (
    <button type="button" className={cls} data-n={n} aria-pressed={sel} aria-label={info.title} title={info.title}
      onClick={() => onSelect(n)}
      onContextMenu={onMenu ? (e) => { e.preventDefault(); onMenu(n, e.clientX, e.clientY) } : undefined}
      {...press}>
      <span className="num">{n}</span>
      {/* рисунок сервера — константа движка, не данные пользователя (заметка в нём не живёт);
          подпись несёт кнопка, у рисунка своя aria-label повторила бы номер */}
      <span className="pic" aria-hidden="true" dangerouslySetInnerHTML={{ __html: info.svg.occlusal }} />
    </button>
  )
}

export function ToothMap({ model, selected, picked, dirty, dim, onSelect, onMenu }: Props) {
  const a = model.arches
  const row = (teeth: number[], upper: boolean, milk = false) => {
    const cut = Math.ceil(teeth.length / 2)
    const half = (xs: number[]) => (
      <div className="dp-tm-q" style={{ gridTemplateColumns: `repeat(${xs.length}, minmax(0, 1fr))` }}>
        {xs.map((n) => {
          const info = model.teeth[String(n)]
          if (!info) return null
          return (
            <MapButton key={n} n={n} info={info} upper={upper} sel={selected === n} picked={picked.has(n)}
              dirty={dirty.has(n)} dim={dim.has(n)} onSelect={onSelect} onMenu={onMenu} />
          )
        })}
      </div>
    )
    return (
      <div className={`dp-tm-row${milk ? ' milk' : ''}`}>
        {half(teeth.slice(0, cut))}
        <i className="dp-tm-mid" />
        {half(teeth.slice(cut))}
      </div>
    )
  }
  return (
    <div className="dp-card dp-tm">
      <div className="dp-tm-h">
        <span className="dp-lbl">{T.title}</span>
        <span className="dp-tm-hint">{T.hint}</span>
      </div>
      <div className="dp-tm-scroll">
        <div className="dp-tm-rows">
          <div className="dp-tm-cap"><span>{T.right}</span><span>{T.upper}</span><span>{T.left}</span></div>
          {row(a.upper, true)}
          {model.milk_open && (
            <>
              <div className="dp-tm-cap"><span /><span>{T.milk}</span><span /></div>
              {row(a.milk_upper, true, true)}
              {row(a.milk_lower, false, true)}
            </>
          )}
          {row(a.lower, false)}
          <div className="dp-tm-cap bottom"><span /><span>{T.lower}</span><span /></div>
        </div>
      </div>
    </div>
  )
}
