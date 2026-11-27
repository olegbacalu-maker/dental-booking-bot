import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DeskCard } from './DeskCard'
import type { Desk, DeskConfirm, DeskConfirmItem } from './desk'

/* «De confirmat» и ответ пациента ссылкой (Premium, волна 2а): порядок и счёт — сервера
   (`desk._confirm_list`: «Nu poate veni» наверху, `n_cant`), экран — вид. Фикстуры только этих проверок. */

const row = (over: Partial<DeskConfirmItem>): DeskConfirmItem => ({
  id: 1, pid: 11, time: '10:00', name: 'Popescu Ana', phone: '069 000 111', doctor: 'Dr. Rusu', service: '',
  call: '', call_via: '', call_at: '', answer_at: '', call_by: '', ...over,
})

const list = (items: DeskConfirmItem[], over: Partial<DeskConfirm> = {}): DeskConfirm => ({
  day: 'luni 30.11', date: '2026-11-30', items, n: items.length,
  n_ok: items.filter((x) => x.call === 'ok').length,
  n_left: items.filter((x) => !x.call).length,
  n_cant: items.filter((x) => x.call === 'cant').length, ...over,
})

const EMPTY = list([], { day: 'azi', date: '2026-11-27' })

const desk = (confirm: DeskConfirm): Desk => ({
  confirm_today: EMPTY, confirm,
  unscheduled: { items: [], n: 0, sum_s: '0' }, unclosed: { items: [], n: 0 }, lost: { items: [], n: 0 },
  collect: null, free: [], recall: null, answers: null,
})

afterEach(() => { cleanup(); localStorage.clear() })

describe('DeskCard — «De confirmat» с ответами ссылкой', () => {
  const ITEMS = [
    row({ id: 3, time: '14:30', name: 'Popescu Ana', call: 'cant', call_via: 'sms', call_at: '10:04' }),
    row({ id: 1, time: '09:00', name: 'Ion Lupu' }),
    row({ id: 2, time: '10:00', name: 'Rotaru Mihai', call: 'ok', call_via: 'sms', call_at: '09:12' }),
    row({ id: 4, time: '11:00', name: 'Vasile Cebotari', call: 'ok', call_via: '', call_at: '08:40' }),
  ]

  it('порядок сервера как есть, «Nu poate veni» наверху; раздел — цветом предупреждения; в счёте звонков и они', () => {
    render(<DeskCard desk={desk(list(ITEMS))} busy={false} onCall={() => {}} />)
    const rows = Array.from(document.querySelectorAll('[data-fold="desk:confirm"] .dk-row'))
    expect(rows.map((r) => r.getAttribute('data-appt'))).toEqual(['3', '1', '2', '4'])
    const cnt = document.querySelector('[data-fold="desk:confirm"] .dk-cnt') as HTMLElement
    expect(cnt.textContent).toBe('2 din 4')                    // не звонили 1 + «nu poate veni» 1
    expect(cnt.classList.contains('amber')).toBe(true)
    expect(document.querySelector('[data-fold="desk:confirm"] .dk-ico')!.classList.contains('amber')).toBe(true)
  })

  it('отметки словами: «nu poate veni · SMS» жёлтым с трубкой, «confirmat · SMS» у ответа, «confirmat» у звонка', () => {
    render(<DeskCard desk={desk(list(ITEMS))} busy={false} onCall={() => {}} />)
    const mark = (id: number) => document.querySelector(`[data-appt="${id}"] .dk-b small:last-child`) as HTMLElement
    expect(mark(3).textContent).toBe(' nu poate veni · SMS 10:04')
    expect(mark(3).className).toBe('dk-no dk-cant')
    expect(mark(3).querySelector('svg')).toBeTruthy()
    expect(document.querySelector('[data-appt="3"]')!.classList.contains('cant')).toBe(true)
    expect(mark(2).textContent).toBe(' confirmat · SMS 09:12')
    expect(mark(2).className).toBe('dk-ok')
    expect(mark(4).textContent).toBe(' confirmat 08:40')
  })

  it('у «Nu poate veni»: «Confirmat» (стойка дозвонилась) и «Anulează bifa», без «Nu răspunde»', () => {
    const onCall = vi.fn()
    render(<DeskCard desk={desk(list(ITEMS))} busy={false} onCall={onCall} />)
    const btns = Array.from(document.querySelectorAll('[data-appt="3"] .dk-act button')) as HTMLButtonElement[]
    expect(btns.map((b) => b.title)).toEqual(['Confirmat', 'Anulează bifa'])
    fireEvent.click(btns[0]!)
    expect(onCall).toHaveBeenLastCalledWith(3, 'ok')
    fireEvent.click(btns[1]!)
    expect(onCall).toHaveBeenLastCalledWith(3, '')
  })

  it('без ответов ссылкой — прежний вид: синий счёт «осталось», зелёный «toți»', () => {
    render(<DeskCard desk={desk(list([row({ id: 1 }), row({ id: 2, call: 'ok', call_at: '09:00' })]))} busy={false}
      onCall={() => {}} />)
    const cnt = document.querySelector('[data-fold="desk:confirm"] .dk-cnt') as HTMLElement
    expect([cnt.textContent, cnt.classList.contains('blue')]).toEqual(['1 din 2', true])
    cleanup()
    // сервер до волны 2а: `n_cant` нет вовсе
    const old = list([row({ id: 2, call: 'ok', call_at: '09:00' })])
    delete old.n_cant
    render(<DeskCard desk={desk(old)} busy={false} onCall={() => {}} />)
    const all = document.querySelector('[data-fold="desk:confirm"] .dk-cnt') as HTMLElement
    expect([all.textContent, all.classList.contains('green')]).toEqual(['toți 1', true])
  })
})
