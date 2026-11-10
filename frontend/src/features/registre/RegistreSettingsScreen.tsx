import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { ARTICLES, LAMPS, NORMS, PACKS, ROOMS, SOLUTIONS, STERILIZERS, SUPERVISORS, lampLow, lampRest } from './mock'

/* Setări › Registre sanitare — МАКЕТ этапа 1 (10.11.2026). Каталог, из
   которого форма записи берёт кнопки: стерилизаторы с программами, лампы с
   ресурсом, помещения с частотой генеральной уборки, растворы, предметы и
   упаковка, кто проверяет уборку, нормативная документация титула 257/e.
   Право — `PERM_SETTINGS` (директор). ⚠️ Ничего не сохраняется. */

export function RegistreSettingsScreen() {
  return (
    <section className="dp-react-root rg rg-set">
      <div className="fcard rg-head">
        <div className="rg-ttl"><span className="rg-crumb"><AppLink href="/admin/settings">Setări</AppLink> › Registre sanitare</span>
          <b>Echipamente și liste pentru registre</b>
          <small>Din aceste liste se fac butoanele formularelor — asistenta alege, nu scrie.</small></div>
        <AppLink className="rg-btn" href="/admin/registre"><Icon name="shield" /> Deschide registrele</AppLink>
      </div>
      <div className="rg-set-grid">
        <div className="fcard rg-card">
          <div className="rg-card-h"><b>Sterilizatoare</b><small>257/e</small><button type="button" className="rg-btn sm"><Icon name="plus" /> Adaugă</button></div>
          {STERILIZERS.map((s) => (
            <div key={s.id} className="rg-item">
              <div><b>{s.name}</b><small>nr. {s.nr} · {s.kind === 'abur' ? 'cu abur (autoclav)' : 'cu aer'} · {s.room}</small></div>
              <div className="rg-tags">{s.programs.map((p) => <span key={p.id} className="chip mute">{p.label}{p.p !== '—' ? ` · ${p.p} bar` : ''} · {p.min} min</span>)}</div>
              <button type="button" className="rg-ib" aria-label="Modifică"><Icon name="pen" /></button>
            </div>
          ))}
        </div>
        <div className="fcard rg-card">
          <div className="rg-card-h"><b>Lămpi bactericide</b><small>501/e</small><button type="button" className="rg-btn sm"><Icon name="plus" /> Adaugă</button></div>
          {LAMPS.map((l) => (
            <div key={l.id} className={`rg-item${lampLow(l) ? ' low' : ''}`}>
              <div><b>{l.name} nr. {l.nr}</b><small>{l.room} · {l.m3} m³ · {l.screened ? 'ecranată' : 'deschisă'} · în funcțiune din {l.since}</small></div>
              <div className="rg-res"><span className="rg-prog"><i style={{ width: `${Math.round(100 * l.used / l.hours)}%` }} /></span>
                <small>{lampRest(l)} ore rămase din {l.hours}</small>
                {lampLow(l) && <button type="button" className="rg-btn sm pri">Lampă nouă</button>}</div>
              <button type="button" className="rg-ib" aria-label="Modifică"><Icon name="pen" /></button>
            </div>
          ))}
          <p className="hint">„Lampă nouă” scrie în registru data schimbării de facto și pornește din nou numărătoarea orelor.</p>
        </div>
        <div className="fcard rg-card">
          <div className="rg-card-h"><b>Încăperi și curățenia generală</b><small>502/e</small><button type="button" className="rg-btn sm"><Icon name="plus" /> Adaugă</button></div>
          {ROOMS.map((r) => (
            <div key={r.id} className="rg-item">
              <div><b>{r.name}</b><small>următoarea: {r.next}</small></div>
              <span className="rg-every">la <input className="dp-fld" defaultValue={r.every} aria-label="zile" /> zile</span>
              <button type="button" className="rg-ib" aria-label="Modifică"><Icon name="pen" /></button>
            </div>
          ))}
          <div className="rg-f"><span className="rg-fl">Cine verifică curățenia</span>
            <div className="rg-chips">{SUPERVISORS.map((s) => <button key={s} type="button" className="rg-chip on">{s}</button>)}</div></div>
        </div>
        <div className="fcard rg-card">
          <div className="rg-card-h"><b>Soluții dezinfectante</b><small>502/e</small><button type="button" className="rg-btn sm"><Icon name="plus" /> Adaugă</button></div>
          <div className="rg-chips">{SOLUTIONS.map((s) => <button key={s} type="button" className="rg-chip">{s}</button>)}</div>
          <div className="rg-card-h"><b>Articole și ambalaje</b><small>257/e</small></div>
          <div className="rg-chips">{ARTICLES.map((s) => <button key={s} type="button" className="rg-chip">{s}</button>)}</div>
          <div className="rg-chips">{PACKS.map((s) => <button key={s} type="button" className="rg-chip">{s}</button>)}</div>
        </div>
        <div className="fcard rg-card wide">
          <div className="rg-card-h"><b>Documentația normativă</b><small>pe foaia de titlu 257/e</small></div>
          <textarea className="dp-fld" rows={3} defaultValue={NORMS.map((n, i) => `${i + 1}. ${n}`).join('\n')} />
        </div>
      </div>
    </section>
  )
}
