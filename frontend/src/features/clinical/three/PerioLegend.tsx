/* Легенда слоя пародонта в 3D (06.10) — одна на режим «Parodont» одонтограммы
   и на 3D над листом пародонтограммы: пороги и цвета полосы — с сервера,
   подписи — здесь. ⛔ Без знака «≥»: блок математики вшитый Inter не покрывает,
   и знак ушёл бы в системный шрифт (прайор «ничего графического от Windows»),
   поэтому глубокий карман — «6+ mm», как в итогах листа и 043/e. */

const T = {
  exam: 'Examen din {at}',
  pocket: 'Pungă {a}–{b} mm',
  deepPocket: 'Pungă {a}+ mm',
  bleed: 'Sângerare la sondare',
  rec: 'Recesiune: rădăcina se vede',
  probe: 'Sonda — cu „Rădăcini”',
} as const

interface Props {
  /** дата осмотра словами сервера; нет — черновик листа */
  at?: string
  limits: { deep: number; severe: number }
  colors: { deep: string; severe: string }
}

export function PerioLegend({ at, limits, colors }: Props) {
  const title = at ? T.exam.replace('{at}', at) : undefined
  return (
    <div className="odo-paro-leg" {...(title ? { 'aria-label': title } : {})}>
      {title && <b>{title}</b>}
      <span><i className="sw" style={{ background: colors.deep }} />
        {T.pocket.replace('{a}', String(limits.deep)).replace('{b}', String(limits.severe - 1))}</span>
      <span><i className="sw" style={{ background: colors.severe }} />
        {T.deepPocket.replace('{a}', String(limits.severe))}</span>
      <span><i className="dot" />{T.bleed}</span>
      <span><i className="sw rec" />{T.rec}</span>
      <span><i className="probe" />{T.probe}</span>
    </div>
  )
}
