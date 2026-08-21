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

/* «Fără telefon» — галочка ПРОИЗВОДНАЯ от пустого поля телефона: своей
   колонки у неё нет (одно состояние — одно имя), она говорит серверу, что
   пустота — намерение, а не забытое поле. Поле чистится и ВЫКЛЮЧАЕТСЯ:
   выключенный input в POST не едет, и сервер видит ровно «не сообщали».
   data-for — имя поля (aphone в журнале, phone в фише), data-req="1" — форме,
   где телефон без галочки обязателен (журнал). Работает и в подменяемом куске:
   вызов идёт из onchange самой разметки, замыканий на узлы нет. */
function togglePhone(cb) {
  var inp = cb.form && cb.form.querySelector(
    'input[name=' + (cb.getAttribute('data-for') || 'phone') + ']');
  if (!inp) return;
  inp.disabled = cb.checked;
  if (cb.checked) inp.value = '';
  inp.required = !cb.checked && cb.getAttribute('data-req') === '1';
}

/* имя выбранного файла рядом с кнопкой: штатный <input type=file> его прячет */
function pickName(inp) {
  var out = document.getElementById(inp.id + '_n');
  if (!out) return;
  var f = inp.files && inp.files[0];
  out.textContent = f ? f.name : 'niciun fișier ales';
  out.classList.toggle('on', !!f);
}

/* Часы в подвале сайдбара. ⚠️ Идут ПО ТАЙМЕРУ, а не пишутся один раз при
   загрузке: страницы себя больше не перезагружают вовсе (живой журнал —
   опрос #live, остальные статичны), и разовая надпись весь день показывала
   бы время ОТКРЫТИЯ страницы. Ошибка ничем себя не выдаёт — цифры
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

/* Живой журнал: ОПРОС вместо перезагрузки (08-20, жалоба пилота «обновление
   каждые 12 сек, видно [мигание]»). До этого страница честно перезагружалась,
   и вокруг reload выросла грядка защит — диалог, перетаскивание, плашка,
   ввод, файл, прокрутка агенды через sessionStorage: чинилось по симптому,
   болел сам подход. Теперь сервер оборачивает живой кусок в <div id="live"
   data-hash=отпечаток> (layout._shell), а мы раз в data-reload секунд
   спрашиваем ТОТ ЖЕ адрес с заголовком X-DP-Live и своим отпечатком.
   204 — день не менялся, DOM не трогается ВООБЩЕ: hover, выделение, прокрутка
   живы, экран неподвижен. 200 — день изменился: подменяем содержимое обёртки
   и доделываем то, что при загрузке делали скрипты страницы.

   ⚠️ Оставшиеся защиты — не про мигание, а про «не выдёргивать из-под рук»:
   открытый диалог (модалки живут В куске), перетаскивание, ввод в поле куска.
   ⚠️ Перед подменой снимается .anim: входные анимации — про приход человека,
   а не про каждую приехавшую бронь (иначе весь экран пульсировал бы).
   ⚠️ Плашка ответа (dp_toast) переносится в новый кусок УЗЛОМ, с живыми
   обработчиками: она отвечает на действие человека, и опрос не вправе её
   отнять. position:fixed — место в DOM ей безразлично.
   ⚠️ innerHTML скрипты не исполняет; заново исполняются только помеченные
   <script data-live> (данные модалок: CARDS, NOTE_ENDS) — они объявляют var,
   не const, иначе повторное объявление упало бы SyntaxError.
   ⚠️ X-DP-V — версия программы: после тихого обновления не вклеиваем новую
   разметку в старый каркас со старым CSS, а перезагружаемся целиком. */
(function () {
  var iv = parseInt(document.body.getAttribute('data-reload') || '', 10);
  var live = document.getElementById('live');
  if (!iv || !live) return;
  var hash = live.getAttribute('data-hash') || '';

  /* «занят» спрашивается ДВАЖДЫ — перед запросом и перед подменой: ответ
     летит миллисекунды, но диалог, перетаскивание или ввод могли начаться
     ровно в эту щель. Отказ в apply ничего не теряет: hash остаётся прежним,
     и следующий тик привезёт то же изменение заново. */
  function busy() {
    if (document.querySelector('dialog[open]')) return true;
    if (document.documentElement.classList.contains('dragging')) return true;
    var a = document.activeElement;
    return !!(a && a.closest && a.closest('#live') &&
              (a.tagName === 'INPUT' || a.tagName === 'SELECT' ||
               a.tagName === 'TEXTAREA'));
  }

  function apply(html, tag) {
    if (busy()) return;
    hash = tag;
    document.documentElement.classList.remove('anim');
    var toast = document.getElementById('dp_toast');
    var ag = live.querySelector('.ag-l');
    var agTop = ag ? ag.scrollTop : 0;
    live.innerHTML = html;
    if (toast) live.appendChild(toast);
    var scr = live.querySelectorAll('script[data-live]');
    for (var i = 0; i < scr.length; i++) {
      var el = document.createElement('script');
      el.textContent = scr[i].textContent;
      scr[i].parentNode.replaceChild(el, scr[i]);
    }
    ag = live.querySelector('.ag-l');
    if (ag) ag.scrollTop = agTop;               // прокрутку агенды не отнимать
    if (window.fitGrid) fitGrid();              // канва: высота часа и ступени
    placeNowline();
    markFresh();
    paintWaits();                               // минуты ожидания в агенде
  }

  function tick() {
    if (document.hidden || busy()) return;      // вкладку не видно / заняты руки
    fetch(location.pathname + location.search,
          {headers: {'X-DP-Live': '1', 'X-DP-Hash': hash}, cache: 'no-store'})
      .then(function (r) {
        if (r.status !== 200) return;           // 204: день не менялся
        var v = r.headers.get('X-DP-V') || '';
        var mine = document.body.getAttribute('data-v') || v;
        if (v && v !== mine) { location.reload(); return; }
        var tag = r.headers.get('X-DP-Hash') || '';
        r.text().then(function (t) { apply(t, tag); });
      })
      .catch(function () { /* сервер перезапускается — следующий тик спросит */ });
  }
  setInterval(tick, iv * 1000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) tick();               // вернулись к вкладке — сразу
  });
})();

/* Прокрутка списка «Agenda zilei» переживает ПОВТОР той же страницы (08-17).

   Список выше окна с первого же загруженного дня: у клиники их два десятка, а
   окно списка 320px. Единственная оставшаяся перезагрузка «сам в себя» —
   303-повтор после POST (смена статуса, dp_auto): опрос живого журнала с 08-20
   страницу не перезагружает, его прокрутку возвращает сама подмена (apply).

   ВАЖНО: восстанавливаем ТОЛЬКО повтор, а не приход человека на страницу, —
   иначе журнал открывался бы с середины списка, и это выглядело бы поломкой.
   Отличаем по классу `anim`: скрипт в шапке выдаёт его, когда загрузка НЕ
   автоматическая (см. layout — там же снимается dp_auto). Второго флага не
   заводим намеренно: одно состояние — одно имя.

   Ключ несёт ДЕНЬ (data-day у сетки): пролистав понедельник и уйдя во вторник,
   человек ждёт вторник с начала, а не чужую позицию.
   ⚠️ Сохранение — делегатом на document (scroll не всплывает, ловим на
   погружении): сам .ag-l живёт в подменяемом куске, и слушатель на элементе
   умирал бы с первой же приехавшей бронью — позиция замирала бы молча. */
(function () {
  var key = function () {
    var grid = document.querySelector('.gridbody');
    return 'dp_ag_' + ((grid && grid.getAttribute('data-day')) || 'x');
  };
  var list = document.querySelector('.ag-l');
  if (list && !document.documentElement.classList.contains('anim')) {
    try {
      var was = parseInt(sessionStorage.getItem(key()) || '', 10);
      if (was > 0) list.scrollTop = was;
    } catch (e) { /* приватный режим */ }
  }
  document.addEventListener('scroll', function (ev) {
    var t = ev.target;
    if (!t || !t.classList || !t.classList.contains('ag-l')) return;
    try { sessionStorage.setItem(key(), String(t.scrollTop)); } catch (e) {}
  }, true);
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
    /* не замыкание dlg: после подмены живого куска тот узел уже вне DOM,
       и showModal() на нём падает — а бросок обязан работать и после того,
       как опрос привёз новую сетку */
    document.getElementById('movedlg').showModal();
  });
})();

/* POST из журнала — 303 на ТУ ЖЕ страницу: браузер открывает её заново, и
   прокрутка встаёт в ноль. Формы стоят и внизу длинных страниц (запись,
   платежи, документы), поэтому каждое действие отбрасывало журнал в начало —
   место приходилось искать глазами (жалоба Олега 08-12 про статусы; жалоба
   клиники 08-14 про запись: «сказали ок, а что случилось — не поняли»).
   Запоминаем положение перед отправкой и возвращаем, вернувшись НА ТОТ ЖЕ
   путь. Ответ (?msg=…) с 08-14 ПЛАВАЕТ поверх окна (toastbox), поэтому
   восстановленная прокрутка его больше не прячет — прежнее исключение
   «с msg не возвращаем» снято вместе с причиной.
   ⚠️ Только POST: GET-формы (поиск) уводят на другую страницу со своим верхом.
   Редирект на ДРУГОЙ путь (новая фиша) прокрутку не получает — пути не
   совпадут. dp_auto остаётся только у смены статуса: там страница повторяет
   саму себя; у записи же новая строка обязана подсветиться как приехавшая. */
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
      /* та же метка, что у автообновления: это не приход человека на страницу,
         а её же повтор — заново играть появление блоков незачем */
      if (/^\/admin\/status\//.test(act)) sessionStorage.setItem('dp_auto', '1');
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
   Это ровно то событие, ради которого журнал висит открытым на стойке: бронь
   не имеет права просто появиться между двумя кадрами незамеченной.
   Сравниваем по id с тем, что было видно в прошлый раз; набор помним ПО ДНЮ,
   иначе переход на завтра красит весь день как новый. Зовётся при загрузке и
   после каждой подмены живого куска (apply) — sessionStorage, а не переменная,
   потому что 303-повтор после смены статуса переживает только он. */
function markFresh() {
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
}
markFresh();

/* Линия «сейчас» на канве дня. Рисуется ЗДЕСЬ, а не сервером (08-20): она —
   единственное, что меняется НЕПРЕРЫВНО, и серверный top из минут делал бы
   отпечаток живого куска всегда другим — опрос подменял бы DOM каждые 12 с,
   мигание вернулось бы через чёрный ход (см. schedule/routes._live_fragment).
   Часы и минуты — В ПОЯСЕ КЛИНИКИ (data-tz у часов сайдбара, тот же приём):
   в облаке через туннель браузер живёт в своём поясе, и линия по часам
   устройства стояла бы на чужом часе. Не на сегодняшнем дне линии нет.
   Координаты — те же, что были у сервера: номер строки часа + доля минут,
   умноженные на живую высоту ячейки (--cell её ставит fitGrid, поэтому и
   пересчёт на resize — ПОСЛЕ fitGrid: его слушатель зарегистрирован раньше). */
function placeNowline() {
  var old = document.querySelector('.nowline');
  if (old) old.parentNode.removeChild(old);
  var gb = document.querySelector('.gridbody[data-day]');
  if (!gb) return;
  var tc = gb.querySelector('.gcol-time');
  if (!tc || !tc.children.length) return;
  var sfc = document.getElementById('sf_clock');
  var tz = (sfc && sfc.getAttribute('data-tz')) || '';
  var d = new Date(), day, hh, mm;
  try {
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz || undefined, hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit'
    }).formatToParts(d);
    var m = {};
    for (var i = 0; i < parts.length; i++) m[parts[i].type] = parts[i].value;
    day = m.year + '-' + m.month + '-' + m.day;
    hh = parseInt(m.hour, 10); mm = parseInt(m.minute, 10);
  } catch (e) {   /* пояс не знаком движку — часы устройства лучше пустоты */
    day = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
          ('0' + d.getDate()).slice(-2);
    hh = d.getHours(); mm = d.getMinutes();
  }
  if (gb.getAttribute('data-day') !== day) return;
  var row = -1;
  for (var k = 0; k < tc.children.length; k++) {
    if (parseInt(tc.children[k].textContent, 10) === hh) { row = k; break; }
  }
  if (row < 0) return;                          // час вне сетки дня
  var cell = parseFloat(getComputedStyle(gb).getPropertyValue('--cell')) || 66;
  var el = document.createElement('div');
  el.className = 'nowline';
  el.style.top = ((row + mm / 60) * cell) + 'px';
  gb.appendChild(el);
}
placeNowline();
setInterval(placeNowline, 30000);
window.addEventListener('resize', placeNowline);

/* «așteaptă N min» у пациента в приёмной (агенда, статус waiting). Минуты
   пишутся ЗДЕСЬ, а не на сервере: серверная строка с минутами меняла бы
   отпечаток живого тела каждую минуту, и подмена шла бы каждый опрос —
   мигание чёрным ходом (прайор живого журнала, тот же, что у линии
   «сейчас»). Сервер даёт только data-wait-since — он детерминирован. */
function paintWaits() {
  var els = document.querySelectorAll('[data-wait-since]');
  for (var i = 0; i < els.length; i++) {
    var t = parseInt(els[i].getAttribute('data-wait-since'), 10);
    if (!t) continue;
    var m = Math.max(0, Math.floor((Date.now() - t) / 60000));
    /* первые 5 минут — тишина: «пришёл и почти сразу позвали» ожиданием не
       считается, а «așteaptă 0 min» на каждом пришедшем — шум (Олег 08-21) */
    if (m < 5) {
      els[i].textContent = '';
      els[i].classList.remove('long');
      continue;
    }
    els[i].textContent = 'așteaptă ' + m + ' min';
    els[i].classList.toggle('long', m >= 15);
  }
}
paintWaits();
setInterval(paintWaits, 60000);

/* Плавающий ответ на действие (?msg=… из редиректа, layout.msg_banner).
   Здесь три обязанности: крестик; автозакрытие УСПЕХА через 6 секунд (ошибки
   и предупреждения висят, пока их не закроют — их читают, а «Programare
   adăugată» достаточно увидеть краем глаза); и чистка адреса — replaceState
   убирает msg, чтобы F5, автообновление (12 с) и кнопка «назад» не показывали
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
