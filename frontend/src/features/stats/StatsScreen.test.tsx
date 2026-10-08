import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import { ApiError } from '../../types/api'
import type { Board, StatsData } from './stats'
import { loadStats, StatsScreen } from './StatsScreen'
import { niceStep } from './StatsCharts'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const NONE = { dir: '' as const, icon: '', value: '', label: 'față de săptămâna trecută', note: '' }

const BOARD: Board = {
  prev_name: 'săptămâna trecută',
  kpis: [
    { key: 'incasari', label: 'Încasări', icon: 'cash', text: '4 200 MDL', value: 4200,
      badge: { dir: 'up', icon: 'caret-u', text: '+40%' },
      trend: { dir: 'up', icon: 'caret-u', value: '+1 200 MDL', label: 'față de săptămâna trecută', note: '' },
      prev: '3 000 MDL', sub: '3 plăți · medie 1 400 MDL', series: [0, 1200, 0, 3000, 0, 0, 0] },
    { key: 'programari', label: 'Programări', icon: 'cal', text: '24', value: 24,
      badge: { dir: 'up', icon: 'caret-u', text: '+12%' }, trend: NONE,
      prev: '21', sub: '20 au venit · 3 anulate', series: [2, 4, 6, 3, 5, 2, 2] },
    /* ⛔ Рост ПЛОХОГО: стрелка вверх, а направление `dn` — цвет красный. */
    { key: 'prezenta', label: 'Rata de prezență', icon: 'checkin', text: '83%', value: 83,
      badge: { dir: 'dn', icon: 'caret-u', text: '+50%' }, trend: NONE,
      prev: '85%', sub: '2 neprezentări · cca 1 000 MDL pierdut', pct: 83 },
    { key: 'ocupare', label: 'Grad de ocupare', icon: 'clock', text: '61%', value: 61,
      badge: { dir: '', icon: '', text: '0 p.p.' }, trend: NONE,
      prev: '61%', sub: '51 ore ocupate din 84 ore de lucru', pct: 61 },
  ],
  parts: [
    { key: 'numerar', label: 'Numerar', value: 2000, text: '2 000 MDL', color: 'var(--teal)', pct: 48 },
    { key: 'card', label: 'Card', value: 2200, text: '2 200 MDL', color: 'var(--blue)', pct: 52 },
    { key: 'transfer', label: 'Transfer', value: 0, text: '0 MDL', color: 'var(--violet)', pct: 0 },
  ],
  series: {
    bucket: 'day',
    labels: ['15.09', '16.09', '17.09', '18.09', '19.09', '20.09', '21.09'],
    hints: ['Lu, 15.09.2026', 'Ma, 16.09.2026', 'Mi, 17.09.2026', 'Jo, 18.09.2026',
            'Vi, 19.09.2026', 'Sâ, 20.09.2026', 'Du, 21.09.2026'],
    appts: [2, 4, 6, 3, 5, 2, 0],
    income: [0, 1200, 0, 3000, 0, 0, 0],
    income_text: ['0 MDL', '1 200 MDL', '0 MDL', '3 000 MDL', '0 MDL', '0 MDL', '0 MDL'],
  },
  summary: {
    appts: { total: '24', avg: '4,0', best: 'Mi, 17.09.2026 · 6' },
    income: { total: '4 200 MDL', avg: '700 MDL', best: 'Jo, 18.09.2026 · 3 000 MDL' },
    work_days: 6,
  },
  money: {
    estimated: '5 000 MDL', estimated_trend: NONE, cash: '4 200 MDL',
    loss: 'cca 1 000 MDL', noshow: 2, today_cash: '0 MDL', today_estimated: '0 MDL',
    link: { href: '/admin/casa', label: 'Raport de casă (azi)', icon: 'print' },
  },
}

const WEEK: StatsData = {
  period: { from: '2026-09-15', to: '2026-09-21', label: '15.09.2026 — 21.09.2026',
            short: '15.09–21.09', days: 7 },
  presets: [
    { key: 'azi', label: 'Azi', from: '2026-09-21', to: '2026-09-21' },
    { key: 'd7', label: '7 zile', from: '2026-09-15', to: '2026-09-21' },
  ],
  compare: 'față de săptămâna trecută',
  export_url: '/admin/export.xlsx?from=2026-09-15&to=2026-09-21',
  /* Поля старой страницы едут в том же конверте (её рисует сервер для
     `?ui=legacy`); экран их не читает. */
  tiles: [],
  chart: {
    labels: [], values: [], title: 'Programări pe zile', sub: '', total: 24,
    total_trend: NONE, present_pct: 83, noshow: 2, loss: 'cca 1 000 MDL pierdut',
    wait: { text: '7 min', sub: '3 vizite măsurate' },
  },
  sources: { show: false, total: 24, parts: [] },
  occupancy: { pct: 61, note: '' },
  money: [],
  doctors: [{ name: 'Dr. Ana', off: false, n: 12, came: 10, pres: 83, pct: 61,
              id: 'd1', spec: 'Terapie', color: '#0E9F8A', initials: 'DA', photo: '' }],
  services: [
    { label: 'Consultație', cnt: 5, val: 'cca 0 MDL', val_n: 0, pct: 100 },
    { label: 'Tratament carie', cnt: 3, val: 'cca 4 500 MDL', val_n: 4500, pct: 60 },
  ],
  activity: [{ text: 'Fișă actualizată', name: 'Ion P', patient_id: 7,
               who: 'Ana', at: '21.09 10:20' }],
  board: BOARD,
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

/* Поля периода живут за кнопкой «Interval»: открыть и взять оба поля. */
function dateFields() {
  fireEvent.click(screen.getByRole('button', { name: /Interval/ }))
  return screen.getAllByDisplayValue(/2026-09/) as [HTMLInputElement, HTMLInputElement]
}

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
  it('период, показатели, график, врачи, услуги и лента — всё из одного конверта', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    expect(await screen.findByText('15.09.2026 — 21.09.2026')).toBeTruthy()
    expect(screen.getByText('Programări pe zile')).toBeTruthy()
    /* подпись раздела — период и «comparat cu …» (08.10) */
    expect(document.querySelector('.dp-react-root > .sub')?.textContent)
      .toBe('15.09.2026 — 21.09.2026 · comparat cu săptămâna trecută')
    expect(document.querySelectorAll('.stx-kpi').length).toBe(4)
    expect(screen.getByText('Dr. Ana')).toBeTruthy()
    expect(screen.getByText('Consultație')).toBeTruthy()
    expect(screen.getByText('Fișă actualizată')).toBeTruthy()
    /* Ссылка на фишу пациента из ленты — как на старой странице. */
    expect(screen.getByRole('link', { name: 'Ion P' }).getAttribute('href'))
      .toBe('/admin/patient/7')
    /* Кольца источников нет: у клиники без бота это тавтология, а долю бота
       сервер при живом боте пишет строкой разбора «Programări». */
    expect(screen.queryByText('Surse programări')).toBeNull()
  })

  it('деньги показываются СТРОКОЙ СЕРВЕРА и с суффиксом валюты', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    await screen.findByText('15.09.2026 — 21.09.2026')
    /* ⛔ `data-count` равен значению ВСЕГДА: анимация — представление, а не
       источник правды. */
    const b = document.querySelector('[data-kpi="incasari"] b[data-count]')!
    expect(b.getAttribute('data-count')).toBe('4200')
    /* ⚠️ Разделитель тысяч у счётчика свой (текст переписывается на каждом
       кадре), и он обязан СОВПАДАТЬ со строкой сервера. */
    expect(b.textContent).toBe(BOARD.kpis[0]!.text)
    /* У каждой карточки — значение прошлого периода, названного по имени. */
    expect(screen.getAllByText('săptămâna trecută:', { exact: false }).length).toBe(4)
    expect(screen.getByRole('link', { name: /Raport de casă/ }).getAttribute('href'))
      .toBe('/admin/casa')
  })

  it('метка сравнения: рост плохого — стрелка вверх, но цвет КРАСНЫЙ', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    await screen.findByText('Rata de prezență')
    /* Вычисли класс из знака числа — и рост неявок позеленел бы. */
    expect(screen.getByText('+50%').closest('.stx-badge')?.className).toBe('stx-badge dn')
    expect(screen.getByText('+40%').closest('.stx-badge')?.className).toBe('stx-badge up')
    expect(screen.getByText('0 p.p.').closest('.stx-badge')?.className).toBe('stx-badge')
  })

  it('«неизменно» — это СЛОВО, а не нулевой процент', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    expect(await screen.findByText(/neschimbat față de săptămâna trecută/)).toBeTruthy()
  })

  it('график: подсказка показывает значение, «Încasări» — деньгами сервера', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    await screen.findByText('Programări pe zile')
    const cols = () => document.querySelectorAll('.stx-bcol')
    expect(cols().length).toBe(7)
    /* столбец фокусируем и назван (08.10): подсказка — теми же словами */
    expect(cols()[2]!.getAttribute('tabindex')).toBe('0')
    expect(cols()[2]!.getAttribute('aria-label')).toBe('Mi, 17.09.2026: 6 programări')
    expect(cols()[2]!.querySelector('.stx-tip')?.textContent).toBe('Mi, 17.09.2026: 6 programări')
    expect(screen.getByText('Mi, 17.09.2026 · 6')).toBeTruthy()
    /* числом подписан только самый высокий столбец; день недели — над датой */
    expect(document.querySelectorAll('.stx-top').length).toBe(1)
    expect(document.querySelector('.stx-top')?.textContent).toBe('6')
    expect(document.querySelector('.stx-xax b')?.textContent).toBe('Lu')
    fireEvent.click(screen.getByRole('button', { name: 'Încasări' }))
    expect(screen.getByRole('button', { name: 'Încasări' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('Încasări pe zile')).toBeTruthy()
    expect(cols()[3]!.getAttribute('aria-label')).toBe('Jo, 18.09.2026: 3 000 MDL')
    expect(document.querySelector('.stx-top')?.textContent).toBe('3 000 MDL')
    expect(screen.getByText('Jo, 18.09.2026 · 3 000 MDL')).toBeTruthy()
    /* ⭐ Нулевой день — пустое место, а не столбик в пиксель. */
    expect(document.querySelectorAll('.stx-bar').length).toBe(2)
  })

  it('пустой период: фраза вместо пустой сетки', async () => {
    const empty: StatsData = {
      ...WEEK,
      board: { ...BOARD, series: { ...BOARD.series, appts: [0, 0, 0, 0, 0, 0, 0] } },
    }
    get.mockResolvedValueOnce(ok(empty))
    open()
    expect(await screen.findByText('— nimic în perioada aleasă —')).toBeTruthy()
    expect(document.querySelector('.stx-cols')).toBeNull()
  })

  it('врач — с аватаром от сервера; бесплатная услуга — без «cca 0 MDL»', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    open()
    expect(await screen.findByText('DA')).toBeTruthy()
    expect(screen.getByText('Terapie')).toBeTruthy()
    expect(screen.queryByText('cca 0 MDL')).toBeNull()
    expect(screen.getByText('cca 4 500 MDL')).toBeTruthy()
  })

  it('шкала оси «круглая»: 1, 2, 2.5, 5 × 10^k', () => {
    expect(niceStep(4.8)).toBe(5)
    expect(niceStep(0.3)).toBe(1)
    expect(niceStep(2.2)).toBe(2.5)
    expect(niceStep(4790)).toBe(5000)
    expect(niceStep(12)).toBe(20)
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
    /* Текущий готовый период отмечен, «Interval» — нет. */
    expect(screen.getByRole('link', { name: '7 zile' }).getAttribute('aria-current')).toBe('true')
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
    const [from, to] = dateFields()
    fireEvent.change(from, { target: { value: '2026-09-21' } })
    fireEvent.change(to, { target: { value: '2026-09-10' } })
    /* Ответ загрузчика придержан: видно, что стоит на экране в этот миг. */
    get.mockImplementationOnce(serve)
    get.mockImplementationOnce(() => new Promise((res) => { answer = res }))
    fireEvent.click(screen.getByRole('button', { name: 'Aplică' }))
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
    const [from, to] = dateFields()
    fireEvent.change(from, { target: { value: '2026-09-21' } })
    fireEvent.change(to, { target: { value: '2026-09-10' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aplică' }))
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
    const [from, to] = dateFields()
    fireEvent.change(from, { target: { value: '2026-09-21' } })
    fireEvent.change(to, { target: { value: '2026-09-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aplică' }))
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
    await screen.findByText('15.09.2026 — 21.09.2026')
    const [from] = dateFields()
    fireEvent.change(from, { target: { value: '0012-09-15' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aplică' }))
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
