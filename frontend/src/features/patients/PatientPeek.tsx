import { useEffect, type RefObject } from 'react'
import { useProseLinks } from '../../components/AppLink'
import { Icon } from '../../components/Icon'

/* Боковой предпросмотр фиши. Кусок разметки приходит с сервера
   (GET /api/patients/{id}/peek — та же функция, что у старой страницы):
   это сводка фиши словами сервера, все значения экранированы там; до
   переезда самой фиши второй рисовальщик ей ни к чему. */
const T = {
  close: 'Închide',
  empty: 'Alegeți un pacient din listă pentru previzualizare — fără să părăsiți lista',
  loading: 'Se încarcă…',
} as const

export interface PeekState {
  id: number
  html: string | null
  error: string
  /** Сводка этого пациента ещё в пути (06.11.2026). `html` при этом — сводка
   *  ПРЕЖНЕГО пациента (или `null`, если панель была пуста): она остаётся на
   *  экране до ответа, чтобы панель не мигала словом «Se încarcă…» на каждом
   *  щелчке по списку. ⛔ Прежняя сводка в это время не нажимается: её ссылки
   *  ведут к прежнему пациенту, а в списке выбран уже новый. */
  pending?: boolean
  /** Ответ задержался — пора сказать «Se încarcă…» словом. */
  slow?: boolean
}

/* Сколько держать содержимое закрытой панели, если её переход не сообщил о
   конце (движение выключено в системе): дольше самого выезда `--dur-slow`. */
const GHOST_MS = 400

interface Props {
  peek: PeekState | null
  /** Что показывает УЕЗЖАЮЩАЯ панель (06.11): узкое окно закрывает предпросмотр
   *  выездом за край, и до его конца в панели остаётся то, что в ней было, —
   *  раньше содержимое в том же кадре менялось на подсказку пустой панели, и
   *  уезжала уже она. На широком окне панель никуда не едет и призрака нет. */
  ghost?: PeekState | null
  /** Панель уехала — призрака можно снять. */
  onGhostDone?: () => void
  onClose: () => void
  /** Узел панели: экран спрашивает у него, едет ли она при закрытии. */
  panel?: RefObject<HTMLElement | null>
}

export function PatientPeek({ peek, ghost = null, onGhostDone, onClose, panel }: Props) {
  /* Ссылки в прозе сервера («Editează», «Profil complet ›») — тем
     же переходом, что и AppLink (B4): голыми они перезагружали документ, и
     переход поиск → фиша «дёргался» (Олег, канарейка 1.30.2). */
  const prose = useProseLinks()
  const leaving = peek === null && ghost !== null
  /* ⛔ Призрака снимает и таймер, а не только конец перехода: без движения
     (`prefers-reduced-motion`, выезд без длительности) события не будет. */
  useEffect(() => {
    if (!leaving || !onGhostDone) return
    const t = window.setTimeout(onGhostDone, GHOST_MS)
    return () => window.clearTimeout(t)
  }, [leaving, onGhostDone])

  const shown = peek ?? ghost
  let body
  if (!shown || (shown.pending && shown.html === null && !shown.slow)) {
    /* пусто — и первые мгновения первого щелчка: подсказка стоит, пока сводка
       в пути, а не меняется на «Se încarcă…» на один кадр */
    body = (
      <div className="pp-empty">
        <Icon name="eye" />
        <span>{T.empty}</span>
      </div>
    )
  } else if (shown.error) {
    body = <div className="pp-empty"><span>{shown.error}</span></div>
  } else if (shown.html === null) {
    body = <div className="pp-empty"><span>{T.loading}</span></div>
  } else {
    /* `inert` — у прежней сводки, пока новая в пути, и у призрака: ни щелчок,
       ни Tab не попадут в ссылки того, что уже не выбрано */
    const idle = shown.pending === true || leaving
    body = (
      <div onClick={prose} inert={idle || undefined} aria-busy={shown.pending || undefined}
        dangerouslySetInnerHTML={{ __html: shown.html }} />
    )
  }
  return (
    <>
      <aside ref={panel} className={peek ? 'ppanel open' : 'ppanel'} aria-label="Previzualizare"
        onTransitionEnd={(e) => {
          if (leaving && e.target === e.currentTarget && e.propertyName === 'transform') onGhostDone?.()
        }}>
        <button type="button" className="pp-x" onClick={onClose} title={T.close}>
          <Icon name="close" />
        </button>
        <div>{body}</div>
      </aside>
      <div className={peek ? 'pp-veil on' : 'pp-veil'} onClick={onClose} />
    </>
  )
}
