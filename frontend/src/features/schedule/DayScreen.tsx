import { useCallback, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { useNavigate, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { shift } from '../../utils/date'
import { AddForm } from './AddForm'
import { CardDialog } from './CardDialog'
import { CardMenu, type CardMenuAt } from './CardMenu'
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
 */
export const loadDay: RouteLoad<DayModel> = (signal, p, q) =>
  day.get(queryParam(q, 'date'), p.dk ?? '', queryParam(q, 'f'), signal)

export function DayScreen({ doctor = '', navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<DayModel>(navigate)
  const to = useNavigate()
  const [q] = useSearchParams()
  /* День действий — дата АДРЕСА как есть, без своей копии: пусто так и
     уходит пустым, и «сегодня» решает сервер в момент запроса (после
     полуночи — уже новый день), а не браузер и не первая загрузка. */
  const at = queryParam(q, 'date')
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [slot, setSlot] = useState<Slot | null>(null)
  const [card, setCard] = useState<number | null>(null)
  /* Меню по правой кнопке — те же исходы, что в диалоге, у курсора. */
  const [menu, setMenu] = useState<CardMenuAt | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
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
  const openCard = card !== null ? m.cards[String(card)] : undefined
  const menuCard = menu !== null ? m.cards[String(menu.id)] : undefined
  const openMenu = (id: number, x: number, y: number) => setMenu({ id, x, y })
  const listNode = (
    <DayList model={m} busy={busy} onCard={setCard} onCardMenu={openMenu} onAll={() => go(m.date, '')}
             onStatus={(id, to) => { void act(() => day.status(at, doctor, tile, id, to)) }} />
  )

  return (
    <section className="dp-react-root">
      {toast ? <Toast tone={toast.tone} text={toast.text} onClose={closeToast} /> : null}
      <div className="nav">
        <b>{m.date}</b>
        <AppLink href={`${base}?date=${shift(m.date, -1)}`}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, -1)) }}>
          <Icon name="chev-l" /> {T.prevDay}
        </AppLink>
        <AppLink href={base} onClick={(e) => { e.preventDefault(); go('') }}>{T.today}</AppLink>
        <AppLink href={`${base}?date=${shift(m.date, 1)}`}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, 1)) }}>
          {T.prevDay} <Icon name="chev-r" />
        </AppLink>
        <AppLink href={`/admin?date=${m.date}`}><Icon name="home" /> {T.panel}</AppLink>
        {doctor ? null : (
          <AppLink href={`/admin/export.xlsx?from=${m.date}&to=${m.date}`}>
            <Icon name="download" /> {T.excel}
          </AppLink>
        )}
        {doctor
          ? <AppLink href={`/admin/all?date=${m.date}`}><Icon name="clipboard" /> {T.all}</AppLink>
          : null}
        <AppLink className="primary" href={`${base}?date=${m.date}&ui=legacy`}>{T.legacy}</AppLink>
      </div>

      {/* ⚠️ Место списка зависит от отбора, и это не косметика: пришедший с
          плитки панели дня должен увидеть СВОИ строки сразу, а не под сеткой
          и формой. Полный список остаётся внизу, как на старой странице. */}
      {m.filter ? listNode : null}

      <DayGrid model={m} drag={drag} hover={hover}
               onDrag={setDrag} onHover={setHover} onDrop={onDrop}
               onPlus={(dk, name, hour) => setSlot({ dk, name, hour })}
               onCard={setCard} onCardMenu={openMenu} />

      {/* ⛔ Ключ — день экрана. Форма засевает дату один раз, а переход по
          дням идёт роутером и экземпляр не пересоздаёт: без ключа форма
          показывала первый день вкладки и записывала в него. Смена дня
          начинает форму заново, как перезагрузка старой страницы (Олег
          24.09); ответ действия приносит тот же день, и набор не трогает. */}
      {m.form
        ? <AddForm key={m.date} form={m.form} date={m.date} busy={busy}
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
