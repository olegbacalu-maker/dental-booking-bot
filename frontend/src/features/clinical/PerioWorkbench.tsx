import { useRef, type KeyboardEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { PerioSummaryCard } from './PerioSummary'
import { PerioTooth } from './PerioTooth'
import type { PerioModel } from './perio'
import type { Kind, PerioApi } from './usePerio'

/* Лист пародонтограммы (C23; с 26.09 ОДИН на два места): датированный осмотр,
   шесть точек на зуб, итог справа — раскладка и классы старой страницы (.perio,
   .pgrid, .parch, .ptooth, .pcell, .pfoot, .psum). Страница `/parodontograma`
   показывает его на всю ширину (рельс даёт сервер), вкладка Parodontogramă
   фиши — внутри рабочего места (B6, шаг 3). Контроллер (`usePerio`) живёт у
   ВЛАДЕЛЬЦА листа, не здесь: черновик обязан пережить смену осмотра, когда лист
   на миг снят с экрана.

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
  full: 'Pe tot ecranul',
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
} as const

interface Props {
  pid: number
  model: PerioModel
  c: PerioApi
  /** переход к другому осмотру — адресом владельца (`?exam=`) */
  goExam: (id: number) => void
  /** после POST: адрес ведёт к осмотру из ответа (новому или оставшемуся) */
  afterExam: (m: PerioModel | null) => void
  /** внутри фиши: без обратной ссылки и заголовка, со ссылкой «Pe tot ecranul» */
  embedded?: boolean
}

export function PerioWorkbench({ pid, model, c, goExam, afterExam, embedded = false }: Props) {
  const root = useRef<HTMLDivElement>(null)
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
      {!embedded && (
        <AppLink className="odop-back" href={`${base}?tab=perio${model.exam ? `&exam=${model.exam.id}` : ''}`}>
          <Icon name="pat" /> {model.patient.name}
        </AppLink>
      )}
      {!embedded && <h2>{T.title} <small>· {T.sub}</small></h2>}
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
        {!embedded && <AppLink className="odo-more" href={`${base}/odontograma`}><Icon name="tooth" /> {T.odo}</AppLink>}
        {embedded && (
          <AppLink className="odo-more" href={`${base}/parodontograma${model.exam ? `?exam=${model.exam.id}` : ''}`}>
            <Icon name="eye" /> {T.full}
          </AppLink>
        )}
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
    )
  }

  const empty = model.exam.teeth === 0 && !c.dirty

  return (
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
  )
}
