import { describe, expect, it } from 'vitest'
import type { ShellModel } from '../layouts/shell'
import {
  accelOf, allItems, itemForAccel, MENU_IDS, menuOf, newApptHref, safePath,
  type CmdState, type MenuEntry, type MenuItem,
} from './commands'

/* Список команд окна Tauri (Т7) — чистые функции: что видит человек в каком
   меню и какой пункт отвечает на какую клавишу. Мост и экраны — bridge.test. */

const CAN_ALL = { money: true, settings: true, doctors: true, schedule_all: true }
const NAV_ALL = [
  { key: 'dash', href: '/admin', icon: 'home', label: 'Panoul principal' },
  { key: 'prog', href: '/admin/all', icon: 'cal', label: 'Programări' },
  { key: 'pat', href: '/admin/search', icon: 'pat', label: 'Pacienți' },
  { key: 'med', href: '/admin/medici', icon: 'med', label: 'Medici' },
  { key: 'stat', href: '/admin/stats', icon: 'stat', label: 'Statistici' },
  { key: 'set', href: '/admin/settings', icon: 'set', label: 'Setări' },
]

function model(over: Partial<ShellModel> = {}): ShellModel {
  return {
    identity: { name: 'Ion Director', role: 'director', role_label: 'Director', initials: 'ID', can: CAN_ALL, doctor: '' },
    clinic: { name: 'Clinica Test', mark: '', logo_topbar: '', logo: '' },
    runtime: { version: '9.9.9', tz: 'Europe/Chisinau' },
    about: { data: '', license_until: '' },
    entry: { pin: true, pin_max: 8, backdrop: '' },
    nav: { active: 'dash', items: NAV_ALL, sync: [], foot_title: '' },
    signals: {
      license: { shown: false, html: '' }, tamper: { shown: false, html: '' },
      split: { shown: false, html: '' }, slot: { shown: false, html: '' },
      setup: { shown: false, html: '' }, demo: { shown: false, html: '' },
      backup: { shown: false, html: '' },
    },
    frame: {
      title: '', sub: '', crumbs: [], rail: false, update: '', msg: '',
      site: { href: 'https://dentpilot.md', mark: '' },
      feedback: { email: 'x@y.md', href: 'mailto:x@y.md' }, today: '2026-10-18',
    },
    ...over,
  }
}

/** Регистратура: без денег и настроек, врачи — есть (как у сервера). */
const RECEPTIE = model({
  identity: { name: 'Ana', role: 'receptie', role_label: 'Recepție', initials: 'A',
    can: { money: false, settings: false, doctors: true, schedule_all: true }, doctor: '' },
  nav: { active: 'dash', items: NAV_ALL.filter((i) => i.key !== 'stat' && i.key !== 'set'), sync: [], foot_title: '' },
})

function st(m: ShellModel | null, declared: string[] = [], locked = false,
  labels: Record<string, string> = {}): CmdState {
  return { model: m, locked, declared: (id) => declared.includes(id), label: (id) => labels[id] }
}

const ids = (v: MenuEntry[]) => v.map((e) => ('sep' in e ? '-' : e.id))
const find = (v: MenuEntry[], id: string) => v.find((e): e is MenuItem => !('sep' in e) && e.id === id)

describe('меню по правам вошедшего', () => {
  it('директор: касса, копия, папка данных, справка и обновления на месте', () => {
    const s = st(model())
    expect(ids(menuOf('file', s))).toEqual([
      'act:newAppt', 'act:newPatient', '-', 'act:print', 'act:export', 'go:/admin/casa', '-',
      'act:backupNow', 'win:datafolder', '-', 'act:switchUser', 'win:quit',
    ])
    expect(ids(menuOf('help', s))).toEqual([
      'go:/admin/settings/faq', 'act:checkUpdate', 'go:/admin/license', 'win:mail', '-', 'act:about',
    ])
  })

  it('регистратура: ни кассы, ни копии, ни папки данных, ни справки — сервер их ей и не отдаст', () => {
    const s = st(RECEPTIE)
    const file = ids(menuOf('file', s))
    expect(file).not.toContain('go:/admin/casa')
    expect(file).not.toContain('act:backupNow')
    expect(file).not.toContain('win:datafolder')
    expect(file).toContain('act:newPatient')
    const help = ids(menuOf('help', s))
    expect(help).not.toContain('go:/admin/settings/faq')
    expect(help).not.toContain('act:checkUpdate')
    expect(help).toEqual(['go:/admin/license', 'win:mail', '-', 'act:about'])
  })

  it('вход по PIN-файлу — «Schimbă persoana…» (Ctrl+L); без него — «Ieșire din cont» ссылкой', () => {
    expect(find(menuOf('file', st(model())), 'act:switchUser')).toMatchObject({ label: 'Schimbă persoana…', accel: 'Ctrl+L' })
    const noPin = menuOf('file', st(model({ entry: { pin: false, pin_max: 8, backdrop: '' } })))
    expect(find(noPin, 'act:switchUser')).toBeUndefined()
    expect(find(noPin, 'go:/admin/logout')?.label).toBe('Ieșire din cont')
  })

  it('без вошедшего (замок, экран PIN): только окно, правка, вид и «Despre»', () => {
    const s = st(model(), ['act:about'], true)
    expect(ids(menuOf('file', s))).toEqual(['win:quit'])
    expect(ids(menuOf('go', s))).toEqual([])
    expect(ids(menuOf('view', s))).toEqual(['act:reload', '-', 'win:zoomin', 'win:zoomout', 'win:zoom0', 'win:fullscreen'])
    expect(ids(menuOf('edit', s))).not.toContain('act:quickfind')
    expect(ids(menuOf('help', s))).toEqual(['win:mail', '-', 'act:about'])
  })

  it('разделителей нет в начале, в конце и двух подряд — ни в одном меню, ни у кого', () => {
    for (const s of [st(model()), st(RECEPTIE), st(model(), [], true), st(null)]) {
      for (const id of MENU_IDS) {
        const v = ids(menuOf(id, s))
        expect(v[0], id).not.toBe('-')
        expect(v.at(-1), id).not.toBe('-')
        expect(v.join(' ').includes('- -'), id).toBe(false)
      }
    }
  })

  it('подписи — по-румынски с диакритикой, клавиши — синтаксисом ускорителей Tauri', () => {
    const items = allItems(st(model(), ['act:print', 'act:export', 'act:quickfind', 'act:switchUser', 'act:about']))
    expect(items.find((i) => i.id === 'act:newPatient')).toMatchObject({ label: 'Pacient nou…', accel: 'Ctrl+Shift+N' })
    expect(items.find((i) => i.id === 'act:backupNow')?.label).toBe('Fă o copie de rezervă acum')
    expect(items.find((i) => i.id === 'win:zoomout')).toMatchObject({ label: 'Micșorează', accel: 'Ctrl+-' })
    expect(items.find((i) => i.id === 'act:back')?.accel).toBe('Alt+Left')
    /* ⛔ ни одного знака вне Inter: ни эмодзи, ни стрелок, ни галочек */
    for (const i of items) expect(i.label, i.id).toMatch(/^[\p{L}\p{N} .,:…-]+$/u)
  })
})

describe('«Mergi la» — из того же списка, что левое меню', () => {
  it('пункты и подписи — `nav.items` модели, Ctrl+1…6 по ключам dash…set', () => {
    const go = menuOf('go', st(model()))
    expect(go.slice(0, 6)).toEqual(NAV_ALL.map((n, i) => ({
      id: `go:${n.href}`, label: n.label, accel: `Ctrl+${i + 1}`, enabled: true,
    })))
    expect(ids(go).slice(6)).toEqual(['-', 'act:back', 'act:forward'])
  })

  it('нет раздела слева — нет его и здесь, а клавиша соседа не сдвигается', () => {
    const go = menuOf('go', st(RECEPTIE)).filter((e): e is MenuItem => !('sep' in e))
    expect(go.map((i) => [i.label, i.accel])).toEqual([
      ['Panoul principal', 'Ctrl+1'], ['Programări', 'Ctrl+2'], ['Pacienți', 'Ctrl+3'], ['Medici', 'Ctrl+4'],
      ['Înapoi', 'Alt+Left'], ['Înainte', 'Alt+Right'],
    ])
    expect(itemForAccel('Ctrl+5', st(RECEPTIE))).toBeNull()
    expect(itemForAccel('Ctrl+6', st(RECEPTIE))).toBeNull()
  })

  it('новый раздел сервера сам встаёт в меню (без клавиши); строка без ссылки — нет', () => {
    const m = model({ nav: { active: '', sync: [], foot_title: '', items: [
      ...NAV_ALL, { key: 'nou', href: '/admin/nou', icon: 'x', label: 'Nou' },
      { key: 'gol', href: '', icon: 'x', label: 'Fără legătură' }] } })
    const go = menuOf('go', st(m))
    expect(find(go, 'go:/admin/nou')).toEqual({ id: 'go:/admin/nou', label: 'Nou', enabled: true })
    expect(go.some((e) => !('sep' in e) && e.label === 'Fără legătură')).toBe(false)
  })
})

describe('экран заявляет печать и выгрузку', () => {
  it('не заявлены — пункты серые, но на месте', () => {
    const file = menuOf('file', st(model()))
    expect(find(file, 'act:print')).toMatchObject({ enabled: false, accel: 'Ctrl+P' })
    expect(find(file, 'act:export')).toMatchObject({ enabled: false })
  })

  it('заявлены — живые', () => {
    const file = menuOf('file', st(model(), ['act:print', 'act:export']))
    expect(find(file, 'act:print')?.enabled).toBe(true)
    expect(find(file, 'act:export')?.enabled).toBe(true)
  })

  it('сворачивание меню — подписью кнопки сайдбара; кнопки нет (одонтограмма) — нет пункта', () => {
    expect(find(menuOf('view', st(model())), 'act:fold')).toBeUndefined()
    const v = menuOf('view', st(model(), ['act:fold'], false, { 'act:fold': 'Extinde meniul' }))
    expect(find(v, 'act:fold')).toEqual({ id: 'act:fold', label: 'Extinde meniul', enabled: true })
  })
})

describe('клавиши', () => {
  const key = (code: string, mods: Partial<KeyboardEventInit> = {}, k = '') =>
    new KeyboardEvent('keydown', { code, key: k, ...mods })

  it('нажатие → строка ускорителя, как у пункта', () => {
    expect(accelOf(key('KeyN', { ctrlKey: true }, 'n'))).toBe('Ctrl+N')
    expect(accelOf(key('KeyN', { ctrlKey: true, shiftKey: true }, 'N'))).toBe('Ctrl+Shift+N')
    expect(accelOf(key('F5', {}, 'F5'))).toBe('F5')
    expect(accelOf(key('F11', {}, 'F11'))).toBe('F11')
    expect(accelOf(key('Digit3', { ctrlKey: true }, '3'))).toBe('Ctrl+3')
    expect(accelOf(key('ArrowLeft', { altKey: true }, 'ArrowLeft'))).toBe('Alt+Left')
    expect(accelOf(key('Minus', { ctrlKey: true }, '-'))).toBe('Ctrl+-')
    expect(accelOf(key('Digit0', { ctrlKey: true }, '0'))).toBe('Ctrl+0')
  })

  it('русская раскладка: Ctrl+N — по физической клавише, не по букве «т»', () => {
    expect(accelOf(key('KeyN', { ctrlKey: true }, 'т'))).toBe('Ctrl+N')
    expect(accelOf(key('KeyF', { ctrlKey: true }, 'а'))).toBe('Ctrl+F')
  })

  it('масштаб: «+» с Shift и на правом блоке — тот же Ctrl+=', () => {
    expect(accelOf(key('Equal', { ctrlKey: true, shiftKey: true }, '+'))).toBe('Ctrl+=')
    expect(accelOf(key('NumpadAdd', { ctrlKey: true }, '+'))).toBe('Ctrl+=')
    expect(accelOf(key('NumpadSubtract', { ctrlKey: true }, '-'))).toBe('Ctrl+-')
  })

  it('правый блок без NumLock — End, а не раздел; AltGr (Ctrl+Alt) — не пункт', () => {
    expect(accelOf(key('Numpad1', { ctrlKey: true }, 'End'))).toBeNull()
    expect(itemForAccel(accelOf(key('KeyN', { ctrlKey: true, altKey: true }, 'n')) ?? '', st(model()))).toBeNull()
  })

  it('карта клавиш: каждая клавиша — ровно один пункт', () => {
    const s = st(model(), ['act:print', 'act:export', 'act:quickfind', 'act:switchUser', 'act:about'])
    const keyed = allItems(s).filter((i) => i.accel && !i.id.startsWith('key:'))
    expect(Object.fromEntries(keyed.map((i) => [i.accel, i.id]))).toEqual({
      'Ctrl+N': 'act:newAppt', 'Ctrl+Shift+N': 'act:newPatient', 'Ctrl+P': 'act:print',
      'Ctrl+L': 'act:switchUser', 'Ctrl+F': 'act:quickfind', F5: 'act:reload',
      'Ctrl+=': 'win:zoomin', 'Ctrl+-': 'win:zoomout', 'Ctrl+0': 'win:zoom0', F11: 'win:fullscreen',
      'Ctrl+1': 'go:/admin', 'Ctrl+2': 'go:/admin/all', 'Ctrl+3': 'go:/admin/search',
      'Ctrl+4': 'go:/admin/medici', 'Ctrl+5': 'go:/admin/stats', 'Ctrl+6': 'go:/admin/settings',
      'Alt+Left': 'act:back', 'Alt+Right': 'act:forward', F1: 'go:/admin/settings/faq',
    })
    expect(new Set(keyed.map((i) => i.accel)).size).toBe(keyed.length)
  })

  it('⛔ Ctrl+Z/Y/X/C/V/A страница не берёт — в поле это родные команды', () => {
    const s = st(model())
    for (const k of ['Z', 'Y', 'X', 'C', 'V', 'A']) expect(itemForAccel(`Ctrl+${k}`, s), k).toBeNull()
    /* а в меню «Editare» они подписаны — их исполняет оболочка */
    expect(ids(menuOf('edit', s)).slice(0, 7)).toEqual(['key:z', 'key:y', '-', 'key:x', 'key:c', 'key:v', 'key:a'])
  })
})

describe('мелочи списка', () => {
  it('«Programare nouă»: на дне журнала — этот день и врач, иначе сегодня', () => {
    expect(newApptHref('/admin/all', '?date=2026-10-22', '2026-10-18')).toBe('/admin/all?date=2026-10-22#addform')
    expect(newApptHref('/admin/doctor/ana', '', '2026-10-18')).toBe('/admin/doctor/ana#addform')
    expect(newApptHref('/admin/stats', '?from=x', '2026-10-18')).toBe('/admin/all?date=2026-10-18#addform')
  })

  it('`go:` — только путь этой программы', () => {
    expect(safePath('/admin/settings/system')).toBe(true)
    expect(safePath('/admin/casa?d=2026-10-18')).toBe(true)
    for (const bad of ['//evil.md/x', 'https://evil.md', 'javascript:alert(1)', '/\\evil', 'admin', '/a b']) {
      expect(safePath(bad), bad).toBe(false)
    }
  })
})
