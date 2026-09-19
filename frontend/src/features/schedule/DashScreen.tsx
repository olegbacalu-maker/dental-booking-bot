import { useRef } from 'react'
import { Icon } from '../../components/Icon'
import { useLive } from '../../hooks/useLive'
import { DashCanvas } from './DashCanvas'
import { DashRail } from './DashRail'
import { useClockTick } from './dashFx'
import { livePath, type DashModel } from './dash'

/**
 * Панель дня (`/admin`) на React — C26.5.2.
 *
 * ⭐ Единственный ЖИВОЙ экран клиента: остальные освежаются переходом и
 * ответом действия, а этот обязан узнавать о брони со второго рабочего места
 * сам. Держит это `useLive`: канал данных, 204 «не менялось», отпечаток от
 * того же, что отправлено.
 * ⛔ Экран ЧИТАЮЩИЙ. Диалоги, запись по клику в пустой час и перетаскивание —
 * C26.5.3; пока их нет, подсказка говорит правду и ведёт в старую панель, а
 * не обещает действий, которых экран не умеет.
 * ⛔ Шапка дня (`_date_nav`) и баннер `?msg=` печатает СЕРВЕР, снаружи узла:
 * на `/admin` приземляется `no_access` со всей программы, и увидеть его надо
 * при первой отрисовке, а не после первого ответа канала.
 */
const T = {
  hint: 'Panoul nou este deocamdată doar pentru citit: se actualizează singur, '
    + 'dar programările se fac în varianta clasică.',
  legacy: 'Deschideți varianta clasică',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
  retry: 'Reîncearcă',
  stopped: 'Panoul nu se mai actualizează singur. Reîncărcați pagina.',
} as const

/* Два разных периода, как и в старом коде: линия «сейчас» — раз в 30 с,
   минуты ожидания — раз в минуту. Общий тик перерисовывал бы одно из них
   вдвое чаще нужного. */
const LINE_MS = 30_000
const WAIT_MS = 60_000

interface Props {
  /** День из адреса; пусто — сегодня (решает сервер). */
  date?: string
}

export function DashScreen({ date = '' }: Props) {
  const rail = useRef<HTMLDivElement | null>(null)
  /* ⚠️ Версия — та, с которой загружена ЭТА страница: разошлась с ответом,
     значит exe обновили под открытой вкладкой, и новые данные нельзя
     вклеивать в старый код. Поверхность — `react`: узнав от сервера, что по
     адресу теперь живёт старая страница, вкладка перезагрузится сама. */
  const version = document.body.dataset.v ?? ''
  const { state, retry } = useLive<DashModel>(livePath(date), 'react', version)
  const lineTick = useClockTick(LINE_MS)
  const waitTick = useClockTick(WAIT_MS)

  if (state.status === 'failed') {
    /* ⚠️ Свой отказ, а не общий `LoadFailed`: тому нужен `ApiError`, а у
       живого канала исходов четыре и исключений среди них нет. Слова и
       разметка — те же. */
    return (
      <section className="dp-react-root">
        <div className="banner err" role="alert">{T.offline}</div>
        <p className="dp-actions">
          <button type="button" className="savebtn" onClick={retry}>
            <Icon name="refresh" /> {T.retry}
          </button>
          <a href="/admin?ui=legacy">{T.legacy}</a>
        </p>
      </section>
    )
  }
  if (state.status === 'stopped') {
    return (
      <section className="dp-react-root">
        <div className="banner err" role="alert">
          {T.stopped} <a href="/admin?ui=legacy">{T.legacy}</a>.
        </div>
      </section>
    )
  }
  if (!state.data) {
    /* `loading` и `leaving`: на уходе форму не показываем даже кадр. */
    return <section className="dp-react-root" />
  }

  const d = state.data
  return (
    <section className="dp-react-root">
      <div className="dash">
        <div className="dashmain">
          <DashCanvas model={d.canvas} rail={rail} waitTick={waitTick} lineTick={lineTick} />
          <p className="hint">
            {T.hint} <a href={`/admin?date=${d.date}&ui=legacy`}>{T.legacy}</a>.
          </p>
        </div>
        <div className="rail" ref={rail}>
          <DashRail minical={d.minical} agenda={d.agenda} tiles={d.tiles}
            occupancy={d.occupancy} date={d.date} waitTick={waitTick} />
        </div>
      </div>
    </section>
  )
}
