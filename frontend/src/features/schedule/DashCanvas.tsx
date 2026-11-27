import { useRef } from 'react'
import { AppLink } from '../../components/AppLink'
import { noteOrigin } from '../../components/dialog'
import { useFlip } from '../../utils/flip'
import { Icon, iconName } from '../../components/Icon'
import { CELL_MIN, GRID_ZOOMS, clinicNow, clinicTz, nowlineRows, useCardView, useFitAppts, useFitGrid, useOdoButton,
  useGridZoom, waitLabel } from './dashFx'
import type { DashAppt, DashBlock, DashCanvasModel, DashColumn } from './dash'
import { CALL_WORDS } from './desk'
import type { VisitFacts } from './day'
import { FactCols } from './FactCols'
import { settleTile, useTileFx } from './tileFx'
import { freeSpans, hourLabel, spanAt, startIn, type FreeSpan } from './slot'
import { cellAtY, CONTROL, dragOf, dropMinute, endOf, hasControl, hhmm, laneEdges, lanesOf, roomTag, type CellRect, type Drag, type Occupies,
  type Room, type Target } from './move'

/* Канва панели дня: колонки врачей, ряды часов, блоки с геометрией.

   Три нажатия, и все три ведут в диалог: блок визита — карточка (C26.5.3-b),
   пустая ячейка — слот (C26.5.3-c), блок заметки — сама заметка (C26.5.3-d).
   Плюс перенос (C26.5.3-f): тащится ЛЮБОЙ блок, которому разрешил СЕРВЕР
   (`movable`), — ⛔ ограничение одними визитами молча отняло бы перенос
   блокировки обеда, а её двигают ровно так же.
   ⛔ Мишень ищется ПО КООРДИНАТЕ внутри колонки, а не по `e.target`: блоки
   лежат ПОВЕРХ ячеек и приходятся им соседями, поэтому бросок на соседний
   визит целится в него, и ячейка под курсором в событии не участвует.

   Вид — по макету Олега (08.10, design/redesign-2026-10, промпт 1): шапка
   врача ВНУТРИ карточки сетки и липкая сверху; свободный час — настоящая
   кнопка с «+ Programare» при наведении (слово Олега 08.10); нерабочее серым с подписью; блок —
   интервал с чипом «Urgent», имя, услуга, кнопка одонтограммы справа; линия
   «сейчас» с плашкой времени в колонке часов; пустой день — карточка поверх
   сетки. Классы сетки те же, что у старой страницы (`.gridbody`, `.gcol`,
   `.gcell`, `.gappt`, `.nowline`): перенос, пересчёт высоты и стенды живут на
   них. ⚠️ Слово статуса на блоке ОСТАВЛЕНО (в макете его нет): «a venit»,
   «în cabinet», «așteaptă N min» на сетке — работа регистратуры, а не
   украшение; названо в отчёте Олегу. */

const T = {
  empty: 'Zi liberă — clinica este închisă',
  closed: 'Închis',
  outside: 'în afara listei',
  off: 'inactiv',
  offHours: 'Nelucrător',
  full: 'Complet',
  free: 'Liber de la',
  one: 'programare',
  many: 'programări',
  minutes: 'minute de lucru',
  comment: 'Comentariu',
  book: 'Programează',
  at: 'la',
  urgent: 'Urgent',
  odo: 'Deschide odontograma',
  noAppts: 'Nicio programare în această zi',
  room: 'Cabinetul',
  control: 'Control',
  main: 'Principal',
  rooms: 'Cabinetele',
  zoom: 'Scara grilei',
  zoomIn: 'Mărește grila',
  zoomOut: 'Micșorează grila',
  noApptsHint: 'Alege un interval liber din calendar pentru a programa un pacient.',
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
  /** Правая кнопка по визиту: меню исходов у курсора (окно: clientX/Y). */
  onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
  /** Открыть заметку стойки: полный текст и её единственная кнопка. */
  onNote: (id: number) => void
  /** Открыть пустой час: врач, его имя, «HH:00», минута щелчка (по делению
   *  масштаба) и кабинет дорожки — у врача с несколькими кабинетами. */
  onSlot: (dk: string, name: string, hour: string, minute: number, room?: string) => void
  /** Начало броска: `null` — бросок кончился. */
  drag: Drag | null
  /** Куда встанет визит, если бросить сейчас: «колонка|минута от полуночи|дорожка». */
  hover: string
  onDrag: (d: Drag | null) => void
  onHover: (key: string) => void
  onDrop: (t: Target) => void
  /** Что приехало прямо сейчас: этим блокам ставится `fresh` (C26.5.4). */
  fresh: ReadonlySet<number>
  /** У кого сменился статус в последнем конверте: этим блокам ставится
   *  `moved` (06.11). Экран без живого канала его не передаёт. */
  moved?: ReadonlySet<number> | undefined
  /** Кто только что ответил «Vin» ссылкой (Premium): на блоке на миг встаёт галочка. Пометка —
   *  из разницы двух конвертов, как `moved` (`fresh.ts › vinOf`). */
  vin?: ReadonlySet<number> | undefined
  /** Факты карточки визита по id — только у дня ОДНОГО врача (22.10, вариант
   *  A): колонки справа от имени. Нет — карточка как на главной. */
  facts?: Record<string, VisitFacts> | undefined
}

const p2 = (n: number) => String(n).padStart(2, '0')

/** Пустая пометка — одна ссылка: новый `Set` на каждый рендер перезапускал бы
 *  перемер ступеней блоков. */
const NO_MARKS: ReadonlySet<number> = new Set()

export function DashCanvas({ model, rail, waitTick, lineTick, onCard, onCardMenu, onSlot, onNote,
  drag, hover, onDrag, onHover, onDrop, fresh, moved = NO_MARKS, vin = NO_MARKS, facts }: Props) {
  const body = useRef<HTMLDivElement | null>(null)
  /* ⚠️ Перемер блоков привязан к минутам ожидания не вообще, а только когда
     ожидающие ЕСТЬ: текст «așteaptă N min» вписывается после замера, и блок
     на грани переполняется. В дне без них тик пересчитывал бы классы вхолостую
     — четыре мутации DOM в минуту на неизменном дне, то есть ровно то, от чего
     ушли в 08-20 (поймано сценой браузера 19.09, не проверками). */
  const waits = model.columns.some(
    (c) => c.blocks.some((b) => b.kind === 'appt' && b.wait_since))
  const view = useCardView()
  const odo = useOdoButton()
  const [zoom, setZoom] = useGridZoom()
  const scale = GRID_ZOOMS[zoom] ?? GRID_ZOOMS[0]
  const keep = useRef<number | null>(null)
  useFitGrid(body, rail, model.hours.length, scale.cell, keep)
  /* `fresh`, `moved` и `vin` меняют className блока без новой модели — и стёрли бы ступени */
  /* кнопка зуба освобождает место в сжатой строке — ступени перемеряются и на её смене */
  useFitAppts(body, waits ? waitTick : 0, model, odo ? view : `${view}:no-odo`, fresh, moved, zoom, vin)
  /* Блок, сменивший место (перенос — свой или с другого места), доезжает до
     нового сдвигом (07.11, вторая волна): только transform, раскладку и
     ступень сжатия не трогает; на опросе без изменений — ни одного запуска. */
  useFlip(body, model, '.gappt', '--dur', settleTile)
  /* отклик блоков на курсор и перенос, очередь появления на открытии дня */
  useTileFx(body, model.empty ? '' : model.date)

  if (model.empty) {
    return (
      <div className="gridcard dp-freeday">{T.empty}</div>
    )
  }

  const at = clinicNow(clinicTz(), new Date(lineTick))
  const rows = nowlineRows(model.hours.map((h) => h.h), model.date, at)
  /* Пустой день — ни одного ВИЗИТА (заметка стойки днём не считается);
     карточка лежит поверх сетки без событий мыши, ячейки под ней кликабельны. */
  const noAppts = !model.columns.some((c) => c.blocks.some((b) => b.kind === 'appt'))
  const pickZoom = (z: number) => {
    const r = body.current?.getBoundingClientRect()
    const mid = r && r.height > 0 ? (window.innerHeight / 2 - r.top) / r.height : -1
    keep.current = mid >= 0 && mid <= 1 ? mid : null
    setZoom(z)
  }
  /* подпись :05 легла бы на подпись самого часа — её деление остаётся линией */
  const marks: number[] = []
  for (let m = scale.marks; scale.marks && m < 60; m += scale.marks) if (m > 5) marks.push(m)
  const [dropDk, dropAt, dropLane] = drag && hover ? hover.split('|') : []

  return (
    <div className="gridcard">
      {/* Шапка врачей — первая строка карточки, липкая (макет 08.10).
          ⚠️ `.gridcard` с overflow:clip, а не hidden: hidden сделал бы карточку
          контейнером прокрутки, и sticky прилипал бы к ней, а не к окну. */}
      <div className={`gridhead${model.tight ? ' tight' : ''}`}>
        <div className="gh-time">
          <div className="gzoom" role="group" aria-label={T.zoom}>
            <button type="button" aria-label={T.zoomOut} title={T.zoomOut}
              disabled={zoom === 0} onClick={() => pickZoom(zoom - 1)}><Icon name="minus" /></button>
            <button type="button" aria-label={T.zoomIn} title={T.zoomIn}
              disabled={zoom === GRID_ZOOMS.length - 1} onClick={() => pickZoom(zoom + 1)}><Icon name="plus" /></button>
          </div>
        </div>
        {model.columns.map((col) => (
          <DocCard key={col.key} col={col} date={model.date} />
        ))}
      </div>
      <Band band={model.bands.top} side="gb-top" />
      <div className="gridbody" data-day={model.date} data-zoom={zoom} ref={body}>
        <div className="gcol-time">
          {model.hours.map((h) => (
            <div key={h.h} className={h.now ? 'nowh' : undefined}>{h.label}
              {marks.map((m) => (
                <i key={m} className={m % 15 ? 'gm5' : undefined}
                  style={{ top: `${(m / 60) * 100}%` }}>:{p2(m)}</i>
              ))}
            </div>
          ))}
        </div>
        {model.columns.map((col) => {
          /* у врача с несколькими кабинетами свободное, щелчок и бросок считаются внутри дорожки */
          const rooms = col.rooms ?? NO_ROOMS
          const n = rooms.length > 1 ? rooms.length : 1
          /* у врача с дорожкой Control дорожки неравные: края — доли ширины колонки */
          const ctl = hasControl(rooms)
          const edges = laneEdges(rooms)
          const realBy = lanesOf(col.blocks, rooms)
          const seenBy = lanesOf(drawn(col.blocks), rooms)
          /* щелчок по занятой основной дорожке ищет свободную среди ОСНОВНЫХ: в Control
             запись попадает только щелчком по самой полосе Control */
          const mainIdx = rooms.map((r, i) => (r.control ? -1 : i)).filter((i) => i >= 0)
          return (
          <div key={col.key} className="gcol" {...(col.id ? { 'data-dk': col.id } : {})}
            {...(n > 1 ? { 'data-lanes': n } : {})}
            {...(ctl ? { 'data-ctl': '' } : {})}
            {...(drag && col.id ? dropZone(col.id, drag.grab ?? 0, scale.snap, rooms, onHover, onDrop) : {})}>
            {ctl && <LaneLines edges={edges} rooms={rooms} />}
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
              if (!dk) {
                /* подпись «Nelucrător» — на ПЕРВОЙ ячейке закрытого ряда, а не
                   на каждой: ряд читается одним куском; у сироты ряда нет */
                const first = !col.orphan && (i === 0 || col.cells[i - 1] === true)
                return (
                  <div key={h} className="gcell off" aria-hidden="true">
                    {first && <span className="gc-off">{T.offHours}</span>}
                  </div>
                )
              }
              const hh = hourLabel(h)
              /* «+ Programare» — только на свободном отрезке часа. Подсказка меряет
                 отрезки по НАРИСОВАННЫМ блокам (короткий дотянут ниже своей длины), а
                 «занят ли час» и минута записи — по настоящим минутам. */
              const real = realBy.map((lane) => freeSpans(lane, h))
              const seen = seenBy.map((lane) => freeSpans(lane, h))
              const li = seen.findIndex((s) => s.length > 0)
              const first = li >= 0 ? seen[li]![0] : undefined
              const low = first ? thin(first, scale.cell || CELL_MIN) : ''
              return (
                <button key={h} type="button" data-h={h} data-hh={hh}
                  data-free={!first ? 'none' : n === 1 && first.to - first.from === 60 ? 'all' : 'part'}
                  {...(low ? { 'data-thin': low } : {})}
                  className="gcell" style={first ? spanVars(first, li, edges) : undefined}
                  aria-label={`${T.book} ${col.name} ${T.at} ${hh}`}
                  disabled={real.every((s) => !s.length)}
                  onMouseMove={n > 1 || (seen[0]?.length ?? 0) > 1
                    ? (e) => aim(e.currentTarget, e.clientX, e.clientY, seen, edges) : undefined}
                  onClick={(e) => {
                    const at = e.detail ? minuteIn(e.currentTarget, e.clientY) : null
                    /* дорожка под щелчком; в занятой и с клавиатуры — первая свободная */
                    let lane = e.detail && n > 1 ? laneIn(e.currentTarget, e.clientX, edges) : -1
                    if (ctl) {
                      if (lane < 0 || (!rooms[lane]?.control && !real[lane]?.length)) {
                        lane = mainIdx.find((i) => (real[i]?.length ?? 0) > 0) ?? mainIdx[0] ?? 0
                      }
                    } else if (lane < 0 || !real[lane]?.length) lane = real.findIndex((s) => s.length > 0)
                    /* основная дорожка врача с Control занята весь час — окно всё равно
                       открывается: оно скажет «nu are început liber» и предложит Control */
                    const busyMain = ctl && !rooms[lane]?.control
                    const m = startIn(real[lane] ?? [], at, scale.snap)
                      ?? (busyMain ? Math.floor((at ?? 0) / scale.snap) * scale.snap : null)
                    if (m === null) return
                    noteOrigin(e.currentTarget)
                    if (n > 1) onSlot(dk, col.name, hh, m, rooms[lane]?.id)
                    else onSlot(dk, col.name, hh, m)
                  }} />
              )
            })}
            {dropDk === col.id && dropAt && model.base_min !== null && drag && (
              <div className="gdrop" data-at={hhmm(Number(dropAt))} style={{
                top: `calc(${(Number(dropAt) - model.base_min) / 60}*var(--cell))`,
                height: `calc(${drag.dur / 60}*var(--cell))`,
                ...(n > 1 && dropLane ? laneBox(Number(dropLane), edges) : {}),
              }} />
            )}
            {col.blocks.map((b) => (
              <Block key={b.id} block={b} waitTick={waitTick} dk={col.id ?? ''}
                {...(ctl ? { edges } : {})}
                onCard={onCard} onCardMenu={onCardMenu} onNote={onNote} onDrag={onDrag}
                fresh={fresh.has(b.id)} moved={moved.has(b.id)} vin={vin.has(b.id)} lanes={n > 1} odo={odo}
                /* колонки фактов рассчитаны на блок во всю колонку — в дорожке их нет */
                facts={n > 1 ? undefined : facts?.[String(b.id)]} date={model.date} />
            ))}
          </div>
          )
        })}
        {/* ⚠️ Линия «сейчас» — единственное, что меняется непрерывно, и
            потому её нет в модели: серверная строка с минутами делала бы
            отпечаток живого состояния всегда другим.
            ⚠️ Время плашки — АТРИБУТОМ, а не текстом внутри: стенд панели
            считает мутации линии отдельно от остальных по узлу `.nowline`, а
            смена текста вложенного узла легла бы в «мигание». */}
        {rows !== null
          && <div className="nowline" data-now={`${p2(at.hh)}:${p2(at.mm)}`}
            style={{ top: `calc(${rows}*var(--cell))` }} />}
        {noAppts && (
          <div className="dp-empty-day" aria-hidden="true">
            <div><b>{T.noAppts}</b><span>{T.noApptsHint}</span></div>
          </div>
        )}
      </div>
      <Band band={model.bands.bottom} side="gb-bot" />
    </div>
  )
}

/** Блоки колонки с длиной, какой они НАРИСОВАНЫ: короткий визит дотянут ниже
 *  своих минут, и ячейка под хвостом щелчка не получит. */
function drawn(blocks: DashBlock[]): Occupies[] {
  return blocks.map((b) => ({
    id: b.id, min: b.min, busy: b.busy,
    dur: Math.max(b.dur || 60, Math.round(b.height * 60)),
    ...(b.kind === 'appt' && b.room_id !== undefined ? { room_id: b.room_id } : {}),
  }))
}

const NO_ROOMS: readonly Room[] = []

function spanVars(s: FreeSpan, lane: number, edges: number[]): React.CSSProperties {
  return { '--ft': s.from / 60, '--fb': 1 - s.to / 60,
    '--fl': edges[lane] ?? 0, '--fr': 1 - (edges[lane + 1] ?? 1) } as React.CSSProperties
}

/** Дорожка под координатой по краям `edges` (у Control дорожки неравные). */
function laneIn(el: HTMLElement, x: number, edges: number[]): number {
  const r = el.getBoundingClientRect()
  const n = edges.length - 1
  if (r.width <= 0) return -1
  const f = (x - r.left) / r.width
  const i = edges.findIndex((e, k) => k > 0 && f < e) - 1
  return Math.max(0, Math.min(n - 1, i < 0 ? n - 1 : i))
}

function laneBox(lane: number, edges: number[]): React.CSSProperties {
  const n = edges.length - 1
  const a = edges[lane] ?? 0
  const w = (edges[lane + 1] ?? 1) - a
  /* равные дорожки — прежняя запись (её читают проверки), неравные — долями */
  if (Math.abs(w - 1 / n) < 1e-9 && Math.abs(a - lane / n) < 1e-9) {
    return { left: `calc(${lane}*(100% - 8px)/${n} + 4px)`, right: 'auto',
      width: `calc((100% - 8px)/${n} - 2px)` }
  }
  return { left: `calc(${a}*(100% - 8px) + 4px)`, right: 'auto',
    width: `calc(${w}*(100% - 8px) - 2px)` }
}

/** Линии между дорожками и подложка полосы Control (у колонки с Control). */
function LaneLines({ edges, rooms }: { edges: number[]; rooms: readonly Room[] }) {
  return (
    <>
      {rooms.map((r, i) => (r.control
        ? <i key={r.id} className="gctl-bg" aria-hidden="true"
            style={{ left: `${(edges[i] ?? 0) * 100}%` }} />
        : null))}
      {edges.slice(1, -1).map((e) => (
        <i key={e} className="glane-line" aria-hidden="true" style={{ left: `${e * 100}%` }} />
      ))}
    </>
  )
}

/** Низкий отрезок: слово подсказки не влезает — остаётся плюс или одна рамка. */
function thin(s: FreeSpan, cellPx: number): 'plus' | 'bar' | '' {
  const px = ((s.to - s.from) / 60) * cellPx - 6
  return px < 9 ? 'bar' : px < 18 ? 'plus' : ''
}

/** Минута часа (дробная) под координатой; `null` — ячейка без высоты (среда без раскладки). */
function minuteIn(el: HTMLElement, y: number): number | null {
  const r = el.getBoundingClientRect()
  if (r.height <= 0) return null
  return Math.max(0, Math.min(59.9, ((y - r.top) / r.height) * 60))
}

/* Рамка подсказки встаёт на свободный отрезок под курсором. Мимо React: это
   оформление наведения, и рендер на каждое движение мыши был бы лишним. */
function aim(el: HTMLElement, x: number, y: number, lanes: FreeSpan[][], edges: number[]): void {
  const at = minuteIn(el, y)
  const n = lanes.length
  let lane = n > 1 ? laneIn(el, x, edges) : 0
  if (lane < 0 || !lanes[lane]?.length) lane = lanes.findIndex((s) => s.length > 0)
  const s = at === null || lane < 0 ? null : spanAt(lanes[lane] ?? [], at)
  if (!s) return
  el.style.setProperty('--ft', String(s.from / 60))
  el.style.setProperty('--fb', String(1 - s.to / 60))
  el.style.setProperty('--fl', String(edges[lane] ?? 0))
  el.style.setProperty('--fr', String(1 - (edges[lane + 1] ?? 1)))
  const low = thin(s, el.offsetHeight)
  if (low) el.dataset.thin = low
  else delete el.dataset.thin
}

/**
 * Мишень переноса — вся КОЛОНКА, а минута начала ищется по координате среди
 * прямоугольников её открытых ячеек.
 *
 * Не на ячейке, и это не оптимизация: блок визита лежит ПОВЕРХ ячеек и
 * перехватывает событие, а ячейка ему сосед, а не родитель, — повесь
 * обработчик на ячейку, и бросок на соседний визит уходил бы в никуда.
 * Без `preventDefault` браузер не отдаёт `drop` вовсе. `dataTransfer` бывает
 * недоступен (и его нет у события, синтезированного проверкой), поэтому
 * указатель места стоит СНАРУЖИ этого условия.
 */
function dropZone(dk: string, grab: number, snap: number, rooms: readonly Room[],
  onHover: (key: string) => void, onDrop: (t: Target) => void) {
  const n = rooms.length > 1 ? rooms.length : 1
  const edges = laneEdges(rooms)
  const lane = (e: React.DragEvent<HTMLDivElement>) =>
    n > 1 ? laneIn(e.currentTarget, e.clientX, edges) : -1
  const at = (e: React.DragEvent<HTMLDivElement>) => {
    const rects: CellRect[] = Array.from(
      e.currentTarget.querySelectorAll<HTMLElement>('.gcell[data-h]'),
    ).map((el) => {
      const r = el.getBoundingClientRect()
      return { h: Number(el.dataset.h), top: r.top, height: r.height }
    })
    /* курсор обязан стоять над открытым часом: закрытое мишенью не бывает */
    return cellAtY(rects, e.clientY) ? dropMinute(rects, e.clientY, grab, snap) : null
  }
  return {
    onDragOver: (e: React.DragEvent<HTMLDivElement>) => {
      const min = at(e)
      if (min === null) { onHover(''); return }
      e.preventDefault()
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
      const li = lane(e)
      onHover(dk + '|' + min + (li >= 0 ? '|' + li : ''))
    },
    onDragLeave: () => onHover(''),
    onDrop: (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      const min = at(e)
      const room = rooms[lane(e)]?.id
      if (min !== null) onDrop({ dk, min, ...(room ? { room } : {}) })
    },
  }
}

/** Полоска срезанного края. Стоит СНАРУЖИ `.gridbody`: внутри она сдвинула бы
 *  начало координат, от которого блоки считают `top`. */
function Band({ band, side }: { band: { from: string; to: string } | null; side: string }) {
  if (!band) return null
  return <div className={`gband ${side}`} title={`${T.closed} · ${band.from} - ${band.to}`} />
}

/**
 * Шапка колонки врача (макет 08.10): аватар-кольцо цветом врача, имя и
 * специализация, строка «N programări · Liber de la HH:MM» и полоска
 * загрузки цветом врача. Цвет — `hue` врача из модели, как и был у полосы
 * слева; заливки аватара больше нет — кольцо.
 * ⚠️ Полоса обрезана сотней только ШИРИНОЙ: подсказка говорит «130%», и это
 * единственный признак перебронированного дня.
 * 12.10 (слово Олега): фото ведёт на страницу врача, как имя, — ссылкой с
 * `tabIndex=-1` и `aria-hidden`: для клавиатуры и читалки ссылка остаётся
 * одна. Кабинет (поле «Cabinet» профиля, `room` модели) — значком двери в
 * начале строки под именем; пусто — строки кабинета нет.
 */
function DocCard({ col, date }: { col: DashColumn; date: string }) {
  const spec = [col.spec || ' ', col.off && !col.orphan ? ` · ${T.off}` : ''].join('')
  const pct = col.occupancy ? Math.min(col.occupancy.pct, 100) : 0
  const href = col.id ? `/admin/doctor/${col.id}?date=${date}` : ''
  const face = col.photo ? <img src={col.photo} alt="" /> : col.initials
  const rooms = col.rooms ?? NO_ROOMS
  const ctl = hasControl(rooms)
  const edges = ctl ? laneEdges(rooms) : []
  return (
    <div className={`gh-doc${ctl ? ' has-ctl' : ''}`}>
      <div className={`dcard${col.off ? ' off' : ''}`}>
        <div className="dc-top">
          {href
            ? <AppLink className="av" href={href} tabIndex={-1} aria-hidden="true" style={{ borderColor: col.hue }}>{face}</AppLink>
            : <span className="av" style={{ borderColor: col.hue }}>{face}</span>}
          <div className="nm">
            {href
              ? <AppLink href={href} title={col.title}>{col.name}</AppLink>
              : <a>{col.name}</a>}
            {/* ⚠️ Плотный режим (окно ≤1440 или >4 врачей) прячет эту строку
                целиком — специализация уходит первой. Кабинет остаётся: на
                ноутбуке клиники (1366) он нужнее всего, поэтому у строки с
                кабинетом прячется только `.dc-spec` (app.css). */}
            <small className={!col.orphan && col.room ? 'has-room' : undefined}>{col.orphan
              ? `${T.outside} · ${col.count} ${col.count === 1 ? T.one : T.many}`
              : col.room
                ? <><span className="dc-room" title={`${(col.rooms?.length ?? 0) > 1 ? T.rooms : T.room} ${col.room}`}><Icon name="door" />{col.room}</span>
                    <span className="dc-spec">{' · '}{spec}</span></>
                : spec}</small>
            {col.relink && <Relink relink={col.relink} date={date} />}
          </div>
        </div>
        {!col.orphan && (
          <div className="dc-load">
            <small className="mt">{col.count} {col.count === 1 ? T.one : T.many}</small>
            <small className={`dc-free${col.free ? '' : ' full'}`}>
              {col.free ? `${T.free} ${col.free}` : T.full}
            </small>
            <div className="track"
              title={col.occupancy
                ? `${col.occupancy.busy} din ${col.occupancy.cap} ${T.minutes} · ${col.occupancy.pct}%` : undefined}>
              <i style={{ width: `${pct}%`, background: col.hue }} />
            </div>
          </div>
        )}
      </div>
      {/* подписи дорожек над колонкой: у врача с Control видно, где основная и где полоса */}
      {ctl && (
        <div className="dc-lanes" aria-hidden="true">
          {rooms.map((r, i) => (
            <span key={r.id} className={r.control ? 'ctl' : undefined}
              style={{ left: `${(edges[i] ?? 0) * 100}%`, width: `${((edges[i + 1] ?? 1) - (edges[i] ?? 0)) * 100}%` }}>
              {r.control ? T.control : r.id ? r.name : T.main}
            </span>
          ))}
        </div>
      )}
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
  { block, waitTick, dk, onCard, onCardMenu, onNote, onDrag, fresh, moved, vin, lanes, odo, facts, date, edges }:
  {
    block: DashBlock; waitTick: number; dk: string
    /** Края неравных дорожек (колонка с Control); нет — дорожки равные. */
    edges?: number[] | undefined
    onCard: (id: number) => void; onNote: (id: number) => void
    onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
    onDrag: (d: Drag | null) => void
    fresh: boolean
    moved: boolean
    vin: boolean
    lanes: boolean
    odo: boolean
    facts: VisitFacts | undefined
    date: string
  },
) {
  /* ⛔ Класс ТОТ ЖЕ, что у легаси (`.gappt.fresh` в panel.css): оформление уже
     лежит в стилях и живёт ВНЕ `.anim` — как раз потому, что эта анимация
     нужна на автообновлении, когда входные уже выключены. */
  const fx = (fresh ? ' fresh' : '') + (moved ? ' moved' : '') + (vin ? ' vin' : '')
  /* ⚠️ Те же множители, что печатал сервер: доли ячейки, ширина делится
     между пересекающимися. Считать позицию «от индекса часа» нельзя — на дне
     со сдвинутым графиком это промахивается (`base_min`). */
  /* у блока короче получаса зазор уже: при зазоре длинного от пяти минут не
     осталось бы ничего */
  const tight = block.height < 0.5
  const pos: React.CSSProperties = {
    top: `calc(${block.top}*var(--cell) + ${tight ? 1 : 2}px)`,
    height: `calc(${block.height}*var(--cell) - ${tight ? 2 : 6}px)`,
    ...(edges ? unequal(block.col, block.of, edges) : {
      left: `calc(${block.col}*(100% - 8px)/${block.of} + 4px)`,
      width: `calc((100% - 8px)/${block.of} - 2px)`,
    }),
  }

  /* ⛔ Тащится то, что разрешил СЕРВЕР (`movable`): активная запись из колонки
     настоящего врача. У колонки-сироты `dk` пуст — и это ВТОРОЙ замок на том
     же правиле, потому что мишени у неё тоже нет. */
  const grab = block.movable && dk
    ? {
        draggable: true,
        onDragStart: (e: React.DragEvent<HTMLElement>) => {
          const d = dragOf(block, dk)
          onDrag(d && { ...d, grab: e.clientY - e.currentTarget.getBoundingClientRect().top })
        },
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
        title={block.title} onClick={(e) => { noteOrigin(e.currentTarget); onNote(block.id) }} {...grab}>
        <b><Icon name="note" /> {block.label}</b>
      </div>
    )
  }
  return <ApptBlock block={block} pos={pos} waitTick={waitTick} onCard={onCard}
    onCardMenu={onCardMenu} grab={grab} fx={fx + (block.room_id === CONTROL ? ' gctl' : '')} facts={facts} date={date}
    vin={vin}
    /* в полосе Control метка лишняя: полоса подписана в шапке, слово — в подсказке */
    room={lanes && block.room_id !== CONTROL ? block.room ?? '' : ''} odo={odo} />
}


/** Место блока в неравных дорожках: сервер даёт `col` из `of` равных долей
 *  (`canvas._lane_places`: дорожка × одновременные в ней), здесь — по краям. */
function unequal(col: number, of: number, edges: number[]): React.CSSProperties {
  const lanes = edges.length - 1
  const per = Math.max(1, Math.round(of / lanes))
  const i = Math.min(lanes - 1, Math.floor(col / per))
  const j = col - i * per
  const a = edges[i] ?? 0
  const w = ((edges[i + 1] ?? 1) - a) / per
  return { left: `calc(${a + j * w}*(100% - 8px) + 4px)`, width: `calc(${w}*(100% - 8px) - 2px)` }
}


function ApptBlock(
  { block, pos, waitTick, onCard, onCardMenu, grab, fx, facts, date, room, odo, vin }: {
    block: DashAppt; pos: React.CSSProperties; waitTick: number
    vin: boolean
    onCard: (id: number) => void
    onCardMenu?: ((id: number, x: number, y: number) => void) | undefined
    grab: Record<string, unknown>
    fx: string
    facts: VisitFacts | undefined
    date: string
    room: string
    odo: boolean
  },
) {
  /* Срочность — чипом в строке интервала (макет), а не только цветом: чип
     со значком читается и без подложки. ⛔ Только у НЕ завершённого визита —
     то же правило, что у повестки: срочность про то, что визита ждут. */
  const urgent = block.urgent && block.status === 'confirmed'
  const ico = urgent ? 'excl' : STATUS_ICON[block.status] ?? ''
  /* ⚠️ Имя иконки приходит от сервера строкой: неизвестное имя не имеет права
     уронить экран, поэтому оно проходит через `iconName`. */
  /* ⛔ Слово статуса печатается только у НЕ подтверждённого: у подтверждённого
     оно ничего не добавляет, а место в блоке решает, влезет ли имя. */
  /* …кроме «nu poate veni» ответом ссылкой (Premium): это не статус, а сигнал стойке — звонить */
  const cant = block.status === 'confirmed' && block.call === 'cant'
  const word = cant ? CALL_WORDS.cantWord : block.status === 'confirmed' ? '' : block.status_label
  const wait = block.wait_since ? waitLabel(block.wait_since, waitTick) : null
  /* Завершённый визит — приглушённый, без цвета категории (09.10, разбор:
     «Durere acută» после приёма оставалась красной, и важное с сделанным
     выглядели одинаково). Цвет категории — про то, что визита ждут. */
  const done = block.status === 'done'
  const bg = done ? 'var(--line2)' : block.bg
  const bar = done ? 'var(--text3)' : block.bar
  /* блок дотянут ниже своей длины — хвост под настоящим концом бледнее */
  const real = block.dur > 0 && block.height * 60 > block.dur + 0.5
    ? Math.round((block.dur / (block.height * 60)) * 100) : 0
  return (
    <div className={`gappt${block.status === 'noshow' ? ' noshow' : ''}${done ? ' done' : ''}${urgent ? ' urg' : ''}${facts ? ' has-vf' : ''}${fx}`}
      data-appt={block.id} data-st={block.status}
      style={{ ...pos, background: bg, borderLeft: `5px solid ${bar}`,
        '--bar': bar } as React.CSSProperties}
      title={block.comment ? `${block.title}\n${T.comment}: ${block.comment}` : block.title}
      onClick={(e) => { noteOrigin(e.currentTarget); onCard(block.id) }}
      onContextMenu={(e) => { e.preventDefault(); onCardMenu?.(block.id, e.clientX, e.clientY) }}
      {...grab}>
      {real > 0 && <i className="gtail" style={{ top: `${real}%` }} />}
      {/* Обе раскладки в разметке сразу, вид выбирает panel.css по
          `<html data-card>`: строка интервала (.gl1 с .gtm) первой у «времени
          впереди», имя первым у «имени впереди» (.gt — начало с длительностью).
          ⛔ Карандаш «записано вручную» снят (03.10): с заморозкой бота так
          записано всё, значок ничего не различал. Бот остался — он отличает. */}
      <span className="gl1">
        <span className="gtm">{block.time}–{endOf(block.time, block.dur)}</span>
        {urgent && <span className="chip urg"><Icon name="excl" />{T.urgent}</span>}
        {word && <span className={`stat s-${cant ? 'cant' : block.status}`}>{word}</span>}
        {wait && <span className={`wait-min${wait.long ? ' long' : ''}`}>{wait.text}</span>}
      </span>
      {ico && <span className="stt"><Icon name={iconName(ico)} /></span>}
      {/* значок «есть комментарий» (03.10, просьба Олега): текст — в подсказке
          блока и в карточке по нажатию */}
      <b data-t={block.time}>{fx.includes(' gctl') && <span className="groom gctl-tag" title={T.control}>C</span>}{room && <span className="groom" title={`${T.room} ${room}`}>{roomTag(room)}</span>}{block.name}{block.source === 'bot' && <> <Icon name="bot" /></>}
        {block.comment && <> <Icon name="chat" /></>}</b>
      <small><span className="gt">{block.time} · {block.dur}′ · </span>{block.service}</small>
      {/* колонки фактов — только у дня врача (`facts`); стоят абсолютно в
          своей полосе и ступени блока не меняют (app.css › `.vf`) */}
      {facts && <FactCols x={facts} date={date} />}
      {/* Кнопка одонтограммы в блоке (макет): только у визита С ПАЦИЕНТОМ, иначе
          ссылка вела бы на `/None/`, и только пока клиника её не выключила
          (`odo`; одонтограмма остаётся в меню карточки). ⛔ Всплытие клика
          останавливает — строка кликабельна целиком; `draggable=false` — иначе
          браузер тащил бы ссылку вместо блока. */}
      {odo && block.pid !== null && (
        <AppLink className="apact" href={`/admin/patient/${block.pid}/odontograma`}
          aria-label={`${T.odo}: ${block.name}`} title={T.odo} draggable={false}
          onClick={(e) => e.stopPropagation()}>
          <Icon name="tooth" />
        </AppLink>
      )}
      {/* слой эффектов блока: блик при наведении и события статуса; оформление — panel.css › .gfx */}
      <i className="gfx" aria-hidden="true"><i /></i>
      {/* «Vin» ссылкой только что (пометка `vin`, таймер экрана): галочка в углу на миг. Стоит
          абсолютно — ни места, ни ступени блока не меняет */}
      {vin && <i className="gvin" title={CALL_WORDS.vinHint} aria-hidden="true"><Icon name="check" /></i>}
    </div>
  )
}
