import { Icon, iconName } from '../../components/Icon'
import { sparkPoints, waitLabel } from './dashFx'
import type {
  DashAgenda, DashMiniCal, DashOccupancy, DashSub, DashTile,
} from './dash'

/* Правая колонка панели: мини-календарь, повестка, карточка «Azi».

   ⛔ Порядок блоков — решение макета (08-11), а не вкус: перестановка это уже
   редизайн, а здесь перенос поведения.
   ⛔ Колокольчика и «Programări noi din bot» тут НЕТ: оба за `tg_configured()`,
   живого grandfather нет ни у кого, и в конверте их тоже нет. Модель для
   блока, которого не видно ни на одном экране, проверялась бы только тестом.
   ⛔ Экран ЧИТАЮЩИЙ (C26.5.2): строка повестки не открывает карточку —
   диалоги это C26.5.3. Ссылки (месяц, плитка, одонтограмма, «Vezi toate»)
   работают: они обычные адреса. */

const T = {
  agenda: 'Agenda zilei',
  empty: '— nicio programare —',
  all: 'Vezi toate programările ›',
  today: 'Azi',
  odo: 'Odontogramă',
  prev: '‹',
  next: '›',
} as const

interface Props {
  minical: DashMiniCal
  agenda: DashAgenda
  tiles: DashTile[]
  occupancy: DashOccupancy
  /** День экрана: ссылка «смотреть все» ведёт в список ЭТОГО дня. */
  date: string
  /** Метка времени для минут ожидания; меняется раз в минуту. */
  waitTick: number
  onCard: (id: number) => void
}

export function DashRail(
  { minical, agenda, tiles, occupancy, date, waitTick, onCard }: Props,
) {
  return (
    <>
      <MiniCal cal={minical} />
      <Agenda agenda={agenda} date={date} waitTick={waitTick} onCard={onCard} />
      <KpiCard tiles={tiles} occupancy={occupancy} />
    </>
  )
}

/**
 * Месяц полными неделями Пн–Вс.
 *
 * ⛔ Три метки НЕЗАВИСИМЫ и складываются: `oth tdy` — законное сочетание,
 * сегодняшний день в хвосте прошлого месяца. Склей их в одно поле — и такой
 * день перестанет подсвечиваться как сегодняшний.
 * ⚠️ Стрелки — литералы `‹`/`›` (U+2039/U+203A), а не иконки: так на старой
 * странице, оба знака в вшитом подмножестве Inter, и замена на `chev-l`
 * развела бы два экрана визуально. Это решение, а не недосмотр.
 */
function MiniCal({ cal }: { cal: DashMiniCal }) {
  return (
    <div className="mcal">
      <div className="mhead">
        <a href={cal.prev.href}>{T.prev}</a>
        <b>{cal.title}</b>
        <a href={cal.next.href}>{T.next}</a>
      </div>
      <table>
        <tbody>
          <tr>{cal.weekdays.map((w) => <th key={w}>{w}</th>)}</tr>
          {cal.weeks.map((week) => (
            <tr key={week[0]!.date}>
              {week.map((c) => (
                <td key={c.date}>
                  <a className={[c.other && 'oth', c.today && 'tdy', c.selected && 'seld']
                    .filter(Boolean).join(' ')} href={c.href}>{c.day}</a>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Пустой день — ДРУГОЕ дерево, а не пустой список: без счётчика, без списка
 *  и без ссылки «смотреть все». */
function Agenda(
  { agenda, date, waitTick, onCard }: {
    agenda: DashAgenda; date: string; waitTick: number; onCard: (id: number) => void
  },
) {
  if (!agenda.items.length) {
    return (
      <div className="agenda">
        <div className="ag-h"><b>{T.agenda}</b></div>
        <p className="hint dp-ag-empty">{T.empty}</p>
      </div>
    )
  }
  return (
    <div className="agenda">
      <div className="ag-h"><b>{T.agenda}</b><span>{agenda.count} programări</span></div>
      {/* ⛔ `.ag-l` — СТАБИЛЬНЫЙ узел с ключами по id: список прокручивается
          (max-height), и пересоздание контейнера роняло бы прокрутку при
          каждом ответе канала. Старая страница возвращала scrollTop руками
          именно потому, что подмена innerHTML его теряла. */}
      <div className="ag-l">
        {agenda.items.map((it) => {
          const wait = it.wait_since ? waitLabel(it.wait_since, waitTick) : null
          return (
            <div key={it.id} className={`ag-i${it.state === 'past' ? ' past' : ''}`}
              data-appt={it.id} style={{ borderLeftColor: it.bar }}
              onClick={() => onCard(it.id)}>
              <span className="ag-t">{it.time}</span>
              <div className="ag-b">
                <b>{it.name}</b>
                <small>{it.service}</small>
                {wait && <small className={`wait-min${wait.long ? ' long' : ''}`}>{wait.text}</small>}
                {/* ⛔ Кнопка одонтограммы — только у визита С ПАЦИЕНТОМ: у
                    легаси-строки без него ссылка вела бы на `/None/`.
                    ⛔ И всплытие клика она останавливает: строка кликабельна
                    целиком, и без этого одно нажатие делало бы два действия —
                    открывало карточку ЗАОДНО с одонтограммой. */}
                {it.patient_id !== null && (
                  <a className="ag-odo" href={`/admin/patient/${it.patient_id}/odontograma`}
                    onClick={(e) => e.stopPropagation()}>
                    <Icon name="tooth" />{T.odo}
                  </a>
                )}
              </div>
              <span className={`pl-badge ${it.badge.cls}`}>{it.badge.label}</span>
            </div>
          )
        })}
      </div>
      <a className="ag-all" href={`/admin/all?date=${date}`}>{T.all}</a>
    </div>
  )
}

function KpiCard({ tiles, occupancy }: { tiles: DashTile[]; occupancy: DashOccupancy }) {
  return (
    <div className="rkpi">
      <div className="rk-h"><b>{T.today}</b></div>
      {/* ⛔ Плиток ЧЕТЫРЕ или пять: «Prin bot» живёт за tg_configured() и у
          клиники с замороженным ботом не рисуется вовсе. Поэтому список, а не
          набор именованных полей — иначе на её месте была бы пустая плитка. */}
      {tiles.map((t) => (
        <a key={t.key} className={`rk-i${t.cls ? ` ${t.cls}` : ''}`} href={t.href}>
          <span className="ico" style={{ background: t.soft, color: t.tone }}>
            <Icon name={iconName(t.icon)} />
          </span>
          <b>{t.value}</b>
          <span className="rk-l">{t.label}</span>
          <Trend sub={t.sub} />
          <Spark series={t.series} tone={t.tone} />
        </a>
      ))}
      {/* ⚠️ Порядок детей у загрузки ДРУГОЙ: число стоит после подписи и
          переносится на свой ряд — так в макете. */}
      <div className="rk-occ">
        <span className="ico" style={{ background: occupancy.soft, color: occupancy.tone }}>
          <Icon name={iconName(occupancy.icon)} />
        </span>
        <span className="rk-l">{occupancy.label}</span>
        <span className="trend">
          {occupancy.dir && (
            <span className={occupancy.dir}>
              <Icon name={occupancy.dir === 'up' ? 'caret-u' : 'caret-d'} />
            </span>
          )}
          {' '}
          {occupancy.from.label} {occupancy.from.value} › {occupancy.to.label} {occupancy.to.value}
        </span>
        <b>{occupancy.value}%</b>
        <Spark series={occupancy.series} tone={occupancy.tone} />
      </div>
    </div>
  )
}

/**
 * Подпись под цифрой. ⛔ Четыре формы, и свести их к одной нельзя: «столько
 * же, сколько вчера», «на столько-то больше», «вперемешку сегодня» и
 * «было → стало» отвечают на разные вопросы.
 * ⛔ Стрелка идёт по ЗНАКУ разницы, а цвет — по ПОЛЯРНОСТИ, которую посчитал
 * сервер. У неявок они расходятся намеренно: рост неявок — стрелка вверх и
 * КРАСНЫЙ. Возьми цвет из знака — и стрелка позеленела бы на росте неявок.
 */
function Trend({ sub }: { sub: DashSub }) {
  if (sub.kind === 'static' || sub.kind === 'same') {
    return <span className="trend">{sub.text}</span>
  }
  if (sub.kind === 'bot_new') {
    /* ⛔ Класс всегда `up`: это не направление, а «есть новое». */
    return <span className="trend"><span className="up">{sub.new} noi</span> {sub.text}</span>
  }
  return (
    <span className="trend">
      <span className={sub.dir}>
        <Icon name={sub.diff > 0 ? 'caret-u' : 'caret-d'} />
        {' '}{sub.diff > 0 ? `+${sub.diff}` : sub.diff}
      </span>
      {' '}{sub.text}
    </span>
  )
}

/** Ряд за две недели инлайновым SVG — без библиотек: программа ставится одним
 *  exe и работает без интернета. */
function Spark({ series, tone }: { series: number[]; tone: string }) {
  const pts = sparkPoints(series)
  if (!pts) return null
  return (
    <svg className="spark" viewBox="0 0 100 26" width="100%" height="26"
      preserveAspectRatio="none" aria-hidden="true">
      <polygon className="sp-a" points={`0,26 ${pts} 100,26`} style={{ fill: tone }} />
      {/* ⛔ `vector-effect`: без него `preserveAspectRatio="none"` размазал бы
          штрих вместе с координатами. */}
      <polyline className="sp-l" points={pts} vectorEffect="non-scaling-stroke"
        style={{ stroke: tone }} />
    </svg>
  )
}
