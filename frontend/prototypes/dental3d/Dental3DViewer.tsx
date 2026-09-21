import { useEffect, useImperativeHandle, useRef } from 'react'
import type { Ref } from 'react'
import { createToothScene, type ToothScene, type ToothSceneStats } from './scene'
import type { SurfaceId } from './surfaces'

/**
 * React-обёртка над сценой: владеет узлом-контейнером и жизненным циклом.
 *
 * Правило одно: React НЕ перерисовывает 3D. Дерево компонента статично, а
 * подсветка поверхности — императивный вызов в already-созданную сцену.
 * Иначе каждое движение мыши гоняло бы reconciliation по дереву, из которого
 * ничего не меняется, — и это был бы ещё один источник «дёрганья».
 */

export interface Dental3DViewerHandle {
  resetView: () => void
}

interface Props {
  /** Выбранная поверхность из состояния React. */
  selected: SurfaceId | null
  onHover: (surface: SurfaceId | null) => void
  onSelect: (surface: SurfaceId) => void
  onStats?: (stats: ToothSceneStats) => void
  ref?: Ref<Dental3DViewerHandle>
}

export function Dental3DViewer({ selected, onHover, onSelect, onStats, ref }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const sceneRef = useRef<ToothScene | null>(null)

  // Колбэки живут в ref: сцена создаётся ОДИН раз и не пересоздаётся из-за
  // новой ссылки на функцию. Пересоздание = новый WebGL-контекст = вспышка.
  const hoverRef = useRef(onHover)
  const selectRef = useRef(onSelect)
  const statsRef = useRef(onStats)
  hoverRef.current = onHover
  selectRef.current = onSelect
  statsRef.current = onStats

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const scene = createToothScene({
      container: host,
      onHover: (s) => hoverRef.current(s),
      onSelect: (s) => selectRef.current(s),
    })
    sceneRef.current = scene
    statsRef.current?.(scene.stats)
    return () => {
      sceneRef.current = null
      scene.dispose()
    }
  }, [])

  useEffect(() => {
    sceneRef.current?.setSelected(selected)
  }, [selected])

  useImperativeHandle(ref, () => ({
    resetView: () => sceneRef.current?.resetView(),
  }), [])

  return <div ref={hostRef} className="d3-stage" />
}
