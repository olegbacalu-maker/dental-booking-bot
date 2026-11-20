/** Печатные листы фиши. `back` — адрес фиши С ВКЛАДКОЙ, куда вернёт кнопка
 *  «назад» на листе (01.10): до того любой лист возвращал на Rezumat. */
export const SHEETS = ['fisa043', 'acord', 'plan-acord', 'deviz', 'anamneza/print'] as const
export type Sheet = (typeof SHEETS)[number]

/** Листы фиши, которые открываются ДОКУМЕНТОМ: сюда же лист пародонтограммы.
 *  Переход на них снимает страницу целиком, и блокер роутера его не видит. */
const DOC_SHEETS: readonly string[] = [...SHEETS, 'parodontograma/print']

/** Ведёт ли ссылка на печатный лист фиши (адрес как в `href`, с query или без). */
export function isSheetHref(href: string): boolean {
  const m = /^\/admin\/patient\/\d+\/([^?#]+)/.exec(href)
  return m !== null && DOC_SHEETS.includes(m[1] ?? '')
}

export function printHref(pid: number, sheet: Sheet, back: string): string {
  return `/admin/patient/${pid}/${sheet}?back=${encodeURIComponent(back)}`
}

/** Лист в окне подписи (09.11): КАК ОН БУДЕТ ПОДПИСАН — без кнопок листа, у
 *  анкеты ответы из фиши. Отдельный адрес, а не печатный: печатный пишет
 *  «tipărit» в летопись, а предпросмотр ничего не пишет. */
export function signPreviewHref(pid: number, key: string): string {
  return `/admin/patient/${pid}/sign/${key}`
}
