/* Поведение, общее для всех экранов журнала. Раньше жило строками в Python
   (REFRESH_JS и скрипт внутри _shell) — вынесено 08-04 тем же движением, что и
   оформление: правка интерфейса не должна требовать правки Python.

   ⚠️ Здесь только код БЕЗ данных из Python. Всё, что зависит от страницы
   (списки часов, карточки визитов, ключи врачей), по-прежнему печатается в
   саму страницу — иначе пришлось бы не переносить, а переписывать. */

/* Ctrl+K — в поиск пациента, откуда бы ни смотрели */
document.addEventListener('keydown', function (e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    var q = document.getElementById('topq');
    if (q) q.focus();
  }
});

/* имя выбранного файла рядом с кнопкой: штатный <input type=file> его прячет */
function pickName(inp) {
  var out = document.getElementById(inp.id + '_n');
  if (!out) return;
  var f = inp.files && inp.files[0];
  out.textContent = f ? f.name : 'niciun fișier ales';
  out.classList.toggle('on', !!f);
}

/* часы в подвале сайдбара */
(function () {
  var sfc = document.getElementById('sf_clock');
  if (sfc) {
    var t = new Date();
    sfc.textContent = ('0' + t.getHours()).slice(-2) + ':' +
                      ('0' + t.getMinutes()).slice(-2);
  }
})();

/* Автообновление страницы. Журнал должен показывать сегодняшний день, а не
   тот, что открыли утром — но перезагрузка НЕ должна отнимать работу:
   открытый диалог, начатое редактирование, выбранный файл и любой ввод в
   форме её отменяют. */
setInterval(function () {
  if (document.querySelector('dialog[open]')) return;
  var pe = document.getElementById('pedit');
  if (pe && pe.style.display !== 'none') return;      // открыта форма профиля
  var fi = document.querySelector('input[type=file]');
  if (fi && fi.files && fi.files.length) return;      // выбран файл — не терять
  var a = document.activeElement;
  if (a && a.closest && a.closest('form')) return;    // любой ввод в форме
  if (!a || (a.tagName !== 'INPUT' && a.tagName !== 'SELECT' &&
             a.tagName !== 'TEXTAREA' && a.tagName !== 'BUTTON')) {
    /* метка для скрипта в шапке: следующая загрузка — НЕ приход человека, а
       наш собственный опрос. Иначе цифры оживали бы каждые 12 секунд. */
    try { sessionStorage.setItem('dp_auto', '1'); } catch (e) { /* приватный режим */ }
    location.reload();
  }
}, 12000);

/* KPI: цифра не появляется готовой, а вырастает от нуля.
   Оформление уже держит её невидимой первые 0.3 с (.anim ... dp-fade), поэтому
   подмена текста на «0» не мигает; если скрипт почему-то не отработал, цифра
   просто проявится настоящей — экран не остаётся пустым. */
(function () {
  if (!document.documentElement.classList.contains('anim')) return;
  var els = document.querySelectorAll('[data-count]');
  for (var i = 0; i < els.length; i++) {
    (function (el) {
      var to = parseInt(el.getAttribute('data-count'), 10);
      if (!to || to < 2) return;               // нулю и единице расти неоткуда
      /* суффикс («%», « MDL») и разделитель тысяч едут с КАЖДЫМ кадром:
         счётчик пишет textContent целиком, и без них последний кадр показывал
         «2550» вместо «2 550 MDL» — скрин Олега 08-07 */
      var suf = el.getAttribute('data-suffix') || '';
      var fmt = function (n) {
        return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
      };
      var t0 = 0;
      el.textContent = '0' + suf;
      requestAnimationFrame(function step(ts) {
        if (!t0) t0 = ts;
        var p = Math.min((ts - t0) / 620, 1);
        el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - p, 3)))) + suf;
        if (p < 1) requestAnimationFrame(step);
      });
    })(els[i]);
  }
})();

/* Запись, приехавшая ПОКА СМОТРЯТ НА ЭКРАН, подсвечивается.
   Это единственная анимация, которая живёт как раз на автоперезагрузке: если
   бронь из бота просто появляется между двумя кадрами, её никто не замечает —
   а это ровно то событие, ради которого журнал висит открытым на стойке.
   Сравниваем по id с тем, что было видно в прошлый раз; набор помним ПО ДНЮ,
   иначе переход на завтра красит весь день как новый. */
(function () {
  var grid = document.querySelector('[data-day]');
  if (!grid) return;
  var key = 'dp_seen_' + grid.getAttribute('data-day');
  var now = [];
  var items = document.querySelectorAll('[data-appt]');
  for (var i = 0; i < items.length; i++) now.push(items[i].getAttribute('data-appt'));
  var seen = null;
  try { seen = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (e) { seen = null; }
  try { sessionStorage.setItem(key, JSON.stringify(now)); } catch (e) { /* приватный режим */ }
  if (!seen) return;              // первый показ дня: новым является всё — не мигаем
  for (var j = 0; j < items.length; j++) {
    if (seen.indexOf(items[j].getAttribute('data-appt')) < 0) {
      items[j].classList.add('fresh');
    }
  }
})();
