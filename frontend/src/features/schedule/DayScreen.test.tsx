import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import { ApiError } from '../../types/api'
import { DayScreen, loadDay } from './DayScreen'
import type { DashBlock, DashCanvasModel } from './dash'
import type { DayModel } from './day'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const appt = (id: number, time: string, name: string, extra = {}) => ({
  kind: 'appt' as const, id, time, name, service: 'Consultație',
  phone: '069000000', status: 'confirmed', status_label: 'Confirmat',
  urgent: false, source: 'panel', dur: 60, comment: '', comment_cut: '', age: null,
  clickable: true, bg: 'var(--green-soft)', bar: 'var(--green)',
  min: 600, busy: true, movable: true, ...extra,
})

const LONG = 'Alergie la penicilină; de sunat cu o zi înainte; vine cu mama; dimineața'

/* Блок канвы — тот же вид записи, что у панели (`canvas.blocks` из
   `day.appt_view`) плюс геометрия. */
const block = (id: number, time: string, name: string,
  extra: Partial<Extract<DashBlock, { kind: 'appt' }>> = {}): Extract<DashBlock, { kind: 'appt' }> => ({
  kind: 'appt', id, time, name, service: 'Consultație', phone: '069000000',
  status: 'confirmed', status_label: 'Confirmat', urgent: false, source: 'panel', dur: 60,
  comment: '', comment_cut: '', age: null, clickable: true,
  bg: 'var(--green-soft)', bar: 'var(--green)', min: 540, busy: true, movable: true,
  doctor: 'Dr. Activ Doi', pid: 7, rec: false, top: 0, height: 1, col: 0, of: 1,
  title: `${time} · 60′ · Consultație · ${name}`, wait_since: null, ...extra,
})

/* ⭐ Сетка дня с 06.10 — КАНВА панели (`DashCanvas`), а не таблица. Часы 9–12,
   ряды по 40 пикселей с сотого (подмена геометрии ниже). У Doi закрыт 12:00,
   в 11:00 у него заметка стойки; Trei выключен и принимает весь день. */
const HOURS = [9, 10, 11, 12]
const CANVAS: DashCanvasModel = {
  date: '2026-09-23', empty: false, base_min: 540, tight: false,
  hours: HOURS.map((h) => ({ h, label: `${String(h).padStart(2, '0')}:00`, now: h === 10 })),
  bands: { top: null, bottom: null },
  columns: [
    {
      key: 'k:d2', id: 'd2', name: 'Dr. Activ Doi', orphan: false, spec: 'Terapeut', off: false,
      hue: 'var(--teal)', photo: '', initials: 'AD', count: 1, free: '10:00',
      occupancy: { busy: 60, cap: 480, pct: 13 }, title: 'Dr. Activ Doi',
      cells: [true, true, true, false],
      blocks: [
        block(1, '09:00', 'Ion Popa', { comment: LONG, comment_cut: LONG.slice(0, 60) }),
        { kind: 'note', id: 9, time: '11:00', min: 660, dur: 60, busy: true, movable: true,
          status: 'confirmed', top: 2, height: 1, col: 0, of: 1,
          title: 'Livrare', text: 'Livrare', label: 'Livrare' },
      ],
      relink: null,
    },
    {
      key: 'k:d3', id: 'd3', name: 'Dr. Activ Trei', orphan: false, spec: 'Ortodont', off: true,
      hue: 'var(--violet)', photo: '', initials: 'AT', count: 1, free: '09:00',
      occupancy: null, title: 'Dr. Activ Trei', cells: [true, true, true, true],
      blocks: [block(2, '10:00', 'Maria Rusu', {
        min: 600, top: 1, status: 'noshow', status_label: 'Nu s-a prezentat', urgent: true,
        service: 'Durere acută', age: 36, comment: 'sună înainte', comment_cut: 'sună înainte',
        bg: 'var(--red-soft)', bar: 'var(--red)', movable: false, busy: false,
        doctor: 'Dr. Activ Trei', pid: 8, rec: true,
      })],
      relink: null,
    },
  ],
}

/* ⛔ Две колонки, и вторая пустая в 09:00: если ячейки раскладывать не по
   позиции в списке врачей, запись переедет к соседу — и это выглядит нормально. */
const MODEL: DayModel = {
  date: '2026-09-23',
  day_label: 'Mi 23.09.2026',
  canvas: CANVAS,
  source_col: true,
  doctors: [
    { id: 'd2', name: 'Dr. Activ Doi', spec: 'Terapeut' },
    { id: 'd3', name: 'Dr. Activ Trei', spec: 'Ortodont · inactiv' },
  ],
  hours: [
    {
      h: 9, label: '09:00', closed: '', now: false, cells: [
        { kind: 'appts', drop: true, items: [appt(1, '09:00', 'Ion Popa', {
          min: 540, comment: LONG, comment_cut: LONG.slice(0, 60),
        })] },
        { kind: 'free', drop: true, items: [] },
      ],
    },
    {
      h: 10, label: '10:00', closed: '', now: true, cells: [
        { kind: 'busy', drop: true, items: [] },
        {
          kind: 'appts', drop: true, items: [appt(2, '10:00', 'Maria Rusu', {
            status: 'noshow', status_label: 'Nu s-a prezentat', urgent: true,
            service: 'Durere acută', age: 36,
            // короткий комментарий: обрезок совпадает с полным — так его
            // и отдаёт сервер, и ячейка обязана его показать
            comment: 'sună înainte', comment_cut: 'sună înainte',
            bg: 'var(--red-soft)', bar: 'var(--red)', movable: false, busy: false,
          })],
        },
      ],
    },
    {
      h: 13, label: '13:00', closed: 'pauza', now: false, cells: [
        { kind: 'off', drop: false, items: [] },
        { kind: 'off', drop: false, items: [] },
      ],
    },
    {
      h: 19, label: '19:00', closed: 'inchis', now: false, cells: [
        { kind: 'appts', drop: false, items: [{ kind: 'note', id: 9, time: '19:00', text: 'Livrare', status: 'confirmed', min: 1140, dur: 60, busy: false, movable: false }] },
        { kind: 'off', drop: false, items: [] },
      ],
    },
  ],
  form: {
    doctors: [{ id: 'd2', name: 'Dr. Activ Doi', spec: '' },
      { id: 'd4', name: 'Dr. Activ Patru', spec: '' }],
    times: { d2: ['09:00', '09:30', '10:00'], d4: ['14:00', '14:30'] },
    hours: ['09:00', '09:30', '10:00', '14:00', '14:30'],
    services: [{ id: 'consult', label: 'Consultație' }, { id: 'pain', label: 'Durere acută' }],
    doctor: 'd2', time: '', birth_max: '2026-09-19',
  },
  note_ends: [10, 11, 12, 15],
  cards: {
    1: { name: 'Ion Popa', phone: '069000000', service: 'Consultație',
      doctor: 'Dr. Activ Doi', time: '09:00', comment: LONG, age: 41,
      status: 'confirmed', pid: 7, rec: false },
    2: { name: 'Maria Rusu', phone: '069000001', service: 'Durere acută',
      doctor: 'Dr. Activ Trei', time: '10:00', comment: '', age: 36,
      status: 'noshow', pid: 8, rec: true },
  },
  actions: {
    confirmed: [{ to: 'waiting', cls: 'b-waiting', label: 'A venit', confirm: '' },
      { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' }],
    noshow: [{ to: 'confirmed', cls: 'b-reopen', label: 'Redeschide',
      confirm: 'Redeschideți programarea (înapoi la «confirmată»)?' }],
  },
  note_actions: {
    confirmed: [{ to: 'cancelled', cls: 'b-cancel', label: 'Șterge', confirm: '' }],
    cancelled: [{ to: 'confirmed', cls: 'b-reopen', label: 'Restabilește',
      confirm: 'Restabiliți notița?' }],
  },
  list: [
    { id: 1, is_note: false, time: '09:00', name: 'Ion Popa', age: 41,
      phone: '069000000', service: 'Consultație', urgent: false, comment: LONG, comment_cut: LONG.slice(0, 80),
      doctor: 'Dr. Activ Doi', source: 'panel', source_label: 'manual',
      status: 'confirmed', status_view: 'confirmed', status_label: 'Confirmat', reminded: false, rec: false },
    { id: 2, is_note: false, time: '10:00', name: 'Maria Rusu', age: 36,
      phone: '069000001', service: 'Durere acută', urgent: true, comment: '', comment_cut: '',
      doctor: 'Dr. Activ Trei', source: 'bot', source_label: 'bot',
      status: 'noshow', status_view: 'noshow', status_label: 'Nu s-a prezentat', reminded: true, rec: true },
    { id: 9, is_note: true, time: '19:00', name: '', age: null, phone: '',
      service: 'Livrare', urgent: false, comment: '', comment_cut: '', doctor: 'Dr. Activ Doi',
      source: 'note', source_label: 'notiță', status: 'confirmed', status_view: 'confirmed',
      status_label: 'Confirmat', reminded: false, rec: false },
  ],
  filter: null,
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: 'ok', text: 'Programare adăugată', tone: 'ok' })
/* День ответа — тот, что спрошен в адресе: иначе любой переход «приезжал»
   бы тем же днём, и смена дня была бы невидима — ни окну записи, ни
   проверке, которая ждёт новый день на ЭКРАНЕ (см. `addr`). */
const dayOfUrl = (url: string) => {
  const date = /date=([\d-]+)/.exec(url)?.[1] ?? MODEL.date
  return Promise.resolve(ok({ ...MODEL, date, day_label: `Zi ${date}` }))
}
/* Места ссылок в шапке дня (06.10 — как у панели дня и старой шапки):
   «« -7 zile», «‹ день», «Azi», «день ›», «» +7 zile», потом Panou и прочее. */
const WK_PREV = 0, PREV = 1, AZI = 2, NEXT = 3, WK_NEXT = 4, DAY = 5, WEEK = 6
const navLink = (i: number) => document.querySelectorAll('.nav a')[i] as HTMLElement
/* Канва: колонка врача, её час, блок записи. */
const colOf = (dk: string) => document.querySelector(`.gridbody > .gcol[data-dk="${dk}"]`) as HTMLElement
const cellOf = (dk: string, h: number) => colOf(dk)?.querySelector(`.gcell[data-h="${h}"]`) as HTMLElement
const blk = (id: number) => document.querySelector(`.gridbody [data-appt="${id}"]`) as HTMLElement
const canvasShown = () => !!document.querySelector('.gridbody')

/* ⚠️ Координату броска приходится доставлять руками: в jsdom нет `DragEvent`,
   и fireEvent.drop({clientY}) роняет её по дороге — мишень всегда пустая.
   Мышиное событие того же имени React разбирает так же, а координата в нём
   настоящая (тот же приём, что в DashCanvas.test). */
const dropAt = (el: Element, type: 'dragover' | 'drop', clientY: number) =>
  act(() => { fireEvent(el, new MouseEvent(type, { bubbles: true, cancelable: true, clientY })) })

/* jsdom не считает геометрию: ряды канвы подставляются по `data-h`, по 40
   пикселей начиная со сотого (9:00 — 100–140, 10:00 — 140–180…). Без этого
   мишень переноса и половина часа не проверяются вовсе. */
beforeEach(() => {
  get.mockResolvedValue(ok(MODEL))
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
    function rect(this: Element) {
      const h = (this as HTMLElement).dataset?.h
      const i = h === undefined ? -1 : HOURS.indexOf(Number(h))
      const top = i < 0 ? 0 : 100 + i * 40
      return { top, height: i < 0 ? 0 : 40, bottom: top + 40,
        left: 0, right: 0, width: 0, x: 0, y: top, toJSON: () => ({}) } as DOMRect
    })
})
afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); vi.restoreAllMocks() })

/* Экран открывается ТЕМ ЖЕ маршрутом, что в App.tsx: путь решает, общий это
   журнал или день врача, и врача экран получает из пути, как и там. */
const open = async (url: string) => {
  const dk = /^\/admin\/doctor\/([^/?]+)/.exec(url)?.[1] ?? ''
  const r = openScreen(dk ? '/admin/doctor/:dk' : '/admin/all', url,
    <DayScreen doctor={dk} navigate={() => {}} />, loadDay)
  await waitFor(() => expect(canvasShown()).toBe(true))
  return r
}

const show = (props: { date?: string; doctor?: string; f?: string } = {}) => {
  const q = new URLSearchParams()
  if (props.date) q.set('date', props.date)
  if (props.f) q.set('f', props.f)
  const tail = q.toString()
  return open(`${props.doctor ? `/admin/doctor/${props.doctor}` : '/admin/all'}${tail ? `?${tail}` : ''}`)
}

type Router = Awaited<ReturnType<typeof open>>['router']
/** Адрес, которым владеет роутер: его и увидит F5.
 *  ⚠️ После перехода С ЗАГРУЗЧИКОМ роутер ВПЕРЕДИ экрана. Здесь это любая
 *  смена дня; закрытие окна записи — уже нет: снятие якоря роутер считает
 *  перезагрузкой, но с 07.10 её отменяет правило маршрута дня
 *  (`hashChangeKeepsData`). Переход с загрузкой кончается уже вне
 *  `act` щелчка, и `RouterProvider` отдаёт новое состояние React'у через
 *  `startTransition`: `router.state` новый, а экран ещё рисуется кусками по
 *  5 мс — под нагрузкой опрос `waitFor` попадает между ними. Поэтому сперва
 *  ждать то, что видно на ЭКРАНЕ, и только потом сверять адрес; обратный
 *  порядок проверяет DOM и обработчики ПРЕЖНЕЙ отрисовки и краснеет лишь в
 *  полном прогоне (06.10). */
const addr = (router: Router) => router.state.location.pathname + router.state.location.search

/* ⭐ F5-паритет: адрес, записанный экраном, открытый ЗАНОВО — свежим роутером,
   без памяти вкладки, — обязан спросить у сервера тот же день. Иначе переход
   изменил адрес только для глаз, а перезагрузка откроет другое. */
const reloadParity = async (router: Router) => {
  const before = get.mock.lastCall?.[0]
  const at = addr(router)
  cleanup()
  get.mockClear()
  await open(at)
  expect(get).toHaveBeenCalledTimes(1)
  expect(get.mock.lastCall?.[0]).toBe(before)
}

/* ⭐ (06.10) Сетка «Programări» — КАНВА панели: те же шапки врачей, те же
   блоки, те же цвета. Сама канва проверена в DashCanvas.test; здесь — что
   экран дня рисует ИМЕННО её, из своей модели, и что старой таблицы с «+»
   больше нет. */
describe('день журнала: чтение', () => {
  it('сетка — канва панели: шапки врачей сервера, ссылка в их день, выключенный назван', async () => {
    await show()
    const heads = Array.from(document.querySelectorAll('.gridhead .gh-doc .nm a'))
    expect(heads.map((h) => h.textContent)).toEqual(['Dr. Activ Doi', 'Dr. Activ Trei'])
    expect(heads[0]?.getAttribute('href')).toBe('/admin/doctor/d2?date=2026-09-23')
    expect(document.querySelectorAll('.gridhead .gh-doc')[1]?.textContent).toContain('inactiv')
    /* шапка с цветом врача и загрузкой — как у панели */
    expect(document.querySelectorAll('.gridhead .dcard .av')[0]?.textContent).toBe('AD')
    expect(document.querySelector('.gridhead .occ b')?.textContent).toBe('13%')
  })

  it('⛔ старой таблицы нет: ни рядов с «+», ни ссылок в форму', async () => {
    await show()
    expect(document.querySelector('table.grid')).toBeNull()
    expect(document.querySelector('a.free')).toBeNull()
    expect(cellOf('d3', 9)?.textContent).toBe('')
  })

  it('запись стоит в колонке своего врача, а свободный час — пустая ячейка', async () => {
    await show()
    expect(colOf('d2').querySelector('[data-appt="1"]')).toBeTruthy()
    expect(colOf('d3').querySelector('[data-appt="1"]')).toBeNull()
    expect(cellOf('d3', 9)).toBeTruthy()
  })

  it('закрытый час — штриховка без мишени', async () => {
    await show()
    expect(colOf('d2').querySelectorAll('.gcell.off')).toHaveLength(1)
    expect(cellOf('d2', 12)).toBeFalsy()
  })

  it('текущий час подсвечен ровно один раз', async () => {
    await show()
    const nowh = document.querySelectorAll('.gcol-time .nowh')
    expect(nowh).toHaveLength(1)
    expect(nowh[0]?.textContent).toBe('10:00')
  })

  it('блок несёт слово статуса сервера, его цвет и значок комментария', async () => {
    await show()
    const card = blk(2)
    expect(card.className).toContain('noshow')
    expect(card.textContent).toContain('Nu s-a prezentat')   // а не «noshow»
    expect(card.style.background).toBe('var(--red-soft)')
    /* полный комментарий — в подсказке блока; на самом блоке — значок */
    expect(card.title).toContain('sună înainte')
  })

  it('вид блока (03.10) — тот же выбор, что у панели: имя, начало, интервал', async () => {
    /* Выбор вида — у panel.css по `<html data-card>`: «имя впереди» видит
       имя и «09:00 · 60′ · услуга», «время впереди» — интервал (.gtm). */
    await show()
    const card = blk(1)
    expect(card.querySelector('b')?.textContent?.trim()).toBe('Ion Popa')
    expect(card.querySelector('.gtm')?.textContent).toBe('09:00–10:00')
    expect(card.querySelector('.gt')?.textContent).toBe('09:00 · 60′ · ')
  })

  it('заметка стойки — своим видом, и нажатие открывает ЕЁ окно с кнопкой сервера', async () => {
    await show()
    const note = blk(9)
    expect(note.className).toContain('gnote')
    expect(note.textContent).toContain('Livrare')
    fireEvent.click(note)
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
    expect(Array.from(document.querySelectorAll('dialog button'))
      .map((b) => b.textContent?.trim())).toContain('Șterge')
  })

  it('соседний день запрашивается у сервера', async () => {
    const { router } = await show({ date: '2026-09-23' })
    fireEvent.click(navLink(PREV))
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      '/schedule/day?date=2026-09-22', expect.anything()))
    /* ⭐ Адрес ведёт РОУТЕР, а не запись мимо него. */
    await waitFor(() => expect(addr(router)).toBe('/admin/all?date=2026-09-22'))
  })

  it('день врача просит только его записи', async () => {
    await show({ doctor: 'd2' })
    expect(get).toHaveBeenCalledWith('/schedule/day?doctor=d2', expect.anything())
  })
})

/* ⭐ (06.10, Олег) Ручная запись — ОКНОМ «Programare nouă», а не формой внизу
   страницы. Открывает его `#addform` в адресе: туда ведёт кнопка шапки
   программы, и адрес — единственное состояние окна. */
describe('окно записи «Programare nouă»', () => {
  const openAdd = (date = '2026-09-23') => open(`/admin/all?date=${date}#addform`)
  const addForm = () => document.querySelector('dialog form.dp-addform') as HTMLFormElement | null
  const sel = (i: number) => addForm()?.querySelectorAll('select')[i] as HTMLSelectElement
  const addDate = () => (addForm()?.querySelector('input[type="date"]') as HTMLInputElement).value
  const field = (ph: string) => addForm()?.querySelector(`input[placeholder="${ph}"]`) as HTMLInputElement

  it('⛔ формы внизу страницы больше нет; без #addform нет и окна', async () => {
    await show()
    expect(document.querySelector('form.add')).toBeNull()
    expect(document.getElementById('addform')).toBeNull()
    expect(addForm()).toBeNull()
  })

  it('#addform открывает окно на дне экрана; «Închide» закрывает его и убирает якорь', async () => {
    get.mockImplementation(dayOfUrl)
    const { router } = await openAdd('2026-09-22')
    expect(addForm()).toBeTruthy()
    expect(addDate()).toBe('2026-09-22')
    fireEvent.click(document.querySelector('dialog .dlg-head button') as HTMLElement)
    /* окно ушло с экрана — значит, и роутер уже без якоря (не наоборот, см. `addr`) */
    await waitFor(() => expect(addForm()).toBeNull())
    expect(router.state.location.hash).toBe('')
    expect(addr(router)).toBe('/admin/all?date=2026-09-22')
  })

  /* ⭐ (07.10, решение Олега) Закрытие окна день НЕ перечитывает. Снятие
     якоря роутер по умолчанию считает перезагрузкой — в отличие от
     постановки, — и «Închide» слал второй GET: окно висело до ответа, а
     отказ этого GET менял весь день на плашку отказа. Свежесть дню дают
     переход по дате и ответ действия, а не закрытие окна. */
  it('«Închide» не перечитывает день: второго GET нет', async () => {
    const { router } = await openAdd()
    expect(get).toHaveBeenCalledTimes(1)
    fireEvent.click(document.querySelector('dialog .dlg-head button') as HTMLElement)
    await waitFor(() => expect(addForm()).toBeNull())
    expect(router.state.location.hash).toBe('')
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('после записи окно закрывается без второго GET, и на экране — день из ответа', async () => {
    /* Новая строка есть в ответе записи и нет в GET: перечитай экран день
       после закрытия — и она пропала бы вместе с подменой. */
    post.mockResolvedValue(ok({ ...MODEL, list: [...MODEL.list,
      { ...MODEL.list[0]!, id: 3, time: '09:30', name: 'Vasile Lupu', age: null }] }))
    await openAdd()
    fireEvent.change(field('Nume pacient'), { target: { value: 'Vasile Lupu' } })
    fireEvent.change(field('Telefon'), { target: { value: '069112233' } })
    fireEvent.submit(addForm() as HTMLFormElement)
    await waitFor(() => expect(addForm()).toBeNull())
    expect(document.querySelector('table.list')?.textContent).toContain('Vasile Lupu')
    expect(get).toHaveBeenCalledTimes(1)
  })

  /* ⛔ Правило — только про ЯКОРЬ. Тот же адрес без окна («Zi» на том же дне)
     и повтор после отказа перечитывают день, как и раньше: правило вида «тот
     же путь и query — не грузить» отняло бы у экрана обновление. */
  it('«Zi» на том же дне без окна перечитывает день', async () => {
    const { router } = await show({ date: '2026-09-23' })
    fireEvent.click(navLink(DAY))
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(router.state.navigation.state).toBe('idle'))
  })

  it('повтор после отказа перечитывает день и с окном в адресе', async () => {
    get.mockRejectedValueOnce(new ApiError({ kind: 'network', detail: 'x' }, 'x'))
    openScreen('/admin/all', '/admin/all?date=2026-09-23#addform',
      <DayScreen navigate={() => {}} />, loadDay)
    fireEvent.click(await screen.findByRole('button', { name: /Reîncearcă/ }))
    await waitFor(() => expect(addForm()).toBeTruthy())
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('врачи и часы — из формы сервера, а не из колонок канвы', async () => {
    await openAdd()
    expect(Array.from(sel(1).options).map((o) => o.value)).toEqual(['d2', 'd4'])
    expect(Array.from(sel(0).options).map((o) => o.value)).toEqual(['09:00', '09:30', '10:00'])
  })

  it('смена врача переписывает часы', async () => {
    await openAdd()
    fireEvent.change(sel(1), { target: { value: 'd4' } })
    expect(Array.from(sel(0).options).map((o) => o.value)).toEqual(['14:00', '14:30'])
  })

  it('галочка «fără telefon» гасит поле и снимает требование', async () => {
    await openAdd()
    expect(field('Telefon').required).toBe(true)
    fireEvent.click(addForm()?.querySelector('.nophone input') as HTMLElement)
    expect(field('Telefon').disabled).toBe(true)
    expect(field('Telefon').required).toBe(false)
  })

  it('отправка шлёт выбранное, показывает плашку сервера и закрывает окно', async () => {
    post.mockResolvedValue(ok(MODEL))
    const { router } = await openAdd()
    fireEvent.change(field('Nume pacient'), { target: { value: 'Vasile Lupu' } })
    fireEvent.change(field('Telefon'), { target: { value: '069112233' } })
    fireEvent.submit(addForm() as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments?date=2026-09-23', {
      date: '2026-09-23', time: '09:00', doctor: 'd2', service: 'consult',
      name: 'Vasile Lupu', phone: '069112233', nophone: false, birth: '',
    }))
    await waitFor(() => expect(document.querySelector('.toastbox')?.textContent)
      .toContain('Programare adăugată'))
    await waitFor(() => expect(router.state.location.hash).toBe(''))
  })

  /* ⛔ Окно закрывается ТОЛЬКО на удаче: закрыть форму, из которой ничего не
     записалось, значит потерять ввод и не сказать почему. */
  it('отказ: окно остаётся открытым с набранным', async () => {
    post.mockRejectedValue(new Error('interval ocupat'))
    const { router } = await openAdd()
    fireEvent.change(field('Nume pacient'), { target: { value: 'Vasile Lupu' } })
    fireEvent.change(field('Telefon'), { target: { value: '069112233' } })
    fireEvent.submit(addForm() as HTMLFormElement)
    await waitFor(() => expect(document.querySelector('.toastbox')).toBeTruthy())
    expect(router.state.location.hash).toBe('#addform')
    expect(field('Nume pacient').value).toBe('Vasile Lupu')
  })

  /* ⛔ Смена дня — это новая запись, как перезагрузка старой страницы (Олег
     24.09): переход по дню убирает якорь, и окно, открытое снова, засевает
     НОВЫЙ день, а недонабранное не переезжает. */
  it('смена дня закрывает окно; открытое снова — на новом дне и чистое', async () => {
    get.mockImplementation(dayOfUrl)
    const { router } = await openAdd('2026-09-22')
    fireEvent.change(field('Nume pacient'), { target: { value: 'Ion Popa' } })
    fireEvent.click(navLink(NEXT))
    await waitFor(() => expect(document.querySelector('.nav b')?.textContent).toBe('Zi 2026-09-23'))
    expect(addForm()).toBeNull()
    await act(async () => { await router.navigate('/admin/all?date=2026-09-23#addform') })
    await waitFor(() => expect(addForm()).toBeTruthy())
    expect(addDate()).toBe('2026-09-23')
    expect(field('Nume pacient').value).toBe('')
  })

  it('у выключенного врача окна нет вовсе, даже по #addform', async () => {
    get.mockResolvedValue(ok({ ...MODEL, form: null }))
    await open('/admin/doctor/d3#addform')
    expect(addForm()).toBeNull()
  })
})

describe('окно свободного часа', () => {
  /* Пустой час канвы — клик по самой ячейке, как на панели (знака «+» нет). */
  const openSlot = async () => {
    await show()
    fireEvent.click(cellOf('d3', 9))
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  it('открывается на своей ячейке: врач в заголовке, час ровный', async () => {
    await openSlot()
    expect(document.querySelector('.dlg-head span')?.textContent)
      .toBe('Dr. Activ Trei — 09:00')
    expect(document.querySelectorAll('.halfpick .hp')[0]?.className).toContain('on')
  })

  it('получас меняет ТОЛЬКО время записи', async () => {
    post.mockResolvedValue(ok(MODEL))
    await openSlot()
    fireEvent.click(document.querySelectorAll('.halfpick .hp')[1] as HTMLElement)
    expect(document.querySelector('.dlg-head span')?.textContent).toContain('09:30')
    fireEvent.change(document.querySelector('.dlg-form input[placeholder="Nume pacient"]') as HTMLElement,
      { target: { value: 'Ana' } })
    fireEvent.change(document.querySelector('.dlg-form input[placeholder="Telefon"]') as HTMLElement,
      { target: { value: '069111222' } })
    fireEvent.submit(document.querySelector('.dlg-form') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments',
      expect.objectContaining({ time: '09:30', doctor: 'd3' })))
  })

  it('вкладка заметки предлагает только концы ПОЗЖЕ начала и шлёт голый час', async () => {
    post.mockResolvedValue(ok(MODEL))
    await openSlot()
    fireEvent.click(document.querySelectorAll('.tabbtn')[1] as HTMLElement)
    const until = document.querySelector('.dlg-form select') as HTMLSelectElement
    expect(Array.from(until.options).map((o) => o.value)).toEqual(['10', '11', '12', '15'])
    fireEvent.change(document.querySelector('.dlg-form input') as HTMLElement,
      { target: { value: 'Ședință' } })
    fireEvent.change(until, { target: { value: '12' } })
    fireEvent.submit(document.querySelector('.dlg-form') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/notes', {
      date: '2026-09-23', time: '09:00', doctor: 'd3', text: 'Ședință', until: 12,
    }))
  })
})

describe('карточка визита', () => {
  const openCard = async (id: number) => {
    await show()
    fireEvent.click(blk(id))
    await waitFor(() => expect(document.querySelector('dialog')).toBeTruthy())
  }

  /* ⛔ Правится ПОЛНОЕ значение из `cards`, а не обрезок: на блоке канвы —
     только значок комментария (как у панели), в списке — обрезок сервера, и
     ни один из них не имеет права стать источником для диалога. */
  it('на блоке — значок комментария, а правится ПОЛНОЕ значение', async () => {
    await openCard(1)
    expect(blk(1).querySelector('b svg')).toBeTruthy()
    expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe(LONG)
  })

  it('кнопки исхода — те, что прислал сервер для этого состояния', async () => {
    await openCard(1)
    expect(Array.from(document.querySelectorAll('.dlg-status button'))
      .map((b) => b.textContent?.trim())).toEqual(['A venit', 'Finalizat'])
  })

  it('правая кнопка по записи на канве — меню с ТЕМИ ЖЕ исходами, «Finalizat» шлёт статус', async () => {
    post.mockResolvedValue(ok(MODEL))
    await show({ date: '2026-09-23' })
    fireEvent.contextMenu(blk(1), { clientX: 200, clientY: 200 })
    const menu = document.querySelector('.dp-cmenu') as HTMLElement
    expect(Array.from(menu.querySelectorAll('button')).map((b) => b.textContent?.trim()))
      .toEqual(['A venit', 'Finalizat'])
    expect(menu.querySelector('a')?.getAttribute('href')).toBe('/admin/patient/7')
    fireEvent.click(Array.from(menu.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Finalizat') as HTMLButtonElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/status?date=2026-09-23', { to: 'done' }))
    await waitFor(() => expect(document.querySelector('.dp-cmenu')).toBeNull())
  })

  it('возврат из меню спрашивает то же серверное подтверждение, что и диалог', async () => {
    post.mockResolvedValue(ok(MODEL))
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await show({ date: '2026-09-23' })
    fireEvent.contextMenu(blk(2), { clientX: 200, clientY: 200 })
    fireEvent.click(Array.from(document.querySelectorAll('.dp-cmenu button'))
      .find((b) => /Redeschide/.test(b.textContent ?? '')) as HTMLButtonElement)
    expect(ask).toHaveBeenCalledWith('Redeschideți programarea (înapoi la «confirmată»)?')
    expect(post).not.toHaveBeenCalled()
  })

  it('возврат закрытой записи спрашивает подтверждение', async () => {
    post.mockResolvedValue(ok(MODEL))
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await openCard(2)
    fireEvent.submit(document.querySelector('.dlg-status form') as HTMLFormElement)
    expect(ask).toHaveBeenCalledWith('Redeschideți programarea (înapoi la «confirmată»)?')
    expect(post).not.toHaveBeenCalled()
  })

  it('дневник визита: слово зависит от того, заполнен ли он', async () => {
    await openCard(1)
    expect(document.querySelectorAll('.dp-card-link')[1]?.textContent)
      .toContain('Completează')
    cleanup()
    await openCard(2)
    expect(document.querySelectorAll('.dp-card-link')[1]?.textContent).toContain('Vezi')
  })

  it('комментарий уходит на сервер вместе с id записи', async () => {
    post.mockResolvedValue(ok(MODEL))
    await openCard(1)
    fireEvent.change(document.querySelector('textarea') as HTMLElement,
      { target: { value: 'Nou' } })
    fireEvent.submit(document.querySelector('.dp-card-cmt') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/comment', { comment: 'Nou' }))
  })
})

/* Перенос — по канве, как у панели: мишень — КОЛОНКА, ячейка под курсором
   ищется по координате среди `.gcell[data-h]` (ряды по 40 px со сотого:
   9:00 — 100–140, 10:00 — 140–180, 12:00 у Doi закрыт). */
describe('перетаскивание', () => {
  const dragTo = (dk: string, y: number, id = 1) => {
    fireEvent.dragStart(blk(id))
    dropAt(colOf(dk), 'dragover', y)
    dropAt(colOf(dk), 'drop', y)
  }

  it('закрытый визит не тащится вовсе', async () => {
    await show()
    expect(blk(2).getAttribute('draggable')).toBeNull()
  })

  it('бросок в верх ячейки даёт ровный час, в низ — половину', async () => {
    await show()
    dragTo('d2', 150)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelectorAll('.mv-rows b')[2]?.textContent)
      .toBe('Dr. Activ Doi · 10:00')
    fireEvent.click(document.querySelector('.mv-no') as HTMLElement)

    dragTo('d2', 170)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelectorAll('.mv-rows b')[2]?.textContent)
      .toBe('Dr. Activ Doi · 10:30')
  })

  it('диалог говорит, КОГО и ОТКУДА двигают — и к какому врачу', async () => {
    await show()
    dragTo('d3', 110)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    const b = document.querySelectorAll('.mv-rows b')
    expect([b[0]?.textContent, b[1]?.textContent, b[2]?.textContent])
      .toEqual(['Ion Popa', 'Dr. Activ Doi · 09:00', 'Dr. Activ Trei · 09:00'])
  })

  it('БРОСОК НА СВОЁ ЖЕ МЕСТО диалога не открывает и запроса не шлёт', async () => {
    await show()
    dragTo('d2', 110)
    expect(document.querySelector('.mv-rows')).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })

  it('закрытый час не принимает бросок', async () => {
    await show()
    dragTo('d2', 230)
    expect(document.querySelector('.mv-rows')).toBeNull()
  })

  /* ⚠️ На 10:00, а не на 10:30: в 11:00 у Doi заметка стойки, и 10:30–11:30
     с ней пересекается — подтверждение там честно заперто (см. ниже). */
  it('подтверждение шлёт час, врача и дату экрана', async () => {
    post.mockResolvedValue(ok(MODEL))
    await show()
    dragTo('d2', 150)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    fireEvent.click(document.querySelectorAll('.mv-act button')[1] as HTMLElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments/1/move',
      { date: '2026-09-23', time: '10:00', doctor: 'd2' }))
  })

  it('заметка стойки занимает свой час: перенос на 10:30 предупреждает и заперт', async () => {
    await show()
    dragTo('d2', 170)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelector('.banner.err')?.textContent)
      .toContain('Medicul are deja o programare la 11:00.')
    expect((document.querySelectorAll('.mv-act button')[1] as HTMLButtonElement).disabled)
      .toBe(true)
  })

  it('занятый интервал предупреждает и не даёт подтвердить — по блокам КАНВЫ', async () => {
    const [doi, trei] = CANVAS.columns
    get.mockResolvedValue(ok({
      ...MODEL,
      canvas: { ...CANVAS, columns: [
        { ...doi!, blocks: [...doi!.blocks,
          block(5, '10:00', 'Ocupa Ora', { min: 600, top: 1 })] },
        trei!,
      ] },
    }))
    await show()
    dragTo('d2', 150)
    await waitFor(() => expect(document.querySelector('.mv-rows')).toBeTruthy())
    expect(document.querySelector('.banner.err')?.textContent)
      .toContain('Medicul are deja o programare la 10:00.')
    expect((document.querySelectorAll('.mv-act button')[1] as HTMLButtonElement).disabled)
      .toBe(true)
  })
})

describe('список дня', () => {
  const list = () => Array.from(document.querySelectorAll('table.list tr')).slice(1)
  const cells = (i: number) =>
    Array.from(list()[i]?.querySelectorAll('td') ?? []).map((c) => c.textContent?.trim())

  it('строки — все записи дня, включая заметку, в порядке сервера', async () => {
    await show()
    expect(list()).toHaveLength(3)
    expect(list().map((r) => r.className)).toEqual(['confirmed', 'noshow', 'confirmed'])
    expect(cells(0)?.slice(0, 4)).toEqual(['1', '09:00', 'Ion Popa (41 ani)', '069000000'])
  })

  it('комментарий строки — обрезанный сервером, а правится полный в карточке', async () => {
    await show()
    expect(document.querySelector('table.list .dp-cmt')?.textContent)
      .toContain(LONG.slice(0, 80))
    fireEvent.click(document.querySelector('table.list .plink') as HTMLElement)
    await waitFor(() => expect(document.querySelector('dialog textarea')).toBeTruthy())
    expect((document.querySelector('dialog textarea') as HTMLTextAreaElement).value).toBe(LONG)
  })

  it('плашка статуса — по ВИДУ с учётом звонка, кнопки — по коду (03.10)', async () => {
    /* «confirmată» даёт звонок из «De confirmat»: код записи остаётся
       `confirmed` (по нему кнопки исхода), а вид и слово — `called`. */
    get.mockResolvedValue(ok({ ...MODEL, list: MODEL.list.map((r) => (r.id === 1
      ? { ...r, status_view: 'called', status_label: 'confirmată' } : r)) }))
    await show()
    const pill = list()[0]?.querySelector('.stat')
    expect(pill?.className).toBe('stat s-called')
    expect(pill?.textContent).toBe('confirmată')
    expect(list()[0]?.className).toBe('confirmed')
  })

  it('источник и метки — словами сервера', async () => {
    await show()
    expect(cells(1)?.[6]).toBe('bot')
    expect(cells(2)?.[6]).toBe('notiță')
    expect(list()[1]?.querySelector('.rem-mark')).toBeTruthy()
    expect(list()[1]?.querySelector('.rec-mark')).toBeTruthy()
    expect(list()[0]?.querySelector('.rem-mark')).toBeNull()
  })

  it('у ЗАМЕТКИ своя кнопка, и по имени её не открыть', async () => {
    await show()
    expect(Array.from(list()[2]?.querySelectorAll('button') ?? [])
      .map((b) => b.textContent?.trim())).toEqual(['Șterge'])
    expect(list()[2]?.querySelector('.plink')).toBeNull()
  })

  it('кнопка строки шлёт статус этой записи', async () => {
    post.mockResolvedValue(ok(MODEL))
    await show()
    fireEvent.submit(list()[0]?.querySelector('form.act') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/status', { to: 'waiting' }))
  })

  /* ⭐ (06.10, Олег) Пять цветных кнопок в строке перекрикивали список: у
     визита — ОДНА, следующий шаг (первое действие матрицы сервера), остальное
     — в «⋯», то же меню, что по правой кнопке. */
  it('у визита — следующий шаг и «⋯»; «⋯» открывает меню с ТЕМИ ЖЕ исходами и фишей', async () => {
    post.mockResolvedValue(ok(MODEL))
    await show()
    expect(Array.from(list()[0]?.querySelectorAll('form.act button') ?? [])
      .map((b) => b.textContent?.trim())).toEqual(['A venit'])
    fireEvent.click(list()[0]?.querySelector('.dp-more') as HTMLElement)
    const menu = document.querySelector('.dp-cmenu') as HTMLElement
    expect(Array.from(menu.querySelectorAll('button')).map((b) => b.textContent?.trim()))
      .toEqual(['A venit', 'Finalizat'])
    expect(menu.querySelector('a')?.getAttribute('href')).toBe('/admin/patient/7')
    fireEvent.click(Array.from(menu.querySelectorAll('button'))
      .find((b) => b.textContent?.trim() === 'Finalizat') as HTMLButtonElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/status', { to: 'done' }))
  })

  it('у заметки «⋯» нет — её единственная кнопка и так на месте', async () => {
    await show()
    expect(list()[2]?.querySelector('.dp-more')).toBeNull()
  })

  /* ⭐ «Sursă» — только у клиники с ботом: без него там везде «manual». */
  it('без бота колонки «Sursă» нет — ни в шапке, ни в строках', async () => {
    get.mockResolvedValue(ok({ ...MODEL, source_col: false }))
    await show()
    const head = Array.from(document.querySelectorAll('table.list th')).map((th) => th.textContent)
    expect(head).not.toContain('Sursă')
    expect(head).toHaveLength(8)
    expect(cells(0)).toHaveLength(8)
    expect(cells(2)?.join('|')).not.toContain('notiță')
  })

  it('возврат неявки спрашивает подтверждение записи, а не заметки', async () => {
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await show()
    fireEvent.submit(list()[1]?.querySelector('form.act') as HTMLFormElement)
    expect(ask).toHaveBeenCalledWith('Redeschideți programarea (înapoi la «confirmată»)?')
    expect(post).not.toHaveBeenCalled()
  })

  it('фильтр плитки: спрашивается у сервера и называет себя', async () => {
    get.mockResolvedValue(ok({
      ...MODEL, list: [MODEL.list[1]!],
      filter: { key: 'noshow', label: 'neprezentări', count: 1 },
    }))
    await show({ f: 'noshow' })
    expect(get).toHaveBeenCalledWith('/schedule/day?f=noshow', expect.anything())
    expect(document.querySelector('.banner.ok')?.textContent)
      .toContain('neprezentări')
    expect(list()).toHaveLength(1)
    // отфильтрованный список стоит НАД сеткой — как на старой странице
    expect(document.querySelectorAll('h2')[0]?.textContent).toContain('neprezentări')
    const all = Array.from(document.querySelectorAll('table'))
    expect(all[0]?.className).toBe('list')
  })

  it('«arată tot» снимает отбор и перезапрашивает день', async () => {
    get.mockResolvedValue(ok({
      ...MODEL, list: [MODEL.list[1]!],
      filter: { key: 'noshow', label: 'neprezentări', count: 1 },
    }))
    const { router } = await show({ f: 'noshow' })
    get.mockResolvedValue(ok(MODEL))
    fireEvent.click(document.querySelector('.banner.ok a') as HTMLElement)
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      '/schedule/day?date=2026-09-23', expect.anything()))
    await waitFor(() => expect(addr(router)).toBe('/admin/all?date=2026-09-23'))
  })

  it('Excel — ссылка этого дня, и только у общего журнала', async () => {
    await show()
    expect(document.querySelector('a[href*="export.xlsx"]')?.getAttribute('href'))
      .toBe('/admin/export.xlsx?from=2026-09-23&to=2026-09-23')
    cleanup()
    await show({ doctor: 'd2' })
    expect(document.querySelector('a[href*="export.xlsx"]')).toBeNull()
  })
})

/* B2.3: день, отбор и врач живут в АДРЕСЕ, и владеет им роутер. Экран не
   держит своей копии ни одного из них, поэтому F5 на любом адресе, который он
   записал, открывает тот же день с тем же отбором. */
describe('адрес дня', () => {
  const FILTERED = ok({
    ...MODEL, list: [MODEL.list[0]!],
    filter: { key: 'noshow', label: 'neprezentări', count: 1 },
  })
  const nav = (i: number) => fireEvent.click(navLink(i))

  /* ⭐ Шапка как у панели дня и у старой страницы (06.10). React-экран
     показывал голую ISO-дату и «‹ zi / zi ›», а листать неделями было нечем —
     при переезде потерялось то, что у старой шапки было. */
  it('шапка: подпись дня — с сервера, соседние дни — числом, «« »» — на неделю', async () => {
    await show({ date: '2026-09-23' })
    expect(document.querySelector('.nav b')?.textContent).toBe('Mi 23.09.2026')
    const hrefs = [WK_PREV, PREV, AZI, NEXT, WK_NEXT].map((i) => navLink(i).getAttribute('href'))
    expect(hrefs).toEqual(['/admin/all?date=2026-09-16', '/admin/all?date=2026-09-22', '/admin/all',
      '/admin/all?date=2026-09-24', '/admin/all?date=2026-09-30'])
    expect([navLink(PREV).textContent?.trim(), navLink(NEXT).textContent?.trim()]).toEqual(['22.09', '24.09'])
    expect([navLink(WK_PREV).title, navLink(WK_NEXT).title]).toEqual(['-7 zile', '+7 zile'])
  })

  /* ⭐ (06.10, Олег) Неделя — вкладка этого же раздела, рядом с днём. */
  it('«Zi / Săptămâna»: день выделен, неделя — этого же дня', async () => {
    await show({ date: '2026-09-23' })
    expect(navLink(DAY).textContent).toBe('Zi')
    expect(navLink(DAY).className).toBe('primary')
    expect(navLink(WEEK).textContent).toBe('Săptămâna')
    expect(navLink(WEEK).getAttribute('href')).toBe('/admin/week?date=2026-09-23')
  })

  it('«» » у дня врача: неделя вперёд, врач в пути и отбор остаются; F5 — тот же запрос', async () => {
    get.mockResolvedValue(FILTERED)
    const { router } = await show({ doctor: 'd2', date: '2026-09-23', f: 'noshow' })
    nav(WK_NEXT)
    await waitFor(() => expect(addr(router)).toBe('/admin/doctor/d2?date=2026-09-30&f=noshow'))
    expect(get.mock.lastCall?.[0]).toBe('/schedule/day?date=2026-09-30&doctor=d2&f=noshow')
    await reloadParity(router)
  })

  it('⛔ «Varianta clasică» в шапке нет (Олег 06.10: «это не нужно»)', async () => {
    await show()
    expect(document.querySelector('.nav a[href*="ui=legacy"]')).toBeNull()
    expect(document.querySelector('.nav')?.textContent).not.toContain('clasic')
  })

  it('открытие по адресу: день и отбор загрузчик берёт из адреса', async () => {
    await open('/admin/all?date=2026-09-20&f=noshow')
    expect(get).toHaveBeenCalledWith('/schedule/day?date=2026-09-20&f=noshow', expect.anything())
  })

  /* ⛔ Ссылка «+» старой страницы ведёт на /admin/all?doctor=…&time_pre=… —
     это предвыбор её формы. У `/api/schedule/day` `doctor` значит «день
     одного врача»: переслать query как есть — и откроется чужая сетка. */
  it('предвыбор старой формы не делает общий журнал днём врача', async () => {
    await open('/admin/all?date=2026-09-23&doctor=d2&time_pre=10:00&msg=ok_add')
    expect(get).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledWith('/schedule/day?date=2026-09-23', expect.anything())
  })

  it('день назад: адрес — день и отбор, без хвоста; F5 — тот же запрос', async () => {
    get.mockResolvedValue(FILTERED)
    const { router } = await open('/admin/all?date=2026-09-23&f=noshow&msg=ok_add')
    nav(PREV)
    await waitFor(() => expect(addr(router)).toBe('/admin/all?date=2026-09-22&f=noshow'))
    expect(get.mock.lastCall?.[0]).toBe('/schedule/day?date=2026-09-22&f=noshow')
    await reloadParity(router)
  })

  it('день вперёд у дня врача: врач остаётся в пути; F5 — тот же запрос', async () => {
    const { router } = await show({ doctor: 'd2', date: '2026-09-23' })
    nav(NEXT)
    await waitFor(() => expect(addr(router)).toBe('/admin/doctor/d2?date=2026-09-24'))
    expect(get.mock.lastCall?.[0]).toBe('/schedule/day?date=2026-09-24&doctor=d2')
    await reloadParity(router)
  })

  it('«Azi»: адрес без даты, отбор остаётся; F5 — тот же запрос', async () => {
    get.mockResolvedValue(FILTERED)
    const { router } = await show({ date: '2026-09-20', f: 'noshow' })
    nav(AZI)
    await waitFor(() => expect(addr(router)).toBe('/admin/all?f=noshow'))
    expect(get.mock.lastCall?.[0]).toBe('/schedule/day?f=noshow')
    await reloadParity(router)
  })

  it('«arată tot»: F5 — тот же запрос', async () => {
    get.mockResolvedValue(FILTERED)
    const { router } = await show({ date: '2026-09-23', f: 'noshow' })
    get.mockResolvedValue(ok(MODEL))
    fireEvent.click(document.querySelector('.banner.ok a') as HTMLElement)
    await waitFor(() => expect(addr(router)).toBe('/admin/all?date=2026-09-23'))
    await reloadParity(router)
  })

  /* Отбор — эхо сервера: чужой ключ он не признаёт (`filter: null`), и дальше
     — ни в адрес, ни в действия — такой ключ не уходит. */
  it('чужой отбор из адреса не переезжает ни в адрес, ни в действие', async () => {
    post.mockResolvedValue(ok(MODEL))
    const { router } = await open('/admin/all?date=2026-09-23&f=bogus')
    fireEvent.submit(document.querySelector('table.list form.act') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/status?date=2026-09-23', { to: 'waiting' }))
    nav(PREV)
    await waitFor(() => expect(addr(router)).toBe('/admin/all?date=2026-09-22'))
  })

  it('признанный отбор уходит в действие', async () => {
    get.mockResolvedValue(FILTERED)
    post.mockResolvedValue(FILTERED)
    await show({ f: 'noshow' })
    fireEvent.submit(document.querySelector('table.list form.act') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/status?f=noshow', { to: 'waiting' }))
  })

  /* ⛔ Своя копия даты, засеянная первой загрузкой, слала бы действие в день,
     которого на экране давно нет. */
  it('после перехода действие шлёт день АДРЕСА', async () => {
    get.mockImplementation(dayOfUrl)
    post.mockResolvedValue(ok(MODEL))
    const { router } = await show({ date: '2026-09-23' })
    nav(PREV)
    /* ⚠️ Ждать новый день на ЭКРАНЕ, а не в роутере (см. `addr`): форма
       прежней отрисовки несёт прежний день, и действие ушло бы в 23-е. */
    await waitFor(() => expect(document.querySelector('.nav b')?.textContent).toBe('Zi 2026-09-22'))
    expect(addr(router)).toBe('/admin/all?date=2026-09-22')
    fireEvent.submit(document.querySelector('table.list form.act') as HTMLFormElement)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/schedule/appointments/1/status?date=2026-09-22', { to: 'waiting' }))
  })

  it('пока новый день грузится, на экране прежний, а не загрузка', async () => {
    const { router } = await show({ date: '2026-09-23' })
    get.mockReturnValueOnce(new Promise(() => {}))
    nav(NEXT)
    await waitFor(() => expect(router.state.navigation.state).toBe('loading'))
    expect(document.querySelector('[aria-busy="true"]')).toBeNull()
    expect(canvasShown()).toBe(true)
    expect(document.querySelector('.nav b')?.textContent).toBe('Mi 23.09.2026')
  })
})
