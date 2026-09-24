import { useCallback, useState } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { shift } from '../../utils/date'
import { AddForm } from './AddForm'
import { CardDialog } from './CardDialog'
import { DayGrid } from './DayGrid'
import { DayList } from './DayList'
import { MoveDialog } from './MoveDialog'
import { SlotDialog } from './SlotDialog'
import { day, type DayModel } from './day'
import type { Slot } from './slot'
import { clash, doctorName, sameSlot, type Drag, type Target } from './move'

/* День журнала: «Toți medicii» и день одного врача — один экран, разница
   только в параметре `doctor` (C25.5a), с записью, карточкой и переносом
   (C25.5b).

   ⛔ Экран НЕ живой, как и неделя: React-дерево внутри #live умирает при
   первой подмене. Сервер сам перестаёт объявлять страницу живой, увидев узел
   (layout._shell), а свежесть здесь даёт переход по дате и ответ действия —
   каждый POST возвращает СВЕЖИЙ день, и второй запрос за ним не нужен.
   ⛔ Перезагрузки страницы после действия больше нет, поэтому не нужна и
   починка прокрутки из panel.js: место на экране не теряется вовсе. */
const T = {
  prevDay: 'zi',
  today: 'Azi',
  all: 'Toți medicii',
  panel: 'Panou',
  legacy: 'Varianta clasică',
  excel: 'Excel',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  /** Дата из адреса; пусто — сегодня. */
  date?: string
  /** Врач: пусто — все. */
  doctor?: string
  /** Отбор плитки панели дня: режет СПИСОК, сетку не трогает. */
  f?: string
  navigate?: (url: string) => void
}

export function DayScreen({ date = '', doctor = '', f = '',
  navigate = defaultNavigate }: Props) {
  const [at, setAt] = useState(date)
  const [tile, setTile] = useState(f)
  const load = useCallback((signal: AbortSignal) => day.get(at, doctor, tile, signal),
    [at, doctor, tile])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [slot, setSlot] = useState<Slot | null>(null)
  const [card, setCard] = useState<number | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [hover, setHover] = useState('')
  const [move, setMove] = useState<{ drag: Drag; target: Target } | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

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
  /* Адрес повторяет отбор — как у старой страницы: перезагрузка и
     `?ui=legacy` открывают тот же день с тем же фильтром. */
  const go = (iso: string, t2: string = tile) => {
    setAt(iso)
    setTile(t2)
    const url = `${base}?date=${iso}${t2 ? `&f=${t2}` : ''}`
    try { window.history.replaceState(null, '', url) } catch { /* jsdom */ }
  }
  const openCard = card !== null ? m.cards[String(card)] : undefined
  const listNode = (
    <DayList model={m} busy={busy} onCard={setCard} onAll={() => go(m.date, '')}
             onStatus={(id, to) => { void act(() => day.status(at, doctor, tile, id, to)) }} />
  )

  return (
    <section className="dp-react-root">
      {toast ? <Toast tone={toast.tone} text={toast.text} onClose={closeToast} /> : null}
      <div className="nav">
        <b>{m.date}</b>
        <a href={`${base}?date=${shift(m.date, -1)}`}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, -1)) }}>
          <Icon name="chev-l" /> {T.prevDay}
        </a>
        <a href={base} onClick={(e) => { e.preventDefault(); go('') }}>{T.today}</a>
        <a href={`${base}?date=${shift(m.date, 1)}`}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, 1)) }}>
          {T.prevDay} <Icon name="chev-r" />
        </a>
        <a href={`/admin?date=${m.date}`}><Icon name="home" /> {T.panel}</a>
        {doctor ? null : (
          <a href={`/admin/export.xlsx?from=${m.date}&to=${m.date}`}>
            <Icon name="download" /> {T.excel}
          </a>
        )}
        {doctor
          ? <a href={`/admin/all?date=${m.date}`}><Icon name="clipboard" /> {T.all}</a>
          : null}
        <a className="primary" href={`${base}?date=${m.date}&ui=legacy`}>{T.legacy}</a>
      </div>

      {/* ⚠️ Место списка зависит от отбора, и это не косметика: пришедший с
          плитки панели дня должен увидеть СВОИ строки сразу, а не под сеткой
          и формой. Полный список остаётся внизу, как на старой странице. */}
      {m.filter ? listNode : null}

      <DayGrid model={m} drag={drag} hover={hover}
               onDrag={setDrag} onHover={setHover} onDrop={onDrop}
               onPlus={(dk, name, hour) => setSlot({ dk, name, hour })}
               onCard={setCard} />

      {m.form
        ? <AddForm form={m.form} date={m.date} busy={busy}
                   onAdd={(b) => act(() => day.add(at, doctor, tile, b))} />
        : null}

      {m.filter ? null : listNode}

      {slot && m.form
        ? <SlotDialog key={`${slot.dk}|${slot.hour}`} open slot={slot}
                      date={m.date} form={m.form}
                      noteEnds={m.note_ends} busy={busy}
                      onClose={() => setSlot(null)}
                      onAdd={(b) => act(() => day.add(at, doctor, tile, b))}
                      onNote={(b) => act(() => day.note(at, doctor, tile, b))} />
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

      {move
        ? <MoveDialog open drag={move.drag} target={move.target} busy={busy}
                      fromName={doctorName(m, move.drag.dk)}
                      toName={doctorName(m, move.target.dk)}
                      busyAt={clash(m, move.target, move.drag.dur, move.drag.id)}
                      onClose={() => setMove(null)}
                      onMove={() => {
                        const { drag: d, target: t } = move
                        setMove(null)
                        void act(() => day.move(at, doctor, tile, d.id,
                          { date: m.date, time: hhmmOf(t.min), doctor: t.dk }))
                      }} />
        : null}
    </section>
  )
}

/** Минуты в «HH:MM» — тем же видом, что ждёт сервер (`mtime`). */
function hhmmOf(min: number): string {
  return `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`
}
