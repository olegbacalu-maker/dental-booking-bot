/* Поведение СЕРВЕРНОГО каркаса (`core/layout._shell`): сайдбар, шапка, плашка
   ответа. Раньше жило строками в Python (REFRESH_JS и скрипт внутри _shell) —
   вынесено 08-04 тем же движением, что и оформление.

   ⭐ С 13.10 экраны программы рисует только React, и этот файл им не нужен:
   `react_shell` его не подключает. Каркас остался у страниц ЗАМОРОЖЕННОГО бота
   (Setări › Telegram, «QR pacienți» без бота) — их не трогаем, пока бот
   заморожен (Олег 13.10). Куски старого журнала (живой опрос #live,
   перенос перетаскиванием, линия «сейчас», подсветка приехавших, счётчики
   плиток, прокрутка повестки) сняты вместе с ним (шаг 6 снятия старого
   интерфейса, docs/dentpilot-2/legacy-removal.md).

   ⚠️ Здесь только код БЕЗ данных из Python. */

/* Ctrl+K — в поиск пациента шапки каркаса. (У React своя накладка быстрого
   поиска, `QuickFind`; этот файл React-страница не грузит.) */
document.addEventListener('keydown', function (e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    var q = document.getElementById('topq');
    if (q) q.focus();
  }
});

/* Часы в подвале сайдбара. ⚠️ Идут ПО ТАЙМЕРУ, а не пишутся один раз при
   загрузке: страница себя не перезагружает, и разовая надпись весь день
   показывала бы время ОТКРЫТИЯ страницы. Ошибка ничем себя не выдаёт — цифры
   правдоподобные, формат верный, час чужой.
   ⚠️ Пояс берётся из разметки (data-tz), а не у устройства: в облаке через
   туннель браузер стоит в своём поясе, а весь остальной экран размечен
   часами клиники (eng.TZ). */
(function () {
  var sfc = document.getElementById('sf_clock');
  if (!sfc) return;
  var tz = sfc.getAttribute('data-tz') || '';
  function tick() {
    var t = new Date();
    var txt;
    try {
      txt = t.toLocaleTimeString('ro-RO',
        { timeZone: tz, hour: '2-digit', minute: '2-digit' });
    } catch (e) {   /* пояс не знаком движку — часы устройства лучше пустоты */
      txt = ('0' + t.getHours()).slice(-2) + ':' +
            ('0' + t.getMinutes()).slice(-2);
    }
    sfc.textContent = txt;
  }
  tick();
  setInterval(tick, 20000);
})();

/* POST со страницы каркаса — 303 на ТУ ЖЕ страницу: браузер открывает её
   заново, и прокрутка встаёт в ноль. Формы стоят и внизу длинных страниц (запись,
   платежи, документы), поэтому каждое действие отбрасывало журнал в начало —
   место приходилось искать глазами (жалоба Олега 08-12 про статусы; жалоба
   клиники 08-14 про запись: «сказали ок, а что случилось — не поняли»).
   Запоминаем положение перед отправкой и возвращаем, вернувшись НА ТОТ ЖЕ
   путь. Ответ (?msg=…) с 08-14 ПЛАВАЕТ поверх окна (toastbox), поэтому
   восстановленная прокрутка его больше не прячет — прежнее исключение
   «с msg не возвращаем» снято вместе с причиной.
   ⚠️ Только POST: GET-формы (поиск) уводят на другую страницу со своим верхом.
   Редирект на ДРУГОЙ путь прокрутку не получает — пути не совпадут. */
(function () {
  var KEY = 'dp_pos';
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || !f.getAttribute) return;
    /* атрибуты, а не свойства: поле формы с name="action" подменяет f.action */
    var act = f.getAttribute('action') || location.pathname;
    var method = (f.getAttribute('method') || 'get').toLowerCase();
    if (method !== 'post' || act.indexOf('/admin/') !== 0) return;
    try {
      sessionStorage.setItem(KEY, location.pathname + '|' + (window.pageYOffset | 0)
        + '|' + Date.now());
    } catch (err) { /* приватный режим */ }
  }, true);
  var saved = null;
  try {
    saved = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
  } catch (err) { saved = null; }
  if (!saved) return;
  var parts = saved.split('|');
  var y = parseInt(parts[1], 10);
  if (parts[0] !== location.pathname || !y) return;
  /* метка живёт полминуты: POST, отвечающий ФАЙЛОМ (выгрузка, бэкап), не ведёт
     к перезагрузке, и без срока годности его позиция всплыла бы при следующем
     заходе на ту же страницу совсем по другому поводу */
  if (Date.now() - (parseInt(parts[2], 10) || 0) > 30000) return;
  window.scrollTo(0, y);
  /* второй заход после полной загрузки: страница к этому моменту ещё растёт
     (шрифт, картинки), и первый scrollTo упирается в тогдашний
     предел прокрутки. Свою прокрутку человека не трогаем — если он успел
     покрутить сам, метка снята. */
  var mine = true;
  var drop = function () { mine = false; };
  window.addEventListener('wheel', drop);
  window.addEventListener('touchmove', drop);
  window.addEventListener('keydown', drop);
  window.addEventListener('load', function () {
    if (mine && Math.abs((window.pageYOffset | 0) - y) > 2) window.scrollTo(0, y);
  });
})();

/* Плавающий ответ на действие (?msg=… из редиректа, layout.msg_banner).
   Здесь три обязанности: крестик; автозакрытие УСПЕХА через 6 секунд (ошибки
   и предупреждения висят, пока их не закроют — их читают, а «Programare
   adăugată» достаточно увидеть краем глаза); и чистка адреса — replaceState
   убирает msg, чтобы F5 и кнопка «назад» не показывали
   тот же ответ заново как свежий. */
(function () {
  var box = document.getElementById('dp_toast');
  if (!box) return;
  try {
    if (/[?&]msg=/.test(location.search)) {
      var q = location.search.replace(/([?&])msg=[^&]*&?/, '$1').replace(/[?&]$/, '');
      history.replaceState(null, '', location.pathname + q + location.hash);
    }
  } catch (e) { /* старый WebView — ответ покажется при F5 ещё раз, не страшно */ }
  var hide = function () {
    box.classList.add('out');
    setTimeout(function () {
      if (box.parentNode) box.parentNode.removeChild(box);
    }, 240);
  };
  var x = box.querySelector('.t-x');
  if (x) x.addEventListener('click', hide);
  if (box.getAttribute('data-kind') === 'ok') setTimeout(hide, 6000);
})();
