/* jsdom не умеет showModal/close: тогда открываем атрибутом — форма та же.
   Те же две функции, что у диалога «Pacient nou»; диалогов в фише четыре. */
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
