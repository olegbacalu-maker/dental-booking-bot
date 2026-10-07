/* Типы таблиц своих моделей зубов (`teeth.js` рядом пишет scripts/teeth/bake.py).
   Бандл этот модуль НЕ импортирует — он грузится по требованию (`loadTeeth.ts`);
   типы нужны тестам, которые проверяют сами таблицы. */
import type { SculptTable } from '../src/features/clinical/three/sculpt'

export declare const SCULPT: Record<string, SculptTable>
export declare const SCULPT_OF: Record<number, string>
