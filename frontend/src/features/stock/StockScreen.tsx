import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { SideMenu, type SideItem } from '../../components/SideMenu'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { roCount } from '../../utils/plural'
import { BuyView } from './BuyView'
import { ImportView } from './ImportView'
import { InventoryView } from './InventoryView'
import { InvoiceView } from './InvoiceView'
import { JournalView } from './JournalView'
import { OutDialog } from './OutDialog'
import { RestView } from './RestView'
import { MATERIALE, stockApi, type Filter, type ListData, type View } from './stock'

/* Корень раздела: меню слева (разделы и категории), данные списка — и меню, и таблице остатков. Разделы
   грузят своё сами; после команды любой из них зовёт `refresh` — перечитываются список и раздел. */

/** Раздел отдаёт корню своё перечитывание, пока смонтирован. */
export function useBindRetry(retry: () => void): void {
  const { bind } = useStockCtx()
  useEffect(() => { bind(retry); return () => bind(null) }, [bind, retry])
}

interface Ctx {
  say: (text: string, tone?: ToastState['tone'], link?: ToastState['link']) => void
  refresh: () => void
  /** Раздел отдаёт своё перечитывание: команда в одном месте обновляет и меню, и раздел. */
  bind: (f: (() => void) | null) => void
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
  ['inventar', 'Inventariere', 'check'], ['cumparat', 'De cumpărat', 'note'], ['import', 'Import din Excel', 'upload'],
]
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
  const load = useCallback((signal: AbortSignal) => stockApi.list(signal), [])
  const { state, retry } = useLoad<ListData>(load, navigate)
  const listRetry = useRef(retry)
  const viewRetry = useRef<(() => void) | null>(null)
  useEffect(() => { listRetry.current = retry }, [retry])
  const refresh = useCallback(() => { listRetry.current(); viewRetry.current?.() }, [])
  const bind = useCallback((fn: (() => void) | null) => { viewRetry.current = fn }, [])
  const say = useCallback((text: string, tone: ToastState['tone'] = 'ok', link?: ToastState['link']) =>
    setToast(link ? { text, tone, link } : { text, tone }), [])
  const go = useCallback((to: View, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams()
    if (to !== 'stoc') p.set('v', to)
    for (const [k, val] of Object.entries(extra)) if (val) p.set(k, val)
    setQ(p)
  }, [setQ])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  const data = state.status === 'ready' ? state.data : null
  const ctx: Ctx = { say, refresh, bind, list: data, navigate, go, out: (item) => setOut({ item, k: Date.now() }) }

  const cats = catsOf(data)
  const items: SideItem<string>[] = VIEWS.map(([k, label, icon]) => {
    const n = k === 'stoc' ? data?.counts.all : k === 'intrari' ? data?.drafts.factura : k === 'inventar' ? data?.drafts.inventar
      : k === 'cumparat' ? data?.counts.low : undefined
    return { key: k, label, icon, count: n || undefined, tone: k !== 'stoc' ? 'warn' : '',
      hint: k === 'intrari' && data?.drafts.factura ? 'ciorne' : k === 'inventar' && data?.drafts.inventar ? 'ciornă'
        : k === 'cumparat' && data?.counts.ordered ? `din care comandate: ${data.counts.ordered}` : undefined }
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
      <section className="dp-react-root rg st" aria-busy={state.status === 'loading' || undefined}>
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
          {v === 'intrari' && <InvoiceView />}
          {v === 'jurnal' && <JournalView />}
          {v === 'inventar' && <InventoryView />}
          {v === 'cumparat' && <BuyView />}
          {v === 'import' && <ImportView />}
        </SideMenu>
        {out && <OutDialog key={out.k} item={out.item} onClose={() => setOut(null)} />}
        {toast && <Toast {...toast} onClose={() => setToast(null)} />}
      </section>
    </StockCtx.Provider>
  )
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
            {d.counts.ordered > 0 && ` · din care comandate: ${d.counts.ordered}`} — lista „De cumpărat”</span><Icon name="chev-r" />
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
