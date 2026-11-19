import { useCallback, useEffect, useState } from 'react'
import { useBlocker, useSearchParams } from 'react-router'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, searchChangeKeepsData, useRouteLoad, type ScreenData } from '../../hooks/useRouteLoad'
import { useUnsavedPage } from '../../hooks/useUnsavedPage'
import { ConsultTemplatesTab } from './ConsultTemplatesTab'
import { PlanTemplatesTab } from './PlanTemplatesTab'
import { settings, type PlanTemplatesData, type TemplatesAll, type TemplatesData } from './settings'

const T = {
  title: 'Șabloane',
  tabs: 'Tipul șabloanelor',
  consult: 'Consultație',
  plan: 'Plan de tratament',
  dirty: 'modificări nesalvate',
  unsaved: {
    consult: 'Șabloanele de consultație au modificări nesalvate.',
    plan: 'Șabloanele de plan au modificări nesalvate.',
  },
  leaveAsk: 'Părăsiți ecranul fără să le salvați?',
  leave: 'Părăsește',
} as const

type Tab = 'consult' | 'plan'

interface Props {
  navigate?: (url: string) => void
}

/**
 * Данные экрана грузит роутер (App.tsx › LOADS): обе вкладки одним ответом,
 * чтобы переключение не ждало сети. Вкладка живёт в адресе (`?tab=plan`), и
 * смену одного query загрузчик не перезапускает — данные те же.
 */
export const loadTemplatesSettings: ScreenData = {
  load: async (signal) => {
    const [consult, plan] = await Promise.all([settings.templates(signal), settings.planTemplates(signal)])
    return { ...consult, data: { consult: consult.data, plan: plan.data } satisfies TemplatesAll }
  },
  shouldRevalidate: searchChangeKeepsData,
}

/**
 * «Setări › Șabloane»: шаблоны консультации и шаблоны плана лечения — вкладками
 * одного экрана. Обе вкладки смонтированы сразу, неактивная спрятана: правка,
 * начатая в одной, переживает взгляд в другую. Теряется она только с уходом с
 * экрана — об этом спрашивает блокер роутера (другой экран) и `useUnsavedPage`
 * (перезагрузка и закрытие окна), как в фише; смена вкладки вопроса не задаёт.
 */
export function TemplatesSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<TemplatesAll>(navigate)
  const [query, setQuery] = useSearchParams()
  const tab: Tab = queryParam(query, 'tab') === 'plan' ? 'plan' : 'consult'
  const [dirty, setDirty] = useState<Record<Tab, boolean>>({ consult: false, plan: false })
  const dirtyConsult = useCallback((d: boolean) => setDirty((x) => (x.consult === d ? x : { ...x, consult: d })), [])
  const dirtyPlan = useCallback((d: boolean) => setDirty((x) => (x.plan === d ? x : { ...x, plan: d })), [])
  /* первые фразы вопроса — по вкладкам с правкой; пусто — спрашивать не о чем */
  const what = [dirty.consult && T.unsaved.consult, dirty.plan && T.unsaved.plan].filter(Boolean).join(' ')
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    what !== '' && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    /* вкладка сообщает «чисто» эффектом: щелчок сразу после записи застаёт
       блокер с прежним флагом — решает свежее состояние */
    if (!what) {
      blocker.proceed()
      return
    }
    void ask({ text: `${what} ${T.leaveAsk}`, ok: T.leave, danger: true }).then((yes) => {
      if (yes) blocker.proceed()
      else blocker.reset()
    })
  }, [blocker, what])
  useUnsavedPage(what || null)

  const all: TemplatesAll | null = state.status === 'ready' ? state.data : null
  const savedConsult = useCallback((d: TemplatesData) => { if (all) replace({ ...all, consult: d }) }, [all, replace])
  const savedPlan = useCallback((d: PlanTemplatesData) => { if (all) replace({ ...all, plan: d }) }, [all, replace])

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="note" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }
  const pick = (t: Tab) => setQuery(t === 'plan' ? { tab: 'plan' } : {}, { replace: true })

  return (
    <section className="dp-react-root dp-tpls" aria-busy={all === null}>
      {head}
      <div className="rc-tabs tpl-tabs" role="tablist" aria-label={T.tabs}>
        {(['consult', 'plan'] as const).map((t) => (
          <button key={t} type="button" role="tab" id={`tpl_tab_${t}`} aria-controls={`tpl_pane_${t}`}
            aria-selected={tab === t} className={`rc-tab${tab === t ? ' on' : ''}`} onClick={() => pick(t)}>
            {T[t]}
            {dirty[t] && <span className="tpl-dirty" title={T.dirty} aria-label={T.dirty} />}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="tpl_pane_consult" aria-labelledby="tpl_tab_consult" hidden={tab !== 'consult'}>
        <ConsultTemplatesTab data={all?.consult ?? null} onSaved={savedConsult}
          leaveIfSignedOut={leaveIfSignedOut} onDirty={dirtyConsult} />
      </div>
      <div role="tabpanel" id="tpl_pane_plan" aria-labelledby="tpl_tab_plan" hidden={tab !== 'plan'}>
        <PlanTemplatesTab data={all?.plan ?? null} onSaved={savedPlan}
          leaveIfSignedOut={leaveIfSignedOut} onDirty={dirtyPlan} />
      </div>
    </section>
  )
}
