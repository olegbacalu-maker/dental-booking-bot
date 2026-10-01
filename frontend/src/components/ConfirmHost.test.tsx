import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ask, when } from './confirm'
import { ConfirmHost } from './ConfirmHost'

/* Окно подтверждения (01.10): вопрос с именем того, что удаляется, две
   кнопки, Esc = отказ, один вопрос за раз; без хоста — окно браузера, чтобы
   действие не прошло без вопроса вовсе. */

const dialog = () => document.querySelector('dialog.dp-ask') as HTMLDialogElement

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ConfirmHost', () => {
  it('без хоста — окно браузера с тем же текстом', async () => {
    const spy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    expect(await ask('Ștergeți?')).toBe(false)
    expect(spy).toHaveBeenCalledWith('Ștergeți?')
  })

  it('вопрос показан своим окном, согласие — true, кнопки по умолчанию', async () => {
    render(<ConfirmHost />)
    expect(dialog().open).toBe(false)
    const p = ask('Redeschideți programarea?')
    await waitFor(() => expect(dialog().open).toBe(true))
    expect(screen.getByText('Redeschideți programarea?')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Renunță' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Da' }))
    expect(await p).toBe(true)
    await waitFor(() => expect(dialog().open).toBe(false))
  })

  it('необратимое: красная кнопка «Șterge», заголовок, отказ — false', async () => {
    render(<ConfirmHost />)
    const p = ask({ title: 'Ștergerea datelor', text: 'Ștergeți documentul „rx.png"?', danger: true })
    await waitFor(() => expect(dialog().open).toBe(true))
    expect(screen.getByText('Ștergerea datelor')).toBeTruthy()
    expect(screen.getByText('Ștergeți documentul „rx.png"?')).toBeTruthy()
    const del = screen.getByRole('button', { name: 'Șterge' })
    expect(del.className).toContain('dp-ask-danger')
    /* фокус на отказе: Enter не удаляет случайно */
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Renunță' }))
    fireEvent.click(screen.getByRole('button', { name: 'Renunță' }))
    expect(await p).toBe(false)
  })

  it('своя подпись согласия и Esc (закрытие окна) = отказ', async () => {
    render(<ConfirmHost />)
    const p = ask({ text: 'Reluați?', ok: 'Reia' })
    await waitFor(() => expect(dialog().open).toBe(true))
    expect(screen.getByRole('button', { name: 'Reia' })).toBeTruthy()
    fireEvent(dialog(), new Event('close'))
    expect(await p).toBe(false)
  })

  it('новый вопрос до ответа закрывает прежний отказом', async () => {
    render(<ConfirmHost />)
    const first = ask('Unu?')
    await waitFor(() => expect(dialog().open).toBe(true))
    const second = ask('Doi?')
    expect(await first).toBe(false)
    expect(screen.getByText('Doi?')).toBeTruthy()
    expect(screen.queryByText('Unu?')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Da' }))
    expect(await second).toBe(true)
  })

  it('when: пустой вопрос действует сразу, непустой — только по согласию', async () => {
    render(<ConfirmHost />)
    const run = vi.fn()
    await when('', run)
    expect(run).toHaveBeenCalledTimes(1)
    const p = when('Sigur?', run)
    await waitFor(() => expect(dialog().open).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Renunță' }))
    await p
    expect(run).toHaveBeenCalledTimes(1)
    const q = when('Sigur?', run)
    await waitFor(() => expect(dialog().open).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Da' }))
    await q
    expect(run).toHaveBeenCalledTimes(2)
  })
})
