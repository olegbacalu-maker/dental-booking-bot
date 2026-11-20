/** Текст для поиска: без диакритики и регистра — «ș», «ă», «î» набирают и без них. */
export const fold = (s: string): string =>
  s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase('ro').trim()
