import { api, type ApiResult } from './api'

/* Дверь журнала (B4.4): вход и выход без перезагрузки — `modules/entry/api.py`.
   Проверка PIN, счётчик неудач и блокировка — на сервере, те же, что у формы
   входа; здесь только два запроса. */

export interface LoginData {
  uid: string
  name: string
}

export const auth = {
  /** Вход: отказ — `ApiError` с текстом сервера (`login_bad`, `lock_pin`,
   *  `auth_broken`); 401 здесь не бывает, экран показывает отказ на месте. */
  login: (pin: string, uid: string): Promise<ApiResult<LoginData>> =>
    api.post<LoginData>('/auth/login', { pin, uid }),
  /** Выход: сервер снимает куку. 401 — уже снаружи, это не отказ. */
  logout: (): Promise<ApiResult<unknown>> => api.post<unknown>('/auth/logout'),
}
