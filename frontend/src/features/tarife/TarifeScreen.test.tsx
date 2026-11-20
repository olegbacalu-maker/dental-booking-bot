import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import type { ImCheck, TarifeData, TarifRow } from './tarife'
import { loadTarife, TarifeScreen } from './TarifeScreen'

/* «Servicii și tarife»: меню категорий, только чтение без права, правка «только тронутое», поиск без
   диакритики, импорт с предпросмотром, команды категорий, вопрос при уходе с правкой. */

const { get, post, postRaw } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postRaw: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postRaw }, loginUrl: () => '/admin/login?next=x' }
})

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })
const svc = (p: Partial<TarifRow> & Pick<TarifRow, 'id' | 'ro'>): TarifRow =>
  ({ ru: p.ro, price: '', amount: null, price_hint: '', cat: '', where: 'both', ...p })

function model(p: Partial<TarifeData> = {}): TarifeData {
  return {
    services: [
      svc({ id: 'consult', ro: 'Consultație', ru: 'Консультация', price: '300', amount: 300 }),
      svc({ id: 's21', ro: '2 restaurări', where: 'agenda' }),
      svc({ id: 's22', ro: 'Restaurare pe 1 suprafață', ru: 'Пломба на 1 поверхность', price: '900', amount: 900, cat: 'c1', where: 'plan' }),
      svc({ id: 's23', ro: 'Coroană din zirconiu', ru: 'Коронка из диоксида циркония', price: '5000', amount: 5000, cat: 'c2', where: 'plan' }),
      svc({ id: 's24', ro: 'Detartraj', price: '600-800', price_hint: '600-800', cat: 'c1', where: 'plan' }),
    ],
    cats: [{ id: 'c1', name: 'Terapie', n: 2 }, { id: 'c2', name: 'Protetică', n: 1 }],
    uncat: 1,
    can_edit: true,
    max: { name: 60, price: 60, cat: 60, cats: 50, services: 1000 },
    import: { bytes: 10485760, remote: null },
    ...p,
  }
}

const nav = vi.fn()
function open(data: TarifeData = model(), url = '/admin/tarife') {
  get.mockResolvedValue(ok(data))
  return openScreen('/admin/tarife', url, <TarifeScreen navigate={nav} />, loadTarife).router
}
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); postRaw.mockReset(); nav.mockReset(); vi.restoreAllMocks() })

describe('TarifeScreen', () => {
  it('меню: все строки прайса, категории по порядку с числом, «Fără categorie», «Doar în agendă»; строки по группам', async () => {
    open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    const menu = screen.getByRole('navigation', { name: 'Servicii și tarife' })
    const names = within(menu).getAllByRole('button').map((b) => b.textContent)
    expect(names).toEqual(['Toate serviciile4', 'Terapie2', 'Protetică1', 'Fără categorie1', 'Doar în agendă1'])
    /* «doar agendă» в прайсе не показывается */
    expect(screen.queryByDisplayValue('2 restaurări')).toBeNull()
    const groups = [...document.querySelectorAll('tr.st-cat-r')].map((r) => r.textContent)
    expect(groups).toEqual(['Terapie', 'Protetică', 'Fără categorie'])
    /* категория в адресе — её строки */
    fireEvent.click(within(menu).getByRole('button', { name: /Protetică/ }))
    await waitFor(() => expect(screen.queryByDisplayValue('Detartraj')).toBeNull())
    expect(screen.getByDisplayValue('Coroană din zirconiu')).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('без права — только чтение: ни полей, ни кнопок правки и импорта; экспорт остаётся', async () => {
    open(model({ can_edit: false }))
    await screen.findByText('Coroană din zirconiu')
    expect(document.querySelectorAll('tbody input, tbody select').length).toBe(0)
    expect(screen.getByText(/Prețurile le schimbă directorul sau recepția/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Serviciu/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Categorie/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Importă/ })).toBeNull()
    expect(screen.getByRole('link', { name: /Exportă/ }).getAttribute('href')).toBe('/admin/tarife.xlsx')
    const row = screen.getByText('Coroană din zirconiu').closest('tr')!
    expect(row.textContent).toContain('5000')
    expect(row.textContent).toContain('Plan')
    expect(row.textContent).not.toContain('Agendă')
  })

  it('поиск без диакритики и регистра — по RO и RU', async () => {
    open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: 'COROANA' } })
    expect(screen.getByDisplayValue('Coroană din zirconiu')).toBeTruthy()
    expect(screen.queryByDisplayValue('Detartraj')).toBeNull()
    expect(screen.getByText('1 serviciu')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: 'пломба' } })
    expect(screen.getByDisplayValue('Restaurare pe 1 suprafață')).toBeTruthy()
    expect(screen.queryByDisplayValue('Coroană din zirconiu')).toBeNull()
    fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: 'xyz' } })
    expect(screen.getByText('Nimic găsit.')).toBeTruthy()
  })

  it('правка уходит «только тронутым»: цена, категория, новая строка; возврат к прежнему не уходит', async () => {
    const saved = model()
    post.mockResolvedValueOnce(ok(saved, 'ok_tarife', 'Lista de prețuri salvată.'))
    open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    expect(screen.queryByRole('region', { name: 'Modificări nesalvate' })).toBeNull()
    fireEvent.change(field('Preț: Coroană din zirconiu'), { target: { value: '5500' } })
    fireEvent.change(screen.getByLabelText('Categorie: Detartraj'), { target: { value: 'c2' } })
    /* тронули и вернули — тело этой строки пустое */
    fireEvent.change(field('Denumire (RU): Consultație'), { target: { value: 'Консультация!' } })
    fireEvent.change(field('Denumire (RU): Consultație'), { target: { value: 'Консультация' } })
    fireEvent.click(screen.getByRole('button', { name: /^Serviciu$/ }))
    fireEvent.change(field('Denumire (RO): nou'), { target: { value: 'Albire ' } })
    fireEvent.change(field('Preț: nou'), { target: { value: '2500' } })
    fireEvent.change(screen.getByLabelText('Categorie: nou'), { target: { value: 'c1' } })
    const bar = screen.getByRole('region', { name: 'Modificări nesalvate' })
    expect(bar.textContent).toContain('3 modificări')
    fireEvent.click(within(bar).getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText('Lista de prețuri salvată.')).toBeTruthy()
    expect(post).toHaveBeenCalledWith('/tarife', {
      services: { s23: { price: '5500' }, s24: { cat: 'c2' } },
      new: [{ ro: 'Albire', ru: '', price: '2500', cat: 'c1' }],
    })
    expect(screen.queryByRole('region', { name: 'Modificări nesalvate' })).toBeNull()
  })

  it('новая строка без имени не уходит: подсветка и слово, без запроса', async () => {
    open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.click(screen.getByRole('button', { name: /^Serviciu$/ }))
    fireEvent.change(field('Preț: nou'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText('Scrieți denumirea serviciului.')).toBeTruthy()
    expect(post).not.toHaveBeenCalled()
    expect(field('Preț: nou').closest('tr')!.className).toContain('tf-bad')
  })

  it('«Plan» у услуги агенды и удаление строки «только plan» — с вопросом', async () => {
    post.mockResolvedValueOnce(ok(model(), 'ok_tarife', 'Lista de prețuri salvată.'))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const router = open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.click(screen.getByRole('button', { name: 'Șterge din listă: Detartraj' }))
    await waitFor(() => expect(screen.getByText('se șterge la salvare')).toBeTruthy())
    expect(confirm.mock.calls[0]?.[0]).toContain('Detartraj')
    /* «Consultație» в агенде и в плане: «Plan» снимается без удаления */
    fireEvent.click(screen.getByRole('button', { name: 'Plan: Consultație' }))
    await act(() => router.navigate('/admin/tarife?c=agenda'))
    fireEvent.click(await screen.findByRole('button', { name: 'Plan: 2 restaurări' }))
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await screen.findByText('Lista de prețuri salvată.')
    expect(post).toHaveBeenCalledWith('/tarife', { services: { consult: { plan: false }, s21: { plan: true }, s24: { plan: false } } })
  })

  it('категории: новая — сразу запросом и в адрес; удаление — с вопросом', async () => {
    const withNew = model({ cats: [...model().cats, { id: 'c3', name: 'Chirurgie', n: 0 }], created: { services: [], cats: { k1: 'c3' } } })
    post.mockResolvedValueOnce(ok(withNew, 'ok_tarife', 'Salvat.'))
    const router = open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.click(screen.getByRole('button', { name: /^Categorie$/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Categorie nouă' })
    fireEvent.change(within(dlg).getByLabelText('Numele categoriei'), { target: { value: 'Chirurgie' } })
    fireEvent.click(within(dlg).getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(router.state.location.search).toBe('?c=c3'))
    expect(post).toHaveBeenCalledWith('/tarife', { cats_new: [{ key: 'k1', name: 'Chirurgie' }] })
    expect(await screen.findByText('Niciun serviciu aici.')).toBeTruthy()

    post.mockResolvedValueOnce(ok(model(), 'ok_tarife', 'Salvat.'))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: /Șterge categoria/ }))
    await waitFor(() => expect(post).toHaveBeenLastCalledWith('/tarife', { cats_removed: ['c3'] }))
    expect(confirm.mock.calls[0]?.[0]).toContain('Chirurgie')
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('порядок категорий — полным списком', async () => {
    post.mockResolvedValueOnce(ok(model(), 'ok_tarife', 'Salvat.'))
    open(model(), '/admin/tarife?c=c2')
    await screen.findByDisplayValue('Coroană din zirconiu')
    expect((screen.getByRole('button', { name: 'Mută mai jos' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Mută mai sus' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/tarife', { cats_order: ['c2', 'c1'] }))
  })

  it('импорт: проверка → предпросмотр «noi / schimbate / neschimbate» → запуск с токеном', async () => {
    const check: ImCheck = {
      file: { name: 'pret.xlsx', size: 1234 },
      rows: [
        { line: 2, cat: 'Protetică', ro: 'Coroană metalo-ceramică', ru: '', price: '3500', act: 'new', id: '', what: [], old_price: '', err: '' },
        { line: 3, cat: 'Terapie', ro: 'Restaurare pe 1 suprafață', ru: '', price: '950', act: 'changed', id: 's22', what: ['price'], old_price: '900', err: '' },
        { line: 4, cat: 'Terapie', ro: 'Detartraj', ru: '', price: '600-800', act: 'same', id: 's24', what: [], old_price: '', err: '' },
        { line: 5, cat: '', ro: '', ru: '', price: '10', act: 'bad', id: '', what: [], old_price: '', err: 'name' },
      ],
      counts: { new: 1, changed: 1, same: 1, bad: 1 },
      cats_new: [],
      token: 'tok1',
    }
    postRaw.mockResolvedValueOnce(ok(check))
    postRaw.mockResolvedValueOnce(ok(model({ imported: { new: 1, changed: 1, same: 1, bad: 1 } }), 'ok_tarife_import', 'Import făcut: 1 nou, 1 schimbat.'))
    open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.click(screen.getByRole('button', { name: /Importă din Excel/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Importă din Excel' })
    const file = new File(['x'], 'pret.xlsx')
    fireEvent.change(within(dlg).getByTestId('tf-file'), { target: { files: [file] } })
    expect(await within(dlg).findByText('Coroană metalo-ceramică')).toBeTruthy()
    expect(postRaw.mock.calls[0]?.[0]).toBe('/tarife/import/check?name=pret.xlsx')
    const tabs = within(dlg).getByRole('group', { name: 'Ce se întâmplă' })
    expect(within(tabs).getAllByRole('button').map((b) => b.textContent)).toEqual(['Noi 1', 'Schimbate 1', 'Neschimbate 1', 'Cu greșeli 1'])
    fireEvent.click(within(tabs).getByRole('button', { name: /Schimbate/ }))
    const tr = within(dlg).getByText('Restaurare pe 1 suprafață').closest('tr')!
    expect(tr.textContent).toContain('900')
    expect(tr.textContent).toContain('950')
    expect(tr.textContent).toContain('preț')
    fireEvent.click(within(tabs).getByRole('button', { name: /Cu greșeli/ }))
    expect(within(dlg).getByText('denumire goală sau prea lungă')).toBeTruthy()
    fireEvent.click(within(dlg).getByRole('button', { name: 'Importă: 1 noi, 1 schimbate' }))
    expect(await screen.findByText('Import făcut: 1 nou, 1 schimbat.')).toBeTruthy()
    expect(postRaw.mock.calls[1]?.[0]).toBe('/tarife/import/run?name=pret.xlsx&token=tok1')
    expect(postRaw.mock.calls[1]?.[1]).toBe(file)
  })

  it('импорт не с ПК программы — подсказка сервера вместо кнопки; с несохранённой правкой — кнопка выключена', async () => {
    open(model({ import: { bytes: 1, remote: { tone: 'info', text: 'Importul se face doar de pe calculatorul programului.' } } }))
    await screen.findByDisplayValue('Coroană din zirconiu')
    expect(screen.queryByRole('button', { name: /Importă/ })).toBeNull()
    expect(screen.getByText('Importul se face doar de pe calculatorul programului.')).toBeTruthy()
    cleanup()
    open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.change(field('Preț: Detartraj'), { target: { value: '700' } })
    expect((screen.getByRole('button', { name: /Importă/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('уход на другой экран с правкой — вопрос; «нет» оставляет правку', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const router = open()
    await screen.findByDisplayValue('Coroană din zirconiu')
    fireEvent.change(field('Preț: Detartraj'), { target: { value: '700' } })
    await act(() => router.navigate('/admin/tarife?c=c1'))
    expect(confirm).not.toHaveBeenCalled()
    await act(async () => { void router.navigate('/admin/stoc') })
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0]?.[0]).toContain('modificări nesalvate')
    expect(field('Preț: Detartraj').value).toBe('700')
  })
})
