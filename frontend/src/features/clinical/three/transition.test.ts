import { describe, expect, it } from 'vitest'
import { targetLook } from './look'
import { comesFrom, sceneFor, startLift } from './transition'

/* Выбор сцены — таблица по виду зуба: имплант впереди всего, потом лунка,
   призрак, золото, живой зуб. */

const P = { ok: '#1F2937', carie: '#EF4444', obturatie: '#3B82F6', coroana: '#F59E0B', implant: '#8B5CF6', extras: '#64748B', lipsa: '#CBD5E1' }
const look = (state: string, bridge: { role: string; material: string } | null = null) =>
  targetLook({ state, sfst: {}, mk: [], bridge }, P)

describe('сцена по виду', () => {
  it('имплант, удаление, отсутствие, золото, живой', () => {
    expect(sceneFor(look('implant'))).toBe('implant')
    expect(sceneFor(look('extras'))).toBe('extract')
    expect(sceneFor(look('lipsa'))).toBe('ghost')
    expect(sceneFor(look('coroana'))).toBe('gold')
    expect(sceneFor(look('lipsa', { role: 'corp', material: 'zr' }))).toBe('gold')
    expect(sceneFor(look('ok'))).toBe('alive')
    expect(sceneFor(look('carie'))).toBe('alive')
  })

  it('откуда возвращается: лунка, имплант, призрак или ниоткуда', () => {
    expect(comesFrom(look('extras'))).toBe('gone')
    expect(comesFrom(look('implant'))).toBe('implant')
    expect(comesFrom(look('lipsa'))).toBe('ghost')
    expect(comesFrom(look('coroana'))).toBeNull()
    expect(comesFrom(look('ok'))).toBeNull()
  })

  it('старт возврата: на пустое место отсутствующего — проявляется на месте, иначе поднимается снизу', () => {
    expect(startLift('ghost')).toBe(0)
    expect(startLift('gone')).toBe(-4)
    expect(startLift('implant')).toBe(-4)
    expect(startLift(null)).toBe(-4)
  })
})
