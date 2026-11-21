import { useEffect, useRef, useState } from 'react'
import { useBlocker, useSearchParams, type ShouldRevalidateFunction } from 'react-router'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { SideMenu, type SideItem } from '../../components/SideMenu'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad, type ScreenData } from '../../hooks/useRouteLoad'
import { useUnsavedPage } from '../../hooks/useUnsavedPage'
import { asApiError } from '../../services/api'
import { fold } from '../../utils/fold'
import { roCount } from '../../utils/plural'
import { CatDialog } from './CatDialog'
import { ImportDialog } from './ImportDialog'
import {
  buildForm, EXPORT_HREF, inAgenda, inPlan, shown, tarifeApi,
  type NewRow, type RowEdit, type TarifeData, type TarifeForm, type TarifRow,
} from './tarife'

/* «Servicii și tarife» — прайс клиники для плана лечения. Слева категории, справа строки; данные — одним
   загрузчиком маршрута (`loadTarife` в LOADS). Строка в покое — плитка только для чтения, случайно её не поменять;
   карандаш в конце открывает её на правку, правки всех строк уходят одной кнопкой «Salvează» — только тронутое
   (контракт § 5). Категории (новая, имя, порядок, удаление) пишутся сразу своей командой.
   Вид в меню и поиск — на клиенте, без загрузки. */

const T = {
  title: 'Servicii și tarife',
  all: 'Toate serviciile',
  uncat: 'Fără categorie',
  agenda: 'Doar în agendă',
  agendaHint: 'Tipuri de programare care nu apar în planul de tratament. «Plan» le adaugă în listă.',
  readOnly: 'Prețurile le schimbă directorul sau recepția. Aici le puteți vedea și exporta.',
  find: 'Caută serviciul',
  addSvc: 'Serviciu',
  addCat: 'Categorie',
  imp: 'Importă din Excel',
  exp: 'Exportă',
  save: 'Salvează',
  discard: 'Renunță',
  unsaved: 'Lista de prețuri are modificări nesalvate.',
  leaveAsk: 'Părăsiți pagina fără să le salvați?',
  leave: 'Părăsește',
  cols: { ro: 'Denumire (RO)', ru: 'Denumire (RU)', price: 'Preț', cat: 'Categorie', where: 'Apare în' },
  fresh: 'Servicii noi — încă nesalvate',
  none: 'Niciun serviciu aici.',
  noneFind: 'Nimic găsit.',
  empty: 'Lista de prețuri e goală. Adăugați un serviciu sau aduceți lista din Excel.',
  agendaChip: 'Agendă',
  agendaTip: 'Tipul de programare se schimbă în Setări › Servicii',
  planChip: 'Plan',
  planOn: 'Apare în planul de tratament',
  planOff: 'Nu apare în plan',
  drop: 'Șterge din listă',
  dropped: 'se șterge la salvare',
  undo: 'Anulează',
  undoTip: 'Anulează ștergerea',
  editRow: 'Editează',
  doneRow: 'Gata',
  doneTip: 'Închide rândul; modificarea rămâne până la «Salvează»',
  sameRo: 'ca RO',
  fresh1: 'Scoate rândul nou',
  noName: 'Scrieți denumirea serviciului.',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

const MODS = { one: '1 modificare', few: '{n} modificări', many: '{n} de modificări' }
const SVCS = { one: '1 serviciu', few: '{n} servicii', many: '{n} de servicii' }

/** Вид меню: все строки прайса, категория по id, без категории, только агенда. */
type View = { k: 'all' } | { k: 'cat'; id: string } | { k: 'none' } | { k: 'agenda' }

const viewOf = (c: string | null): View =>
  !c ? { k: 'all' } : c === 'none' ? { k: 'none' } : c === 'agenda' ? { k: 'agenda' } : { k: 'cat', id: c }
const keyOf = (v: View): string => (v.k === 'cat' ? `c:${v.id}` : v.k)

/** Вид меню и поиск данных не меняют: загрузка — при повторе и уходе на другой адрес. */
const keepOnSearch: ShouldRevalidateFunction = ({ currentUrl, nextUrl, defaultShouldRevalidate }) =>
  currentUrl.pathname === nextUrl.pathname && currentUrl.search !== nextUrl.search ? false : defaultShouldRevalidate

const loadModel: RouteLoad<TarifeData> = (signal) => tarifeApi.load(signal)
export const loadTarife: ScreenData = { load: loadModel as RouteLoad<unknown>, shouldRevalidate: keepOnSearch }

/** Строка принадлежит виду по ПРОФИЛЮ, не по черновику: правка не уводит её из-под руки до записи. */
function inView(r: TarifRow, v: View): boolean {
  if (v.k === 'agenda') return r.where === 'agenda'
  if (!inPlan(r.where)) return false
  return v.k === 'all' || (v.k === 'none' ? !r.cat : r.cat === v.id)
}

let seq = 0
const newKey = () => `n${++seq}`

export function TarifeScreen({ navigate = defaultNavigate }: { navigate?: (url: string) => void }) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<TarifeData>(navigate, { keep: true })
  const [q, setQ] = useSearchParams()
  const view = viewOf(q.get('c'))
  const [find, setFind] = useState('')
  const [edits, setEdits] = useState<Record<string, RowEdit>>({})
  const [added, setAdded] = useState<NewRow[]>([])
  /* строки, открытые карандашом; новые строки открыты всегда */
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [bad, setBad] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [catDlg, setCatDlg] = useState<{ id: string; name: string | null } | null>(null)
  const [importing, setImporting] = useState(false)
  const focusKey = useRef<string | null>(null)
  const say = (text: string, tone: ToastState['tone'] = 'ok') => setToast({ text, tone })

  const data = state.status === 'ready' ? state.data : null
  const form: TarifeForm = data ? buildForm(data, edits, added) : {}
  const changes = (Object.keys(form.services ?? {}).length) + (form.new?.length ?? 0)
  const dirty = changes > 0
  /* гаснущая после записи полоса держит последнее число, а не «0» */
  const [lastChanges, setLastChanges] = useState(1)
  if (changes > 0 && changes !== lastChanges) setLastChanges(changes)

  /* уход с экрана с правкой — своим окном; смена вида меню (тот же адрес) правку не теряет */
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (!dirty) { blocker.proceed(); return }
    void ask({ text: `${T.unsaved} ${T.leaveAsk}`, ok: T.leave, danger: true }).then((yes) => {
      if (yes) blocker.proceed()
      else blocker.reset()
    })
  }, [blocker, dirty])
  useUnsavedPage(dirty ? T.unsaved : null)

  useEffect(() => {
    const k = focusKey.current
    if (!k) return
    focusKey.current = null
    const el = document.querySelector<HTMLInputElement>(`[data-row="${k}"] input`)
    el?.focus()
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [added, open])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return <section className="dp-react-root rg tf"><LoadFailed error={state.error} onRetry={retry} /></section>
  }

  const can = data?.can_edit ?? false
  const cats = data?.cats ?? []
  const catName = (id: string) => cats.find((c) => c.id === id)?.name ?? T.uncat
  const agendaOnly = data ? data.services.filter((r) => r.where === 'agenda').length : 0
  const planTotal = data ? data.services.filter((r) => inPlan(r.where)).length : 0
  const viewTitle = view.k === 'all' ? T.all : view.k === 'none' ? T.uncat : view.k === 'agenda' ? T.agenda : catName(view.id)
  const curCat = view.k === 'cat' ? cats.find((c) => c.id === view.id) ?? null : null

  const items: SideItem<string>[] = [
    { key: 'all', label: T.all, icon: 'cash', count: planTotal },
    ...cats.map((c, i) => ({ key: `c:${c.id}`, label: c.name, icon: 'folder' as const, count: c.n, sep: i === 0 })),
    { key: 'none', label: T.uncat, icon: 'folder', count: data?.uncat ?? 0, sep: cats.length === 0 },
    ...(agendaOnly ? [{ key: 'agenda', label: T.agenda, icon: 'cal' as const, count: agendaOnly, sep: true, note: T.agendaHint }] : []),
  ]
  const pick = (k: string) => {
    const p = new URLSearchParams(q)
    if (k === 'all') p.delete('c')
    else p.set('c', k.startsWith('c:') ? k.slice(2) : k)
    setQ(p, { replace: true })
  }

  const needle = fold(find)
  /* Правило поиска услуги в плане (`pickGroups`): каждое слово — в имени RO, RU или категории, в любом порядке.
     Иначе «restaurare supraf», что находит строку в плане, здесь давало «Nimic găsit.». */
  const words = needle.split(/\s+/).filter(Boolean)
  const hit = (r: TarifRow) => {
    if (!words.length) return true
    const s = shown(r, edits[r.id])
    const hay = fold(`${s.ro} ${s.ru} ${r.ro} ${cats.find((c) => c.id === r.cat)?.name ?? ''}`)
    return words.every((w) => hay.includes(w))
  }
  const rows = data ? data.services.filter((r) => inView(r, view) && hit(r)) : []
  /* «Toate»: группы по порядку категорий, «Fără categorie» последней */
  const groups: [string, TarifRow[]][] = view.k !== 'all' ? [['', rows]]
    : [...cats.map((c) => [c.name, rows.filter((r) => r.cat === c.id)] as [string, TarifRow[]]),
      [T.uncat, rows.filter((r) => !r.cat || !cats.some((c) => c.id === r.cat))] as [string, TarifRow[]]]
      .filter(([, list]) => list.length > 0)

  const edit = (id: string, p: RowEdit) => {
    setEdits((x) => ({ ...x, [id]: { ...x[id], ...p } }))
    if (bad.has(id)) setBad((b) => { const n = new Set(b); n.delete(id); return n })
  }
  const editNew = (key: string, p: Partial<NewRow>) => {
    setAdded((x) => x.map((n) => (n.key === key ? { ...n, ...p } : n)))
    if (bad.has(key)) setBad((b) => { const n = new Set(b); n.delete(key); return n })
  }
  const addRow = () => {
    const key = newKey()
    focusKey.current = key
    setAdded((x) => [...x, { key, ro: '', ru: '', price: '', cat: view.k === 'cat' ? view.id : '' }])
  }
  const openRow = (id: string, on: boolean) => {
    if (on) focusKey.current = id
    setOpen((o) => { const n = new Set(o); if (on) n.add(id); else n.delete(id); return n })
  }
  async function dropRow(r: TarifRow) {
    if (!(await ask({ text: `Ștergeți „${r.ro}” din lista de prețuri? Serviciul nu apare în agendă, deci dispare de tot la salvare. `
      + 'Planurile pacienților îl păstrează așa cum a fost scris.', ok: 'Șterge', danger: true }))) return
    edit(r.id, { plan: false })
  }
  const discard = () => { setEdits({}); setAdded([]); setBad(new Set()); setOpen(new Set()) }

  async function save() {
    if (!data || !dirty) return
    const empty = [
      ...Object.entries(form.services ?? {}).filter(([, e]) => e.ro !== undefined && !e.ro).map(([id]) => id),
      ...added.filter((n) => !n.ro.trim() && (n.ru.trim() || n.price.trim())).map((n) => n.key),
    ]
    if (empty.length) { setBad(new Set(empty)); setOpen((o) => new Set([...o, ...empty])); say(T.noName, 'err'); return }
    setBusy(true)
    try {
      const r = await tarifeApi.save(form)
      replace(r.data)
      discard()
      say(r.text || 'Lista de prețuri salvată.', r.tone)
    } catch (e) {
      const er = asApiError(e)
      if (leaveIfSignedOut(er)) return
      if (er.failure.kind === 'conflict') retry()
      const label = (er.failure.kind === 'validation' ? (er.failure.data as { label?: string } | undefined)?.label : undefined) ?? ''
      if (label) {
        const l = fold(label)
        const taken = [
          ...data.services.filter((x) => fold(shown(x, edits[x.id]).ro) === l || fold(shown(x, edits[x.id]).ru) === l).map((x) => x.id),
          ...added.filter((n) => fold(n.ro) === l || fold(n.ru) === l).map((n) => n.key),
        ]
        setBad(new Set(taken))
        /* строку с занятым именем — открыть: в плитке поправить нечего */
        setOpen((o) => new Set([...o, ...taken]))
      }
      say(er.text || T.offline, 'err')
    } finally {
      setBusy(false)
    }
  }

  /** Команда категорий пишется сразу; отказ — текстом (окну имени) или плашкой. */
  async function catCmd(body: TarifeForm, ok?: (d: TarifeData) => void): Promise<string | null> {
    try {
      const r = await tarifeApi.save(body)
      replace(r.data)
      ok?.(r.data)
      say(r.text || 'Salvat.', r.tone)
      return null
    } catch (e) {
      const er = asApiError(e)
      if (leaveIfSignedOut(er)) return null
      if (er.failure.kind === 'conflict') retry()
      return er.text || T.offline
    }
  }
  async function moveCat(id: string, by: -1 | 1) {
    const order = cats.map((c) => c.id)
    const i = order.indexOf(id)
    const j = i + by
    if (i < 0 || j < 0 || j >= order.length) return
    ;[order[i], order[j]] = [order[j]!, order[i]!]
    const bad2 = await catCmd({ cats_order: order })
    if (bad2) say(bad2, 'err')
  }
  async function dropCat(c: { id: string; name: string; n: number }) {
    const what = c.n ? ` ${roCount(c.n, SVCS)} trec la «${T.uncat}»; nu se șterge niciun serviciu.` : ''
    if (!(await ask({ text: `Ștergeți categoria „${c.name}”?${what}`, ok: 'Șterge', danger: true }))) return
    const bad2 = await catCmd({ cats_removed: [c.id] }, () => {
      /* черновик, указывавший на снятую категорию, — «Fără categorie», как и сами строки */
      setEdits((x) => Object.fromEntries(Object.entries(x).map(([id, e]) => [id, e.cat === c.id ? { ...e, cat: '' } : e])))
      setAdded((x) => x.map((n) => (n.cat === c.id ? { ...n, cat: '' } : n)))
      pick('all')
    })
    if (bad2) say(bad2, 'err')
  }

  const catSelect = (value: string, label: string, onPick: (v: string) => void) => (
    <select className="dp-sel tf-cat" value={value} aria-label={label} disabled={busy} onChange={(e) => onPick(e.target.value)}>
      <option value="">{T.uncat}</option>
      {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  )

  /** Значение плитки — та же коробка, что у поля правки (высота, отступы, прозрачная рамка): строка не прыгает. */
  const val = (text: string, cls = '', empty = '—') =>
    <span className={`tf-val${cls ? ` ${cls}` : ''}${text ? '' : ' none'}`} title={text || undefined}>{text || empty}</span>
  const undoBtn = (r: TarifRow) => (
    <button type="button" className="rg-ib tf-undo" aria-label={T.undo} title={T.undoTip} onClick={() => edit(r.id, { plan: true })}>
      <Icon name="undo" /></button>
  )

  function row(r: TarifRow) {
    const s = shown(r, edits[r.id])
    const gone = r.where === 'plan' && !s.plan
    const off = r.where !== 'plan' && !s.plan
    const isOpen = can && open.has(r.id)
    const cls = [bad.has(r.id) && 'tf-bad', gone && 'tf-gone', off && 'tf-off', form.services?.[r.id] && 'tf-ed', isOpen && 'tf-open']
      .filter(Boolean).join(' ')
    /* «Apare în»: в плитке — чипы словами; переключатель «Plan» — только в правке */
    const where = (
      <td className="tf-where">
        {/* пометка удаления встаёт на место «Plan», а не строкой под именем: строка не меняет высоту */}
        {gone && <span className="tf-drop st-errt">{T.dropped}</span>}
        {inAgenda(r.where) && <span className="tf-chip mute" title={T.agendaTip}>{T.agendaChip}</span>}
        {isOpen && inAgenda(r.where) ? (
          <button type="button" className={`tf-chip tog${s.plan ? ' on' : ''}`} aria-pressed={s.plan} disabled={busy}
            title={s.plan ? T.planOn : T.planOff} aria-label={`${T.planChip}: ${r.ro}`} onClick={() => edit(r.id, { plan: !s.plan })}>
            {s.plan && <Icon name="check" />}{T.planChip}</button>
        ) : s.plan && <span className="tf-chip on">{T.planChip}</span>}
      </td>
    )
    if (!isOpen) {
      return (
        <tr key={r.id} className={cls} data-row={r.id}>
          <td>{val(s.ro)}</td>
          <td>{s.ru ? val(s.ru) : val('', 'same', T.sameRo)}</td>
          <td className="num">{val(s.price, 'num')}</td>
          <td>{s.cat ? val(catName(s.cat)) : val('', '', T.uncat)}</td>
          {where}
          {can && (
            <td className="tf-act">
              {/* два постоянных места — карандаш и отмена удаления: кнопки не ездят между плиткой и правкой */}
              <button type="button" className="rg-ib tf-pen" aria-label={`${T.editRow}: ${r.ro}`} title={T.editRow} disabled={busy}
                onClick={() => openRow(r.id, true)}><Icon name="pen" /></button>
              {gone ? undoBtn(r) : <span className="tf-slot" />}
            </td>
          )}
        </tr>
      )
    }
    return (
      <tr key={r.id} className={cls} data-row={r.id}>
        <td><input className="dp-fld" value={s.ro} maxLength={data!.max.name} disabled={busy || gone} aria-label={`${T.cols.ro}: ${r.ro}`}
          onChange={(e) => edit(r.id, { ro: e.target.value })} /></td>
        <td><input className="dp-fld" value={s.ru} placeholder={T.sameRo} maxLength={data!.max.name} disabled={busy || gone} aria-label={`${T.cols.ru}: ${r.ro}`}
          onChange={(e) => edit(r.id, { ru: e.target.value })} /></td>
        <td><input className="dp-fld tf-price" value={s.price} maxLength={data!.max.price} disabled={busy || gone} placeholder="—" aria-label={`${T.cols.price}: ${r.ro}`}
          onChange={(e) => edit(r.id, { price: e.target.value })} /></td>
        <td>{catSelect(s.cat, `${T.cols.cat}: ${r.ro}`, (v) => edit(r.id, { cat: v }))}</td>
        {where}
        <td className="tf-act">
          <button type="button" className="rg-ib tf-pen on" aria-label={`${T.doneRow}: ${r.ro}`} title={T.doneTip} disabled={busy}
            onClick={() => openRow(r.id, false)}><Icon name="check" /></button>
          {/* корзина — только в правке, как «Șterge» в окне лаборатории: в плитке её не задеть случайно;
              отмена удаления — значком на её месте */}
          {gone ? undoBtn(r)
            : r.where === 'plan' ? (
              <button type="button" className="rg-ib bad tf-del" aria-label={`${T.drop}: ${r.ro}`} title={T.drop} disabled={busy}
                onClick={() => { void dropRow(r) }}><Icon name="trash" /></button>
            ) : <span className="tf-slot" />}
        </td>
      </tr>
    )
  }

  const colCount = can ? 6 : 5
  const headRow = (
    <tr>
      <th>{T.cols.ro}</th><th>{T.cols.ru}</th><th className="num">{T.cols.price}</th>
      <th>{T.cols.cat}</th><th>{T.cols.where}</th>{can && <th />}
    </tr>
  )

  return (
    <section className="dp-react-root rg st tf" aria-busy={!data || undefined}>
      <SideMenu label={T.title} items={items} value={keyOf(view)} onPick={pick}>
        {/* Шапка — двумя постоянными рядами: название и общие кнопки; поиск слева и кнопки категории справа.
            В одном ряду с названием поле ездило вбок и меняло ширину от длины названия категории. */}
        <div className="fcard rg-head st-head tf-head">
          <div className="tf-hrow">
            <b className="st-ttl">{viewTitle}</b>
            <div className="rg-tools">
              <AppLink className="rg-btn" href={EXPORT_HREF} download><Icon name="download" /> {T.exp}</AppLink>
              {can && (data?.import.remote
                ? null
                : <button type="button" className="rg-btn" disabled={!data || dirty} title={dirty ? 'Salvați modificările întâi' : undefined}
                    onClick={() => setImporting(true)}><Icon name="upload" /> {T.imp}</button>)}
              {can && <button type="button" className="rg-btn" disabled={!data} onClick={() => setCatDlg({ id: '', name: null })}><Icon name="plus" /> {T.addCat}</button>}
              {can && <button type="button" className="rg-btn pri" disabled={!data || view.k === 'agenda'} onClick={addRow}><Icon name="plus" /> {T.addSvc}</button>}
            </div>
          </div>
          <div className="tf-hrow">
            <span className="tf-find">
              <input className="dp-fld" type="search" placeholder={T.find} aria-label={T.find} value={find} onChange={(e) => setFind(e.target.value)} />
              {/* место под число найденного занято всегда: иначе поле сужалось бы под курсором с первой буквой */}
              <span className="st-mute" aria-hidden={!needle || undefined}>{needle ? roCount(rows.length, SVCS) : ''}</span>
            </span>
            {can && curCat && (
              <div className="rg-tools tf-cat-tools">
                <button type="button" className="rg-btn sm" onClick={() => setCatDlg({ id: curCat.id, name: curCat.name })}><Icon name="pen" /> Redenumește</button>
                <button type="button" className="rg-btn sm" aria-label="Mută mai sus" title="Mută mai sus" disabled={cats[0]?.id === curCat.id}
                  onClick={() => { void moveCat(curCat.id, -1) }}><Icon name="caret-u" /></button>
                <button type="button" className="rg-btn sm" aria-label="Mută mai jos" title="Mută mai jos" disabled={cats.at(-1)?.id === curCat.id}
                  onClick={() => { void moveCat(curCat.id, 1) }}><Icon name="caret-d" /></button>
                <button type="button" className="rg-btn sm" onClick={() => { void dropCat(curCat) }}><Icon name="trash" /> Șterge categoria</button>
              </div>
            )}
          </div>
        </div>
        {!can && data && <p className="st-note"><Icon name="info" /> {T.readOnly}</p>}
        {can && data?.import.remote && <div className={`banner ${data.import.remote.tone}`} role="status">{data.import.remote.text}</div>}
        {view.k === 'agenda' && <p className="st-note"><Icon name="info" /> {T.agendaHint}</p>}
        <div className="fcard rg-body">
          {!data ? <div aria-busy="true" className="tf-wait" /> : (
            <div className="rg-scroll">
              <table className="rg-tbl st-tbl tf-tbl ed">
                <thead>{headRow}</thead>
                <tbody>
                  {added.length > 0 && <tr className="st-cat-r"><td colSpan={colCount}>{T.fresh}</td></tr>}
                  {added.map((n) => (
                    <tr key={n.key} data-row={n.key} className={`tf-new${bad.has(n.key) ? ' tf-bad' : ''}`}>
                      <td><input className="dp-fld" value={n.ro} maxLength={data.max.name} disabled={busy} placeholder="Serviciu" aria-label={`${T.cols.ro}: nou`}
                        onChange={(e) => editNew(n.key, { ro: e.target.value })} /></td>
                      <td><input className="dp-fld" value={n.ru} maxLength={data.max.name} disabled={busy} placeholder={T.sameRo} aria-label={`${T.cols.ru}: nou`}
                        onChange={(e) => editNew(n.key, { ru: e.target.value })} /></td>
                      <td><input className="dp-fld tf-price" value={n.price} maxLength={data.max.price} disabled={busy} placeholder="preț" aria-label={`${T.cols.price}: nou`}
                        onChange={(e) => editNew(n.key, { price: e.target.value })} /></td>
                      <td>{catSelect(n.cat, `${T.cols.cat}: nou`, (v) => editNew(n.key, { cat: v }))}</td>
                      <td className="tf-where"><span className="tf-chip on">{T.planChip}</span></td>
                      <td className="tf-act"><span className="tf-slot" /><button type="button" className="rg-ib bad" aria-label={T.fresh1}
                        title={T.fresh1} disabled={busy} onClick={() => setAdded((x) => x.filter((y) => y.key !== n.key))}><Icon name="close" /></button></td>
                    </tr>
                  ))}
                  {groups.map(([name, list]) => [
                    name ? <tr key={`g-${name}`} className="st-cat-r"><td colSpan={colCount}>{name}</td></tr> : null,
                    ...list.map(row),
                  ])}
                  {rows.length === 0 && added.length === 0 && (
                    <tr><td colSpan={colCount} className="tf-none">{needle ? T.noneFind : planTotal || agendaOnly ? T.none : T.empty}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {/* Полоса записи стоит всегда и проявляется с первой правкой: снятая после «Salvează» укорачивала бы
            страницу, и у прокрученной до низа всё содержимое съезжало бы вниз на её высоту. */}
        {can && data && (
          <div className={`fcard tf-save${dirty ? '' : ' off'}`} role="region" aria-label="Modificări nesalvate"
            aria-hidden={!dirty || undefined} inert={!dirty}>
            {/* кнопки слева: справа внизу встаёт плашка ответа и закрыла бы их */}
            <button type="button" className="rg-btn pri" disabled={busy} onClick={() => { void save() }}><Icon name="save" /> {T.save}</button>
            <button type="button" className="rg-btn" disabled={busy} onClick={discard}>{T.discard}</button>
            <span><b>{roCount(dirty ? changes : lastChanges, MODS)}</b> nesalvate</span>
          </div>
        )}
      </SideMenu>
      {catDlg && data && (
        <CatDialog name={catDlg.name} max={data.max.cat} onClose={() => setCatDlg(null)}
          onSave={(name) => (catDlg.id
            ? catCmd({ cats: { [catDlg.id]: { name } } })
            : catCmd({ cats_new: [{ key: 'k1', name }] }, (d) => { const id = d.created?.cats.k1; if (id) pick(`c:${id}`) }))} />
      )}
      {importing && (
        <ImportDialog onClose={() => setImporting(false)} onSignedOut={leaveIfSignedOut}
          onDone={(d, text) => { replace(d); say(text || 'Prețurile importate.') }} />
      )}
      {toast && <Toast {...toast} onClose={() => setToast(null)} />}
    </section>
  )
}

