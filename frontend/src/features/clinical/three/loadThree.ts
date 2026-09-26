import type * as THREE from 'three'

/* three.js — по требованию (B7, ступень 2; решение 3 — вариант B): бандл его не
   содержит, файл лежит рядом с бандлом (`/static/js/three.js`, копия на сборке)
   и грузится один раз на программу, когда врач впервые открывает вид 3D.
   Версия в адресе — та же, что у bundle.js на странице (`layout._asset_ver`):
   кэш three.js живёт и умирает вместе с бандлом. Отказ (нет сети не бывает —
   файл локальный; бывает потерянная копия) отдаётся вызывающему: сцена покажет
   текст, 2D продолжает работать; следующий вызов попробует снова. Типы —
   только типы (`import type`): в бандл three не попадает. */
export type Three = typeof THREE

type Importer = (url: string) => Promise<unknown>

/** Версия статики из адреса бандла на странице; пусто, если бандл не с /static. */
export function assetVer(doc: Document = document): string {
  const s = doc.querySelector<HTMLScriptElement>('script[src*="/static/js/bundle.js"]')
  const m = /[?&]v=([^&]+)/.exec(s?.getAttribute('src') ?? '')
  return m?.[1] ?? ''
}

export function threeUrl(ver: string = assetVer()): string {
  return `/static/js/three.js${ver ? `?v=${encodeURIComponent(ver)}` : ''}`
}

let pending: Promise<Three> | null = null

const realImport: Importer = (url) => import(/* @vite-ignore */ url)

/** Один промис на программу; после отказа — снова попытка при следующем вызове. */
export function loadThree(importer: Importer = realImport): Promise<Three> {
  if (!pending) {
    pending = importer(threeUrl()).then(
      (m) => m as Three,
      (e: unknown) => { pending = null; throw e },
    )
  }
  return pending
}

/** Только для тестов: забыть загруженное. */
export function resetThree(): void { pending = null }
