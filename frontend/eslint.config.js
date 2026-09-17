// Lint клиента — минимальный набор и ни одного правила «на вырост» (§4, §23):
// рекомендованные правила JS и TypeScript плюс правила хуков React. Последние
// ловят то, чего не видит tsc: хук под условием, забытая зависимость эффекта —
// оба дают экран, который «иногда» не обновляется, и тест это не поймает.
import js from '@eslint/js'
import { defineConfig } from 'eslint/config'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default defineConfig([
  { ignores: ['node_modules/**'] },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [reactHooks.configs.flat.recommended],
  },
])
