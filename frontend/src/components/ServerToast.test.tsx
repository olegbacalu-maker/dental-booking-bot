import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ServerToast } from './ServerToast'
import { allowMotion } from '../test/motion'

/* Плашка ответа сервера (`frame.msg`, разметка `messages.msg_banner`): крестик
   закрывает её сразу, повтор той же модели (опрос, перерисовка) её не
   возвращает; новый документ с тем же ответом — новый повод. */

const html = (kind: string, text: string) =>
  `<div class='toastbox' id='dp_toast' data-kind='${kind}' role='status'>`
  + `<div class='banner ${kind}'>${text}`
  + `<button class='t-x' type='button' aria-label='Închide'>x</button></div></div>`

const TERMS = html('ok', 'Ați acceptat versiunea actualizată a Termenilor și condițiilor DentPilot')
const DENY = html('err', 'Nu aveți acces')

beforeEach(() => { window.history.replaceState({ idx: 3, key: 'k' }, '', '/admin?msg=license_terms_ok&date=2026-11-26') })
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const closeBtn = () => screen.getByRole('button', { name: 'Închide' })

describe('ServerToast: крестик', () => {
  it('без движения крестик снимает плашку сразу, повтор той же модели её не возвращает', () => {
    const frame = { msg: DENY }
    const prose = vi.fn()
    const { rerender } = render(<ServerToast frame={frame} prose={prose} />)
    fireEvent.click(closeBtn())
    expect(document.querySelector('.toastbox')).toBeNull()
    expect(prose).not.toHaveBeenCalled()
    rerender(<ServerToast frame={frame} prose={prose} />)
    expect(document.querySelector('.toastbox')).toBeNull()
  })

  it('с движением — сперва класс out, через ступень плашки нет', () => {
    allowMotion()
    vi.useFakeTimers()
    const frame = { msg: DENY }
    render(<ServerToast frame={frame} prose={vi.fn()} />)
    fireEvent.click(closeBtn())
    expect(document.querySelector('.toastbox')?.className).toContain('out')
    act(() => { vi.advanceTimersByTime(300) })
    expect(document.querySelector('.toastbox')).toBeNull()
  })

  it('отказ висит, пока не закроют; успех гаснет сам через 6 секунд', () => {
    vi.useFakeTimers()
    const { unmount } = render(<ServerToast frame={{ msg: DENY }} prose={vi.fn()} />)
    act(() => { vi.advanceTimersByTime(10_000) })
    expect(document.querySelector('.toastbox')).not.toBeNull()
    unmount()
    render(<ServerToast frame={{ msg: TERMS }} prose={vi.fn()} />)
    act(() => { vi.advanceTimersByTime(6_050) })
    expect(document.querySelector('.toastbox')).toBeNull()
  })

  it('новый документ с тем же ответом — плашка снова, без класса ухода', () => {
    allowMotion()
    vi.useFakeTimers()
    const { rerender } = render(<ServerToast frame={{ msg: DENY }} prose={vi.fn()} />)
    fireEvent.click(closeBtn())
    rerender(<ServerToast frame={{ msg: DENY }} prose={vi.fn()} />)
    act(() => { vi.advanceTimersByTime(300) })
    const box = document.querySelector('.toastbox')
    expect(box).not.toBeNull()
    expect(box?.className).not.toContain('out')
  })

  it('msg уходит из адреса, состояние записи истории роутера цело', () => {
    render(<ServerToast frame={{ msg: TERMS }} prose={vi.fn()} />)
    expect(window.location.search).toBe('?date=2026-11-26')
    expect(window.history.state).toEqual({ idx: 3, key: 'k' })
  })

  it('щелчок по тексту и ссылкам уходит в обработчик прозы', () => {
    const prose = vi.fn()
    render(<ServerToast frame={{ msg: DENY }} prose={prose} />)
    fireEvent.click(screen.getByText('Nu aveți acces'))
    expect(prose).toHaveBeenCalledTimes(1)
    expect(document.querySelector('.toastbox')).not.toBeNull()
  })
})
