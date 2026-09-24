import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screenRoute } from '../../hooks/useRouteLoad'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import { loadPerio, PerioScreen } from './PerioScreen'
import { hasData, roundLikeServer, rowOf, summarize, type PerioEdit, type PerioModel, type PerioSave } from './perio'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

const LIMITS = { mm_max: 15, mob_max: 3, furc_max: 3, deep: 4, severe: 6 }

const teeth: PerioModel['teeth'] = {}
for (const n of [...UPPER, ...LOWER]) {
  teeth[String(n)] = {
    state: 'ok', absent: false, title: `${n} · Sănătos`,
    svg: { frontal: `<svg class='tooth-svg' aria-label='${n}'></svg>`, occlusal: '<svg></svg>' },
  }
}
teeth['26'] = { ...teeth['26'], state: 'lipsa', absent: true, title: '26 · Lipsă' } as PerioModel['teeth'][string]

const MODEL: PerioModel = {
  patient: { id: 5, name: 'Perio Pin' },
  rev: 'a1b2c3d4e5f6',
  exams: [
    { id: 9, at: '18.09.2026', doctor: 'Dr. Activ Doi', note: 'reevaluare', teeth: 2 },
    { id: 4, at: '01.03.2026', doctor: '', note: '', teeth: 5 },
  ],
  exam: { id: 9, at: '18.09.2026', doctor: 'Dr. Activ Doi', note: 'reevaluare', teeth: 2 },
  rows: {
    '16': { tooth: 16, pd: [3, 2, 3, 4, 2, 5], rec: [1, 0, 0, 0, 0, 2], bop: '010010', mob: 1, furc: 2, cal: [4, 2, 3, 4, 2, 7] },
    '46': { tooth: 46, pd: [2, 2, 2, 2, 2, 2], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [2, 2, 2, 2, 2, 2] },
  },
  teeth,
  arches: { upper: UPPER, lower: LOWER },
  sites: [
    { key: 'MV', label: 'mezio-vestibular' }, { key: 'V', label: 'vestibular' },
    { key: 'DV', label: 'disto-vestibular' }, { key: 'ML', label: 'mezio-lingual' },
    { key: 'L', label: 'lingual / palatinal' }, { key: 'DL', label: 'disto-lingual' },
  ],
  summary: { teeth: 2, sites: 12, bop: 17, pd_mean: 2.6, cal_mean: 2.8, deep: 2, severe: 0, mob: [[16, 1]], furc: [[16, 2]] },
  limits: LIMITS,
  grades: { mob: { '1': 'gr. I', '2': 'gr. II', '3': 'gr. III' }, furc: { '1': 'gr. I', '2': 'gr. II', '3': 'gr. III' } },
  doctors: ['Dr. Activ Doi', 'Dr. Activ Trei'],
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const col = (n: number) => document.querySelector(`.ptooth[data-tooth="${n}"]`) as HTMLElement
const cell = (n: number, kind: 'pd' | 'rec', i: number) =>
  col(n).querySelector(`input[data-k="${kind}"][data-i="${i}"]`) as HTMLInputElement
const dot = (n: number, i: number) =>
  col(n).querySelectorAll('.pdot')[i] as HTMLButtonElement
const sums = () => Array.from(document.querySelectorAll('.psum-i b')).map((b) => b.textContent)
const unsaved = () => screen.queryByText('Nesalvat')

beforeEach(() => {
  get.mockResolvedValue(ok(MODEL))
})

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
})

const PATH = '/admin/patient/:pid/parodontograma'
const SHEET = '/admin/patient/5/parodontograma'

/** Лист тем же маршрутом, что в App.tsx: данные приносит загрузчик роутера. */
const open = (url = SHEET) => openScreen(PATH, url, <PerioScreen pid={5} navigate={() => {}} />, loadPerio)

const show = async (url = SHEET) => {
  const r = open(url)
  await waitFor(() => expect(col(16)).toBeTruthy())
  return r
}

/** Адрес, которым владеет роутер: его и увидит F5. */
const at = (router: ReturnType<typeof open>['router']) =>
  router.state.location.pathname + router.state.location.search

/** Последний адрес, по которому экран спросил движок. */
const lastGet = () => (get.mock.calls[get.mock.calls.length - 1] as [string, unknown] | undefined)?.[0]

/** Отложенный ответ: позволяет печатать, пока запрос «в пути». */
const deferred = <T,>() => {
  let go: (v: T) => void = () => {}
  const promise = new Promise<T>((resolve) => { go = resolve })
  return { promise, go }
}

describe('лист пародонтограммы', () => {
  it('рисует обе дуги, шесть точек на зуб и измерения выбранного осмотра', async () => {
    await show()
    expect(document.querySelectorAll('.ptooth')).toHaveLength(32)
    expect(Array.from(col(16).querySelectorAll('input[data-k]')).map(
      (x) => `${(x as HTMLInputElement).dataset.k}${(x as HTMLInputElement).dataset.i}`))
      .toEqual(['pd0', 'pd1', 'pd2', 'rec0', 'rec1', 'rec2', 'rec3', 'rec4', 'rec5', 'pd3', 'pd4', 'pd5'])
    expect(cell(16, 'pd', 0).value).toBe('3')
    expect(cell(16, 'rec', 5).value).toBe('2')
    // ноль — пустое поле: в базе это «не измеряли», а нолик читался бы измерением
    expect(cell(16, 'rec', 1).value).toBe('')
    expect(cell(11, 'pd', 0).value).toBe('')
  })

  it('точка кровоточивости только у глубины, и их ровно шесть', async () => {
    await show()
    expect(col(16).querySelectorAll('.pdot')).toHaveLength(6)
    expect(col(16).querySelectorAll('.pdot.on')).toHaveLength(2)
    expect(col(16).querySelectorAll('.prow.rec .pdot')).toHaveLength(0)
  })

  it('карман от порога сервера помечен, мельче — нет', async () => {
    await show()
    expect(cell(16, 'pd', 3).closest('.pcell')?.className).toContain('deep')
    expect(cell(16, 'pd', 1).closest('.pcell')?.className).not.toContain('deep')
  })

  it('отсутствующий зуб приглушён, но ввод не запрещён', async () => {
    await show()
    expect(col(26).className).toContain('absent')
    expect(cell(26, 'pd', 0).disabled).toBe(false)
    expect(col(16).className).not.toContain('absent')
  })

  it('рисунок зуба под колонкой — тот же, что даёт сервер', async () => {
    await show()
    expect(col(16).querySelector('.ptpic svg')?.getAttribute('aria-label')).toBe('16')
    expect(document.querySelectorAll('.ptpic svg')).toHaveLength(32)
  })
})

describe('диктовка', () => {
  it('цифра уходит к следующей точке, а единица ждёт вторую', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '3' } })
    expect(document.activeElement).toBe(cell(11, 'pd', 1))
    fireEvent.change(cell(11, 'pd', 1), { target: { value: '1' } })
    expect(document.activeElement).toBe(cell(11, 'pd', 1))   // 1 может стать 12
    fireEvent.change(cell(11, 'pd', 1), { target: { value: '12' } })
    expect(document.activeElement).toBe(cell(11, 'pd', 2))
  })

  it('порядок перехода — порядок листа, и он же порядок диктовки вслух', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 5), { target: { value: '3' } })
    expect(document.activeElement).toBe(cell(21, 'pd', 0))
  })

  it('глубже потолка не принимается: остаётся первая цифра', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '19' } })
    expect(cell(11, 'pd', 0).value).toBe('1')
  })

  it('нецифры отбрасываются', async () => {
    await show()
    fireEvent.change(cell(11, 'rec', 1), { target: { value: 'a' } })
    expect(cell(11, 'rec', 1).value).toBe('')
  })

  it('клавиша b ставит кровоточивость с того же места, у рецессии — молчит', async () => {
    await show()
    expect(dot(16, 0).className).not.toContain('on')
    fireEvent.keyDown(cell(16, 'pd', 0), { key: 'b' })
    expect(dot(16, 0).className).toContain('on')
    fireEvent.keyDown(cell(16, 'pd', 0), { key: 'b' })
    expect(dot(16, 0).className).not.toContain('on')
    fireEvent.keyDown(cell(16, 'rec', 0), { key: 'b' })
    expect(col(16).querySelectorAll('.pdot.on')).toHaveLength(2)
  })

  it('Enter ведёт к следующей точке и осмотр не записывает', async () => {
    await show()
    fireEvent.keyDown(cell(16, 'pd', 0), { key: 'Enter' })
    expect(document.activeElement).toBe(cell(16, 'pd', 1))  // Enter — следующая точка
    expect(post).not.toHaveBeenCalled()
  })

  it('клик по рисунку зуба ведёт фокус в его колонку', async () => {
    await show()
    fireEvent.click(col(21).querySelector('.ptpic .tooth-btn') as HTMLElement)
    expect(document.activeElement).toBe(cell(21, 'pd', 0))
  })
})

describe('черновик и запись', () => {
  it('итог пересчитывается сразу, до записи, и тем же счётом, что у сервера', async () => {
    await show()
    expect(sums()).toEqual(['17%', '2.6 mm', '2', '2', '2.8 mm'])
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '6' } })
    // 13 точек, из них кровоточат 2; глубоких 3, тяжёлых 1
    expect(sums()).toEqual(['15%', '2.8 mm', '3', '3', '3.1 mm'])
    expect(unsaved()).toBeTruthy()
  })

  it('«Renunță» возвращает измерения осмотра', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Renunță' }))
    expect(cell(11, 'pd', 0).value).toBe('')
    expect(unsaved()).toBeNull()
    expect(sums()).toEqual(['17%', '2.6 mm', '2', '2', '2.8 mm'])
  })

  it('записываются ТРОНУТЫЕ зубы, они же названы в covers — нетронутых запись не касается', async () => {
    await show()
    post.mockResolvedValue(ok(MODEL, 'ok_perio', 'Parodontograma a fost salvată'))
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const [path, body] = post.mock.calls[0] as [string, PerioSave]
    expect(path).toBe('/patients/5/perio/9')
    expect(Object.keys(body.teeth)).toEqual(['11'])
    expect(body.teeth['11']?.pd).toEqual([5, 0, 0, 0, 0, 0])
    expect(body.covers).toEqual([11])
    expect(body.rev).toBe(MODEL.rev)
    // ⚠️ Подпись и заметку не трогали — их в записи нет ВОВСЕ: «поля нет»
    // значит «не сообщали», иначе стала́я вкладка стёрла бы чужую подпись
    expect('doctor' in body).toBe(false)
    expect('note' in body).toBe(false)
    expect(screen.getByText('Parodontograma a fost salvată')).toBeTruthy()
  })

  it('зуб, у которого убрали измерения, назван в covers — иначе стирать нечем', async () => {
    await show()
    post.mockResolvedValue(ok(MODEL, 'ok_perio', ''))
    for (let i = 0; i < 6; i += 1) fireEvent.change(cell(46, 'pd', i), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const [, body] = post.mock.calls[0] as [string, PerioSave]
    expect(body.covers).toEqual([46])
    expect(Object.keys(body.teeth)).toEqual([])
  })

  it('зуб второго рабочего места приезжает с ответом и не стирается следующей записью', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    // Сервер ответил картой, в которой ЕСТЬ зуб 21: его измерили на соседнем
    // месте, пока лист был открыт. Наш черновик о нём не знает.
    const merged: PerioModel = {
      ...MODEL,
      rev: 'ffffffffffff',
      rows: {
        ...MODEL.rows,
        '11': { tooth: 11, pd: [5, 0, 0, 0, 0, 0], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [5, 0, 0, 0, 0, 0] },
        '21': { tooth: 21, pd: [4, 4, 4, 4, 4, 4], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [4, 4, 4, 4, 4, 4] },
      },
    }
    post.mockResolvedValue(ok(merged, 'ok_perio_merged', 'Parodontograma a fost salvată. Atenție'))
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(unsaved()).toBeNull())
    expect(cell(21, 'pd', 0).value).toBe('4')
    // ⛔ И следующая запись НЕ называет чужой зуб тронутым: иначе он был бы
    // стёрт — ровно так терялась работа соседнего места до 18.09
    post.mockClear()
    post.mockResolvedValue(ok(merged, 'ok_perio', ''))
    fireEvent.change(cell(11, 'pd', 1), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const [, body] = post.mock.calls[0] as [string, PerioSave]
    expect(body.covers).toEqual([11])
  })

  it('удачная запись снимает черновик сама — свежий осмотр приехал с сервера', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    const saved: PerioModel = {
      ...MODEL,
      rows: { ...MODEL.rows, '11': { tooth: 11, pd: [5, 0, 0, 0, 0, 0], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [5, 0, 0, 0, 0, 0] } },
    }
    post.mockResolvedValue(ok(saved, 'ok_perio', 'Parodontograma a fost salvată'))
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(unsaved()).toBeNull())
    expect(cell(11, 'pd', 0).value).toBe('5')
  })

  it('отказ сервера ввод не трогает', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    post.mockRejectedValue(new Error('offline'))
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(unsaved()).toBeTruthy())
    expect(cell(11, 'pd', 0).value).toBe('5')
  })

  it('подвижность и фуркация — у зуба целиком, словами сервера', async () => {
    await show()
    const sel = col(16).querySelector('select[data-k="mob"]') as HTMLSelectElement
    expect(sel.value).toBe('1')
    expect(Array.from(sel.options).map((o) => o.text)).toEqual(['—', 'gr. I', 'gr. II', 'gr. III'])
    fireEvent.change(sel, { target: { value: '3' } })
    expect(unsaved()).toBeTruthy()
  })
})

describe('осмотры', () => {
  it('список осмотров с датой и счётом, выбранный — текущий', async () => {
    await show()
    const sel = document.querySelector('.pexam') as HTMLSelectElement
    expect(Array.from(sel.options).map((o) => o.text)).toEqual(['18.09.2026 · 2 dinți', '01.03.2026 · 5 dinți'])
    expect(sel.value).toBe('9')
  })

  it('выбор прошлого осмотра перечитывает лист по его id', async () => {
    const { router } = await show()
    fireEvent.change(document.querySelector('.pexam') as HTMLSelectElement, { target: { value: '4' } })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/patients/5/perio?exam=4', expect.anything()))
    // ⭐ Адрес ведёт РОУТЕР: это его адрес, а не только строка в истории браузера
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=4'))
    expect(router.state.historyAction).toBe('REPLACE')   // смена осмотра не копит «Назад»
  })

  it('черновик привязан к своему осмотру и переживает переключение', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '7' } })
    const other: PerioModel = { ...MODEL, exam: MODEL.exams[1] ?? null, rows: {} }
    get.mockResolvedValue(ok(other))
    fireEvent.change(document.querySelector('.pexam') as HTMLSelectElement, { target: { value: '4' } })
    await waitFor(() => expect((document.querySelector('.pexam') as HTMLSelectElement | null)?.value).toBe('4'))
    expect(unsaved()).toBeNull()
    expect(cell(11, 'pd', 0).value).toBe('')     // у прошлого осмотра своих измерений нет
    get.mockResolvedValue(ok(MODEL))
    fireEvent.change(document.querySelector('.pexam') as HTMLSelectElement, { target: { value: '9' } })
    await waitFor(() => expect(cell(11, 'pd', 0).value).toBe('7'))
    expect(unsaved()).toBeTruthy()
  })

  it('пациент без осмотров: экран начала, а не пустая карта', async () => {
    get.mockResolvedValue(ok({ ...MODEL, exams: [], exam: null, rows: {} }))
    open()
    await waitFor(() => expect(screen.getByRole('button', { name: /Începe primul examen/ })).toBeTruthy())
    expect(document.querySelector('.ptooth')).toBeNull()
    expect(document.querySelector('.pexam')).toBeNull()
  })

  it('пустой осмотр можно снять, осмотр с измерениями — нет', async () => {
    get.mockResolvedValue(ok({ ...MODEL, exam: { ...MODEL.exam!, teeth: 0 }, rows: {} }))
    await show()
    expect(screen.getByRole('button', { name: 'Șterge examenul gol' })).toBeTruthy()
    get.mockResolvedValue(ok(MODEL))
    cleanup()
    await show()
    expect(screen.queryByRole('button', { name: 'Șterge examenul gol' })).toBeNull()
  })

  it('печать берёт ВЫБРАННЫЙ осмотр', async () => {
    await show()
    expect(screen.getByRole('link', { name: /Printează/ }).getAttribute('href'))
      .toBe('/admin/patient/5/parodontograma/print?exam=9')
  })
})

describe('счёт предпросмотра', () => {
  const rows = (): PerioEdit[] => [rowOf(MODEL, 16), rowOf(MODEL, 46)]

  it('повторяет числа сервера на тех же данных', () => {
    const s = summarize(rows(), LIMITS)
    expect({ ...s, mob: s.mob, furc: s.furc }).toEqual(MODEL.summary)
  })

  it('знаменатель — измеренные точки, а не все 192', () => {
    const one: PerioEdit = { tooth: 11, pd: [4, 0, 0, 0, 0, 0], rec: [0, 0, 0, 0, 0, 0], bop: '100000', mob: 0, furc: 0 }
    expect(summarize([one], LIMITS)).toMatchObject({ sites: 1, bop: 100, pd_mean: 4, deep: 1 })
  })

  it('CAL считается только у измеренных точек', () => {
    const one: PerioEdit = { tooth: 11, pd: [0, 3, 0, 0, 0, 0], rec: [2, 2, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0 }
    expect(summarize([one], LIMITS).cal_mean).toBe(5)
  })

  it('зуб без единого показания не считается измеренным', () => {
    const empty: PerioEdit = { tooth: 11, pd: [0, 0, 0, 0, 0, 0], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0 }
    expect(hasData(empty)).toBe(false)
    expect(summarize([empty], LIMITS).teeth).toBe(0)
  })
})

describe('находки ревью C23', () => {
  it('цифра, набранная ПОКА идёт запись, не пропадает', async () => {
    await show()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    const d = deferred<ApiResult<PerioModel>>()
    post.mockReturnValue(d.promise)
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    // ассистент не остановился и диктует дальше, пока сервер отвечает
    fireEvent.change(cell(12, 'pd', 0), { target: { value: '4' } })
    const saved: PerioModel = {
      ...MODEL,
      rows: { ...MODEL.rows, '11': { tooth: 11, pd: [5, 0, 0, 0, 0, 0], rec: [0, 0, 0, 0, 0, 0], bop: '000000', mob: 0, furc: 0, cal: [5, 0, 0, 0, 0, 0] } },
    }
    d.go(ok(saved, 'ok_perio', 'Parodontograma a fost salvată'))
    await waitFor(() => expect(cell(11, 'pd', 0).value).toBe('5'))
    expect(cell(12, 'pd', 0).value).toBe('4')   // набранное во время записи цело
    expect(unsaved()).toBeTruthy()              // и оно честно помечено несохранённым
  })

  it('заметка с пробелом по краям: сервер её обрезал — лист считается записанным', async () => {
    await show()
    const note = screen.getByPlaceholderText(/reevaluare după detartraj/) as HTMLInputElement
    fireEvent.change(note, { target: { value: 'a doua ' } })
    expect(unsaved()).toBeTruthy()
    post.mockResolvedValue(ok(
      { ...MODEL, exam: { ...MODEL.exam!, note: 'a doua' } }, 'ok_perio', 'salvat'))
    fireEvent.click(screen.getByRole('button', { name: /Salvează examenul/ }))
    await waitFor(() => expect(unsaved()).toBeNull())
    expect(note.value).toBe('a doua')
  })

  it('записывать нечего — кнопка заперта: летопись не собирает одинаковые строки', async () => {
    await show()
    const save = screen.getByRole('button', { name: /Salvează examenul/ }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    expect(save.disabled).toBe(false)
  })

  it('Enter в заметке записывает осмотр, как неявная отправка старой формы', async () => {
    await show()
    const note = screen.getByPlaceholderText(/reevaluare după detartraj/)
    fireEvent.change(note, { target: { value: 'gata' } })
    post.mockResolvedValue(ok(MODEL, 'ok_perio', 'salvat'))
    fireEvent.keyDown(note, { key: 'Enter' })
    await waitFor(() => expect(post).toHaveBeenCalled())
  })

  it('смена осмотра уводит лист в загрузку — цифра не уходит в покинутый осмотр', async () => {
    const { router } = await show()
    const d = deferred<ApiResult<PerioModel>>()
    get.mockReturnValue(d.promise)
    fireEvent.change(document.querySelector('.pexam') as HTMLSelectElement, { target: { value: '4' } })
    expect(document.querySelector('.ptooth')).toBeNull()        // печатать некуда
    expect(document.querySelector('.pcell input')).toBeNull()   // ни одного поля прежнего осмотра
    expect(document.querySelector('[aria-busy="true"]')).toBeTruthy()
    d.go(ok({ ...MODEL, exam: MODEL.exams[1] ?? null, rows: {} }))
    await waitFor(() => expect(col(16)).toBeTruthy())
    expect(cell(16, 'pd', 0).value).toBe('')
    expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=4')
  })

  it('«Examen nou» ставит новый осмотр в адрес — F5 возвращает в него', async () => {
    const { router } = await show()
    post.mockResolvedValue(ok(
      { ...MODEL, exam: { id: 12, at: '18.09.2026', doctor: '', note: '', teeth: 0 }, rows: {} },
      'ok_perio_new', 'examen nou'))
    fireEvent.click(screen.getByRole('button', { name: /Examen nou/ }))
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=12'))
  })
})

describe('адрес листа ведёт роутер (B2.3)', () => {
  const NEW: PerioModel = {
    ...MODEL,
    exams: [{ id: 12, at: '24.09.2026', doctor: '', note: '', teeth: 0 }, ...MODEL.exams],
    exam: { id: 12, at: '24.09.2026', doctor: '', note: '', teeth: 0 },
    rows: {},
  }
  const PAST: PerioModel = { ...MODEL, exam: MODEL.exams[1] ?? null, rows: {} }
  const picked = () => (document.querySelector('.pexam') as HTMLSelectElement).value

  /**
   * F5: СВЕЖИЙ роутер на адресе, который оставил экран, обязан спросить у
   * движка то же самое. Иначе переход поменял адрес только на вид.
   */
  const f5 = async (router: ReturnType<typeof open>['router']) => {
    const asked = lastGet()
    const url = at(router)
    cleanup()
    get.mockClear()
    await show(url)
    expect(lastGet()).toBe(asked)
  }

  it('загрузка встаёт на экран ещё внутри события выбора — как reset(), ни мгновения на прежний осмотр', async () => {
    // ⚠️ Не openScreen: там RouterProvider из 'react-router', без flushSync, и
    // переход рисуется переходом React — задачей позже. App.tsx берёт его из
    // 'react-router/dom', и проверять это надо тем же.
    const router = createMemoryRouter(
      [screenRoute(PATH, <PerioScreen pid={5} navigate={() => {}} />, loadPerio)], { initialEntries: [SHEET] })
    render(<RouterProvider router={router} />)
    await waitFor(() => expect(col(16)).toBeTruthy())
    const d = deferred<ApiResult<PerioModel>>()
    get.mockReturnValue(d.promise)
    const sel = document.querySelector('.pexam') as HTMLSelectElement
    sel.value = '4'
    sel.dispatchEvent(new Event('change', { bubbles: true }))   // без act: как в окне программы
    expect(document.querySelector('.pcell input')).toBeNull()
    expect(document.querySelector('[aria-busy="true"]')).toBeTruthy()
    d.go(ok({ ...MODEL, exam: MODEL.exams[1] ?? null, rows: {} }))
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=4'))
  })

  it('открытие по адресу: осмотр загрузчик берёт из ?exam=', async () => {
    await show(`${SHEET}?exam=4`)
    expect(get).toHaveBeenCalledWith('/patients/5/perio?exam=4', expect.anything())
  })

  it('?exam= читается правилом страницы: только цифры, иначе — свежий осмотр', async () => {
    const asked = async (search: string) => {
      get.mockClear()
      await loadPerio(new AbortController().signal, { pid: '5' }, new URLSearchParams(search))
      return lastGet()
    }
    expect(await asked('exam=4')).toBe('/patients/5/perio?exam=4')
    expect(await asked('exam=%204%20')).toBe('/patients/5/perio?exam=4')
    expect(await asked('exam=0004')).toBe('/patients/5/perio?exam=4')
    for (const v of ['', 'exam=', 'exam=0']) expect(await asked(v)).toBe('/patients/5/perio')
    // страница эти значения не пропускает (`isdecimal`) — значит, свежий осмотр
    for (const v of ['4.0', '%2B4', '0x4', '1e1', '-4', 'abc']) {
      expect(await asked(`exam=${v}`)).toBe('/patients/5/perio')
    }
    // ⚠️ Полноширинная «４»: страница её пропускает, но число из неё в браузере
    // не выходит — и сегодня это свежий осмотр, а не осмотр 4 (так прочёл бы
    // её Python). То же с сотнями цифр: это бесконечность, а не номер.
    expect(await asked('exam=%EF%BC%94')).toBe('/patients/5/perio')
    expect(await asked(`exam=${'9'.repeat(400)}`)).toBe('/patients/5/perio')
  })

  it('F5 после смены осмотра открывает тот же осмотр', async () => {
    const { router } = await show()
    get.mockResolvedValue(ok(PAST))
    fireEvent.change(document.querySelector('.pexam') as HTMLSelectElement, { target: { value: '4' } })
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=4'))
    await f5(router)
    expect(picked()).toBe('4')
  })

  it('«Examen nou»: ответ POST на экране сразу, загрузчик перечитывает ЕГО осмотр, а не свежий', async () => {
    const { router } = await show()
    post.mockResolvedValue(ok(NEW, 'ok_perio_new', 'examen nou'))
    const d = deferred<ApiResult<PerioModel>>()
    get.mockClear()
    get.mockReturnValue(d.promise)
    fireEvent.click(screen.getByRole('button', { name: /Examen nou/ }))
    await waitFor(() => expect(get).toHaveBeenCalled())
    // как и до роутера: новый осмотр виден и правится, пока идёт перечитывание
    expect(picked()).toBe('12')
    expect(document.querySelector('[aria-busy="true"]')).toBeNull()
    fireEvent.change(cell(11, 'pd', 0), { target: { value: '5' } })
    d.go(ok(NEW))
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=12'))
    // ОДИН запрос, и по номеру: «самый свежий» могло завести второе рабочее место
    expect(get.mock.calls.map((x) => x[0])).toEqual(['/patients/5/perio?exam=12'])
    expect(cell(11, 'pd', 0).value).toBe('5')    // набранное в эти полсекунды цело
    expect(unsaved()).toBeTruthy()
  })

  it('F5 после «Examen nou» открывает новый осмотр', async () => {
    const { router } = await show()
    post.mockResolvedValue(ok(NEW, 'ok_perio_new', 'examen nou'))
    get.mockResolvedValue(ok(NEW))
    fireEvent.click(screen.getByRole('button', { name: /Examen nou/ }))
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=12'))
    await f5(router)
    expect(picked()).toBe('12')
  })

  it('F5 после снятия пустого осмотра открывает оставшийся', async () => {
    get.mockResolvedValue(ok(NEW))
    const { router } = await show(`${SHEET}?exam=12`)
    post.mockResolvedValue(ok(PAST, 'ok_perio_drop', 'examen șters'))
    get.mockResolvedValue(ok(PAST))
    fireEvent.click(screen.getByRole('button', { name: 'Șterge examenul gol' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/patients/5/perio/12/delete', {}))
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=4'))
    expect(lastGet()).toBe('/patients/5/perio?exam=4')
    await f5(router)
    expect(picked()).toBe('4')
  })

  it('новый адрес собирается заново: хвост прошлого (msg) не едет, F5 не повторит плашку', async () => {
    const { router } = await show(`${SHEET}?exam=9&msg=ok_perio`)
    fireEvent.change(document.querySelector('.pexam') as HTMLSelectElement, { target: { value: '4' } })
    await waitFor(() => expect(at(router)).toBe('/admin/patient/5/parodontograma?exam=4'))
  })
})

describe('округление предпросмотра', () => {
  it('половина идёт к чётному — как у Python на сервере', () => {
    expect(roundLikeServer(12.5)).toBe(12)
    expect(roundLikeServer(13.5)).toBe(14)
    expect(roundLikeServer(2.25, 1)).toBe(2.2)
    expect(roundLikeServer(2.35, 1)).toBe(2.4)
  })

  it('на измерениях с ровной половиной итог сходится с сервером', () => {
    const six = (v: number) => [v, v, v, v, v, v]
    const rows: PerioEdit[] = [
      { tooth: 16, pd: six(3), rec: six(1), bop: '110000', mob: 0, furc: 0 },
      { tooth: 26, pd: [4, 4, 4, 3, 3, 3], rec: six(1), bop: '100000', mob: 0, furc: 0 },
      { tooth: 36, pd: six(3), rec: six(1), bop: '000000', mob: 0, furc: 0 },
      { tooth: 46, pd: [4, 4, 4, 3, 3, 3], rec: six(1), bop: '000000', mob: 0, furc: 0 },
    ]
    // 24 точки, сумма 78 → 3.25; att 102 → 4.25; 3 кровоточат → ровно 12.5 %
    const s = summarize(rows, LIMITS)
    expect([s.bop, s.pd_mean, s.cal_mean]).toEqual([12, 3.2, 4.2])
  })
})
