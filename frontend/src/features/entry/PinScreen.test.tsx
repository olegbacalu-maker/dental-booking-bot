import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ShellModel } from '../../layouts/shell'
import { ApiError } from '../../types/api'
import { PinScreen } from './PinScreen'

/* Модель оболочки на момент выхода — как её отдаёт `App` замку (B4.4). */
const M: ShellModel = {
  identity: null,
  clinic: { name: 'Clinica Test', mark: '', logo_topbar: '', logo: '/admin/clinic-logo' },
  runtime: { version: '9.9.9', tz: 'Europe/Chisinau' },
  about: { data: '', license_until: '' },
  entry: { pin: true, pin_max: 8, backdrop: '<div class="dp-bg" data-x="фон"></div>' },
  nav: { active: '', items: [], sync: [], foot_title: '' },
  signals: {
    license: { shown: false, html: '' },
    tamper: { shown: false, html: '' },
    split: { shown: false, html: '' },
    slot: { shown: false, html: '' },
    setup: { shown: false, html: '' },
    demo: { shown: false, html: '' },
    backup: { shown: false, html: '' },
  },
  frame: {
    title: '', sub: '', crumbs: [], rail: false, update: '', msg: '',
    site: { href: 'https://dentpilot.md', mark: '<svg class="bcmark"></svg>' },
    feedback: { email: 'x@y.md', href: 'mailto:x@y.md' }, today: '2026-10-22',
  },
}

afterEach(cleanup)

async function pressEnter(pin: string) {
  fireEvent.change(screen.getByLabelText('PIN'), { target: { value: pin } })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Intră' })) })
}

describe('PinScreen: экран PIN без поля id (22.10)', () => {
  it('в карточке одно поле — PIN; «ID (opțional)» нет, курсор в PIN', () => {
    render(<PinScreen m={M} enter={vi.fn()} />)
    /* ⛔ Поле «ID (opțional)» снято: PIN уникален на клинику (`auth.pin_free`),
       сервер находит человека по одному PIN. Поле было наследием времён до
       уникальности; на странице входа сервера его тоже нет (`test_pin`). */
    expect(screen.queryByLabelText('ID (opțional)')).toBeNull()
    expect(document.querySelector('input[name="uid"]')).toBeNull()
    const inputs = document.querySelectorAll('.dp-lock-card input')
    expect(inputs).toHaveLength(1)
    expect((inputs[0] as HTMLInputElement).name).toBe('password')
    expect((inputs[0] as HTMLInputElement).maxLength).toBe(8)
    expect(document.activeElement).toBe(screen.getByLabelText('PIN'))
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Clinica Test')
    expect((document.querySelector('.dp-lock-card img.clogo') as HTMLImageElement).getAttribute('src')).toBe('/admin/clinic-logo')
    expect(document.querySelector('.dp-lock [data-x="фон"]')).toBeTruthy()
  })

  it('«Intră» — дверь получает один PIN, uid пустой (дверь его принимает, как и раньше)', async () => {
    const enter = vi.fn().mockResolvedValue(undefined)
    render(<PinScreen m={M} enter={enter} />)
    await pressEnter('3333')
    expect(enter).toHaveBeenCalledTimes(1)
    expect(enter).toHaveBeenCalledWith('3333', '')
  })

  it('отказ сервера — слово на месте, PIN очищен, кнопка снова «Intră»', async () => {
    const enter = vi.fn().mockRejectedValue(
      new ApiError({ kind: 'validation', code: 'login_bad', text: 'PIN greșit', field: 'pin' }, 'v'))
    render(<PinScreen m={M} enter={enter} />)
    await pressEnter('1111')
    expect((await screen.findByRole('alert')).textContent).toBe('PIN greșit')
    expect((screen.getByLabelText('PIN') as HTMLInputElement).value).toBe('')
    expect(screen.getByRole('button', { name: 'Intră' })).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByLabelText('PIN'))
  })
})
