import { type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/icons'
import { CALL_WORDS, type CallResult, type Desk, type DeskConfirm, type DeskConfirmItem } from './desk'
import { Fold } from './Fold'

/* Списки стойки (01.10, «La recepție»): рабочие списки регистратуры — каждая
   строка человек и одно действие; пустой список не рисуется, пустая карточка
   тоже. Слово Олега 28.09: «колонке Azi там не место … то, что надо
   регистратуре»; на показ — «выглядит очень серьёзно, мне очень нравится».
   08.10 (макет): строка цифр дня снята — они в подзаголовке страницы;
   «Primul loc liber» и касса — своей карточкой (`DashRail.FreeCard`).
   ⛔ Данные — из конверта живого канала (`desk`), не своим GET; отметка
   звонка — команда, после которой экран спрашивает канал (`onCall`).
   12.10 (слово Олега): «De confirmat azi» — сегодняшние, кого не подтвердили
   вчера, над списком на завтра; разделы сворачиваются и помнят это на
   компьютере, а сворачивание у низа страницы больше не дёргает её (`Fold`). */

const T = {
  confirm: 'De confirmat',
  confirmHint: 'sunați și bifați',
  ...CALL_WORDS,
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
  const ct = desk.confirm_today
  const any = (desk.collect !== null && desk.collect.n > 0) || c.n > 0 || ct.n > 0 || desk.unscheduled.n > 0
  if (!any) return null
  return (
    <div className="desk">
      {desk.collect && desk.collect.n > 0 && (
        <Section id="collect" icon="money" title={T.collect} count={`${desk.collect.sum_s} ${T.mdl}`} tone="red">
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
      {ct.n > 0 && <ConfirmSection id="confirm_today" c={ct} busy={busy} onCall={onCall} />}
      {c.n > 0 && <ConfirmSection id="confirm" c={c} busy={busy} onCall={onCall} />}

      {desk.unscheduled.n > 0 && (
        <Section id="unsched" icon="clipboard" title={T.unsched} count={`${desk.unscheduled.n}`}
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

/** Обзвон одного дня — «azi» или «mâine»: одна форма, одни кнопки. */
function ConfirmSection({ id, c, busy, onCall }: { id: string; c: DeskConfirm; busy: boolean; onCall: Props['onCall'] }) {
  return (
    <Section id={id} icon="phone" title={`${T.confirm} ${c.day}`}
      count={c.n_left ? `${c.n_left} ${T.of} ${c.n}` : `${T.all} ${c.n}`}
      hint={T.confirmHint} tone={c.n_left ? 'blue' : 'green'}>
      {c.items.map((it) => <ConfirmRow key={it.id} it={it} busy={busy} onCall={onCall} />)}
    </Section>
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

function Section({ id, icon, title, count, hint, tone, children }: {
  id: string; icon: IconName; title: string; count?: string; hint?: string; tone: string; children: ReactNode
}) {
  return (
    <Fold id={`desk:${id}`} className="dk-sec" head={
      <>
        <span className={`dk-ico ${tone}`}><Icon name={icon} /></span>
        <span className="dk-st">{title}{hint && <small>{hint}</small>}</span>
        {count && <span className={`dk-cnt ${tone}`}>{count}</span>}
      </>
    }>
      <div className="dk-list">{children}</div>
    </Fold>
  )
}
