import { readShell, type ShellModel } from '../layouts/shell'

/**
 * Документ адреса — то, что сервер отдаёт по нему при полной загрузке.
 *
 * С B4 перехода к SPA документ читается дважды: при загрузке окна (узел
 * монтирования этой страницы) и при переходе без перезагрузки (узел документа
 * НОВОГО адреса, `services/doc.ts`). Разбор один на оба случая: два разборщика
 * одного атрибута разошлись бы молча, и переход показал бы не то, что F5.
 * Решение и правила — docs/dentpilot-2/spa-transition.md › «B4».
 */

/** Голова документа: то, что оболочка сама не рисует, но от адреса зависит. */
export interface DocHead {
  title: string
  /** `<html data-style>` — стиль темы. */
  style: string
  /** `<meta name="theme-color">` — цвет полосы окна. */
  themeColor: string
  /** `<style>` темы: переменные `:root`, посчитанные сервером. */
  themeCss: string
}

/** Что сервер положил в узел монтирования. */
export interface MountNode {
  /** `data-screen`: какой экран сервер отдал по ЭТОМУ адресу. */
  screen: string
  /** `data-params`: параметры экрана, посчитанные сервером (дата по умолчанию и т. п.). */
  params: Record<string, string>
  /** `data-shell`: модель оболочки (B1); `null` — каркас печатает сервер. */
  shell: ShellModel | null
  /** Голова документа — только у узла, прочитанного ПЕРЕХОДОМ: первый кадр
   *  свою голову уже нарисовал. */
  head?: DocHead
}

export function readNode(host: HTMLElement): MountNode {
  // Параметры экрана (id врача и т. п.) сервер кладёт в data-params JSON-ом.
  let params: Record<string, string> = {}
  try {
    params = JSON.parse(host.dataset.params ?? '{}') as Record<string, string>
  } catch {
    console.error('DentPilot: data-params не разбирается', host.dataset.params)
  }
  return { screen: host.dataset.screen ?? 'unknown', params, shell: readShell(host) }
}

export function readHead(doc: Document): DocHead {
  return {
    title: doc.title,
    style: doc.documentElement.dataset.style ?? '',
    themeColor: doc.querySelector('meta[name="theme-color"]')?.getAttribute('content') ?? '',
    themeCss: doc.head.querySelector('style')?.textContent ?? '',
  }
}

/**
 * Поставить голову нового адреса в окно. ⚠️ Тема меняется не только
 * переездом: её сохраняют в настройках, и документ соседнего адреса уже несёт
 * новую, а голова окна — ту, с которой вкладку открыли.
 */
export function applyHead(h: DocHead, doc: Document = document): void {
  if (doc.title !== h.title) doc.title = h.title
  if (h.style && doc.documentElement.dataset.style !== h.style) doc.documentElement.dataset.style = h.style
  const meta = doc.querySelector('meta[name="theme-color"]')
  if (meta && h.themeColor && meta.getAttribute('content') !== h.themeColor) {
    meta.setAttribute('content', h.themeColor)
  }
  const css = doc.head.querySelector('style')
  if (css && css.textContent !== h.themeCss) css.textContent = h.themeCss
}

/**
 * Чем документ собран: адреса стилей и скриптов вместе с `?v=`. Разошлись у
 * двух документов — у них разный код (exe обновили, бандл пересобрали), и
 * новый адрес обязан открыться документом, иначе старый бандл жил бы до F5.
 */
export function assetsOf(doc: Document): string {
  return [...doc.querySelectorAll('link[rel="stylesheet"][href], script[src]')]
    .map((e) => e.getAttribute('href') ?? e.getAttribute('src'))
    .join(' ')
}
