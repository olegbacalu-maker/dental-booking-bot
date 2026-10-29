import { describe, expect, it } from 'vitest'
import { dmy, letter, mailto, type RecallRow } from './recall'

/* «Rechemări»: письмо и адрес `mailto:` — кодирование (диакритика, `&`,
   переносы строк), язык из фиши, текст без цен и акций. */

const ROW: RecallRow = {
  pid: 7, name: 'Maria Ceban', phone: '069 123 456', email: 'maria&co@example.md', lang: 'ro',
  service_id: 'hygiene', service: 'Igienizare profesională', months: 6,
  last_at: '2026-04-02', doctor: 'Dr. Rusu', due: '2026-10-02', late_days: 4, late: 'întârziere 4 zile',
  booked: null, mark: null, tab: 'due',
}
const CLINIC = { name: 'Zâmbet & Co', phone: '+373 60 000 000' }

describe('recall: письмо и mailto', () => {
  it('RO: тема и текст — клинические, с именем, услугой, сроком и телефоном; без цен', () => {
    const l = letter(ROW, CLINIC)
    expect(l.subject).toBe('Control periodic — Zâmbet & Co')
    expect(l.body).toContain('Bună ziua, Maria.')
    expect(l.body).toContain('Au trecut 6 luni de la ultima procedură „Igienizare profesională” la Zâmbet & Co')
    expect(l.body).toContain('+373 60 000 000')
    expect(l.body).not.toMatch(/MDL|%|reducere|ofert/i)
  })

  it('RU: язык из фиши', () => {
    const l = letter({ ...ROW, lang: 'ru', name: 'Ольга Руссу' }, CLINIC)
    expect(l.subject).toBe('Плановый контроль — Zâmbet & Co')
    expect(l.body).toContain('Здравствуйте, Ольга.')
    expect(l.body).toContain('Прошло 6 мес.')
  })

  it('mailto: адрес, тема и тело в кодировке URL — диакритика, &, переносы строк', () => {
    const href = mailto(ROW.email, letter(ROW, CLINIC))
    expect(href.startsWith('mailto:maria%26co%40example.md?subject=')).toBe(true)
    expect(href).toContain('subject=Control%20periodic%20%E2%80%94%20Z%C3%A2mbet%20%26%20Co')
    expect(href).toContain('%0A%0A')
    expect(href).not.toContain('\n')
    expect(href).not.toContain(' ')
    /* обратно читается тем же письмом */
    const u = new URL(href)
    expect(u.searchParams.get('subject')).toBe('Control periodic — Zâmbet & Co')
    expect(u.searchParams.get('body')).toContain('Bună ziua, Maria.\n\nAu trecut 6 luni')
  })

  it('dmy: ISO → дд.мм.гггг, чужое — как есть', () => {
    expect(dmy('2026-10-02')).toBe('02.10.2026')
    expect(dmy('')).toBe('')
    expect(dmy('03.11')).toBe('03.11')
  })
})
