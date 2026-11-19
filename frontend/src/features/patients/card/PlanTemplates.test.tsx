import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { asApiError, type ApiResult } from '../../../services/api'
import { ApiError } from '../../../types/api'
import type { CardActions, FormKey } from './actions'
import type { PatientCard, PlanItem, PlanTplCatalog } from './card'
import { PlanCard } from './PlanCard'

/* Шаблоны плана в фише: окно «Adaugă din șablon» и «Salvează ca șablon».
   Подмена слоя сети — только в этих проверках. */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../services/api')>()
  return { ...real, api: { get, post } }
})

const item = (id: number, procedure: string, over: Partial<PlanItem> = {}): PlanItem => ({
  id, tooth: null, procedure, doctor: '', status: 'planificat', service_id: null, doctor_id: null, label: 'Planificat',
  price: null, due: '', overdue: false, done: '', motiv: '', next: 'in_lucru', refusable: true, deletable: true,
  editable: true, due_date: '', ...over,
})

const ITEMS = [
  item(1, 'Consultație', { service_id: 'consult' }),
  item(2, 'Coroană zirconiu', { tooth: 36, price: 4500, doctor: 'Dr. Activ Doi' }),
  item(3, 'Implant dentar', { tooth: 36, price: 9000, status: 'refuzat', label: 'Refuzat', motiv: 'refuză', editable: false, deletable: false }),
  item(4, 'Igienizare', { service_id: 'hygiene', price: 1000 }),
]

const card = (over: Partial<PatientCard['plan']> = {}): PatientCard => ({
  id: 5, name: 'Pin Test',
  profile: { primary_doctor: 'Dr. Activ Doi' },
  plan: {
    items: ITEMS, counts: { planificat: 3, in_lucru: 0, finalizat: 0, refuzat: 1 }, n_act: 3, default_tab: 'act',
    total: 5500, total_done: 0, n_track: 3, pct_done: 0, can_template: true, ...over,
  },
  forms: [],
  appoint: {
    services: [
      { id: 'consult', label: 'Consultație', price: null, price_hint: 'gratuit' },
      { id: 'hygiene', label: 'Igienizare', price: 1000, price_hint: '' },
      { id: 'canal', label: 'Tratament de canal', price: null, price_hint: '1200–1800 MDL' },
      { id: 'bont', label: 'Bont protetic', price: 3000, price_hint: '' },
    ],
  },
  options: {
    tab_states: { act: ['planificat', 'in_lucru'], finalizat: ['finalizat'], refuzat: ['refuzat'] },
    teeth: [36, 37, 46], milk: [55], doctors: ['Dr. Activ Doi', 'Dr. Activ Trei'],
  },
} as unknown as PatientCard)

const CATALOG: PlanTplCatalog = {
  doctor: 'Dr. Activ Doi',
  templates: [
    { id: 'pt1', name: 'Canal + coroană', note: 'pentru molari', rows: [
      { procedure: 'Consultație', service_id: 'consult', tooth: false, price: null },
      { procedure: 'Tratament de canal', service_id: 'canal', tooth: true, price: null },
      { procedure: 'Bont protetic', service_id: 'bont', tooth: true, price: null },
      { procedure: 'Coroană zirconiu', service_id: '', tooth: true, price: 5000 },
    ] },
    { id: 'pt2', name: 'Igienizare completă', note: '', rows: [
      { procedure: 'Igienizare', service_id: 'hygiene', tooth: false, price: null },
    ] },
  ],
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

/** Карточка плана с действием фиши: удача — null, отказ — ошибка вызывающему, как у экрана. */
function mount(c: PatientCard = card()) {
  const form = vi.fn<(k: FormKey, on: boolean) => void>()
  const a: CardActions = {
    pid: 5, views: false, busy: false, back: '/admin/patient/5?tab=plan', form,
    act: async (run) => {
      try {
        await run()
        return null
      } catch (e) {
        return asApiError(e)
      }
    },
  }
  render(<section className="dp-react-root"><PlanCard card={c} a={a} onTooth={() => undefined} onUploadSigned={() => undefined} /></section>)
  return { form }
}

const dlg = () => document.querySelector('dialog.dp-plan-tpl') as HTMLDialogElement | null
const inDlg = () => within(dlg() as HTMLElement)
const rowOf = (procedure: string) => inDlg().getByText(procedure, { selector: '.tp-proc span' }).closest('tr') as HTMLElement
const price = (procedure: string) => inDlg().getByLabelText(`Prețul procedurii: ${procedure}`) as HTMLInputElement
const tooth = (procedure: string) => inDlg().getByLabelText(`Dintele procedurii: ${procedure}`) as HTMLSelectElement
const note = (procedure: string) => rowOf(procedure).querySelector('.dp-price-note')?.textContent
const go = () => inDlg().getByRole('button', { name: /^Adaugă .*în plan$/ }) as HTMLButtonElement

async function openInsert(c: PatientCard = card(), catalog: PlanTplCatalog = CATALOG) {
  get.mockResolvedValue(ok(catalog))
  const r = mount(c)
  fireEvent.click(screen.getByRole('button', { name: 'Adaugă din șablon' }))
  await waitFor(() => expect(dlg()?.hasAttribute('open')).toBe(true))
  return r
}

async function openSave(c: PatientCard = card()) {
  const r = mount(c)
  fireEvent.click(screen.getByRole('button', { name: 'Acțiuni pentru tot planul' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Salvează ca șablon' }))
  await waitFor(() => expect(dlg()?.hasAttribute('open')).toBe(true))
  return r
}

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.restoreAllMocks()
})

describe('план: кто видит шаблоны', () => {
  it('«Adaugă din șablon» — у всех, под планом и в меню плана; «Salvează ca șablon» — только с правом и непустым планом', async () => {
    const menu = () => {
      fireEvent.click(screen.getByRole('button', { name: 'Acțiuni pentru tot planul' }))
      return screen.getAllByRole('menuitem').map((x) => x.textContent?.trim())
    }
    mount(card({ can_template: false }))
    expect(screen.getByRole('button', { name: 'Adaugă din șablon' })).toBeTruthy()
    expect(menu()).toEqual(['Adaugă din șablon'])
    cleanup()
    mount(card({ items: [], n_act: 0 }))
    expect(screen.getByRole('button', { name: 'Adaugă din șablon' })).toBeTruthy()
    expect(menu()).toEqual(['Adaugă din șablon'])
    cleanup()
    mount()
    expect(menu()).toEqual(['Adaugă din șablon', 'Salvează ca șablon'])
    /* пункт меню открывает то же окно, что кнопка под планом */
    get.mockResolvedValue(ok(CATALOG))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Adaugă din șablon' }))
    await waitFor(() => expect(dlg()?.hasAttribute('open')).toBe(true))
    expect(await inDlg().findByText('Bont protetic')).toBeTruthy()
  })
})

describe('план: «Adaugă din șablon»', () => {
  it('окно берёт шаблоны клиники; первый выбран; цена строки — шаблона, прайса или пусто с подсказкой', async () => {
    await openInsert()
    expect(get).toHaveBeenCalledWith('/patients/5/plan/templates', expect.anything())
    const list = within(inDlg().getByRole('navigation', { name: 'Șabloanele clinicii' }))
    expect(list.getAllByRole('button').map((b) => b.textContent)).toEqual(
      ['Canal + coroană4 proceduri · pentru molari', 'Igienizare completă1 procedură'])
    expect(list.getByRole('button', { current: true }).textContent).toContain('Canal + coroană')
    /* врач — медик курант, и окно это говорит */
    expect((inDlg().getByLabelText(/^Medic/) as HTMLSelectElement).value).toBe('Dr. Activ Doi')
    expect(inDlg().getByText(/medicul curant/)).toBeTruthy()
    expect([price('Consultație').value, note('Consultație')]).toEqual(['', 'în listă: gratuit, scrieți prețul'])
    expect([price('Tratament de canal').value, note('Tratament de canal')])
      .toEqual(['', 'în listă: 1200–1800 MDL, scrieți prețul'])
    expect([price('Bont protetic').value, note('Bont protetic')]).toEqual(['3000', 'din lista de prețuri'])
    expect([price('Coroană zirconiu').value, note('Coroană zirconiu')]).toEqual(['5000', 'prețul din șablon'])
    /* строка «без зуба» зуба не выбирает */
    expect(rowOf('Consultație').querySelector('select')).toBeNull()
    expect(inDlg().getByText('Șablonul nu se schimbă — modificările rămân doar în planul acestui pacient.')).toBeTruthy()
    expect(go().textContent).toContain('Adaugă 4 proceduri în plan')
    expect(post).not.toHaveBeenCalled()
  })

  it('поиск сужает список и ведёт выбор; правка строк переживает взгляд на другой шаблон', async () => {
    await openInsert()
    fireEvent.change(price('Bont protetic'), { target: { value: '2800' } })
    fireEvent.change(inDlg().getByLabelText('Caută șablon…'), { target: { value: 'igien' } })
    /* Enter в поиске гасится: поле стоит в форме окна, и браузер иначе отправил бы её — шаблон ушёл бы в план */
    expect(fireEvent.keyDown(inDlg().getByLabelText('Caută șablon…'), { key: 'Enter' })).toBe(false)
    expect(fireEvent.keyDown(inDlg().getByLabelText('Caută șablon…'), { key: 'a' })).toBe(true)
    const list = within(inDlg().getByRole('navigation', { name: 'Șabloanele clinicii' }))
    expect(list.getAllByRole('button').map((b) => b.querySelector('b')?.textContent)).toEqual(['Igienizare completă'])
    expect([price('Igienizare').value, note('Igienizare')]).toEqual(['1000', 'din lista de prețuri'])
    expect(go().textContent).toContain('Adaugă 1 procedură în plan')
    /* поиск не различает диакритику и регистр: «coroana» находит «Canal + coroană» */
    fireEvent.change(inDlg().getByLabelText('Caută șablon…'), { target: { value: 'COROANA' } })
    expect(list.getAllByRole('button').map((b) => b.querySelector('b')?.textContent)).toEqual(['Canal + coroană'])
    fireEvent.change(inDlg().getByLabelText('Caută șablon…'), { target: { value: 'zzz' } })
    expect(inDlg().getByText('Niciun șablon cu acest nume.')).toBeTruthy()
    expect(go().disabled).toBe(true)
    /* у другого шаблона — его цены, а правка первого на месте, когда к нему вернулись */
    fireEvent.change(inDlg().getByLabelText('Caută șablon…'), { target: { value: '' } })
    expect(price('Bont protetic').value).toBe('2800')
  })

  it('зуб на весь шаблон ведёт строки «с зубом», свой зуб строки сильнее; уходит отмеченное и то, что в полях', async () => {
    const { form } = await openInsert()
    expect(inDlg().getByText('Dinte neales: 3 proceduri intră în plan fără dinte.')).toBeTruthy()
    fireEvent.change(inDlg().getByLabelText('Dinte (pentru tot șablonul)'), { target: { value: '36' } })
    expect(inDlg().queryByText(/Dinte neales/)).toBeNull()
    expect([tooth('Tratament de canal').value, tooth('Bont protetic').value, tooth('Coroană zirconiu').value])
      .toEqual(['36', '36', '36'])
    /* зуб и врач окна — не работа, которую жалко потерять */
    expect(form.mock.calls.some(([k, on]) => k === 'planTpl' && on)).toBe(false)
    fireEvent.change(tooth('Coroană zirconiu'), { target: { value: '37' } })
    fireEvent.change(inDlg().getByLabelText('Dinte (pentru tot șablonul)'), { target: { value: '46' } })
    expect([tooth('Tratament de canal').value, tooth('Coroană zirconiu').value]).toEqual(['46', '37'])
    fireEvent.click(within(rowOf('Consultație')).getByRole('checkbox'))
    expect(rowOf('Consultație').className).toBe('off')
    expect(rowOf('Consultație').querySelector('input.tp-price')).toBeNull()
    fireEvent.change(price('Tratament de canal'), { target: { value: '1 500 lei' } })
    expect(price('Tratament de canal').value).toBe('1500')
    fireEvent.change(inDlg().getByLabelText(/^Medic/), { target: { value: 'Dr. Activ Trei' } })
    expect(inDlg().queryByText(/medicul curant/)).toBeNull()
    expect(go().textContent).toContain('Adaugă 3 proceduri în plan')
    await waitFor(() => expect(form).toHaveBeenLastCalledWith('planTpl', true))
    post.mockResolvedValue(ok(card(), 'ok_ptpl_ins', 'Procedurile din șablon au fost adăugate în plan'))
    fireEvent.click(go())
    await waitFor(() => expect(dlg()).toBeNull())
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenLastCalledWith('/patients/5/plan/from-template', {
      template_id: 'pt1', tooth: '46', doctor: 'Dr. Activ Trei',
      rows: [
        { i: 1, procedure: 'Tratament de canal', tooth: '46', price: '1500' },
        { i: 2, procedure: 'Bont protetic', tooth: '46', price: '3000' },
        { i: 3, procedure: 'Coroană zirconiu', tooth: '37', price: '5000' },
      ],
    })
    await waitFor(() => expect(form).toHaveBeenLastCalledWith('planTpl', false))
  })

  it('отказ сервера — словами в окне; шаблон переписали — окно берёт свежий список', async () => {
    await openInsert()
    post.mockRejectedValueOnce(new ApiError({ kind: 'validation', code: 'bad_card', text: 'Date invalide', field: 'price' }, 'v'))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'tpl_changed', text: 'Șablonul a fost modificat între timp' }, 'c'))
    fireEvent.click(go())
    expect((await inDlg().findByRole('alert')).textContent).toContain('Date invalide')
    expect(dlg()?.hasAttribute('open')).toBe(true)
    expect(get).toHaveBeenCalledTimes(1)
    get.mockResolvedValue(ok({ ...CATALOG, templates: [CATALOG.templates[1]!] }))
    fireEvent.click(go())
    await waitFor(() => expect(inDlg().getByRole('alert').textContent).toContain('Șablonul a fost modificat între timp'))
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    /* прежнего шаблона в свежем списке нет — на экране уже другой, отказ остаётся виден */
    await waitFor(() => expect(inDlg().queryByText('Bont protetic')).toBeNull())
    expect(price('Igienizare').value).toBe('1000')
    expect(dlg()?.hasAttribute('open')).toBe(true)
  })

  it('шаблонов нет: с правом — ссылка в настройки, без права — кто их делает', async () => {
    await openInsert(card(), { doctor: '', templates: [] })
    expect(await inDlg().findByText('Clinica nu are încă șabloane de plan.')).toBeTruthy()
    expect(inDlg().getByRole('link', { name: 'Faceți primul șablon în Setări › Șabloane' }).getAttribute('href'))
      .toBe('/admin/settings/templates?tab=plan')
    cleanup()
    await openInsert(card({ can_template: false }), { doctor: '', templates: [] })
    expect(await inDlg().findByText('Șabloanele le fac directorul și recepția, în Setări › Șabloane.')).toBeTruthy()
    expect(inDlg().queryByRole('link')).toBeNull()
  })

  it('список не загрузился — слова и повтор, а не пустое окно', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'n'))
    mount()
    fireEvent.click(screen.getByRole('button', { name: 'Adaugă din șablon' }))
    expect((await inDlg().findByRole('alert')).textContent).toContain('Nu am putut încărca șabloanele.')
    get.mockResolvedValue(ok(CATALOG))
    fireEvent.click(inDlg().getByRole('button', { name: 'Reîncearcă' }))
    expect(await inDlg().findByText('Bont protetic')).toBeTruthy()
  })

  it('закрытие: без правки строк — сразу, с правкой — вопрос; отказ оставляет окно и ввод', async () => {
    const confirm = vi.spyOn(window, 'confirm')
    await openInsert()
    fireEvent.change(inDlg().getByLabelText('Dinte (pentru tot șablonul)'), { target: { value: '36' } })
    fireEvent.click(inDlg().getByRole('button', { name: 'Renunță' }))
    await waitFor(() => expect(dlg()).toBeNull())
    expect(confirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Adaugă din șablon' }))
    await waitFor(() => expect(dlg()?.hasAttribute('open')).toBe(true))
    fireEvent.change(await waitFor(() => price('Bont protetic')), { target: { value: '2800' } })
    confirm.mockReturnValueOnce(false)
    fireEvent.click(inDlg().getByRole('button', { name: 'Închide' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(confirm.mock.calls[0]?.[0]).toContain('Renunțați la șablon?')
    expect(price('Bont protetic').value).toBe('2800')
    fireEvent.click(inDlg().getByRole('button', { name: 'Închide' }))
    await waitFor(() => expect(dlg()).toBeNull())
    expect(post).not.toHaveBeenCalled()
  })
})

describe('план: «Salvează ca șablon»', () => {
  const name = () => inDlg().getByLabelText('Numele șablonului') as HTMLInputElement
  const save = () => inDlg().getByRole('button', { name: 'Salvează șablonul' }) as HTMLButtonElement
  const box = (procedure: string) => inDlg().getByRole('checkbox', { name: new RegExp(`^${procedure}`) }) as HTMLInputElement

  it('отмечено всё, кроме отказанного; уходят имя, номера позиций в порядке плана и «с ценами»', async () => {
    await openSave()
    expect(['Consultație', 'Coroană zirconiu', 'Implant dentar', 'Igienizare'].map((p) => box(p).checked))
      .toEqual([true, true, false, true])
    /* окно говорит, что уезжает: «с зубом» или нет — но не номер зуба и не врача */
    const text = dlg()?.textContent ?? ''
    expect(text).toContain('Nimic despre pacient nu intră în șablon: nici dinții, nici medicul, nici notițele.')
    expect(text).not.toContain('36')
    expect(text).not.toContain('Dr. Activ Doi')
    expect(text).not.toContain('4 500')
    fireEvent.click(inDlg().getByRole('checkbox', { name: 'Păstrează prețurile' }))
    expect(dlg()?.textContent).toContain('4 500 MDL')
    fireEvent.click(box('Implant dentar'))
    fireEvent.click(box('Consultație'))
    fireEvent.change(name(), { target: { value: '  Implant + coroană ' } })
    post.mockResolvedValue(ok(card(), 'ok_ptpl_new', 'Șablonul a fost salvat'))
    fireEvent.click(save())
    await waitFor(() => expect(dlg()).toBeNull())
    expect(post).toHaveBeenLastCalledWith('/patients/5/plan/save-template',
      { name: 'Implant + coroană', item_ids: [2, 3, 4], keep_prices: true })
  })

  it('отказ сервера — в окне: занятое имя подсвечено, ввод цел; без позиций сохранять нечего', async () => {
    const { form } = await openSave()
    fireEvent.change(name(), { target: { value: 'Canal' } })
    await waitFor(() => expect(form).toHaveBeenLastCalledWith('planSave', true))
    post.mockRejectedValueOnce(new ApiError(
      { kind: 'validation', code: 'dup_ptpl', text: 'Există deja un șablon cu acest nume — alegeți alt nume', field: 'name' }, 'v'))
    fireEvent.click(save())
    expect((await inDlg().findByRole('alert')).textContent).toContain('Există deja un șablon cu acest nume')
    expect([name().getAttribute('aria-invalid'), name().value]).toEqual(['true', 'Canal'])
    expect(post).toHaveBeenLastCalledWith('/patients/5/plan/save-template',
      { name: 'Canal', item_ids: [1, 2, 4], keep_prices: false })
    for (const p of ['Consultație', 'Coroană zirconiu', 'Igienizare']) fireEvent.click(box(p))
    expect(save().disabled).toBe(true)
  })

  it('закрытие с набранным именем — вопрос; пустое окно закрывается сразу', async () => {
    const confirm = vi.spyOn(window, 'confirm')
    await openSave()
    fireEvent.click(inDlg().getByRole('button', { name: 'Renunță' }))
    await waitFor(() => expect(dlg()).toBeNull())
    expect(confirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Acțiuni pentru tot planul' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Salvează ca șablon' }))
    await waitFor(() => expect(dlg()?.hasAttribute('open')).toBe(true))
    fireEvent.change(name(), { target: { value: 'Ceva' } })
    confirm.mockReturnValueOnce(false)
    fireEvent.click(inDlg().getByRole('button', { name: 'Renunță' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(name().value).toBe('Ceva')
    expect(post).not.toHaveBeenCalled()
  })
})
