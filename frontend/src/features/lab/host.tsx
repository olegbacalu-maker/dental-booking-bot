import { useCallback, useState } from 'react'
import { useLocation } from 'react-router'
import { defaultNavigate } from '../../hooks/useLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { labApi, sheetUrl, type Act, type FormData, type OrderData, type OrderRow } from './lab'
import { OrderDialog } from './OrderDialog'
import { StepDialog, type StepKind } from './StepDialog'

type Say = (text: string, tone: 'ok' | 'err') => void
interface Open { form: FormData; order: OrderData | null; planItem: number | null; k: number }

/**
 * Окна раздела одним хозяином — у блока фиши и у списка. Команды состояния не
 * возвращают: после каждой владелец перечитывает свою модель (`onChanged`), а
 * открытое окно — заказ.
 */
export function useLabHost(onChanged: () => void, say: Say, navigate: (url: string) => void = defaultNavigate) {
  const { pathname, search } = useLocation()
  const [open, setOpen] = useState<Open | null>(null)
  const [step, setStep] = useState<{ o: OrderRow; kind: StepKind } | null>(null)
  const [busy, setBusy] = useState(false)

  const fail = useCallback((e: unknown) => { say(asApiError(e).text || 'Programul nu a răspuns.', 'err') }, [say])

  const create = useCallback(async (pid: number | null, planItem: number | null = null) => {
    try {
      const r = await labApi.form(pid, planItem)
      setOpen({ form: r.data, order: null, planItem, k: Date.now() })
    } catch (e) { fail(e) }
  }, [fail])

  const openOrder = useCallback(async (id: number) => {
    try {
      const o = await labApi.order(id)
      const f = await labApi.form(o.data.order.pid, null)
      setOpen({ form: f.data, order: o.data, planItem: null, k: Date.now() })
    } catch (e) { fail(e) }
  }, [fail])

  /** Команда и её слово; окно заказа, если открыто, перечитывается. */
  const run = useCallback(async (id: number, cmd: () => Promise<ApiResult<unknown>>): Promise<string | null> => {
    setBusy(true)
    try {
      const r = await cmd()
      if (r.text) say(r.text, 'ok')
      onChanged()
      if (open?.order?.order.id === id) {
        const o = await labApi.order(id)
        setOpen((cur) => (cur && cur.order?.order.id === id ? { ...cur, order: o.data } : cur))
      }
      return null
    } catch (e) {
      return asApiError(e).text || 'Programul nu a răspuns.'
    } finally {
      setBusy(false)
    }
  }, [say, onChanged, open])

  const act = useCallback((o: OrderRow, a: Act) => {
    if (a === 'etapa' || a === 'refacere' || a === 'cancel') { setStep({ o, kind: a }); return }
    void run(o.id, () => (a === 'undo' ? labApi.undo(o.id) : labApi.step(o.id, a))).then((err) => { if (err) say(err, 'err') })
  }, [run, say])

  const print = useCallback((id: number) => navigate(sheetUrl(id, `${pathname}${search}`)), [navigate, pathname, search])

  const node = (
    <>
      {open && (
        <OrderDialog key={`${open.order?.order.id ?? 'new'}:${open.k}`} form={open.form} data={open.order} planItem={open.planItem}
          busy={busy} onClose={() => setOpen(null)}
          onCreated={(id, text, andPrint) => { say(text, 'ok'); onChanged(); setOpen(null); if (andPrint) print(id) }}
          onSaved={(text) => { say(text, 'ok'); onChanged() }}
          onPrint={print} onAct={act} />
      )}
      {step && (
        <StepDialog key={`${step.o.id}${step.kind}`} o={step.o} kind={step.kind} words={open?.form.words ?? null}
          onClose={() => setStep(null)}
          onDone={(b) => run(step.o.id, () => (step.kind === 'etapa' ? labApi.etapa(step.o.id, b)
            : step.kind === 'refacere' ? labApi.refacere(step.o.id, b) : labApi.cancel(step.o.id, b.note)))} />
      )}
    </>
  )
  return {
    node, busy,
    create: (pid: number | null, planItem: number | null = null) => { void create(pid, planItem) },
    open: (id: number) => { void openOrder(id) },
    act,
    print,
  }
}

export type LabHost = ReturnType<typeof useLabHost>
