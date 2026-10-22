import type { ShellModel } from '../layouts/shell'

/*
 * Один список команд окна программы (Т7 перехода на Tauri, контракт
 * docs/dentpilot-2/tauri-contract.md § 3). Из него строятся И пункты полосы
 * меню (оболочка зовёт `dpMenu` при каждом открытии списка), И горячие
 * клавиши страницы (`bridge.ts`): второй карты клавиш нет, и пункт, которого
 * человек не видит в меню, не срабатывает и клавишей.
 *
 * ⭐ Пункты — песочница Т4, которую Олег видел (`menus.rs`), и § 8 разбора
 * `review/windows-app-tauri-2026-10-18.md`. Каждый пункт ЗОВЁТ уже
 * существующее действие: кнопку шапки, диалог «Pacient nou», «Exportă» экрана,
 * «Fă o copie acum», «Verifică acum», Ctrl+K поиска. Новой логики в меню нет.
 *
 * ⛔ Скрытый пункт — удобство, а не право: отказ выдаёт сервер в самом
 * маршруте (как у левого меню, `layouts/shell.ts`).
 *
 * Клавиша — строка синтаксиса ускорителей Tauri («Ctrl+Shift+N», «Alt+Left»,
 * «Ctrl+=»): её же оболочка подписывает справа от пункта.
 */

export type MenuId = 'file' | 'edit' | 'view' | 'go' | 'help'
export const MENU_IDS: readonly MenuId[] = ['file', 'edit', 'view', 'go', 'help']

export interface MenuItem {
  /** `act:` и `go:` исполняет страница, `win:` и `key:` — оболочка. */
  id: string
  label: string
  accel?: string
  enabled: boolean
}
export type MenuEntry = MenuItem | { sep: true }

/** Что известно странице в момент вопроса. */
export interface CmdState {
  /** Модель оболочки текущего документа; `null` — каркаса нет. */
  model: ShellModel | null
  /** Стоит замок (экран PIN, B4.4): вошедшего нет, хотя модель прежняя. */
  locked: boolean
  /** Заявил ли пункт смонтированный экран (`useCommand`). */
  declared: (id: string) => boolean
  /** Подпись, которую заявитель назвал сам (кнопка сайдбара: «Restrânge» / «Extinde»). */
  label: (id: string) => string | undefined
}

/**
 * Пункты, которые без экрана не исполнить: печать и выгрузку заявляет экран,
 * где они есть (на остальных пункт серый), поиск — накладка `QuickFind`,
 * смену человека — кнопка выхода шапки, «Despre» — его окно, сворачивание
 * меню — кнопка сайдбара, «Programare nouă» — кнопка шапки (22.10: вне дня
 * журнала она открывает окно оболочки, а не переход, и знает это только она).
 */
export const DECLARED: ReadonlySet<string> = new Set([
  'act:print', 'act:export', 'act:quickfind', 'act:switchUser', 'act:about', 'act:fold',
  'act:newAppt',
])

/**
 * Пункты, чьё действие живёт на СВОЁМ экране: заявлено — исполняется сразу,
 * нет — переход туда, и экран исполняет его, как только смонтируется
 * (`useCommand`; заказ — `act` в `bridge.ts`).
 */
export const HOMES: Readonly<Record<string, string>> = {
  'act:newPatient': '/admin/search',
  'act:backupNow': '/admin/settings/backup',
  'act:checkUpdate': '/admin/settings/system',
}

/** «Mergi la»: ключи левого меню в порядке Ctrl+1…6 (как в Outlook). */
export const NAV_ORDER = ['dash', 'prog', 'pat', 'med', 'stat', 'set'] as const

/** Права, как их считает сервер: без вошедшего (ключ сервера) — всё видно. */
function rights(m: ShellModel) {
  return m.identity?.can ?? { money: true, settings: true, doctors: true }
}

/** Человек в окне: модель есть и замка нет. */
export function loggedIn(s: CmdState): boolean {
  return s.model !== null && !s.locked
}

function make(id: string, label: string, accel: string | undefined, enabled: boolean): MenuItem {
  return accel ? { id, label, accel, enabled } : { id, label, enabled }
}

const SEP = { sep: true } as const

/** Пункты меню `id` для того, кто сейчас в окне. */
export function menuOf(id: MenuId, s: CmdState): MenuEntry[] {
  const v: MenuEntry[] = []
  const m = loggedIn(s) ? s.model : null
  const can = m ? rights(m) : null
  /* серый — пункт из DECLARED, которого сейчас никто не заявил */
  const item = (cmd: string, label: string, accel?: string) =>
    make(cmd, label, accel, !DECLARED.has(cmd) || s.declared(cmd))
  const fold = s.declared('act:fold') ? s.label('act:fold') : undefined
  switch (id) {
    case 'file':
      if (m && can) {
        v.push(item('act:newAppt', 'Programare nouă…', 'Ctrl+N'))
        v.push(item('act:newPatient', 'Pacient nou…', 'Ctrl+Shift+N'))
        v.push(SEP)
        v.push(item('act:print', 'Tipărește…', 'Ctrl+P'))
        v.push(item('act:export', 'Exportă în Excel…'))
        if (can.money) v.push(item('go:/admin/casa', 'Raportul de casă al zilei…'))
        v.push(SEP)
        if (can.settings) {
          v.push(item('act:backupNow', 'Fă o copie de rezervă acum'))
          v.push(item('win:datafolder', 'Deschide dosarul cu datele'))
          v.push(SEP)
        }
        /* ⭐ Вход по PIN-файлу: «Ieșire din cont» шапки и есть смена человека
           без перезагрузки (B4.4) — второй пункт с тем же действием путал бы.
           Без PIN-файла (ключ сервера) выход — ссылка, как в шапке. */
        if (m.entry.pin) v.push(item('act:switchUser', 'Schimbă persoana…', 'Ctrl+L'))
        else v.push(item('go:/admin/logout', 'Ieșire din cont'))
      }
      v.push(item('win:quit', 'Închide DentPilot complet…'))
      break
    case 'edit':
      v.push(item('key:z', 'Anulează', 'Ctrl+Z'))
      v.push(item('key:y', 'Refă', 'Ctrl+Y'))
      v.push(SEP)
      v.push(item('key:x', 'Decupează', 'Ctrl+X'))
      v.push(item('key:c', 'Copiază', 'Ctrl+C'))
      v.push(item('key:v', 'Lipește', 'Ctrl+V'))
      v.push(item('key:a', 'Selectează tot', 'Ctrl+A'))
      if (m) {
        v.push(SEP)
        v.push(item('act:quickfind', 'Caută pacient…', 'Ctrl+F'))
      }
      break
    case 'view':
      v.push(item('act:reload', 'Reîncarcă', 'F5'))
      v.push(SEP)
      v.push(item('win:zoomin', 'Mărește', 'Ctrl+='))
      v.push(item('win:zoomout', 'Micșorează', 'Ctrl+-'))
      v.push(item('win:zoom0', 'Mărime normală', 'Ctrl+0'))
      v.push(item('win:fullscreen', 'Ecran complet', 'F11'))
      if (m) {
        v.push(SEP)
        v.push(item('go:/admin/all', 'Programări: ziua'))
        v.push(item('go:/admin/week', 'Programări: săptămâna'))
        /* «Restrânge / Extinde meniul» — словами кнопки сайдбара (подпись
           называет сама кнопка); на экранах, где узость задал сервер
           (одонтограмма), кнопки нет — нет и пункта */
        if (fold) v.push(item('act:fold', fold))
      }
      break
    case 'go':
      if (m) {
        /* ⭐ Тот же список, что левое меню: сервер присылает его уже по правам
           (`nav.items`), и новый раздел сам появится и слева, и здесь. */
        for (const it of m.nav.items) {
          if (!it.href) continue
          const n = (NAV_ORDER as readonly string[]).indexOf(it.key)
          v.push(item(`go:${it.href}`, it.label, n >= 0 ? `Ctrl+${n + 1}` : undefined))
        }
        v.push(SEP)
        v.push(item('act:back', 'Înapoi', 'Alt+Left'))
        v.push(item('act:forward', 'Înainte', 'Alt+Right'))
      }
      break
    case 'help':
      if (m && can) {
        /* справка и «Stare sistem» — за правом настроек у сервера
           (`/api/settings/faq`, `/api/settings/system`) */
        if (can.settings) {
          v.push(item('go:/admin/settings/faq', 'Întrebări frecvente', 'F1'))
          v.push(item('act:checkUpdate', 'Verifică actualizări'))
        }
        v.push(item('go:/admin/license', 'Licența'))
      }
      v.push(item('win:mail', 'Scrie-ne o problemă'))
      v.push(SEP)
      v.push(item('act:about', 'Despre DentPilot'))
      break
  }
  return tidy(v)
}

/** Без разделителей в начале, в конце и двух подряд. */
function tidy(v: MenuEntry[]): MenuEntry[] {
  const out: MenuEntry[] = []
  for (const e of v) {
    if ('sep' in e && (out.length === 0 || 'sep' in (out.at(-1) ?? SEP))) continue
    out.push(e)
  }
  if (out.length > 0 && 'sep' in (out.at(-1) ?? SEP)) out.pop()
  return out
}

/** Все пункты всех меню — для клавиш и для проверки `dpRun`. */
export function allItems(s: CmdState): MenuItem[] {
  return MENU_IDS.flatMap((id) => menuOf(id, s)).filter((e): e is MenuItem => !('sep' in e))
}

/**
 * Пункт, чью клавишу нажали. ⛔ `key:*` (Ctrl+Z/Y/X/C/V/A) страница не
 * перехватывает НИКОГДА: в поле это родные команды WebView2, и меню их только
 * подписывает.
 */
export function itemForAccel(accel: string, s: CmdState): MenuItem | null {
  return allItems(s).find((i) => i.accel === accel && !i.id.startsWith('key:')) ?? null
}

/**
 * Нажатие → строка ускорителя того же синтаксиса, что у пунктов.
 * ⭐ Буквы и цифры — по ФИЗИЧЕСКОЙ клавише (`code`): при русской раскладке
 * Ctrl+N даёт `key === 'т'`, а клиники в Молдове работают и в ней.
 * ⚠️ AltGr румынской раскладки Windows присылает как Ctrl+Alt — такие
 * сочетания ни с одним пунктом не совпадут, и набор букв не пострадает.
 */
export function accelOf(e: KeyboardEvent): string | null {
  const k = keyName(e)
  if (!k) return null
  const mods: string[] = []
  if (e.ctrlKey || e.metaKey) mods.push('Ctrl')
  if (e.altKey) mods.push('Alt')
  /* «+» на американской раскладке — это Shift+=: масштаб от Shift не зависит */
  if (e.shiftKey && k !== '=' && k !== '-') mods.push('Shift')
  return [...mods, k].join('+')
}

function keyName(e: KeyboardEvent): string | null {
  const c = e.code
  if (/^Key[A-Z]$/.test(c)) return c.slice(3)
  if (/^Digit[0-9]$/.test(c)) return c.slice(5)
  /* цифры правого блока — только при включённом NumLock: без него та же
     клавиша — End/Home, и Ctrl+End не должен открывать раздел */
  if (/^Numpad[0-9]$/.test(c)) return /^[0-9]$/.test(e.key) ? c.slice(6) : null
  if (c === 'Equal' || c === 'NumpadAdd') return '='
  if (c === 'Minus' || c === 'NumpadSubtract') return '-'
  if (/^F([1-9]|1[0-2])$/.test(c)) return c
  if (c === 'ArrowLeft') return 'Left'
  if (c === 'ArrowRight') return 'Right'
  return null
}

/** День журнала — общий или врача: там у «Programare nouă» своё окно (`#addform`). */
export function isJournalDay(pathname: string): boolean {
  return pathname === '/admin/all' || pathname.startsWith('/admin/doctor/')
}

/**
 * Адрес ссылки «Programare nouă» (06.10): на дне журнала (общем или врача) —
 * окно записи на ЭТОМ дне и у этого врача; с любой другой страницы — сегодня.
 * ⚠️ С 22.10 вне дня журнала по этому адресу НЕ ходят: простой щелчок, Ctrl+N
 * и пункт меню открывают окно оболочки на месте (`AppShell` › `Topbar`), а
 * адрес остаётся ссылкой для Ctrl+щелчка.
 */
export function newApptHref(pathname: string, search: string, today: string): string {
  return isJournalDay(pathname) ? `${pathname}${search}#addform` : `/admin/all?date=${today}#addform`
}

/**
 * Адрес `go:` — только путь ЭТОЙ программы. `dpRun` зовёт оболочка, но
 * функция висит на `window`, и чужой адрес (`//host`, `javascript:`) она
 * открывать не должна.
 */
export function safePath(p: string): boolean {
  return /^\/(?!\/)[^\s\\]*$/.test(p)
}
