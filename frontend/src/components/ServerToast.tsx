import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react'
import { motionOk, stepMs } from '../utils/motion'

/** Адрес без `msg`: F5 и «назад» не должны показывать прежний ответ как свежий. */
function dropMsg(): void {
  try {
    const u = new URL(window.location.href)
    if (!u.searchParams.has('msg')) return
    u.searchParams.delete('msg')
    // состояние записи истории — роутера (ключ, номер): подменяется только адрес
    window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash)
  } catch { /* без адреса ответ покажется при F5 ещё раз — не страшно */ }
}

/**
 * Плашка ответа сервера (`frame.msg`, разметка `messages.msg_banner`) — то же
 * поведение, что у `Toast`: крестик, успех гаснет сам через 6 секунд, отказ и
 * предупреждение висят до крестика. Разметка серверная, поэтому обработчик —
 * на контейнере, а тон читается из `data-kind`.
 *
 * Закрытие помнится для ЭТОГО документа (`frame` — новый объект на каждой
 * загрузке оболочки): та же модель плашку не вернёт, следующий ответ сервера,
 * даже с тем же текстом, покажется снова.
 */
export function ServerToast({ frame, prose }: {
  frame: { msg: string }
  prose: (e: MouseEvent<HTMLElement>) => void
}) {
  const [closedFor, setClosedFor] = useState<object | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const going = useRef<number | null>(null)
  const shown = frame.msg !== '' && closedFor !== frame

  const leave = useCallback(() => {
    const el = box.current?.querySelector('.toastbox')
    if (!motionOk() || !el) { setClosedFor(frame); return }
    el.classList.add('out')
    if (going.current !== null) window.clearTimeout(going.current)
    going.current = window.setTimeout(() => setClosedFor(frame), stepMs('--dur'))
  }, [frame])

  useEffect(() => {
    if (!shown) return
    dropMsg()
    const kind = box.current?.querySelector('[data-kind]')?.getAttribute('data-kind')
    if (kind !== 'ok') return
    const timer = window.setTimeout(leave, 6000)
    return () => window.clearTimeout(timer)
  }, [shown, leave])
  useEffect(() => () => { if (going.current !== null) window.clearTimeout(going.current) }, [])
  /* Новая модель с тем же текстом: React разметку не перерисует, и класс ухода
     прежней плашки остался бы на ней — снимаем его вместе с недоигранным уходом. */
  useLayoutEffect(() => {
    if (going.current !== null) { window.clearTimeout(going.current); going.current = null }
    box.current?.querySelector('.toastbox')?.classList.remove('out')
  }, [frame])

  if (!shown) return null
  const click = (e: MouseEvent<HTMLDivElement>) => {
    if ((e.target as Element).closest?.('.t-x')) { leave(); return }
    prose(e)
  }
  return <div ref={box} onClick={click} dangerouslySetInnerHTML={{ __html: frame.msg }} />
}
