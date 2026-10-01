/** Печатные листы фиши. `back` — адрес фиши С ВКЛАДКОЙ, куда вернёт кнопка
 *  «назад» на листе (01.10): до того любой лист возвращал на Rezumat. */
export type Sheet = 'fisa043' | 'acord' | 'plan-acord' | 'anamneza/print'

export function printHref(pid: number, sheet: Sheet, back: string): string {
  return `/admin/patient/${pid}/${sheet}?back=${encodeURIComponent(back)}`
}
