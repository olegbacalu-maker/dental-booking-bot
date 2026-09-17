/** Старая страница того же экрана — откат на один запрос, без сборки. */
export function legacyUrl(): string {
  return `${window.location.pathname}?ui=legacy`
}
