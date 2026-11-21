import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import type { ImCheck, TarifeData, TarifRow } from './tarife'
import { loadTarife, TarifeScreen } from './TarifeScreen'

/* «Servicii și tarife»: меню категорий, строки-плитки и правка карандашом, только чтение без права, правка «только
   тронутое», поиск без диакритики, импорт с предпросмотром, команды категорий, вопрос при уходе с правкой. */

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
/** Открыть строку карандашом: в покое она — плитка без полей. */
const pen = (name: string) => fireEvent.click(screen.getByRole('button', { name: `Editează: ${name}` }))

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); postRaw.mockReset(); nav.mockReset(); vi.restoreAllMocks() })

describe('TarifeScreen', () => {
  it('меню: все строки прайса, категории по порядку с числом, «Fără categorie», «Doar în agendă»; строки по группам', async () => {
    open()
    await screen.findByText('Coroană din zirconiu')
    const menu = screen.getByRole('navigation', { name: 'Servicii și tarife' })
    const names = within(menu).getAllByRole('button').map((b) => b.textContent)
    expect(names).toEqual(['Toate serviciile4', 'Terapie2', 'Protetică1', 'Fără categorie1', 'Doar în agendă1'])
    /* «doar agendă» в прайсе не показывается */
    expect(screen.queryByText('2 restaurări')).toBeNull()
    const groups = [...document.querySelectorAll('tr.st-cat-r')].map((r) => r.textContent)
    expect(groups).toEqual(['Terapie', 'Protetică', 'Fără categorie'])
    /* категория в адресе — её строки */
    fireEvent.click(within(menu).getByRole('button', { name: /Protetică/ }))
    await waitFor(() => expect(screen.queryByText('Detartraj')).toBeNull())
    expect(screen.getByText('Coroană din zirconiu')).toBeTruthy()
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('плитки: в покое строки без полей и без корзины — карандаш открывает, «Gata» закрывает с правкой, «Renunță» возвращает', async () => {
    open()
    await screen.findByText('Coroană din zirconiu')
    expect(document.querySelectorAll('tbody input, tbody select')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: /^Șterge din listă/ })).toBeNull()
    /* у каждой строки прайса — карандаш; RU не писали — «ca RO»; категория — именем */
    expect(screen.getAllByRole('button', { name: /^Editează: / })).toHaveLength(4)
    const det = screen.getByText('Detartraj').closest('tr')!
    expect(within(det).getByText('ca RO')).toBeTruthy()
    expect(within(det).getByText('Terapie')).toBeTruthy()
    expect(within(det).getByText('600-800')).toBeTruthy()
    /* карандаш: строка открыта, курсор в имени; соседние строки — плитки */
    pen('Detartraj')
    await waitFor(() => expect(document.activeElement).toBe(field('Denumire (RO): Detartraj')))
    expect(document.querySelectorAll('tbody tr.tf-open')).toHaveLength(1)
    expect(field('Denumire (RU): Detartraj').placeholder).toBe('ca RO')
    expect(screen.getByRole('button', { name: 'Șterge din listă: Detartraj' })).toBeTruthy()
    fireEvent.change(field('Preț: Detartraj'), { target: { value: '750' } })
    /* «Gata»: строка снова плитка с новой ценой, правка ждёт «Salvează» */
    fireEvent.click(screen.getByRole('button', { name: 'Gata: Detartraj' }))
    expect(document.querySelectorAll('tbody input, tbody select')).toHaveLength(0)
    const tile = screen.getByText('Detartraj').closest('tr')!
    expect(within(tile).getByText('750')).toBeTruthy()
    expect(tile.className).toContain('tf-ed')
    const bar = screen.getByRole('region', { name: 'Modificări nesalvate' })
    expect(bar.textContent).toContain('1 modificare')
    /* «Renunță» — прежняя цена, все строки закрыты */
    pen('Consultație')
    fireEvent.click(within(bar).getByRole('button', { name: 'Renunță' }))
    expect(document.querySelectorAll('tbody input, tbody select')).toHaveLength(0)
    expect(within(screen.getByText('Detartraj').closest('tr')!).getByText('600-800')).toBeTruthy()
    expect(post).not.toHaveBeenCalled()
  })

  it('плитка и правка — одни колонки, одно место кнопок: строка не меняет вид таблицы', async () => {
    open()
    await screen.findByText('Coroană din zirconiu')
    const tr = screen.getByText('Coroană din zirconiu').closest('tr')!
    const shape = () => [tr.children.length, (tr.querySelector('td.tf-act') as HTMLElement).children.length]
    const before = shape()
    pen('Coroană din zirconiu')
    expect(shape()).toEqual(before)
    expect(before).toEqual([6, 2])
    /* значение плитки — в коробке поля (`.tf-val`), а не голым текстом ячейки */
    fireEvent.click(screen.getByRole('button', { name: 'Gata: Coroană din zirconiu' }))
    expect(tr.querySelectorAll('td .tf-val')).toHaveLength(4)
  })

  it('отказ «имя занято» открывает строку с этим именем', async () => {
    post.mockRejectedValueOnce(new (await import('../../types/api')).ApiError(
      { kind: 'validation', code: 'dup_tarif', text: 'Denumirea „Detartraj” există deja', field: 'ro', data: { label: 'Detartraj' } }, 'dup'))
    open()
    await screen.findByText('Coroană din zirconiu')
    pen('Coroană din zirconiu')
    fireEvent.change(field('Denumire (RO): Coroană din zirconiu'), { target: { value: 'Detartraj' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gata: Coroană din zirconiu' }))
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    expect(await screen.findByText('Denumirea „Detartraj” există deja')).toBeTruthy()
    expect(field('Denumire (RO): Detartraj').closest('tr')!.className).toContain('tf-bad')
    expect(document.querySelectorAll('tbody tr.tf-open')).toHaveLength(2)
  })

  it('без права — только чтение: ни полей, ни кнопок правки и импорта; экспорт остаётся', async () => {
    open(model({ can_edit: false }))
    await screen.findByText('Coroană din zirconiu')
    expect(document.querySelectorAll('tbody input, tbody select').length).toBe(0)
    expect(screen.queryByRole('button', { name: /^Editează/ })).toBeNull()
    expect(document.querySelectorAll('tbody .tf-val').length).toBeGreaterThan(0)
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
    await screen.findByText('Coroană din zirconiu')
    fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: 'COROANA' } })
    expect(screen.getByText('Coroană din zirconiu')).toBeTruthy()
    expect(screen.queryByText('Detartraj')).toBeNull()
    expect(screen.getByText('1 serviciu')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: 'пломба' } })
    expect(screen.getByText('Restaurare pe 1 suprafață')).toBeTruthy()
    expect(screen.queryByText('Coroană din zirconiu')).toBeNull()
    fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: 'xyz' } })
    expect(screen.getByText('Nimic găsit.')).toBeTruthy()
  })

  it('поиск по словам, как в плане: куски слов в любом порядке и имя категории', async () => {
    open()
    await screen.findByText('Coroană din zirconiu')
    const find = (v: string) => fireEvent.change(screen.getByLabelText('Caută serviciul'), { target: { value: v } })
    find('restaurare supraf')
    expect(screen.getByText('Restaurare pe 1 suprafață')).toBeTruthy()
    expect(screen.getByText('1 serviciu')).toBeTruthy()
    find('  supraf   restaur ')
    expect(screen.getByText('Restaurare pe 1 suprafață')).toBeTruthy()
    find('protetica zirc')
    expect(screen.getByText('Coroană din zirconiu')).toBeTruthy()
    expect(screen.getByText('1 serviciu')).toBeTruthy()
    find('terapie')
    expect(screen.getByText('Restaurare pe 1 suprafață')).toBeTruthy()
    expect(screen.getByText('Detartraj')).toBeTruthy()
    expect(screen.queryByText('Coroană din zirconiu')).toBeNull()
    find('restaurare zirc')
    expect(screen.getByText('Nimic găsit.')).toBeTruthy()
  })

  it('правка уходит «только тронутым»: цена, категория, новая строка; возврат к прежнему не уходит', async () => {
    const saved = model()
    post.mockResolvedValueOnce(ok(saved, 'ok_tarife', 'Lista de prețuri salvată.'))
    open()
    await screen.findByText('Coroană din zirconiu')
    expect(screen.queryByRole('region', { name: 'Modificări nesalvate' })).toBeNull()
    pen('Coroană din zirconiu')
    pen('Detartraj')
    pen('Consultație')
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
    /* после записи все строки снова плитки */
    expect(document.querySelectorAll('tbody input, tbody select')).toHaveLength(0)
  })

  it('ничто не прыгает: место под число поиска, полосу записи и пометку удаления занято всегда', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    open()
    await screen.findByText('Coroană din zirconiu')
    /* шапка двумя рядами: поиск — во втором, отдельно от названия вида; кнопки категории — там же справа */
    const rows = document.querySelectorAll('.tf-head > .tf-hrow')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.querySelector('.tf-find')).toBeNull()
    expect(rows[1]!.firstElementChild!.className).toBe('tf-find')
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Servicii și tarife' })).getByRole('button', { name: /Protetică/ }))
    expect(await within(rows[1] as HTMLElement).findByRole('button', { name: /Redenumește/ })).toBeTruthy()
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Servicii și tarife' })).getByRole('button', { name: /Toate/ }))
    await waitFor(() => expect(screen.queryByRole('button', { name: /Redenumește/ })).toBeNull())
    /* число найденного: узел стоит и до первой буквы — поле не сужается под курсором */
    const count = document.querySelector('.tf-find > span')!
    expect(count.getAttribute('aria-hidden')).toBe('true')
    fireEvent.change(screen.getByRole('searchbox', { name: 'Caută serviciul' }), { target: { value: 'coroana' } })
    expect(document.querySelector('.tf-find > span')).toBe(count)
    expect(count.textContent).toBe('1 serviciu')
    expect(count.hasAttribute('aria-hidden')).toBe(false)
    fireEvent.change(screen.getByRole('searchbox', { name: 'Caută serviciul' }), { target: { value: '' } })
    /* полоса записи: без правки стоит невидимой и не трогается; правка её проявляет — тот же узел */
    const bar = document.querySelector('.tf-save')!
    expect(bar.classList.contains('off')).toBe(true)
    expect(bar.hasAttribute('inert')).toBe(true)
    pen('Detartraj')
    fireEvent.click(screen.getByRole('button', { name: 'Șterge din listă: Detartraj' }))
    await waitFor(() => expect(screen.getByText('se șterge la salvare')).toBeTruthy())
    expect(confirm).toHaveBeenCalled()
    expect(document.querySelector('.tf-save')).toBe(bar)
    expect(bar.classList.contains('off')).toBe(false)
    expect(bar.hasAttribute('inert')).toBe(false)
    /* удалённая строка не растёт: пометка — на месте «Plan», отмена — значком на месте корзины */
    const tr = screen.getByLabelText('Denumire (RO): Detartraj').closest('tr')!
    expect(tr.querySelector('td:first-child small')).toBeNull()
    expect(within(tr.querySelector('td.tf-where') as HTMLElement).getByText('se șterge la salvare')).toBeTruthy()
    const undo = within(tr.querySelector('td.tf-act') as HTMLElement).getByRole('button', { name: 'Anulează' })
    expect(undo.className).toContain('tf-undo')
    fireEvent.click(undo)
    expect(screen.queryByText('se șterge la salvare')).toBeNull()
    expect(bar.classList.contains('off')).toBe(true)
  })

  it('новая строка без имени не уходит: подсветка и слово, без запроса', async () => {
    open()
    await screen.findByText('Coroană din zirconiu')
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
    await screen.findByText('Coroană din zirconiu')
    /* в плитке ни корзины, ни переключателя «Plan» — только карандаш */
    expect(screen.queryByRole('button', { name: 'Șterge din listă: Detartraj' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Plan: Consultație' })).toBeNull()
    pen('Detartraj')
    fireEvent.click(screen.getByRole('button', { name: 'Șterge din listă: Detartraj' }))
    await waitFor(() => expect(screen.getByText('se șterge la salvare')).toBeTruthy())
    expect(confirm.mock.calls[0]?.[0]).toContain('Detartraj')
    pen('Consultație')
    /* «Consultație» в агенде и в плане: «Plan» снимается без удаления */
    fireEvent.click(screen.getByRole('button', { name: 'Plan: Consultație' }))
    await act(() => router.navigate('/admin/tarife?c=agenda'))
    fireEvent.click(await screen.findByRole('button', { name: 'Editează: 2 restaurări' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Plan: 2 restaurări' }))
    fireEvent.click(screen.getByRole('button', { name: /Salvează/ }))
    await screen.findByText('Lista de prețuri salvată.')
    expect(post).toHaveBeenCalledWith('/tarife', { services: { consult: { plan: false }, s21: { plan: true }, s24: { plan: false } } })
  })

  it('категории: новая — сразу запросом и в адрес; удаление — с вопросом', async () => {
    const withNew = model({ cats: [...model().cats, { id: 'c3', name: 'Chirurgie', n: 0 }], created: { services: [], cats: { k1: 'c3' } } })
    post.mockResolvedValueOnce(ok(withNew, 'ok_tarife', 'Salvat.'))
    const router = open()
    await screen.findByText('Coroană din zirconiu')
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
    await screen.findByText('Coroană din zirconiu')
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
    await screen.findByText('Coroană din zirconiu')
    fireEvent.click(screen.getByRole('button', { name: /Importă din Excel/ }))
    const dlg = await screen.findByRole('dialog', { name: 'Importă din Excel' })
    const file = new File(['x'], 'pret.xlsx')
    fireEvent.change(within(dlg).getByTestId('tf-file'), { target: { files: [file] } })
    expect(await within(dlg).findByText('Coroană metalo-ceramică')).toBeTruthy()
    expect(postRaw.mock.calls[0]?.[0]).toBe('/tarife/import/check?name=pret.xlsx')
    const tabs = within(dlg).getByRole('group', { name: 'Ce se întâmplă' })
    expect(within(tabs).getAllByRole('button').map((b) => b.textContent)).toEqual(['Noi 1', 'Schimbate 1', 'Neschimbate 1', 'Cu greșeli 1'])
    /* место под жирную подпись нажатой вкладки — та же строка в `data-t` (app.css › ::after) */
    expect(within(tabs).getAllByRole('button').map((b) => b.dataset.t)).toEqual(['Noi 1', 'Schimbate 1', 'Neschimbate 1', 'Cu greșeli 1'])
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
    await screen.findByText('Coroană din zirconiu')
    expect(screen.queryByRole('button', { name: /Importă/ })).toBeNull()
    expect(screen.getByText('Importul se face doar de pe calculatorul programului.')).toBeTruthy()
    cleanup()
    open()
    await screen.findByText('Coroană din zirconiu')
    pen('Detartraj')
    fireEvent.change(field('Preț: Detartraj'), { target: { value: '700' } })
    expect((screen.getByRole('button', { name: /Importă/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('уход на другой экран с правкой — вопрос; «нет» оставляет правку', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const router = open()
    await screen.findByText('Coroană din zirconiu')
    pen('Detartraj')
    fireEvent.change(field('Preț: Detartraj'), { target: { value: '700' } })
    await act(() => router.navigate('/admin/tarife?c=c1'))
    expect(confirm).not.toHaveBeenCalled()
    await act(async () => { void router.navigate('/admin/stoc') })
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0]?.[0]).toContain('modificări nesalvate')
    expect(field('Preț: Detartraj').value).toBe('700')
  })
})
