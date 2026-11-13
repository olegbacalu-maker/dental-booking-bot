import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Occupies } from './move'
import { SlotDialog, type Fail } from './SlotDialog'

/* Окно пустого часа само по себе: минуты старта, занятые по канве, и отказ
   внутри окна.
   ⛔ Отказ печатается В ОКНЕ, а не плашкой экрана: `<dialog>` живёт в top
   layer, и плашка на z-index 80 под ним не видна вовсе. Экран отдаёт слово
   колбэком `fail`. */

const FORM = { services: [{ id: 'consult', label: 'Consultație' }], birth_max: '2026-10-17' }
const SLOT = { dk: 'd2', name: 'Dr. Ion', hour: '10:00' }
const FREE: Occupies[] = []
const busy = (min: number, dur: number): Occupies => ({ id: min, min, dur, busy: true })

const onClose = vi.fn()
const onNote = vi.fn(async () => true)

function show(taken: Occupies[], onAdd: (body: unknown, fail: Fail) => Promise<boolean> =
  async () => true) {
  return render(<SlotDialog open slot={SLOT} date="2026-10-17" form={FORM} noteEnds={[11, 12]}
    taken={taken} busy={false} onClose={onClose} onAdd={onAdd} onNote={onNote} />)
}

const mp = () => Array.from(document.querySelectorAll('.dp-minpick .mp')) as HTMLButtonElement[]
const at = (label: string) => mp().find((b) => b.textContent === label) as HTMLButtonElement
const on = () => mp().filter((b) => b.className.includes(' on')).map((b) => b.textContent)
const off = () => mp().filter((b) => b.disabled).map((b) => b.textContent)
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

describe('окно пустого часа: минута старта шагом 5, занятые — подсказка по канве', () => {
  it('час свободен: двенадцать минут, выбрана :00, все нажимаются', () => {
    show(FREE)
    expect(mp().map((b) => b.textContent)).toEqual(
      [':00', ':05', ':10', ':15', ':20', ':25', ':30', ':35', ':40', ':45', ':50', ':55'])
    expect(off()).toEqual([])
    expect(on()).toEqual([':00'])
    expect(banner()).toBe('')
    expect(submit().disabled).toBe(false)
  })

  it('выбранная минута уходит временем записи и стоит в заголовке', async () => {
    const onAdd = vi.fn<(b: unknown, f: Fail) => Promise<boolean>>(async () => true)
    show(FREE, onAdd)
    fireEvent.click(at(':05'))
    expect(head()).toBe('Dr. Ion — 10:05')
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ time: '10:05' })
  })

  it('занятые минуты не нажать, выбрана сразу первая свободная', () => {
    show([busy(600, 20)])
    expect(off()).toEqual([':00', ':05', ':10', ':15'])
    expect(on()).toEqual([':20'])
    expect(head()).toBe('Dr. Ion — 10:20')
  })

  it('минута щелчка по сетке — выбрана сразу и держится, пока услуга в неё не влезает', () => {
    const form = { ...FORM, services: [{ id: 'consult', label: 'Consultație', dur: 30 }],
      durations: [10, 30], dur_step: 5, dur_max: 240 }
    const open = (minute: number, taken: Occupies[]) =>
      render(<SlotDialog open slot={{ ...SLOT, minute }} date="2026-10-17" form={form}
        noteEnds={[11, 12]} taken={taken} busy={false} onClose={onClose}
        onAdd={async () => true} onNote={onNote} />)
    open(35, FREE)
    expect([on(), head(), banner()]).toEqual([[':35'], 'Dr. Ion — 10:35', ''])
    cleanup()
    /* дыра 10:10–10:20 между визитами: услуга на 30 минут в неё не влезает —
       минута щелчка остаётся, окно говорит почему и не даёт записать */
    open(10, [busy(600, 10), busy(620, 40)])
    expect([on(), head()]).toEqual([[':10'], 'Dr. Ion — 10:10'])
    expect(banner()).toContain('De la 10:10 nu încap 30 min')
    expect(submit().disabled).toBe(true)
    /* длительность 10 минут — влезло */
    fireEvent.change(document.querySelector('dialog .dp-dur') as HTMLElement, { target: { value: '10' } })
    expect([on(), banner(), submit().disabled]).toEqual([[':10'], '', false])
  })

  it('занят весь час: сказано почему, кнопка записи выключена', () => {
    show([busy(600, 60)])
    expect(off()).toHaveLength(12)
    expect(banner()).toBe('Medicul nu are niciun început liber în ora 10:00 pentru 5 min.')
    expect(submit().disabled).toBe(true)
  })

  it('канва обновилась под открытым окном — выбранный старт переставляется на свободный', () => {
    const r = show(FREE)
    fireEvent.click(at(':30'))
    expect(head()).toBe('Dr. Ion — 10:30')
    r.rerender(<SlotDialog open slot={SLOT} date="2026-10-17" form={FORM} noteEnds={[11, 12]}
      taken={[busy(630, 30)]} busy={false} onClose={onClose}
      onAdd={async () => true} onNote={onNote} />)
    expect(head()).toBe('Dr. Ion — 10:00')
    expect(at(':30').disabled).toBe(true)
  })
})

describe('окно пустого часа: отказ сервера — внутри окна', () => {
  it('⛔ отказ печатается в окне, окно остаётся открытым с набранным', async () => {
    const onAdd = vi.fn(async (_b: unknown, fail: Fail) => {
      fail('Intervalul este deja ocupat la acest medic')
      return false
    })
    show(FREE, onAdd)
    fill()
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLElement) })
    await waitFor(() => expect(banner()).toBe('Intervalul este deja ocupat la acest medic'))
    expect(onClose).not.toHaveBeenCalled()
    expect((document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLInputElement).value)
      .toBe('Ion Popa')
  })

  it('удача — окно закрывается, слова отказа нет', async () => {
    const onAdd = vi.fn(async () => true)
    show(FREE, onAdd)
    fill()
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLElement) })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(banner()).toBe('')
  })

  it('смена минуты снимает прежний отказ: следующая попытка — с чистого листа', async () => {
    const onAdd = vi.fn(async (_b: unknown, fail: Fail) => { fail('ocupat'); return false })
    show(FREE, onAdd)
    fill()
    await act(async () => { fireEvent.submit(document.querySelector('dialog form') as HTMLElement) })
    await waitFor(() => expect(banner()).toBe('ocupat'))
    fireEvent.click(at(':30'))
    expect(banner()).toBe('')
  })
})

describe('окно пустого часа: «Durată»', () => {
  const FORM_D = {
    services: [{ id: 'consult', label: 'Consultație', dur: 15 }, { id: 'long', label: 'Tratament lung', dur: 120 }],
    durations: [5, 10, 15, 20, 30, 45, 60, 90, 120], dur_step: 5, dur_max: 240, step: 5,
    birth_max: '2026-10-17',
  }
  const showD = (onAdd: (body: unknown, fail: Fail) => Promise<boolean>, taken: Occupies[] = FREE) =>
    render(<SlotDialog open slot={SLOT} date="2026-10-17" form={FORM_D} noteEnds={[11, 12]}
      taken={taken} busy={false} onClose={onClose} onAdd={onAdd} onNote={onNote} />)
  const durSel = () => document.querySelector('dialog select[aria-label="Durată"]') as HTMLSelectElement
  const durInp = () => document.querySelector('dialog input.dp-dur-n') as HTMLInputElement
  const svcSel = () => document.querySelector('dialog select[aria-label="Serviciu"]') as HTMLSelectElement

  it('нетронутая — длительность услуги, идёт за сменой услуги и НЕ уходит на сервер', async () => {
    const onAdd = vi.fn<(b: unknown, f: Fail) => Promise<boolean>>(async () => true)
    showD(onAdd)
    expect(Array.from(svcSel().options).map((o) => o.textContent))
      .toEqual(['Consultație · 15 min', 'Tratament lung · 120 min'])
    expect(durSel().value).toBe('15')
    fireEvent.change(svcSel(), { target: { value: 'long' } })
    expect(durSel().value).toBe('120')
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd).toHaveBeenCalledTimes(1)
    expect(onAdd.mock.calls[0]?.[0]).not.toHaveProperty('duration')
  })

  it('тронутая — уходит числом и больше не идёт за услугой', async () => {
    const onAdd = vi.fn<(b: unknown, f: Fail) => Promise<boolean>>(async () => true)
    showD(onAdd)
    fireEvent.change(durSel(), { target: { value: '30' } })
    fireEvent.change(svcSel(), { target: { value: 'long' } })
    expect(durSel().value).toBe('30')
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ service: 'long', duration: 30 })
  })

  it('быстрые значения и последней строкой «Altă durată…»', () => {
    showD(async () => true)
    expect(Array.from(durSel().options).map((o) => o.textContent)).toEqual(
      ['5 min', '10 min', '15 min', '20 min', '30 min', '45 min', '60 min', '90 min', '120 min', 'Altă durată…'])
  })

  it('«Altă durată…» — поле минут: 25 уходит числом', async () => {
    const onAdd = vi.fn<(b: unknown, f: Fail) => Promise<boolean>>(async () => true)
    showD(onAdd)
    expect(durInp()).toBeNull()
    fireEvent.change(durSel(), { target: { value: 'other' } })
    expect(durInp().value).toBe('15')
    fireEvent.change(durInp(), { target: { value: '25' } })
    expect(submit().disabled).toBe(false)
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ duration: 25 })
  })

  it('число не по правилу (не кратно 5, больше потолка, пусто) — правило красным, запись выключена', () => {
    showD(async () => true)
    fireEvent.change(durSel(), { target: { value: 'other' } })
    for (const raw of ['52', '245', '']) {
      fireEvent.change(durInp(), { target: { value: raw } })
      expect(document.querySelector('dialog .dp-dur-rule.bad')?.textContent)
        .toBe('din 5 în 5 minute, cel mult 240')
      expect(submit().disabled).toBe(true)
    }
    fireEvent.change(durInp(), { target: { value: '240' } })
    expect(document.querySelector('dialog .dp-dur-rule.bad')).toBeNull()
    expect(submit().disabled).toBe(false)
  })

  it('занятость минут считается с выбранной длительностью', () => {
    /* сосед в 10:40: визит 15 минут влезает до 10:25, пятиминутный — до 10:35 */
    showD(async () => true, [busy(640, 20)])
    expect(off()).toEqual([':30', ':35', ':40', ':45', ':50', ':55'])
    fireEvent.change(durSel(), { target: { value: '5' } })
    expect(off()).toEqual([':40', ':45', ':50', ':55'])
    fireEvent.change(durSel(), { target: { value: '60' } })
    expect(off()).toHaveLength(12)
    expect(banner()).toBe('Medicul nu are niciun început liber în ora 10:00 pentru 60 min.')
  })

  it('сервер не прислал список — поля нет, запись как раньше', () => {
    show(FREE)
    expect(durSel()).toBeNull()
  })
})
