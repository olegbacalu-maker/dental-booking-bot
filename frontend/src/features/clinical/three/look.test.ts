import { describe, expect, it } from 'vitest'
import { COLOR, effState, hex, lerpHex, structChanged, targetLook } from './look'

/* Вид зуба — таблица состояний → видимость и цвета, с палитрой сервера. */

const PALETTE = { ok: '#1F2937', carie: '#EF4444', obturatie: '#3B82F6', coroana: '#F59E0B', implant: '#8B5CF6', extras: '#64748B', lipsa: '#CBD5E1' }
const tooth = (state: string, sfst: Record<string, string> = {}, mk: string[] = [], bridge: { role: string; material: string } | null = null) =>
  ({ state, sfst, mk, bridge })

describe('цвета', () => {
  it('hex читает #RRGGBB, прочее — 0; lerp по компонентам', () => {
    expect(hex('#EF4444')).toBe(0xef4444)
    expect(hex(' ef4444 ')).toBe(0xef4444)
    expect(hex('red')).toBe(0)
    expect(lerpHex(0x000000, 0xffffff, 0.5)).toBe(0x808080)
    expect(lerpHex(0x102030, 0x102030, 0.7)).toBe(0x102030)
    expect(lerpHex(0x000000, 0xffffff, 2)).toBe(0xffffff)
  })
})

describe('эффективное состояние', () => {
  it('поверхность с кариесом красит «здоровый» зуб; у коронки поверхности не считаются', () => {
    expect(effState(tooth('ok'))).toBe('ok')
    expect(effState(tooth('ok', { O: 'obturatie' }))).toBe('obturatie')
    expect(effState(tooth('ok', { O: 'obturatie', M: 'carie' }))).toBe('carie')
    expect(effState(tooth('coroana', { O: 'carie' }))).toBe('coroana')
    expect(effState(tooth('implant'))).toBe('implant')
  })
})

describe('вид по состоянию', () => {
  it('здоровый: эмаль везде, коронка и корни видны, ни винта, ни лунки', () => {
    const l = targetLook(tooth('ok'), PALETTE)
    expect(l.cols).toEqual([COLOR.enamel, COLOR.enamel, COLOR.enamel, COLOR.enamel, COLOR.enamel])
    expect([l.crown, l.roots, l.screw, l.socket, l.ghost, l.mark]).toEqual([true, true, false, false, false, false])
    expect(l.opacity).toBe(1)
    expect(l.metalness).toBe(0)
  })

  it('кариес на поверхности O красит только её цветом палитры (0.6), остальные — эмаль', () => {
    const l = targetLook(tooth('ok', { O: 'carie' }), PALETTE)
    expect(l.st).toBe('carie')
    expect(l.cols[0]).toBe(lerpHex(COLOR.enamel, 0xef4444, 0.6))
    expect(l.cols.slice(1)).toEqual([COLOR.enamel, COLOR.enamel, COLOR.enamel, COLOR.enamel])
  })

  it('кариес зуба целиком без поверхностей — лёгкий оттенок (0.32) на всех пяти', () => {
    const l = targetLook(tooth('carie'), PALETTE)
    const c = lerpHex(COLOR.enamel, 0xef4444, 0.32)
    expect(l.cols).toEqual([c, c, c, c, c])
  })

  it('имплант: винт есть, корней нет, коронка керамическая', () => {
    const l = targetLook(tooth('implant'), PALETTE)
    expect([l.screw, l.roots, l.crown, l.implant]).toEqual([true, false, true, true])
    expect(l.cols[0]).toBe(COLOR.ceramic)
    expect(l.roughness).toBe(0.22)
  })

  it('коронка и тело моста — золото без корней у тела; опора моста корни оставляет', () => {
    const crown = targetLook(tooth('coroana'), PALETTE)
    expect([crown.gold, crown.roots, crown.metalness]).toEqual([true, true, 0.85])
    const pontic = targetLook(tooth('lipsa', {}, [], { role: 'corp', material: 'zirconiu' }), PALETTE)
    expect([pontic.gold, pontic.pontic, pontic.roots, pontic.ghost]).toEqual([true, true, false, false])
    const abutment = targetLook(tooth('ok', {}, [], { role: 'stalp', material: 'zirconiu' }), PALETTE)
    expect([abutment.gold, abutment.roots]).toEqual([false, true])
  })

  it('⭐ отсутствующий — пустое место с пунктиром шейки, БЕЗ коронки (26.09: призрак 0,22 читался целым зубом); удалённый — лунка', () => {
    const ghost = targetLook(tooth('lipsa'), PALETTE)
    expect([ghost.ghost, ghost.gap, ghost.crown, ghost.roots, ghost.socket]).toEqual([true, true, false, false, false])
    const gone = targetLook(tooth('extras'), PALETTE)
    expect([gone.gone, gone.crown, gone.socket, gone.roots, gone.gap]).toEqual([true, false, true, false, false])
    // тело моста на отсутствующем — золото, не пустое место
    const pontic = targetLook(tooth('lipsa', {}, [], { role: 'corp', material: 'zr' }), PALETTE)
    expect([pontic.gap, pontic.crown]).toEqual([false, true])
    expect(targetLook(tooth('ok'), PALETTE).gap).toBe(false)
  })

  it('отметка «în tratament» — кольцо; пустая палитра не роняет, а даёт чёрный оттенок', () => {
    expect(targetLook(tooth('ok', {}, ['tratament']), PALETTE).mark).toBe(true)
    const l = targetLook(tooth('carie'), {})
    expect(l.cols[0]).toBe(lerpHex(COLOR.enamel, 0, 0.32))
  })

  it('сцена смены состояния нужна при смене состояния или роли тела моста, не при перекраске поверхности', () => {
    const a = targetLook(tooth('ok'), PALETTE)
    const b = targetLook(tooth('ok', { O: 'obturatie' }), PALETTE)
    const c = targetLook(tooth('ok', { O: 'carie' }), PALETTE)
    expect(structChanged(null, a)).toBe(false)
    expect(structChanged(a, b)).toBe(true)
    expect(structChanged(b, c)).toBe(true)
    expect(structChanged(c, targetLook(tooth('ok', { M: 'carie' }), PALETTE))).toBe(false)
  })
})
