import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { settings, type ThemeData, type ThemeForm } from './settings'

const T = {
  title: 'Aspectul clinicii',
  style: 'Stil interfață',
  menu: 'Meniul lateral',
  font: 'Font',
  color: 'Culoare principală',
  customTitle: 'Culoare personalizată',
  hint:
    'Culoarea se aplică butoanelor, meniului și accentelor. Roșu pentru urgențe, galben ' +
    'pentru avertismente și verde pentru „confirmat” rămân neschimbate — acolo culoarea ' +
    'înseamnă ceva, nu decorează.',
  save: 'Salvează',
  logo: 'Logo',
  noLogo: 'fără logo',
  pick: 'Alege fișier',
  upload: 'Încarcă',
  remove: 'Șterge',
  topbar: 'Afișează logo-ul și în bara de sus a registrului, pe centru',
  logoHint:
    'PNG sau JPEG, cel mult {mb} MB. Apare pe ecranul de intrare și în antetul ' +
    'documentelor tipărite (043/e, acord, raport de casă). Logoul rămâne la actualizarea ' +
    'programului — se păstrează lângă profilul clinicii.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

function formOf(d: ThemeData): ThemeForm {
  return {
    style: d.style,
    primary: d.custom ? 'custom' : d.primary,
    custom: d.primary,
    logo_topbar: d.logo_topbar,
    menu: d.menu,
    font: d.font,
  }
}

/** Живой предпросмотр: переменные :root — ровно те, что сервер посчитал. */
function put(vars: Record<string, string>) {
  for (const [k, v] of Object.entries(vars)) document.documentElement.style.setProperty(k, v)
}

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadThemeSettings: RouteLoad<ThemeData> = (signal) => settings.theme(signal)

/**
 * Стиль, фирменный цвет, логотип. Палитры считает сервер и отдаёт готовыми;
 * свой цвет предпросмотр получает от /api/settings/theme/palette — клиент
 * арифметику контраста не повторяет (иначе при выборе один цвет, после
 * сохранения другой).
 */
export function ThemeSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<ThemeData>(navigate)
  const [form, setForm] = useState<ThemeForm | null>(null)
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const data: ThemeData | null = state.status === 'ready' ? state.data : null
  const f = form ?? (data ? formOf(data) : null)

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }

  /** Применить выбор к странице: стиль, меню и шрифт — переменными сервера,
   *  цвет — из набора или с сервера. */
  async function preview(next: ThemeForm) {
    if (!data) return
    const st = data.styles.find((s) => s.key === next.style)
    if (st) put(st.vars)
    const mn = data.menus.find((m) => m.key === next.menu)
    if (mn) put(mn.vars)
    const ft = data.fonts.find((x) => x.key === next.font)
    if (ft) put({ '--font': ft.stack })
    const hex = (next.primary === 'custom' ? next.custom : next.primary).toUpperCase()
    const known = data.palettes[next.style]?.[hex]
    if (known) {
      put(known)
      return
    }
    try {
      const r = await settings.themePalette(hex, next.style)
      put(r.data)
    } catch {
      /* предпросмотр — не данные: без палитры экран остаётся как есть */
    }
  }

  function change(patch: Partial<ThemeForm>) {
    if (!f) return
    const next = { ...f, ...patch }
    setForm(next)
    void preview(next)
  }

  async function save(next: ThemeForm) {
    setBusy(true)
    try {
      const r = await settings.themeSave(next)
      replace(r.data)
      setForm(formOf(r.data))
      setToast({ tone: r.tone, text: r.text })
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (f) await save(f)
  }

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    try {
      const r = await settings.themeLogo(file)
      setFile(null)
      replace(r.data)
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function removeLogo() {
    setBusy(true)
    try {
      const r = await settings.themeLogoDelete()
      replace(r.data)
      setForm(formOf(r.data))
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="palette" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      {data && f && (
        <>
          <form onSubmit={onSubmit}>
            <h3 className="th-h">{T.style}</h3>
            <div className="th-styles">
              {data.styles.map((s) => (
                <label key={s.key} className="th-style">
                  <input type="radio" name="style" value={s.key} checked={f.style === s.key}
                    disabled={busy} onChange={() => change({ style: s.key })} />
                  <span className="th-card" style={{
                    borderRadius: s.vars['--r-card'], background: s.vars['--bg'],
                    borderColor: s.vars['--line'], boxShadow: s.vars['--sh'],
                  }}>
                    <i style={{ borderRadius: s.vars['--r-ctl'] }} /><u /><u className="sh" />
                  </span>
                  <b>{s.label}</b>
                  <small>{s.hint}</small>
                </label>
              ))}
            </div>

            <h3 className="th-h">{T.menu}</h3>
            <div className="th-opts">
              {data.menus.map((m) => (
                <label key={m.key} className="th-opt">
                  <input type="radio" name="menu" value={m.key} checked={f.menu === m.key}
                    disabled={busy} onChange={() => change({ menu: m.key })} />
                  <span className="th-box">
                    <span className={`mm ${m.key}`}><i /><i /><i /></span>
                    <span>{m.label}</span>
                  </span>
                  <small>{m.hint}</small>
                </label>
              ))}
            </div>

            <h3 className="th-h">{T.font}</h3>
            <div className="th-opts">
              {data.fonts.map((ft) => (
                <label key={ft.key} className="th-opt">
                  <input type="radio" name="font" value={ft.key} checked={f.font === ft.key}
                    disabled={busy} onChange={() => change({ font: ft.key })} />
                  {/* образец — тем самым набором семейств, что уедет в --font */}
                  <span className="th-box" style={{ fontFamily: ft.stack }}>
                    <span className="fs">Aa</span>
                    <span>{ft.label}</span>
                  </span>
                  <small>{ft.hint}</small>
                </label>
              ))}
            </div>

            <h3 className="th-h">{T.color}</h3>
            <div className="th-colors">
              {data.presets.map((p) => (
                <label key={p.hex} className="th-c" title={p.name}>
                  <input type="radio" name="primary" value={p.hex} checked={f.primary === p.hex}
                    disabled={busy} onChange={() => change({ primary: p.hex })} />
                  <span style={{ background: p.hex }} />
                </label>
              ))}
              <label className="th-c th-custom" title={T.customTitle}>
                <input type="radio" name="primary" value="custom" checked={f.primary === 'custom'}
                  disabled={busy} onChange={() => change({ primary: 'custom' })} />
                <span className="pick"><Icon name="palette" /></span>
              </label>
              <input type="color" id="thcustom" aria-label={T.customTitle} value={f.custom} disabled={busy}
                onChange={(e) => change({ primary: 'custom', custom: e.target.value })} />
            </div>
            <p className="hint">{T.hint}</p>
            <button className="savebtn" disabled={busy}><Icon name="save" /> {T.save}</button>
          </form>

          <h3 className="th-h">{T.logo}</h3>
          <div className="th-logowrap">
            {data.logo ? <img className="th-logo" src={data.logo} alt="logo" /> : <div className="th-logo none">{T.noLogo}</div>}
            <form onSubmit={upload} className="th-logof">
              <div className="filepick">
                <input type="file" id="thlogo" accept="image/png,image/jpeg" disabled={busy}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                <label htmlFor="thlogo"><Icon name="clip" /> {file ? file.name : T.pick}</label>
              </div>
              <div className="dp-logo-actions">
                <button className="pl-btn primary" disabled={busy || !file}>{T.upload}</button>
                {data.logo && (
                  <button type="button" className="pl-btn" disabled={busy} onClick={removeLogo}>
                    <Icon name="trash" /> {T.remove}
                  </button>
                )}
              </div>
            </form>
          </div>
          {data.logo && (
            <label className="th-topbar">
              <input type="checkbox" checked={f.logo_topbar} disabled={busy}
                onChange={(e) => { const next = { ...f, logo_topbar: e.target.checked }; setForm(next); void save(next) }} />
              {T.topbar}
            </label>
          )}
          <p className="hint">{T.logoHint.replace('{mb}', String(data.logo_max_mb))}</p>
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
