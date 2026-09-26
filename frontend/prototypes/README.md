# `prototypes/` — технические прототипы клиента

Каталог для проверки технологий ДО того, как они попадут в программу.
Здесь лежит код, который ещё ничего не доказал.

## Почему не в `src/`

Всё в этой папке намеренно лежит **вне `src/`**, и это не вкусовщина —
три существующих конфига считают `src` своей границей:

| Конфиг | Что смотрит | Следствие для `prototypes/` |
|---|---|---|
| `tsconfig.app.json` | `"include": ["src"]` | `npm run typecheck` и `tsc -b` в `npm run build` прототип **не видят** |
| `vite.config.ts` → `test.include` | `src/**/*.test.{ts,tsx}` | `npm test` прототип **не запускает** |
| `vite.config.ts` → `rollupOptions.input` | `src/main.tsx` | прототип **не попадает** в `bot/app/static/js/bundle.js` |

Последняя строка — главная. Сборка клиента даёт ОДИН неразрезанный бандл
(`inlineDynamicImports: true`), который едет внутрь exe клиники. Если бы
прототип с three.js лежал в `src/` и был хоть откуда-то импортирован, он
добавил бы к бандлу около 200 КБ (gzip) на каждом компьютере каждой клиники —
за технологию, которую ещё не решили применять.

Проверить это можно в любой момент:

```powershell
npm run build
# и посмотреть размер bot\app\static\js\bundle.js — он не меняется
```

## Как запускать

```powershell
npm run dev:dental3d     # откроет /prototypes/dental3d/index.html
```

Или вручную: `npm run dev` и адрес
`http://localhost:5173/prototypes/dental3d/index.html`.

Второй прототип — одонтограмма: раскладки 2D и вид 2D/3D, HTML без сборки:

```powershell
npm run dev:odontogram                               # /prototypes/odontogram/index.html — три раскладки 2D
npm run dev:odontogram3d                             # /prototypes/odontogram/3d.html — обе челюсти в 3D + карта 2D
python ..\frontend\prototypes\odontogram\gen.py       # пересобрать index.html из bot/app/teeth_svg.py
python ..\frontend\prototypes\odontogram\gen.py --3d  # пересобрать 3d.html (three.js грузится с cdn.jsdelivr.net)
```

Типы прототипов проверяются отдельной командой — у них свой `tsconfig.json`,
не подключённый к сборке:

```powershell
npm run typecheck:dental3d
```

## Правила каталога

1. Прототип **не импортирует** ничего из `src/` и **не импортируется** оттуда.
   Как только понадобится общий код — это сигнал, что прототип пора выносить
   в `src/` как обычный экран, а папку чистить.
2. Прототип **не ходит в API** и ничего не сохраняет.
3. Прототип не считается частью программы: его можно удалить одним `rm -r`,
   и единственный след — две строки в `devDependencies` (`three`,
   `@types/three`) и скрипты в `package.json` (`dev:dental3d`,
   `typecheck:dental3d`, `dev:odontogram`, `dev:odontogram3d`).
