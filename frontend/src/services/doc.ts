import { assetsOf, readHead, readNode, type MountNode } from '../app/doc'

/**
 * Документ адреса для перехода без перезагрузки (B4 перехода к SPA).
 *
 * ⭐ Оболочку нового адреса сервер уже умеет посчитать — он делает это на
 * каждой полной загрузке, внутри маршрута страницы. Здесь берётся ТОТ ЖЕ
 * ответ, что получил бы F5, и из него читается узел: второй модели оболочки,
 * второй таблицы «адрес → пункт меню» и ни одной строки бэкенда ради роутера.
 *
 * ⛔ Всё, кроме «React-страница того же бандла», — уход ДОКУМЕНТОМ: сегодня
 * документом идёт каждый переход, поэтому хуже, чем сегодня, не станет.
 */

export type DocAnswer =
  /** Страница React того же бандла: переходим без перезагрузки. */
  | { kind: 'page'; node: MountNode }
  /** Решает не клиент: открыть адрес документом (сервер увёл, старая страница,
   *  другой код, движок не ответил). */
  | { kind: 'leave'; url: string }

export async function fetchDoc(url: string, signal: AbortSignal, here: Document = document): Promise<DocAnswer> {
  try {
    const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal })
    // Редирект сервера — вход (`_guard`), отказ в праве (`require` → `no_access`),
    // исчезнувшая фиша. Идём туда, куда увёл он, и так же, как увёл бы F5.
    if (res.redirected) return { kind: 'leave', url: res.url }
    if (!res.ok) return { kind: 'leave', url }
    const doc = new DOMParser().parseFromString(await res.text(), 'text/html')
    const host = doc.getElementById('root')
    // Узла нет — по адресу старая страница (`ui.react`, `?ui=legacy`) или не
    // экран вовсе. Модели нет — оболочку печатает сервер. Обе рисует документ.
    if (!host?.dataset.shell) return { kind: 'leave', url }
    // ⛔ Другой код: вклеить новую модель в старый бандл нельзя.
    if (assetsOf(doc) !== assetsOf(here)) return { kind: 'leave', url }
    const node = readNode(host)
    if (!node.shell) return { kind: 'leave', url }
    return { kind: 'page', node: { ...node, head: readHead(doc) } }
  } catch (e) {
    // ⚠️ Переход перебит следующим — ответ роутер выбросит сам. Уйти здесь
    // документом значило бы увести человека с того, куда он нажал ПОСЛЕДНИМ.
    if (signal.aborted) throw e
    // Движок не ответил: пусть окно покажет то же, что показало бы сегодня.
    return { kind: 'leave', url }
  }
}
