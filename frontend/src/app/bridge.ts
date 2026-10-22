import { useEffect, useLayoutEffect, useRef } from 'react'
import type { DataRouter } from 'react-router'
import { isAppHref } from '../components/AppLink'
import { defaultNavigate } from '../hooks/useLoad'
import { defaultReload } from '../hooks/useLive'
import type { ShellModel } from '../layouts/shell'
import {
  accelOf, allItems, HOMES, itemForAccel, loggedIn, MENU_IDS, menuOf, safePath,
  type CmdState, type MenuEntry, type MenuId,
} from './commands'

/*
 * Мост страницы к оболочке Tauri (Т7, контракт
 * docs/dentpilot-2/tauri-contract.md § 3).
 *
 * ⛔ Только при `window.dpShell`: его вставляет оболочка в страницы своего
 * окна. Браузер второго ПК и телефон его не имеют — и у них нет ни
 * `dpMenu`/`dpRun`/`dpCtx`, ни новых клавиш, ни окна «Despre» (Олег 18.10: в
 * браузере меню не нужно). С 2.0.0 (18.10) программа клиники — окно Tauri, и
 * мост стоит в каждом её окне.
 *
 * Что исполняет пункт — решает список (`commands.ts`); здесь только то, как
 * он доходит: клавиша, `dpRun` из меню, реестр заявленных экранами действий.
 */

/** Что вставляет оболочка. `send('win/zoomin')`, `send('ctx')` — команда ей. */
export interface DpShell {
  v: number
  version: string
  send: (path: string) => void
}

/** Ответ `dpCtx()`: цвет полосы меню и пункты значка у часов. */
export interface ShellCtx {
  v: 1
  color: string
  logged: boolean
  title: string
}

declare global {
  interface Window {
    dpShell?: DpShell
    dpMenu?: (id: string) => { v: 1; items: MenuEntry[] }
    dpRun?: (id: string) => boolean
    dpCtx?: () => ShellCtx
  }
}

/** Версия контракта, на которую написана страница. */
const CONTRACT = 1

interface Bridge {
  router: DataRouter
  shell: DpShell
  model: ShellModel | null
  locked: boolean
  /** Последнее, о чём сказали оболочке (`ctx` + кто вошёл). */
  told: string
}

let bridge: Bridge | null = null

/* ---------- реестр: что заявили смонтированные экраны ---------- */

interface Claim {
  run: () => void
  label?: string
}

/** Стопка на пункт: заявил последним — исполняет он (вкладка поверх экрана). */
const claims = new Map<string, Claim[]>()

/**
 * Пункт, ушедший на свой экран (`HOMES`): экран исполнит его, как только
 * смонтируется. Живёт ровно до прихода: смена пути снимает его в любом
 * случае (`shellArrived`), иначе кнопка, появившаяся на том экране позже
 * (папку копий настроили через минуту), сработала бы сама.
 */
let pending: { id: string; path: string } | null = null

function top(id: string): Claim | undefined {
  return claims.get(id)?.at(-1)
}

function claim(id: string, c: Claim): () => void {
  const stack = claims.get(id) ?? []
  stack.push(c)
  claims.set(id, stack)
  if (pending && pending.id === id && bridge?.router.state.location.pathname === pending.path) {
    pending = null
    c.run()
  }
  return () => {
    const s = claims.get(id)
    const i = s ? s.lastIndexOf(c) : -1
    if (s && i >= 0) s.splice(i, 1)
    if (s && s.length === 0) claims.delete(id)
  }
}

/**
 * Экран заявляет пункт меню: «Tipărește» и «Exportă» серые, пока их никто не
 * заявил; «Pacient nou», «Fă o copie», «Verifică acum» исполняются на своём
 * экране. `run` — то же, что делает кнопка экрана; `null`/`false` — кнопки
 * сейчас нет, и пункта тоже.
 * Без оболочки ничего не регистрирует.
 */
export function useCommand(id: string, run: (() => void) | null | false | undefined, label?: string): void {
  const ref = useRef<(() => void) | null>(null)
  useLayoutEffect(() => { ref.current = run || null })
  const on = Boolean(run)
  useEffect(() => {
    if (!on || !bridge) return
    return claim(id, label ? { run: () => ref.current?.(), label } : { run: () => ref.current?.() })
  }, [id, on, label])
}

/* ---------- состояние окна ---------- */

function state(): CmdState {
  return {
    model: bridge?.model ?? null,
    locked: bridge?.locked ?? false,
    declared: (id) => top(id) !== undefined,
    label: (id) => top(id)?.label,
  }
}

/** Стоит ли мост — то есть открыта ли страница в окне оболочки. */
export function shellOn(): boolean {
  return bridge !== null
}

/** Модель оболочки, которую видит мост (окно «Despre» стоит вне роутера). */
export function shellNow(): ShellModel | null {
  return bridge?.model ?? null
}

/** Версия оболочки — для «Despre». */
export function shellVersion(): string {
  return bridge?.shell.version ?? ''
}

function ctx(): ShellCtx {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--teal').trim()
  return {
    v: 1,
    color: /^#[0-9a-f]{3,8}$/i.test(raw) ? raw : '',
    logged: loggedIn(state()),
    title: document.title,
  }
}

/** Снимок для сравнения: `ctx` плюс КТО вошёл — смена человека тоже повод. */
function snapshot(): string {
  const id = bridge && !bridge.locked ? bridge.model?.identity : null
  return JSON.stringify([ctx(), id ? [id.name, id.role] : null])
}

/**
 * Сказать оболочке «перечитай dpCtx», если что-то из него сменилось: человек,
 * вход, тема. Без оболочки — ничего.
 */
export function shellCtxChanged(): void {
  const b = bridge
  if (!b) return
  const now = snapshot()
  if (now === b.told) return
  b.told = now
  send(b, 'ctx')
}

/** Документ нового адреса принёс свою модель (переход, вход другого человека). */
export function shellModel(m: ShellModel | null): void {
  if (!bridge) return
  bridge.model = m
  shellCtxChanged()
}

/** Замок (экран PIN) встал или снят. */
export function shellLocked(on: boolean): void {
  if (!bridge) return
  bridge.locked = on
  shellCtxChanged()
}

/** Путь сменился: что не исполнилось при приходе, уже не исполнится. */
export function shellArrived(): void {
  pending = null
}

function send(b: Bridge, path: string): void {
  try {
    b.shell.send(path)
  } catch (e) {
    console.error('DentPilot: оболочка не приняла команду', path, e)
  }
}

/* ---------- исполнение ---------- */

/** Переход: экран программы — роутером, без перезагрузки; остальное — документом. */
function go(b: Bridge, path: string): void {
  if (isAppHref(path)) void b.router.navigate(path)
  else defaultNavigate(path)
}

function act(b: Bridge, id: string): void {
  const loc = b.router.state.location
  /* «Programare nouă» здесь не разбирается: её исполняет кнопка шапки
     (`useCommand` в `Topbar`) — окно оболочки на месте или окно дня журнала */
  switch (id) {
    case 'act:reload':
      defaultReload()
      return
    case 'act:back':
      void b.router.navigate(-1)
      return
    case 'act:forward':
      void b.router.navigate(1)
      return
  }
  const c = top(id)
  if (c) {
    c.run()
    return
  }
  /* действие живёт на своём экране: туда — и экран исполнит его сам. Уже
     стоим там, а кнопки нет (папка копий не настроена) — человек на месте,
     где её настраивают; заказ без прихода не ставится */
  const home = HOMES[id]
  if (home && loc.pathname !== home) {
    pending = { id, path: home }
    go(b, home)
  }
}

/**
 * Исполнить пункт `act:*` или `go:*`. `act:` — только видимый и не серый для
 * того, кто сейчас в окне: скрытый пункт не исполняется и снаружи.
 * `go:` — любой путь этой программы (клик по уведомлению ведёт и туда, чего в
 * меню нет), но не при замке: за экраном PIN переходить некуда.
 */
function run(id: string): boolean {
  const b = bridge
  if (!b) return false
  if (id.startsWith('go:')) {
    const path = id.slice(3)
    if (!safePath(path) || b.locked) return false
    go(b, path)
    return true
  }
  if (!id.startsWith('act:')) return false
  const it = allItems(state()).find((i) => i.id === id)
  if (!it || !it.enabled) return false
  act(b, id)
  return true
}

/**
 * Клавиши окна — по тому же списку. Пункт найден: браузеру клавиша не
 * достаётся (Ctrl+P не напечатает весь журнал с меню, когда экран печать не
 * заявил). `win:*` уходит оболочке. Не найден (скрытый раздел, Ctrl+Z в
 * поле) — клавиша идёт своим путём.
 */
function onKey(e: KeyboardEvent): void {
  const b = bridge
  if (!b || e.isComposing) return
  const a = accelOf(e)
  if (!a) return
  const it = itemForAccel(a, state())
  if (!it) return
  e.preventDefault()
  e.stopPropagation()
  /* зажатая клавиша повторяет только масштаб: десять окон записи от одного
     долгого Ctrl+N никому не нужны */
  if (e.repeat && it.id !== 'win:zoomin' && it.id !== 'win:zoomout') return
  if (!it.enabled) return
  if (it.id.startsWith('win:')) send(b, `win/${it.id.slice(4)}`)
  else run(it.id)
}

/**
 * Поставить мост, если страница открыта в окне оболочки. Без `window.dpShell`
 * (или с чужой версией контракта) — ничего. Возвращает снятие (для проверок).
 */
export function installShellBridge(router: DataRouter, model: ShellModel | null): () => void {
  const shell = window.dpShell
  if (!shell || bridge) return () => {}
  if (shell.v !== CONTRACT) {
    console.error(`DentPilot: оболочка говорит на контракте v${shell.v}, страница — на v${CONTRACT}`)
    return () => {}
  }
  const b: Bridge = { router, shell, model, locked: false, told: '' }
  bridge = b
  b.told = snapshot()
  window.dpMenu = (id) => ({
    v: 1,
    items: (MENU_IDS as readonly string[]).includes(id) ? menuOf(id as MenuId, state()) : [],
  })
  window.dpRun = (id) => run(String(id))
  window.dpCtx = ctx
  window.addEventListener('keydown', onKey, true)
  return () => {
    window.removeEventListener('keydown', onKey, true)
    delete window.dpMenu
    delete window.dpRun
    delete window.dpCtx
    if (bridge === b) bridge = null
    pending = null
  }
}
