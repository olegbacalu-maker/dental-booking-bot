/**
 * Модель оболочки — то, что сервер кладёт в узел монтирования атрибутом
 * `data-shell` (B1, контракт в docs/dentpilot-2/b1-contract.md).
 *
 * ⛔ Права приезжают РАЗРЕШЁННЫМИ (`can.money`), а не таблицей `PERMS`.
 * Скрытый пункт меню — удобство, а не защита: отказ по-прежнему выдаёт
 * `require()` в самом маршруте, и роль читается из файла по id при каждом
 * запросе, чтобы понижение действовало немедленно. Оболочка на этой модели
 * НЕ становится границей безопасности.
 *
 * ⚠️ Поля `html` у сигналов и `mark` у клиники — серверная проза, как у
 * `lan.py` и `crypt.py`: доказуемо значением здесь УСЛОВИЕ (`shown`), а не
 * формулировка. Второй экземпляр этих текстов в TSX разошёлся бы с первым.
 */

export interface NavItem {
  key: string
  /** Пустая строка — строка без ссылки: так «Telegram Bot» остаётся у того, кому настройки закрыты. */
  href: string
  icon: string
  label: string
  /** Индикатор «бот жив» у пункта Telegram: ok | off. */
  dot?: 'ok' | 'off'
}

export interface Signal {
  shown: boolean
  /** Готовая разметка баннера с сервера; пусто, когда `shown` ложно. */
  html: string
}

export interface ShellModel {
  identity: {
    name: string
    role: string
    role_label: string
    initials: string
    can: { money: boolean; settings: boolean; doctors: boolean }
  } | null
  clinic: { name: string; mark: string; logo_topbar: string }
  runtime: { version: string; tz: string }
  nav: { active: string; items: NavItem[]; sync: NavItem[]; foot_title: string }
  signals: { license: Signal; tamper: Signal; split: Signal; slot: Signal; setup: Signal }
  frame: {
    /** Заголовок страницы — имя РАЗДЕЛА (B5, шаг 10): «Pacienți», «Setări».
     *  Считает сервер по активному пункту меню; до 26.09 здесь стояло
     *  постоянное «Registrul Clinicii». */
    title: string
    sub: string
    /**
     * Навигация раздела — сегодня её печатает `_sec_page`, одну и ту же на всех
     * страницах настроек. Пустой список значит «у этого раздела крошки нет».
     * ⚠️ Форма та же, что у `nav.items`, и это не совпадение: обе — навигация
     * каркаса, и держать их разными структурами значило бы завести две формы
     * одного понятия.
     */
    crumbs: NavItem[]
    rail: boolean
    bell: number | null
    sec_warn: string
    /** Строка обновления в шапке, HTML сервера; пусто, когда обновляться нечем. */
    update: string
    /** Плашка ответа после 303 с `?msg=`. */
    msg: string
    feedback: { email: string; href: string }
    today: string
  }
}

/**
 * Модель со страницы. `null` — сервер её не положил, значит это ещё страница
 * со старой оболочкой: экран рисуется один, без каркаса.
 */
export function readShell(host: HTMLElement): ShellModel | null {
  const raw = host.dataset.shell
  if (!raw) return null
  try {
    return JSON.parse(raw) as ShellModel
  } catch {
    /* ⚠️ Молча не глотаем: без модели каркаса не будет вовсе, и пустой экран
       без единой строки в консоли — худший из возможных исходов. */
    console.error('DentPilot: data-shell не разбирается', raw.slice(0, 200))
    return null
  }
}
