import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { ApiError } from '../../types/api'
import type { OdontogramOcluzie } from './chart'

/* Прикус в панели рабочего стола ТОЛЬКО ДЛЯ ЧТЕНИЯ (этап 3 «ocluzie», 07.11):
   так панель «Dintele» без выбранного зуба выглядит на странице «Pe tot
   ecranul» (`/admin/patient/{pid}/odontograma`), где фиши нет. Форма
   (`OcluziaCard`) живёт во вкладке «Odontogramă» фиши: ей нужны словари и
   врачи фиши, а GET фиши — это ОТКРЫТИЕ (строка «Fișa deschisă» журнала
   доступа по закону 195), и тянуть его ради формы на этой странице нельзя.
   Здесь — та же строка, что на листе 043/e (`summary` сервера), и дорога к
   форме. ⛔ Никаких слов о норме: пусто — «не записано». */

/** Запись прикуса из панели; отказ возвращается — форма подсвечивает поле. */
export type OclSave = (fields: Record<string, string>) => Promise<ApiError | null>

const T = {
  title: 'Ocluzia',
  none: 'neînregistrată',
  edit: 'Editează în fișă',
  add: 'Completează în fișă',
} as const

export function OcluziaRecord({ pid, oc }: { pid: number; oc: OdontogramOcluzie }) {
  return (
    <div className="fcard dp-ocl-rec" id="ocluzia">
      <h3>{T.title} {!oc.recorded && <span className="pill grey">{T.none}</span>}</h3>
      {oc.recorded && oc.summary && <p className="ocsum">{oc.summary}</p>}
      <AppLink className="dp-ocl-go" href={`/admin/patient/${pid}?tab=odonto`}>
        <Icon name="pen" /> {oc.recorded ? T.edit : T.add}
      </AppLink>
    </div>
  )
}
