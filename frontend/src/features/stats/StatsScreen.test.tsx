import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import { ApiError } from '../../types/api'
import type { StatsData } from './stats'
import { loadStats, StatsScreen } from './StatsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const WEEK: StatsData = {
  period: { from: '2026-09-15', to: '2026-09-21', label: '15.09.2026 — 21.09.2026',
            short: '15.09–21.09', days: 7 },
  presets: [
    { key: 'azi', label: 'Azi', from: '2026-09-21', to: '2026-09-21' },
    { key: 'd7', label: '7 zile', from: '2026-09-15', to: '2026-09-21' },
  ],
  compare: 'față de săptămâna trecută',
  export_url: '/admin/export.xlsx?from=2026-09-15&to=2026-09-21',
  tiles: [
    { key: 'total', label: 'Programări', value: 24, icon: 'cal', tone: 'var(--green)',
      soft: 'var(--green-soft)', bad: false, series: [2, 4, 6, 3, 5, 2, 2],
      trend: { dir: 'up', icon: 'caret-u', value: '12%',
               label: 'față de săptămâna trecută', note: '' } },
    { key: 'cancel', label: 'Anulate', value: 3, icon: 'ban', tone: 'var(--red)',
      soft: 'var(--red-soft)', bad: true, series: [1, 0, 1, 0, 1, 0, 0],
      trend: { dir: 'dn', icon: 'caret-u', value: '50%',
               label: 'față de săptămâna trecută', note: '' } },
  ],
  chart: {
    labels: ['15.09', '16.09'], values: [2, 4],
    title: 'Programări pe zile', sub: '· 15.09 — 21.09.2026', total: 24,
    total_trend: { dir: '', icon: '', value: '', label: 'față de săptămâna trecută', note: '' },
    present_pct: 83, noshow: 2, loss: 'cca 1 000 MDL pierdut',
    wait: { text: '7 min', sub: '3 vizite măsurate' },
  },
  sources: { show: false, total: 24, parts: [] },
  occupancy: { pct: 61, note: 'media 15.09–21.09 (7 zile)' },
  money: [
    { key: 'incasari', title: 'Încasări', sub: '· bani reali, 15.09–21.09',
      value: 4200, text: '4 200 MDL', suffix: ' MDL',
      trend: { dir: 'up', icon: 'caret-u', value: '+1 200 MDL',
               label: 'față de săptămâna trecută', note: '' },
      note: [{ icon: 'cash', t: '2 000 MDL' }, { icon: 'card', t: '2 200 MDL' }],
      link: { href: '/admin/casa', label: 'Raport de casă (azi) ›', icon: 'print' } },
  ],
  doctors: [{ name: 'Dr. Ana', off: false, n: 12, came: 10, pres: 83, pct: 61 }],
  services: [{ label: 'Consultație', cnt: 5, val: 'cca 1 500 MDL', pct: 100 }],
  activity: [{ text: 'Fișă actualizată', name: 'Ion P', patient_id: 7,
               who: 'Ana', at: '21.09 10:20' }],
  hint: 'Prețurile sunt medii orientative din lista clinicii.',
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

/* Экран открывается РОУТЕРОМ, как в App.tsx: период приносит загрузчик. */
const open = (url = '/admin/stats', navigate = vi.fn()) =>
  openScreen('/admin/stats', url, <StatsScreen navigate={navigate} />, loadStats, navigate)

const DENIED = new ApiError({ kind: 'forbidden', code: 'no_access', text: 'Nu aveți acces la această secțiune' }, 'f')

/* Сервер в миниатюре для проверок адреса: период из запроса, перевёрнутый —
   развёрнут (как `period()`), без запроса — неделя по умолчанию. */
const ro = (iso: string) => iso.split('-').reverse().join('.')
const span = (from: string, to: string): StatsData => ({
  ...WEEK,
  period: { from, to, label: `${ro(from)} — ${ro(to)}`, short: '', days: 0 },
})
const serve = (path: string) => {
  const q = new URLSearchParams(path.split('?')[1] ?? '')
  const a = q.get('from') ?? WEEK.period.from
  const b = q.get('to') ?? WEEK.period.to
  return Promise.resolve(ok(a <= b ? span(a, b) : span(b, a)))
}
const lastPath = () => get.mock.lastCall?.[0] as string

/* ⭐ F5: СВЕЖИЙ роутер на адресе, который экран записал, обязан попросить у
   сервера ТОТ ЖЕ период, что показывал экран до перезагрузки. */
async function reload(router: ReturnType<typeof open>['router']) {
  const before = lastPath()
  const url = router.state.location.pathname + router.state.location.search
  cleanup()
  get.mockClear()
  open(url)
  await waitFor(() => expect(get).toHaveBeenCalled())
  expect(lastPath()).toBe(before)
}

afterEach(() => {
  cleanup()
  get.mockReset()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/admin/stats')
})

describe('StatsScreen', () => {
  it('период, плитки, врачи, услуги и лента — всё из одного конверта', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    expect(await screen.findByText('15.09.2026 — 21.09.2026')).toBeTruthy()
    expect(screen.getByText('Programări pe zile')).toBeTruthy()
    expect(screen.getByText('Dr. Ana')).toBeTruthy()
    expect(screen.getByText('Consultație')).toBeTruthy()
    expect(screen.getByText('Fișă actualizată')).toBeTruthy()
    /* Ссылка на фишу пациента из ленты — как на старой странице. */
    expect(screen.getByRole('link', { name: 'Ion P' }).getAttribute('href'))
      .toBe('/admin/patient/7')
  })

  it('деньги показываются СТРОКОЙ СЕРВЕРА и с суффиксом валюты', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    /* ⛔ `data-count` равен значению ВСЕГДА: анимация — представление, а не
       источник правды (у легаси это контракт, проверки читают атрибут). */
    const b = await screen.findByText('4 200 MDL')
    expect(b.getAttribute('data-count')).toBe('4200')
    /* ⚠️ Разделитель тысяч у счётчика свой (текст переписывается на каждом
       кадре), и он обязан СОВПАДАТЬ со строкой сервера — иначе цифра меняет
       вид в момент, когда анимация кончилась. */
    expect(b.textContent).toBe(WEEK.money[0]!.text)
    expect(screen.getByRole('link', { name: /Raport de casă/ }).getAttribute('href'))
      .toBe('/admin/casa')
  })

  it('рост плохого — стрелка вверх, но цвет КРАСНЫЙ: тон берётся у сервера', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    await screen.findByText('Anulate')
    /* Отмены выросли на 50%: направление `dn` (плохо) при стрелке вверх.
       Вычисли класс из знака числа — и рост неявок позеленел бы. */
    const bad = screen.getByText('50%').closest('span')
    expect(bad?.className).toBe('dn')
  })

  it('«неизменно» — это СЛОВО, а не нулевой процент', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    expect(await screen.findByText(/neschimbat față de săptămâna trecută/)).toBeTruthy()
  })

  it('один источник — кольца нет вовсе: это тавтология, а не разбивка', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    await screen.findByText('Programări pe zile')
    expect(screen.queryByText('Surse programări')).toBeNull()
  })

  it('готовый период меняет отбор и АДРЕС — закладка открывает тот же', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    get.mockResolvedValueOnce(ok({
      ...WEEK,
      period: { from: '2026-09-21', to: '2026-09-21', label: '21.09.2026 — 21.09.2026',
                short: '21.09–21.09', days: 1 },
    }))
    const { router } = open()
    await screen.findByText('15.09.2026 — 21.09.2026')
    fireEvent.click(screen.getByRole('link', { name: 'Azi' }))
    expect(await screen.findByText('21.09.2026 — 21.09.2026')).toBeTruthy()
    expect(get).toHaveBeenLastCalledWith('/stats?from=2026-09-21&to=2026-09-21',
      expect.anything())
    /* ⭐ Адрес ведёт РОУТЕР, и заменой: смена периода не копит шагов «Назад». */
    expect(router.state.location.search).toBe('?from=2026-09-21&to=2026-09-21')
    expect(router.state.historyAction).toBe('REPLACE')
  })

  it('открытие по адресу: период загрузчик берёт из адреса, каждую границу — отдельно', async () => {
    get.mockImplementation(serve)
    open('/admin/stats?from=2026-09-01&to=2026-09-10')
    expect(await screen.findByText('01.09.2026 — 10.09.2026')).toBeTruthy()
    expect(lastPath()).toBe('/stats?from=2026-09-01&to=2026-09-10')
    /* ⛔ Одна граница — НЕ повод отбросить обе: недостающую достраивает
       `period()` сервера, как и на странице после F5 (X..сегодня). */
    cleanup()
    open('/admin/stats?from=2026-09-01')
    await waitFor(() => expect(lastPath()).toBe('/stats?from=2026-09-01'))
    cleanup()
    open('/admin/stats?to=2026-09-10')
    await waitFor(() => expect(lastPath()).toBe('/stats?to=2026-09-10'))
    /* Хвосты адреса, кроме периода, в запрос не уходят. */
    cleanup()
    open('/admin/stats?msg=bad_period&from=2026-09-01&to=2026-09-10&ui=x')
    await waitFor(() => expect(lastPath()).toBe('/stats?from=2026-09-01&to=2026-09-10'))
  })

  it('пока идёт новый период — на экране прежний, без сброса в загрузку', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    get.mockReturnValueOnce(new Promise(() => {}))
    open()
    await screen.findByText('15.09.2026 — 21.09.2026')
    fireEvent.click(screen.getByRole('link', { name: 'Azi' }))
    await waitFor(() => expect(lastPath()).toBe('/stats?from=2026-09-21&to=2026-09-21'))
    expect(screen.getByText('15.09.2026 — 21.09.2026')).toBeTruthy()
    expect(document.querySelector('[aria-busy]')).toBeNull()
  })

  it('поля: проверка сервером, в адрес — период из ОТВЕТА, данные — загрузчиком', async () => {
    get.mockImplementation(serve)
    let answer: (r: ApiResult<StatsData>) => void = () => {}
    const { router } = open()
    await screen.findByText('15.09.2026 — 21.09.2026')
    const [from, to] = screen.getAllByDisplayValue(/2026-09/) as [HTMLInputElement, HTMLInputElement]
    fireEvent.change(from, { target: { value: '2026-09-21' } })
    fireEvent.change(to, { target: { value: '2026-09-10' } })
    /* Ответ загрузчика придержан: видно, что стоит на экране в этот миг. */
    get.mockImplementationOnce(serve)
    get.mockImplementationOnce(() => new Promise((res) => { answer = res }))
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    /* Перевёрнутый период уходит на проверку как набран, а загрузчику и в
       адрес — уже развёрнутым: адрес описывает то, что сервер покажет и
       после F5. */
    await waitFor(() => expect(get).toHaveBeenCalledTimes(3))
    expect(get.mock.calls.map((c) => c[0])).toEqual([
      '/stats', '/stats?from=2026-09-21&to=2026-09-10', '/stats?from=2026-09-10&to=2026-09-21'])
    expect(router.state.navigation.location?.search).toBe('?from=2026-09-10&to=2026-09-21')
    /* Пока ответа нет: прежний период на экране, набранное — в полях. */
    expect(screen.getByText('15.09.2026 — 21.09.2026')).toBeTruthy()
    expect(from.value).toBe('2026-09-21')
    expect(to.value).toBe('2026-09-10')
    answer(ok(span('2026-09-10', '2026-09-21')))
    expect(await screen.findByText('10.09.2026 — 21.09.2026')).toBeTruthy()
    expect(from.value).toBe('2026-09-10')
    expect(to.value).toBe('2026-09-21')
    expect(router.state.location.search).toBe('?from=2026-09-10&to=2026-09-21')
    expect(router.state.historyAction).toBe('REPLACE')
    /* Один путь к данным: после ответа загрузчика — ни одного запроса сверх. */
    expect(get).toHaveBeenCalledTimes(3)
  })

  it('перевёрнутый период, равный текущему: адрес тот же, поля всё равно уступают эху', async () => {
    get.mockImplementation(serve)
    const { router } = open('/admin/stats?from=2026-09-10&to=2026-09-21')
    await screen.findByText('10.09.2026 — 21.09.2026')
    const [from, to] = screen.getAllByDisplayValue(/2026-09/) as [HTMLInputElement, HTMLInputElement]
    fireEvent.change(from, { target: { value: '2026-09-21' } })
    fireEvent.change(to, { target: { value: '2026-09-10' } })
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    /* Переход на ТОТ ЖЕ адрес роутер отрабатывает загрузчиком заново — иначе
       набранные перевёрнутыми цифры так и стояли бы в полях. */
    await waitFor(() => expect(from.value).toBe('2026-09-10'))
    expect(to.value).toBe('2026-09-21')
    expect(get).toHaveBeenCalledTimes(3)
    expect(router.state.location.search).toBe('?from=2026-09-10&to=2026-09-21')
  })

  it('F5 на адресе готового периода — тот же период', async () => {
    get.mockImplementation(serve)
    const { router } = open()
    await screen.findByText('15.09.2026 — 21.09.2026')
    fireEvent.click(screen.getByRole('link', { name: 'Azi' }))
    expect(await screen.findByText('21.09.2026 — 21.09.2026')).toBeTruthy()
    await reload(router)
    expect(await screen.findByText('21.09.2026 — 21.09.2026')).toBeTruthy()
  })

  it('F5 на адресе из полей — тот же период', async () => {
    get.mockImplementation(serve)
    const { router } = open()
    await screen.findByText('15.09.2026 — 21.09.2026')
    const [from, to] = screen.getAllByDisplayValue(/2026-09/) as [HTMLInputElement, HTMLInputElement]
    fireEvent.change(from, { target: { value: '2026-09-21' } })
    fireEvent.change(to, { target: { value: '2026-09-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('01.09.2026 — 21.09.2026')).toBeTruthy()
    await reload(router)
    expect(await screen.findByText('01.09.2026 — 21.09.2026')).toBeTruthy()
  })

  it('негодный период — отказ сервера, а НЕ молча другой период', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    get.mockRejectedValueOnce(new ApiError(
      { kind: 'validation', code: 'bad_period', text: 'Perioada aleasă nu este validă' },
      'bad_period'))
    const { router } = open()
    const inputs = await screen.findAllByDisplayValue(/2026-09/)
    fireEvent.change(inputs[0]!, { target: { value: '0012-09-15' } })
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('Perioada aleasă nu este validă')).toBeTruthy()
    /* Цифры остались теми, что человек набрал: экран не подменил их своими. */
    await waitFor(() => expect(screen.getByDisplayValue('0012-09-15')).toBeTruthy())
    /* Отказ — не переход: адрес прежний, и загрузчик не ходил второй раз. */
    expect(router.state.location.search).toBe('')
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('B3: без права — экран НЕ монтируется, уход туда же, куда страница сервера', async () => {
    get.mockRejectedValueOnce(DENIED)
    const navigate = vi.fn()
    open('/admin/stats', navigate)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin?msg=no_access'))
    /* ⛔ Ни плашки отказа внутри раздела, ни его кадра: экрана нет. */
    await waitFor(() => expect(document.querySelector('.dp-react-root')).toBeNull())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('B3: право отняли посреди сеанса — первый же переход уводит, старый период не остаётся', async () => {
    get.mockResolvedValueOnce(ok(WEEK)).mockRejectedValueOnce(DENIED)
    const navigate = vi.fn()
    open('/admin/stats', navigate)
    await screen.findByText('15.09.2026 — 21.09.2026')
    fireEvent.click(screen.getByRole('link', { name: 'Azi' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/admin?msg=no_access'))
    await waitFor(() => expect(screen.queryByText('15.09.2026 — 21.09.2026')).toBeNull())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
