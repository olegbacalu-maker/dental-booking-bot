/* Позиция плана из прайса: процедура остаётся свободным текстом, а подсказки —
   услуги клиники. Ключ услуги уходит, только пока текст равен её имени: по нему
   потом считаются техкарта, лаборатория и % врача, и чужой ключ хуже пустого.
   Последнее слово — у сервера (`routes._plan_service_id`). */

export interface ServiceOption { id: string; label: string }

export function serviceIdFor(services: ServiceOption[], procedure: string): string {
  const text = procedure.trim()
  return services.find((s) => s.label === text)?.id ?? ''
}

export function ServiceList({ id, services }: { id: string; services: ServiceOption[] }) {
  return (
    <datalist id={id}>
      {services.map((s) => <option key={s.id} value={s.label} />)}
    </datalist>
  )
}
