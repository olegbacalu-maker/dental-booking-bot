import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))

// Сборка кладёт результат ПРЯМО в каталог статики движка, а не в свой dist/.
// Так его подхватывает уже существующий --add-data в Build-Desktop.ps1
// ("bot\app\static;app\static") и ничего в сборщике exe менять не надо.
const ENGINE_STATIC = resolve(HERE, '../bot/app/static')

// Порт песочницы из scripts/dev.py (`dev up`). ⛔ НЕ 8088: там установленная
// программа с настоящей картотекой клиники.
const DEV_ENGINE = 'http://127.0.0.1:8099'

/**
 * ⛔ Имена файлов сборки НЕ хешируются, и это не забывчивость.
 *
 * Статику отдаёт маршрут /static/{kind}/{name} (bot/app/main.py:273), и он
 * пропускает только имя по шаблону `[a-z0-9_-]+\.{kind}` из папок css, js и
 * fonts, без вложенности. Обычное имя Vite вида `index-D4f2Ab9c.js` содержит
 * заглавные буквы и получит 404 — то есть страница откроется пустой, без
 * единой ошибки в логе сервера.
 *
 * Версионирование кеша при этом не теряется: адрес несёт `?v=` из
 * layout._asset_ver(), и после обновления программы браузер запросит файл
 * заново.
 */
const ASSET_RULE = /^[a-z0-9_-]+$/

export default defineConfig({
  plugins: [react()],

  // Тесты компонентов: jsdom вместо браузера, только src/**/*.test.{ts,tsx}.
  // Подмена движка в них — фикстуры ТОЛЬКО тестов (§26): бандл ничего из
  // этого не видит, входная точка сборки — main.tsx.
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },

  build: {
    outDir: ENGINE_STATIC,
    // ⛔ Каталог НЕ чистить: рядом лежат panel.css, panel.js, index.html и
    // четыре шрифта — всё это к сборке фронта отношения не имеет.
    emptyOutDir: false,
    // ⛔ Карта кода выключена не из скрытности, а потому что она бесполезна:
    // имя `bundle.js.map` содержит две точки и шаблон маршрута
    // `[a-z0-9_-]+\.js` его не пропускает — браузер получит 404. При этом
    // файл весит около мегабайта и уехал бы внутрь exe через --add-data.
    // Нужна отладка у клиники — собирать точечно с DP_SOURCEMAP=1.
    sourcemap: process.env.DP_SOURCEMAP === '1',
    rollupOptions: {
      // Входная точка — модуль, а НЕ index.html: иначе Vite положил бы свой
      // index.html в bot/app/static/ поверх лендинга бота, который там уже
      // живёт. index.html в этой папке нужен только `vite dev`.
      input: resolve(HERE, 'src/main.tsx'),
      output: {
        // Ни разбиения на чанки, ни ленивых кусков: каждый лишний файл — это
        // ещё одно имя, которое обязано пройти шаблон маршрута выше.
        inlineDynamicImports: true,
        entryFileNames: 'js/bundle.js',
        assetFileNames(info) {
          const name = info.names?.[0] ?? (info as { name?: string }).name ?? ''
          if (name.endsWith('.css')) return 'css/bundle.css'
          throw new Error(
            `Файл «${name}» не переживёт маршрут /static/{kind}/{name}: ` +
            'он пропускает только css, js и fonts с именем ' +
            `${ASSET_RULE} и без вложенных папок. Не импортируй двоичную ` +
            'статику из React — шрифты уже отдаёт движок.',
          )
        },
      },
    },
  },

  server: {
    // Разработка идёт через прокси на песочницу, чтобы origin у браузера был
    // ОДИН. Тогда кука admin_auth (samesite=lax) доходит, а same_origin_post
    // не отвергает POST — ровно те два условия, на которых держится вход.
    proxy: Object.fromEntries(
      ['/api', '/admin', '/static', '/health', '/clinic-logo'].map((p) => [
        p,
        { target: DEV_ENGINE, changeOrigin: false },
      ]),
    ),
  },
})
