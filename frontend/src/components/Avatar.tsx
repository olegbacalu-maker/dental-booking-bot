/**
 * Аватар врача — та же разметка, что у серверного core/visits._avatar: фото,
 * если оно есть, иначе инициалы на цвете врача. И цвет, и инициалы, и адрес
 * фото приходят с сервера — клиент их не считает.
 */
interface Props {
  color: string
  initials: string
  photo: string
  big?: boolean
}

export function Avatar({ color, initials, photo, big }: Props) {
  return (
    <span className={big ? 'avatar big' : 'avatar'} style={{ background: color }}>
      {photo ? <img src={photo} alt="" /> : initials}
    </span>
  )
}
