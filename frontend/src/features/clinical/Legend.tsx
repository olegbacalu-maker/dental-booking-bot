import type { LegendItem } from './chart'

/* Легенда показывает НАСТОЯЩИЙ зуб в каждом состоянии, потом отметки на
   здоровом зубе за разделителем — та же разметка, что у старой страницы
   (.lg, .lg-sep). Рисунок и подпись — сервера. */
function esc(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] ?? c)
}

export function Legend({ items }: { items: LegendItem[] }) {
  const states = items.filter((it) => it.kind === 'state')
  const marks = items.filter((it) => it.kind === 'mark')
  return (
    <>
      {states.map((it) => (
        <span key={it.key} className="lg" dangerouslySetInnerHTML={{ __html: `${it.svg} ${esc(it.label)}` }} />
      ))}
      <span className="lg-sep"></span>
      {marks.map((it) => (
        <span key={it.key} className="lg" dangerouslySetInnerHTML={{ __html: `${it.svg} ${esc(it.label)}` }} />
      ))}
    </>
  )
}
