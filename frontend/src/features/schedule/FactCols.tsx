import { Icon, iconName } from '../../components/Icon'
import { dm } from '../../utils/date'
import type { VisitFacts } from './day'

/* Карточка визита дня ОДНОГО врача: три колонки справа от имени (22.10,
   вариант A Олега; макет и кадры — design/doctor-day). Риски фиши и
   анамнеза; план с номерами зубов; история — какой визит и прошлый визит.
   Колонки одинаковые у всех визитов дня: день читается таблицей сверху
   вниз, аллергия у всех в одном и том же месте.
   ⛔ Денег здесь нет (Олег 22.10: «не думаю что врачу эта информация
   нужна») — сервер их и не присылает; долг — в фише и у статистики.

   ⛔ Колонки стоят АБСОЛЮТНО в своей полосе блока (app.css › `.vf`) и высоту
   блока не растят: ступени сжатия `useFitAppts` те же, что без них. Не
   влезшие строки колонки уходят в «+N» тем же проходом (`dashFx.fitFacts`),
   а не режутся краем: на кадре макета пятая строка у 90-минутного визита
   стояла срезанной снизу, и замер блока этого не видел.
   ⛔ Риски сведены без дублей СЕРВЕРОМ (`core.risks.merge`); здесь они только
   рисуются. Давность прошлого визита — от дня ЭКРАНА, не от часов: ответ
   сервера «сейчас» не несёт, и день, открытый завтра, читается так же. */

const T = {
  newP: 'Pacient nou',
  nth: (n: number) => `vizita a ${n}-a`,
  last: 'ultima',
  noAnam: 'Anamneză necompletată',
  denies: 'Neagă afecțiunile din chestionar',
  filledOn: 'completat',
  noRisk: 'fără riscuri',
  noPlan: 'fără plan activ',
  inWork: 'în lucru',
  risks: 'Atenționări',
  plan: 'Plan de tratament',
  hist: 'Istoric',
} as const

/** Давность словами: дни между прошлым визитом и днём экрана. */
export function ago(days: number): string {
  if (days <= 0) return 'azi'
  if (days === 1) return 'ieri'
  if (days < 14) return `acum ${days} zile`
  if (days < 60) return `acum ${Math.round(days / 7)} săpt.`
  if (days < 365) {
    const m = Math.round(days / 30)
    return m <= 1 ? 'acum o lună' : `acum ${m} luni`
  }
  const y = Math.floor(days / 365)
  return y === 1 ? 'acum un an' : `acum ${y}${y >= 20 ? ' de' : ''} ani`
}

/** Дни между двумя ISO-датами. ⚠️ Полдень, как `utils/date.shift`: полночь
 *  в поясе восточнее UTC уехала бы на сутки. */
function daysBetween(from: string, to: string): number {
  const t = (iso: string) => new Date(`${iso}T12:00:00`).getTime()
  return Math.round((t(to) - t(from)) / 86_400_000)
}

/** Дата прошлого визита: «12.08» в году экрана, «12.08.2025» — в другом. */
function lastDay(iso: string, date: string): string {
  return iso.slice(0, 4) === date.slice(0, 4) ? dm(iso) : `${dm(iso)}.${iso.slice(0, 4)}`
}

/** Дата опроса анамнеза — всегда с годом: опросник бывает старше года. */
const dmy = (iso: string) => `${dm(iso)}.${iso.slice(0, 4)}`

/** Позиции плана по процедуре: «45 46 Obturație compozit»; «în lucru» — у
 *  группы, где хоть одна позиция в работе. */
function planGroups(x: VisitFacts) {
  const by = new Map<string, { teeth: number[]; work: boolean }>()
  for (const p of x.plan) {
    const g = by.get(p.proc) ?? { teeth: [], work: false }
    if (p.tooth !== null && !g.teeth.includes(p.tooth)) g.teeth.push(p.tooth)
    g.work ||= p.work
    by.set(p.proc, g)
  }
  return [...by.entries()]
}

/** `date` — день экрана: от него давность прошлого визита. */
export function FactCols({ x, date }: { x: VisitFacts; date: string }) {
  const groups = planGroups(x)
  return (
    <span className="vf">
      <span className="vf-col" aria-label={T.risks}>
        {x.risks.map((r, i) => (
          <span key={i} className={`vf-chip ${r.tone}`} title={r.title}>
            {r.icon ? <Icon name={iconName(r.icon)} /> : null}{r.text}
          </span>
        ))}
        {!x.anam && <span className="vf-chip grey">{T.noAnam}</span>}
        {/* третье состояние (23.10): собран, рисков нет, заявил, что здоров —
            серое слово медзаписи и дата опроса второй строкой (в «+N» уходит
            с полным текстом из title) */}
        {x.anam && !x.risks.length && x.denies && (
          <>
            <span className="vf-chip grey" title={`${T.denies} · ${T.filledOn} ${dmy(x.denies)}`}>{T.denies}</span>
            <span className="vf-muted" title={`${T.filledOn} ${dmy(x.denies)}`}>{T.filledOn} {dmy(x.denies)}</span>
          </>
        )}
        {x.anam && !x.risks.length && !x.denies && <span className="vf-muted">{T.noRisk}</span>}
        <span className="vf-more" />
      </span>
      <span className="vf-col vf-plan" aria-label={T.plan}>
        {groups.length
          ? groups.map(([proc, g]) => (
              <span key={proc} className="vf-pl" title={g.work ? `${proc} · ${T.inWork}` : proc}>
                {g.teeth.map((n) => <span key={n} className={`vf-tn${g.work ? ' work' : ''}`}>{n}</span>)}
                <span className="vf-proc">{proc}</span>
              </span>
            ))
          : <span className="vf-muted">{T.noPlan}</span>}
        <span className="vf-more" />
      </span>
      <span className="vf-col vf-hist" aria-label={T.hist}>
        {x.nth <= 1
          ? <span className="vf-chip green"><Icon name="user" />{T.newP}</span>
          : <span className="vf-nth">{T.nth(x.nth)}</span>}
        {x.last && (
          <span className="vf-last">
            {T.last} {lastDay(x.last.date, date)} <i>· {ago(daysBetween(x.last.date, date))}</i>
          </span>
        )}
        {x.last && <span className="vf-last vf-what" title={x.last.what}>{x.last.what}</span>}
        <span className="vf-more" />
      </span>
    </span>
  )
}
