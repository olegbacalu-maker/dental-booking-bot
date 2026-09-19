import { useEffect, useLayoutEffect, useState } from 'react'

/**
 * То, что панель считает В БРАУЗЕРЕ, и почему это не уехало на сервер.
 *
 * Две разные причины, и путать их нельзя.
 * ⭐ Высота часа и ступени сжатия блока — потому что их решает ОКНО. Высоту
 * ряда выбирает `fitGrid` из вьюпорта, поэтому получасовая запись на ноутбуке
 * клиники и на большом мониторе — разные пиксели, и порог числом («короче 55
 * минут») соврал бы на одном из двух. Правило спрашивает браузер: влез текст
 * или нет (`scrollHeight > clientHeight`). Побочная выгода — ни одной
 * магической цифры: поменяются кегль или padding, и правило подстроится само.
 * ⭐ Линия «сейчас» и минуты ожидания — потому что они меняются НЕПРЕРЫВНО.
 * Серверная строка с минутами делала бы отпечаток живого состояния всегда
 * другим, и подмена шла бы каждые 12 секунд на неизменном дне — мигание,
 * от которого ушли 08-20, вернулось бы чёрным ходом.
 */

/* ⚠️ Пол 66, а не 56, и это ЗАМЕРЕНО браузером на 1920/1600/1366, а не
   посчитано (08-17). Пол задаёт высоту блока (пол минус 6), а от неё зависит,
   останется ли визит двустрочным: при 56 блок 50px, а имени, строке
   «время · услуга» и бейджу нужно 57 — блок схлопывался в одну строку, и
   услуга читалась приписанной к имени. Цена названа честно: на 1600 и 1366
   без прокрутки видно на час меньше. */
export const CELL_MIN = 66
/* ⚠️ Потолок обязателен: у клиники с коротким днём (три-четыре часа) рельс
   той же длины раздул бы час до сотен пикселей, и один визит занял бы
   пол-экрана. */
export const CELL_MAX = 96

/**
 * Высота часа в пикселях. Чистая функция: все замеры делает вызывающий.
 *
 * ⛔ `over` применяется ТОЛЬКО когда ниже всех кончается сама сетка. Правая
 * колонка длиннее её почти всегда, и отнятые у часа пиксели не убирали
 * прокрутку ни на один — страница всё равно длиной с соседа. Платили за это
 * дырой ПОД сеткой: замер дал 360px пустоты (08-12).
 */
export function cellPx(avail: number, hours: number, over = 0): number {
  const n = Math.max(1, hours)
  const c = Math.max(CELL_MIN, Math.min(CELL_MAX, Math.floor(avail / n)))
  return over > 0 ? Math.max(CELL_MIN, c - Math.ceil(over / n)) : c
}

/**
 * «Сколько ждёт в приёмной». `null` — молчим.
 *
 * ⚠️ Первые пять минут тишина намеренно: «пришёл и почти сразу позвали»
 * ожиданием не считается, а «așteaptă 0 min» на каждом пришедшем — шум
 * (просьба Олега 08-21).
 */
export function waitLabel(since: number, now: number): { text: string; long: boolean } | null {
  const m = Math.max(0, Math.floor((now - since) / 60_000))
  if (m < 5) return null
  return { text: `așteaptă ${m} min`, long: m >= 15 }
}

/** Часы клиники сейчас. ⛔ Пояс — КЛИНИКИ, а не устройства: в облаке через
 *  туннель браузер живёт в своём поясе, и линия по часам устройства стояла бы
 *  на чужом часе. Пояс лежит в подвале сайдбара — он серверный и на
 *  React-странице тоже. */
export function clinicNow(tz: string, at: Date): { day: string; hh: number; mm: number } {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz || undefined, hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    }).formatToParts(at)
    const m: Record<string, string> = {}
    for (const p of parts) m[p.type] = p.value
    return { day: `${m.year}-${m.month}-${m.day}`, hh: +(m.hour ?? 0), mm: +(m.minute ?? 0) }
  } catch {
    /* пояс не знаком движку — часы устройства лучше пустоты */
    const p2 = (n: number) => String(n).padStart(2, '0')
    return {
      day: `${at.getFullYear()}-${p2(at.getMonth() + 1)}-${p2(at.getDate())}`,
      hh: at.getHours(), mm: at.getMinutes(),
    }
  }
}

/**
 * Где линия «сейчас», В ДОЛЯХ ЯЧЕЙКИ от верха сетки. `null` — линии нет.
 *
 * ⛔ Доли, а не пиксели, и это то же разделение, что у блоков: множитель
 * считает код, высоту ячейки — CSS (`--cell`). Верни отсюда пиксели — и
 * значение пришлось бы держать в состоянии React, то есть пересчитывать
 * раскладку через рендер, а при каждом `resize` получать лишний кадр.
 * ⛔ Строка ищется по НОМЕРУ ЧАСА в списке рядов, а не по индексу от начала
 * дня: крайние закрытые часы срезаны в полоски, и «час минус первый час»
 * промахнулся бы ровно на дне со сдвинутым графиком.
 */
export function nowlineRows(
  hours: number[], day: string, at: { day: string; hh: number; mm: number },
): number | null {
  if (day !== at.day) return null
  const row = hours.indexOf(at.hh)
  if (row < 0) return null                       // час вне сетки дня
  return row + at.mm / 60
}

/** Пояс клиники из подвала сайдбара (серверная разметка каркаса). */
export function clinicTz(): string {
  return document.getElementById('sf_clock')?.getAttribute('data-tz') ?? ''
}

/**
 * Часы тикают — экран пересчитывает то, что зависит от «сейчас».
 * ⚠️ Два разных периода, как в старом коде: линия — раз в 30 с, минуты
 * ожидания — раз в минуту. Один общий тик в 30 с перерисовывал бы ожидание
 * вдвое чаще нужного, а в 60 с двигал бы линию рывками по полтора пикселя.
 */
export function useClockTick(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}

/**
 * Высота часа под окно: сетка дотягивается до низа правой колонки.
 *
 * ⛔ Обе опоры снимаются ДО растяжения и в координатах ДОКУМЕНТА (плюс
 * scrollY). Иначе расчёт зависит от собственного результата: замерив зазор
 * ПОСЛЕ того, как сам растянул сетку, получаешь обратную связь — час подрастал
 * на пиксель за каждый вызов. А `getBoundingClientRect().top` живёт в
 * координатах ОКНА и меняется от одной лишь прокрутки: у прокрученной вниз
 * страницы он уходит в минус, и час раздувался «сам собой» (08-17).
 * ⛔ Конец СОДЕРЖИМОГО рельса, а не его коробки: рельс — элемент того же
 * flex-ряда и растягивается вслед за сеткой.
 */
export function useFitGrid(
  body: React.RefObject<HTMLDivElement | null>,
  rail: React.RefObject<HTMLDivElement | null>,
  hours: number,
): void {
  /* ⚠️ Слой раскладки, а не эффект: час обязан встать ДО первой отрисовки,
     иначе сетка успевает мигнуть полом 66 и подпрыгнуть.
     ⛔ Результат уходит в CSS-переменную, а НЕ в состояние React: величина
     нужна только оформлению, а состояние дало бы лишний рендер на каждый
     resize и каскад «эффект → рендер → эффект». */
  useLayoutEffect(() => {
    const fit = () => {
      const gb = body.current
      if (!gb || hours < 1) return
      gb.style.setProperty('--cell', `${CELL_MIN}px`)
      const sy = window.scrollY
      const top0 = gb.getBoundingClientRect().top + sy
      const last = rail.current?.lastElementChild ?? rail.current
      const railEnd = last ? last.getBoundingClientRect().bottom + sy : 0
      const avail = Math.max(window.innerHeight - top0 - 24, railEnd - top0)
      gb.style.setProperty('--cell', `${cellPx(avail, hours)}px`)
      /* ужимать час имеет смысл, только если страницу распирает САМА сетка */
      const railLower = rail.current
        && rail.current.getBoundingClientRect().bottom > gb.getBoundingClientRect().bottom
      const over = railLower ? 0 : document.documentElement.scrollHeight - window.innerHeight
      gb.style.setProperty('--cell', `${cellPx(avail, hours, over)}px`)
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [body, rail, hours])
}

/**
 * Ступени сжатия блока: `slim` → `tiny` → `bare`, каждая следующая только
 * если предыдущая не влезла.
 *
 * ⚠️ Ступень «только имя» появилась не сразу, и её отсутствие стоило релиза:
 * блок в 0.4 ячейки проваливался мимо slim прямо в «текста нет», и короткая
 * запись стояла в журнале безымянным пятном.
 * ⚠️ Перемер зависит от минут ожидания: текст «așteaptă N min» вписывается
 * ПОСЛЕ замера, и блок на грани переполняется — поэтому `tick` в зависимостях.
 */
export function useFitAppts(
  body: React.RefObject<HTMLDivElement | null>, tick: number, deps: unknown,
): void {
  useLayoutEffect(() => {
    const gb = body.current
    if (!gb) return
    for (const a of gb.querySelectorAll<HTMLElement>('.gappt')) {
      a.classList.remove('slim', 'tiny', 'bare')
      if (a.scrollHeight > a.clientHeight) a.classList.add('slim')
      if (a.scrollHeight > a.clientHeight) a.classList.add('tiny')
      if (a.scrollHeight > a.clientHeight) a.classList.add('bare')
    }
  }, [body, tick, deps])
}
