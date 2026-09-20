import { useCallback, useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { Toast, type ToastState } from '../../components/Toast'
import { CardDialog } from './CardDialog'
import { asApiError, type ApiResult } from '../../services/api'
import { useLive } from '../../hooks/useLive'
import { DashCanvas } from './DashCanvas'
import { DashRail } from './DashRail'
import { SlotDialog } from './SlotDialog'
import { useClockTick } from './dashFx'
import { dash, livePath, type DashAppt, type DashModel } from './dash'
import type { Slot } from './slot'

/**
 * Панель дня (`/admin`) на React — C26.5.2.
 *
 * ⭐ Единственный ЖИВОЙ экран клиента: остальные освежаются переходом и
 * ответом действия, а этот обязан узнавать о брони со второго рабочего места
 * сам. Держит это `useLive`: канал данных, 204 «не менялось», отпечаток от
 * того же, что отправлено.
 * ⛔ Экран пока НЕ ПИШЕТ. Диалоги открываются (визит — `b`, пустой час — `c`),
 * но команды записи и переноса — `e` и `f`; подсказка говорит правду и ведёт в
 * старую панель, а не обещает действий, которых экран не умеет.
 * ⛔ Шапка дня (`_date_nav`) и баннер `?msg=` печатает СЕРВЕР, снаружи узла:
 * на `/admin` приземляется `no_access` со всей программы, и увидеть его надо
 * при первой отрисовке, а не после первого ответа канала.
 */
const T = {
  hint: 'Click pe o programare — detalii și statusuri. Programări noi și '
    + 'mutările se fac deocamdată în varianta clasică.',
  /* ⚠️ Слово взято у легаси (`MSG_BANNER["mv_gone"]`), а не придумано: та же
     ситуация там называется так же. Хвост «reîmprospătați pagina» убран —
     панель освежается сама, и советовать перезагрузку значило бы врать. */
  gone: 'Programarea nu mai există.',
  legacy: 'Deschideți varianta clasică',
  /* ⚠️ Ступень, а не решение: слот здесь уже МОДЕЛИРУЕТСЯ (врач, час, получас,
     концы блокировки), а команда приходит в `e`. Форма без объяснения выглядела
     бы сломанной, а без формы нечего было бы проверять. */
  slotSoon: 'Ora se alege aici, dar programarea se salvează deocamdată în '
    + 'varianta clasică.',
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
  /* ⚠️ Вместе с номером хранится СНИМОК записи на момент клика — он и
     станет надгробием, если запись исчезнет. Снимок берётся в
     обработчике, а не в рендере: писать реф во время рендера нельзя, а
     `setState` в эффекте даёт каскад — оба запрещены линтом React, и оба
     запрещены по делу.
     ⭐ И показывает надгробие ровно то, что человек ОТКРЫВАЛ. */
  const [card, setCard] = useState<{ id: number; at: DashAppt } | null>(null)
  /* ⛔ Надгробия у слота нет и не нужно: слот — не запись, а МЕСТО. Пока
     диалог открыт, час могли занять со второго рабочего места, и отвечает на
     это ОТКАЗ команды (`e`), а не исчезновение из конверта: своей проверки
     занятости на клиенте не заводится (`clash` — подсказка, сериализует
     сервер). Поэтому диалог живёт на трёх значениях клика и не смотрит в
     канву вовсе. */
  const [slot, setSlot] = useState<Slot | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  /* ⛔ Признак «команда в полёте» ставится СИНХРОННО, рефом, и предикат
     читает его в момент тика: состояние доехало бы до хука кадром позже, а
     команда длиной в круг по 127.0.0.1 в этот кадр укладывается. */
  const flying = useRef(false)
  /* ⚠️ Версия — та, с которой загружена ЭТА страница: разошлась с ответом,
     значит exe обновили под открытой вкладкой, и новые данные нельзя
     вклеивать в старый код. Поверхность — `react`: узнав от сервера, что по
     адресу теперь живёт старая страница, вкладка перезагрузится сама. */
  const version = document.body.dataset.v ?? ''
  const { state, retry, refresh } = useLive<DashModel>(
    livePath(date), 'react', version, { hold: () => flying.current })
  const lineTick = useClockTick(LINE_MS)
  const waitTick = useClockTick(WAIT_MS)

  /* ⛔ Класс `anim` снимается ЗДЕСЬ, и снимать его больше некому. Ставит его
     каркас всякой странице (`core/layout.py`), а снимал единственный —
     `apply()` живого опроса `panel.js`, который на React-странице не
     запускается вовсе. Оставь как есть — и `.anim .ag-i`, `.anim .spark`,
     `.anim .statbar>div` переигрывали бы входную анимацию на КАЖДОМ новом
     узле, приехавшем каналом, вечно. Сцена этого не поймала бы: анимация CSS
     мутацией DOM не является.
     ⚠️ На ПЕРВОМ обновлении, а не на первой отрисовке, и это буквальный
     перенос старого поведения: у легаси первая отрисовка серверная и
     анимируется, а снимает класс первый же `apply`, то есть первое
     ИЗМЕНЕНИЕ. Сними на первой — и анимация входа оборвалась бы на середине.
     ⚠️ Сравнение по ссылке, а не счётчик: `StrictMode` (`main.tsx`) зовёт
     эффекты дважды, и счётчик добрался бы до двух на первой же отрисовке. */
  const shown = useRef<DashModel | null>(null)
  useEffect(() => {
    const d = state.data
    if (!d) return
    if (shown.current && shown.current !== d) {
      document.documentElement.classList.remove('anim')
    }
    shown.current = d
  }, [state.data])

  /* ⛔ Надгробие. Запись могли отменить или перенести со второго рабочего
     места, пока диалог открыт. Молча размонтировать нельзя — человек решит,
     что промахнулся мимо кнопки; врать «она есть» тоже нельзя. Диалог
     остаётся на ПОСЛЕДНЕМ известном блоке, говорит словом и запирает все
     кнопки: из надгробия ничего отправить нельзя, им можно только сказать
     «этого больше нет». */
  const found = card === null ? null : findAppt(state.data, card.id)
  const openCard = found ?? card?.at ?? null
  const gone = card !== null && found === null

  /* Одно действие на обе команды. ⛔ Ответ состояния НЕ несёт: после команды
     экран спрашивает канал (`refresh()`), и путь к состоянию остаётся один.
     ⚠️ `refresh()` зовётся на ЛЮБОМ исходе, включая 409: «интервал занят»
     значит, что каноническое состояние уже изменилось под тобой, а отказ
     приходит без данных — человек прочтёт отказ и будет смотреть на
     несуществующую запись. */
  const act = useCallback(async (run: () => Promise<ApiResult<void>>) => {
    flying.current = true
    setBusy(true)
    try {
      const r = await run()
      if (r.text) setToast({ tone: r.tone, text: r.text })
      return true
    } catch (e) {
      const err = asApiError(e)
      setToast({ tone: 'err', text: err.text || T.offline })
      return false
    } finally {
      flying.current = false
      setBusy(false)
      refresh()
    }
  }, [refresh])

  /* Открыть карточку: снимок записи берётся ЗДЕСЬ, в обработчике клика. */
  const openById = (m: DashModel, id: number) => {
    const at = findAppt(m, id)
    if (at) setCard({ id, at })
  }

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
          <DashCanvas model={d.canvas} rail={rail} waitTick={waitTick}
            lineTick={lineTick} onCard={(id) => openById(d, id)}
            onSlot={(dk, name, hour) => setSlot({ dk, name, hour })} />
          <p className="hint">
            {T.hint} <a href={`/admin?date=${d.date}&ui=legacy`}>{T.legacy}</a>.
          </p>
        </div>
        <div className="rail" ref={rail}>
          <DashRail minical={d.minical} agenda={d.agenda} tiles={d.tiles}
            occupancy={d.occupancy} date={d.date} waitTick={waitTick}
            onCard={(id) => openById(d, id)} />
        </div>
      </div>

      {card !== null && openCard && (
        <CardDialog key={card.id} open id={card.id} card={openCard}
          /* ⛔ Кнопки приходят С СЕРВЕРА по состоянию записи. У надгробия их
             нет вовсе: действовать не над чем. */
          actions={gone ? [] : d.actions[openCard.status] ?? []}
          note={gone ? T.gone : ''}
          back={`/admin?date=${d.date}`} busy={busy}
          onClose={() => setCard(null)}
          onComment={(text) => act(() => dash.comment(d.date, card.id, text))}
          onStatus={async (to) => {
            const ok = await act(() => dash.status(d.date, card.id, to))
            if (ok) setCard(null)
            return ok
          }} />
      )}
      {slot && (
        /* ⚠️ Ключ «врач|час» — тот же приём, что у карточки: другая ячейка =
           другой диалог, и набранное имя не переезжает на соседний час.
           ⛔ Данные — ИЗ КОНВЕРТА (`slotform`, `note_ends`), а не отдельным
           запросом: они постоянны, отпечаток не двигают, и второй двери к
           состоянию не появляется. */
        <SlotDialog key={`${slot.dk}|${slot.hour}`} open slot={slot}
          date={d.date} form={d.slotform} noteEnds={d.note_ends} busy={busy}
          notice={T.slotSoon} onClose={() => setSlot(null)} />
      )}
      {toast && <Toast {...toast} onClose={() => setToast(null)} />}
    </section>
  )
}

/** Блок визита по номеру — в той канве, что сейчас на экране. */
function findAppt(m: DashModel | null, id: number): DashAppt | null {
  if (!m) return null
  for (const col of m.canvas.columns) {
    for (const b of col.blocks) if (b.kind === 'appt' && b.id === id) return b
  }
  return null
}
