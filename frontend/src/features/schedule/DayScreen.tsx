import { useCallback, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import {
  hashChangeKeepsData, queryParam, useRouteLoad, type RouteLoad, type ScreenData,
} from '../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { dm, shift } from '../../utils/date'
import { AddDialog } from './AddDialog'
import { CardDialog } from './CardDialog'
import { CardMenu, type CardMenuAt } from './CardMenu'
import { DashCanvas } from './DashCanvas'
import { DayList } from './DayList'
import { MoveDialog } from './MoveDialog'
import { NoteDialog } from './NoteDialog'
import { SlotDialog } from './SlotDialog'
import { canvasBlocks, canvasColName, canvasNote, type DashNote } from './dash'
import { useClockTick } from './dashFx'
import { day, type DayModel } from './day'
import type { Slot } from './slot'
import { clashAmong, hhmm, sameSlot, type Drag, type Target } from './move'

/* День журнала — раздел «Programări»: «Toți medicii» и день одного врача —
   один экран, разница только в параметре `doctor` (C25.5a), с записью,
   карточкой и переносом (C25.5b).

   ⭐ (06.10, Олег: «проверь эту вкладку, мы про неё забыли») Сетка дня — ТА ЖЕ
   канва, что у «Panoul principal» (`DashCanvas` по `canvas.model`): шапки
   врачей с цветом и загрузкой, цвет по типу процедуры, срочный красным,
   длительность — высотой блока, линия «сейчас». До того здесь жила старая
   таблица со своей раскраской по статусу и «+» в каждом свободном часе — два
   экрана одного дня говорили разными цветами. Запись — окном (`#addform`), не
   формой внизу страницы; неделя — вкладкой «Săptămâna» этого же раздела.

   ⛔ Экран НЕ живой, как и неделя: React-дерево внутри #live умирает при
   первой подмене. Сервер сам перестаёт объявлять страницу живой, увидев узел
   (layout._shell), а свежесть здесь даёт переход по дате и ответ действия —
   каждый POST возвращает СВЕЖИЙ день, и второй запрос за ним не нужен.
   ⛔ Перезагрузки страницы после действия больше нет, поэтому не нужна и
   починка прокрутки из panel.js: место на экране не теряется вовсе. */
const T = {
  /* ⚠️ Шапка дня — те же слова, что у панели дня и у старой шапки
     (`routes._date_nav`): подпись дня с сервера, соседний день числом,
     «-7 zile» / «+7 zile» на двойных стрелках. До 06.10 здесь стояли голая
     ISO-дата и «‹ zi / zi ›», а листать неделями было нечем — при переезде
     в React шапка потеряла то, что у старой страницы было (Олег 06.10). */
  today: 'Azi',
  prevDay: 'Ziua precedentă',
  nextDay: 'Ziua următoare',
  period: 'Perioadă',
  day: 'Zi',
  week: 'Săptămâna',
  all: 'Toți medicii',
  doctorSel: 'Medic',
  excel: 'Excel',
  /* подзаголовок (08.10): «Joi, 8 octombrie 2026 · 1 programare · 3% ocupare» */
  one: 'programare',
  many: 'programări',
  occ: 'ocupare',
  /* Подсказка одной строкой (08.10, макет): место — действие. */
  hintFree: 'Interval liber',
  hintFreeT: 'programare nouă sau notiță',
  hintAppt: 'Programare',
  hintApptT: 'detalii și statusuri',
  hintDrag: 'Trage o programare pentru a o muta la altă oră sau alt medic.',
  /* Слово своё — у сервера его нет (снятие блокировки отвечает пустым кодом);
     то же, что у панели дня. */
  noteGone: 'Notița nu mai există.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

/* Два разных периода, как и у панели дня: линия «сейчас» — раз в 30 с,
   минуты ожидания — раз в минуту. */
const LINE_MS = 30_000
const WAIT_MS = 60_000
/** Подсветки «только что приехал» здесь нет: экран не живой, приезжать нечему. */
const NO_FRESH: ReadonlySet<number> = new Set()
/** Якорь «Programare nouă»: с ним сюда ведёт кнопка шапки программы. */
const ADD_HASH = '#addform'

interface Props {
  /** Врач из ПУТИ (`/admin/doctor/:dk`): пусто — все. */
  doctor?: string
  navigate?: (url: string) => void
}

/**
 * Данные дня грузит роутер (B2.2), и ЧТО грузить, он берёт из адреса (B2.3):
 * «какой день» — `?date=`, «какой отбор» — `?f=`, «чей день» — путь, и больше
 * никто. Пустая дата — сегодня, его считает сервер в поясе клиники.
 * ⛔ Запрос собирается ТОЛЬКО из этих трёх, query как есть не пересылается:
 * на `/admin/all` `?doctor=` и `?time_pre=` — предвыбор формы старой страницы
 * (её ссылка «+»), а у `/api/schedule/day` `doctor` значит «день одного
 * врача». Переслать адрес целиком — и общий журнал открылся бы днём врача.
 * ⭐ Смена ОДНОГО якоря загрузчик не перезапускает (`hashChangeKeepsData`,
 * 07.10, Олег): `#addform` — окно поверх того же дня, и его закрытие слало
 * второй GET — окно висело до ответа, а отказ менял день на плашку отказа.
 * Тот же адрес («Zi» на том же дне) и повтор перечитывают день, как и раньше.
 */
export const loadDay: ScreenData = {
  load: ((signal, p, q) =>
    day.get(queryParam(q, 'date'), p.dk ?? '', queryParam(q, 'f'), signal)) satisfies RouteLoad<DayModel>,
  shouldRevalidate: hashChangeKeepsData,
}

export function DayScreen({ doctor = '', navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<DayModel>(navigate)
  const to = useNavigate()
  const loc = useLocation()
  const [q] = useSearchParams()
  /* День действий — дата АДРЕСА как есть, без своей копии: пусто так и
     уходит пустым, и «сегодня» решает сервер в момент запроса (после
     полуночи — уже новый день), а не браузер и не первая загрузка. */
  const at = queryParam(q, 'date')
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [slot, setSlot] = useState<Slot | null>(null)
  const [card, setCard] = useState<number | null>(null)
  /* Заметка — со СНИМКОМ, как у панели: после действия день приезжает
     свежим, и убранная заметка остаётся в окне тем, что человек открывал. */
  const [note, setNote] = useState<{ id: number; at: DashNote } | null>(null)
  /* Меню по правой кнопке и по «⋯» списка — те же исходы, что в диалоге. */
  const [menu, setMenu] = useState<CardMenuAt | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  const [drag, setDrag] = useState<Drag | null>(null)
  const [hover, setHover] = useState('')
  const [move, setMove] = useState<{ drag: Drag; target: Target } | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  /* Рельса у этого экрана нет: сетка тянется по окну (`useFitGrid`). */
  const noRail = useRef<HTMLDivElement | null>(null)
  const lineTick = useClockTick(LINE_MS)
  const waitTick = useClockTick(WAIT_MS)

  /* Одно действие на все формы и диалоги: удача подменяет день и показывает
     плашку сервера, отказ — только плашку. Возвращает «получилось ли», чтобы
     диалог закрывался лишь на удаче. */
  const act = useCallback(async (run: () => Promise<ApiResult<DayModel>>): Promise<boolean> => {
    setBusy(true)
    try {
      const r = await run()
      replace(r.data)
      if (r.text) setToast({ tone: r.tone, text: r.text })
      return true
    } catch (e) {
      const err = asApiError(e)
      if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
      return false
    } finally {
      setBusy(false)
    }
  }, [replace, leaveIfSignedOut])

  const onDrop = useCallback((t: Target) => {
    setHover('')
    const d = drag
    setDrag(null)
    /* ⛔ Бросок на своё же место — не перенос. Сервер такой запрос ПРИНИМАЕТ
       и пишет строку в летопись пациента, а летопись не переписывают. */
    if (!d || sameSlot(d, t)) return
    setMove({ drag: d, target: t })
  }, [drag])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} text={T.offline} />
      </section>
    )
  }
  if (state.status === 'loading') {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const m = state.data
  const base = doctor ? `/admin/doctor/${doctor}` : '/admin/all'
  /* Отбор — ЭХО сервера, а не сырой `?f=`: чужой ключ сервер отбрасывает
     (`filter: null`), и в адрес и в действия дальше уходит только признанный. */
  const tile = m.filter?.key ?? ''
  /* Переход на другой день или отбор — через РОУТЕР: адрес меняется, загрузчик
     читает уже его, и F5 на этом адресе откроет тот же день с тем же отбором.
     Query собирается заново (дата и отбор, без `msg` и прочего хвоста);
     `replace`, как и было: листание дней не копит шаги «Назад». Пока ответа
     нет, на экране прежний день, как и до роутера. */
  const go = (iso: string, f: string = tile) => {
    const next = new URLSearchParams()
    if (iso) next.set('date', iso)
    if (f) next.set('f', f)
    const tail = next.toString()
    void to(tail ? `${base}?${tail}` : base, { replace: true })
  }
  /* ⭐ Окно записи открыто, пока в адресе `#addform`: с ним сюда ведёт кнопка
     «Programare nouă» шапки программы, и повторное нажатие той же кнопки —
     это тот же адрес, который снова откроет окно. Закрыть — убрать якорь
     (`replace`). День при этом НЕ перечитывается, но не сам по себе: снятие
     якоря роутер считает перезагрузкой, её отменяет правило маршрута
     (`loadDay` › `hashChangeKeepsData`). Своего флага у экрана нет: адрес и
     есть состояние. */
  const adding = loc.hash === ADD_HASH
  const closeAdd = () => { void to(`${loc.pathname}${loc.search}`, { replace: true }) }
  const openCard = card !== null ? m.cards[String(card)] : undefined
  const menuCard = menu !== null ? m.cards[String(menu.id)] : undefined
  const openMenu = (id: number, x: number, y: number) => setMenu({ id, x, y })
  const openNote = (id: number) => {
    const n = canvasNote(m.canvas, id)
    if (n) setNote({ id, at: n })
  }
  const foundNote = note === null ? null : canvasNote(m.canvas, note.id)
  const shownNote = foundNote ?? note?.at ?? null
  const noteGone = note !== null && foundNote === null
  const listNode = (
    <DayList model={m} busy={busy} onCard={setCard} onCardMenu={openMenu} onAll={() => go(m.date, '')}
             onStatus={(id, to) => { void act(() => day.status(at, doctor, tile, id, to)) }} />
  )

  /* Сводка дня для подзаголовка (08.10): число записей — по списку без заметок
     и отменённых, загрузка — по канве (занятые минуты из рабочих у всех
     колонок). Те же цифры, что считают шапки колонок; второго счёта нет. */
  const count = m.list.filter((r) => !r.is_note && r.status !== 'cancelled').length
  const occ = m.canvas.columns.reduce((a, c) => ({
    busy: a.busy + (c.occupancy?.busy ?? 0), cap: a.cap + (c.occupancy?.cap ?? 0),
  }), { busy: 0, cap: 0 })
  const occPct = occ.cap ? Math.min(100, Math.round(100 * occ.busy / occ.cap)) : 0
  const docName = doctor ? m.doctors.find((d) => d.id === doctor)?.name ?? '' : ''

  return (
    <section className="dp-react-root">
      {toast ? <Toast tone={toast.tone} text={toast.text} onClose={closeToast} /> : null}
      {/* Инструменты дня по макету (08.10, промпт 2): врач, стрелки на день,
          «Azi», сегмент «Zi | Săptămâna», «Excel». «Panou» и «±7 zile» сняты —
          меню и стрелки их дублируют. Выбор врача — адресом: день одного врача
          живёт на `/admin/doctor/{dk}`, и F5 его сохраняет. */}
      <div className="nav dp-daynav">
        <select className="dp-sel" aria-label={T.doctorSel} value={doctor}
          onChange={(e) => {
            const dk = e.target.value
            void to(`${dk ? `/admin/doctor/${dk}` : '/admin/all'}?date=${m.date}`)
          }}>
          <option value="">{T.all}</option>
          {m.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <AppLink className="dp-ibtn" href={`${base}?date=${shift(m.date, -1)}`}
           title={`${T.prevDay} · ${dm(shift(m.date, -1))}`} aria-label={T.prevDay}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, -1)) }}><Icon name="chev-l" /></AppLink>
        <AppLink className="dp-ibtn" href={`${base}?date=${shift(m.date, 1)}`}
           title={`${T.nextDay} · ${dm(shift(m.date, 1))}`} aria-label={T.nextDay}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, 1)) }}><Icon name="chev-r" /></AppLink>
        <AppLink href={base} onClick={(e) => { e.preventDefault(); go('') }}>{T.today}</AppLink>
        {/* ⭐ «Zi / Săptămâna» — как у панели: неделя с 06.10 живёт в этом же
            разделе (Олег), и её вкладка рядом с днём. */}
        <span className="dp-seg" role="group" aria-label={T.period}>
          <AppLink className="on" href={`${base}?date=${m.date}`} aria-current="page"
             onClick={(e) => { e.preventDefault(); go(m.date) }}>{T.day}</AppLink>
          <AppLink href={`/admin/week?date=${m.date}`}>{T.week}</AppLink>
        </span>
        {doctor ? null : (
          <AppLink href={`/admin/export.xlsx?from=${m.date}&to=${m.date}`}>
            <Icon name="download" /> {T.excel}
          </AppLink>
        )}
        {/* ⛔ «Varianta clasică» из шапки убрана (Олег 06.10: «это не нужно»):
            старая страница осталась только аварийным выходом — на экране
            отказа загрузки (`LoadFailed`). */}
      </div>
      <div className="sub dp-daysub">
        {docName ? <><b>{docName}</b> · </> : null}
        <b className="dp-daysub-date">{m.day_long}</b> · {count} {count === 1 ? T.one : T.many} · {occPct}% {T.occ}
      </div>

      {/* ⚠️ Место списка зависит от отбора, и это не косметика: пришедший с
          плитки панели дня должен увидеть СВОИ строки сразу, а не под сеткой.
          Полный список остаётся внизу, как на старой странице. */}
      {m.filter ? listNode : null}

      {/* на телефоне сетка прокручивается внутри обёртки (как .dashmain на
          главной), а не растягивает страницу вбок */}
      <div className="dp-daymain">
        <DashCanvas model={m.canvas} rail={noRail} waitTick={waitTick} lineTick={lineTick}
                    onCard={setCard} onCardMenu={openMenu}
                    onSlot={(dk, name, hour) => setSlot({ dk, name, hour })}
                    onNote={openNote}
                    drag={drag} hover={hover} onDrag={setDrag} onHover={setHover} onDrop={onDrop}
                    fresh={NO_FRESH} />
      </div>
      <p className="hint dp-dayhint">
        <b>{T.hintFree}</b> — {T.hintFreeT} · <b>{T.hintAppt}</b> — {T.hintApptT} · {T.hintDrag}
      </p>

      {m.filter ? null : listNode}

      {/* ⛔ Ключ — день экрана. Окно засевает дату при открытии, а переход по
          дням идёт роутером и экземпляр не пересоздаёт: без ключа окно
          показывало бы первый день вкладки и записывало в него. Смена дня
          начинает запись заново, как перезагрузка старой страницы (Олег
          24.09). */}
      {adding && m.form
        ? <AddDialog key={m.date} open form={m.form} date={m.date} busy={busy}
                     onClose={closeAdd}
                     onAdd={(b) => act(() => day.add(at, doctor, tile, b))} />
        : null}

      {slot && m.form
        ? <SlotDialog key={`${slot.dk}|${slot.hour}`} open slot={slot}
                      date={m.date} form={m.form}
                      noteEnds={m.note_ends} busy={busy}
                      onClose={() => setSlot(null)}
                      onAdd={(b) => act(() => day.add(at, doctor, tile, b))}
                      onNote={(b) => act(() => day.note(at, doctor, tile, b))} />
        : null}

      {menu !== null && menuCard
        ? <CardMenu at={menu} card={menuCard} actions={m.actions[menuCard.status] ?? []}
                    busy={busy} onClose={closeMenu}
                    onStatus={async (to) => {
                      const ok = await act(() => day.status(at, doctor, tile, menu.id, to))
                      if (ok) setMenu(null)
                      return ok
                    }} />
        : null}

      {card !== null && openCard
        ? <CardDialog key={card} open id={card} card={openCard}
                      actions={m.actions[openCard.status] ?? []}
                      back={`${base}?date=${m.date}`} busy={busy}
                      onClose={() => setCard(null)}
                      onComment={(text) => act(() => day.comment(at, doctor, tile, card, text))}
                      onStatus={async (to) => {
                        const ok = await act(() => day.status(at, doctor, tile, card, to))
                        if (ok) setCard(null)
                        return ok
                      }} />
        : null}

      {note !== null && shownNote
        ? <NoteDialog key={note.id} open note={shownNote}
                      actions={noteGone ? [] : m.note_actions[shownNote.status] ?? []}
                      gone={noteGone ? T.noteGone : ''}
                      busy={busy} onClose={() => setNote(null)}
                      onStatus={async (to) => {
                        const ok = await act(() => day.status(at, doctor, tile, note.id, to))
                        if (ok) setNote(null)
                        return ok
                      }} />
        : null}

      {move
        ? <MoveDialog open drag={move.drag} target={move.target} busy={busy}
                      fromName={canvasColName(m.canvas, move.drag.dk)}
                      toName={canvasColName(m.canvas, move.target.dk)}
                      busyAt={clashAmong(canvasBlocks(m.canvas, move.target.dk), move.target.min,
                        move.drag.dur, move.drag.id)}
                      onClose={() => setMove(null)}
                      onMove={() => {
                        const { drag: d, target: t } = move
                        setMove(null)
                        void act(() => day.move(at, doctor, tile, d.id,
                          { date: m.date, time: hhmm(t.min), doctor: t.dk }))
                      }} />
        : null}
    </section>
  )
}
