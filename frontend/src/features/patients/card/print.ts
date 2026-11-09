/** Печатные листы фиши. `back` — адрес фиши С ВКЛАДКОЙ, куда вернёт кнопка
 *  «назад» на листе (01.10): до того любой лист возвращал на Rezumat. */
export type Sheet = 'fisa043' | 'acord' | 'plan-acord' | 'anamneza/print'

export function printHref(pid: number, sheet: Sheet, back: string): string {
  return `/admin/patient/${pid}/${sheet}?back=${encodeURIComponent(back)}`
}

/** Лист в окне подписи (09.11): КАК ОН БУДЕТ ПОДПИСАН — без кнопок листа, у
 *  анкеты ответы из фиши. Отдельный адрес, а не печатный: печатный пишет
 *  «tipărit» в летопись, а предпросмотр ничего не пишет. */
export function signPreviewHref(pid: number, key: string): string {
  return `/admin/patient/${pid}/sign/${key}`
}
