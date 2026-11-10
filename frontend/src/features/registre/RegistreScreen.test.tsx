import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import { RegistreScreen } from './RegistreScreen'
import type { CleanRow, CycleRow, RegData, UvRow } from './registre'

/* «Registre» (10.11, вариант B): «Azi» — плитки оборудования, старт и
   закрытие цикла, лампа, уборка и проверка; «Istoric» — таблица бланка,
   исправление новой записью, удаление только с правом. Правила (подпись,
   однократное закрытие, ресурс лампы) — сервера и `tests/test_registre.py`;
   здесь только то, что рисует и шлёт экран. ⛔ Учётки и времени экран не шлёт;
   КТО СДЕЛАЛ — человек из окна (`doer`, registre-people 10.11). */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

const cycle = (over: Partial<CycleRow> = {}): CycleRow => ({
  id: 5, reg: '257', actor: 'Recepție', doer: 'Ana Rusu', legacy: false, at: '10.11.2026 09:16', fixes: null, fixed_by: null, why: '',
  date: '10.11.2026', start: '08:30', end: '09:15', open: false, ster_id: 1, ster: 'Melag 23 B+ nr. 23-11845',
  program: 'Universal 134 °C', pressure: '2,1', temp: '134', arts: [{ name: 'Instrumentar stomatologic', qty: 12, pack: 'Pungă' }],
  chem: 'ok', term: 'ok', bio: '', end_actor: 'Recepție', end_doer: 'Ana Rusu', bio_actor: '', bio_at: '', started_at: '2026-11-10T06:30:00+00:00', ...over,
})
const clean = (over: Partial<CleanRow> = {}): CleanRow => ({
  id: 3, reg: '502', actor: 'Recepție', doer: 'Ion Cebotari', legacy: false, at: '07.11.2026 18:55', fixes: null, fixed_by: null, why: '',
  room_id: 9, room: 'Sala de sterilizare', plan: '07.11.2026', done: '07.11.2026', solution: 'Septodor', sup_actor: '', sup_by: '', sup_at: '',
  actor_id: 'ion', ...over,
})
const uv = (over: Partial<UvRow> = {}): UvRow => ({
  id: 4, reg: '501', actor: 'Recepție', doer: 'Ana Rusu', legacy: false, at: '10.11.2026 08:20', fixes: null, fixed_by: null, why: '', date: '10.11.2026',
  lamp_id: 20, lamp: 'OBN-150 nr. 2', room: 'Cabinet 1', cond: 'fără persoane', on: '07:50', off: '08:20', open: false,
  minutes: 30, rest: 38, off_actor: 'Ana Rusu', on_at: '2026-11-10T05:50:00+00:00', ...over,
})

const RUN = cycle({ id: 8, open: true, end: '', end_actor: '', end_doer: '', chem: '', term: '', started_at: '2026-11-10T09:20:00+00:00', start: '11:20' })

function data(over: Partial<RegData> = {}): RegData {
  return {
    today: '2026-11-10', month: '2026-11', prev: '2026-10', next: '2026-12',
    me: { name: 'Ana Rusu', id: 'ana' }, can: { delete: false, settings: false },
    sters: [
      { id: 1, kind: 'ster', name: 'Melag 23 B+', nr: '23-11845', room: '', active: true,
        data: { type: 'abur', programs: [{ label: 'Universal 134 °C', temp: '134', pressure: '2,1', min: 5 },
          { label: 'Delicat 121 °C', temp: '121', pressure: '1,1', min: 20 }] }, running: RUN, last: null },
      { id: 2, kind: 'ster', name: 'GP-40', nr: '0412', room: '', active: true,
        data: { type: 'aer', programs: [{ label: 'Aer 180 °C', temp: '180', pressure: '', min: 60 }] }, running: null, last: cycle({ id: 2 }) },
    ],
    lamps: [
      { id: 20, kind: 'lamp', name: 'OBN-150', nr: '2', room: 'Cabinet 1', active: true, used: 7962, rest: 38, low: true,
        data: { hours: 8000, screened: false, since: '2025-03-01' }, on: null },
      { id: 21, kind: 'lamp', name: 'Dezar-3', nr: '7', room: 'Cabinet 2', active: true, used: 10, rest: 8990, low: false,
        data: { hours: 9000, screened: true, since: '2026-01-12' }, on: uv({ id: 6, open: true, off: '', minutes: null, rest: null }) },
    ],
    rooms: [
      { id: 9, kind: 'room', name: 'Cabinet 1', nr: '', room: '', active: true, data: { every: 7 }, next: '10.11.2026', last: '03.11.2026', due: true, late: false, done_azi: false, done_ieri: false },
      { id: 10, kind: 'room', name: 'Cabinet 2', nr: '', room: '', active: true, data: { every: 7 }, next: '12.11.2026', last: '10.11.2026', due: false, late: false, done_azi: true, done_ieri: false },
    ],
    waiting: [clean(), clean({ id: 7, room: 'Cabinet 2', doer: 'Director', legacy: true, actor: 'Director', actor_id: 'clinic' })],
    staff: [{ name: 'Ion Cebotari', func: 'îngrijitor', sup: false }, { name: 'Ana Rusu', func: 'asistentă medicală', sup: false },
      { name: 'Elena Ceban', func: 'asistentă-șefă', sup: true }],
    solutions: ['Septodor Forte 0,2 % · 60 min', 'Clorantoin 0,1 %'],
    articles: ['Instrumentar stomatologic', 'Freze și pile'],
    packs: ['Pungă', 'Casetă'],
    empty: false,
    feed: [RUN, uv()],
    rows: {
      '257': [cycle({ id: 3, fixed_by: 4 }), cycle({ id: 4, fixes: 3, why: 'Piese: 3, nu 4' }), cycle({ id: 7, bio: 'wait' }), RUN],
      '502': [clean({ id: 2, sup_actor: 'Elena Ceban', sup_by: 'Recepție', sup_at: '08.11.2026 08:15' }),
        clean({ id: 1, doer: 'Director', legacy: true, actor: 'Director', sup_actor: 'Medic', sup_at: '08.11.2026 08:00' }), clean()],
      '501': [uv(), uv({ id: 6, open: true, off: '', minutes: null, rest: null })],
    },
    ...over,
  }
}

const tile = (attr: string, id: number) => document.querySelector(`[${attr}="${id}"]`) as HTMLElement
const findTile = (attr: string, id: number) => waitFor(() => {
  const e = tile(attr, id)
  if (!e) throw new Error(`нет [${attr}=${id}]`)
  return e
})
const dialog = () => document.querySelector('dialog[open]') as HTMLElement
/** Своё слово: поле с подписью `label` и его «Adaugă» (полей в окне бывает два). */
function own(d: HTMLElement, label: string, value: string) {
  const box = within(d).getByRole('textbox', { name: label })
  fireEvent.change(box, { target: { value } })
  fireEvent.click(within(box.closest('.rg-own') as HTMLElement).getByRole('button', { name: /Adaugă/ }))
  return box as HTMLInputElement
}

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); vi.restoreAllMocks(); window.history.replaceState(null, '', '/') })

describe('RegistreScreen — «Azi»', () => {
  it('плитки: идущий цикл и свободный автоклав, лампа на исходе, уборка к сроку, проверка окном, лента', async () => {
    get.mockResolvedValueOnce(ok(data()))
    render(<RegistreScreen />)
    expect(await screen.findByText('Azi, 10 noiembrie')).toBeTruthy()
    expect(within(tile('data-ster', 1)).getByRole('button', { name: /Încheie ciclul/ })).toBeTruthy()
    expect(within(tile('data-ster', 1)).getByText('Universal 134 °C · pornit 11:20')).toBeTruthy()
    expect(within(tile('data-ster', 2)).getByRole('button', { name: /Ciclu nou/ })).toBeTruthy()
    expect(tile('data-lamp', 20).className).toContain('low')
    expect(tile('data-lamp', 20).querySelector('.lamp-rest')?.textContent).toBe('38 ore rămase din 8000 — schimbați lampa')
    expect(within(tile('data-lamp', 21)).getByRole('button', { name: /Oprește/ })).toBeTruthy()
    expect(tile('data-room', 9).querySelector('.chip')?.textContent).toBe('azi')
    expect(tile('data-room', 10).querySelector('.chip')?.textContent).toBe('12.11.2026')
    // проверка — окном выбора человека у любой учётки (одна учётка вносит обе подписи)
    expect((within(tile('data-sup', 7)).getByRole('button', { name: /Verifică/ }) as HTMLButtonElement).disabled).toBe(false)
    expect(tile('data-sup', 3).textContent).toContain('Ion Cebotari')
    expect(tile('data-bio', 7)).toBeTruthy()
    expect(document.querySelectorAll('.rg-feed-r')).toHaveLength(2)
    expect(screen.queryByText('Echipamente')).toBeNull()
  })

  it('«Ciclu nou»: автоклав, программа, предметы, ответственный кнопками → команда без учётки и времени, затем перечитать', async () => {
    get.mockResolvedValue(ok(data()))
    post.mockResolvedValueOnce(ok(null, 'ok_san_start', 'Ciclul a pornit'))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-ster', 2)).findByRole('button', { name: /Ciclu nou/ }))
    const d = dialog()
    expect(within(d).getByText('Înregistrează: Ana Rusu')).toBeTruthy()
    // вошедшая — в списке «Personal»: она и предложена
    expect(within(d).getByRole('button', { name: /^Ana Rusu/ }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(within(d).getByRole('button', { name: /^Ion Cebotari/ }))
    // занятый автоклав выбрать нельзя
    expect((within(d).getByRole('button', { name: 'Melag 23 B+' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(within(d).getByRole('button', { name: /Freze și pile/ }))
    fireEvent.click(within(d).getAllByRole('button', { name: 'plus' })[0]!)
    fireEvent.click(within(d).getByRole('button', { name: /Pornește ciclul/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/257', {
      ster_id: 2, program: 0, doer: 'Ion Cebotari',
      arts: [{ name: 'Instrumentar stomatologic', qty: 2, pack: 'Pungă' }, { name: 'Freze și pile', qty: 1, pack: 'Pungă' }],
    }))
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Ciclul a pornit')).toBeTruthy()
  })

  it('«Încheie ciclul»: тесты кнопками, неудачный — предупреждение; отказ сервера — его словами', async () => {
    get.mockResolvedValue(ok(data()))
    post.mockRejectedValueOnce(new ApiError({ kind: 'conflict', code: 'san_closed', text: 'Înregistrarea este deja încheiată — reîncărcați pagina' }, 'c'))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-ster', 1)).findByRole('button', { name: /Încheie ciclul/ }))
    const d = dialog()
    expect(within(d).queryByText(/marcat roșu/)).toBeNull()
    fireEvent.click(within(d).getAllByRole('button', { name: /Incorect/ })[0]!)
    expect(within(d).getByText(/marcat roșu/)).toBeTruthy()
    fireEvent.click(within(d).getByRole('button', { name: 'Pus la incubare' }))
    fireEvent.click(within(d).getAllByRole('button', { name: /Încheie ciclul/ }).at(-1)!)
    // закрывает по умолчанию тот, кто запускал
    expect(within(d).getByRole('button', { name: /^Ana Rusu/ }).getAttribute('aria-pressed')).toBe('true')
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/257/8/finish', { chem: 'fail', term: 'ok', bio: 'wait', doer: 'Ana Rusu' }))
    expect(await screen.findByText('Înregistrarea este deja încheiată — reîncărcați pagina')).toBeTruthy()
  })

  it('лампа: без экрана «в присутствии» выключено; «Oprește» — команда сразу; итог биотеста — кнопкой', async () => {
    get.mockResolvedValue(ok(data()))
    post.mockResolvedValue(ok(null, 'ok', ''))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-lamp', 20)).findByRole('button', { name: /Pornește lampa/ }))
    const d = dialog()
    expect((within(d).getByRole('button', { name: 'în prezența persoanelor' }) as HTMLButtonElement).disabled).toBe(true)
    expect(within(d).getByText(/38 ore rămase din 8000/)).toBeTruthy()
    fireEvent.click(within(d).getAllByRole('button', { name: /Pornește lampa/ }).at(-1)!)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/501', { lamp_id: 20, cond: 'fara', doer: 'Ana Rusu' }))
    fireEvent.click(within(tile('data-lamp', 21)).getByRole('button', { name: /Oprește/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/501/6/off', {}))
    fireEvent.click(within(tile('data-bio', 7)).getByRole('button', { name: /Negativ/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/257/7/bio', { bio: 'ok' }))
  })

  it('проверка уборки: исполнитель выключен, проверяющие впереди, без выбора не сохранить', async () => {
    get.mockResolvedValue(ok(data()))
    post.mockResolvedValue(ok(null, 'ok_san_sup', ''))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-sup', 3)).findByRole('button', { name: /Verifică/ }))
    const d = dialog()
    expect(within(d).getByText('Ion Cebotari', { selector: 'b' })).toBeTruthy()
    const doer = within(d).getByRole('button', { name: /^Ion Cebotari/ }) as HTMLButtonElement
    expect(doer.disabled).toBe(true)
    expect(doer.textContent).toContain('a efectuat')
    expect(within(d).getAllByRole('button', { name: /·/ })[0]!.textContent).toContain('Elena Ceban')
    const save = within(d).getByRole('button', { name: /Salvează/ }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.click(within(d).getByRole('button', { name: /^Elena Ceban/ }))
    fireEvent.click(save)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/502/3/sup', { who: 'Elena Ceban' }))
  })

  it('уборка: помещение, кто сделал, раствор, «Ieri» → команда; повтор дня — предупреждение', async () => {
    get.mockResolvedValue(ok(data()))
    post.mockResolvedValueOnce(ok(null))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-room', 9)).findByRole('button', { name: /Efectuată/ }))
    const d = dialog()
    expect(within(d).getByText('10.11.2026')).toBeTruthy()
    fireEvent.click(within(d).getByRole('button', { name: 'Clorantoin 0,1 %' }))
    expect(within(d).queryByText(/deja scrisă/)).toBeNull()
    // Cabinet 2 уже убран сегодня — предупреждение, но не запрет; на «Ieri» — его нет
    fireEvent.click(within(d).getByRole('button', { name: 'Cabinet 2' }))
    expect(within(d).getByText(/Cabinet 2: curățenia generală e deja scrisă azi/)).toBeTruthy()
    fireEvent.click(within(d).getByRole('button', { name: 'Ieri' }))
    expect(within(d).queryByText(/deja scrisă/)).toBeNull()
    fireEvent.click(within(d).getByRole('button', { name: /^Ion Cebotari/ }))
    fireEvent.click(within(d).getByRole('button', { name: /Salvează/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/502',
      { room_id: 10, solution: 'Clorantoin 0,1 %', doer: 'Ion Cebotari', day: 'ieri' }))
  })

  it('свежая клиника: список персонала пуст — не тупик, имя словом (Alt nume)', async () => {
    get.mockResolvedValue(ok(data({ staff: [], me: { name: 'Director', id: 'clinic' } })))
    post.mockResolvedValueOnce(ok(null))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-room', 9)).findByRole('button', { name: /Efectuată/ }))
    const d = dialog()
    expect(within(d).getByText(/Lista personalului este goală/)).toBeTruthy()
    const save = within(d).getByRole('button', { name: /Salvează/ }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    own(d, 'Alt nume', '  Maria   Lungu ')
    expect(within(d).getByRole('button', { name: 'Maria Lungu' }).getAttribute('aria-pressed')).toBe('true')
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/502',
      { room_id: 9, solution: 'Septodor Forte 0,2 % · 60 min', doer: 'Maria Lungu', day: 'azi' }))
  })

  it('пустой каталог: директору — дверь в настройки, остальным — кому сказать', async () => {
    get.mockResolvedValueOnce(ok(data({ empty: true, sters: [], lamps: [], rooms: [], can: { delete: true, settings: true } })))
    render(<RegistreScreen />)
    expect(await screen.findByText('Registrele nu au încă echipamente')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Setări › Registre sanitare/ }).getAttribute('href')).toBe('/admin/settings/registre')
    cleanup()
    get.mockResolvedValueOnce(ok(data({ empty: true, sters: [], lamps: [], rooms: [] })))
    render(<RegistreScreen />)
    expect(await screen.findByText('Registrele nu au încă echipamente')).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Setări › Registre sanitare/ })).toBeNull()
  })
})

describe('RegistreScreen — пустой каталог не тупик (2.14.1)', () => {
  it('предметов нет: подсказка со ссылкой у директора, «Alt articol» добавляет предмет и открывает «Pornește ciclul»', async () => {
    get.mockResolvedValue(ok(data({ articles: [], packs: [], can: { delete: true, settings: true } })))
    post.mockResolvedValueOnce(ok(null))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-ster', 2)).findByRole('button', { name: /Ciclu nou/ }))
    const d = dialog()
    expect(within(d).getByText(/Lista de articole este goală/)).toBeTruthy()
    expect(within(d).getByRole('link', { name: /Setări › Registre sanitare/ }).getAttribute('href')).toBe('/admin/settings/registre')
    const start = within(d).getByRole('button', { name: /Pornește ciclul/ }) as HTMLButtonElement
    expect(start.disabled).toBe(true)
    const box = own(d, 'Alt articol', '  Spatulă   de ciment ')
    expect(within(d).getByText('Spatulă de ciment')).toBeTruthy()
    expect(box.value).toBe('')
    expect(start.disabled).toBe(false)
    fireEvent.click(start)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/257', {
      ster_id: 2, program: 0, doer: 'Ana Rusu', arts: [{ name: 'Spatulă de ciment', qty: 1, pack: '' }] }))
  })

  it('без права настроек — подсказка без ссылки; пустых видов — строка, чего нет', async () => {
    get.mockResolvedValue(ok(data({ articles: [], lamps: [], rooms: [], waiting: [] })))
    render(<RegistreScreen />)
    expect(await screen.findByText(/Încă nu sunt adăugate: lămpile bactericide \(501\/e\), încăperile \(502\/e\)/)).toBeTruthy()
    fireEvent.click(await within(await findTile('data-ster', 2)).findByRole('button', { name: /Ciclu nou/ }))
    const d = dialog()
    expect(within(d).getByText(/Directorul le adaugă/)).toBeTruthy()
    expect(within(d).queryByRole('link')).toBeNull()
  })

  it('растворов нет: свой раствор словом → уборка уходит с ним', async () => {
    get.mockResolvedValue(ok(data({ solutions: [] })))
    post.mockResolvedValueOnce(ok(null))
    render(<RegistreScreen />)
    fireEvent.click(await within(await findTile('data-room', 9)).findByRole('button', { name: /Efectuată/ }))
    const d = dialog()
    expect(within(d).getByText(/Lista de soluții este goală/)).toBeTruthy()
    const save = within(d).getByRole('button', { name: /Salvează/ }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    own(d, 'Altă soluție', 'Clorhexidină 0,05 %')
    expect(within(d).getByRole('button', { name: 'Clorhexidină 0,05 %' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(save)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/502',
      { room_id: 9, solution: 'Clorhexidină 0,05 %', doer: 'Ana Rusu', day: 'azi' }))
  })
})

describe('RegistreScreen — «Istoric și tipar»', () => {
  it('вкладки со счётчиками, исправленная строка зачёркнута, лист и Excel за месяц, удаления без права нет', async () => {
    get.mockResolvedValue(ok(data()))
    render(<RegistreScreen />)
    fireEvent.click(await screen.findByRole('button', { name: /Istoric și tipar/ }))
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(
      ['Sterilizare 257/e 4', 'Curățenie generală 502/e 3', 'Lămpi bactericide 501/e 2'])
    const old = document.querySelector('[data-row="3"]') as HTMLElement
    expect(old.className).toContain('old')
    expect(old.textContent).toContain('corectată prin nr. 4')
    expect(within(old).queryByRole('button', { name: /Corectează/ })).toBeNull()
    expect((document.querySelector('[data-row="4"]') as HTMLElement).textContent).toContain('corectează nr. 3: Piese: 3, nu 4')
    expect(within(document.querySelector('[data-row="8"]') as HTMLElement).queryByRole('button', { name: /Corectează/ })).toBeNull()
    expect(screen.getByRole('link', { name: /Tipărește/ }).getAttribute('href')).toBe('/admin/registre/tipar/257?month=2026-11')
    expect(screen.getByRole('link', { name: /Excel/ }).getAttribute('href')).toBe('/admin/registre/excel/257?month=2026-11')
    expect(screen.queryByRole('button', { name: /Șterge nr/ })).toBeNull()
    // кто сделал — человек, под ним учётка; строка до 10.11 — «cont (înreg. veche)»
    expect(screen.getByText(/Semnăturile — de mână, pe foaia tipărită/)).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: /Curățenie/ }))
    const r2 = document.querySelector('[data-row="2"]') as HTMLElement
    expect(r2.textContent).toContain('Ion Cebotariînreg. Recepție')
    expect(r2.textContent).toContain('Elena Ceban')
    const r1 = document.querySelector('[data-row="1"]') as HTMLElement
    expect(r1.textContent).toContain('Directorcont (înreg. veche)')
    expect(r1.textContent).toContain('Mediccont (înreg. veche)')
    fireEvent.click(screen.getByRole('tab', { name: /Lămpi/ }))
    expect(screen.getByRole('link', { name: /Tipărește/ }).getAttribute('href')).toBe('/admin/registre/tipar/501?month=2026-11')
    fireEvent.click(screen.getByRole('button', { name: 'Luna trecută' }))
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/registre?month=2026-10', expect.anything()))
  })

  it('исправление: причина обязательна, уходит новой записью; директор удаляет после вопроса', async () => {
    get.mockResolvedValue(ok(data({ can: { delete: true, settings: true } })))
    post.mockResolvedValue(ok(null))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<RegistreScreen />)
    fireEvent.click(await screen.findByRole('button', { name: /Istoric și tipar/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Corectează nr. 7' }))
    const d = dialog()
    const save = within(d).getByRole('button', { name: /Salvează/ }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    const why = Array.from(d.querySelectorAll('input')).at(-1)!
    fireEvent.change(why, { target: { value: 'altă oră' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/257/7/fix', expect.objectContaining({
      why: 'altă oră', start: '08:30', end: '09:15', chem: 'ok', bio: 'wait' })))
    // исполнителя не трогали — он не уходит (сервер перенесёт прежнего)
    expect(post.mock.calls.at(-1)![1]).not.toHaveProperty('doer')
    fireEvent.click(screen.getByRole('button', { name: 'Șterge nr. 7' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/registre/257/7/delete', {}))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(confirm.mock.calls[0]![0]).toContain('nr. 7')
  })
})
