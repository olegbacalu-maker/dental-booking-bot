/**
 * Корень клиента. Пока это только развилка по имени экрана: настоящие экраны
 * приезжают по одному, начиная с «Setări clinică» (§32, группа 1).
 */
interface AppProps {
  screen: string
}

export function App({ screen }: AppProps) {
  return (
    <section className="dp-react-root">
      <p className="dp-react-note">
        React-клиент подключён. Экран: <code>{screen}</code>
      </p>
    </section>
  )
}
