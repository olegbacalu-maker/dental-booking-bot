/**
 * Точка входа ТОЛЬКО этой страницы прототипа.
 *
 * ⛔ Никакого отношения к src/main.tsx: у сборки клиента вход один —
 * `src/main.tsx` (vite.config.ts, rollupOptions.input), поэтому ни три.js, ни
 * этот файл в bundle.js клиники не попадают. Страница живёт лишь в
 * `npm run dev` по адресу /prototypes/dental3d/index.html.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Dental3DPrototype } from './Dental3DPrototype'

const host = document.getElementById('dental3d-root')
if (!host) throw new Error('Dental3D: узел #dental3d-root не найден')

createRoot(host).render(
  <StrictMode>
    <Dental3DPrototype />
  </StrictMode>,
)
