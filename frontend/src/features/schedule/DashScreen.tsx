import { useCallback, useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { Toast, type ToastState } from '../../components/Toast'
import { CardDialog } from './CardDialog'
import { asApiError, type ApiResult } from '../../services/api'
import { useLive } from '../../hooks/useLive'
import { DashCanvas } from './DashCanvas'
import { DashRail } from './DashRail'
import { MoveDialog } from './MoveDialog'
import { NoteDialog } from './NoteDialog'
import { SlotDialog } from './SlotDialog'
import { useClockTick } from './dashFx'
import { dash, livePath, type DashAppt, type DashBlock, type DashModel, type DashNote } from './dash'
import type { Slot } from './slot'
import { freshOf, readSeen, writeSeen, FRESH_MS } from './fresh'
import { clashAmong, hhmm, sameSlot, type Drag, type Target } from './move'

/**
 * Панель дня (`/admin`) на React — C26.5.2.
 *
 * ⭐ Единственный ЖИВОЙ экран клиента: остальные освежаются переходом и
 * ответом действия, а этот обязан узнавать о брони со второго рабочего места
 * сам. Держит это `useLive`: канал данных, 204 «не менялось», отпечаток от
 * того же, что отправлено.
 * ⭐ Экран ПИШЕТ: карточка, пустой час, заметка и перенос отправляют команды
 * (C26.5.3-e и -f). Состояние после любой из них приезжает ОДНОЙ дверью —
 * каналом, — и локального мира расписания у React нет.
 * ⛔ Шапка дня (`_date_nav`) и баннер `?msg=` печатает СЕРВЕР, снаружи узла:
 * на `/admin` приземляется `no_access` со всей программы, и увидеть его надо
 * при первой отрисовке, а не после первого ответа канала.
 */
const T = {
  hint: 'Click pe o programare — detalii și statusuri; pe o oră liberă — '
    + 'programare nouă. Trageți o programare pentru a o muta.',
  /* ⚠️ Слово взято у легаси (`MSG_BANNER["mv_gone"]`), а не придумано: та же
     ситуация там называется так же. Хвост «reîmprospătați pagina» убран —
     панель освежается сама, и советовать перезагрузку значило бы врать. */
  gone: 'Programarea nu mai există.',
  legacy: 'Deschideți varianta clasică',
  /* ⚠️ Слово СВОЁ, и это названо: у сервера его нет вовсе (снятие блокировки
     отвечает пустым кодом), а чужое — «Programarea nu mai există» — назвало бы
     заметку программой. */
  noteGone: 'Notița nu mai există.',
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
  /* Что приехало ПРЯМО СЕЙЧАС — номера, которых в прошлом конверте не было. */
  const [fresh, setFresh] = useState<ReadonlySet<number>>(NO_FRESH)
  /* ⚠️ Со снимком, как у карточки, и по той же причине: заметку могли убрать
     со второго рабочего места, пока диалог открыт, — тогда на экране остаётся
     то, что человек ОТКРЫВАЛ, и слово о том, что этого больше нет. */
  const [note, setNote] = useState<{ id: number; at: DashNote } | null>(null)
  /* Перетаскивание (C26.5.3-f). ⛔ Между `dragstart` и `drop` живёт НАМЕРЕНИЕ,
     а не состояние: канва под курсором продолжает обновляться, и только на
     время самого броска хук придерживает применение — иначе приехавшие данные
     увезли бы блок из-под мыши. */
  const [drag, setDrag] = useState<Drag | null>(null)
  const [hover, setHover] = useState('')
  const [move, setMove] = useState<{ drag: Drag; target: Target } | null>(null)
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
  /* ⛔ `hold` держит ровно два случая, и оба недолгие: команда в полёте и
     ИДУЩИЙ бросок. Открытый диалог сюда не входит — иначе рабочее место с
     забытой открытой карточкой перестало бы узнавать о бронях, оставаясь
     живым НА ВИД (ровно `panel.js`, от которого уходим).
     ⚠️ Предикат над рефами, а не булев проп: проп доезжает до хука кадром
     позже, а бросок и круг по 127.0.0.1 в этот кадр укладываются. */
  const dragging = useRef(false)
  const startDrag = useCallback((d: Drag | null) => {
    /* ⚠️ Реф ставится В ОБРАБОТЧИКЕ, а не в рендере: писать реф во время
       рендера нельзя, а состояние доехало бы до предиката кадром позже — как
       раз к моменту, когда данные уже увезли бы блок из-под мыши. */
    dragging.current = d !== null
    setDrag(d)
  }, [])
  const { state, retry, refresh } = useLive<DashModel>(
    livePath(date), 'react', version,
    { hold: () => flying.current || dragging.current })
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
  /* Память дня для подсветки приехавшего. ⛔ В ПЕРВЫЙ раз читается из
     хранилища — её мог оставить легаси-экран этой же вкладки, и ключ у них
     общий; дальше ведётся здесь. */
  const seen = useRef<string[] | null>(null)
  useEffect(() => {
    const d = state.data
    if (!d || shown.current === d) return
    if (shown.current) document.documentElement.classList.remove('anim')
    shown.current = d
    const ids = idsOf(d)
    const was = seen.current ?? readSeen(d.date)
    seen.current = ids
    writeSeen(d.date, ids)
    /* ⛔ Подсветка родится ТОЛЬКО здесь, из разницы двух конвертов. Никакое
       локальное действие её не ставит: «приехало» — это то, что сказал канал,
       а не то, что мы сами сделали минуту назад. */
    const got = freshOf(was, ids)
    if (got.length) setFresh(new Set(got.map(Number)))
  }, [state.data])

  /* ⛔ Пометку снимает ТАЙМЕР, а не `animationend`: под
     `prefers-reduced-motion` анимации нет вовсе, события не будет, и пометка
     осталась бы навсегда. У легаси её не снимали никогда — там узел умирал при
     первой же подмене, а здесь он живёт, и залипшая пометка означала бы, что
     вторая такая же запись уже не мигнёт. */
  useEffect(() => {
    if (!fresh.size) return
    const t = setTimeout(() => setFresh(NO_FRESH), FRESH_MS)
    return () => clearTimeout(t)
  }, [fresh])

  /* ⛔ Надгробие. Запись могли отменить или перенести со второго рабочего
     места, пока диалог открыт. Молча размонтировать нельзя — человек решит,
     что промахнулся мимо кнопки; врать «она есть» тоже нельзя. Диалог
     остаётся на ПОСЛЕДНЕМ известном блоке, говорит словом и запирает все
     кнопки: из надгробия ничего отправить нельзя, им можно только сказать
     «этого больше нет». */
  const found = card === null ? null : findAppt(state.data, card.id)
  const openCard = found ?? card?.at ?? null
  const gone = card !== null && found === null
  const foundNote = note === null ? null : findNote(state.data, note.id)
  const openNote = foundNote ?? note?.at ?? null
  const noteGone = note !== null && foundNote === null

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

  const openNoteById = (m: DashModel, id: number) => {
    const at = findNote(m, id)
    if (at) setNote({ id, at })
  }

  /* ⛔ Бросок на СВОЁ ЖЕ место — не перенос. Сервер такой запрос ПРИНИМАЕТ
     (`ok_move`) и пишет строку в летопись пациента, а летопись не
     переписывают. Получас при этом переносом считается: 09:00 → 09:30 —
     настоящее изменение. */
  const onDrop = useCallback((t: Target) => {
    setHover('')
    const d = drag
    startDrag(null)
    if (!d || sameSlot(d, t)) return
    setMove({ drag: d, target: t })
  }, [drag, startDrag])

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
            onSlot={(dk, name, hour) => setSlot({ dk, name, hour })}
            onNote={(id) => openNoteById(d, id)}
            drag={drag} hover={hover} onDrag={startDrag} onHover={setHover}
            onDrop={onDrop} fresh={fresh} />
          <p className="hint">
            {T.hint} <a href={`/admin?date=${d.date}&ui=legacy`}>{T.legacy}</a>.
          </p>
        </div>
        <div className="rail" ref={rail}>
          <DashRail minical={d.minical} agenda={d.agenda} tiles={d.tiles}
            occupancy={d.occupancy} date={d.date} waitTick={waitTick}
            onCard={(id) => openById(d, id)} fresh={fresh} />
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
      {note !== null && openNote && (
        /* ⛔ Кнопка приходит С СЕРВЕРА по состоянию заметки — той же матрицей,
           что печатает список дня. У надгробия её нет вовсе: действовать не над
           чем. ⚠️ Матрица знает два состояния из шести, и заметка, уведённая в
           чужой статус, честно остаётся без кнопок. */
        <NoteDialog key={note.id} open note={openNote}
          actions={noteGone ? [] : d.note_actions[openNote.status] ?? []}
          gone={noteGone ? T.noteGone : ''}
          busy={busy} onClose={() => setNote(null)}
          onStatus={async (to) => {
            const ok = await act(() => dash.status(d.date, note.id, to))
            if (ok) setNote(null)
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
          onClose={() => setSlot(null)}
          /* ⛔ Своей проверки занятости здесь НЕТ и быть не должно:
             сериализует сервер (`_slot_lock`, один критический участок на
             «проверка + вставка»), а клиентская подсказка не имеет права не
             пустить команду. Отказ приходит словом сервера, и после него
             диалог остаётся открытым с набранным. */
          onAdd={(b) => act(() => dash.add(d.date, b))}
          onNote={(b) => act(() => dash.note(d.date, b))} />
      )}
      {move && (
        /* ⛔ Подсказку о помехе считает ЭКРАН по своей канве, а не диалог по
           модели: у дня и у панели разные модели и разный ключ колонки, а
           диалог переноса ОДИН на оба.
           ⚠️ И это именно подсказка: правду говорит сервер под `_BOOK_LOCK` —
           пока тянули, час мог занять второй администратор. */
        <MoveDialog open drag={move.drag} target={move.target} busy={busy}
          fromName={colName(d, move.drag.dk)} toName={colName(d, move.target.dk)}
          busyAt={clashAmong(blocksOf(d, move.target.dk), move.target.min,
            move.drag.dur, move.drag.id)}
          onClose={() => setMove(null)}
          onMove={() => {
            /* ⚠️ Диалог закрывается ДО ответа, в отличие от записи: терять
               здесь нечего — набранного в нём нет, — а ответом служит сам
               блок, который либо переехал, либо остался на месте. */
            const { drag: what, target: to } = move
            setMove(null)
            void act(() => dash.move(d.date, what.id,
              { date: d.date, time: hhmm(to.min), doctor: to.dk }))
          }} />
      )}
      {toast && <Toast {...toast} onClose={() => setToast(null)} />}
    </section>
  )
}

/** Пустая пометка — ОДНА ссылка на всех: новый `new Set()` в состоянии давал
 *  бы новый объект на каждый тик и перезапускал бы эффект таймера. */
const NO_FRESH: ReadonlySet<number> = new Set()

/** Номера всего, что ВИДНО на панели: блоки канвы (визиты и заметки стойки) и
 *  строки повестки. ⛔ Тот же состав, что собирает легаси своим
 *  `[data-appt]`, — иначе две памяти одного дня разошлись бы, и переход на
 *  `?ui=legacy` дал бы вспышку всего экрана. */
function idsOf(m: DashModel): string[] {
  const out: string[] = []
  for (const col of m.canvas.columns) {
    for (const b of col.blocks) out.push(String(b.id))
  }
  for (const it of m.agenda.items) out.push(String(it.id))
  return out
}

/** Имя колонки по ключу врача — для строк «De la» / «La». ⛔ Из КАНВЫ, а не
 *  из модели дня: ключ колонки здесь свой, и у выпавшего из справочника врача
 *  колонка отдельная. */
function colName(m: DashModel, dk: string): string {
  return m.canvas.columns.find((c) => c.id === dk)?.name ?? '—'
}

/** Блоки ЭТОЙ колонки — по ним считается подсказка о помехе. */
function blocksOf(m: DashModel, dk: string) {
  return m.canvas.columns.find((c) => c.id === dk)?.blocks ?? []
}

/** Блок по номеру — в той канве, что сейчас на экране. ⚠️ Номер один на
 *  визиты и заметки (заметка это строка `appointments` с `source='note'`),
 *  поэтому ищется блок, а вид уточняется после. */
function findBlock(m: DashModel | null, id: number): DashBlock | null {
  if (!m) return null
  for (const col of m.canvas.columns) {
    for (const b of col.blocks) if (b.id === id) return b
  }
  return null
}

function findAppt(m: DashModel | null, id: number): DashAppt | null {
  const b = findBlock(m, id)
  return b && b.kind === 'appt' ? b : null
}

function findNote(m: DashModel | null, id: number): DashNote | null {
  const b = findBlock(m, id)
  return b && b.kind === 'note' ? b : null
}
