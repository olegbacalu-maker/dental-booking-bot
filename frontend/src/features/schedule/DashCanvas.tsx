import { useRef } from 'react'
import { Icon, iconName } from '../../components/Icon'
import { clinicNow, clinicTz, nowlineRows, useFitAppts, useFitGrid, waitLabel } from './dashFx'
import type { DashAppt, DashBlock, DashCanvasModel, DashColumn } from './dash'
import { hourLabel } from './slot'
import { cellAtY, dragOf, type CellRect, type Drag, type Target } from './move'

/* Канва панели дня: колонки врачей, ряды часов, блоки с геометрией.

   Три нажатия, и все три ведут в диалог: блок визита — карточка (C26.5.3-b),
   пустая ячейка — слот (C26.5.3-c), блок заметки — сама заметка (C26.5.3-d).
   Плюс перенос (C26.5.3-f): тащится ЛЮБОЙ блок, которому разрешил СЕРВЕР
   (`movable`), — ⛔ ограничение одними визитами молча отняло бы перенос
   блокировки обеда, а её двигают ровно так же.
   ⛔ Мишень ищется ПО КООРДИНАТЕ внутри колонки, а не по `e.target`: блоки
   лежат ПОВЕРХ ячеек и приходятся им соседями, поэтому бросок на соседний
   визит целится в него, и ячейка под курсором в событии не участвует.
   ⛔ Классы берутся у panel.css как есть: это перенос поведения, а не
   редизайн. Своя вторая раскладка развела бы старую страницу и новую на
   первом же правиле темы. */

const T = {
  empty: 'Zi liberă — clinica este închisă',
  closed: 'Închis',
  outside: 'în afara listei',
  off: 'inactiv',
  full: 'complet',
  prog: 'prog.',
  free: 'liber',
  minutes: 'minute de lucru',
} as const

/** Значок статуса — тот же словарь, что печатает сервер (`_STATUS_ICON`). */
const STATUS_ICON: Record<string, string> = {
  confirmed: 'clock', waiting: 'hourglass', arrived: 'checkin',
  done: 'check', noshow: 'ban',
}

interface Props {
  model: DashCanvasModel
  /** Рельс: `fitGrid` тянет сетку до низа его СОДЕРЖИМОГО. */
  rail: React.RefObject<HTMLDivElement | null>
  /** Метка времени для минут ожидания; меняется раз в минуту. */
  waitTick: number
  /** Метка времени для линии «сейчас»; меняется раз в 30 с. */
  lineTick: number
  /** Открыть карточку визита. ⛔ Только у визита: у заметки карточки не
   *  бывает — `_collect_cards` её пропускает, и диалог у неё СВОЙ. */
  onCard: (id: number) => void
  /** Открыть заметку стойки: полный текст и её единственная кнопка. */
  onNote: (id: number) => void
  /** Открыть пустой час: врач, его имя и «HH:00» — те же три значения, что
   *  принимал легаси-обработчик `openSlot(dk, dname, hh)`. */
  onSlot: (dk: string, name: string, hour: string) => void
  /** Начало броска: `null` — бросок кончился. */
  drag: Drag | null
  /** Подсвеченная ячейка: «колонка|час». */
  hover: string
  onDrag: (d: Drag | null) => void
  onHover: (key: string) => void
  onDrop: (t: Target) => void
  /** Что приехало прямо сейчас: этим блокам ставится `fresh` (C26.5.4). */
  fresh: ReadonlySet<number>
}

export function DashCanvas({ model, rail, waitTick, lineTick, onCard, onSlot, onNote,
  drag, hover, onDrag, onHover, onDrop, fresh }: Props) {
  const body = useRef<HTMLDivElement | null>(null)
  /* ⚠️ Перемер блоков привязан к минутам ожидания не вообще, а только когда
     ожидающие ЕСТЬ: текст «așteaptă N min» вписывается после замера, и блок
     на грани переполняется. В дне без них тик пересчитывал бы классы вхолостую
     — четыре мутации DOM в минуту на неизменном дне, то есть ровно то, от чего
     ушли в 08-20 (поймано сценой браузера 19.09, не проверками). */
  const waits = model.columns.some(
    (c) => c.blocks.some((b) => b.kind === 'appt' && b.wait_since))
  useFitGrid(body, rail, model.hours.length)
  useFitAppts(body, waits ? waitTick : 0, model)

  if (model.empty) {
    return (
      <div className="gridcard dp-freeday">{T.empty}</div>
    )
  }

  const at = clinicNow(clinicTz(), new Date(lineTick))
  const rows = nowlineRows(model.hours.map((h) => h.h), model.date, at)

  return (
    <>
      <div className={`gridhead${model.tight ? ' tight' : ''}`}>
        <div className="gh-time" />
        {model.columns.map((col) => (
          <DocCard key={col.key} col={col} date={model.date} />
        ))}
      </div>
      <div className="gridcard">
        <Band band={model.bands.top} side="gb-top" />
        <div className="gridbody" data-day={model.date} ref={body}>
          <div className="gcol-time">
            {model.hours.map((h) => (
              <div key={h.h} className={h.now ? 'nowh' : undefined}>{h.label}</div>
            ))}
          </div>
          {model.columns.map((col) => (
            <div key={col.key} className="gcol" {...(col.id ? { 'data-dk': col.id } : {})}
              {...(drag && col.id ? dropZone(col.id, onHover, onDrop) : {})}>
              {col.cells.map((open, i) => {
                /* ⛔ Закрытая ячейка БЕЗ `data-h`: «куда нельзя записать, туда
                   нельзя и перенести». Признак ОДИН на класс, на `data-h` и на
                   нажатие: разведи их — и появится ячейка, которая выглядит
                   открытой и молчит в ответ.
                   ⛔ Мишень — это ПАРА «врач + час», а у колонки-сироты врача
                   нет: писать в неё некуда, и сервер говорит то же самое
                   (`cells` сироты пусты). Здесь это сказано ТИПОМ. */
                const h = model.hours[i]!.h
                const dk = open ? col.id : null
                if (!dk) return <div key={h} className="gcell off" />
                return (
                  <div key={h} data-h={h}
                    className={hover === dk + '|' + h ? 'gcell dropzone' : 'gcell'}
                    onClick={() => onSlot(dk, col.name, hourLabel(h))} />
                )
              })}
              {col.blocks.map((b) => (
                <Block key={b.id} block={b} waitTick={waitTick} dk={col.id ?? ''}
                  onCard={onCard} onNote={onNote} onDrag={onDrag}
                  fresh={fresh.has(b.id)} />
              ))}
            </div>
          ))}
          {/* ⚠️ Линия «сейчас» — единственное, что меняется непрерывно, и
              потому её нет в модели: серверная строка с минутами делала бы
              отпечаток живого состояния всегда другим. */}
          {rows !== null
            && <div className="nowline" style={{ top: `calc(${rows}*var(--cell))` }} />}
        </div>
        <Band band={model.bands.bottom} side="gb-bot" />
      </div>
    </>
  )
}

/**
 * Мишень переноса — вся КОЛОНКА, а ячейка под курсором ищется перебором её
 * прямоугольников.
 *
 * ⛔ Не на ячейке, и это не оптимизация: блок визита лежит ПОВЕРХ ячеек и
 * перехватывает событие, а ячейка ему сосед, а не родитель, — повесь
 * обработчик на ячейку, и бросок на соседний визит уходил бы в никуда.
 * ⚠️ Без `preventDefault` браузер не отдаёт `drop` вовсе.
 * ⚠️ `dataTransfer` бывает недоступен (и его нет у события, синтезированного
 * проверкой), поэтому подсветка стоит СНАРУЖИ этого условия.
 */
function dropZone(dk: string, onHover: (key: string) => void,
  onDrop: (t: Target) => void) {
  const at = (e: React.DragEvent<HTMLDivElement>) => {
    const rects: CellRect[] = Array.from(
      e.currentTarget.querySelectorAll<HTMLElement>('.gcell[data-h]'),
    ).map((el) => {
      const r = el.getBoundingClientRect()
      return { h: Number(el.dataset.h), top: r.top, height: r.height }
    })
    return cellAtY(rects, e.clientY)
  }
  return {
    onDragOver: (e: React.DragEvent<HTMLDivElement>) => {
      const cell = at(e)
      if (!cell) { onHover(''); return }
      e.preventDefault()
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
      onHover(dk + '|' + cell.h)
    },
    onDragLeave: () => onHover(''),
    onDrop: (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      const cell = at(e)
      if (cell) onDrop({ dk, min: cell.h * 60 + cell.half })
    },
  }
}

/** Полоска срезанного края. Стоит СНАРУЖИ `.gridbody`: внутри она сдвинула бы
 *  начало координат, от которого блоки считают `top`. */
function Band({ band, side }: { band: { from: string; to: string } | null; side: string }) {
  if (!band) return null
  return <div className={`gband ${side}`} title={`${T.closed} · ${band.from} - ${band.to}`} />
}

function DocCard({ col, date }: { col: DashColumn; date: string }) {
  const sub = [col.spec || ' ', col.off && !col.orphan ? ` · ${T.off}` : ''].join('')
  return (
    <div className="gh-doc">
      <div className={`dcard${col.off ? ' off' : ''}`} style={{ borderLeftColor: col.hue }}>
        <span className="av" style={{ background: col.hue }}>
          {col.photo ? <img src={col.photo} alt="" /> : col.initials}
        </span>
        <div className="nm">
          {col.id
            ? <a href={`/admin/doctor/${col.id}?date=${date}`} title={col.title}>{col.name}</a>
            : <a>{col.name}</a>}
          <small>{col.orphan ? `${T.outside} · ${col.count} ${T.prog}` : sub}</small>
          {!col.orphan && (
            <small className="mt">
              {col.count} {T.prog} · {col.free ? `${T.free} ${col.free}` : T.full}
            </small>
          )}
          {col.occupancy && (
            <div className="occ" title={`${col.occupancy.busy} din ${col.occupancy.cap} ${T.minutes}`}>
              {/* ⚠️ Сотней обрезана только ШИРИНА полосы: само число говорит
                  «130%», и это единственный признак перебронированного дня. */}
              <div className="statbar">
                <div style={{ width: `${Math.min(col.occupancy.pct, 100)}%` }} />
              </div>
              <b>{col.occupancy.pct}%</b>
            </div>
          )}
          {col.relink && <Relink relink={col.relink} date={date} />}
        </div>
        {!col.orphan && (
          <span className="st"
            style={{ background: col.free ? 'var(--green)' : 'var(--text3)' }}
            title={col.free ? `${T.free} ${col.free}` : T.full} />
        )}
      </div>
    </div>
  )
}

/**
 * Единственный вход в «переприкрепить к врачу».
 *
 * ⛔ Обычная форма с 303, а не `fetch`: маршрут `POST /admin/relink` живёт в
 * модуле врачей под HTML-охраной и отвечает редиректом. `fetch` получил бы
 * форму входа как «успех», а маршрута под `/api/` для этого сегодня нет.
 * ⚠️ Колонка-сирота — единственное место в программе, где видно записи
 * врача, которого больше нет в справочнике.
 */
function Relink({ relink, date }: { relink: NonNullable<DashColumn['relink']>; date: string }) {
  return (
    <form method="post" action="/admin/relink" className="dp-relink">
      <input type="hidden" name="old_name" value={relink.name} />
      <input type="hidden" name="back" value={`/admin?date=${date}`} />
      <select name="dk">
        {relink.options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
      <button><Icon name="chev-r" /></button>
    </form>
  )
}

function Block(
  { block, waitTick, dk, onCard, onNote, onDrag, fresh }:
  {
    block: DashBlock; waitTick: number; dk: string
    onCard: (id: number) => void; onNote: (id: number) => void
    onDrag: (d: Drag | null) => void
    fresh: boolean
  },
) {
  /* ⛔ Класс ТОТ ЖЕ, что у легаси (`.gappt.fresh` в panel.css): оформление уже
     лежит в стилях и живёт ВНЕ `.anim` — как раз потому, что эта анимация
     нужна на автообновлении, когда входные уже выключены. */
  const fx = fresh ? ' fresh' : ''
  /* ⚠️ Те же множители, что печатал сервер: доли ячейки, ширина делится
     между пересекающимися. Считать позицию «от индекса часа» нельзя — на дне
     со сдвинутым графиком это промахивается (`base_min`). */
  const pos: React.CSSProperties = {
    top: `calc(${block.top}*var(--cell) + 2px)`,
    height: `calc(${block.height}*var(--cell) - 6px)`,
    left: `calc(${block.col}*(100% - 8px)/${block.of} + 4px)`,
    width: `calc((100% - 8px)/${block.of} - 2px)`,
  }

  /* ⛔ Тащится то, что разрешил СЕРВЕР (`movable`): активная запись из колонки
     настоящего врача. У колонки-сироты `dk` пуст — и это ВТОРОЙ замок на том
     же правиле, потому что мишени у неё тоже нет. */
  const grab = block.movable && dk
    ? {
        draggable: true,
        onDragStart: () => onDrag(dragOf(block, dk)),
        onDragEnd: () => onDrag(null),
      }
    : {}

  if (block.kind === 'note') {
    /* ⚠️ Блок лежит ПОВЕРХ ячейки, но ячейка ему не родитель, а сосед: без
       своего обработчика нажатие уходило бы в `.gcol` и не делало ничего —
       ровно как на легаси-панели, где у заметки курсор-палец и мёртвый клик.
       ⛔ И оно НЕ должно доставать до ячейки под собой: «записать в этот час»
       поверх уже заблокированного часа — не то, что человек нажимал. */
    return (
      <div className={`gappt gnote${fx}`} data-appt={block.id} style={pos}
        title={block.title} onClick={() => onNote(block.id)} {...grab}>
        <b><Icon name="note" /> {block.label}</b>
      </div>
    )
  }
  return <ApptBlock block={block} pos={pos} waitTick={waitTick} onCard={onCard}
    grab={grab} fx={fx} />
}

function ApptBlock(
  { block, pos, waitTick, onCard, grab, fx }: {
    block: DashAppt; pos: React.CSSProperties; waitTick: number
    onCard: (id: number) => void
    grab: Record<string, unknown>
    fx: string
  },
) {
  const ico = block.urgent && block.status === 'confirmed'
    ? 'excl' : STATUS_ICON[block.status] ?? ''
  /* ⚠️ Имя иконки приходит от сервера строкой: неизвестное имя не имеет права
     уронить экран, поэтому оно проходит через `iconName`. */
  /* ⛔ Слово статуса печатается только у НЕ подтверждённого: у подтверждённого
     оно ничего не добавляет, а место в блоке решает, влезет ли имя. */
  const word = block.status === 'confirmed' ? '' : block.status_label
  const wait = block.wait_since ? waitLabel(block.wait_since, waitTick) : null
  return (
    <div className={`gappt${block.status === 'noshow' ? ' noshow' : ''}${fx}`}
      data-appt={block.id} style={{ ...pos, background: block.bg, borderLeft: `5px solid ${block.bar}` }}
      title={block.title} onClick={() => onCard(block.id)} {...grab}>
      {ico && <span className="stt"><Icon name={iconName(ico)} /></span>}
      <b>{block.name} <Icon name={block.source === 'bot' ? 'bot' : 'pen'} /></b>
      <small>{block.time} · {block.dur}′ · {block.service}</small>
      {word && (
        <small className="stw">
          <span className={`stat s-${block.status}`}>{word}</span>
          {wait && <span className={`wait-min${wait.long ? ' long' : ''}`}>{wait.text}</span>}
        </small>
      )}
    </div>
  )
}
