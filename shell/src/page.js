// Вставляется оболочкой в КАЖДЫЙ документ WebView программы до его скриптов
// (контракт § 3). Даёт странице программы `window.dpShell` — и ничего больше:
// меню, клавиши и команды строит сама программа (React), пока он есть.
// ⛔ Только адрес движка: свои страницы оболочки (заставка) и чужие адреса
// его не получают. Порт проверяет оболочка (переход на чужой 127.0.0.1 она не
// пускает, а сообщение — по адресу документа, приславшего его).
(function () {
  if (location.protocol !== 'http:' || location.hostname !== '127.0.0.1') return;
  var wv = window.chrome && window.chrome.webview;
  if (!wv || window.dpShell) return;
  var post = wv.postMessage.bind(wv);
  var api = Object.freeze({
    v: 1,
    version: '__DP_SHELL_VERSION__',
    // команда оболочке: 'win/zoomin', 'win/fullscreen', 'ctx', …
    // ⭐ сообщением, без перехода: `beforeunload` страницы спит. Форма — запрос
    // IPC Tauri с чужим ключом: Tauri его молча отбрасывает (webview.rs).
    send: function (path) {
      post(JSON.stringify({ cmd: 'dpShell', callback: 0, error: 0, payload: { path: String(path) },
                            __TAURI_INVOKE_KEY__: 'dpShell' }));
    }
  });
  Object.defineProperty(window, 'dpShell', { value: api, writable: false, configurable: false, enumerable: true });
})();
