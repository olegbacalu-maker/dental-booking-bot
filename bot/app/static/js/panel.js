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

/* Автообновление страницы — ТОЛЬКО там, где сервер его попросил: <body
   data-reload="секунды"> (layout.LIVE_RELOAD, это живое расписание). Раньше
   перезагружались ВСЕ страницы, и каждая теряла своё: раскрытые <details>
   FAQ, позицию прокрутки, предпросмотр пациента — чинилось по одному месту,
   пока не стало ясно, что болеет сама всеобщность. Даже на живой странице
   перезагрузка НЕ должна отнимать работу: открытый диалог, начатое
   редактирование, выбранный файл и любой ввод в форме её отменяют. */
(function () {
  var iv = parseInt(document.body.getAttribute('data-reload') || '', 10);
  if (!iv) return;
  setInterval(function () {
    if (document.querySelector('dialog[open]')) return;
    /* идёт перетаскивание — страница не имеет права исчезнуть из-под мыши */
    if (document.documentElement.classList.contains('dragging')) return;
    var pe = document.getElementById('pedit');
    if (pe && pe.style.display !== 'none') return;    // открыта форма профиля
    var fi = document.querySelector('input[type=file]');
    if (fi && fi.files && fi.files.length) return;    // выбран файл — не терять
    var a = document.activeElement;
    if (a && a.closest && a.closest('form')) return;  // любой ввод в форме
    if (!a || (a.tagName !== 'INPUT' && a.tagName !== 'SELECT' &&
               a.tagName !== 'TEXTAREA' && a.tagName !== 'BUTTON')) {
      /* метка для скрипта в шапке: следующая загрузка — НЕ приход человека, а
         наш собственный опрос. Иначе цифры оживали бы каждые 12 секунд. */
      try { sessionStorage.setItem('dp_auto', '1'); } catch (e) { /* приватный режим */ }
      location.reload();
    }
  }, iv * 1000);
})();

/* Перенос визита перетаскиванием (08-12, просьба Олега).

   Работает ОДИНАКОВО на канве панели дня и в таблице «Programări»: разметку
   обеим страницам печатает один `core/visits._move_attrs`, а различие форм
   (блок поверх колонки против ячейки таблицы) прячется в targetAt().

   ⚠️ Полчаса берутся из МЕСТА броска внутри ячейки, а не из её номера: сетка
   стартов 30-минутная (engine.GRID_STEP), и «09:30 → 10:00» обязано отличаться
   от «09:30 → 10:30». Верх ячейки — :00, низ — :30.
   ⚠️ Проверка занятости здесь — ТОЛЬКО подсказка. Правду говорит сервер под
   _BOOK_LOCK: страница живёт с автообновлением 12 с, и за это время бронь мог
   поставить бот или вторая регистратура.
   ⛔ Никакого «перенеслось молча»: визит — это человек, которому уже назвали
   время, а мышь соскакивает. Между броском и запросом стоит диалог. */
(function () {
  var dlg = document.getElementById('movedlg');
  if (!dlg) return;                       // страница без дневного вида
  var drag = null, hover = null;

  var DOC = {};                           // ключ врача → имя, из ссылок шапки
  var links = document.querySelectorAll('a[href]');
  for (var i = 0; i < links.length; i++) {
    var m = links[i].getAttribute('href').match(/\/admin\/doctor\/([^?#/]+)/);
    if (m) DOC[decodeURIComponent(m[1])] = links[i].textContent.trim();
  }

  function hhmm(min) {
    return ('0' + Math.floor(min / 60)).slice(-2) + ':' + ('0' + (min % 60)).slice(-2);
  }

  function clearHover() {
    if (hover) hover.classList.remove('dropzone');
    hover = null;
  }

  function slot(cell, y, rect, col) {
    var h = parseInt(cell.getAttribute('data-h'), 10);
    var half = (y - rect.top) >= rect.height / 2 ? 30 : 0;
    return {dk: cell.getAttribute('data-dk') || (col && col.getAttribute('data-dk')),
            min: h * 60 + half, cell: cell};
  }

  function targetAt(e) {
    if (!e.target || !e.target.closest) return null;
    var td = e.target.closest('td[data-h]');           // таблица «Programări»
    if (td) return slot(td, e.clientY, td.getBoundingClientRect());
    var col = e.target.closest('.gcol[data-dk]');      // канва панели дня
    if (!col) return null;
    /* ячейку ищем ПО КООРДИНАТЕ, а не по e.target: блоки визитов лежат ПОВЕРХ
       ячеек, и бросок на соседний визит обязан попадать в его час, а не в никуда */
    var cells = col.querySelectorAll('.gcell[data-h]');
    for (var k = 0; k < cells.length; k++) {
      var r = cells[k].getBoundingClientRect();
      if (e.clientY >= r.top && e.clientY < r.bottom)
        return slot(cells[k], e.clientY, r, col);
    }
    return null;                                       // закрытый час: не мишень
  }

  /* Занят ли интервал у ЭТОГО врача — теми же статусами, что считает
     db._conflicts (data-busy ставит _move_attrs). Возвращает минуту помехи. */
  function clash(dk, min, dur, id) {
    var els = document.querySelectorAll('[data-busy]');
    for (var k = 0; k < els.length; k++) {
      if (els[k].getAttribute('data-dk') !== dk) continue;
      if (els[k].getAttribute('data-appt') === id) continue;
      var s = parseInt(els[k].getAttribute('data-min'), 10);
      var e2 = s + (parseInt(els[k].getAttribute('data-dur'), 10) || 60);
      if (s < min + dur && min < e2) return s;
    }
    return -1;
  }

  document.addEventListener('dragstart', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-mv]') : null;
    if (!el) return;
    drag = {el: el, id: el.getAttribute('data-appt'),
            dk: el.getAttribute('data-dk'),
            min: parseInt(el.getAttribute('data-min'), 10),
            dur: parseInt(el.getAttribute('data-dur'), 10) || 60,
            nm: el.getAttribute('data-nm') || ''};
    el.classList.add('dragging');
    /* метка для автообновления: перезагрузка посреди перетаскивания уронила бы
       блок в никуда — страница исчезает из-под мыши */
    document.documentElement.classList.add('dragging');
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', drag.id); } catch (err) { /* IE-наследие */ }
    }
  });

  document.addEventListener('dragend', function () {
    if (drag) drag.el.classList.remove('dragging');
    document.documentElement.classList.remove('dragging');
    clearHover();
    drag = null;
  });

  document.addEventListener('dragover', function (e) {
    if (!drag) return;
    var t = targetAt(e);
    if (!t || !t.dk) { clearHover(); return; }
    e.preventDefault();                    // без этого браузер не даст бросить
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    if (t.cell !== hover) {
      clearHover();
      hover = t.cell;
      hover.classList.add('dropzone');
    }
  });

  document.addEventListener('drop', function (e) {
    if (!drag) return;
    var t = targetAt(e);
    if (!t || !t.dk) return;
    e.preventDefault();
    var d = drag;                          // dragend обнулит drag сразу после
    clearHover();
    if (t.dk === d.dk && t.min === d.min) return;   // бросок на своё место
    var busy = clash(t.dk, t.min, d.dur, d.id);
    document.getElementById('mv_nm').textContent = d.nm;
    document.getElementById('mv_from').textContent =
      (DOC[d.dk] || '—') + ' · ' + hhmm(d.min);
    document.getElementById('mv_to').textContent =
      (DOC[t.dk] || '—') + ' · ' + hhmm(t.min);
    document.getElementById('mv_time').value = hhmm(t.min);
    document.getElementById('mv_doc').value = t.dk;
    document.getElementById('mv_form').action = '/admin/move/' + d.id;
    var warn = document.getElementById('mv_warn'), yes = document.getElementById('mv_yes');
    if (busy >= 0) {
      warn.textContent = 'Medicul are deja o programare la ' + hhmm(busy) + '.';
      warn.style.display = '';
      yes.disabled = true;
    } else {
      warn.style.display = 'none';
      yes.disabled = false;
    }
    dlg.showModal();
  });
})();

/* Смена статуса — POST и 303 на ТУ ЖЕ страницу: браузер открывает её заново, и
   прокрутка встаёт в ноль. У регистратуры список дня длиннее экрана, поэтому
   каждое нажатие «Finalizat» на нижней строке отбрасывало журнал в начало —
   и место приходилось искать глазами (жалоба Олега 08-12). Запоминаем
   положение перед отправкой и возвращаем, вернувшись НА ТОТ ЖЕ путь.
   ⚠️ Не возвращаем, если в адресе есть msg: сообщение («intervalul e ocupat»)
   висит баннером НАВЕРХУ, и восстановленная прокрутка спрятала бы ровно тот
   ответ, ради которого стоило смотреть. */
(function () {
  var KEY = 'dp_pos';
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || !f.action || !/\/admin\/status\//.test(String(f.action))) return;
    try {
      sessionStorage.setItem(KEY, location.pathname + '|' + (window.pageYOffset | 0));
      /* та же метка, что у автообновления: это не приход человека на страницу,
         а её же повтор — заново играть появление блоков незачем */
      sessionStorage.setItem('dp_auto', '1');
    } catch (err) { /* приватный режим */ }
  }, true);
  var saved = null;
  try {
    saved = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
  } catch (err) { saved = null; }
  if (!saved || /[?&]msg=/.test(location.search)) return;
  var parts = saved.split('|');
  var y = parseInt(parts[1], 10);
  if (parts[0] !== location.pathname || !y) return;
  window.scrollTo(0, y);
  /* второй заход после полной загрузки: страница к этому моменту ещё растёт
     (шрифт, вписывание блоков канвы), и первый scrollTo упирается в тогдашний
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
