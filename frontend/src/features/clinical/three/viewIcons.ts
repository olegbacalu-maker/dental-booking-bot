import type { IconName } from '../../../components/icons'
import type { ViewName } from './scene'

/* Значок ракурса (Олег 24.10 «ракурсы значками») — один словарь на обе сцены:
   одонтограмму (`Odontogram3D`) и 3D над листом пародонтограммы (`Perio3D`).
   Сами значки — `layout._I` сервера через сгенерированный `icons.ts`. */
export const VIEW_ICON: Record<ViewName, IconName> = {
  frontal: 'arch-front', sus: 'arch-up', jos: 'arch-down', dreapta: 'arch-right', stanga: 'arch-left',
}
