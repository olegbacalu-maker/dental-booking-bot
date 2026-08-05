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
    location.reload();
  }
}, 12000);
