import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowMotion } from '../../test/motion'
import { ANSWER_MAX, ANSWER_MS, answerDay, answerKey, answerKeys, newAnswers, stackAnswers, type AnswerPlate } from './answers'
import { AnswerToasts } from './AnswerToasts'
import type { DeskAnswer, DeskConfirm } from './desk'

/* Плашка «пациент ответил» (Premium, вид A): что новое, что старое, ночь, выключено, стопка,
   таймер. Новое — только разницей двух конвертов (`desk.answers`), как `fresh` и `moved`. */

const A = (id: number, call: 'ok' | 'cant', at = '2026-11-27T08:04:00Z', name = `Pacient ${id}`): DeskAnswer =>
  ({ id, pid: 100 + id, name, call, when: 'luni 30.11, 14:30', answer_at: at })

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('answers: что всплывает', () => {
  it('⛔ первый показ (открыли главную, утро после ночных ответов) — ничего', () => {
    expect(newAnswers(null, [A(1, 'ok'), A(2, 'cant')])).toEqual([])
  })

  it('новое с прошлого опроса — по паре id + answer_at + call; прежнее не всплывает снова', () => {
    const prev = answerKeys([A(1, 'ok')])
    expect(newAnswers(prev, [A(1, 'ok'), A(2, 'cant')])).toEqual([A(2, 'cant')])
    expect(newAnswers(answerKeys([A(1, 'ok'), A(2, 'cant')]), [A(1, 'ok'), A(2, 'cant')])).toEqual([])
    // пациент передумал: тот же визит, другой ответ и время — новая плашка
    const changed = A(1, 'cant', '2026-11-27T09:00:00Z')
    expect(newAnswers(prev, [changed])).toEqual([changed])
    expect(answerKey(changed)).toBe('1|2026-11-27T09:00:00Z|cant')
  })

  it('`answers === null` (нет права, ссылки или галочки) — плашек нет, и память забывается', () => {
    expect(newAnswers(answerKeys([A(1, 'ok')]), null)).toEqual([])
    expect(answerKeys(null)).toBeNull()
    // галочку включили снова: следующий конверт — снова «первый показ», старое не выплёскивается
    expect(newAnswers(answerKeys(null), [A(1, 'ok'), A(2, 'ok')])).toEqual([])
  })

  it(`стопка не больше ${ANSWER_MAX}: новая снизу, лишняя сверху уходит; новый ответ того же визита заменяет прежний`, () => {
    let s: AnswerPlate[] = stackAnswers([], [A(1, 'ok'), A(2, 'cant')])
    s = stackAnswers(s, [A(3, 'ok')])
    expect(s.map((p) => p.a.id)).toEqual([1, 2, 3])
    s = stackAnswers(s, [A(4, 'cant')])
    expect(s.map((p) => p.a.id)).toEqual([2, 3, 4])
    s = stackAnswers(s, [A(3, 'cant', '2026-11-27T10:00:00Z')])
    expect(s.map((p) => [p.a.id, p.a.call])).toEqual([[2, 'cant'], [4, 'cant'], [3, 'cant']])
  })

  it('день визита — из списка обзвона, где он стоит; нет — null', () => {
    const day = (date: string, ids: number[]): DeskConfirm => ({
      day: '', date, n: ids.length, n_ok: 0, n_left: 0,
      items: ids.map((id) => ({ id, pid: id, time: '10:00', name: '', phone: '', doctor: '', service: '',
        call: '', call_at: '', call_by: '' })),
    })
    const lists = [day('2026-11-27', [1]), day('2026-11-30', [2])]
    expect(answerDay(A(2, 'ok'), lists)).toBe('2026-11-30')
    expect(answerDay(A(1, 'ok'), lists)).toBe('2026-11-27')
    expect(answerDay(A(9, 'ok'), lists)).toBeNull()
  })
})

describe('AnswerToasts: вид A и таймер', () => {
  const plates = (...a: DeskAnswer[]) => stackAnswers([], a)

  it('строка вида A: имя и день визита жирно, хвост словом; «Nu poate veni» — трубка и класс cant', () => {
    render(<AnswerToasts plates={plates(A(1, 'cant', undefined, 'Popescu Ana'), A(2, 'ok', undefined, 'Rotaru Mihai'))}
      onOpen={() => {}} onGone={() => {}} />)
    const rows = Array.from(document.querySelectorAll('.toastbox.dp-ans .banner.dp-ans-t'))
    expect(rows.map((r) => r.textContent)).toEqual([
      'Popescu Ana · luni 30.11, 14:30 — nu poate veni (SMS)',
      'Rotaru Mihai · luni 30.11, 14:30 — a confirmat prin SMS',
    ])
    expect(rows[0]!.classList.contains('cant')).toBe(true)
    expect(rows[1]!.classList.contains('cant')).toBe(false)
    // значки — наши SVG (Icon), не знаки Windows
    expect(rows.every((r) => r.querySelector('.dp-ans-open svg'))).toBe(true)
  })

  it('пусто — ничего в разметке', () => {
    render(<AnswerToasts plates={[]} onOpen={() => {}} onGone={() => {}} />)
    expect(document.querySelector('.dp-ans')).toBeNull()
  })

  it(`«Vin» уходит сама через ${ANSWER_MS / 1000} с (сперва гаснет), «Nu poate veni» висит до крестика`, () => {
    vi.useFakeTimers()
    allowMotion()
    const onGone = vi.fn()
    const p = plates(A(1, 'cant'), A(2, 'ok'))
    render(<AnswerToasts plates={p} onOpen={() => {}} onGone={onGone} />)
    act(() => { vi.advanceTimersByTime(ANSWER_MS - 1) })
    expect(document.querySelector('.dp-ans-w.out')).toBeNull()
    act(() => { vi.advanceTimersByTime(1) })
    expect(document.querySelector('[data-appt="2"]')!.closest('.dp-ans-w')!.classList.contains('out')).toBe(true)
    expect(onGone).not.toHaveBeenCalled()                          // гаснет ступень, потом уходит
    act(() => { vi.advanceTimersByTime(1000) })
    expect(onGone).toHaveBeenCalledWith(p[1]!.key)
    expect(onGone).toHaveBeenCalledTimes(1)
    act(() => { vi.advanceTimersByTime(60_000) })                  // «Nu poate veni» висит
    expect(onGone).toHaveBeenCalledTimes(1)
    fireEvent.click(document.querySelector('[data-appt="1"] .t-x')!)
    act(() => { vi.advanceTimersByTime(1000) })
    expect(onGone).toHaveBeenLastCalledWith(p[0]!.key)
  })

  it('без движения — уходит сразу, без затухания', () => {
    vi.useFakeTimers()
    const onGone = vi.fn()
    const p = plates(A(2, 'ok'))
    render(<AnswerToasts plates={p} onOpen={() => {}} onGone={onGone} />)
    act(() => { vi.advanceTimersByTime(ANSWER_MS) })
    expect(onGone).toHaveBeenCalledWith(p[0]!.key)
  })

  it('нажатие на плашку открывает визит и убирает плашку', () => {
    const onOpen = vi.fn()
    const onGone = vi.fn()
    const p = plates(A(7, 'cant'))
    render(<AnswerToasts plates={p} onOpen={onOpen} onGone={onGone} />)
    fireEvent.click(document.querySelector('.dp-ans-open')!)
    expect(onOpen).toHaveBeenCalledWith(p[0]!.a)
    expect(onGone).toHaveBeenCalledWith(p[0]!.key)
  })
})
