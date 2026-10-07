import { assetVer, loadThree, type Three } from './loadThree'
import type { SculptSet } from './sculpt'

/* Свои модели зубов — по требованию (07.10), тем же путём, что three.js: бандл
   таблиц не содержит (~0,5 МБ чисел вклеились бы в каждую страницу программы),
   файл `/static/js/teeth.js` лежит рядом с бандлом (копия на сборке из
   `frontend/models/teeth.js`, его пишет `scripts/teeth/bake.py`) и грузится один
   раз на программу, когда открывается вид 3D. Версия в адресе — та же, что у
   bundle.js. Отказ отдаётся вызывающему (сцена тогда строит коронки-формулы)
   и не залипает: следующий вызов пробует снова. */

type Importer = (url: string) => Promise<unknown>

export function teethUrl(ver: string = assetVer()): string {
  return `/static/js/teeth.js${ver ? `?v=${encodeURIComponent(ver)}` : ''}`
}

let pending: Promise<SculptSet> | null = null

const realImport: Importer = (url) => import(/* @vite-ignore */ url)

/** Модуль похож на набор моделей: обе таблицы на месте (битая копия — отказ, а не пустая сцена). */
function asSet(m: unknown): SculptSet {
  const s = m as Partial<SculptSet> | null
  if (!s || typeof s.SCULPT !== 'object' || typeof s.SCULPT_OF !== 'object' || !s.SCULPT || !s.SCULPT_OF) {
    throw new Error('teeth.js: нет SCULPT/SCULPT_OF')
  }
  return { SCULPT: s.SCULPT, SCULPT_OF: s.SCULPT_OF }
}

/** Один промис на программу; после отказа — снова попытка при следующем вызове. */
export function loadTeeth(importer: Importer = realImport): Promise<SculptSet> {
  if (pending) return pending
  const p = importer(teethUrl()).then(asSet)
  pending = p
  // и отказ импорта, и битый модуль — забыть, чтобы следующий вызов пробовал снова
  p.catch(() => { if (pending === p) pending = null })
  return p
}

/** Только для тестов: забыть загруженное. */
export function resetTeeth(): void { pending = null }

/** Всё для сцены: без three — отказ (как раньше), без моделей — коронки-формулы.
 *  Модели — ПОСЛЕ three: где three не загрузился (тесты экранов подменяют его
 *  отказом), за файлом моделей не ходим вовсе. */
export function load3d(): Promise<{ THREE: Three; teeth: SculptSet | null }> {
  return loadThree().then((THREE) => loadTeeth().then(
    (teeth) => ({ THREE, teeth }),
    () => ({ THREE, teeth: null }),
  ))
}
