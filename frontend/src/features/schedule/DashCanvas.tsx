import { useRef } from 'react'
import { Icon, iconName } from '../../components/Icon'
import { clinicNow, clinicTz, nowlineRows, useFitAppts, useFitGrid, waitLabel } from './dashFx'
import type { DashAppt, DashBlock, DashCanvasModel, DashColumn } from './dash'

/* Канва панели дня: колонки врачей, ряды часов, блоки с геометрией.

   ⛔ Экран ЧИТАЮЩИЙ (C26.5.2). Ни диалогов, ни перетаскивания: это C26.5.3.
   Поэтому у ячеек и блоков нет ни обработчиков, ни полей переноса — их
   отсутствие честнее, чем кнопка, которая ничего не делает.
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
}

export function DashCanvas({ model, rail, waitTick, lineTick }: Props) {
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
            <div key={col.key} className="gcol" {...(col.id ? { 'data-dk': col.id } : {})}>
              {col.cells.map((open, i) => (
                /* ⛔ Закрытая ячейка БЕЗ `data-h`: «куда нельзя записать, туда
                   нельзя и перенести». Признак один на клик и на перенос. */
                <div key={model.hours[i]!.h}
                  className={open ? 'gcell' : 'gcell off'}
                  {...(open ? { 'data-h': model.hours[i]!.h } : {})} />
              ))}
              {col.blocks.map((b) => (
                <Block key={b.id} block={b} waitTick={waitTick} />
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

function Block({ block, waitTick }: { block: DashBlock; waitTick: number }) {
  /* ⚠️ Те же множители, что печатал сервер: доли ячейки, ширина делится
     между пересекающимися. Считать позицию «от индекса часа» нельзя — на дне
     со сдвинутым графиком это промахивается (`base_min`). */
  const pos: React.CSSProperties = {
    top: `calc(${block.top}*var(--cell) + 2px)`,
    height: `calc(${block.height}*var(--cell) - 6px)`,
    left: `calc(${block.col}*(100% - 8px)/${block.of} + 4px)`,
    width: `calc((100% - 8px)/${block.of} - 2px)`,
  }

  if (block.kind === 'note') {
    return (
      <div className="gappt gnote" data-appt={block.id} style={pos} title={block.title}>
        <b><Icon name="note" /> {block.label}</b>
      </div>
    )
  }
  return <ApptBlock block={block} pos={pos} waitTick={waitTick} />
}

function ApptBlock(
  { block, pos, waitTick }: { block: DashAppt; pos: React.CSSProperties; waitTick: number },
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
    <div className={`gappt${block.status === 'noshow' ? ' noshow' : ''}`}
      data-appt={block.id} style={{ ...pos, background: block.bg, borderLeft: `5px solid ${block.bar}` }}
      title={block.title}>
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
