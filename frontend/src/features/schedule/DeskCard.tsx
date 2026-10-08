import { type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/icons'
import type { CallResult, Desk, DeskConfirmItem } from './desk'

/* Списки стойки (01.10, «La recepție»): рабочие списки регистратуры — каждая
   строка человек и одно действие; пустой список не рисуется, пустая карточка
   тоже. Слово Олега 28.09: «колонке Azi там не место … то, что надо
   регистратуре»; на показ — «выглядит очень серьёзно, мне очень нравится».
   08.10 (макет): строка цифр дня снята — они в подзаголовке страницы;
   «Primul loc liber» и касса — своей карточкой (`DashRail.FreeCard`).
   ⛔ Данные — из конверта живого канала (`desk`), не своим GET; отметка
   звонка — команда, после которой экран спрашивает канал (`onCall`). */

const T = {
  confirm: 'De confirmat',
  confirmHint: 'sunați și bifați',
  ok: 'Confirmat',
  no: 'Nu răspunde',
  undo: 'Anulează bifa',
  okDone: 'confirmat',
  noDone: 'nu răspunde',
  all: 'toți',
  of: 'din',
  unsched: 'Plan fără programare',
  unschedHint: 'au plan de tratament, dar nicio programare',
  more: 'încă',
  collect: 'De încasat azi',
  proc: 'proc.',
  days: 'zile',
  mdl: 'MDL',
} as const

interface Props {
  desk: Desk
  busy: boolean
  onCall: (id: number, result: CallResult) => void
}

export function DeskCard({ desk, busy, onCall }: Props) {
  const c = desk.confirm

  /* Пустые списки не рисуются — и пустая карточка тоже: в тихий день колонка
     кончается на «Primul loc liber», как в макете. */
  const any = (desk.collect !== null && desk.collect.n > 0) || c.n > 0 || desk.unscheduled.n > 0
  if (!any) return null
  return (
    <div className="desk">
      {desk.collect && desk.collect.n > 0 && (
        <Section icon="money" title={T.collect} count={`${desk.collect.sum_s} ${T.mdl}`} tone="red">
          {desk.collect.items.map((it) => (
            <div key={it.pid} className="dk-row">
              <span className="dk-t">{it.time}</span>
              <div className="dk-b">
                <AppLink href={`/admin/patient/${it.pid}?tab=plan`}><b>{it.name}</b></AppLink>
                <small>{it.status_label}</small>
              </div>
              <span className="dk-sum bad">{it.debt_s} {T.mdl}</span>
            </div>
          ))}
        </Section>
      )}
      {c.n > 0 && (
        <Section icon="phone" title={`${T.confirm} ${c.day}`}
          count={c.n_left ? `${c.n_left} ${T.of} ${c.n}` : `${T.all} ${c.n}`}
          hint={T.confirmHint} tone={c.n_left ? 'blue' : 'green'}>
          {c.items.map((it) => <ConfirmRow key={it.id} it={it} busy={busy} onCall={onCall} />)}
        </Section>
      )}

      {desk.unscheduled.n > 0 && (
        <Section icon="clipboard" title={T.unsched} count={`${desk.unscheduled.n}`}
          hint={`${T.unschedHint} · ${desk.unscheduled.sum_s} ${T.mdl}`} tone="amber">
          {desk.unscheduled.items.map((it) => (
            <div key={it.pid} className="dk-row">
              <div className="dk-b">
                <AppLink href={`/admin/patient/${it.pid}?tab=plan`}><b>{it.name}</b></AppLink>
                <small>{it.phone || '—'} · {it.n} {T.proc} · de {it.days} {T.days}</small>
              </div>
              <span className="dk-sum">{it.total_s} {T.mdl}</span>
            </div>
          ))}
          {desk.unscheduled.n > desk.unscheduled.items.length && (
            <AppLink className="dk-more" href="/admin/search">
              {T.more} {desk.unscheduled.n - desk.unscheduled.items.length} ›
            </AppLink>
          )}
        </Section>
      )}
    </div>
  )
}

function ConfirmRow({ it, busy, onCall }: { it: DeskConfirmItem; busy: boolean; onCall: Props['onCall'] }) {
  return (
    <div className={`dk-row${it.call === 'ok' ? ' done' : ''}`} data-appt={it.id}>
      <span className="dk-t">{it.time}</span>
      <div className="dk-b">
        <AppLink href={`/admin/patient/${it.pid}`}><b>{it.name}</b></AppLink>
        <small>{it.phone || '—'} · {it.doctor}</small>
        {it.call && (
          <small className={it.call === 'ok' ? 'dk-ok' : 'dk-no'}>
            <Icon name={it.call === 'ok' ? 'check' : 'phone-off'} />
            {' '}{it.call === 'ok' ? T.okDone : T.noDone} {it.call_at}
          </small>
        )}
      </div>
      <span className="dk-act">
        {it.call !== 'ok' && (
          <button type="button" className="dk-btn ok" title={T.ok} aria-label={`${T.ok}: ${it.name}`}
            disabled={busy} onClick={() => onCall(it.id, 'ok')}><Icon name="check" /></button>
        )}
        {!it.call && (
          <button type="button" className="dk-btn no" title={T.no} aria-label={`${T.no}: ${it.name}`}
            disabled={busy} onClick={() => onCall(it.id, 'noanswer')}><Icon name="phone-off" /></button>
        )}
        {it.call && (
          <button type="button" className="dk-btn" title={T.undo} aria-label={`${T.undo}: ${it.name}`}
            disabled={busy} onClick={() => onCall(it.id, '')}><Icon name="undo" /></button>
        )}
      </span>
    </div>
  )
}

function Section({ icon, title, count, hint, tone, children }: {
  icon: IconName; title: string; count?: string; hint?: string; tone: string; children: ReactNode
}) {
  return (
    <details className="dk-sec" open>
      <summary>
        <span className={`dk-ico ${tone}`}><Icon name={icon} /></span>
        <span className="dk-st">{title}{hint && <small>{hint}</small>}</span>
        {count && <span className={`dk-cnt ${tone}`}>{count}</span>}
      </summary>
      <div className="dk-list">{children}</div>
    </details>
  )
}
