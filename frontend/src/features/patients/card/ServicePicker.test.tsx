import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { pickGroups, priceLabel, ServicePicker, type PickOption } from './ServicePicker'

/* Прайс как его отдаёт сервер (`prices.options(plan)`): по порядку категорий, «Fără categorie» — последней. */
const S: PickOption[] = [
  { id: 's1', label: 'Restaurare dentară pe 1 suprafață', ru: 'Пломба на 1 поверхность', cat: 'c1', cat_name: 'Terapie', price: 900 },
  { id: 's2', label: 'Restaurare dentară pe 2 suprafețe', ru: 'Пломба на 2 поверхности', cat: 'c1', cat_name: 'Terapie', price: 1200 },
  { id: 's3', label: 'Tratament endodontic – 3 canale', cat: 'c1', cat_name: 'Terapie', price: null, price_hint: '1800–2400 MDL' },
  { id: 's4', label: 'Coroană din zirconiu', cat: 'c2', cat_name: 'Protetică', price: 5000 },
  { id: 's5', label: 'Consultație', cat: '', price: null, price_hint: '' },
]

const names = (gs: ReturnType<typeof pickGroups>) => gs.map((g) => [g.name, g.items.map((s) => s.id)])

afterEach(cleanup)

describe('pickGroups', () => {
  it('без запроса — всё, группами в порядке сервера', () => {
    expect(names(pickGroups(S, ''))).toEqual([
      ['Terapie', ['s1', 's2', 's3']], ['Protetică', ['s4']], ['Fără categorie', ['s5']],
    ])
  })

  it('поиск без диакритики и регистра, по словам в любом порядке', () => {
    expect(names(pickGroups(S, 'suprafete 2'))).toEqual([['Terapie', ['s2']]])
    expect(names(pickGroups(S, 'COROANA'))).toEqual([['Protetică', ['s4']]])
    expect(names(pickGroups(S, 'restaurare SUPRAF'))).toEqual([['Terapie', ['s1', 's2']]])
  })

  it('ищет и по имени RU, и по категории', () => {
    expect(names(pickGroups(S, 'пломба 1'))).toEqual([['Terapie', ['s1']]])
    expect(names(pickGroups(S, 'protetica'))).toEqual([['Protetică', ['s4']]])
  })

  it('«Fără categorie» — последней, даже если сервер поставил её раньше', () => {
    expect(names(pickGroups([S[4]!, S[3]!], ''))).toEqual([['Protetică', ['s4']], ['Fără categorie', ['s5']]])
  })
})

describe('priceLabel', () => {
  it('сумма — с тысячами и валютой, диапазон и строка прайса — как записаны, без цены — пусто', () => {
    expect(priceLabel(S[3]!)).toBe('5 000 MDL')
    expect(priceLabel(S[2]!)).toBe('1800–2400 MDL')
    expect(priceLabel({ id: 'x', label: 'x', price: ' 9000–12000 MDL ' })).toBe('9000–12000 MDL')
    expect(priceLabel({ id: 'x', label: 'x', price: '4850' })).toBe('4 850 MDL')
    expect(priceLabel(S[4]!)).toBe('')
  })
})

/* поле в форме, как у плана: Enter в нём не должен отправлять форму */
function Harness({ services = S, onSubmit, onPick }: {
  services?: PickOption[]; onSubmit: () => void; onPick?: (s: PickOption) => void
}) {
  const [v, setV] = useState('')
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
      <ServicePicker value={v} services={services} label="Procedură" onChange={setV}
        onPick={(s) => { setV(s.label); onPick?.(s) }} />
      <button>Adaugă</button>
    </form>
  )
}

const field = () => screen.getByRole('combobox', { name: 'Procedură' }) as HTMLInputElement
const options = () => within(screen.getByRole('listbox')).getAllByRole('option')
const active = () => options().find((o) => o.getAttribute('aria-selected') === 'true')?.querySelector('.dp-svc-name')?.textContent

describe('ServicePicker', () => {
  it('набор открывает список: группы с заголовками, цена справа; первая строка подсвечена', () => {
    render(<Harness onSubmit={vi.fn()} />)
    expect(screen.queryByRole('listbox')).toBeNull()
    fireEvent.change(field(), { target: { value: 'restaurare' } })
    const list = screen.getByRole('listbox')
    expect(within(list).getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual(['Terapie'])
    expect(options().map((o) => [o.querySelector('.dp-svc-name')?.textContent, o.querySelector('.dp-svc-price')?.textContent]))
      .toEqual([['Restaurare dentară pe 1 suprafață', '900 MDL'], ['Restaurare dentară pe 2 suprafețe', '1 200 MDL']])
    expect(active()).toBe('Restaurare dentară pe 1 suprafață')
    expect(field().getAttribute('aria-activedescendant')).toBe(options()[0]!.id)
  })

  it('выбор за три нажатия: буквы, ↓, Enter — имя в поле, список закрыт, форма НЕ ушла', () => {
    const submit = vi.fn()
    const pick = vi.fn()
    render(<Harness onSubmit={submit} onPick={pick} />)
    fireEvent.change(field(), { target: { value: 'supraf' } })
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    expect(active()).toBe('Restaurare dentară pe 2 suprafețe')
    fireEvent.keyDown(field(), { key: 'Enter' })
    expect(pick).toHaveBeenCalledWith(S[1])
    expect(field().value).toBe('Restaurare dentară pe 2 suprafețe')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(submit).not.toHaveBeenCalled()
  })

  it('⛔ Enter без списка тоже не отправляет форму (поле стоит в формах окон)', () => {
    const submit = vi.fn()
    render(<Harness onSubmit={submit} />)
    fireEvent.change(field(), { target: { value: 'Ceva în afara listei' } })
    expect(within(screen.getByRole('listbox')).queryAllByRole('option')).toEqual([])
    expect(screen.getByText(/rămâne textul scris/)).toBeTruthy()
    const ev = fireEvent.keyDown(field(), { key: 'Enter' })
    expect(ev).toBe(false)
    expect(submit).not.toHaveBeenCalled()
    /* свободный текст остался как написан */
    expect(field().value).toBe('Ceva în afara listei')
  })

  it('стрелки ходят по кругу через группы; ↑ с первой — на последнюю', () => {
    render(<Harness onSubmit={vi.fn()} />)
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    expect(options()).toHaveLength(5)
    expect(active()).toBe('Restaurare dentară pe 1 suprafață')
    fireEvent.keyDown(field(), { key: 'ArrowUp' })
    expect(active()).toBe('Consultație')
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    expect(active()).toBe('Coroană din zirconiu')
  })

  it('⛔ Esc закрывает список и дальше не идёт; без списка — идёт (окно закрывается как обычно)', () => {
    const outer = vi.fn()
    render(<div onKeyDown={(e) => outer(e.key)}><Harness onSubmit={vi.fn()} /></div>)
    fireEvent.change(field(), { target: { value: 'coroana' } })
    fireEvent.keyDown(field(), { key: 'Escape' })
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(outer).not.toHaveBeenCalled()
    expect(field().value).toBe('coroana')
    fireEvent.keyDown(field(), { key: 'Escape' })
    expect(outer).toHaveBeenCalledWith('Escape')
  })

  it('щелчок по строке выбирает её; фокус не уходит с поля', () => {
    const pick = vi.fn()
    render(<Harness onSubmit={vi.fn()} onPick={pick} />)
    field().focus()
    fireEvent.click(field())
    const opt = options().find((o) => o.textContent?.startsWith('Coroană'))!
    expect(fireEvent.mouseDown(opt)).toBe(false)
    fireEvent.click(opt)
    expect(pick).toHaveBeenCalledWith(S[3])
    expect(field().value).toBe('Coroană din zirconiu')
  })

  it('прайс без категорий — без заголовков групп; пустой прайс — списка нет совсем', () => {
    const flat = S.map((s) => ({ ...s, cat: '', cat_name: '' }))
    const { unmount } = render(<Harness services={flat} onSubmit={vi.fn()} />)
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    expect(within(screen.getByRole('listbox')).getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual([null])
    expect(document.querySelector('.dp-svc-cat')).toBeNull()
    unmount()
    render(<Harness services={[]} onSubmit={vi.fn()} />)
    fireEvent.change(field(), { target: { value: 'x' } })
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(field().getAttribute('aria-expanded')).toBe('false')
  })

  it('уход с поля закрывает список', () => {
    render(<Harness onSubmit={vi.fn()} />)
    fireEvent.change(field(), { target: { value: 'res' } })
    fireEvent.blur(field())
    expect(screen.queryByRole('listbox')).toBeNull()
  })
})
