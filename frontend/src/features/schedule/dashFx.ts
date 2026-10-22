import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react'

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
export const CELL_MIN = 64
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
/** С какой минуты ожидание показывается (раньше — тишина, см. ниже). */
export const WAIT_SHOW_MIN = 5
/** С какой минуты ожидание — «засиделся», красным. ⛔ Порог ОДИН на повестку,
 *  сетку и вкладки потока (`flow.ts`); у старой страницы — тот же в panel.js. */
export const WAIT_LONG_MIN = 15

export function waitLabel(since: number, now: number): { text: string; long: boolean } | null {
  const m = Math.max(0, Math.floor((now - since) / 60_000))
  if (m < WAIT_SHOW_MIN) return null
  return { text: `așteaptă ${m} min`, long: m >= WAIT_LONG_MIN }
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
 * Вид карточки визита — атрибут `<html data-card>` (Setări › Aspect, 03.10).
 *
 * ⚠️ Подпиской, а не чтением атрибута при отрисовке: от вида зависит, влез ли
 * текст, то есть ступени сжатия ниже. А голову ЧУЖОГО адреса кладёт слой
 * раскладки оболочки (App.tsx › Frame) — уже ПОСЛЕ перемера блоков того же
 * кадра, потому что эффекты детей идут раньше родительских. Без подписки
 * ступени оставались бы посчитанными под прежний вид до следующего опроса.
 */
export function useCardView(): string {
  return useSyncExternalStore(onCardView, cardView)
}

function cardView(): string {
  return document.documentElement.dataset.card ?? ''
}

function onCardView(changed: () => void): () => void {
  const mo = new MutationObserver(changed)
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-card'] })
  return () => mo.disconnect()
}

/**
 * Ступени сжатия блока, каждая следующая только если предыдущая не влезла:
 * полный вид → `slim duo` (две строки: имя со временем и статусом, под ними
 * услуга) → `slim` (одна строка) → `tiny` (только имя) → `bare`.
 *
 * ⭐ Две строки — разновидность сжатого вида, а не своя ступень рядом: блок
 * несёт и `slim`, поэтому правила полного вида (`:not(.slim)`) его не задевают.
 * До 13.10 ступени не было, и визит на 45 минут на ноутбуке (блок 42 px)
 * стоял одной строкой с пустотой под ней.
 * ⚠️ Ступень «только имя» появилась не сразу, и её отсутствие стоило релиза:
 * короткий блок проваливался мимо slim прямо в «текста нет», и запись стояла
 * в журнале безымянным пятном.
 * ⚠️ Перемер зависит от минут ожидания: текст «așteaptă N min» вписывается
 * ПОСЛЕ замера, и блок на грани переполняется — поэтому `tick` в зависимостях.
 * ⛔ Ступени ставятся МИМО React (classList), а React, меняя className блока,
 * переписывает его целиком и стирает их. Всё, что меняет className без новой
 * модели, — в зависимостях (`marks`): подсветка приехавшей записи `fresh`
 * ставится и снимается таймером, и до 14.10 новая запись на открытом дне
 * стояла в полном виде с обрезанной услугой — до перелистывания дня.
 */
export function useFitAppts(
  body: React.RefObject<HTMLDivElement | null>, tick: number, deps: unknown, view = '',
  marks: unknown = null,
): void {
  useLayoutEffect(() => {
    const gb = body.current
    if (!gb) return
    const over = (a: HTMLElement) => a.scrollHeight > a.clientHeight
    for (const a of gb.querySelectorAll<HTMLElement>('.gappt')) {
      a.classList.remove('slim', 'duo', 'tiny', 'bare')
      if (over(a)) a.classList.add('slim', 'duo')
      if (over(a)) a.classList.remove('duo')
      if (over(a)) a.classList.add('tiny')
      if (over(a)) a.classList.add('bare')
      fitFacts(a)
    }
  }, [body, tick, deps, view, marks])
}

/**
 * Колонки фактов карточки дня врача (22.10, вариант A, `FactCols`): строки,
 * не влезшие в колонку, прячутся С КОНЦА (`vf-cut`), а у последней видимой
 * встаёт «+N» с их текстом в подсказке.
 *
 * ⛔ Зовётся ПОСЛЕ ступени блока, в том же проходе: высоту колонки задаёт
 * ступень (полный вид — колонка строк, сжатый — одна строка), и мерить её
 * раньше — значит мерить не ту колонку.
 * ⛔ Колонка стоит абсолютно с `overflow:hidden` и `scrollHeight` блока не
 * растит — поэтому ступень её не видит, и без этого прохода строка резалась
 * бы краем молча (кадр A-zoom макета: пятая строка у 90-минутного визита).
 * Переполнение колонки мерится У НЕЁ САМОЙ — по высоте и по ширине (сжатый
 * вид — строка, и там лишнее уходит вбок). Первая строка остаётся всегда:
 * она режется своим многоточием, а не пропадает.
 * ⚠️ Мимо React, как и ступени: React не знает про `vf-cut`, и потому
 * перемер идёт на каждую новую модель — тем же эффектом.
 * Скрытое правилами вида (`display:none` в сжатом) в «+N» не считается.
 */
export function fitFacts(a: HTMLElement): void {
  for (const col of a.querySelectorAll<HTMLElement>('.vf-col')) {
    const more = col.querySelector<HTMLElement>(':scope > .vf-more')
    if (!more) continue
    col.classList.remove('cut')
    more.classList.remove('on')
    more.textContent = ''
    more.removeAttribute('title')
    more.style.removeProperty('top')
    const kids = Array.from(col.children).filter((e): e is HTMLElement => e !== more)
    for (const k of kids) k.classList.remove('vf-cut', 'vf-tail')
    const items = kids.filter((k) => getComputedStyle(k).display !== 'none')
    const over = () => col.scrollHeight > col.clientHeight + 0.5
      || col.scrollWidth > col.clientWidth + 0.5
    if (!over()) continue
    col.classList.add('cut')
    more.classList.add('on')
    const cut: string[] = []
    for (let i = items.length - 1; i > 0 && over(); i--) {
      const it = items[i]!
      it.classList.add('vf-cut')
      cut.unshift(it.title || (it.textContent ?? '').trim())
      more.textContent = `+${cut.length}`
    }
    if (!cut.length) {
      col.classList.remove('cut')
      more.classList.remove('on')
      continue
    }
    const tail = items[items.length - 1 - cut.length]!
    tail.classList.add('vf-tail')
    more.style.top = `${tail.offsetTop}px`
    more.title = cut.join('\n')
  }
}
