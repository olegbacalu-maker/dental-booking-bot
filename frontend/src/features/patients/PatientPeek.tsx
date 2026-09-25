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
}

interface Props {
  peek: PeekState | null
  onClose: () => void
}

export function PatientPeek({ peek, onClose }: Props) {
  /* Ссылки в прозе сервера («Editează fișa», «Vezi profilul complet») — тем
     же переходом, что и AppLink (B4): голыми они перезагружали документ, и
     переход поиск → фиша «дёргался» (Олег, канарейка 1.30.2). */
  const prose = useProseLinks()
  let body
  if (!peek) {
    body = (
      <div className="pp-empty">
        <Icon name="eye" />
        <span>{T.empty}</span>
      </div>
    )
  } else if (peek.error) {
    body = <div className="pp-empty"><span>{peek.error}</span></div>
  } else if (peek.html === null) {
    body = <div className="pp-empty"><span>{T.loading}</span></div>
  } else {
    body = <div onClick={prose} dangerouslySetInnerHTML={{ __html: peek.html }} />
  }
  return (
    <>
      <aside className={peek ? 'ppanel open' : 'ppanel'} aria-label="Previzualizare">
        <button type="button" className="pp-x" onClick={onClose} title={T.close}>
          <Icon name="close" />
        </button>
        <div>{body}</div>
      </aside>
      <div className={peek ? 'pp-veil on' : 'pp-veil'} onClick={onClose} />
    </>
  )
}
