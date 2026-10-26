import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../../types/api'
import type { CardActions } from './actions'
import { OcluziaCard, ocDirty, type OcDraft } from './OcluziaCard'
import { patientCard, type Ocluzie, type PatientCard } from './card'

/* Прикус — графа «Ocluzia» 043/e (26.10). Здесь: не записан — серая пилюля и
   раскрытая форма; записан — сводка словами листа, дата и автор, форма
   свёрнута; черновик у хозяина, «modificări nesalvate»; сохранение шлёт ВСЕ
   поля (отсутствующий ключ сервер читал бы как «не сообщали»); поле из отказа
   сервера подсвечивается. Сервер и бумага — `test_ocluzie`. */

const EMPTY_FIELDS = { angle_dr: '', angle_st: '', overjet: '', overbite: '', incrucisata: '', deschisa: '', mediana_mm: '', mediana_spre: '', nota: '', doctor: '' }
const NONE: Ocluzie = { filled: false, fields: EMPTY_FIELDS, summary: '', when: '', author: '' }
const FULL: Ocluzie = {
  filled: true,
  fields: { ...EMPTY_FIELDS, angle_dr: 'I', angle_st: 'II/1', overjet: '3', overbite: '2.5', mediana_mm: '2', mediana_spre: 'dreapta', doctor: 'Dr. Activ Doi' },
  summary: 'Angle dr. I, stg. II/1 · overjet 3 mm · overbite 2.5 mm · linia mediană: 2 mm spre dreapta',
  when: '26.10.2026', author: 'Director',
}
const OPTS = {
  ocluzie: {
    angle: [{ id: '', label: 'neevaluat' }, { id: 'I', label: 'I' }, { id: 'II/1', label: 'II/1' }, { id: 'III', label: 'III' }],
    sides: [{ id: '', label: '—' }, { id: 'dreapta', label: 'dreapta' }, { id: 'stanga', label: 'stânga' }],
  },
  doctors: ['Dr. Activ Doi', 'Dr. Trei'],
}
const card = (oc: Ocluzie) => ({ id: 5, ocluzie: oc, options: OPTS }) as unknown as PatientCard

function Host({ oc, act }: { oc: Ocluzie; act?: CardActions['act'] }) {
  const [draft, setDraft] = useState<OcDraft | null>(null)
  const a: CardActions = {
    pid: 5, views: false, busy: false, back: '/admin/patient/5?tab=date',
    act: act ?? (async (run) => { await run(); return null }),
  }
  return <OcluziaCard card={card(oc)} a={a} draft={draft} onDraft={setDraft} />
}

const details = () => document.querySelector('details.anform') as HTMLDetailsElement

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('OcluziaCard — графа «Ocluzia» 043/e (26.10)', () => {
  it('не записана: серая пилюля (не риск), подсказка, форма раскрыта, Angle начинается с «neevaluat»', () => {
    render(<Host oc={NONE} />)
    expect(document.querySelector('.pill.grey')?.textContent).toBe('neînregistrată')
    expect(document.querySelector('.hint')?.textContent).toContain('Nu a fost înregistrată')
    expect(details().open).toBe(true)
    const dr = screen.getByLabelText('dreapta') as HTMLSelectElement
    expect(Array.from(dr.options).map((o) => o.textContent)).toEqual(['neevaluat', 'I', 'II/1', 'III'])
    expect(dr.value).toBe('')
    expect(document.querySelector('.ocsum')).toBeNull()
  })

  it('записана: сводка словами листа, дата и автор, форма свёрнута с полями записи', () => {
    render(<Host oc={FULL} />)
    expect(document.querySelector('.ocsum')?.textContent).toBe(FULL.summary)
    expect(document.querySelector('.hint')?.textContent).toContain('Înregistrat: 26.10.2026 · Director')
    expect(document.querySelector('.pill.grey')).toBeNull()
    expect(details().open).toBe(false)
    expect((screen.getByLabelText('stânga') as HTMLSelectElement).value).toBe('II/1')
    expect((screen.getByLabelText('Overbite (mm)') as HTMLInputElement).value).toBe('2.5')
    expect((screen.getByLabelText('Medic') as HTMLSelectElement).value).toBe('Dr. Activ Doi')
  })

  it('записана, но снята до пустой — «înregistrare goală», сводки нет', () => {
    render(<Host oc={{ ...FULL, fields: EMPTY_FIELDS, summary: '' }} />)
    expect(document.querySelector('.pill.grey')?.textContent).toBe('înregistrare goală')
    expect(document.querySelector('.ocsum')).toBeNull()
  })

  it('правка — «modificări nesalvate»; сохранение шлёт ВСЕ поля формы разом', async () => {
    const save = vi.spyOn(patientCard, 'saveOcluzie')
      .mockResolvedValue({ data: card(FULL), code: 'ok_occl', text: 'Ocluzia a fost salvată', tone: 'ok' })
    render(<Host oc={FULL} />)
    expect(screen.queryByText('modificări nesalvate')).toBeNull()
    fireEvent.change(screen.getByLabelText('Overjet (mm)'), { target: { value: '4,5' } })
    expect(screen.getByText('modificări nesalvate')).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/Ocluzie deschisă/), { target: { value: 'frontal' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează ocluzia/ }))
    await waitFor(() => expect(save).toHaveBeenCalledWith(5, false, { ...FULL.fields, overjet: '4,5', deschisa: 'frontal' }))
  })

  it('ocDirty: черновик привязан к записи — другая запись (свежая фиша) черновик не считает', () => {
    const d: OcDraft = { oc: FULL, fields: { ...FULL.fields, nota: 'x' } }
    expect(ocDirty(d, FULL)).toBe(true)
    expect(ocDirty(d, { ...FULL })).toBe(false)
    expect(ocDirty({ oc: FULL, fields: { ...FULL.fields, nota: ' ' } }, FULL)).toBe(false)
  })

  it('отказ сервера с полем — поле подсвечено; не число в мм подсвечено ещё до отправки', async () => {
    const err = new ApiError({ kind: 'validation', code: 'bad_occl_val', text: 'verificați câmpul', field: 'angle_dr' }, 'verificați câmpul')
    render(<Host oc={FULL} act={async () => err} />)
    /* ⚠️ кадр 26.10: «не число» красило и Angle «I», и «13–43» — только мм */
    expect(document.querySelectorAll('.ocform .is-bad').length).toBe(0)
    fireEvent.change(screen.getByLabelText('Overjet (mm)'), { target: { value: 'mult' } })
    expect(screen.getByLabelText('Overjet (mm)').closest('label')?.className).toContain('is-bad')
    fireEvent.change(screen.getByLabelText('Overjet (mm)'), { target: { value: '-1,5' } })
    expect(screen.getByLabelText('Overjet (mm)').closest('label')?.className).not.toContain('is-bad')
    fireEvent.click(screen.getByRole('button', { name: /Salvează ocluzia/ }))
    await waitFor(() => expect(screen.getByLabelText('dreapta').closest('label')?.className).toContain('is-bad'))
  })
})
