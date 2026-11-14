import { createContext, useCallback, useContext, useState } from 'react'
import { useLoaderData, useRevalidator, useSearchParams, type ShouldRevalidateFunction } from 'react-router'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { SideMenu, type SideItem } from '../../components/SideMenu'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, type LoadState } from '../../hooks/useLoad'
import type { RouteLoad, ScreenData } from '../../hooks/useRouteLoad'
import { roCount } from '../../utils/plural'
import { BuyView } from './BuyView'
import { ConsumView } from './ConsumView'
import { ImportView } from './ImportView'
import { InventoryView } from './InventoryView'
import { InvoiceView } from './InvoiceView'
import { JournalView } from './JournalView'
import { OutDialog } from './OutDialog'
import { RestView } from './RestView'
import { MATERIALE, stockApi, type Filter, type ListData, type StockModel, type View } from './stock'

/* Корень раздела: меню слева (разделы и категории) и раздел справа. Данные — ОДНИМ загрузчиком маршрута
   (`loadStock` в LOADS): список склада и то, что нужно открытому разделу, приходят вместе до первого кадра,
   и экран не дорисовывает блоки после данных. Фильтр, категория и поиск остатков — на клиенте, без загрузки. */

/** Ключи адреса, от которых зависят данные раздела; `f`, `cat`, `q` остатков данных не меняют. */
export const JOURNAL_KEYS = ['item', 'kind', 'from', 'to', 'actor', 'supplier'] as const
const VIEW_KEYS = ['v', 'doc', 'by', ...JOURNAL_KEYS]

const loadModel: RouteLoad<StockModel> = async (signal, _params, q) => {
  const v = q.get('v') ?? ''
  const docId = Number(q.get('doc')) || 0
  const extra: Promise<Partial<StockModel>> =
    (v === 'intrari' || v === 'inventar') && docId > 0 ? stockApi.doc(docId, signal).then((r) => ({ doc: r.data }))
      : v === 'intrari' ? stockApi.docs('factura', signal).then((r) => ({ docs: r.data }))
        : v === 'inventar' ? stockApi.docs('inventar', signal).then((r) => ({ docs: r.data }))
          : v === 'jurnal' ? stockApi.moves(Object.fromEntries(JOURNAL_KEYS.map((k) => [k, q.get(k) ?? ''])), signal).then((r) => ({ moves: r.data }))
            : v === 'cumparat' ? stockApi.buy(signal).then((r) => ({ buy: r.data }))
              : v === 'consum' ? stockApi.report({ by: q.get('by') ?? '', from: q.get('from') ?? '', to: q.get('to') ?? '' }, signal).then((r) => ({ report: r.data }))
              : v === 'import' ? stockApi.importHome(signal).then((r) => ({ imp: r.data }))
                : Promise.resolve({})
  const [list, more] = await Promise.all([stockApi.list(signal), extra])
  return { ...list, data: { list: list.data, ...more } }
}

/** Повтор (`revalidate`) и смена раздела, документа или фильтров журнала — загрузка; фильтр остатков — нет. */
const viewChangeOnly: ShouldRevalidateFunction = ({ currentUrl, nextUrl, defaultShouldRevalidate }) => {
  if (currentUrl.pathname !== nextUrl.pathname || currentUrl.href === nextUrl.href) return defaultShouldRevalidate
  const a = currentUrl.searchParams
  const b = nextUrl.searchParams
  return VIEW_KEYS.some((k) => (a.get(k) ?? '') !== (b.get(k) ?? '')) ? defaultShouldRevalidate : false
}

export const loadStock: ScreenData = { load: loadModel as RouteLoad<unknown>, shouldRevalidate: viewChangeOnly }

interface Ctx {
  say: (text: string, tone?: ToastState['tone'], link?: ToastState['link']) => void
  /** Перечитать модель экрана: меню и открытый раздел. На время повтора на экране остаются прежние данные. */
  refresh: () => void
  list: ListData | null
  navigate: (url: string) => void
  go: (v: View, extra?: Record<string, string>) => void
  out: (item: number) => void
}
export const StockCtx = createContext<Ctx | null>(null)
export function useStockCtx(): Ctx {
  const c = useContext(StockCtx)
  if (!c) throw new Error('StockCtx')
  return c
}

const VIEWS: [View, string, SideItem<string>['icon']][] = [
  ['stoc', 'Stoc', 'box'], ['intrari', 'Intrări (facturi)', 'download'], ['jurnal', 'Mișcări', 'clipboard'],
  ['inventar', 'Inventariere', 'check'], ['cumparat', 'De cumpărat', 'note'], ['consum', 'Consum', 'stat'],
  ['import', 'Import din Excel', 'upload'],
]
const COMANDATE = { one: '1 comandat', few: '{n} comandate', many: '{n} de comandate' }
const isView = (s: string | null): s is View => VIEWS.some(([k]) => k === s)
const isFilter = (s: string | null): s is Filter => s === 'low' || s === 'exp' || s === 'arh'

/** «Stoc» — что и сколько: остатки, intrări după factură, scoateri, mișcări, inventariere, de cumpărat, import. */
export function StockScreen({ navigate = defaultNavigate }: { navigate?: (url: string) => void }) {
  const [q, setQ] = useSearchParams()
  const qv = q.get('v')
  const v: View = isView(qv) ? qv : 'stoc'
  const qf = q.get('f')
  const f: Filter = isFilter(qf) ? qf : 'all'
  const cat = v === 'stoc' ? q.get('cat') ?? '' : ''
  const find = v === 'stoc' ? q.get('q') ?? '' : ''
  const [toast, setToast] = useState<ToastState | null>(null)
  const [out, setOut] = useState<{ item: number; k: number } | null>(null)
  /* не `useRouteLoad`: тот на повторе показывает загрузку, и открытый черновик накладной потерял бы строки */
  const loaded = useLoaderData() as LoadState<StockModel> | undefined
  const { revalidate } = useRevalidator()
  const refresh = useCallback(() => { void revalidate() }, [revalidate])
  const say = useCallback((text: string, tone: ToastState['tone'] = 'ok', link?: ToastState['link']) =>
    setToast(link ? { text, tone, link } : { text, tone }), [])
  const go = useCallback((to: View, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams()
    if (to !== 'stoc') p.set('v', to)
    for (const [k, val] of Object.entries(extra)) if (val) p.set(k, val)
    setQ(p)
  }, [setQ])

  if (loaded?.status === 'leaving') return null
  if (loaded?.status === 'failed') return <section className="dp-react-root"><LoadFailed error={loaded.error} onRetry={refresh} /></section>
  const model = loaded?.status === 'ready' ? loaded.data : null
  const data = model?.list ?? null
  const ctx: Ctx = { say, refresh, list: data, navigate, go, out: (item) => setOut({ item, k: Date.now() }) }

  const cats = catsOf(data)
  const ordered = orderedOf(data)
  const items: SideItem<string>[] = VIEWS.map(([k, label, icon]) => {
    const n = k === 'stoc' ? data?.counts.all : k === 'intrari' ? data?.drafts.factura : k === 'inventar' ? data?.drafts.inventar
      : k === 'cumparat' ? data?.counts.low : undefined
    return { key: k, label, icon, count: n || undefined, tone: k !== 'stoc' ? 'warn' : '',
      hint: k === 'intrari' && data?.drafts.factura ? 'ciorne' : k === 'inventar' && data?.drafts.inventar ? 'ciornă'
        : k === 'cumparat' && ordered ? roCount(ordered, COMANDATE) : undefined }
  })
  if (v === 'stoc' && cats.length > 1) {
    cats.forEach((c, i) => items.push({ key: `c:${c.name}`, label: c.name, icon: 'folder', count: c.count, sep: i === 0,
      tone: c.low ? 'warn' : '', note: c.low ? `${c.name}: ${roCount(c.low, MATERIALE)} sub prag` : c.name }))
  }
  const value = v === 'stoc' && cat ? `c:${cat}` : v
  const pick = (k: string) => {
    if (k.startsWith('c:')) {
      const p = new URLSearchParams(q)
      p.delete('v')
      const name = k.slice(2)
      if (cat === name) p.delete('cat')
      else p.set('cat', name)
      setQ(p, { replace: true })
      return
    }
    go(k as View)
  }
  const title = VIEWS.find(([k]) => k === v)![1]

  return (
    <StockCtx.Provider value={ctx}>
      <section className="dp-react-root rg st" aria-busy={!model || undefined}>
        <SideMenu label="Stoc" items={items} value={value} onPick={pick}>
          <div className="fcard rg-head st-head">
            <b className="st-ttl">{v === 'stoc' && cat ? cat : title}</b>
            <div className="rg-tools">
              <button type="button" className="rg-btn" onClick={() => setOut({ item: 0, k: Date.now() })} disabled={!data?.counts.all}>
                <Icon name="minus" /> Scoate din stoc</button>
              <button type="button" className="rg-btn pri" onClick={() => go('intrari', { doc: 'nou' })}><Icon name="plus" /> Intrare după factură</button>
            </div>
          </div>
          {v === 'stoc' && data && <Alerts d={data} />}
          {v === 'stoc' && <RestView data={data} f={f} cat={cat} find={find} />}
          {v === 'intrari' && <InvoiceView docs={model?.docs ?? null} doc={model?.doc ?? null} />}
          {v === 'jurnal' && <JournalView data={model?.moves ?? null} />}
          {v === 'inventar' && <InventoryView docs={model?.docs ?? null} doc={model?.doc ?? null} />}
          {v === 'cumparat' && <BuyView data={model?.buy ?? null} />}
          {v === 'consum' && <ConsumView data={model?.report ?? null} />}
          {v === 'import' && <ImportView home={model?.imp ?? null} />}
        </SideMenu>
        {out && <OutDialog key={out.k} item={out.item} onClose={() => setOut(null)} />}
        {toast && <Toast {...toast} onClose={() => setToast(null)} />}
      </section>
    </StockCtx.Provider>
  )
}

/** «Din care comandate» — только свежие отметки: истёкшая («n-a venit») строку снова делает обычной. */
export function orderedOf(d: ListData | null): number {
  return (d?.items ?? []).filter((it) => it.active && it.low && it.ordered && !it.ordered.late).length
}

/** Категории из того, что есть в каталоге (подсказки сервера `cats` шире — для окна материала). */
function catsOf(d: ListData | null): { name: string; count: number; low: number }[] {
  const out = new Map<string, { name: string; count: number; low: number }>()
  for (const it of d?.items ?? []) {
    if (!it.active) continue
    const name = it.cat || 'Fără categorie'
    const c = out.get(name) ?? { name, count: 0, low: 0 }
    c.count += 1
    if (it.low) c.low += 1
    out.set(name, c)
  }
  const order = d?.cats ?? []
  const rank = (n: string) => { const i = order.indexOf(n); return i < 0 ? order.length : i }
  return [...out.values()].sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
}

function Alerts({ d }: { d: ListData }) {
  const { go } = useStockCtx()
  const low = d.counts.low
  const exp = d.counts.soon + d.counts.expired
  if (!low && !exp) return null
  return (
    <div className="st-alerts" role="status">
      {low > 0 && (
        <button type="button" className="st-alert warn" onClick={() => go('cumparat')}>
          <Icon name="excl" /><span><b>{low === 1 ? '1 material sub prag' : `${roCount(low, MATERIALE)} sub prag`}</b>
            {orderedOf(d) > 0 && ` · din care comandate: ${orderedOf(d)}`} — lista „De cumpărat”</span><Icon name="chev-r" />
        </button>
      )}
      {exp > 0 && (
        <button type="button" className="st-alert warn" onClick={() => go('stoc', { f: 'exp' })}>
          <Icon name="hourglass" /><span><b>{exp === 1 ? '1 material expiră în curând' : `${roCount(exp, MATERIALE)} expiră în curând`}</b> — de folosit întâi</span><Icon name="chev-r" />
        </button>
      )}
    </div>
  )
}
