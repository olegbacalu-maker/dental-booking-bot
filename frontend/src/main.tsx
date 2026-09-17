/**
 * Точка входа React-клиента.
 *
 * Монтируется В СУЩЕСТВУЮЩУЮ страницу движка: серверный core/layout._shell
 * рисует сайдбар, верхнюю панель, тему и шрифты, а сюда отдаёт один узел
 *   <div id="root" data-screen="имя-экрана"></div>
 * Какой экран показывать, решает СЕРВЕР через data-screen — это тот же
 * рубильник, что и флаг в clinic.json (§29): включение экрана не требует
 * пересборки, потому что оба интерфейса лежат в одном бинарнике.
 *
 * ⛔ Сайдбар и шапку здесь не дублировать. Тема, иконки и тексты сообщений —
 * серверные (§7), React их потребляет.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import './app/app.css'

const host = document.getElementById('root')

if (!host) {
  // Экран, который сервер ещё не отдал React, — это норма, а не поломка:
  // большинство страниц пока рисует Python. Молча выходим.
  console.debug('DentPilot: #root отсутствует — страница серверная')
} else {
  const screen = host.dataset.screen ?? 'unknown'
  // Параметры экрана (id врача и т. п.) сервер кладёт в data-params JSON-ом.
  let params: Record<string, string> = {}
  try {
    params = JSON.parse(host.dataset.params ?? '{}') as Record<string, string>
  } catch {
    console.error('DentPilot: data-params не разбирается', host.dataset.params)
  }
  // Внутри узла сервер оставил заглушку «интерфейс не загрузился» со
  // ссылкой на старую страницу (layout.react_mount). Раз мы здесь — бандл
  // загрузился; заглушку убираем сами, чтобы React монтировался в пустой узел.
  host.replaceChildren()
  createRoot(host).render(
    <StrictMode>
      <App screen={screen} params={params} />
    </StrictMode>,
  )
}
