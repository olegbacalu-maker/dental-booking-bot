import { useCallback, useRef, useState, type KeyboardEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { useNavigate, useNavigation } from 'react-router'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { PerioSummaryCard } from './PerioSummary'
import { PerioTooth } from './PerioTooth'
import { perio, type PerioModel } from './perio'
import { usePerio, type Kind } from './usePerio'

/* Пародонтограмма (C23): датированный осмотр, шесть точек на зуб, итог
   справа. Раскладка и классы — те же, что у старой страницы (.perio, .pgrid,
   .parch, .ptooth, .pcell, .pfoot, .psum), сайдбар узкий — рамку даёт сервер.

   ⚠️ Главное здесь не рисунок, а ВВОД: осмотр — это без малого двести чисел,
   и вводят их ДИКТОВКОЙ (врач называет, ассистент печатает). Поэтому поле
   само уходит к следующей точке, как только число не может вырасти («3» —
   готовое значение, «1» ждёт вторую цифру, бывает 12 мм), а кровоточивость
   ставится клавишей «b» с того же места. Без этого карту просто не ведут.
   ⛔ Enter здесь НЕ сохраняет, в отличие от одонтограммы: руки ассистента не
   уходят с цифровой клавиатуры, и Enter — это «следующая точка». Осмотр
   записывается кнопкой, одной на весь лист. */
const T = {
  title: 'Parodontogramă',
  sub: '6 puncte pe dinte',
  newExam: 'Examen nou',
  firstExam: 'Începe primul examen',
  none: 'Pentru acest pacient nu există încă niciun examen parodontal.',
  print: 'Printează',
  odo: 'Odontogramă',
  save: 'Salvează examenul',
  dropEmpty: 'Șterge examenul gol',
  unsaved: 'Nesalvat',
  discard: 'Renunță',
  doctor: 'Medic',
  note: 'Notă',
  notePh: 'ex. reevaluare după detartraj',
  upper: 'Maxilar',
  lower: 'Mandibular',
  hint: 'Rânduri: adâncimea de sondare și recesiunea, dinspre vestibular spre oral. '
    + 'Punctul roșu = sângerare (tasta «b»). Cifra trece singură la punctul următor.',
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  pid: number
  navigate?: (url: string) => void
}

/**
 * Осмотр из адреса (`?exam=`) — правилом СТРАНИЦЫ сервера: обрезанное
 * значение из одних цифр ASCII — номер, всё прочее — «самый свежий» (null).
 * ⚠️ Не `Number` по сырому значению: «4.0», «+4», «0x4», «1e1» открыли бы
 * конкретный осмотр там, где страница отдаёт свежий. И не сырая строка в API:
 * полноширинную «４» Python читает как 4. Бесконечность (сотни цифр) —
 * тоже свежий, как и было.
 */
function examOf(q: URLSearchParams): number | null {
  const raw = queryParam(q, 'exam').trim()
  const n = Number(raw)
  return /^\d+$/.test(raw) && Number.isInteger(n) ? n : null
}

/**
 * Данные грузит роутер (B2.3): фишу — из пути, осмотр — из `?exam=` ТЕКУЩЕГО
 * адреса. Владелец «какой осмотр» — адрес, и больше никто; на экране — эхо
 * сервера (`model.exam`): чужой или несуществующий номер он сводит к свежему.
 */
export const loadPerio: RouteLoad<PerioModel> = (signal, params, q) =>
  perio.get(Number(params.pid), examOf(q), signal)

export function PerioScreen({ pid, navigate = defaultNavigate }: Props) {
  const { state, pending, retry, replace, leaveIfSignedOut } = useRouteLoad<PerioModel>(navigate)
  const to = useNavigate()
  const target = useNavigation().location
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const say = useCallback((x: ToastState) => setToast(x), [])
  const fail = useCallback((e: unknown) => {
    const err = asApiError(e)
    if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
  }, [leaveIfSignedOut])
  const data = state.status === 'ready' ? state.data : null
  /* ⛔ Переход к ДРУГОМУ осмотру ждёт загрузчика, а роутер тем временем держит
     прежний. Его не показывать: набранная в этот миг цифра ушла бы в запись,
     которую человек только что покинул. Ответ POST (новый или оставшийся
     осмотр) уже И ЕСТЬ тот, куда ведёт адрес, — он остаётся на экране, как и
     до роутера. */
  const leaving = pending && data !== null
    && examOf(new URLSearchParams(target?.search ?? '')) !== (data.exam?.id ?? null)
  const model = leaving ? null : data
  const c = usePerio(pid, model, replace, fail, say)
  const root = useRef<HTMLDivElement>(null)

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }
  if (!model) {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const base = `/admin/patient/${pid}`
  const cells = () =>
    Array.from(root.current?.querySelectorAll<HTMLInputElement>('.pcell input[data-k]') ?? [])

  /** Следующая точка по порядку листа — тем же порядком, что диктуют вслух. */
  const advance = (el: HTMLInputElement) => {
    const all = cells()
    const next = all[all.indexOf(el) + 1]
    if (next) { next.focus(); next.select() }
  }

  const onCell = (n: number, kind: Kind, i: number, raw: string, el: HTMLInputElement) => {
    let digits = raw.replace(/\D+/g, '').slice(0, 2)
    let value = digits ? Number(digits) : 0
    if (value > model.limits.mm_max) {
      digits = digits.slice(0, 1)
      value = digits ? Number(digits) : 0
    }
    c.setCell(n, kind, i, value)
    // «1» ждёт вторую цифру, всё остальное уже готово: без этого правила
    // ассистент жмёт Tab сто девяносто два раза
    if (digits.length === 2 || (value >= 2 && value <= 9)) advance(el)
  }

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const el = e.target as HTMLInputElement
    if (el.tagName !== 'INPUT' || !el.dataset.k) return
    if (e.ctrlKey || e.metaKey || e.altKey) return
    if (e.key === 'b' || e.key === 'B') {
      e.preventDefault()
      if (el.dataset.k === 'pd') c.toggleBop(Number(el.dataset.n), Number(el.dataset.i))
      return
    }
    if (e.key === 'Enter') { e.preventDefault(); advance(el) }
  }

  const pickTooth = (n: number) => {
    root.current?.querySelector<HTMLInputElement>(
      `.ptooth[data-tooth="${n}"] .pcell input[data-k="pd"]`)?.focus()
  }

  /** Адрес листа: осмотр виден в ссылке, поэтому F5 и «открыть ещё раз»
   *  возвращают туда же, а не к самому свежему. Пишет его РОУТЕР, и загрузчик
   *  читает уже новый адрес. `replace`, как и было: смена осмотра не копит
   *  шаги «Назад». Query — заново: `msg` прошлого адреса повторил бы плашку. */
  const goTo = (id: number | null, now = false) => {
    void to(`${base}/parodontograma${id ? `?exam=${id}` : ''}`, { replace: true, flushSync: now })
  }

  const goExam = (id: number) => {
    // ⛔ Сначала В ЗАГРУЗКУ, потом запрос: иначе прежний осмотр висит на экране
    // весь ответ, а набранная в этот миг цифра уходит в него — в запись,
    // которую человек только что покинул. Загрузку рисует `leaving`, а
    // `flushSync` ставит её на экран ещё в этом событии, как это делал reset().
    goTo(id, true)
  }

  /* После POST ответ уже на экране (`replace`); адрес ведёт к ЕГО осмотру по
     номеру, и загрузчик перечитывает именно его, а не «самый свежий», который
     могло тем временем завести второе рабочее место. */
  const afterExam = (m: PerioModel | null) => {
    if (m) goTo(m.exam?.id ?? null)
  }

  const arch = (teeth: number[], lower?: boolean) => (
    <div className="pscroll">
      <div className="parch">
        {teeth.map((n) => (
          <PerioTooth
            key={n}
            n={n}
            row={c.row(n)}
            meta={model.teeth[String(n)] ?? { state: 'ok', absent: false, title: String(n), svg: { frontal: '', occlusal: '' } }}
            limits={model.limits}
            sites={model.sites}
            grades={model.grades}
            {...(lower ? { lower: true } : {})}
            onCell={onCell}
            onBop={c.toggleBop}
            onGrade={c.setGrade}
            onPick={pickTooth}
          />
        ))}
      </div>
    </div>
  )

  const head = (
    <div className="odop-top">
      <AppLink className="odop-back" href={`${base}?tab=odonto`}><Icon name="pat" /> {model.patient.name}</AppLink>
      <h2>{T.title} <small>· {T.sub}</small></h2>
      <div className="odo-actions">
        {model.exams.length > 0 && (
          <select
            className="pexam"
            value={String(model.exam?.id ?? '')}
            title="Examen"
            aria-label="Examen"
            onChange={(e) => goExam(Number(e.target.value))}
          >
            {model.exams.map((x) => (
              <option key={x.id} value={String(x.id)}>{x.at} · {x.teeth} dinți</option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="odo-more"
          disabled={c.busy}
          onClick={() => { void c.newExam().then(afterExam) }}
        >
          <Icon name="plus" /> {T.newExam}
        </button>
        <AppLink className="odo-more" href={`${base}/odontograma`}><Icon name="tooth" /> {T.odo}</AppLink>
        {model.exam && (
          /* ⛔ Без target="_blank": окно программы отдаёт «новое окно»
             системному браузеру, где нет куки входа — см. AnamnezaCard. */
          <AppLink
            className="odo-more"
            href={`${base}/parodontograma/print?exam=${model.exam.id}`}
          >
            <Icon name="print" /> {T.print}
          </AppLink>
        )}
      </div>
    </div>
  )

  if (!model.exam) {
    return (
      <section className="dp-react-root">
        <div className="perio">
          {head}
          <div className="fcard pempty">
            <p>{T.none}</p>
            <button
              type="button"
              className="pl-btn primary"
              disabled={c.busy}
              onClick={() => { void c.newExam().then(afterExam) }}
            >
              <Icon name="plus" /> {T.firstExam}
            </button>
          </div>
        </div>
        {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
      </section>
    )
  }

  const empty = model.exam.teeth === 0 && !c.dirty

  return (
    <section className="dp-react-root">
      <div className="perio" ref={root}>
        {head}
        <div className="pgrid">
          <div className="fcard">
            <p className="hint">{T.hint}</p>
            {/* Клавиши листа — делегатом на обёртке дуг: обработчик один на
                384 поля, и «b» работает из той точки, где стоит курсор. */}
            <div onKeyDown={onKey}>
              {arch(model.arches.upper)}
              <div className="pmid"><span>{T.upper}</span><i /><span>{T.lower}</span></div>
              {arch(model.arches.lower, true)}
            </div>
            <div className="pfoot">
              <label>
                {T.doctor}
                <select value={c.doctor} onChange={(e) => c.setDoctor(e.target.value)} aria-label={T.doctor}>
                  <option value="">—</option>
                  {model.doctors.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </label>
              <label className="pnote">
                {T.note}
                <input
                  type="text"
                  maxLength={200}
                  value={c.note}
                  placeholder={T.notePh}
                  onChange={(e) => c.setNote(e.target.value)}
                  /* Старая страница была ФОРМОЙ, и Enter из заметки записывал
                     осмотр неявной отправкой. Экран формы не имеет — возвращаем
                     то же поведение руками. */
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter') return
                    e.preventDefault()
                    if (c.dirty && !c.busy) void c.save()
                  }}
                />
              </label>
              <button
                type="button"
                className="pl-btn primary"
                /* ⚠️ Нечего записывать — кнопка заперта: каждая запись пишет
                   строку в летопись пациента, и три клика подряд оставили бы
                   три одинаковые записи «кто что сделал». */
                disabled={c.busy || !c.dirty}
                onClick={() => { void c.save() }}
              >
                <Icon name="save" /> {T.save}
              </button>
              {c.dirty && (
                <>
                  <button type="button" className="pl-btn" disabled={c.busy} onClick={c.discard}>{T.discard}</button>
                  <span className="dp-draft">{T.unsaved}</span>
                </>
              )}
              {empty && model.exams.length > 1 && (
                <button
                  type="button"
                  className="odo-more"
                  disabled={c.busy}
                  onClick={() => {
                    const id = model.exam?.id
                    if (id) void c.dropExam(id).then(afterExam)
                  }}
                >
                  {T.dropEmpty}
                </button>
              )}
            </div>
          </div>
          <PerioSummaryCard summary={c.summary} limits={model.limits} />
        </div>
      </div>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
