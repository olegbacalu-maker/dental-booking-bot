import { useEffect, useState } from 'react'
import { Form } from 'react-router'
import { AppLink, useProseLinks } from '../components/AppLink'
import { Icon, iconName } from '../components/Icon'
import { t } from '../utils/i18n'
import type { NavItem, ShellModel } from './shell'

/* Оболочка журнала в React (B1). Разметка и классы — ТЕ ЖЕ, что печатал
   серверный `_shell`: paritet здесь не «похоже», а те же узлы в том же
   порядке, потому что panel.css написан под них.
   ⛔ Никакой перекладки и никакого редизайна: облик меняется с B5, не здесь.
   ⭐ B4.2: ссылки оболочки — переходы без перезагрузки (`AppLink`): сайдбар,
   крошки, шапка, поиск. Адрес не из карты маршрутов (Telegram, QR, выход)
   остаётся обычной ссылкой — это решает сам `AppLink`, не список здесь. */

const T = t('shell', {
  title: 'Registrul Clinicii',
  menu: 'Meniu',
  sync: 'Sincronizări',
  search: 'Caută pacient, telefon…',
  kbd: 'Ctrl K',
  newAppt: 'Programare nouă',
  logout: 'Ieșire din cont',
  bell: 'Programări noi din bot',
  feedback: 'Feedback',
} as const)

/** Пункт меню. Пустой `href` — строка без ссылки (см. модель). */
function Item({ it, active }: { it: NavItem; active: string }) {
  const body = (
    <>
      <Icon name={iconName(it.icon)} />
      <span>{it.label}</span>
      {it.dot && <span className={`dot ${it.dot}`} />}
    </>
  )
  const cls = it.key === active ? 'on' : ''
  return it.href
    ? <AppLink className={cls} href={it.href} title={it.label}>{body}</AppLink>
    : <a className={cls} title={it.label}>{body}</a>
}

/**
 * Часы подвала. ⚠️ Пояс — КЛИНИКИ, из модели, а не устройства: в облаке через
 * туннель браузер живёт в своём поясе. Формат и период (20 с) те же, что были
 * у `panel.js`, который эти часы и вёл до B1.
 */
function Clock({ tz }: { tz: string }) {
  const [txt, setTxt] = useState('')
  useEffect(() => {
    const tick = () => {
      const now = new Date()
      try {
        setTxt(now.toLocaleTimeString('ro-RO',
          { timeZone: tz || undefined, hour: '2-digit', minute: '2-digit' }))
      } catch {
        /* пояс не знаком движку — часы устройства лучше пустоты */
        const p2 = (n: number) => String(n).padStart(2, '0')
        setTxt(`${p2(now.getHours())}:${p2(now.getMinutes())}`)
      }
    }
    tick()
    const id = window.setInterval(tick, 20_000)
    return () => window.clearInterval(id)
  }, [tz])
  return <span id="sf_clock" data-tz={tz}>{txt}</span>
}

function Sidebar({ m }: { m: ShellModel }) {
  const { nav, clinic, runtime, frame } = m
  return (
    <aside className={frame.rail ? 'side side-rail' : 'side'}>
      <div className="brand">
        {/* знак приходит строкой сервера — второй его владелец не нужен */}
        <span dangerouslySetInnerHTML={{ __html: clinic.mark }} />
        <div className="txt">
          <b title={clinic.name}>{clinic.name}</b><small>DentPilot</small>
        </div>
      </div>
      <nav>
        <div className="sec">{T.menu}</div>
        {nav.items.map((it) => <Item key={it.key} it={it} active={nav.active} />)}
        {nav.sync.length > 0 && (
          <>
            <div className="sec">{T.sync}</div>
            {nav.sync.map((it) => <Item key={it.key} it={it} active={nav.active} />)}
          </>
        )}
      </nav>
      <div className="sfoot" {...(nav.foot_title ? { title: `Telegram: ${nav.foot_title}` } : {})}>
        v{runtime.version} · <Clock tz={runtime.tz} />
      </div>
    </aside>
  )
}

function Topbar({ m, prose }: { m: ShellModel; prose: (e: React.MouseEvent<HTMLElement>) => void }) {
  const { identity, clinic, frame } = m
  return (
    <div className="top">
      {/* ⭐ Поиск из шапки — переход роутером (B4.2): `Form` с методом GET
          собирает `?q=` из поля и ведёт на экран поиска без перезагрузки;
          в разметке это тот же <form method=get action>, Enter работает. */}
      <Form className="searchf" method="get" action="/admin/search">
        <input id="topq" name="q" placeholder={T.search} autoComplete="off" />
        <span className="kbd">{T.kbd}</span>
        <button><Icon name="search" /></button>
      </Form>
      {clinic.logo_topbar && (
        <AppLink className="tb-logo" href="/admin"><img src={clinic.logo_topbar} alt="" /></AppLink>
      )}
      <div style={{ flex: 1 }} />
      <span className="dp-upd" onClick={prose} dangerouslySetInnerHTML={{ __html: frame.update }} />
      {/* ⛔ Колокольчик заморожен вместе с ботом: сервер присылает `bell: null`,
          пока `tg_configured()` ложно. Размораживать его здесь нельзя. */}
      {frame.bell !== null && (
        <AppLink className="bell" href="/admin#botnew" title={T.bell}>
          <Icon name="bell" />
          {frame.bell > 0 && <span className="n">{frame.bell}</span>}
        </AppLink>
      )}
      <AppLink className="newbtn" href={`/admin/all?date=${frame.today}#addform`}>
        <span className="plus">+</span><span className="nb-t">{T.newAppt}</span>
      </AppLink>
      {identity && (
        <div className="who" title={`${identity.name} · ${identity.role_label}`}>
          <span className="who-av">{identity.initials}</span>
          <div className="who-n">
            <b>{identity.name}</b>
            <small>{identity.role_label} · {clinic.name}</small>
          </div>
          {/* выход — не экран: обычная ссылка, сервер снимает куку и уводит на вход */}
          <AppLink className="who-out" href="/admin/logout" title={T.logout}>
            <Icon name="power" />
          </AppLink>
        </div>
      )}
    </div>
  )
}

/**
 * Каркас страницы. Экран приезжает детьми и стоит там же, где стоял `body` у
 * серверной оболочки, — внутри `.content`, после заголовка, подписи и
 * баннеров.
 */
export function AppShell({ m, children }: { m: ShellModel; children: React.ReactNode }) {
  const sig = m.signals
  /* Ссылки в серверной прозе (баннеры, плашка, строка обновления) — тем же
     переходом, что и `AppLink`: обработчик на контейнере прозы. */
  const prose = useProseLinks()
  return (
    <>
      <Sidebar m={m} />
      <div className="main">
        <Topbar m={m} prose={prose} />
        <div className="content">
          <h1><AppLink href="/admin">{T.title}</AppLink></h1>
          <div className="sub">{m.frame.sub}{m.frame.sec_warn} · v{m.runtime.version}</div>
          {[sig.tamper, sig.split, sig.slot, sig.setup].map((s, i) =>
            s.shown ? <div key={i} onClick={prose} dangerouslySetInnerHTML={{ __html: s.html }} /> : null)}
          {/* ⚠️ Порядок тот же, что печатал сервер: системные баннеры, потом
              навигация раздела, потом плашка ответа, потом экран. Крошка идёт
              ДО плашки — так её и ставил `_sec_page`. */}
          {m.frame.crumbs.length > 0 && (
            <div className="nav">
              {m.frame.crumbs.map((c) => (
                <AppLink key={c.href} href={c.href}>
                  <Icon name={iconName(c.icon)} /> {c.label}
                </AppLink>
              ))}
            </div>
          )}
          {m.frame.msg && <div onClick={prose} dangerouslySetInnerHTML={{ __html: m.frame.msg }} />}
          {children}
        </div>
      </div>
      <div className="brandcorner">
        <Icon name="tooth" /> <b>DentPilot</b> ·{' '}
        <AppLink href={m.frame.feedback.href} title={m.frame.feedback.email}>
          <Icon name="chat" /> {T.feedback}
        </AppLink>
      </div>
    </>
  )
}
