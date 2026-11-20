/* Позиция плана из прайса: процедура остаётся свободным текстом, а подсказки —
   услуги прайса клиники (`ServicePicker`). Ключ услуги уходит, только пока текст равен её имени: по нему
   потом считаются техкарта, лаборатория и % врача, и чужой ключ хуже пустого.
   Последнее слово — у сервера (`routes._plan_service_id`).
   Цена — тоже из прайса: сервер отдаёт у услуги сумму (`price`), когда в прайсе
   одно число, и строку прайса (`price_hint`), когда там диапазон или слова.
   Первое подставляется в поле, второе показывается рядом — из диапазона цену
   выбирает человек. */

export interface ServiceOption {
  id: string
  label: string
  /** Сумма прайса, если она одна; иначе null. */
  price?: number | null
  /** Строка прайса, из которой сумму не взять («1200–1800 MDL»); иначе пусто. */
  price_hint?: string
  /** Имя RU, категория и её имя — у услуг плана (`plan_services`): по ним ищет и группирует `ServicePicker`. */
  ru?: string
  cat?: string
  cat_name?: string
}

export function serviceFor(services: ServiceOption[], procedure: string): ServiceOption | undefined {
  const text = procedure.trim()
  return services.find((s) => s.label === text)
}

export function serviceIdFor(services: ServiceOption[], procedure: string): string {
  return serviceFor(services, procedure)?.id ?? ''
}

/** Поле цены формы плана: значение и «его поставила программа, человек не трогал». */
export interface PriceField { price: string; auto: boolean }

/**
 * Цена после смены текста процедуры. Услуга сменилась — цена берётся из прайса,
 * но только в пустое поле или поверх той, что подставила программа: вписанное
 * рукой не переписывается. У услуги с диапазоном подставленная раньше цена
 * стирается — она была ценой другой услуги; стёртая процедура уносит её тоже,
 * иначе форма с одной подставленной ценой считалась бы начатой.
 */
export function priceAfterProcedure(services: ServiceOption[], before: string, after: string,
  f: PriceField): PriceField {
  if (after.trim() === '') return f.auto ? { price: '', auto: false } : f
  const svc = serviceFor(services, after)
  if (!svc || svc.id === serviceIdFor(services, before)) return f
  if (f.price !== '' && !f.auto) return f
  return svc.price != null ? { price: String(svc.price), auto: true } : { price: '', auto: false }
}

/** Цена поля — та же, что в прайсе у этой услуги (позицию открыли на правку). */
export function priceIsListed(services: ServiceOption[], procedure: string, price: string): boolean {
  const svc = serviceFor(services, procedure)
  return svc?.price != null && price === String(svc.price)
}

const T = {
  listed: 'din lista de prețuri',
  inList: 'în listă:',
  write: 'scrieți prețul',
  mdl: 'MDL',
} as const

const thousands = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

/** Что прайс говорит о цене выбранной услуги; null — услуга не из прайса или цены в нём нет. */
export function priceNote(services: ServiceOption[], procedure: string, price: string):
  { text: string; warn: boolean } | null {
  const svc = serviceFor(services, procedure)
  if (!svc) return null
  if (svc.price != null) {
    return price === String(svc.price)
      ? { text: T.listed, warn: false }
      : { text: `${T.inList} ${thousands(svc.price)} ${T.mdl}`, warn: false }
  }
  if (!svc.price_hint) return null
  return price === ''
    ? { text: `${T.inList} ${svc.price_hint}, ${T.write}`, warn: true }
    : { text: `${T.inList} ${svc.price_hint}`, warn: false }
}

export function PriceNote({ id, services, procedure, price }: {
  id: string; services: ServiceOption[]; procedure: string; price: string
}) {
  const note = priceNote(services, procedure, price)
  if (!note) return null
  return <span id={id} className={`dp-price-note${note.warn ? ' warn' : ''}`}>{note.text}</span>
}
