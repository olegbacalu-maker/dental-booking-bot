import { useEffect, useState } from 'react'
import { day } from './day'

/* Галочка «SMS reminder» окна записи (Олег 19.10): регистратор спросил
   пациента и сразу отметил, не ища фишу. Одна на оба окна — `AddDialog`
   (день журнала и окно шапки) и `SlotDialog` (пустой час).

   Хранится ОДНИМ полем — `patients.sms_off` (отказ), тем же, что пишет фиша
   «Fără remindere SMS»; галочка = НЕ отказ.
   ⛔ Видна, только когда форма сказала `sms` (сервер: пакет работает И у
   вошедшего право `PERM_SMS`; врач её не видит, Олег 22.10).
   ⭐ Показывает того, в чью карточку ляжет запись: по номеру спрашивается
   `/schedule/sms-of` (правило выбора пациента — серверное, то же, что у
   записи); новый номер — стоит.
   ⛔ В тело записи уходит только ТРОНУТАЯ галочка (прайор 08-16 и `covers`:
   экран сообщает о тронутом, а не о показанном). Пока ответ про номер в
   пути, галочка показывает «новый» — отправь она показанное, быстрый ввод
   включил бы SMS пациенту, который от них отказался. Нетронутая — поля нет,
   сервер `sms_off` не трогает.
   ⚠️ Выбор человека переживает правку номера: отмечают согласие того, кто
   стоит у стойки, а номер чаще всего правят опечаткой.
   ⚠️ «fără telefon» выключает галочку: без номера напоминать некуда. */
const T = {
  label: 'SMS reminder',
} as const

/** Цифр в номере, с которых есть смысл спрашивать (как `bad_phone` сервера). */
const MIN_DIGITS = 6

export interface SmsBox {
  /** Рисовать ли галочку вообще. */
  on: boolean
  checked: boolean
  disabled: boolean
  set: (v: boolean) => void
  /** Добавка к телу записи: `{ sms }` только у тронутой галочки. */
  field: { sms?: boolean }
}

/** `form` — флаг формы окна; нет флага — галочки нет. */
export function useSmsBox(form: boolean | undefined, phone: string, noPhone: boolean,
  delayMs = 250): SmsBox {
  const on = form === true
  const [pick, setPick] = useState<boolean | null>(null)
  const [seen, setSeen] = useState<{ digits: string; sms: boolean } | null>(null)
  const digits = phone.replace(/\D/g, '')
  const ask = on && !noPhone && digits.length >= MIN_DIGITS

  useEffect(() => {
    if (!ask) return
    const ctl = new AbortController()
    const timer = window.setTimeout(() => {
      day.smsOf(digits, ctl.signal).then(
        (r) => { if (!ctl.signal.aborted) setSeen({ digits, sms: r.data.sms }) },
        /* не ответил — показ остаётся «новый»; писать всё равно будет
           только тронутое */
        () => {},
      )
    }, delayMs)
    return () => { window.clearTimeout(timer); ctl.abort() }
  }, [ask, digits, delayMs])

  const known = seen !== null && seen.digits === digits ? seen.sms : true
  return {
    on,
    checked: !noPhone && (pick ?? known),
    disabled: noPhone,
    set: setPick,
    field: on && !noPhone && pick !== null ? { sms: pick } : {},
  }
}

export function SmsCheck({ box }: { box: SmsBox }) {
  if (!box.on) return null
  return (
    <label className="nophone">
      <input type="checkbox" checked={box.checked} disabled={box.disabled}
             onChange={(e) => box.set(e.target.checked)} /> {T.label}
    </label>
  )
}
