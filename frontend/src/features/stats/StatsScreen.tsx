import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { canAnimate } from '../../utils/fx'
import { t } from '../../utils/i18n'
import { StatsBoard } from './StatsBoard'
import { stats, type StatsData } from './stats'

/* Здесь — владелец периода и данных; раскладка — `StatsBoard` (B8, 27.09).
   Всё, что несёт ЦИФРУ или её объяснение, приходит с сервера. */
const T = t('stats', {
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const)

interface Props {
  navigate?: (url: string) => void
}

/**
 * Данные грузит роутер, и ПЕРИОД он берёт из адреса (B2.3): владелец «какой
 * период» — `?from=` и `?to=` в адресе, и больше никто. Каждая граница
 * уходит своей, прочие хвосты адреса (`msg`, `ui`) в запрос не попадают.
 * Пустой адрес — последние 7 дней, их считает сервер в поясе клиники.
 */
export const loadStats: RouteLoad<StatsData> = (signal, _p, q) =>
  stats.get(queryParam(q, 'from'), queryParam(q, 'to'), signal)


/** Адрес периода — СВЕЖИЙ query из двух границ: `msg=bad_period` и прочее
 *  не переносятся, иначе плашка отказа возвращалась бы на каждой F5. */
const periodUrl = (f: string, t2: string) => `/admin/stats?from=${f}&to=${t2}`

export function StatsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, leaveIfSignedOut } = useRouteLoad<StatsData>(navigate)
  /* Смена адреса — РОУТЕРОМ; `navigate` из пропсов — это уход на вход. */
  const routeTo = useNavigate()
  const [toast, setToast] = useState<ToastState | null>(null)
  /* Набранный в полях период — состояние ФОРМЫ, а не адреса. `sent` — данные,
     поверх которых сервер его принял: принятый период стоит в полях, пока
     роутер не принёс ответ для нового адреса, и уступает эху сервера вместе с
     ним, а не кадром раньше — поля не прыгают назад, на прежний период. */
  const [draft, setDraft] = useState<{ from: string; to: string; sent?: StatsData } | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  const live = canAnimate()

  /* Адрес повторяет отбор — как у старой страницы: перезагрузка, закладка и
     `?ui=legacy` открывают ТОТ ЖЕ период. Пишет его РОУТЕР, и загрузчик читает
     уже новый адрес. `replace`, как и было: смена периода не копит шагов
     «Назад». Пока ответа нет, на экране прежний период — так было и до
     роутера (экран только читает). */
  function go(f: string, t2: string) {
    setDraft(null)
    void routeTo(periodUrl(f, t2), { replace: true })
  }

  async function apply(f: string, t2: string, over: StatsData) {
    /* ⛔ Негодный период НЕ сбрасывает экран на «последние 7 дней», как делал
       редирект старой страницы: человек промахнулся по сегменту года, и
       ответом обязан быть отказ с названной причиной, а не молча другой
       период под теми же цифрами в полях.
       Поэтому проверка — ПРЯМЫМ запросом ДО перехода: переход с отказом увёл
       бы весь экран в «не загрузилось» и записал бы в адрес негодный период.
       Данные же экрану приносит только загрузчик — по НОРМАЛИЗОВАННОМУ периоду
       из ответа (перевёрнутый развёрнут, недостающая граница достроена). */
    try {
      const r = await stats.get(f, t2)
      setDraft({ from: f, to: t2, sent: over })
      void routeTo(periodUrl(r.data.period.from, r.data.period.to), { replace: true })
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    }
  }

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }
  if (state.status === 'loading') {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const d: StatsData = state.data
  const pick = draft && (!draft.sent || draft.sent === d)
    ? draft : { from: d.period.from, to: d.period.to }
  return (
    <section className="dp-react-root">
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
      <StatsBoard
        d={d}
        live={live}
        pick={pick}
        onPick={(f, t2) => setDraft({ from: f, to: t2 })}
        onPreset={go}
        onApply={() => { void apply(pick.from, pick.to, d) }}
        periodUrl={periodUrl}
      />
    </section>
  )
}
