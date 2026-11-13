import { useState } from 'react'

/* «Durată»: один выбор на окна записи, окно визита и строку услуги в
   настройках; быстрые значения и правило «другой» приезжают с сервера.

   В окнах записи поле едет на сервер только тронутым: тронутое ложится с
   признаком «задана руками», и смена процедуры его не перебьёт. */

const T = {
  dur: 'Durată',
  other: 'Altă durată…',
  min: 'min',
  rule: (step: number, max: number) => `din ${step} în ${step} minute, cel mult ${max}`,
} as const

export interface DurRule {
  durations: number[]
  step: number
  max: number
}

interface RuleFields {
  durations?: number[]
  dur_step?: number
  dur_max?: number
}

export function durRule(v: RuleFields): DurRule {
  return { durations: v.durations ?? [], step: v.dur_step ?? 5, max: v.dur_max ?? 240 }
}

export function durOk(n: number, rule: DurRule): boolean {
  return Number.isInteger(n) && n >= rule.step && n <= rule.max && n % rule.step === 0
}

interface FieldProps {
  rule: DurRule
  value: number
  onPick: (minutes: number) => void
  label?: string
  disabled?: boolean
  autoFocus?: boolean
}

const OTHER = 'other'

export function DurField({ rule, value, onPick, label = T.dur, disabled, autoFocus }: FieldProps) {
  const [other, setOther] = useState(false)
  const [text, setText] = useState('')
  if (!rule.durations.length) return null
  const quick = rule.durations.includes(value)
  /* значение вне быстрых стоит первой строкой, иначе поле показало бы чужое число */
  const list = quick || !value || other ? rule.durations : [value, ...rule.durations]
  const bad = other && !durOk(value, rule)
  const hint = T.rule(rule.step, rule.max)

  function fromList(raw: string) {
    if (raw === OTHER) {
      setOther(true)
      setText(value ? String(value) : '')
      return
    }
    setOther(false)
    onPick(Number(raw))
  }

  function typed(raw: string) {
    const digits = raw.replace(/\D/g, '').slice(0, 3)
    setText(digits)
    onPick(digits ? Number(digits) : 0)
  }

  return (
    <span className={`dp-durf${other ? ' open' : ''}`}>
      <select className="dp-dur" value={other ? OTHER : value} aria-label={label} title={label}
              disabled={disabled} autoFocus={autoFocus && !other}
              onChange={(e) => fromList(e.target.value)}>
        {value || other ? null : <option value={0} disabled>{label}</option>}
        {list.map((d) => <option key={d} value={d}>{d} {T.min}</option>)}
        <option value={OTHER}>{T.other}</option>
      </select>
      {other ? (
        <>
          <input className="dp-dur-n" type="text" inputMode="numeric" value={text}
                 aria-label={`${label} (${T.min})`} aria-invalid={bad} title={hint}
                 placeholder={T.min} disabled={disabled} autoFocus
                 onChange={(e) => typed(e.target.value)} />
          <small className={`dp-dur-rule${bad ? ' bad' : ''}`} role={bad ? 'alert' : undefined}>{hint}</small>
        </>
      ) : null}
    </span>
  )
}

interface Svc { id: string; dur?: number }

export interface DurBox {
  rule: DurRule
  value: number
  pick: (minutes: number) => void
  /** Тронутое поле держит число не по правилу — отправлять нельзя. */
  bad: boolean
  /** Добавка к телу записи: пусто, пока поле не тронуто. */
  field: { duration?: number }
}

/** `initial` — окно открыто заполненным: длительность считается тронутой. */
export function useDurPick(services: Svc[], service: string, rule: RuleFields,
  initial?: number): DurBox {
  const [picked, setPicked] = useState<number | null>(initial ?? null)
  const base = services.find((s) => s.id === service)?.dur ?? 0
  const r = durRule(rule)
  return {
    rule: r,
    value: picked ?? base,
    pick: setPicked,
    bad: picked !== null && !durOk(picked, r),
    field: picked !== null ? { duration: picked } : {},
  }
}

export function DurSelect({ box }: { box: DurBox }) {
  return <DurField rule={box.rule} value={box.value} onPick={box.pick} />
}
