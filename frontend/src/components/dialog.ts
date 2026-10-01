/* jsdom не умеет showModal/close: тогда открываем атрибутом — форма та же.
   Одни и те же две функции у всех диалогов бандла: фиша (`patients/card`),
   «Pacient nou», окно подтверждения (`ConfirmHost`). */
export function showDialog(d: HTMLDialogElement | null) {
  if (!d || d.open) return
  if (typeof d.showModal === 'function') d.showModal()
  else d.setAttribute('open', '')
}

export function hideDialog(d: HTMLDialogElement | null) {
  if (!d || !d.open) return
  if (typeof d.close === 'function') d.close()
  else d.removeAttribute('open')
}
