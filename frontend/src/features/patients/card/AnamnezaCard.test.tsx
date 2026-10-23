import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CardActions } from './actions'
import { AnamnezaCard, type AnDraft } from './AnamnezaCard'
import { patientCard, type Anamneza, type PatientCard } from './card'

/* Опросник анамнеза — «Niciuna dintre afecțiunile de mai sus» (Олег 23.10):
   тринадцатая строка списка, взаимоисключающая с двенадцатью. Здесь — что
   клиент снимает другую сторону сам (сервер на оба разом отвечает отказом,
   `test_anamneza.suite_none`), что свободные поля она не трогает и что
   сохранённый ответ виден серым чипом словами медзаписи с датой. Экран
   целиком (полоса в шапке, вкладки) — `PatientCardScreen.test`. */

const FLAGS = [
  { id: 'cardio', label: 'Boli cardiovasculare / hipertensiune' },
  { id: 'diabet', label: 'Diabet zaharat' },
  { id: 'hepatita', label: 'Hepatită' },
]
const NONE = { id: 'niciuna', label: 'Niciuna dintre afecțiunile de mai sus' }
const TEXTS = [{ id: 'alergii', label: 'Alergii (medicamente, materiale)', placeholder: 'ex. penicilină' }]

const ANAM: Anamneza = {
  filled: true, state: 'risk', n_risk: 2, denies: false, flags: ['cardio', 'diabet'],
  texts: { alergii: '' },
  marked: ['Boli cardiovasculare / hipertensiune', 'Diabet zaharat'], free: [],
  when: '18.09.2026', author: 'Director',
}
const DENIES: Anamneza = {
  ...ANAM, state: 'ok', n_risk: 0, denies: true, flags: ['niciuna'], marked: [], when: '03.11.2025',
}

/* Карточке нужны только фиша-носитель опросника и справочники формы. */
const card = (an: Anamneza) => ({
  id: 5, anamneza: an,
  options: { anamneza_flags: FLAGS, anamneza_none: NONE, anamneza_texts: TEXTS },
}) as unknown as PatientCard

/** Экран держит черновик (01.10) — здесь его роль играет хозяин. */
function Host({ an }: { an: Anamneza }) {
  const [draft, setDraft] = useState<AnDraft | null>(null)
  const a: CardActions = {
    pid: 5, views: false, busy: false, back: '/admin/patient/5?tab=date',
    act: async (run) => { await run(); return null },
  }
  return <AnamnezaCard card={card(an)} a={a} draft={draft} onDraft={setDraft} focusTick={0} />
}

const box = (label: string) => screen.getByLabelText(label) as HTMLInputElement
const checked = () => Array.from(document.querySelectorAll<HTMLInputElement>('.anbox input'))
  .filter((i) => i.checked).map((i) => i.closest('label')!.textContent!.trim())

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('опросник: «Niciuna dintre afecțiunile de mai sus» (23.10)', () => {
  it('тринадцатая строка — последняя в списке, на всю ширину (annone); отмечено то, что в flags', () => {
    render(<Host an={ANAM} />)
    const labels = Array.from(document.querySelectorAll('.anbox label'))
    expect(labels.length).toBe(FLAGS.length + 1)
    const last = labels[labels.length - 1]!
    expect(last.className).toBe('annone')
    expect(last.textContent?.trim()).toBe(NONE.label)
    expect(checked()).toEqual(['Boli cardiovasculare / hipertensiune', 'Diabet zaharat'])
  })

  it('отметил «Niciuna…» — двенадцать снимаются; отметил болезнь — «Niciuna…» снимается; снял «Niciuna…» — список пуст', () => {
    render(<Host an={ANAM} />)
    fireEvent.click(box(NONE.label))
    expect(checked()).toEqual([NONE.label])
    fireEvent.click(box('Hepatită'))
    expect(checked()).toEqual(['Hepatită'])
    fireEvent.click(box(NONE.label))
    expect(checked()).toEqual([NONE.label])
    fireEvent.click(box(NONE.label))
    expect(checked()).toEqual([])
  })

  it('свободные поля от «Niciuna…» не зависят: аллергия, набранная до отметки, остаётся', () => {
    render(<Host an={ANAM} />)
    const ta = screen.getByLabelText(/Alergii/) as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: 'penicilină' } })
    fireEvent.click(box(NONE.label))
    expect((screen.getByLabelText(/Alergii/) as HTMLTextAreaElement).value).toBe('penicilină')
    expect(checked()).toEqual([NONE.label])
  })

  it('сохранение шлёт один ключ «niciuna» и свободные поля как есть', async () => {
    const save = vi.spyOn(patientCard, 'saveAnamneza')
      .mockResolvedValue({ data: card(DENIES), code: 'ok_anam', text: 'Anamneza a fost salvată', tone: 'ok' })
    render(<Host an={ANAM} />)
    fireEvent.click(box(NONE.label))
    fireEvent.click(screen.getByRole('button', { name: /Salvează anamneza/ }))
    await waitFor(() => expect(save).toHaveBeenCalledWith(5, false, ['niciuna'], { alergii: '' }))
  })

  it('сохранённый ответ: пилюля «fără riscuri», серый чип словами медзаписи, дата в «Completat»; черновика нет', () => {
    render(<Host an={DENIES} />)
    expect(document.querySelector('.pill.green')?.textContent).toBe('fără riscuri')
    expect(Array.from(document.querySelectorAll('.anlist span')).map((e) => [e.className, e.textContent?.trim()]))
      .toEqual([['none', 'Neagă afecțiunile din chestionar']])
    expect(document.querySelector('.hint')?.textContent).toContain('Completat: 03.11.2025')
    expect(screen.queryByText('modificări nesalvate')).toBeNull()
    expect(box(NONE.label).checked).toBe(true)
  })
})
