# Одонтограмма 2D/3D — перенос из прототипа в программу (C‑3D)

✅ **Решения приняты Олегом 26.09.2026** (раздел 1, его слова при каждом
пункте). План писался до B6 (фиша во вкладках, один рабочий стол
одонтограммы на странице и во вкладке — `patient-workspace.md`), точки
интеграции ниже уже поправлены под него. Что уже есть:

- макет — `frontend/prototypes/odontogram/3d.html` (генератор `gen.py`, в нём
  блок `JS3D` со всей геометрией, раскладкой, сценой и анимациями), артефакт
  https://claude.ai/artifact/WW7eW52s8bxBdJvvxrMaF4;
- доказанная технология — `frontend/prototypes/dental3d/` (один зуб, пять
  поверхностей, пикинг, кадры по требованию, жизненный цикл React);
- контракт клинического модуля — [clinical-chart.md](clinical-chart.md):
  сервер владеет клинической истиной и геометрией, React — композицией и
  интерактивом.

Порядок тот же, что у C21–C23: пины → сервер → чистые модули с Vitest →
компонент → интеграция → кадры. Коммиты раздельные, по ступеням.

## 1. Решения до начала (Олег)

1. **Где показываем 3D.** Решение («первый пункт на странице и во вкладке»):
   третий вид «3D» рядом с «Vedere frontală / ocluzală» в `OdontogramWorkbench`
   — то есть и на детальной `/admin/patient/:pid/odontograma`, и во вкладке
   Odontogramă фиши. После B6 компактной карточки нет, инструмент один; первый
   кадр вкладки остаётся 2D — three.js грузится только при выборе вида.
   Печать 043/e, лист пародонтограммы и выгрузка не меняются.
2. **Поправка к контракту.** В clinical-chart.md стоит ⛔ «второго движка
   геометрии на TypeScript не будет» — это про SVG зуба, который едет в
   печать и выгрузку. 3D‑сетка — не клиническая истина, а рендер той же
   модели: размеры зуба (мезио‑дистальный, вестибуло‑язычный, число корней)
   отдаёт сервер из `teeth_svg`, состояния и цвета — та же модель API. В
   печать, 043/e и выгрузку 3D не попадает никогда. Решение: принято («хорошо
   понятно»); абзац в clinical-chart.md внесён 26.09 с оговоркой: ни одна
   клиническая величина на клиенте не считается — размеры и цвета с сервера.
3. **Как везём three.js** (ESM-минификат `three.module.min.js` в
   `node_modules` — ≈ 340 КБ, не 650). Решение: вариант B («отдельный файл по
   требованию»). *Вариант B:* отдельный файл `bot/app/static/js/three.js`,
   который клиент грузит динамическим `import()` только при открытии вида
   3D; `bundle.js` не растёт, остальные экраны ничего не платят.
   *Вариант A:* в бандл (проще на одну ступень, но +≈400 КБ после
   tree‑shaking на каждой странице программы).
4. **Дуга 2D подковой и схема MODVL** из макета — отдельные этапы, с 3D не
   смешивать. Дуга — композиция серверного SVG в клиенте (поворот и
   расстановка готовых рисунков, контракт это разрешает). Схема — рисует
   сервер (`teeth_svg.schema_svg`), иначе она не попадёт в печать. Решение: да.
5. **Анимации.** Правило дизайн‑системы Dental3D: ничего не движется само.
   Оставить из макета: переезд камеры между видами, выезд скрытой челюсти,
   смыкание, плавную смену цвета поверхности и сцены смены состояния
   (имплант вкручивается, удалённый выходит из лунки, отсутствующий тает,
   коронка садится). Авто‑вращение — только по кнопке. При
   `prefers-reduced-motion` всё мгновенно. Решение: да.
6. **Молочный ряд** в 3D первой версии не показываем (в макете его тоже
   нет); молочные остаются в 2D. Решение: да («разумно»). ⚠️ В виде 3D у
   пациента с открытым молочным рядом — надпись «Dinții de lapte — în 2D»,
   иначе они пропадут молча.

## 2. Формула

| Что | Где | Почему |
|---|---|---|
| Размеры зуба для 3D: `md`, `bl` в мм, число корней, класс, челюсть | сервер, `odontogram.model()` → `teeth[n].geom`, считает `teeth_svg.tooth_geom()` из `occ_half`, `root_count`, `tooth_class`, `is_upper` | один источник; таблица ширин в TS была бы вторым движком |
| Цвета состояний | сервер, `model.palette` из `teeth_svg.COLORS` | легенда, 2D и 3D красят одним цветом |
| Форма коронки, корней, винта, десны; раскладка по дуге; камера | клиент, `src/features/clinical/three/` | рендер, не истина (решение 2) |
| Состояния, поверхности, отметки, мосты | та же модель `Odontogram` (`ToothInfo.state`, `sfst`, `mk`, `bridge`) | второго словаря нет |
| Действия из 3D | те же `useChart`: `select(n)`, `pickSurface(n, letter)`, `setState`; правая кнопка — тот же `ToothMenu` | 3D — ещё один вход в ту же модель, как цели `data-s` в SVG |
| three.js | `/static/js/three.js?v=…` по требованию (вариант B) | маршрут `/static/{kind}/{name}` уже пускает `[a-z0-9_-]+\.js` |

## 3. Ступени

### Ступень 1 — сервер: размеры и палитра в модели

- `bot/app/teeth_svg.py`: константа `MM_PER_UNIT = 10.5 / 36.3` (моляр
  10,5 мм = 36,3 единицы вида сверху — та же пропорция, на которой стоят все
  ширины движка) и функция `tooth_geom(fdi) -> dict(md, bl, roots, cls,
  upper)` в миллиметрах. Высота коронки и длина корней — таблицы по классам
  из макета (`CROWN_H`, `ROOT_L` в `gen.py`), тоже сюда: сервер владеет
  размерами целиком.
- `bot/app/modules/patients/odontogram.py`, `model()`: `"geom":
  tsvg.tooth_geom(n)` рядом с `"svg"`; `"palette": dict(tsvg.COLORS)` рядом с
  `"states"`.
- `frontend/src/features/clinical/chart.ts`: `ToothInfo.geom` и
  `Odontogram.palette` в типах.
- Тесты: `tests/test_teeth.py`, новый набор `suite_geom`: 16 → `md` 10.5,
  `bl` 11.0, `roots` 3; 14 → `roots` 2; 41 → `roots` 1 и `md` < `md` у 11;
  молочный 55 → `roots` 3 (у молочных моляров тоже три); `GET
  /api/patients/{pid}/odontogram` отдаёт `geom` у всех 52 зубов и `palette` с
  семью ключами (`test_odontogram_api`).
- ⚠️ Старые страницы и печать это поле не читают и не меняются.

### Ступень 2 — three.js в сборке (вариант B)

- `frontend/vite.config.ts`: плагин с хуком `closeBundle`, который копирует
  `node_modules/three/build/three.module.min.js` в
  `bot/app/static/js/three.js`. ⛔ Не через `assetFileNames` — он бросает на
  любом ассете кроме css, и это правильно; копия — просто файл рядом с
  `bundle.js`. Имя обязано пройти шаблон маршрута `[a-z0-9_-]+\.js`.
- `.gitignore`: `bot/app/static/js/three.js` — артефакт сборки, как
  `bundle.js`.
- `Build-Desktop.ps1`: проверка `Test-Path bot\app\static\js\three.js` рядом
  с `BUNDLE MISSING` — иначе exe с чистого клона уедет без 3D, и увидит это
  только клиника. И `tests/smoke_exe.py`: `/static/js/three.js` отдаётся из
  СОБРАННОЙ программы (рядом с проверкой `bundle.js`) — сборка проверяет
  исходник, дымовой тест — то, что уехало в exe.
- `frontend/src/features/clinical/three/loadThree.ts`: один промис на
  программу, `import(/* @vite-ignore */ '/static/js/three.js?v=' + ver)`,
  где `ver` — параметр `v` из адреса `bundle.js` в `<script>` страницы (его
  печатает `layout._asset_ver`; так кэш three.js живёт и умирает вместе с
  бандлом). Отказ → сцена показывает текст «3D nu s-a încărcat», 2D
  работает. Типы — `import type * as THREE from 'three'`, объект — из
  промиса.
- Орбита: `OrbitControls` лежит в `three/addons`, которых в одном файле нет.
  Либо своя орбита (в `gen.py` она 60 строк: перетаскивание, колёсико,
  щипок, пресеты), либо собирать `three + OrbitControls` в один файл своим
  скриптом esbuild. Предложение: своя — меньше движущихся частей.
- Vitest: `loadThree` мокается (jsdom без WebGL).

### Ступень 3 — чистые модули без React и без WebGL

Каталог `frontend/src/features/clinical/three/`:

- `toothGeometry.ts` — `buildCrown(geom, cls, upper)`, `buildRoots(...)`,
  `buildScrew(r)`: перенос из `gen.py` › `JS3D` (`PROF`, `SQUARE`,
  `reliefFn`, `rootSpecs`) и из `prototypes/dental3d/toothGeometry.ts`
  (сплайн Catmull‑Rom профиля, суперэллипс, секторы поверхностей, общий
  краевой гребень стенки и площадки). Пять групп геометрии в порядке
  `O V L M D` = порядок материалов = `face.materialIndex → буква`.
- `arch.ts` — парабола дуги, расстановка по длине дуги (сумма ширин зубов
  растягивает дугу), базис `(дистально, окклюзионно, щёчно)` → матрица
  группы зуба; десна `buildRidge`. ⭐ Правило, которое ломается молча:
  отражаются квадранты 2 и 4 (определитель базиса < 0), мезиальная сторона
  всегда к средней линии. В панораме 2D отражаются 2 и 3, потому что там
  нижний ряд переворачивается по вертикали, — в 3D это не так.
- `look.ts` — `targetLook(info: ToothInfo, palette, bridgeRole)`: что видно
  (коронка / корни / винт / лунка / кольца) и цвет каждой поверхности.
  Имплант: винт виден всегда — полупрозрачная копия поверх десны с
  фиолетовым свечением состояния, кольцо у шейки, керамическая коронка
  светлее эмали.
- `tween.ts` — твины и сцены смены состояния (`applyLook`,
  `animateStruct` из макета); при `prefers-reduced-motion` — мгновенно.
- Vitest, всё чисто вычислимое: у каждого класса и челюсти коронка даёт
  ровно пять групп с треугольниками; у 11/21/41/31 мезиальная сторона
  смотрит к `x = 0`, отрицательный определитель только у квадрантов 2 и 4;
  сумма ширин равна длине дуги; таблица состояний → видимость и цвета
  (имплант: винт есть, корней нет; тело моста: золото, корней нет; lipsă:
  призрак 0,22; extras: лунка); reduced‑motion → твин завершается сразу.

### Ступень 4 — сцена и компонент

- `scene.ts` — из `prototypes/dental3d/scene.ts`: рендерер, свет, кадры
  только по требованию (`invalidate`), DPR ≤ 2, `setSize(w, h, false)`,
  `dispose` с `forceContextLoss`. Обобщить: 32 зуба в `Map<n, ToothNodes>`,
  две группы челюстей, десна, пресеты камеры (Frontal, Ocluzal sus/jos —
  окклюзионный вид прячет другую челюсть, Dreapta, Stânga), переключатели
  Rădăcini / Numere / Maxilar / Mandibular / Ocluzie / Rotire. Пикинг:
  `intersectObjects(коронки)` → `{n, letter}`; клик отличается от
  перетаскивания порогом 4 px; наведение не чаще одного кадра.
- `Odontogram3D.tsx` — как `Dental3DViewer.tsx`: props `{ model, selected,
  dirty, onSelect, onSurface, onMenu }`; обновления императивные —
  `useEffect` по `model.teeth` зовёт `paint(targetLook)`, по `selected` —
  кольцо. ⛔ Дерево React статично, движение мыши не вызывает reconciliation
  (правило README прототипа).
- Оформление в `panel.css`, не в компоненте: `.odo-stage` фиксированной
  высоты (520 px, 400 px уже 880 px), `contain: paint`, без `transition`,
  фон `--panel`; сегмент видов — тот же `.viewsw`. Тема клиники (`core/
  theme.py`) красит только рамку: зуб — материал, а не интерфейс.

### Ступень 5 — интеграция в экран

- `chart.ts`: `export type View = 'frontal' | 'ocluzal' | '3d'`;
  `savedView()` принимает `'3d'`, ключ `dp_odo_view` тот же.
- `ViewSwitch.tsx`: третья кнопка `data-v="3d"`, подпись «3D».
- `OdontogramWorkbench.tsx` (один на страницу и вкладку, B6): при
  `c.view === '3d'` в `.odop-main` вместо `<DentalArch>` рендерится
  `<Odontogram3D>` с теми же `onSelect`, `onSurface`, `onMenu`; инспектор,
  контекстное меню, режим моста и клавиатура не меняются (стрелки →
  `c.select`, подсветка в 3D через `selected`). `focusTooth` для 3D
  фокусирует canvas. Молочный ряд открыт → надпись из решения 6.
- `OdontogramTab.tsx`: ничего особого — тот же рабочий стол; сохранённый вид
  `'3d'` применяется и во вкладке, three.js едет по требованию.
- Тесты: `OdontogramScreen.test.tsx` — существующий сценарий «Vedere
  ocluzală» остаётся; новый: кнопка 3D ставит `data-view="3d"`, при
  замоканном `loadThree` сцена показывает текст отказа, а 2D‑инспектор жив;
  `PatientCardScreen.test.tsx` — вкладка Odontogramă с сохранённым видом 3d
  при замоканном `loadThree` не ломает фишу.
- Кадры headless Edge (как в C22, migration.md › этап 10): frontal;
  ocluzal sus и jos со скрытой челюстью; dreapta + Rădăcini; Ocluzie;
  выбранный зуб; после смены состояния; узкое окно; тёмный стиль.

### Ступень 6 — анимации

По решению 5: перенос `tween.ts` и сцен смены состояния; кадры идут только
пока идёт твин, в покое ноль кадров — проверить счётчиком кадров, как это
делал прототип dental3d (README › «кадров в покое — ноль»).

### Ступень 7 — уборка и документы

- `frontend/prototypes/dental3d` и `frontend/prototypes/odontogram` —
  удалить, когда их код переехал (правило `prototypes/README.md`: как
  только код общий, прототип выносят и папку чистят). `gen.py` можно оставить
  как генератор макетов, если он ещё нужен для показа.
- `three` в `package.json`: при варианте B остаётся в `devDependencies`
  (в бандл не входит, копия делается на сборке).
- `migration.md` — разбор этапа; `clinical-chart.md` — поправка по решению
  2 и строка о 3D в «чего нет намеренно»; `README.md` — абзац.

## 4. Точки интеграции

| Файл | Что меняется |
|---|---|
| `bot/app/teeth_svg.py` | `MM_PER_UNIT`, `tooth_geom()`, таблицы высот коронок и длин корней |
| `bot/app/modules/patients/odontogram.py` › `model()` | `teeth[n].geom`, `palette` |
| `tests/test_teeth.py`, `tests/test_odontogram_api.py` | пины размеров и формы ответа |
| `frontend/vite.config.ts`, `.gitignore`, `Build-Desktop.ps1`, `tests/smoke_exe.py` | копия three.js, игнор, проверка сборки и дымовой тест exe |
| `frontend/src/features/clinical/chart.ts` | `View` с `'3d'`, типы `geom`, `palette` |
| `frontend/src/features/clinical/three/*` | новое: `loadThree`, `toothGeometry`, `arch`, `look`, `tween`, `scene`, `Odontogram3D` |
| `frontend/src/features/clinical/ViewSwitch.tsx`, `OdontogramWorkbench.tsx` (+ `OdontogramTab.tsx` без правок) | третий вид |
| `bot/app/static/css/panel.css` | `.odo-stage` и переключатели сцены |
| `frontend/src/features/clinical/OdontogramScreen.test.tsx` + новые `three/*.test.ts` | сценарии выше |

## 5. ⛔ Чего не делать

- Готовые модели зубов (GLB/OBJ) и любые ассеты: `vite.config.ts` бросает на
  любом ассете кроме css, и чужая лицензия в медицинском продукте не нужна.
  Геометрия остаётся процедурной, ноль байт ассетов.
- `@react-three/fiber`, `drei`: конфликт peer‑зависимостей с React 19.3
  (разбор в `prototypes/dental3d/scene.ts`), `npm ci` в CI упал бы до
  typecheck.
- Новые клинические состояния, второй словарь состояний, таблицы размеров
  зубов в TypeScript.
- Постоянный animation loop, `transition` на контейнере сцены, размеры,
  зависящие от hover — мерцание интерфейса в продукте остаётся открытой
  проблемой, и 3D не имеет права добавить новое.
- Печать, 043/e, выгрузка по 195‑му — только из серверного 2D, как сейчас.
- Смешивать с редизайном 2D: дуга подковой и схема MODVL — свои этапы.

## 6. Как проверять

```powershell
cd frontend
npm ci
npm run typecheck
npm test
npm run lint
npm run build            # должен появиться bot\app\static\js\three.js (вариант B)
cd ..
.venv-desktop\Scripts\python.exe tests\run_tests.py   # ступень 1: пины размеров
```

Живой экран — через песочницу (`dev up`, порт 8099) и `npm run dev`:
`http://localhost:5173/admin/patient/<pid>/odontograma`. Кадры headless
Edge — по списку из ступени 5.

## 7. Откуда брать код

- `frontend/prototypes/odontogram/gen.py`, блок `JS3D`: `buildCrown`,
  `buildRoots`, `buildScrew`, `buildRidge`, `curve` и базис зуба,
  `targetLook`, `applyLook`, `animateStruct`, орбита с пресетами и щипком.
- `frontend/prototypes/dental3d/`: `scene.ts` (свет, кадры по требованию,
  dispose), `toothGeometry.ts` (сплайн профиля, суперэллипс, группы),
  `Dental3DViewer.tsx` (жизненный цикл, `ResizeObserver`), README (правила
  производительности и что было проверено).
- Дизайн‑система Dental3D (артефакт, `project/tokens.json`): цвета материалов
  (`enamel-base`, `dentin`), сцены и панели.
