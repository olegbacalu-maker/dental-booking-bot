import { useCallback, useRef, useState } from 'react'
import { Dental3DViewer, type Dental3DViewerHandle } from './Dental3DViewer'
import { SURFACES, surfaceMeta, type SurfaceId } from './surfaces'
import type { ToothSceneStats } from './scene'
import './dental3d.css'

/**
 * Изолированный прототип Dental3D.
 *
 * ⛔ Это НЕ часть рабочего процесса программы: ни одонтограммы, ни диагнозов,
 * ни плана лечения, ни обращений к API. Проверяется ровно одно — один зуб,
 * пять поверхностей, наведение, клик, состояние React, стабильный кадр.
 */

/** Модель состояния из задания. Ничего сверх — ни пациента, ни диагноза. */
interface Dental3DState {
  tooth: number
  selectedSurface: SurfaceId | null
}

export function Dental3DPrototype() {
  const [state, setState] = useState<Dental3DState>({ tooth: 16, selectedSurface: null })
  const [hovered, setHovered] = useState<SurfaceId | null>(null)
  const [stats, setStats] = useState<ToothSceneStats | null>(null)
  const viewer = useRef<Dental3DViewerHandle | null>(null)

  /** Ровно тот вызов, который назван в задании: selectSurface("occlusal"). */
  const selectSurface = useCallback((surface: SurfaceId) => {
    setState((prev) => ({
      ...prev,
      selectedSurface: prev.selectedSurface === surface ? null : surface,
    }))
  }, [])

  const selectedMeta = state.selectedSurface ? surfaceMeta(state.selectedSurface) : null
  const hoveredMeta = hovered ? surfaceMeta(hovered) : null

  return (
    <div className="d3-root">
      <header className="d3-head">
        <div>
          <h1 className="d3-title">Dental3D — prototip tehnic</h1>
          <p className="d3-sub">
            Un singur dinte, cinci suprafețe. Fără odontogramă, fără API, fără salvare.
          </p>
        </div>
        <button type="button" className="d3-btn" onClick={() => viewer.current?.resetView()}>
          Reset view
        </button>
      </header>

      <div className="d3-body">
        <div className="d3-viewport">
          <Dental3DViewer
            ref={viewer}
            selected={state.selectedSurface}
            onHover={setHovered}
            onSelect={selectSurface}
            onStats={setStats}
          />
        </div>

        <aside className="d3-panel" aria-live="polite">
          <div className="d3-row">
            <span className="d3-k">Selected tooth</span>
            <span className="d3-v d3-tooth">{state.tooth}</span>
          </div>
          <p className="d3-note">Molar prim superior drept · FDI 16</p>

          <div className="d3-row">
            <span className="d3-k">Selected surface</span>
            <span className={`d3-v${selectedMeta ? '' : ' d3-empty'}`}>
              {selectedMeta ? selectedMeta.label : '—'}
            </span>
          </div>
          {selectedMeta && (
            <p className="d3-note">
              {selectedMeta.ro} · cod <b>{selectedMeta.display}</b>
            </p>
          )}

          <div className="d3-row">
            <span className="d3-k">Hover</span>
            <span className={`d3-v${hoveredMeta ? '' : ' d3-empty'}`}>
              {hoveredMeta ? hoveredMeta.label : '—'}
            </span>
          </div>

          <ul className="d3-list">
            {SURFACES.map((s) => {
              const on = state.selectedSurface === s.id
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`d3-chip${on ? ' on' : ''}`}
                    aria-pressed={on}
                    onClick={() => selectSurface(s.id)}
                  >
                    <span className="d3-code">{s.display}</span>
                    {s.label}
                  </button>
                </li>
              )
            })}
          </ul>

          <pre className="d3-state">{JSON.stringify(state, null, 2)}</pre>

          {stats && (
            <p className="d3-stats">
              {stats.crownTriangles.toLocaleString('ro-RO')} triunghiuri coroană ·{' '}
              {stats.rootTriangles.toLocaleString('ro-RO')} rădăcini · geometrie procedurală, 0 KB
              asset
            </p>
          )}
        </aside>
      </div>
    </div>
  )
}
