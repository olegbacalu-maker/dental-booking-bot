import { useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type Ref } from 'react'
import { fold } from '../../../utils/fold'

/* Поле процедуры плана с поиском по прайсу клиники. Прайс бывает на сотни строк:
   нужен отбор по словам, группы и цена в строке — `<datalist>` браузера этого не
   умеет. Отбор — без диакритики и регистра, по имени RO, RU и категории; строки
   сгруппированы по категориям в порядке сервера, цена справа.
   Выбор кладёт в поле имя услуги — ключ и цену владелец берёт по нему же
   (`planService`), так что второго правила «какая это услуга» нет. Свободный текст
   по-прежнему разрешён: список только подсказывает.
   Enter в поле не отправляет форму никогда: поле стоит внутри форм окон, и Enter
   на подсвеченной строке без этого увёл бы позицию в план с полупустыми полями.
   Список стоит `position: fixed` по прямоугольнику поля: модальное окно режет
   прокруткой всё, что выходит за его край, а растущее окно прыгало бы. */

export interface PickOption {
  id: string
  label: string
  ru?: string
  cat?: string
  cat_name?: string
  /** Сумма прайса (форма плана) или строка прайса, как её написала клиника (шаблоны). */
  price?: number | string | null
  price_hint?: string
}

const T = {
  uncat: 'Fără categorie',
  none: 'Nimic în lista de prețuri — rămâne textul scris.',
  mdl: 'MDL',
} as const

const thousands = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

/** Цена строки списка: сумма — с валютой (и строка прайса из одних цифр — тоже), прочая строка — как записана. */
export function priceLabel(s: PickOption): string {
  if (typeof s.price === 'number') return `${thousands(s.price)} ${T.mdl}`
  const text = typeof s.price === 'string' ? s.price.trim() : ''
  if (/^\d+$/.test(text)) return `${thousands(Number(text))} ${T.mdl}`
  if (text) return text
  return s.price_hint ?? ''
}

export interface PickGroup { cat: string; name: string; items: PickOption[] }

/**
 * Строки, подходящие к тексту поля, группами по категориям. Каждое слово запроса
 * должно найтись в имени RO, RU или в имени категории. Порядок — как у сервера
 * (категории по порядку прайса, «Fără categorie» последней).
 */
export function pickGroups(services: PickOption[], query: string): PickGroup[] {
  const words = fold(query).split(/\s+/).filter(Boolean)
  const groups: PickGroup[] = []
  for (const s of services) {
    if (words.length) {
      const hay = fold(`${s.label} ${s.ru ?? ''} ${s.cat_name ?? ''}`)
      if (!words.every((w) => hay.includes(w))) continue
    }
    const cat = s.cat ?? ''
    let g = groups.find((x) => x.cat === cat)
    if (!g) {
      g = { cat, name: cat ? (s.cat_name || T.uncat) : T.uncat, items: [] }
      groups.push(g)
    }
    g.items.push(s)
  }
  const uncat = groups.findIndex((g) => g.cat === '')
  if (uncat >= 0 && uncat < groups.length - 1) groups.push(...groups.splice(uncat, 1))
  return groups
}

interface Props {
  value: string
  services: PickOption[]
  /** Человек набрал текст (свободный или начало имени услуги). */
  onChange: (text: string) => void
  /** Строку выбрали из списка; по умолчанию — `onChange(имя)`. */
  onPick?: (s: PickOption) => void
  placeholder?: string
  label?: string
  /** Подпись поля по id — вместо `label`, когда она видна рядом. ⛔ Не оборачивать поле в `<label>`:
      список стоит внутри и вошёл бы в имя поля. */
  labelledBy?: string
  required?: boolean
  invalid?: boolean
  disabled?: boolean
  maxLength?: number
  describedBy?: string
  className?: string
  inputRef?: Ref<HTMLInputElement>
}

export function ServicePicker({
  value, services, onChange, onPick, placeholder, label, labelledBy, required, invalid, disabled, maxLength, describedBy,
  className, inputRef,
}: Props) {
  const uid = useId()
  const listId = `${uid}-list`
  const wrap = useRef<HTMLSpanElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)

  const groups = useMemo(() => pickGroups(services, value), [services, value])
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups])
  const index = useMemo(() => new Map(flat.map((s, n) => [s.id, n])), [flat])
  /* заголовки групп — когда у прайса есть категории; без них «Fără categorie» над всем — шум */
  const headed = groups.some((g) => g.cat !== '')
  const shown = open && services.length > 0
  const cur = Math.min(active, flat.length - 1)

  /* место списка — от поля, при открытии и при каждой прокрутке/смене окна;
     пишется прямо в стиль узла: это геометрия, а не состояние экрана */
  useLayoutEffect(() => {
    if (!shown) return
    const place = () => {
      const r = wrap.current?.getBoundingClientRect()
      const el = listRef.current
      if (!r || !el) return
      const vw = window.innerWidth, vh = window.innerHeight
      const width = Math.min(Math.max(r.width, 340), vw - 16)
      const below = vh - r.bottom - 8, above = r.top - 8
      const up = below < 200 && above > below
      el.style.left = `${Math.max(8, Math.min(r.left, vw - width - 8))}px`
      el.style.width = `${width}px`
      el.style.maxHeight = `${Math.max(120, Math.min(340, up ? above : below))}px`
      el.style.top = up ? '' : `${r.bottom + 4}px`
      el.style.bottom = up ? `${vh - r.top + 4}px` : ''
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [shown])

  /* подсвеченная строка видна при ходе стрелками */
  useLayoutEffect(() => {
    if (!shown || cur < 0) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-i="${cur}"]`)
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [shown, cur])

  function pick(s: PickOption) {
    setOpen(false)
    if (onPick) onPick(s)
    else onChange(s.label)
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) { setOpen(true); setActive(0); return }
      const n = flat.length
      if (n) setActive((cur + (e.key === 'ArrowDown' ? 1 : n - 1)) % n)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const s = shown ? flat[cur] : undefined
      if (s) pick(s)
    } else if (e.key === 'Escape' && shown) {
      /* Esc закрывает список, а не окно, в котором стоит поле */
      e.preventDefault()
      e.stopPropagation()
      setOpen(false)
    }
  }

  const optId = (n: number) => `${uid}-o${n}`
  return (
    <span ref={wrap} className={`dp-svc${className ? ` ${className}` : ''}`}>
      <input ref={inputRef} className="dp-fld" value={value} placeholder={placeholder} aria-label={label}
        aria-labelledby={labelledBy} required={required} disabled={disabled} maxLength={maxLength} autoComplete="off" spellCheck={false}
        aria-invalid={invalid || undefined} aria-describedby={describedBy}
        role="combobox" aria-autocomplete="list" aria-expanded={shown} aria-controls={listId}
        aria-activedescendant={shown && cur >= 0 ? optId(cur) : undefined}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(0) }}
        onKeyDown={onKey}
        onClick={() => { if (!open) { setOpen(true); setActive(0) } }}
        onBlur={() => setOpen(false)} />
      {shown && (
        <div ref={listRef} id={listId} role="listbox" className="dp-svc-list"
          /* щелчок по списку не снимает фокус с поля: иначе blur закрыл бы список раньше выбора */
          onMouseDown={(e) => e.preventDefault()}>
          {flat.length === 0 && <p className="dp-svc-none">{T.none}</p>}
          {groups.map((g) => (
            <div key={g.cat || '~'} role="group" aria-label={headed ? g.name : undefined}>
              {headed && <div className="dp-svc-cat" aria-hidden="true">{g.name}</div>}
              {g.items.map((s) => {
                const n = index.get(s.id) ?? 0
                const price = priceLabel(s)
                return (
                  <div key={s.id} id={optId(n)} data-i={n} role="option" aria-selected={n === cur}
                    className={`dp-svc-opt${n === cur ? ' on' : ''}`}
                    onMouseMove={() => { if (n !== cur) setActive(n) }} onClick={() => pick(s)}>
                    <span className="dp-svc-name">{s.label}</span>
                    {price && <span className="dp-svc-price">{price}</span>}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </span>
  )
}
