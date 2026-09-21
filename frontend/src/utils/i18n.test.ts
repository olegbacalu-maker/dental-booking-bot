import { afterEach, describe, expect, it } from 'vitest'
import { t } from './i18n'

const T = t('demo', { save: 'Salvează', off: 'Oprește' } as const)

afterEach(() => {
  delete window.DP_I18N
})

describe('шов каталога', () => {
  it('без каталога отдаёт румынский из самого файла', () => {
    expect(T.save).toBe('Salvează')
  })

  it('каталог накрывает ключ по имени `нс.ключ`', () => {
    window.DP_I18N = { 'demo.save': 'Сохранить' }
    expect(T.save).toBe('Сохранить')
    expect(T.off).toBe('Oprește')
  })

  it('чужое пространство имён не подменяет ничего', () => {
    window.DP_I18N = { 'other.save': 'Сохранить' }
    expect(T.save).toBe('Salvează')
  })

  it('пустое значение — это отсутствие перевода, а не пустая кнопка', () => {
    window.DP_I18N = { 'demo.save': '' }
    expect(T.save).toBe('Salvează')
  })

  /* ⭐ Ровно ради этого шов — Proxy, а не копия объекта на импорте: каталог
     приезжает скриптом страницы, а модули экранов грузятся раньше него. */
  it('каталог, приехавший ПОСЛЕ импорта, всё равно действует', () => {
    expect(T.off).toBe('Oprește')
    window.DP_I18N = { 'demo.off': 'Выключить' }
    expect(T.off).toBe('Выключить')
  })
})
