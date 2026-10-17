import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SlotDialog, type Fail } from './SlotDialog'
import type { FreeHalves } from './slot'

/* Окно пустого часа само по себе (17.10): занятые старты и отказ внутри окна.
   ⛔ Отказ печатается В ОКНЕ, а не плашкой экрана: `<dialog>` живёт в top
   layer, и плашка на z-index 80 под ним не видна вовсе — так «интервал
   занят» и терялся у Олега. Экран отдаёт слово колбэком `fail`. */

const FORM = { services: [{ id: 'consult', label: 'Consultație' }], birth_max: '2026-10-17' }
const SLOT = { dk: 'd2', name: 'Dr. Ion', hour: '10:00' }
const BOTH: FreeHalves = { h0: true, h30: true }

const onClose = vi.fn()
const onNote = vi.fn(async () => true)

function show(free: FreeHalves, onAdd: (body: unknown, fail: Fail) => Promise<boolean> =
  async () => true) {
  return render(<SlotDialog open slot={SLOT} date="2026-10-17" form={FORM} noteEnds={[11, 12]}
    free={free} busy={false} onClose={onClose} onAdd={onAdd} onNote={onNote} />)
}

const hp = () => Array.from(document.querySelectorAll('.halfpick .hp')) as HTMLButtonElement[]
const head = () => document.querySelector('.dlg-head span')?.textContent
const banner = () => document.querySelector('dialog .banner.err')?.textContent ?? ''
const submit = () => document.querySelector('dialog form button:not([type="button"])') as HTMLButtonElement

const fill = () => {
  fireEvent.change(document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLElement,
    { target: { value: 'Ion Popa' } })
  fireEvent.change(document.querySelector('dialog input[placeholder="Telefon"]') as HTMLElement,
    { target: { value: '069000000' } })
}

afterEach(() => { cleanup(); onClose.mockClear() })

describe('окно пустого часа: занятые старты — подсказка по канве', () => {
  it('оба свободны: как прежде, :00 выбран, оба нажимаются', () => {
    show(BOTH)
    expect(hp().map((b) => b.disabled)).toEqual([false, false])
    expect(hp()[0]?.className).toContain('on')
    expect(banner()).toBe('')
    expect(submit().disabled).toBe(false)
  })

  it('занятый :00 — не нажать, словом «ocupat», а выбран сразу :30', () => {
    show({ h0: false, h30: true })
    expect(hp()[0]?.disabled).toBe(true)
    expect(hp()[0]?.textContent).toContain('ocupat')
    expect(hp()[1]?.className).toContain('on')
    expect(head()).toBe('Dr. Ion — 10:30')
  })

  it('оба заняты: сказано почему, кнопка записи выключена', () => {
    show({ h0: false, h30: false })
    expect(banner()).toBe('Medicul are deja programări la 10:00 și 10:30.')
    expect(submit().disabled).toBe(true)
  })

  it('канва обновилась под открытым окном — выбранный старт переставляется на свободный', () => {
    const r = show(BOTH)
    fireEvent.click(hp()[1] as HTMLElement)
    expect(head()).toBe('Dr. Ion — 10:30')
    r.rerender(<SlotDialog open slot={SLOT} date="2026-10-17" form={FORM} noteEnds={[11, 12]}
      free={{ h0: true, h30: false }} busy={false} onClose={onClose}
      onAdd={async () => true} onNote={onNote} />)
    expect(head()).toBe('Dr. Ion — 10:00')
    expect(hp()[1]?.disabled).toBe(true)
  })
})

describe('окно пустого часа: отказ сервера — внутри окна', () => {
  it('⛔ отказ печатается в окне, окно остаётся открытым с набранным', async () => {
    const onAdd = vi.fn(async (_b: unknown, fail: Fail) => {
      fail('Intervalul este deja ocupat la acest medic')
      return false
    })
    show(BOTH, onAdd)
    fill()
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLElement) })
    await waitFor(() => expect(banner()).toBe('Intervalul este deja ocupat la acest medic'))
    expect(onClose).not.toHaveBeenCalled()
    expect((document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLInputElement).value)
      .toBe('Ion Popa')
  })

  it('удача — окно закрывается, слова отказа нет', async () => {
    const onAdd = vi.fn(async () => true)
    show(BOTH, onAdd)
    fill()
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLElement) })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(banner()).toBe('')
  })

  it('смена получаса снимает прежний отказ: следующая попытка — с чистого листа', async () => {
    const onAdd = vi.fn(async (_b: unknown, fail: Fail) => { fail('ocupat'); return false })
    show(BOTH, onAdd)
    fill()
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLElement) })
    await waitFor(() => expect(banner()).toBe('ocupat'))
    fireEvent.click(hp()[1] as HTMLElement)
    expect(banner()).toBe('')
  })
})
