import { clashAmong, type Occupies } from './move'

/**
 * Пустой час: слот, его времена и то, что нужно его диалогу.
 *
 * Времён ДВА, и выбор минуты двигает ровно одно. Запись начинается в любую
 * минуту с шагом сетки стартов, а заметка остаётся почасовой: она блокирует
 * ЧАСЫ ПРИЁМА, как и ячейки сетки. Послать ей минуты нельзя даже «на пробу»:
 * `_add_note` берёт час как `int(ntime.split(":")[0])` и молча округлит вниз —
 * экран сказал бы «с 10:30», а в базе легла бы блокировка с 10:00.
 * ⭐ Оба времени считает ОДНА функция. Пока они считались по месту в двух
 * обработчиках отправки, «минута меняет только время записи» было
 * НАМЕРЕНИЕМ; здесь это правило, и у него есть проверка (`slot.test.ts`).
 */

/** Ячейка, по которой нажали: врач и его час. */
export interface Slot {
  /** Ключ врача — `data-dk` колонки; у колонки-сироты его нет, и слота тоже. */
  dk: string
  /** Имя врача — оно стоит в заголовке диалога. */
  name: string
  /** Час ячейки, «HH:00». */
  hour: string
}

/**
 * Что нужно диалогу пустого часа — и ничего сверх.
 *
 * ⭐ Узкий вид, под который структурно ложатся и `DayForm` (день), и
 * `DashSlotForm` (панель), — ровно как `VisitCardView` под карточку визита.
 * Диалог у двух экранов ОДИН: заведи второй, и список услуг или потолок «даты
 * рождения» разойдутся у двух экранов молча, а увидеть это можно, только
 * открыв оба.
 */
export interface SlotFormView {
  services: { id: string; label: string; dur?: number }[]
  /** Быстрые значения «Durată»; нет поля — выбора нет. */
  durations?: number[]
  /** Правило «другой» длительности: шаг и потолок, минут. */
  dur_step?: number
  dur_max?: number
  /** Шаг сетки стартов, минут. */
  step?: number
  /** Потолок поля «дата рождения» — сегодня В ЧАСАХ КЛИНИКИ. */
  birth_max: string
  /** Галочка «SMS reminder» (`day.sms_box`); нет поля — галочки нет. */
  sms?: boolean
}

export interface SlotTimes {
  /** Время ЗАПИСИ: «HH:MM» — минуту и двигает выбор в окне. */
  atime: string
  /** Начало ЗАМЕТКИ: целый час, про минуты не знает. */
  ntime: string
  /**
   * Часы, которыми может кончиться блокировка: только ПОЗЖЕ начала.
   * ⚠️ Обеденный час выпал из `note_ends` ещё на сервере: при обеде 13–14
   * закончить блокировку в 14:00 нельзя, и это правило, а не дыра в списке.
   */
  ends: number[]
}

export function slotTimes(hour: string, minute: number, noteEnds: number[]): SlotTimes {
  const hh = hour.split(':')[0] ?? ''
  const start = Number(hh)
  return {
    atime: `${hh}:${String(minute).padStart(2, '0')}`,
    ntime: `${hh}:00`,
    ends: noteEnds.filter((e) => e > start),
  }
}

/** Час ячейки канвы в тот же вид, что печатал сервер (`f"{h:02d}:00"`). */
export function hourLabel(h: number): string {
  return `${String(h).padStart(2, '0')}:00`
}

/** Минуты часа, с которых может начаться запись: 0, 5, … 55 при шаге 5. */
export function hourMinutes(step: number): number[] {
  const out: number[] = []
  for (let m = 0; m < 60; m += step > 0 ? step : 5) out.push(m)
  return out
}

/** Старты часа, с которых запись длиной `dur` задела бы занятый блок колонки
 *  (`self` — переносимый визит, сам себе не помеха). Подсказка окну. */
export function takenMinutes(items: Occupies[], hour: number, dur: number,
  step: number, self = -1): Set<number> {
  const out = new Set<number>()
  for (const m of hourMinutes(step)) {
    if (clashAmong(items, hour * 60 + m, dur, self) >= 0) out.add(m)
  }
  return out
}

/**
 * Какие из двух стартов часа (`:00`, `:30`) свободны у врача — по блокам его
 * колонки канвы, тем же `clashAmong`, что считает помеху переносу (17.10).
 *
 * ⭐ Это ПОДСКАЗКА, как у диалога переноса: правду говорит сервер под своим
 * замком, пока окно открыто, час мог занять второй администратор. Подсказка
 * лишь не даёт нажать то, что по канве заведомо занято: до неё ячейка под
 * 45-минутным визитом звала «+ Programare», окно предлагало оба занятых
 * старта, а отказ «ocupat» уходил в плашку ПОД модальным окном.
 * ⚠️ Половина занята, если ЛЮБОЙ занятый блок её задевает: визит 09:00–09:45
 * занимает обе — 30-минутный слот в 09:45 канва не предлагает (шаг сетки).
 */
export interface FreeHalves {
  h0: boolean
  h30: boolean
}

export function freeHalves(items: Occupies[], hour: number): FreeHalves {
  const m = hour * 60
  return {
    h0: clashAmong(items, m, 30, -1) < 0,
    h30: clashAmong(items, m + 30, 30, -1) < 0,
  }
}

/** Значение `data-free` ячейки канвы: где рисовать «+ Programare». */
export function freeKind(f: FreeHalves): 'both' | 'top' | 'bottom' | 'none' {
  if (f.h0 && f.h30) return 'both'
  if (f.h0) return 'top'
  if (f.h30) return 'bottom'
  return 'none'
}
