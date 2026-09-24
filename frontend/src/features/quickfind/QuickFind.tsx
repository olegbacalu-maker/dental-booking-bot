import { useCallback, useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import { defaultNavigate } from '../../hooks/useLoad'
import { patients, type PatientRow } from '../patients/patients'

/*
 * Быстрый поиск пациента поверх любого экрана — Ctrl+K.
 *
 * ⭐ Почему это вообще понадобилось: шапка уже ОБЕЩАЕТ горячую клавишу
 * (`<span class="kbd">Ctrl K</span>` в `core/layout`), а даёт по ней только
 * фокус в поле. Дальше регистратура жмёт Enter и ждёт полной перезагрузки
 * страницы — посреди телефонного разговора. Обещание интерфейса и его
 * поведение разошлись, и разошлись молча.
 *
 * ⛔ Серверной страницей это не делается, и не по вкусу. Тело живой страницы
 * обязано быть ДЕТЕРМИНИРОВАННЫМ: `panel.js` сверяет отпечаток и подменяет
 * `#live` каждые 12 секунд. Выпадающий список, который меняется от каждой
 * набранной буквы, сделал бы отпечаток всегда другим — подмена шла бы на
 * каждый опрос, и мигание, которое чинили 08-20, вернулось бы чёрным ходом.
 * Поэтому накладка живёт в React и ВНЕ `#live`.
 *
 * ⭐ `position: fixed` снимает вопрос о месте в разметке: узел React стоит под
 * шапкой, а накладка всё равно накрывает окно целиком. Второй корень React
 * заводить не нужно — а он и запрещён.
 */

const T = {
  title: 'Căutare rapidă',
  ph: 'Nume sau telefon…',
  hint: 'Săgeți pentru a alege · Enter pentru a deschide · Esc pentru a închide',
  short: 'Scrieți cel puțin două caractere',
  none: 'Nimic găsit',
  busy: 'Se caută…',
  err: 'Programul nu răspunde',
  all: 'Toți pacienții',
} as const

const MIN = 2
const LIMIT = 8

interface Props {
  navigate?: (url: string) => void
  /** Шов для проверок: настоящая пауза делает их медленными и хрупкими. */
  debounceMs?: number
}

export function QuickFind({ navigate = defaultNavigate, debounceMs = 200 }: Props) {
  const [open, setOpen] = useState(false)

  /* Ctrl+K открывает откуда угодно. ⚠️ `preventDefault` обязателен: у браузера
     это своя команда (поиск в закладках у части сборок Chromium). */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(true)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  /* Закрыли — забываем ввод: следующий вызов начинается с чистого листа, а не
     с чужого запроса получасовой давности. Забывает РАЗМОНТИРОВАНИЕ накладки,
     а не сброс полей эффектом по `open`: такой сброс перечислял поля поимённо,
     и новое поле состояния пережило бы закрытие молча. */
  if (!open) return null
  return <Overlay navigate={navigate} debounceMs={debounceMs} onClose={() => setOpen(false)} />
}

interface OverlayProps {
  navigate: (url: string) => void
  debounceMs: number
  onClose: () => void
}

function Overlay({ navigate, debounceMs, onClose }: OverlayProps) {
  const [q, setQ] = useState('')
  /* Ответ помнит, НА КАКОЙ запрос он пришёл. Список прошлого ответа виден всю
     паузу и весь следующий запрос (иначе он мигал бы на каждую букву), но
     открывать из него можно только пока поле спрашивает то же самое.
     ⚠️ Без метки «Ion» → вставленный телефон второго однофамильца → Enter
     до ответа открывал ПЕРВОГО «Ion Popescu»: по запросу, которого в поле
     уже нет, — а во время запроса вообще по спрятанному списку. */
  const [found, setFound] = useState<{ asked: string; rows: PatientRow[] } | null>(null)
  const rows = found?.rows ?? null
  const fresh = found !== null && found.asked === q.trim()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [cur, setCur] = useState(0)
  const input = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    input.current?.focus()
  }, [])

  /* Короткий запрос не ищет, и прошлый ответ стирается тут же, в обработчике
     ввода. ⚠️ Одного «не показывать, пока короткий» мало: «Ana» → «A» → «Ma»
     вернул бы ответ по «Ana» на всю паузу перед поиском, и Enter открыл бы
     фишу, которую никто не искал. */
  function onType(value: string) {
    const next = value.slice(0, 60)
    setQ(next)
    if (next.trim().length < MIN) {
      setFound(null)
      setBusy(false)
    }
  }

  /* Поиск с паузой. ⚠️ Прошлый запрос ОТМЕНЯЕТСЯ: без этого ответы приходят
     не в том порядке, в каком уходили, и список показывает результат по
     предыдущей букве — это видно только на медленной сети. */
  useEffect(() => {
    const text = q.trim()
    if (text.length < MIN) return
    const ac = new AbortController()
    const timer = setTimeout(() => {
      setBusy(true)
      setErr('')
      patients
        .page({ q: text, med: '', st: '', ch: '', dat: '', sort: 'last',
                page: 1, per: LIMIT }, ac.signal)
        .then((r) => {
          setFound({ asked: text, rows: r.data.rows.slice(0, LIMIT) })
          setCur(0)
        })
        .catch((e) => {
          if (ac.signal.aborted) return
          setErr(asApiError(e).text || T.err)
          setFound({ asked: text, rows: [] })
        })
        .finally(() => {
          if (!ac.signal.aborted) setBusy(false)
        })
    }, debounceMs)
    return () => {
      clearTimeout(timer)
      ac.abort()
    }
  }, [q, debounceMs])

  /* Единственный вход в «открыть» — и Enter, и щелчок идут сюда, поэтому
     проверка свежести стоит здесь, а не у каждого. Несвежий список молчит:
     «дождаться ответа и открыть первого» значило бы открыть пациента,
     которого человек ещё не видел, — среди однофамильцев это и есть ошибка.
     Ответ придёт через долю секунды, второй Enter откроет уже его. */
  const go = useCallback((row: PatientRow) => {
    if (!fresh) return
    onClose()
    navigate(`/admin/patient/${row.id}`)
  }, [fresh, navigate, onClose])

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (!rows || !rows.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCur((i) => (i + 1) % rows.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCur((i) => (i - 1 + rows.length) % rows.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      // ⚠️ Строгий режим прав: индекс МОЖЕТ не дать строки, если список
      // сменился между нажатием и обработкой. Открывать «что-нибудь» тут
      // нельзя — человек нажал Enter на конкретном пациенте.
      const row = rows[cur]
      if (row) go(row)
    }
  }

  const short = q.trim().length > 0 && q.trim().length < MIN
  return (
    <div className="dp-qf-back" onMouseDown={onClose}>
      <div
        className="dp-qf"
        role="dialog"
        aria-label={T.title}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="dp-qf-top">
          <Icon name="search" />
          {/* ⚠️ Подпись поля НЕ та же, что у накладки: одинаковый `aria-label`
              на диалоге и на поле даёт два узла с одним именем — читалке это
              двусмысленно, а проверкам просто нечего выбрать. */}
          <input
            ref={input}
            value={q}
            onChange={(e) => onType(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={T.ph}
            aria-label={T.ph}
            autoComplete="off"
          />
          <span className="kbd">Esc</span>
        </div>

        {busy && <div className="dp-qf-note">{T.busy}</div>}
        {!busy && short && <div className="dp-qf-note">{T.short}</div>}
        {!busy && err && <div className="dp-qf-note dp-qf-err">{err}</div>}
        {!busy && !err && rows && !rows.length && (
          <div className="dp-qf-note">{T.none}</div>
        )}

        {!busy && !err && rows && rows.length > 0 && (
          <ul className="dp-qf-list">
            {rows.map((r, i) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={i === cur ? 'on' : ''}
                  onMouseEnter={() => setCur(i)}
                  onClick={() => go(r)}
                >
                  <span className="dp-qf-ini">{r.initials}</span>
                  <span className="dp-qf-name">{r.name}</span>
                  {/* ⚠️ Телефон и врач — то, чем регистратура отличает двух
                      однофамильцев. Без них список красив и бесполезен. */}
                  <span className="dp-qf-sub">
                    {[r.phone, r.doctor].filter(Boolean).join(' · ')}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="dp-qf-foot">
          <span>{T.hint}</span>
          <a href={`/admin/search${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`}>
            {T.all}
          </a>
        </div>
      </div>
    </div>
  )
}
