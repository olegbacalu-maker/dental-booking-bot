import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import type { FaqData } from './settings'
import { openScreen } from '../../test/openScreen'
import { FaqScreen, loadFaq } from './FaqScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const FAQ: FaqData = {
  items: [
    { icon: 'save', question: 'Cât de des fac copii de rezervă?', answer: '<p>O copie <b>pe săptămână</b>.</p>' },
    { icon: 'box', question: 'Cum deschid arhiva?', answer: '<p>Cu 7-Zip.</p>' },
  ],
  contact: 'dentpilotpro@gmail.com',
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })

const open = (navigate?: (url: string) => void) => openScreen(
  '/admin/settings/faq', '/admin/settings/faq', <FaqScreen {...(navigate ? { navigate } : {})} />,
  loadFaq, navigate)

afterEach(() => {
  cleanup()
  get.mockReset()
})

describe('FaqScreen', () => {
  it('вопросы раскрываются браузером, ответы — HTML сервера, контакт — ссылка', async () => {
    get.mockResolvedValueOnce(ok(FAQ))
    open()
    expect(await screen.findByText('Cât de des fac copii de rezervă?')).toBeTruthy()
    const details = document.querySelectorAll('details.faq')
    expect(details.length).toBe(2)
    expect(details[0]?.querySelector('summary svg')).toBeTruthy()
    expect(details[0]?.querySelector('.dp-faq-a b')?.textContent).toBe('pe săptămână')
    expect(screen.getByText('Cu 7-Zip.')).toBeTruthy()
    const mail = screen.getByRole('link', { name: 'dentpilotpro@gmail.com' })
    expect(mail.getAttribute('href')).toBe('mailto:dentpilotpro@gmail.com')
    expect(get).toHaveBeenCalledWith('/settings/faq', expect.anything())
  })
})
