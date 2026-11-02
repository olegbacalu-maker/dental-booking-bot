/**
 * Подсказка-СОСТОЯНИЕ сервера внутри модели экрана (22.10, права врача):
 * учётка `medic` без привязки к врачу получает пустой журнал и строку
 * «contul nu e legat de un medic» — в дне, на панели, в неделе и у кресла
 * одним ключом `notice`.
 *
 * ⛔ Слова и тон — сервера (`layout.msg_view`, тот же словарь `MSG_BANNER`,
 * что у плашек ответа): клиент код не переводит. Это не `Toast`: плашка
 * отвечает на действие и закрывается, состояние стоит, пока оно есть, — та
 * же разметка `.banner`, что у баннеров каркаса, в потоке экрана.
 */
export interface ServerNotice {
  code: string
  tone: string
  text: string
}

/**
 * Та же подсказка сервера, но СТРОКОЙ на месте кнопки (02.11): выгрузка
 * файлом, которую сервер из сети не отдаст (`auth.LOCAL_ONLY`, код
 * `only_local`), — в ряду кнопок экрана, а не баннером над всем экраном:
 * экраны Pacienți и Programări второй ПК открывает весь день.
 */
export function NoticeInline({ n }: { n?: ServerNotice | null | undefined }) {
  if (!n || !n.text) return null
  return <small className="dp-muted" role="note" data-code={n.code}>{n.text}</small>
}

export function Notice({ n }: { n?: ServerNotice | null | undefined }) {
  if (!n || !n.text) return null
  return (
    <div className={`banner ${n.tone}`} role={n.tone === 'err' ? 'alert' : 'status'}
      data-code={n.code}>
      {n.text}
    </div>
  )
}
