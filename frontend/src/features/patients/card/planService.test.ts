import { describe, expect, it } from 'vitest'
import { priceAfterProcedure, priceIsListed, priceNote, serviceIdFor, type ServiceOption } from './planService'

/* Цена из прайса — правило без экрана: одна сумма подставляется, из диапазона
   цену выбирает человек, вписанное рукой не переписывается. */
const S: ServiceOption[] = [
  { id: 'hygiene', label: 'Igienizare', price: 1000, price_hint: '' },
  { id: 'crown', label: 'Coroană zirconiu', price: 3000, price_hint: '' },
  { id: 'canal', label: 'Tratament de canal', price: null, price_hint: '1200–1800 MDL' },
  { id: 'consult', label: 'Consultație', price: null, price_hint: '' },
  { id: 'old', label: 'Radiografie' },
]
const EMPTY = { price: '', auto: false }

describe('priceAfterProcedure', () => {
  it('услуга с одной суммой — сумма в пустое поле, помечена как подставленная', () => {
    expect(priceAfterProcedure(S, '', 'Igienizare', EMPTY)).toEqual({ price: '1000', auto: true })
    expect(priceAfterProcedure(S, 'Igien', ' Igienizare ', EMPTY)).toEqual({ price: '1000', auto: true })
  })

  it('диапазон — поле остаётся пустым; подставленная раньше цена другой услуги стирается', () => {
    expect(priceAfterProcedure(S, '', 'Tratament de canal', EMPTY)).toEqual({ price: '', auto: false })
    expect(priceAfterProcedure(S, 'Igienizare', 'Tratament de canal', { price: '1000', auto: true }))
      .toEqual({ price: '', auto: false })
  })

  it('подставленная цена идёт за услугой, вписанная рукой — остаётся', () => {
    expect(priceAfterProcedure(S, 'Igienizare', 'Coroană zirconiu', { price: '1000', auto: true }))
      .toEqual({ price: '3000', auto: true })
    const mine = { price: '900', auto: false }
    expect(priceAfterProcedure(S, 'Igienizare', 'Coroană zirconiu', mine)).toBe(mine)
    expect(priceAfterProcedure(S, '', 'Tratament de canal', mine)).toBe(mine)
  })

  it('свободный текст и та же услуга цену не трогают', () => {
    const f = { price: '1000', auto: true }
    expect(priceAfterProcedure(S, 'Igienizare', 'Igienizare + fluor', f)).toBe(f)
    expect(priceAfterProcedure(S, 'Igienizare', 'Igienizare ', f)).toBe(f)
    /* дописали и вернулись к другой услуге — подставленная цена сменилась */
    expect(priceAfterProcedure(S, 'Igienizare + fluor', 'Coroană zirconiu', f)).toEqual({ price: '3000', auto: true })
  })

  it('процедуру стёрли — подставленная цена уходит с ней, вписанная рукой остаётся', () => {
    expect(priceAfterProcedure(S, 'Igienizare', '', { price: '1000', auto: true })).toEqual({ price: '', auto: false })
    const mine = { price: '900', auto: false }
    expect(priceAfterProcedure(S, 'Igienizare', ' ', mine)).toBe(mine)
  })

  it('услуга без цены в ответе сервера (прежний формат) — поле пустое', () => {
    expect(priceAfterProcedure(S, '', 'Radiografie', EMPTY)).toEqual({ price: '', auto: false })
    expect(serviceIdFor(S, 'Radiografie')).toBe('old')
  })
})

describe('priceNote', () => {
  it('одна сумма: поле равно прайсу — «din lista de prețuri», иначе цена прайса рядом', () => {
    expect(priceNote(S, 'Igienizare', '1000')).toEqual({ text: 'din lista de prețuri', warn: false })
    expect(priceNote(S, 'Igienizare', '900')).toEqual({ text: 'în listă: 1 000 MDL', warn: false })
    expect(priceNote(S, 'Igienizare', '')).toEqual({ text: 'în listă: 1 000 MDL', warn: false })
  })

  it('диапазон: пустое поле просит цену, заполненное — показывает диапазон', () => {
    expect(priceNote(S, 'Tratament de canal', '')).toEqual({ text: 'în listă: 1200–1800 MDL, scrieți prețul', warn: true })
    expect(priceNote(S, 'Tratament de canal', '1500')).toEqual({ text: 'în listă: 1200–1800 MDL', warn: false })
  })

  it('цены в прайсе нет или процедура не из прайса — подсказки нет', () => {
    expect(priceNote(S, 'Consultație', '')).toBeNull()
    expect(priceNote(S, 'Radiografie', '')).toBeNull()
    expect(priceNote(S, 'Igienizare + fluor', '1000')).toBeNull()
  })
})

describe('priceIsListed', () => {
  it('цена позиции равна цене её услуги в прайсе', () => {
    expect(priceIsListed(S, 'Igienizare', '1000')).toBe(true)
    expect(priceIsListed(S, 'Igienizare', '900')).toBe(false)
    expect(priceIsListed(S, 'Tratament de canal', '')).toBe(false)
    expect(priceIsListed(S, 'Altceva', '1000')).toBe(false)
  })
})
