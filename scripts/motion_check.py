# -*- coding: utf-8 -*-
"""Движение на панели дня: есть там, где задумано, и нет там, где его быть не должно (06.11.2026).

    python scripts\\motion_check.py                 шесть сценариев на дереве
    python scripts\\motion_check.py --pair          и пары: копии дерева со сломанным правилом
                                                   обязаны краснеть — каждая своим сценарием
    python scripts\\motion_check.py --styles clar,sticla,fluent,modern,elegant,calm
                                                   окно, статус, меню и ответ — в каждом стиле
    python scripts\\motion_check.py --styles clar,sticla --only tile,event
                                                   названные сценарии — в каждом стиле
    ключи: --polls N (сколько опросов ждать в покое, по умолчанию 3), --only idle,dialog

⛔ Не в CI и не в `.\\dev test`: нужны Edge и websocket-client в системном Python
(в `.venv-desktop` ничего не ставить).

Зачем. Плавность не видит ни один другой стенд: `look_sweep` гасит переходы перед
кадром, `shift_sweep` смотрит только сдвиги раскладки, vitest не считает стилей.
А ломается она молча и в обе стороны: правило появления пропало — окно снова
«хлопает»; правило без охраны — анимация играет на каждом опросе живого канала
или у того, кто попросил систему убрать движение.

Сценарии (каждый — на свежей странице главной, окно 1366×768):
  idle    покой живого канала: N опросов подряд — все 204, ни одного запуска
          анимации или перехода, ни одного изменившегося узла (кроме часов меню
          и линии «сейчас»);
  dialog  окно визита: прозрачность по кадрам растёт от нуля до единицы, переход
          длится ступень `--dur-fast`, высота окна не меняется с приходом
          карандаша, сдвигов раскладки нет, окно кликабельно сразу;
  status  смена статуса при процессоре ×4: кнопки шага выключены на время
          команды, а их вид не меняется ни на одном кадре (не мигают);
  menu    меню правой кнопки проявляется;
  toast   плавающий ответ въезжает и ПОСЛЕ снятия класса `anim` (он снимается
          первым же изменением дня и до перезагрузки документа не возвращается);
  reduce  `prefers-reduced-motion`: после окна, меню, вкладки, смены статуса и
          сворачивания меню — ни одного НОВОГО перехода или анимации с
          длительностью (список «новое» — NEW ниже; задержанная ступенька вида
          выключенной кнопки длительности не имеет и движением не считается);
          закрытое окно и ушедшая строка уходят в том же кадре, без призрака.
  Вторая волна (07.11.2026):
  leave   строка, ушедшая со вкладки потока: её призрак гаснет на прежнем
          месте, соседняя строка доезжает сдвигом (несколько промежуточных
          положений) и встаёт ровно на место раскладки без остатка transform;
  close   закрытие: окно по Esc гаснет за ступень и уходит из дерева; щелчок
          по вкладке потока во время затухания срабатывает (ввод не задержан);
          меню по Esc и плашка по крестику гаснут и уходят;
  move    блок, перенесённый с другого рабочего места, после опроса доезжает
          до нового места сдвигом и встаёт точно на него;
  stats   «Statistici» при приходе на экран (после снятия `anim` с документа):
          корень экрана несёт `anim`, графики проявляются, цифры считают;
  print   печать посреди движения (строка уходит, окно гаснет): на листе ни
          идущей анимации, ни сдвига, ни призрака, ни гаснущего окна.
  Окна, которые хозяин монтирует условно, — их `close` не видит:
  plan    план лечения в фише: окно «Adaugă din șablon» стоит на одном месте и
          одной высоты от первого кадра — пока грузятся шаблоны, при выборе зуба
          и возврате к «fără dinte», при смене шаблона в списке (в том числе на
          длинный); окна вставки, правки позиции, «Salvează ca șablon» и подписи
          гаснут за ступень по «Renunță», по Esc и после удачной записи и только
          потом уходят из дерева; окно правки не меняет высоту, когда под ценой
          появляется и уходит подсказка прайса; печать посреди такого закрытия —
          конечный вид.
  Блок визита отвечает на курсор и на событие дня:
  tile    наведение: блок поднимается на `--lift-block`, место, размер и
          ступени сжатия всех блоков те же; у нижней кромки (курсор в полоске под
          поднятым блоком, рука дрожит) блок не дёргается; оборот зубчика и блик —
          один запуск за наведение, курсор внутри блока повтора не даёт, ушёл и
          вернулся — играет снова. Щелчок посреди анимации у края блока открывает
          карточку ЭТОГО визита; окно растёт из блока, по Esc сворачивается в него,
          доигрывает переход и уходит из дерева. Перенос, начатый посреди анимации:
          в миг хвата блок стоит ровно на своём месте, под курсор отдана наклонённая
          копия, блок на старом месте бледнеет, место броска светится, бросок
          открывает окно переноса, после него пометок не остаётся;
  event   событие статуса: «a venit» — вспышка и блик по одному разу; «în cabinet»
          — три удара полоски и тишина; «finalizat» — один переворот блока, по концу
          без остатка transform, раскладка та же; опрос живого канала после событий
          не играет ничего; печать посреди переворота — конечный вид.
  agenda  вид повестки «compactă / detaliată»: переключатель стоит в шапке блока,
          и при переключении кнопка остаётся под курсором на том же месте (список
          под ней меняет высоту); щелчок блок не сворачивает; у свёрнутого блока
          переключателя нет, у открытого снова — он на месте и вид тот же.
  focus   час сетки, открывший окно записи МЫШЬЮ, после окна остаётся без рамки
          клавиатуры: окно закрыли Esc; запись короче часа внесли клавишей Enter
          (час остаётся со свободным отрезком и включённым). Открывший окно с
          клавиатуры получает фокус и рамку назад.
  Прайс и поиск услуги (20.11.2026; засев — прайс с категориями путём клиники, файл
  импорта — .csv, свой у каждого прохода):
  pimport мастер «Import pacienți» с записями: полоса шагов и карточка файла на месте на
          каждом шаге; на «Verificare» галочки визитов и выбор процедуры перепроверяют файл, а сами
          галочка, блок «Programări din fișier» и всё выше него не сдвигаются ни на одном кадре;
          импорт идёт до итога со строкой визитов; кадры шагов — в $MC_SHOTS, если он задан;
  tarife  «Servicii și tarife»: переход из меню; в любом виде меню шапка, верх таблицы,
          ширины колонок и место поля поиска одни, пункт меню под курсором; с числом
          найденного поле не сужается; плитка ↔ правка карандашом («Gata», «Renunță»): строка
          той же высоты, соседи и колонки на месте, «Gata» на месте карандаша; удалённая
          строка той же высоты, отмена — на месте корзины и в строке целиком; полоса записи проявляется с первой правкой, а
          запись у прокрученной до низа страницы ничего не сдвигает; окно категории
          одной высоты с отказом и без; окно импорта одно место и высота до файла, со
          сравнением и на каждой вкладке, нажатая вкладка соседей не толкает; оба окна
          гаснут и уходят из дерева (Esc, крестик, после записи); вопрос при уходе с
          правкой проявляется; без движения полоса и окно встают и уходят сразу; в
          «Setări › Servicii» плитка ↔ правка карандашом не меняет высоту строки.
  Premium волна 2а (27.11.2026; засев — право `sms_link` файлом лицензии, галочки ссылки и плашки в
  clinic.json, ответ пациента — строкой `appt_calls` каналом `sms`, как её пишет `schedule/plink.apply`):
  answer  ответ пациента ссылкой на главной: «Vin» приехал опросом — галочка на блоке выскакивает один
          раз (`dp-vin`), плашка въезжает (`dp-toast`), место и размер блоков те же; следующий опрос —
          204 и ни одного запуска; «Vin» гаснет сама (переход прозрачности) и уходит из дерева;
          «Nu pot veni» — плашка висит, слово на блоке, «De confirmat» — этот визит наверху и раздел
          цветом предупреждения; щелчок по плашке — окно визита проявляется, высота окна с жёлтой
          полосой не меняется по кадрам; без движения — плашка и галочка встают без анимации.
  picker  поле поиска услуги (ServicePicker) в форме плана фиши, в «Editează procedura»,
          в «Adaugă în plan · dintele 36» с одонтограммы и в строке шаблона плана:
          щелчок, ↓, набор (список меняет высоту), Esc, набор и Enter — поле и окно не
          двигаются, список стоит под полем; Esc закрывает только список. Окно правки
          проходится и в стиле Sticlă (у его окон backdrop-filter).

⚠️ Покой меряется ВНЕ границы получаса: на ней сервер законно меняет конверт (час
«сейчас», прошедшее начало записи). Перед сценарием стенд ждёт, если до границы
меньше, чем длится замер. Засев — записи не ближе двух часов от «сейчас»: у них
нет минутных порогов (опоздание 5 и 15 минут, счётчик ожидания).
⛔ Час засева — из часов КЛИНИКИ, а не от «сейчас» (07.11.2026): прежнее «час − 4»
с 22:00 ставило записи на 18 ч, щелчок по блоку прокручивал страницу на 600 px,
вкладка потока уходила под липкую шапку — и `close` краснел на любой версии; с
23:00 засев уходил за закрытие. Теперь — самое раннее окно рабочего дня клиники
(у блоков вверху сетки прокрутки почти нет); окна нет — отказ словами, не зелёный.

⛔ Зелёный стенд сам по себе ничего не доказывает — доказательство пары (`--pair`,
проверено при заведении 06.11.2026, каждая покраснела своим сценарием):
  idle    · в конверт канала дописано «сейчас» (`core/api.live_envelope`) → опросы
            отвечают 200 вместо 204;
          · в panel.css дописан бесконечный пульс цифры вкладки → запуски в покое;
  dialog  · `dialog[open]{transition:none !important}` → перехода у окна нет;
  status  · у кнопок шага снята задержка вида (`transition:none !important`) →
            вид кнопок меняется на кадрах команды;
  menu    · `.dp-cmenu{transition:none !important}` → меню встаёт сразу;
  toast   · въезд ответа возвращён под `.anim` → после первого изменения дня
            ответ стоит без движения;
  reduce  · правило появления окна дописано БЕЗ `@media (prefers-reduced-motion)`
            → переход у окна при выключенном движении;
  leave   · `.fl-list{--motion-flip:none}` → соседняя строка встаёт одним кадром;
          · `.fl-row.leaving{display:none !important}` → призрака нет;
  close   · `dialog{transition:none !important}` → окно уходит без затухания;
          · окно остаётся модальным, пока гаснет (`cancel` отменён, `close()` через
            200 мс — скриптом в странице: так ломает клиент, не CSS) → щелчок по
            вкладке ловит окно (07.11.2026; CSS-пара тут слепа — закрытое окно
            Chromium не пускает под щелчок даже с `pointer-events:auto` во весь экран);
          · `.dp-cmenu.out{opacity:1 !important}` → меню не гаснет;
          · `.toastbox.out{opacity:1 !important}` → плашка не гаснет;
  move    · `.gridbody{--motion-flip:none}` → блок встаёт одним кадром;
  stats   · `.dp-react-root.anim .spark{animation:none !important}` → графики не
            проявляются;
          · `.anim .stx-bar{animation:none !important}` → столбцы не растут;
          · `.stx-bar{animation:stx-grow-y .55s both !important}` → вход играет и
            на смене периода;
  print   · `@media print{.fl-row.leaving{display:flex !important;animation:fl-out 9s both !important}}`
            → призрак строки на листе.
  plan    · клиенту сказано «движения нет» при живом CSS (`matchMedia` о reduced-motion
            подменён в странице) → хозяин снимает окно в кадре закрытия: затухания
            нет ни у одного из окон;
          · высота окна шаблона снова по содержимому, строка предупреждения без
            места → окно меняет высоту при загрузке, выборе зуба и смене шаблона;
          · у подсказки прайса в окне правки нет своего места → окно меняет высоту
            при наборе процедуры;
          · `@media print{dialog:not([open]){display:block !important}}` → гаснущее
            окно на листе.
  tile    · подъём на `:hover` вместо пометки `data-hov` → блок дёргается у нижней
            кромки;
          · `.gappt[data-hov]{translate:none !important}` → блок не поднимается;
          · `.gridbody[data-dragging] .gappt{translate:0 -9px !important}` → в миг
            хвата блок не на своём месте;
          · `dialog[data-grow]:not([open]){transform:none !important}` → окно не
            сворачивается в блок;
          · у сворачивающегося окна оставлен один переход transform → окно уходит
            без своего перехода (ни конца прозрачности, ни конца display);
          · клиенту сказано «движения нет» при живом CSS → ни зубчика, ни блика, ни
            роста окна, ни копии под курсором;
  event   · `.gappt.moved[data-st="waiting"] .gfx{animation:none !important}` →
            вспышки нет;
          · пульс у каждого «în cabinet» без конца → ударов не три, после событий
            покоя нет;
          · у завершённого блока оставлено одно кольцо пометки → переворота нет;
          · `@media print{.gappt.moved[data-st="done"]{animation:g-flip 9s !important}}`
            → переворот на листе.
  agenda  · у кнопок вида снято место под жирную подпись → нажатая кнопка шире, и
            соседняя сдвигается из-под курсора;
          · переключатель показан и у свёрнутого блока.
  focus   · клиенту запрещено снимать фокус (`blur` ничего не делает) → час,
            открывший окно мышью, после Esc и после Enter стоит с рамкой клавиатуры.
  tarife  · у тела окна импорта высота по содержимому → окно прыгает при выборе файла;
          · у вкладок импорта снято место под жирную подпись → соседи сдвигаются;
          · поле поиска забирает свободное место ряда → ездит от вида к виду;
          · число найденного в потоке и без места → поле сужается с первой буквой;
          · полоса записи снимается без правки → запись внизу страницы сдвигает всё;
          · полоса записи без перехода → встаёт одним кадром;
          · пометка удаления строкой под именем → строка растёт, ниже всё съезжает;
          · отмена удаления шире корзины → под курсором другое место;
          · строка отказа окна категории без места → окно меняет высоту;
          · переход полосы без охраны reduced-motion → движение без движения.
  answer  · `.gappt.vin .gvin{animation:none !important}` → галочка «Vin» без движения;
          · плашка ответа без затухания (`.dp-ans-w{transition:none !important}`) → «Vin» уходит рывком.
  picker  · у подсказки прайса в окне с зуба нет места → окно растёт при выборе;
          · список услуг в потоке окна → окно растёт с открытием списка;
          · список не в верхнем слое (движок без `showPopover`) → в окне Sticlă он
            отсчитывается от окна и уезжает вниз на его высоту.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import BOT, TZ, Client, Server, new_patient  # noqa: E402
from test_plink import _license as plink_license  # noqa: E402
from test_sms import KEY_ENV  # noqa: E402
from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402

# ⛔ Свой порт отладки: 9337–9347, 9349, 9352/9353, 9355, 9360/9361 заняты
# соседними стендами, и запуск на занятом МОЛЧА подключается к чужому браузеру.
PORT = 9348
SIZE = (1366, 768)
LIVE_S = 12            # период опроса живого канала (services/live.ts › LIVE_MS)
SCENARIOS = ("idle", "dialog", "status", "menu", "toast", "reduce", "leave", "close", "move", "stats", "print", "plan",
             "tile", "event", "agenda", "focus", "tarife", "picker", "pimport", "patient", "answer")
STYLE_SCENARIOS = ("dialog", "status", "menu", "toast", "close", "reduce")

# Замеры в странице: кадры, изменения узлов, сеть, сдвиги раскладки, запуски
# анимаций и переходов. Код программы не трогается — всё вводится по CDP.
# Повестка у человека, который её не трогал, свёрнута (память блока `dp_fold:agenda`
# пуста), а сценарии жмут кнопки шага и вкладки потока внутри неё. Стенд открывает её
# так же, как открыл бы человек и как это запомнил бы компьютер, — до первого кадра.
OPEN_AGENDA = "try { localStorage.setItem('dp_fold:agenda', '1') } catch (e) {}"

INSTR = r"""(() => {
  if (window.__mc) return 1;
  const M = window.__mc = { frames: [], samples: [], muts: [], res: [], shifts: [], runs: [], ends: [], waapi: [], img: null,
    on: false, sample: null };
  const sel = (n) => {
    if (!n) return 'null';
    if (n.nodeType === 3) return '#text<' + (n.parentElement ? sel(n.parentElement) : '') + '>';
    if (n.nodeType !== 1) return n.nodeName;
    let s = n.tagName.toLowerCase();
    if (n.id) s += '#' + n.id;
    const c = (typeof n.className === 'string' ? n.className : '').trim();
    if (c) s += '.' + c.split(/\s+/).join('.');
    return s.slice(0, 80);
  };
  M.reset = () => { M.frames = []; M.samples = []; M.muts = []; M.res = []; M.shifts = []; M.runs = []; M.ends = [];
    M.waapi = []; M.on = true; };
  // Web Animations блоков визита (метка `tile`): у них нет событий запуска — считаем вызовы
  const animate = Element.prototype.animate;
  Element.prototype.animate = function (frames, opts) {
    if (M.on && opts && opts.id === 'tile') { const t = this.closest('.gappt');
      M.waapi.push({ appt: t ? t.dataset.appt || '' : '', props: Object.keys(frames[0] || {}).sort().join('+') }); }
    return animate.call(this, frames, opts);
  };
  // картинка переноса: что блок отдал браузеру под курсор
  const setImg = DataTransfer.prototype.setDragImage;
  DataTransfer.prototype.setDragImage = function (el, x, y) {
    const copy = el.querySelector('.gappt');
    M.img = { cls: el.className, x, y, w: el.offsetWidth, h: el.offsetHeight, rot: copy ? getComputedStyle(copy).rotate : '' };
    return setImg.call(this, el, x, y);
  };
  const dur = (e) => {
    try {
      const all = e.target.getAnimations({ subtree: false }).concat(
        e.pseudoElement ? document.getAnimations().filter((a) => a.effect && a.effect.target === e.target
          && a.effect.pseudoElement === e.pseudoElement) : []);
      const mine = all.filter((a) => (a.animationName || a.transitionProperty) === (e.animationName || e.propertyName));
      return mine.length ? Math.max(...mine.map((a) => Number(a.effect.getComputedTiming().duration) || 0)) : -1;
    } catch (x) { return -1; }
  };
  const run = (kind) => (e) => { if (M.on) M.runs.push({ kind, name: e.animationName || e.propertyName,
    target: sel(e.target), pseudo: e.pseudoElement || '', dur: dur(e), off: !!e.target.disabled }); };
  document.addEventListener('animationstart', run('animation'), true);
  document.addEventListener('animationiteration', run('iteration'), true);
  document.addEventListener('transitionrun', run('transition'), true);
  // доигранный переход: у узла, снятого посреди перехода, события конца нет
  document.addEventListener('transitionend', (e) => { if (M.on) M.ends.push({ name: e.propertyName,
    target: sel(e.target), pseudo: e.pseudoElement || '' }); }, true);
  const watch = () => new MutationObserver((recs) => {
    if (!M.on) return;
    for (const r of recs) {
      const now = r.type === 'attributes' ? String(r.target.getAttribute(r.attributeName)) : '';
      // перемер ступеней блоков раз в минуту переписывает класс тем же значением — не изменение
      if (r.type === 'attributes' && String(r.oldValue) === now) continue;
      M.muts.push(sel(r.target) + (r.attributeName ? ' @' + r.attributeName : ''));
    }
  }).observe(document.documentElement, { subtree: true, childList: true, attributes: true,
    characterData: true, attributeOldValue: true });
  if (document.documentElement) watch(); else document.addEventListener('readystatechange', watch, { once: true });
  const loop = () => {
    if (M.on) {
      M.frames.push(performance.now());
      if (M.sample) { try { M.samples.push(M.sample()); } catch (e) { /* узла ещё нет */ } }
    }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  new PerformanceObserver((l) => { if (!M.on) return; for (const e of l.getEntries())
    M.res.push({ name: e.name.replace(location.origin, ''), status: e.responseStatus });
  }).observe({ type: 'resource', buffered: false });
  try { new PerformanceObserver((l) => { if (!M.on) return; for (const e of l.getEntries())
    M.shifts.push(Math.round(e.value * 10000) / 10000);
  }).observe({ type: 'layout-shift', buffered: false }); } catch (e) { /* движок без layout-shift */ }
  return 1;
})()"""

# ⚠️ Блок — НЕ завершённый: сценарии статуса доводят записи до «Finalizat», а у
# закрытого визита карандаша смены процедуры нет (режим --styles ходит по кругу).
BLOCK = "document.querySelector('.gappt:not(.gnote):not(.done)')"
STEP = "document.querySelector('.ag-l .ag-i .ag-next')"
WAIT_BTN = ("Array.from(document.querySelectorAll('.ag-l .ag-i .ag-next'))"
            ".filter((b) => b.textContent.trim() === 'A venit')[{i}]")
DLG = ("() => { const d = document.querySelector('dialog[open]'); if (!d) return null;"
       " return [Number(getComputedStyle(d).opacity), d.offsetHeight, !!d.querySelector('button.dp-card-pen')]; }")

# Окна плана лечения в фише. Место и высота — раскладкой (`offset*`): прямоугольник
# экрана видит и transform перехода появления, а он раскладку не двигает.
TPL = "document.querySelector('dialog.dp-plan-tpl:not(.save)')"
BOX = ("() => {{ const d = {dlg}; return d ? [d.offsetTop, d.offsetHeight, d.open,"
       " Number(getComputedStyle(d).opacity)] : null; }}")
BY_TEXT = "Array.from(document.querySelectorAll('{sel}')).find((b) => b.textContent.includes('{text}'))"
# Шаблоны засева: с зубом и без, короткий и длиннее окна — высота окна от них не зависит.
PLAN_TPLS = [
    {"name": "Proba canal", "note": "pentru molari", "rows": [
        {"procedure": "Consultație de probă", "tooth": False, "price": 200},
        {"procedure": "Tratament de canal de probă", "tooth": True, "price": 1500},
        {"procedure": "Bont de probă", "tooth": True, "price": 3000},
        {"procedure": "Coroană de probă", "tooth": True, "price": 4500}]},
    {"name": "Proba igienă", "rows": [{"procedure": "Igienizare de probă", "tooth": False, "price": 900}]},
    {"name": "Proba lungă", "rows": [{"procedure": f"Procedură de probă {i}", "tooth": True, "price": 100 * i}
                                      for i in range(1, 15)]},
]

# Блок визита по номеру записи и раскладка всех блоков (место, размер, ступень сжатия) —
# то, что движение блока менять не вправе: высоту читает перемер ступеней.
TILE = "document.querySelector('.gappt[data-appt=\"{id}\"]')"
LAYOUT = ("JSON.stringify(Object.fromEntries(Array.from(document.querySelectorAll('.gappt')).map((a) => [a.dataset.appt,"
          " [a.className.replace(/ ?(fresh|moved|done)\\b/g, '').trim(), a.offsetTop, a.offsetLeft, a.offsetWidth,"
          " a.offsetHeight, a.scrollHeight, a.clientHeight]])))")
# Только место и размер: слово статуса на блоке законно меняет ступень сжатия.
PLACE = ("JSON.stringify(Object.fromEntries(Array.from(document.querySelectorAll('.gappt')).map((a) => [a.dataset.appt,"
         " [a.offsetTop, a.offsetLeft, a.offsetWidth, a.offsetHeight]])))")
# Подъём блока и пометка наведения по кадрам.
LIFT = ("() => {{ const t = {tile}; const v = getComputedStyle(t).translate;"
        " return [v === 'none' ? 0 : parseFloat(v.split(' ')[1] || '0'), t.hasAttribute('data-hov') ? 1 : 0]; }}")
# Окно на экране (открытое или гаснущее; окно подтверждения стоит в дереве всегда): масштаб
# по экрану, прозрачность, открыто ли, и масштаб, к которому ведёт переход transform, — он
# известен с первого кадра закрытия, а промежуточных кадров у headless-Edge на ступень один-три;
# так же — масштаб, с которого окно растёт (первый кадр его Web-анимации).
WIN = ("() => { const d = Array.from(document.querySelectorAll('dialog:not(.dp-ask)'))"
       ".find((x) => x.open || getComputedStyle(x).display !== 'none'); if (!d) return null;"
       " const cs = getComputedStyle(d); const a = (t) => (t === 'none' ? 1 : new DOMMatrix(t).a);"
       " const tr = d.getAnimations().find((x) => x.transitionProperty === 'transform');"
       " const to = tr ? tr.effect.getKeyframes().slice(-1)[0].transform : '';"
       " const up = d.getAnimations().find((x) => !x.transitionProperty && !x.animationName);"
       " const from = up ? up.effect.getKeyframes()[0].transform : '';"
       " return [Math.round(a(cs.transform) * 1000) / 1000, Number(cs.opacity), d.open ? 1 : 0,"
       " to ? Math.round(a(to) * 1000) / 1000 : null, from ? Math.round(a(from) * 1000) / 1000 : null]; }")
# Что видит обработчик блока в миг хвата: сдвиг блока от места раскладки, пометки канвы и источника.
GRAB = ("window.__ds = null; document.addEventListener('dragstart', (e) => { const t = e.target.closest('.gappt');"
        " const r = t.getBoundingClientRect(); let top = 0, n = t;"
        " while (n && !n.classList.contains('gridbody')) { top += n.offsetTop; n = n.offsetParent; }"
        " const g = document.querySelector('.gridbody');"
        " window.__ds = { dy: Math.round((r.top - (g.getBoundingClientRect().top + top)) * 100) / 100,"
        " h: Math.round(r.height * 100) / 100, lh: t.offsetHeight, dragging: g.hasAttribute('data-dragging') }; }, { once: true }); 1")

# Что считается НОВЫМ движением первой волны (сценарий reduce): цель и свойство.
# Наведение и фокус старых правил сюда не входят — их гасит прежний блок под `.anim`.
NEW = (
    ("dialog", ("opacity", "transform")),
    (".dp-cmenu", ("opacity", "transform")),
    (".fl-list", ("opacity",)), (".fl-empty", ("opacity",)),
    (".banner", ("dp-toast",)),
    (".side", ("width", "flex-basis")),
    ("", ("dp-moved", "dp-moved-g")),
    # блок визита отвечает на курсор и на событие: под «без движения» не играет ничего из этого
    ("", ("g-flash", "g-sweep", "g-beat", "g-flip", "g-droppulse", "dp-draw", "dp-pop", "dp-shake")),
    # ответ пациента ссылкой (Premium 2а): галочка на блоке
    ("", ("dp-vin",)),
    (".stat", ("background-color", "color")), (".pl-badge", ("background-color", "color")),
    (".gappt", ("background-color", "opacity", "translate", "scale", "box-shadow")),
    (".ag-i", ("border-left-color", "border-top-color", "opacity")),
    ("b", ("color",)),
)


def is_new(r: dict) -> bool:
    if r["dur"] == 0:
        return False            # ступенька без длительности — не движение
    tag, *classes = r["target"].split("#")[0].split(".")
    for who, props in NEW:
        hit = not who or (who[1:] in classes if who.startswith(".") else who == tag)
        if hit and r["name"] in props:
            return True
    return r["off"] and r["name"] == "opacity"     # затухание выключенной кнопки


class Run:
    """Одна страница главной на одном сервере; собирает утверждения."""

    def __init__(self, cdp: CDP, url: str, label: str, client: Client, day: str):
        self.cdp, self.url, self.label = cdp, url, label
        self.client, self.day = client, day
        self.page = Page(cdp, url)
        self.bad: list[str] = []
        self.n = 0
        self.pid = 0            # фиша с планом лечения (сценарий plan)
        self.listed = ""        # услуга прайса с ценой одним числом
        self.price_dir: pathlib.Path | None = None     # куда класть файл импорта (сценарий tarife)
        self.round = 0          # проход сценария tarife: имена файла и категории свои у каждого стиля
        self.data_dir: pathlib.Path | None = None      # папка данных сервера (сценарий answer пишет ответ в базу)

    def ok(self, cond: bool, text: str) -> None:
        self.n += 1
        if not cond:
            self.bad.append(text)
        print(f"  {'OK ' if cond else 'RED'} {text}")

    def js(self, expr: str):
        return self.page.js(expr)

    def home(self) -> None:
        self.cdp.cmd("Network.setCookie", name="admin_auth", value=login_cookie(self.url), url=self.url + "/")
        self.page.size(*SIZE)
        self.page.go("/admin")
        time.sleep(1.2)

    def tap(self, finder: str, wait: float, sample: str = "", button: str = "left") -> dict:
        """Настоящий щелчок по центру элемента; всё, что случилось за `wait` секунд."""
        self.js(f"(() => {{ const el = {finder}; if (el) el.scrollIntoView({{block: 'center'}}); }})()")
        time.sleep(0.3)
        x, y = self.page.center(finder)
        m = self.cdp.cmd
        m("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        time.sleep(0.35)                 # наведение доиграло свои переходы
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        m("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=1)
        m("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=1)
        self.cdp.drain(wait)
        return self.take()

    def take(self) -> dict:
        return json.loads(self.js("(() => { __mc.on = false; return JSON.stringify({samples: __mc.samples,"
                                  " muts: __mc.muts, res: __mc.res, shifts: __mc.shifts, runs: __mc.runs, ends: __mc.ends,"
                                  " waapi: __mc.waapi,"
                                  " frames: __mc.frames.length}) })()"))

    def esc(self) -> None:
        self.page.key("Escape")

    # ---------- сценарии ----------

    def idle(self, polls: int) -> None:
        span = polls * LIVE_S + 3
        now = datetime.now(TZ)
        left = (30 - now.minute % 30) * 60 - now.second
        if left < span + 5:
            print(f"  … до границы получаса {left} с — жду её: на ней сервер законно меняет конверт")
            time.sleep(left + 3)
            self.home()
        self.js("__mc.sample = null; __mc.reset(); 1")
        self.cdp.drain(span)
        d = self.take()
        live = [r["status"] for r in d["res"] if "/schedule/live" in r["name"]]
        self.ok(len(live) >= polls and all(s == 204 for s in live),
                f"покой: опросов {len(live)}, все 204 «не менялось»: {live}")
        self.ok(not d["runs"], f"покой: запусков анимаций и переходов {len(d['runs'])}"
                + (f" — {[r['name'] + ' ' + r['target'] for r in d['runs'][:4]]}" if d["runs"] else ""))
        noise = [m for m in d["muts"] if "sf_clock" not in m and "nowline" not in m]
        self.ok(not noise, f"покой: изменившихся узлов {len(noise)}" + (f" — {noise[:4]}" if noise else ""))
        waapi = self.js("document.getAnimations().filter((a) => a.playState === 'running').length")
        self.ok(waapi == 0, f"покой: идущих анимаций (и Web Animations — смыкание, переезд) {waapi}")

    def dialog(self) -> None:
        step = self.js("getComputedStyle(document.documentElement).getPropertyValue('--dur-fast').trim()")
        want = float(step.rstrip("s")) * (1 if step.endswith("ms") else 1000) if step else -1
        d = self.tap(BLOCK, 0.9, DLG)
        seen = [s for s in d["samples"] if s]
        ops = [s[0] for s in seen]
        self.ok(bool(ops) and ops[0] < 0.2 and ops[-1] == 1 and ops == sorted(ops),
                f"окно: прозрачность по кадрам растёт от нуля до единицы ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")
        mine = [r for r in d["runs"] if r["target"].startswith("dialog") and r["name"] == "opacity" and not r["pseudo"]]
        self.ok(len(mine) == 1 and abs(mine[0]["dur"] - want) < 1,
                f"окно: переход прозрачности один и длится ступень --dur-fast ({step}): {[r['dur'] for r in mine]} мс")
        back = [r for r in d["runs"] if r["target"].startswith("dialog") and r["pseudo"] == "::backdrop"]
        self.ok(bool(back), "окно: затемнение темнеет переходом вместе с окном")
        self.ok(len({s[1] for s in seen}) == 1 and any(s[2] for s in seen),
                f"окно: карандаш пришёл и высоту окна не изменил ({sorted({s[1] for s in seen})})")
        self.ok(not d["shifts"], f"окно: сдвигов раскладки после открытия нет ({d['shifts']})")
        self.ok(self.js("(() => { const d = document.querySelector('dialog[open]'); const r = d.getBoundingClientRect();"
                        " return d.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); })()"),
                "окно: под курсором — само окно, а не слой поверх (кликабельно)")
        self.esc()
        time.sleep(0.3)

    def status(self) -> None:
        look = ("() => { const bs = Array.from(document.querySelectorAll('.ag-next, .dk-btn, .dp-free-btn'));"
                " return [Math.min(...bs.map((b) => Number(getComputedStyle(b).opacity))),"
                " bs.filter((b) => b.disabled).length, bs.length]; }")
        self.cdp.cmd("Emulation.setCPUThrottlingRate", rate=4)
        time.sleep(0.3)
        try:
            before = self.js(f"({look})()[0]")
            d = self.tap(STEP, 1.8, look)
        finally:
            self.cdp.cmd("Emulation.setCPUThrottlingRate", rate=1)
        posts = [r for r in d["res"] if "/status" in r["name"]]
        self.ok(len(posts) == 1 and posts[0]["status"] == 200, f"статус: одна команда, ответ 200 ({[r['status'] for r in posts]})")
        self.ok(any(s[1] == s[2] and s[2] > 1 for s in d["samples"]),
                "статус: на время команды кнопки шага выключены все (защита от второго щелчка цела)")
        lows = sorted({s[0] for s in d["samples"]})
        self.ok(lows == [before], f"статус: вид кнопок не менялся ни на одном кадре (прозрачность {lows}, до щелчка {before})")
        time.sleep(1.6)                  # пометка сменившегося статуса доиграла

    def menu(self) -> None:
        d = self.tap(BLOCK, 0.6, "() => { const m = document.querySelector('.dp-cmenu');"
                     " return m ? Number(getComputedStyle(m).opacity) : null; }", button="right")
        ops = [s for s in d["samples"] if s is not None]
        self.ok(bool(ops) and ops[0] < 0.3 and ops[-1] == 1 and ops == sorted(ops),
                f"меню: проявляется по кадрам ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")
        self.esc()
        time.sleep(0.3)

    def toast(self) -> None:
        if self.js("document.documentElement.classList.contains('anim')"):
            self.tap(STEP, 1.8)          # первое изменение дня снимает `anim` — как у стойки
            time.sleep(1.6)
        self.ok(not self.js("document.documentElement.classList.contains('anim')"),
                "ответ: класс anim к этому времени снят (первым изменением дня)")
        self.tap(BLOCK, 0.9)
        self.js("(() => { const t = document.querySelector('dialog[open] textarea');"
                " Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, 'de sunat înapoi ' + Date.now());"
                " t.dispatchEvent(new Event('input', { bubbles: true })); return 1 })()")
        time.sleep(0.3)
        d = self.tap("Array.from(document.querySelectorAll('dialog[open] button')).find((b) => b.textContent.includes('Salvează'))",
                     1.2, "() => { const b = document.querySelector('.toastbox .banner');"
                          " return b ? [Number(getComputedStyle(b).opacity), Math.round(b.getBoundingClientRect().top)] : null; }")
        seen = [s for s in d["samples"] if s]
        self.ok(bool(seen) and seen[0][0] < 0.5 and seen[-1][0] == 1 and seen[0][1] > seen[-1][1],
                "ответ: плашка въезжает — прозрачность и место меняются по кадрам "
                + (f"({seen[0]} → {seen[-1]})" if seen else "(плашки нет)"))
        if self.js("!!document.querySelector('.toastbox .t-x')"):
            self.js("document.querySelector('.toastbox .t-x').click()")

    def reduce(self) -> None:
        if self.js("document.documentElement.classList.contains('anim')"):
            self.tap(STEP, 1.8)          # дальше — как у стойки: `anim` снят, прежний выключатель не работает
            time.sleep(1.6)
        self.cdp.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        runs: list[dict] = []
        try:
            d = self.tap(BLOCK, 0.6, DLG)
            first = next((s for s in d["samples"] if s), None)
            self.ok(first is not None and first[0] == 1, f"без движения: окно стоит целиком с первого кадра ({first})")
            runs += d["runs"]
            self.esc()
            time.sleep(0.2)
            d = self.tap(BLOCK, 0.5, "() => { const m = document.querySelector('.dp-cmenu');"
                         " return m ? Number(getComputedStyle(m).opacity) : null; }", button="right")
            first = next((s for s in d["samples"] if s is not None), None)
            self.ok(first == 1, f"без движения: меню стоит целиком с первого кадра ({first})")
            runs += d["runs"]
            self.esc()
            time.sleep(0.2)
            runs += self.tap("document.querySelectorAll('.fl-tab')[1]", 0.4)["runs"]
            runs += self.tap("document.querySelectorAll('.fl-tab')[0]", 0.4)["runs"]
            d = self.tap(STEP, 2.0, "() => Array.from(document.querySelectorAll('.moved')).filter((el) =>"
                         " / 0px 0px 0px 3px/.test(' ' + getComputedStyle(el).boxShadow)).length")
            runs += d["runs"]
            self.ok(max(d["samples"] or [0]) >= 2,
                    f"без движения: запись со сменившимся статусом помечена кольцом без анимации ({max(d['samples'] or [0])} узла)")
            if self.js("!!document.querySelector('.side .side-fold')"):
                runs += self.tap("document.querySelector('.side .side-fold')", 0.5)["runs"]
                runs += self.tap("document.querySelector('.side .side-fold')", 0.5)["runs"]
            # уход: окно по Esc — сразу из дерева; строка со вкладки — без призрака
            self.tap(BLOCK, 0.5)
            # ⚠️ окно подтверждения стоит в дереве всегда; считается закрытое и ВИДИМОЕ
            d = self.key("Escape", 27, 0.4, "() => Array.from(document.querySelectorAll('dialog:not([open])'))"
                         ".filter((x) => getComputedStyle(x).display !== 'none').length")
            runs += d["runs"]
            self.ok(not any(d["samples"]), "без движения: закрытое окно не видно ни кадра")
            self.tap(WAIT_BTN.format(i=0), 1.2)      # на свежем сервере в «A venit» никого нет
            self.tap("document.querySelectorAll('.fl-tab')[2]", 0.4)
            d = self.tap("document.querySelector('.fl-list .fl-row .dk-btn')", 1.2,
                         "() => document.querySelectorAll('.fl-row.leaving').length")
            runs += d["runs"]
            self.ok(not any(d["samples"]), "без движения: ушедшая строка без призрака")
            self.tap("document.querySelectorAll('.fl-tab')[0]", 0.3)
        finally:
            self.cdp.cmd("Emulation.setEmulatedMedia", features=[])
        new = [r for r in runs if is_new(r)]
        if os.environ.get("MC_VERBOSE"):       # что именно запускалось — глазами, при разборе
            for line in sorted({f"{r['kind']} {r['name']} {r['target'][:40]} {r['pseudo']} {r['dur']}" for r in runs}):
                print("      ·", line)
        self.ok(not new, f"без движения: новых переходов и анимаций с длительностью {len(new)} из {len(runs)} запусков"
                + (f" — {[(r['name'], r['target'][:30], r['pseudo'], r['dur']) for r in new[:4]]}" if new else ""))

    def key(self, key: str, vk: int, wait: float, sample: str = "") -> dict:
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        self.cdp.cmd("Input.dispatchKeyEvent", type="keyDown", key=key, code=key, windowsVirtualKeyCode=vk)
        self.cdp.cmd("Input.dispatchKeyEvent", type="keyUp", key=key, code=key, windowsVirtualKeyCode=vk)
        self.cdp.drain(wait)
        return self.take()

    def leave(self) -> None:
        # две записи «a venit», вкладка потока «A venit», первая уходит в кабинет
        self.tap(WAIT_BTN.format(i=0), 1.6)
        self.tap(WAIT_BTN.format(i=0), 1.6)
        time.sleep(1.6)
        self.tap("document.querySelectorAll('.fl-tab')[2]", 0.5)
        self.ok(self.js("document.querySelectorAll('.fl-list .fl-row').length") >= 2, "смыкание: на вкладке не меньше двух строк")
        second = self.js("document.querySelectorAll('.fl-list .fl-row')[1].getAttribute('data-appt')")
        smp = (f"() => {{ const g = document.querySelector('.fl-row.leaving'); const r = document.querySelector('.fl-row[data-appt=\"{second}\"]');"
               " if (!r) return null; const b = r.parentElement.getBoundingClientRect();"
               " return [g ? Number(getComputedStyle(g).opacity) : null, Math.round((r.getBoundingClientRect().top - b.top) * 10) / 10,"
               " getComputedStyle(r).transform, r.offsetTop, r.getAnimations().length]; }")
        d = self.tap("document.querySelector('.fl-list .fl-row .dk-btn')", 1.4, smp)
        seen = [s for s in d["samples"] if s]
        ghost = [s[0] for s in seen if s[0] is not None]
        self.ok(len(ghost) >= 2 and ghost[0] > 0.6 and ghost[-1] < 0.3 and ghost == sorted(ghost, reverse=True),
                f"смыкание: призрак ушедшей строки гаснет по кадрам ({ghost[:1]} … {ghost[-1:]}, кадров {len(ghost)})")
        tops = [s[1] for s in seen]
        mid = [t for t in tops if tops[0] > t > tops[-1]]
        self.ok(len(mid) >= 3 and tops[-1] < tops[0] and all(a >= b for a, b in zip(tops, tops[1:])),
                f"смыкание: соседняя строка доезжает сдвигом ({tops[0]} → {tops[-1]}, промежуточных положений {len(mid)})")
        end = seen[-1] if seen else None
        self.ok(end is not None and end[2] == "none" and abs(end[1] - end[3]) < 1,
                f"смыкание: по концу — без остатка transform, на месте раскладки ({end[2:] if end else '—'})")
        self.tap("document.querySelectorAll('.fl-tab')[0]", 0.4)

    def close(self) -> None:
        smp = ("() => { const d = document.querySelector('dialog:not(.dp-ask)'); const t = document.querySelectorAll('.fl-tab')[1];"
               " return [d ? Number(getComputedStyle(d).opacity) : null, d ? d.open : null, t.getAttribute('aria-selected')]; }")
        tab = "document.querySelectorAll('.fl-tab')[1]"
        self.tap(BLOCK, 0.9)
        # ⛔ `tap` прокрутил страницу к БЛОКУ: блок внизу сетки уводит вкладку потока под
        # липкую шапку, и сырой щелчок ниже попадает в шапку (07.11.2026: красное на любой
        # версии при засеве на 18 ч). Вкладку — в видимую область, координаты — после.
        self.js(f"{tab}.scrollIntoView({{block: 'center'}}); 1")
        time.sleep(0.2)
        x, y = self.page.center(tab)
        self.js(f"__mc.sample = {smp}; __mc.reset(); 1")
        m = self.cdp.cmd
        m("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        m("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        time.sleep(0.04)
        # Что под точкой щелчка, пока окно гаснет: вкладка — продукт ввод пропускает; окно —
        # держит (законное красное ниже); иное — стенд промахнулся, и это не про продукт.
        hit = self.js(f"(() => {{ const e = document.elementFromPoint({x}, {y}); if (!e) return 'ничего';"
                      f" return e.closest('.fl-tab') === {tab} ? 'вкладка' : e.closest('dialog') ? 'окно'"
                      " : e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className : ''); })()")
        if hit not in ("вкладка", "окно"):
            raise SystemExit(f"стенд: под точкой щелчка ({x:.0f}, {y:.0f}) не вкладка потока и не окно, а {hit}"
                             " — промах стенда, о вводе продукта он ничего не говорит")
        m("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        m("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        m("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        self.cdp.drain(0.8)
        d = self.take()
        seen = d["samples"]
        fading = [s[0] for s in seen if s[0] is not None and s[1] is False and 0 < s[0] < 1]
        # ⚠️ Промежуточных кадров мало, и это стенд, а не продукт: headless-Edge без
        # видеокарты рисует Sticlă (размытие) кадром в 50–60 мс — на 150 мс выходит
        # один-три кадра. Поэтому главное утверждение — сам переход длиной в ступень.
        step = self.js("getComputedStyle(document.documentElement).getPropertyValue('--dur-fast').trim()")
        want = float(step.rstrip("ms").rstrip("s")) * (1 if step.endswith("ms") else 1000) if step else -1
        mine = [r for r in d["runs"] if r["target"].startswith("dialog") and r["name"] == "opacity" and not r["pseudo"]]
        self.ok(len(mine) == 1 and abs(mine[0]["dur"] - want) < 1 and fading and fading == sorted(fading, reverse=True),
                f"закрытие: окно гаснет переходом в ступень ({[r['dur'] for r in mine]} мс, промежуточных кадров {len(fading)})")
        self.ok(seen and seen[-1][0] is None, "закрытие: по концу окна в дереве нет")
        self.ok(seen and seen[-1][2] == "true",
                f"закрытие: щелчок по вкладке во время затухания сработал — ввод не задержан (под точкой: {hit})")
        self.tap("document.querySelectorAll('.fl-tab')[0]", 0.3)
        # меню
        self.tap(BLOCK, 0.5, button="right")
        d = self.key("Escape", 27, 0.6, "() => { const m = document.querySelector('.dp-cmenu'); return m ? Number(getComputedStyle(m).opacity) : null; }")
        ops = [s for s in d["samples"] if s is not None and s < 1]
        self.ok(len(ops) >= 2 and ops == sorted(ops, reverse=True) and d["samples"][-1] is None,
                f"закрытие: меню гаснет по кадрам и уходит ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")
        # плашка
        self.tap(BLOCK, 0.9)
        self.js("(() => { const t = document.querySelector('dialog[open] textarea');"
                " Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, 'de sunat ' + Date.now());"
                " t.dispatchEvent(new Event('input', { bubbles: true })); return 1 })()")
        time.sleep(0.3)
        self.tap("Array.from(document.querySelectorAll('dialog[open] button')).find((b) => b.textContent.includes('Salvează'))", 1.0)
        d = self.tap("document.querySelector('.toastbox .t-x')", 0.8,
                     "() => { const b = document.querySelector('.toastbox'); return b ? Number(getComputedStyle(b).opacity) : null; }")
        ops = [s for s in d["samples"] if s is not None and s < 1]
        self.ok(len(ops) >= 2 and ops == sorted(ops, reverse=True) and d["samples"][-1] is None,
                f"закрытие: плашка гаснет по крестику и уходит ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")

    def move(self) -> None:
        # перенос с «другого рабочего места»: команда мимо этой страницы, ждём опрос
        info = self.js("(() => { const b = document.querySelector('.gappt:not(.gnote):not(.done)'); const c = b.closest('.gcol');"
                       " const h = c.querySelector('.gcell[data-h]:not([disabled])'); return JSON.stringify([b.dataset.appt, c.dataset.dk, h ? h.dataset.hh : '']); })()")
        bid, dk, free_hh = json.loads(info)
        self.ok(bool(free_hh), f"переезд: свободный час в колонке есть ({free_hh})")
        smp = (f"() => {{ const b = document.querySelector('.gappt[data-appt=\"{bid}\"]'); if (!b) return null;"
               " const g = document.querySelector('.gridbody').getBoundingClientRect(); const r = b.getBoundingClientRect();"
               " return [Math.round(r.top - g.top), Math.round(r.left - g.left), getComputedStyle(b).transform, b.offsetTop]; }")
        self.js(f"__mc.sample = {smp}; __mc.reset(); 1")
        r = self.client.post_json(f"/api/schedule/appointments/{bid}/move", {"date": self.day, "time": free_hh, "doctor": dk})
        self.ok(r.status == 200, f"переезд: команда переноса принята ({r.status})")
        self.cdp.drain(LIVE_S + 2.5)
        d = self.take()
        seen = [s for s in d["samples"] if s]
        tops = [s[0] for s in seen]
        mid = sorted({t for t in tops if min(tops[0], tops[-1]) < t < max(tops[0], tops[-1])})
        self.ok(tops and tops[0] != tops[-1] and len(mid) >= 3,
                f"переезд: блок доезжает до нового места сдвигом ({tops[0]} → {tops[-1]}, промежуточных положений {len(mid)})")
        end = seen[-1] if seen else None
        self.ok(end is not None and end[2] == "none" and abs(end[0] - end[3]) < 1,
                f"переезд: по концу — без остатка transform, на месте раскладки ({end[2:] if end else '—'})")

    def stats(self) -> None:
        if self.js("document.documentElement.classList.contains('anim')"):
            self.tap(STEP, 1.8)          # первое изменение дня снимает `anim` с документа
            time.sleep(1.6)
        self.ok(not self.js("document.documentElement.classList.contains('anim')"), "Statistici: класс anim с документа снят")
        names = "(q) => Array.from(document.querySelectorAll(q)).flatMap((e) => e.getAnimations().map((a) => a.animationName)).join(',')"
        smp = (f"() => {{ const n = {names};"
               " return [!!document.querySelector('.dp-react-root.anim'), n('.dp-react-root .spark'),"
               " Array.from(document.querySelectorAll('.stx-kpi-v')).map((v) => v.textContent.trim()).join('|'),"
               " n('.stx-bar'), n('.stx-tbl tbody tr')]; }")
        d = self.tap("document.querySelector('.side nav a[href=\"/admin/stats\"]')", 1.6, smp)
        seen = [s for s in d["samples"] if s and s[0]]
        self.ok(bool(seen), "Statistici: экран пришёл с классом anim на своём корне")
        self.ok(any("dp-wipe" in s[1] for s in seen), "Statistici: графики проявляются (dp-wipe идёт)")
        vals = [s[2] for s in seen]
        self.ok(len(set(vals)) >= 3, f"Statistici: цифры плиток считают по кадрам ({len(set(vals))} состояний)")
        self.ok(any("stx-grow-y" in s[3] for s in seen), "Statistici: столбцы графика растут")
        self.ok(any("dp-in" in s[4] for s in seen), "Statistici: строки таблицы въезжают")
        self.ok(not self.js("!!document.querySelector('.dp-react-root.anim')"), "Statistici: по концу входа класс снят")
        # смена периода — новые узлы, но вход не играет заново
        d = self.tap("document.querySelector('.stx-seg a:not(.on)')", 1.0,
                     f"() => {{ const n = {names}; return n('.stx-bar') + n('.stx-tbl tbody tr') + n('.spark'); }}")
        self.ok(not any(d["samples"]), f"Statistici: смена периода вход не повторяет ({sorted(set(d['samples']))[:3]})")
        self.tap("document.querySelector('.side nav a[href=\"/admin\"]')", 1.0)

    def print(self) -> None:
        state = ("JSON.stringify({ css: document.getAnimations().filter((a) => a.playState === 'running'"
                 " && (a.animationName || a.transitionProperty)).length,"
                 " waapi: document.getAnimations().filter((a) => a.playState === 'running' && !(a.animationName || a.transitionProperty)).length,"
                 " ghosts: Array.from(document.querySelectorAll('.fl-row.leaving')).filter((e) => getComputedStyle(e).display !== 'none').length,"
                 " closing: Array.from(document.querySelectorAll('dialog:not([open])')).filter((e) => getComputedStyle(e).display !== 'none').length,"
                 " moved: Array.from(document.querySelectorAll('.fl-row')).filter((e) => getComputedStyle(e).transform !== 'none').length })")
        m = self.cdp.cmd

        def press(finder: str) -> None:
            x, y = self.page.center(finder)
            for t in ("mousePressed", "mouseReleased"):
                m("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)

        # строка уходит со вкладки — печать в момент призрака и сдвига
        self.tap(WAIT_BTN.format(i=0), 1.2)
        self.tap(WAIT_BTN.format(i=0), 1.2)
        self.tap("document.querySelectorAll('.fl-tab')[2]", 0.4)
        press("document.querySelector('.fl-list .fl-row .dk-btn')")
        for _ in range(60):
            if self.js("!!document.querySelector('.fl-row.leaving')"):
                break
            time.sleep(0.01)
        m("Emulation.setEmulatedMedia", media="print")
        # ⚠️ Подмена носителя `beforeprint` не шлёт, а изменение `matchMedia('print')`
        # приходит событием к следующему кадру — его и ждём (настоящая печать шлёт
        # `beforeprint` до раскладки листа, utils/flip слушает оба)
        time.sleep(0.1)
        s = json.loads(self.js(state))
        m("Emulation.setEmulatedMedia", media="")
        self.ok(not any(s.values()), f"печать посреди смыкания: на листе конечный вид ({s})")
        self.tap("document.querySelectorAll('.fl-tab')[0]", 0.4)
        # окно гаснет — печать в момент затухания
        self.tap(BLOCK, 0.6)
        m("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        m("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        time.sleep(0.03)
        m("Emulation.setEmulatedMedia", media="print")
        s = json.loads(self.js(state))
        m("Emulation.setEmulatedMedia", media="")
        self.ok(not any(s.values()), f"печать посреди закрытия окна: на листе конечный вид ({s})")

    def pick(self, finder: str, value: str, wait: float, sample: str = "") -> dict:
        """Выбор в <select> так, как его видит React: значение и событие change."""
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        self.js(f"(() => {{ const s = {finder}; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')"
                f".set.call(s, {json.dumps(value)}); s.dispatchEvent(new Event('change', {{ bubbles: true }})); return 1 }})()")
        self.cdp.drain(wait)
        return self.take()

    def type_in(self, finder: str, text: str, wait: float, sample: str = "") -> dict:
        """Текст в поле так, как его видит React: значение и событие input."""
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        self.js(f"(() => {{ const el = {finder}; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')"
                f".set.call(el, {json.dumps(text)}); el.dispatchEvent(new Event('input', {{ bubbles: true }})); return 1 }})()")
        self.cdp.drain(wait)
        return self.take()

    def fades(self, what: str, dlg: str, d: dict) -> None:
        """Окно `dlg` (условно смонтированное) после закрытия: `d` — замеры `BOX` с
        момента закрытия. Гаснет переходом в ступень, доигрывает его и только потом
        уходит из дерева. Доказательство — событие конца перехода на самом окне (у узла,
        снятого посреди перехода, его нет); промежуточных кадров у headless-Edge на
        ступень выходит от нуля до трёх, поэтому их число не утверждается."""
        step = self.js("getComputedStyle(document.documentElement).getPropertyValue('--dur-fast').trim()")
        want = float(step.rstrip("ms").rstrip("s")) * (1 if step.endswith("ms") else 1000) if step else -1
        seen = d["samples"]
        fading = [s[3] for s in seen if s and s[2] is False and 0 < s[3] < 1]
        mine = [r for r in d["runs"] if r["target"].startswith("dialog") and r["name"] == "opacity" and not r["pseudo"]]
        done = [e for e in d["ends"] if e["target"].startswith("dialog") and e["name"] == "opacity" and not e["pseudo"]]
        self.ok(len(mine) == 1 and abs(mine[0]["dur"] - want) < 1 and len(done) == 1 and fading == sorted(fading, reverse=True),
                f"{what}: окно гаснет переходом в ступень и доигрывает его ({[r['dur'] for r in mine]} мс,"
                f" доиграно {len(done)}, промежуточных кадров {len(fading)})")
        self.ok(bool(seen) and seen[-1] is None and self.js(f"{dlg} === null"), f"{what}: по концу окна в дереве нет")

    def plan(self) -> None:
        if not self.pid:
            raise SystemExit("стенд: фиша с планом не засеяна — сценарий plan не прогнан")
        m = self.cdp.cmd
        self.page.go(f"/admin/patient/{self.pid}?tab=plan")
        time.sleep(0.8)
        box = BOX.format(dlg=TPL)
        open_tpl = "document.querySelector('.plan-add .ptpl-open')"
        cancel = f"Array.from({TPL}.querySelectorAll('.tp-foot .dp-btn')).find((b) => !b.classList.contains('pri'))"
        tooth = f"{TPL}.querySelector('.tp-fields select')"

        # 1. место и высота окна шаблона — от первого кадра (шаблоны ещё грузятся) и дальше
        seen = self.tap(open_tpl, 1.2, box)["samples"]
        self.ok(self.js(f"{TPL}.querySelectorAll('.tp-item').length") == len(PLAN_TPLS),
                f"окно шаблона: открылось со списком из {len(PLAN_TPLS)} шаблонов")
        warn = f"(() => {{ const w = {TPL}.querySelector('.tp-warn'); return w ? w.textContent.trim() : null; }})()"
        said = [self.js(warn)]
        for value in ("36", "", "36"):
            seen += self.pick(tooth, value, 0.5, box)["samples"]
            said.append(self.js(warn))
        self.ok(bool(said[0]) and bool(said[2]) and not said[1] and not said[3],
                f"окно шаблона: предупреждение о зубе есть без зуба и молчит с зубом ({[bool(x) for x in said]})")
        for i in (1, 2, 0):
            seen += self.tap(f"{TPL}.querySelectorAll('.tp-item')[{i}]", 0.5, box)["samples"]
        self.ok(self.js(f"{TPL}.querySelector('.tp-main').scrollHeight <= {TPL}.querySelector('.tp-main').clientHeight"),
                "окно шаблона: короткий шаблон виден целиком, без прокрутки")
        frames = [s for s in seen if s and s[2]]
        sizes = sorted({(s[0], s[1]) for s in frames})
        self.ok(len(frames) > 20 and len(sizes) == 1,
                f"окно шаблона: место и высота одни при загрузке, выборе зуба и смене шаблона"
                f" (верх, высота: {sizes[:4]}, кадров {len(frames)})")

        # 2. закрытие: «Renunță», Esc, удачная вставка
        self.fades("вставка, «Renunță»", TPL, self.tap(cancel, 0.8, box))
        self.tap(open_tpl, 1.0)
        self.fades("вставка, Esc", TPL, self.key("Escape", 27, 0.8, box))
        self.tap(open_tpl, 1.0)
        self.pick(tooth, "36", 0.3)
        d = self.tap(f"{TPL}.querySelector('.tp-foot .dp-btn.pri')", 1.4, box)
        posts = [r["status"] for r in d["res"] if "/plan/from-template" in r["name"]]
        self.ok(posts == [200], f"вставка: шаблон ушёл в план одной командой ({posts})")
        self.fades("вставка, после записи", TPL, d)
        self.ok(self.js("document.querySelectorAll('.plan-row').length") >= 4, "вставка: строки шаблона встали в план")
        time.sleep(0.4)

        # 3. правка позиции: меню строки → «Editează»
        edit = "document.querySelector('dialog.dp-plan-edit')"
        self.tap("document.querySelector('.plan-row .pact .dp-more')", 0.5)
        self.tap(BY_TEXT.format(sel=".dp-cmenu [role=menuitem]", text="Editează"), 0.8)
        self.ok(self.js(f"!!{edit} && {edit}.open"), "правка позиции: окно открылось")
        # подсказка прайса приходит и уходит с набором процедуры — высота окна та же
        ebox = BOX.format(dlg=edit)
        seen, notes = [], []
        for text in (self.listed, "Ceva în afara listei", self.listed):
            seen += self.type_in(f"{edit}.querySelector('.dp-svc input')", text, 0.4, ebox)["samples"]
            notes.append(self.js(f"!!{edit}.querySelector('.dp-price-note')"))
        sizes = sorted({(s[0], s[1]) for s in seen if s and s[2]})
        self.ok(notes == [True, False, True] and len(sizes) == 1,
                f"правка позиции: подсказка прайса есть и нет ({notes}), место и высота окна одни ({sizes})")
        self.type_in(f"{edit}.querySelector('.dp-svc input')", "Coroană de probă", 0.3)     # как было: закрытие без вопроса
        # набор открыл список услуг (ServicePicker), и Esc закрыл бы только его: поле отпускается, список уходит
        self.js("document.activeElement && document.activeElement.blur(); 1")
        time.sleep(0.2)
        self.fades("правка позиции, Esc", edit, self.key("Escape", 27, 0.8, ebox))

        # 4. «Salvează ca șablon»: меню карточки плана
        save = "document.querySelector('dialog.dp-plan-tpl.save')"
        self.tap("document.querySelector('h3.plan-h .dp-more')", 0.5)
        self.tap(BY_TEXT.format(sel=".dp-cmenu [role=menuitem]", text="Salvează ca șablon"), 0.8)
        self.ok(self.js(f"!!{save} && {save}.open"), "«Salvează ca șablon»: окно открылось")
        self.fades("«Salvează ca șablon», «Renunță»", save,
                   self.tap(f"Array.from({save}.querySelectorAll('.tp-foot .dp-btn')).find((b) => !b.classList.contains('pri'))",
                            0.8, BOX.format(dlg=save)))

        # 5. подпись на экране — где сервер её даёт (нужен Edge для PDF: у стенда он есть)
        sign = "document.querySelector('dialog.dp-sign')"
        sign_btn = BY_TEXT.format(sel=".dp-consent button.lnk", text="Semnează")
        self.ok(self.js(f"!!{sign_btn}"), "подпись: кнопка «Semnează pe ecran» в полосе согласия есть")
        if self.js(f"!!{sign_btn}"):
            self.tap(sign_btn, 1.2)
            self.fades("подпись, «Renunță»", sign,
                       self.tap(f"{sign}.querySelector('.sg-foot .pl-btn')", 0.8, BOX.format(dlg=sign)))

        # 6. печать посреди закрытия окна вставки
        self.tap(open_tpl, 1.0)
        x, y = self.page.center(cancel)
        for t in ("mousePressed", "mouseReleased"):
            m("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)
        time.sleep(0.03)
        m("Emulation.setEmulatedMedia", media="print")
        s = json.loads(self.js(
            "JSON.stringify({ css: document.getAnimations().filter((a) => a.playState === 'running'"
            " && (a.animationName || a.transitionProperty)).length,"
            " waapi: document.getAnimations().filter((a) => a.playState === 'running' && !(a.animationName || a.transitionProperty)).length,"
            " closing: Array.from(document.querySelectorAll('dialog:not([open])')).filter((e) => getComputedStyle(e).display !== 'none').length })"))
        m("Emulation.setEmulatedMedia", media="")
        self.ok(not any(s.values()), f"печать посреди закрытия окна вставки: на листе конечный вид ({s})")
        time.sleep(0.4)
        self.ok(self.js(f"{TPL} === null"), "печать посреди закрытия: после неё окно из дерева ушло")

    def move_to(self, x: float, y: float) -> None:
        self.cdp.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    def rect(self, finder: str) -> list[float]:
        """Прямоугольник элемента на экране; элемент — в видимую область."""
        self.js(f"(() => {{ const el = {finder}; if (el) el.scrollIntoView({{block: 'center'}}); }})()")
        time.sleep(0.3)
        return json.loads(self.js(f"(() => {{ const r = ({finder}).getBoundingClientRect();"
                                  " return JSON.stringify([r.left, r.top, r.width, r.height]) })()"))

    def press(self, x: float, y: float, hold: float = 0.0) -> None:
        m = self.cdp.cmd
        m("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        if hold:
            time.sleep(hold)
        m("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)

    def tile(self) -> None:
        m = self.cdp.cmd
        ids = json.loads(self.js("JSON.stringify(Array.from(document.querySelectorAll('.gcol')).map((c) =>"
                                 " Array.from(c.querySelectorAll('.gappt:not(.gnote):not(.done)')).map((a) => a.dataset.appt))"
                                 ".find((l) => l.length >= 3) || [])"))
        if len(ids) < 3:
            raise SystemExit("стенд: в колонке нет трёх блоков визита — сценарий tile не прогнан")
        a, b, c = (TILE.format(id=i) for i in ids[:3])

        def mine(d: dict, i: str) -> list[str]:
            return sorted(r["props"] for r in d["waapi"] if r["appt"] == i)

        base = self.js(LAYOUT)
        lift = float((self.js("getComputedStyle(document.documentElement).getPropertyValue('--lift-block').trim()") or "0")
                     .replace("px", "") or 0)
        self.ok(lift < 0, f"стенд: подъём блока задан ({lift} px) — иначе наведение мерить нечем")

        # 1. наведение: подъём на ступень, раскладка та же, зубчик и блик — раз
        x, y, w, h = self.rect(a)
        self.move_to(5, 5)
        time.sleep(0.3)
        self.js(f"__mc.sample = {LIFT.format(tile=a)}; __mc.reset(); 1")
        self.move_to(x + w / 2, y + h / 2)
        self.cdp.drain(0.6)
        d = self.take()
        ys = [s[0] for s in d["samples"]]
        self.ok(bool(ys) and ys[-1] == lift and d["samples"][-1][1] == 1 and all(p >= q for p, q in zip(ys, ys[1:])),
                f"наведение: блок поднимается на ступень и стоит ({ys[:1]} … {ys[-1:]} px, кадров {len(ys)})")
        self.ok(self.js(LAYOUT) == base, "наведение: место, размер и ступени сжатия всех блоков те же")
        tooth = bool(self.js(f"(() => {{ const l = {a}.querySelector('.apact'); return !!l && getComputedStyle(l).display !== 'none'; }})()"))
        want = sorted(["opacity+translate"] + (["rotate"] if tooth else []))
        self.ok(mine(d, ids[0]) == want, f"наведение: оборот зубчика и блик — по одному запуску ({mine(d, ids[0])}, зуб {'есть' if tooth else 'нет'})")
        self.js("__mc.sample = null; __mc.reset(); 1")
        for i in range(8):                      # курсор ходит внутри блока: с имени на зуб и обратно
            self.move_to(x + w * (0.25 + 0.07 * i), y + h * (0.4 + 0.03 * (i % 3)))
            time.sleep(0.12)
        time.sleep(0.5)
        self.ok(not mine(self.take(), ids[0]), "наведение: курсор ходит внутри блока — повтора нет")
        self.js("__mc.sample = null; __mc.reset(); 1")
        self.move_to(5, 5)
        time.sleep(0.3)
        self.move_to(x + w / 2, y + h / 2)
        time.sleep(0.9)
        self.ok(mine(self.take(), ids[0]) == want, "наведение: ушёл и вернулся — играет снова")

        # 2. нижняя кромка: курсор в полоске под поднятым блоком, рука дрожит в пределах пикселя
        self.move_to(5, 5)
        time.sleep(0.4)
        x, y, w, h = self.rect(b)
        self.js(f"__mc.sample = {LIFT.format(tile=b)}; __mc.reset(); 1")
        self.move_to(x + w / 2, y + h - 0.6)
        self.cdp.drain(1.0)
        for i in range(14):
            self.move_to(x + w / 2 + (i % 2) * 0.6, y + h - 0.6 - (i % 3) * 0.3)
            time.sleep(0.12)
        ys = [s[0] for s in self.take()["samples"]]
        turns, last = 0, 0
        for p, q in zip(ys, ys[1:]):
            way = (q > p) - (q < p)
            if way and last and way != last:
                turns += 1
            last = way or last
        self.ok(bool(ys) and min(ys) == lift and turns == 0,
                f"кромка: блок поднят и не дёргается — разворотов движения {turns} (кадров {len(ys)}, от {min(ys or [0])} до {max(ys or [0])} px)")

        # 3. щелчок посреди анимации у края блока: окно ЭТОГО визита, растёт из блока
        self.move_to(5, 5)
        time.sleep(0.5)
        x, y, w, h = self.rect(c)
        name = self.js(f"Array.from({c}.querySelector('b').childNodes).filter((n) => n.nodeType === 3)"
                       ".map((n) => n.textContent).join('').trim()")
        px, py = x + w * 0.12, y + h * 0.25
        self.move_to(px, y - 12)
        time.sleep(0.2)
        self.js(f"__mc.sample = {WIN}; __mc.reset(); 1")
        self.move_to(px, py)
        time.sleep(0.14)
        self.press(px, py, 0.06)
        self.cdp.drain(0.9)
        d = self.take()
        seen = [s for s in d["samples"] if s]
        got = self.js("(() => { const w = document.querySelector('dialog[open]'); return w ? w.textContent.slice(0, 300) : ''; })()")
        self.ok(bool(name) and name in got, f"щелчок посреди анимации у края блока открыл карточку этого визита ({name})")
        scales = [s[0] for s in seen]
        starts = sorted({s[4] for s in seen if s[4] is not None})
        self.ok(bool(starts) and starts[0] < 0.8 and bool(scales) and scales[-1] == 1 and all(p <= q for p, q in zip(scales, scales[1:])),
                f"окно: растёт из блока до своего размера (с масштаба {starts[:1]}, по кадрам {scales[:1]} … {scales[-1:]}, кадров {len(scales)})")
        ops = [s[1] for s in seen]
        self.ok(bool(ops) and ops[-1] == 1 and all(p <= q for p, q in zip(ops, ops[1:])) and not d["shifts"],
                f"окно: прозрачность только растёт, сдвигов раскладки нет ({ops[:1]} … {ops[-1:]}, сдвиги {d['shifts']})")
        self.ok(self.js("(() => { const w = document.querySelector('dialog[open]'); const r = w.getBoundingClientRect();"
                        " return w.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); })()"),
                "окно: встало на место и кликабельно")
        d = self.key("Escape", 27, 0.9, WIN)
        closing = [s for s in d["samples"] if s and s[2] == 0]
        aims = sorted({s[3] for s in closing if s[3] is not None})
        done = [e for e in d["ends"] if e["target"].startswith("dialog") and e["name"] == "opacity" and not e["pseudo"]]
        # Окно ушло СВОИМ переходом, а не снятием узла: доказательство — событие конца перехода на
        # самом окне. Обычно это прозрачность; примерно раз из сорока заходов окно уходит по концу
        # своего перехода `display` на кадр раньше, и конец прозрачности (она к этому кадру у нуля)
        # движок уже не шлёт. У узла, снятого посреди перехода, нет ни того, ни другого.
        left = [e for e in d["ends"] if e["target"].startswith("dialog") and e["name"] == "display" and not e["pseudo"]]
        faded = min([s[1] for s in closing] or [1])
        self.ok(bool(aims) and aims[0] < 0.8 and (len(done) == 1 or len(left) == 1) and faded < 0.3,
                f"окно: по Esc сворачивается в блок и доигрывает переход (масштаб цели {aims[:1]},"
                f" конец прозрачности {len(done)}, конец display {len(left)}, погасло до {round(faded, 3)})")
        if not (done or left) or os.environ.get("MC_VERBOSE"):      # что было с окном — глазами, при разборе
            for r in d["runs"]:
                if r["target"].startswith("dialog"):
                    print("      · запуск", r["kind"], r["name"], r["pseudo"], r["dur"])
            for e in d["ends"]:
                if e["target"].startswith("dialog"):
                    print("      · конец", e["name"], e["pseudo"])
            print("      · кадры (масштаб, прозрачность, открыто, цель):", [s[:4] if s else None for s in d["samples"]][:40])
        self.ok(bool(d["samples"]) and d["samples"][-1] is None, "окно: по концу сворачивания окна на экране нет")

        # 4. перенос, начатый посреди анимации наведения
        self.move_to(5, 5)
        time.sleep(0.6)
        x, y, w, h = self.rect(a)
        name = self.js(f"Array.from({a}.querySelector('b').childNodes).filter((n) => n.nodeType === 3)"
                       ".map((n) => n.textContent).join('').trim()")
        self.js(GRAB)
        self.js("__mc.img = null; 1")
        m("Input.setInterceptDrags", enabled=True)
        try:
            px, py = x + w * 0.5, y + h * 0.3
            self.move_to(px, y - 12)
            time.sleep(0.2)
            self.move_to(px, py)
            time.sleep(0.12)
            m("Input.dispatchMouseEvent", type="mousePressed", x=px, y=py, button="left", clickCount=1)
            self.cdp.events = []
            for i in range(1, 6):
                m("Input.dispatchMouseEvent", type="mouseMoved", x=px + 2, y=py + i * 6, button="left", buttons=1)
                time.sleep(0.03)
            self.cdp.drain(0.5)
            data = next((e["params"]["data"] for e in self.cdp.events if e["method"] == "Input.dragIntercepted"), None)
            ds = json.loads(self.js("JSON.stringify(window.__ds)") or "null")
            img = json.loads(self.js("JSON.stringify(__mc.img)") or "null")
            self.ok(data is not None and ds is not None, "перенос посреди анимации начался")
            self.ok(bool(ds) and abs(ds["dy"]) < 0.6 and abs(ds["h"] - ds["lh"]) < 0.6 and ds["dragging"],
                    f"перенос: в миг хвата блок стоит ровно на своём месте ({ds})")
            self.ok(bool(img) and img["cls"] == "gdragimg" and img["rot"] not in ("", "none")
                    and 0 < img["x"] < img["w"] and 0 < img["y"] < img["h"],
                    f"перенос: под курсор отдана наклонённая копия блока, курсор держит её внутри ({img})")
            ty = py + 2 * h + 40
            if data is not None:
                for kind in ("dragEnter", "dragOver", "dragOver"):
                    m("Input.dispatchDragEvent", type=kind, x=px, y=ty, data=data)
                    time.sleep(0.08)
            mid = json.loads(self.js(f"(() => {{ const t = {a}; const g = document.querySelector('.gdrop');"
                                     " return JSON.stringify({ src: t.hasAttribute('data-src'), op: Number(getComputedStyle(t).opacity),"
                                     " drop: g ? getComputedStyle(g).animationName : '', at: g ? g.dataset.at : '' }) })()"))
            self.ok(mid["src"] and mid["op"] < 0.5, f"перенос: блок на старом месте бледнеет, пока его несут (opacity {mid['op']})")
            self.ok(mid["drop"] == "g-droppulse" and bool(mid["at"]), f"перенос: место броска светится ({mid['drop']}, {mid['at']})")
            if data is not None:
                m("Input.dispatchDragEvent", type="drop", x=px, y=ty, data=data)
            m("Input.dispatchMouseEvent", type="mouseReleased", x=px, y=ty, button="left", clickCount=1)
            time.sleep(0.7)
            got = self.js("(() => { const w = document.querySelector('dialog[open]'); return w ? w.textContent.slice(0, 200) : ''; })()")
            self.ok(bool(name) and name in got, f"перенос: бросок открыл окно переноса этого визита ({got[:40]!r})")
            self.esc()
            self.move_to(px, ty + 3)
            time.sleep(0.2)
            left = self.js("document.querySelectorAll('[data-dragging], [data-src], .gdragimg').length")
            self.ok(left == 0, f"перенос: после броска пометок и копии не осталось ({left})")
        finally:
            m("Input.setInterceptDrags", enabled=False)
        self.move_to(5, 5)
        time.sleep(0.4)

    def event(self) -> None:
        m = self.cdp.cmd
        now = datetime.now(TZ)
        left = (30 - now.minute % 30) * 60 - now.second
        if left < 75:
            print(f"  … до границы получаса {left} с — жду её: на ней сервер законно меняет конверт")
            time.sleep(left + 3)
            self.home()
        ids = json.loads(self.js("JSON.stringify(Array.from(document.querySelectorAll('.gappt[data-st=\"confirmed\"]'))"
                                 ".map((a) => a.dataset.appt))"))
        if len(ids) < 2:
            raise SystemExit("стенд: нет двух записей «programată» — сценарий event не прогнан")
        first, second = ids[0], ids[1]
        step = "document.querySelector('.ag-l .ag-i[data-appt=\"{id}\"] .ag-next')"
        base = self.js(PLACE)

        def names(d: dict, kind: str) -> list[str]:
            return [r["name"] for r in d["runs"] if r["kind"] == kind and r["name"].startswith("g-")]


        d = self.tap(step.format(id=first), 1.7)
        self.ok(self.js(f"{TILE.format(id=first)}.dataset.st") == "waiting" and sorted(names(d, "animation")) == ["g-flash", "g-sweep"],
                f"«a venit»: вспышка и блик — по одному разу ({names(d, 'animation')})")
        d = self.tap(step.format(id=first), 1.9)
        self.ok(self.js(f"{TILE.format(id=first)}.dataset.st") == "arrived"
                and names(d, "animation") == ["g-beat"] and names(d, "iteration") == ["g-beat", "g-beat"],
                f"«în cabinet»: полоска бьёт три раза и замолкает (запуск {names(d, 'animation')}, повторов {len(names(d, 'iteration'))})")
        turn = (f"() => {{ const t = {TILE.format(id=first)}; return [getComputedStyle(t).transform === 'none' ? 0 : 1, t.dataset.st]; }}")
        d = self.tap(step.format(id=first), 1.9, turn)
        flips = [r for r in d["runs"] if r["kind"] == "animation" and r["name"] == "g-flip"]
        seen = [s for s in d["samples"] if s]
        self.ok(len(flips) == 1 and abs(flips[0]["dur"] - 600) < 1 and any(s[0] for s in seen) and bool(seen) and seen[-1] == [0, "done"],
                f"«finalizat»: блок переворачивается один раз за 600 мс, по концу без остатка transform"
                f" ({[r['dur'] for r in flips]} мс, кадров с поворотом {sum(s[0] for s in seen)})")
        self.ok(self.js(PLACE) == base, "события: место и размер всех блоков те же")
        # опрос живого канала после событий: всё отыграло, пометок нет — не играет ничего
        self.js("__mc.sample = null; __mc.reset(); 1")
        self.cdp.drain(LIVE_S + 3)
        d = self.take()
        live = [r["status"] for r in d["res"] if "/schedule/live" in r["name"]]
        self.ok(bool(live) and all(s == 204 for s in live) and not d["runs"] and not d["waapi"],
                f"события: опрос после них — {live}, запусков {len(d['runs'])}"
                + (f" — {[r['name'] + ' ' + r['target'][:30] for r in d['runs'][:4]]}" if d["runs"] else ""))
        # печать посреди переворота
        self.tap(step.format(id=second), 1.7)
        self.tap(step.format(id=second), 1.9)
        x, y = self.page.center(step.format(id=second))
        self.move_to(x, y)
        time.sleep(0.3)
        self.press(x, y)
        for _ in range(150):
            if self.js(f"!!document.querySelector('.gappt.moved[data-appt=\"{second}\"][data-st=\"done\"]')"):
                break
            time.sleep(0.01)
        time.sleep(0.05)
        going = self.js("document.getAnimations().filter((a) => a.animationName === 'g-flip' && a.playState === 'running').length")
        m("Emulation.setEmulatedMedia", media="print")
        s = json.loads(self.js(
            "JSON.stringify({ css: document.getAnimations().filter((a) => a.playState === 'running'"
            " && (a.animationName || a.transitionProperty)).length,"
            " waapi: document.getAnimations().filter((a) => a.playState === 'running' && !(a.animationName || a.transitionProperty)).length,"
            " turned: Array.from(document.querySelectorAll('.gappt')).filter((e) => getComputedStyle(e).transform !== 'none').length })"))
        m("Emulation.setEmulatedMedia", media="")
        self.ok(going == 1 and not any(s.values()), f"печать посреди переворота: на листе конечный вид (шёл переворот: {going}, на листе {s})")
        time.sleep(1.6)

    def answer_put(self, aid: str, result: str) -> None:
        """Пациент нажал ссылку: строка `appt_calls` каналом `sms` — то, что пишет `schedule/plink.apply`."""
        con = sqlite3.connect(str(self.data_dir / "dental.db"), timeout=5)
        try:
            con.execute(
                "INSERT INTO appt_calls(appointment_id, result, actor, at, via) VALUES(?, ?, 'pacient', ?, 'sms')"
                " ON CONFLICT(appointment_id) DO UPDATE SET result = excluded.result, actor = excluded.actor,"
                " at = excluded.at, via = excluded.via",
                (int(aid), result, datetime.now(timezone.utc).replace(microsecond=0).isoformat()))
            con.commit()
        finally:
            con.close()

    def answer_wait(self, finder: str, sample: str = "", extra: float = 1.0) -> dict:
        """Ждать опроса, который принесёт ответ (до двух периодов), и ещё `extra` секунд после."""
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        for _ in range(int((2 * LIVE_S + 4) / 0.25)):
            self.cdp.drain(0.25)
            if self.js(f"!!({finder})"):
                break
        self.cdp.drain(extra)
        return self.take()

    def answer(self) -> None:
        if self.data_dir is None:
            raise SystemExit("стенд: сценарий answer без засева права sms_link")
        now = datetime.now(TZ)
        left = (30 - now.minute % 30) * 60 - now.second
        if left < 110:
            print(f"  … до границы получаса {left} с — жду её: на ней сервер законно меняет конверт")
            time.sleep(left + 3)
            self.home()
        if self.js("document.documentElement.classList.contains('anim')"):
            self.tap(STEP, 1.8)          # как у стойки: первое изменение дня снимает `anim`
            time.sleep(1.6)
        ids = json.loads(self.js("JSON.stringify(Array.from(document.querySelectorAll('.gappt[data-st=\"confirmed\"]'))"
                                 ".map((a) => a.dataset.appt))"))
        if len(ids) < 3:
            raise SystemExit("стенд: нет трёх записей «programată» — сценарий answer не прогнан")
        yes, no, late = ids[0], ids[1], ids[2]
        base = self.js(PLACE)
        plate = ("() => {{ const b = Array.from(document.querySelectorAll('.dp-ans .dp-ans-t'))"
                 ".find((x) => x.dataset.appt === '{id}'); return b ? [Number(getComputedStyle(b).opacity),"
                 " Math.round(b.getBoundingClientRect().top), b.parentElement.classList.contains('out') ? 1 : 0,"
                 " Number(getComputedStyle(b.parentElement).opacity)] : null; }}")

        # «Vin» приехал опросом
        self.answer_put(yes, "ok")
        d = self.answer_wait(f"document.querySelector('.dp-ans-t[data-appt=\"{yes}\"]')", plate.format(id=yes), 1.8)
        vin = [r for r in d["runs"] if r["kind"] == "animation" and r["name"] == "dp-vin"]
        toast = [r for r in d["runs"] if r["kind"] == "animation" and r["name"] == "dp-toast" and "dp-ans-t" in r["target"]]
        seen = [x for x in d["samples"] if x]
        self.ok(len(vin) == 1 and abs(vin[0]["dur"] - 1600) < 1,
                f"«Vin»: галочка на блоке выскакивает один раз за 1,6 с ({[r['dur'] for r in vin]} мс)")
        self.ok(len(toast) == 1 and bool(seen) and seen[0][0] < 0.6 and seen[0][1] > seen[-1][1],
                "«Vin»: плашка въезжает — прозрачность и место по кадрам "
                + (f"({seen[0]} → {seen[-1]})" if seen else "(плашки нет)"))
        self.ok(self.js(PLACE) == base, "«Vin»: место и размер всех блоков те же")
        self.ok(not self.js(f"!!document.querySelector('.gappt[data-appt=\"{yes}\"] .gvin')"),
                "«Vin»: галочка ушла с блока (таймер пометки)")
        # «Vin» гаснет сама (~8 с с прихода) и уходит из дерева; опросы за это время — 204 без анимаций
        self.js(f"__mc.sample = {plate.format(id=yes)}; __mc.reset(); 1")
        for _ in range(60):
            self.cdp.drain(0.25)
            if not self.js(f"!!document.querySelector('.dp-ans-t[data-appt=\"{yes}\"]')"):
                break
        # и ещё период опроса после ухода: в окне замера обязан быть опрос (он и должен ответить 204)
        self.cdp.drain(LIVE_S + 1)
        d = self.take()
        fade = [r for r in d["runs"] if r["kind"] == "transition" and r["name"] == "opacity" and "dp-ans-w" in r["target"]]
        mid = [x for x in d["samples"] if x and x[2] and 0 < x[3] < 1]
        self.ok(bool(fade) and bool(mid) and not self.js(f"!!document.querySelector('.dp-ans-t[data-appt=\"{yes}\"]')"),
                f"«Vin»: плашка гаснет переходом и уходит из дерева (переходов {len(fade)}, кадров затухания {len(mid)})")
        live = [r["status"] for r in d["res"] if "/schedule/live" in r["name"]]
        news = [r for r in d["runs"] if r["kind"] == "animation"]
        self.ok(bool(live) and all(x == 204 for x in live) and not news,
                f"«Vin»: опросы после ответа — {live}, анимаций {len(news)}"
                + (f" — {[r['name'] + ' ' + r['target'][:30] for r in news[:4]]}" if news else ""))

        # «Nu pot veni»: висит, слово на блоке, «De confirmat»
        self.js("try { localStorage.setItem('dp_fold:desk:confirm_today', '1') } catch (e) {} 1")
        self.answer_put(no, "cant")
        self.answer_wait(f"document.querySelector('.dp-ans-t[data-appt=\"{no}\"]')", "", 0.5)
        self.cdp.drain(9)
        self.ok(self.js(f"!!document.querySelector('.dp-ans-t.cant[data-appt=\"{no}\"]:not(.out)')"),
                "«Nu pot veni»: плашка висит и через 9 с")
        word = self.js(f"(() => {{ const w = document.querySelector('.gappt[data-appt=\"{no}\"] .stat');"
                       " return w ? w.className + '|' + w.textContent : ''; })()")
        self.ok(word == "stat s-cant|nu poate veni", f"«Nu pot veni»: слово на блоке цветом предупреждения ({word!r})")
        self.home()
        self.js("__mc.sample = null; __mc.reset(); 1")
        first = self.js("(() => { const r = document.querySelector('[data-fold=\"desk:confirm_today\"] .dk-row');"
                        " const c = document.querySelector('[data-fold=\"desk:confirm_today\"] .dk-cnt');"
                        " return (r ? r.dataset.appt : '') + '|' + (c ? c.className : ''); })()")
        self.ok(first == f"{no}|dk-cnt amber", f"«De confirmat azi»: «Nu poate veni» наверху, счёт цветом предупреждения ({first!r})")
        self.ok(not self.js("!!document.querySelector('.dp-ans')"),
                "первый показ главной (вернулись на экран): старые ответы плашками не всплывают")

        # окно визита из плашки: свежий ответ, щелчок по плашке
        self.answer_put(no, "cant")      # новое время ответа — новая пара, плашка снова
        con = sqlite3.connect(str(self.data_dir / "dental.db"), timeout=5)
        con.execute("UPDATE appt_calls SET at = ? WHERE appointment_id = ?",
                    ((datetime.now(timezone.utc) + timedelta(seconds=1)).replace(microsecond=0).isoformat(), int(no)))
        con.commit()
        con.close()
        self.answer_wait(f"document.querySelector('.dp-ans-t[data-appt=\"{no}\"]')", "", 0.6)
        d = self.tap(f"document.querySelector('.dp-ans-t[data-appt=\"{no}\"] .dp-ans-open')", 0.9, DLG)
        seen = [x for x in d["samples"] if x]
        ops = [x[0] for x in seen]
        self.ok(bool(ops) and ops[0] < 0.3 and ops[-1] == 1 and ops == sorted(ops),
                f"окно из плашки: проявляется по кадрам ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")
        self.ok(len({x[1] for x in seen}) == 1 and self.js("!!document.querySelector('dialog[open] .dp-card-cant')"),
                f"окно из плашки: жёлтая полоса на месте, высота окна по кадрам одна ({sorted({x[1] for x in seen})})")
        self.ok(not d["shifts"], f"окно из плашки: сдвигов раскладки нет ({d['shifts']})")
        self.esc()
        time.sleep(0.4)

        # без движения: плашка и галочка встают сразу
        self.cdp.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        try:
            self.answer_put(late, "ok")
            d = self.answer_wait(f"document.querySelector('.dp-ans-t[data-appt=\"{late}\"]')", "", 1.0)
        finally:
            self.cdp.cmd("Emulation.setEmulatedMedia", features=[])
        moving = [r for r in d["runs"] if r["dur"] > 0 and r["name"] in ("dp-vin", "dp-toast")]
        self.ok(not moving, f"без движения: «Vin» — без анимаций ({[r['name'] for r in moving]})")
        if self.js("!!document.querySelector('.dp-ans .t-x')"):
            self.js("document.querySelectorAll('.dp-ans .t-x').forEach((b) => b.click()); 1")
        time.sleep(0.4)

    def agenda(self) -> None:
        box = "document.querySelector('details[data-fold=\"agenda\"]')"
        btn = "Array.from(document.querySelectorAll('.ag-view button')).find((b) => b.textContent.trim() === '{t}')"
        place = "(() => {{ const r = {b}.getBoundingClientRect(); return JSON.stringify([Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10]) }})()"
        self.ok(bool(self.js(f"{box}.open && !!{btn.format(t='compactă')} && !!{btn.format(t='detaliată')}"
                             f" && {btn.format(t='detaliată')}.closest('summary') === {box}.querySelector('summary')")),
                "вид повестки: переключатель стоит в шапке открытого блока")
        for t, compact in (("detaliată", False), ("compactă", True)):
            b = btn.format(t=t)
            x, y, w, h = self.rect(b)
            cx, cy = x + w / 2, y + h / 2
            self.move_to(cx, cy)
            time.sleep(0.2)
            tall = self.js(f"{box}.querySelector('.ag-l').offsetHeight")
            before = json.loads(self.js(place.format(b=b)))
            self.press(cx, cy)
            time.sleep(0.5)
            after = json.loads(self.js(place.format(b=b)))
            under = self.js(f"document.elementFromPoint({cx}, {cy}) === {b}")
            now = self.js(f"{box}.querySelector('.ag-l').offsetHeight")
            self.ok(before == after and bool(under) and self.js(f"{box}.open") and self.js(f"{box}.classList.contains('cmp')") == compact
                    and now != tall,
                    f"«{t}»: кнопка осталась под курсором на месте ({before} → {after}), список {tall} → {now} px, блок открыт")
        head = f"{box}.querySelector('summary b')"
        self.tap(head, 0.6)
        shown = self.js(f"getComputedStyle({box}.querySelector('.ag-view')).display")
        self.ok(not self.js(f"{box}.open") and shown == "none", f"вид повестки: у свёрнутого блока переключателя нет ({shown})")
        self.tap(head, 0.6)
        shown = self.js(f"getComputedStyle({box}.querySelector('.ag-view')).display")
        self.ok(self.js(f"{box}.open") and shown != "none" and self.js(f"{box}.classList.contains('cmp')")
                and self.js("localStorage.getItem('dp_fold:agenda')") == "1",
                f"вид повестки: открыли снова — переключатель на месте, вид тот же, блок помнит, что открыт ({shown})")

    def enter(self, wait: float) -> None:
        """Enter с символом: нажатие без него не отправляет форму и не нажимает кнопку."""
        for kind in ("keyDown", "keyUp"):
            self.cdp.cmd("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                         **({"text": chr(13)} if kind == "keyDown" else {}))
        self.cdp.drain(wait)

    def focus(self) -> None:
        # Последний целиком свободный час дня: вечер, после засева, записи в прошлое нет.
        where = json.loads(self.js(
            "(() => { const all = Array.from(document.querySelectorAll('.gcell[data-free=\"all\"]:not([disabled])'));"
            " const c = all.at(-1); if (!c) return 'null';"
            " return JSON.stringify([Array.from(document.querySelectorAll('.gcol')).indexOf(c.closest('.gcol')),"
            " c.getAttribute('data-hh')]) })()"))
        self.ok(bool(where) and where[0] >= 0, f"фокус: свободный час для записи есть ({where})")
        if not where or where[0] < 0:
            return
        cell = f"document.querySelectorAll('.gcol')[{where[0]}].querySelector('.gcell[data-hh=\"{where[1]}\"]')"
        ringed = "document.querySelectorAll('.gcell:focus-visible').length"
        opened = "!!document.querySelector('dialog[open] input[placeholder=\"Nume, telefon sau nr. fișei\"]')"
        field = "document.querySelector('dialog[open] input[placeholder=\"{p}\"]')"

        self.tap(cell, 0.8)
        was = self.js(opened)
        self.esc()
        time.sleep(0.6)
        self.ok(bool(was) and not self.js(opened) and self.js(ringed) == 0,
                f"мышь и Esc: окно открылось ({was}) и закрылось, рамки клавиатуры на часе нет ({self.js(ringed)})")

        self.tap(cell, 0.8)
        self.pick("Array.from(document.querySelectorAll('dialog[open] select'))"
                  ".find((s) => Array.from(s.options).some((o) => o.value === '15'))", "15", 0.2)
        self.type_in(field.format(p="Nume, telefon sau nr. fișei"), "Proba Focus", 0.1)
        self.type_in(field.format(p="Telefon"), "069770999", 0.1)
        self.js(f"{field.format(p='Nume, telefon sau nr. fișei')}.focus(); 1")
        self.enter(1.6)
        made = self.js("Array.from(document.querySelectorAll('.gappt')).filter((b) => (b.title || '').includes('Proba Focus')).length")
        free = self.js(f"(() => {{ const c = {cell}; return c ? c.getAttribute('data-free') + (c.disabled ? ' off' : '') : 'null' }})()")
        self.ok(made == 1 and not self.js(opened) and free == "part" and self.js(ringed) == 0,
                f"мышь и Enter: запись внесена ({made}), час остался со свободным отрезком ({free}),"
                f" рамки клавиатуры на нём нет ({self.js(ringed)})")

        # с клавиатуры: последним было нажатие клавиши, фокус из скрипта браузер считает клавиатурным
        had = self.js(f"(() => {{ const c = {cell}; c.focus(); return c.matches(':focus-visible') }})()")
        self.enter(0.8)
        was = self.js(opened)
        self.esc()
        time.sleep(0.6)
        back = self.js(f"(() => {{ const c = {cell}; return document.activeElement === c && c.matches(':focus-visible') }})()")
        self.ok(bool(had) and bool(was) and bool(back) and not self.js(opened),
                f"клавиатура: час с рамкой ({had}) открыл окно клавишей ({was}), после Esc фокус и рамка вернулись ({back})")
        self.js("document.activeElement && document.activeElement.blur(); 1")

    # ---------- импорт пациентов с записями ----------

    def shot(self, name: str) -> None:
        """Кадр страницы целиком в папку $MC_SHOTS (не задана — кадров нет)."""
        folder = os.environ.get("MC_SHOTS")
        if not folder:
            return
        import base64
        # окно во всю высоту страницы: кадр «за окном» рисует шапку и меню там, где стоит прокрутка
        y = self.js("Math.round(scrollY)")
        h = self.js("Math.ceil(document.documentElement.scrollHeight)")
        self.page.size(SIZE[0], max(SIZE[1], h))
        time.sleep(0.4)
        shot = self.cdp.cmd("Page.captureScreenshot", format="png")
        self.page.size(*SIZE)
        self.js(f"window.scrollTo(0, {y}); 1")
        time.sleep(0.3)
        out = pathlib.Path(folder) / f"{self.label.split(' · ')[-1]}-{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(shot["data"]))

    def pimport(self) -> None:
        if not self.price_dir:
            raise SystemExit("стенд: файл импорта не приготовлен — сценарий pimport не прогнан")
        book = visits_book(self.price_dir, self.round)
        self.round += 1
        # место — от верха документа: щелчок прокручивает страницу к кнопке, а полоса шагов от этого не едет
        frame = ("() => { const st = document.querySelector('.pi .pi-steps'); const f = document.querySelector('.pi .pi-file');"
                 " if (!st) return null; const y = scrollY, r = st.getBoundingClientRect();"
                 " return [Math.round(r.top + y), Math.round(r.height), f ? Math.round(f.getBoundingClientRect().top + y) : null,"
                 " f ? f.offsetHeight : null]; }")
        self.page.go("/admin/patients/import")
        time.sleep(1.2)
        self.ok(self.js("!!document.querySelector('.pi .pi-pick')"), "импорт: экран открылся на шаге «Fișier»")
        self.shot("1-fisier")
        d = self.file_in(book, 2.5, frame, selector=".pi input[type=file]")
        steps = [s for s in d["samples"] if s]
        self.ok(self.js("!!document.querySelector('.pi .pi-preview')"), "импорт: файл прочитан — шаг «Coloane»")
        self.shot("2-coloane")
        seen = steps[-1:]
        d = self.tap(BY_TEXT.format(sel=".pi .pi-cols .dp-btn", text="Verifică"), 1.6, frame)
        seen += [s for s in d["samples"] if s and s[2] is not None]
        self.ok(self.js("!!document.querySelector('.pi .pi-docs')"), "импорт: незнакомый врач — шаг «Medici»")
        self.ok(self.js("Array.from(document.querySelectorAll('.pi-docs option')).some((o) => o.textContent === 'Fără medic — nu programa')"),
                "импорт, «Medici»: «Fără medic» с датой записи значит «не programa»")
        self.shot("3-medici")
        d = self.tap(BY_TEXT.format(sel=".pi .pi-docs .dp-btn", text="Continuă"), 1.0, frame)
        seen += [s for s in d["samples"] if s and s[2] is not None]
        self.ok(self.js("!!document.querySelector('.pi .pi-visits')"), "импорт: «Verificare» с блоком «Programări din fișier»")
        looks = sorted({tuple(x) for x in seen})
        self.ok(len(looks) == 1, f"импорт: полоса шагов и карточка файла на одном месте на каждом шаге ({looks[:3]})")

        # галочки и процедура: перепроверка файла, а галочка и всё выше блока на месте
        past = "document.querySelector('.pi .pi-visits input[type=checkbox]')"
        place = ("() => { const b = " + past + "; const v = document.querySelector('.pi .pi-visits');"
                 " const c = document.querySelector('.pi .pi-check > .pi-counts'); if (!b || !v) return null;"
                 " const r = b.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.left),"
                 " Math.round(v.getBoundingClientRect().top), c ? Math.round(c.getBoundingClientRect().top) : null]; }")
        self.js(f"{past}.scrollIntoView({{block: 'center'}}); 1")
        time.sleep(0.4)
        before = self.at(BY_TEXT.format(sel=".pi .pi-visits .pi-count", text="Programări noi"))
        seen = []
        reqs = []
        for _ in range(2):
            d = self.tap(past, 1.2, place)
            seen += d["samples"]
            reqs += [r["status"] for r in d["res"] if "/pimport/check" in r["name"]]
        sel = "document.querySelector('.pi .pi-visits .pi-svc select')"
        d = self.pick(sel, self.js(f"{sel}.options[1].value"), 1.2, place)
        seen += d["samples"]
        reqs += [r["status"] for r in d["res"] if "/pimport/check" in r["name"]]
        looks = sorted({tuple(x) for x in seen if x})
        self.ok(reqs == [200, 200, 200], f"импорт: галочки и процедура перепроверяют файл ({reqs})")
        # сдвиги раскладки НИЖЕ блока законны: ответ меняет группы визитов под галочками
        self.ok(len(looks) == 1,
                f"импорт: галочка, блок и счётчики выше на месте на каждом кадре перепроверки ({looks[:3]})")
        self.ok(before == self.at(BY_TEXT.format(sel=".pi .pi-visits .pi-count", text="Programări noi")),
                "импорт: счётчики визитов на месте после перепроверки")
        self.js("window.scrollTo(0, 0); 1")
        self.shot("4-verificare")

        # импорт: вопрос своим окном, итог со строкой визитов
        go = BY_TEXT.format(sel=".pi .pi-acts .dp-btn.pri", text="Importă")
        said = self.js(f"{go}.textContent")
        self.tap(go, 0.8)
        d = self.tap("Array.from(document.querySelectorAll('dialog.dp-ask button')).find((b) => b.textContent.trim() === 'Importă')", 3.0)
        runs = [r["status"] for r in d["res"] if "/pimport/run" in r["name"]]
        done = self.js("Array.from(document.querySelectorAll('.pi .pi-done .pi-done-n')).map((x) => x.textContent).join(' | ')")
        self.ok(bool(runs) and set(runs) == {200} and "programări puse" in (done or ""),
                f"импорт: «{said.strip()}» — порции {runs}, итог «{done}»")
        self.shot("5-final")


    # ---------- прайс и поиск услуги (20.11.2026) ----------

    def at(self, finder: str):
        """Прямоугольник без прокрутки к элементу: место там, где его видит человек."""
        v = self.js(f"(() => {{ const e = {finder}; if (!e) return null; const r = e.getBoundingClientRect();"
                    " return JSON.stringify([Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]) })()")
        return json.loads(v) if v else None

    def file_in(self, path: pathlib.Path, wait: float, sample: str = "", selector: str = "[data-testid=tf-file]") -> dict:
        """Файл в поле выбора окна импорта — как его кладёт системное окно выбора."""
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        doc = self.cdp.cmd("DOM.getDocument", depth=-1)
        node = self.cdp.cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)
        self.cdp.cmd("DOM.setFileInputFiles", files=[str(path)], nodeId=node["nodeId"])
        self.cdp.drain(wait)
        return self.take()

    def chars(self, text: str, wait: float, sample: str = "") -> dict:
        """Набор с клавиатуры по букве — как печатает человек (список меняет высоту на каждой)."""
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        for ch in text:
            self.cdp.cmd("Input.insertText", text=ch)
            time.sleep(0.04)
        self.cdp.drain(wait)
        return self.take()

    def tarife(self) -> None:
        if not self.price_dir:
            raise SystemExit("стенд: прайс не засеян — сценарий tarife не прогнан")
        m = self.cdp.cmd
        csv_file = price_csv(self.price_dir, self.round)
        rail = "document.querySelectorAll('.tf .dp-rail button.dp-ri')[{i}]"
        head = ("() => { const h = document.querySelector('.tf .st-head'); const t = document.querySelector('.tf .tf-tbl thead');"
                " const f = document.querySelector('.tf .tf-find input'); const r = f.getBoundingClientRect();"
                " return [h.offsetHeight, Math.round(t.getBoundingClientRect().top),"
                " Array.from(t.querySelectorAll('th')).map((x) => x.offsetWidth).join(','), Math.round(r.left), Math.round(r.width)]; }")
        self.tap("document.querySelector('a[href=\"/admin/tarife\"]')", 1.6)
        self.ok(self.js("location.pathname") == "/admin/tarife" and self.js("!!document.querySelector('.tf .tf-tbl')"),
                "прайс: экран открылся из меню")

        # 1. меню категорий: шапка, верх таблицы, ширины колонок и место поля поиска — одни
        seen, moved = [], []
        for i in (1, 2, 3, 0):
            before = self.at(rail.format(i=i))
            seen += self.tap(rail.format(i=i), 0.5, head)["samples"]
            moved.append(before == self.at(rail.format(i=i)))
        looks = sorted({tuple(s) for s in seen if s})
        self.ok(len(looks) == 1 and all(moved),
                f"прайс, меню: шапка, таблица и колонки одни во всех видах, пункт меню под курсором ({looks[:3]}, {moved})")
        # 2. поиск: поле не сужается с первой буквой и не растёт с пустым
        find = "document.querySelector('.tf .tf-find input')"
        seen = []
        for text in ("c", "coroana", "zzz", ""):
            seen += self.type_in(find, text, 0.35, head)["samples"]
        looks = sorted({tuple(s) for s in seen if s})
        self.ok(len(looks) == 1, f"прайс, поиск: поле, шапка и таблица на месте с числом найденного и без ({looks[:3]})")

        # 3. плитка ↔ правка: строка той же высоты, соседи и колонки на месте, «Gata» — на месте карандаша
        pen = "document.querySelectorAll('.tf tbody tr[data-row]:not(.tf-new) .tf-act .tf-pen')[2]"
        prow = "document.querySelectorAll('.tf tbody tr[data-row]:not(.tf-new)')[2]"
        pnext = f"{prow}.nextElementSibling"
        cols = "Array.from(document.querySelectorAll('.tf .tf-tbl thead th')).map((x) => x.offsetWidth).join(',')"
        self.js(f"{prow}.scrollIntoView({{block: 'center'}}); 1")
        time.sleep(0.3)
        p0, q0, c0, b0 = self.at(prow), self.at(pnext), self.js(cols), self.at(pen)
        d = self.tap(pen, 0.6)
        g0 = self.at(f"{prow}.querySelector('.tf-act .tf-pen')")
        opened = self.js(f"{prow}.classList.contains('tf-open') && !!{prow}.querySelector('input')")
        self.ok(opened and self.at(prow) == p0 and self.at(pnext) == q0 and self.js(cols) == c0 and not d["shifts"],
                f"прайс, карандаш: строка открыта той же высоты, соседняя и колонки на месте ({p0} → {self.at(prow)},"
                f" {q0} → {self.at(pnext)}, колонки {c0} → {self.js(cols)}, сдвиги {d['shifts']})")
        self.ok(g0 == b0, f"прайс, карандаш: «Gata» стоит на месте карандаша ({b0} → {g0})")
        d = self.tap(f"{prow}.querySelector('.tf-act .tf-pen')", 0.6)
        closed = self.js(f"!{prow}.classList.contains('tf-open') && !{prow}.querySelector('input')")
        self.ok(closed and self.at(prow) == p0 and self.at(pnext) == q0 and not d["shifts"],
                f"прайс, «Gata»: строка снова плитка той же высоты ({self.at(prow)}, сдвиги {d['shifts']})")
        # «Renunță» стоит в липкой полосе: `tap` прокручивает к ней страницу, поэтому место строк — от верха таблицы
        rel = ("(() => {{ const t = document.querySelector('.tf .tf-tbl').getBoundingClientRect();"
               " return [{r}, {n}].map((e) => {{ const b = e.getBoundingClientRect(); return [Math.round(b.top - t.top), Math.round(b.height)]; }}); }})()")
        self.tap(pen, 0.4)
        self.type_in(f"{prow}.querySelector('.tf-price')", str(777 + self.round), 0.3)
        r0 = self.js(rel.format(r=prow, n=pnext))
        d = self.tap(BY_TEXT.format(sel=".tf .tf-save button", text="Renunță"), 0.6)
        n_open = self.js("document.querySelectorAll('.tf tbody tr.tf-open').length")
        r1 = self.js(rel.format(r=prow, n=pnext))
        self.ok(n_open == 0 and r1 == r0 and not d["shifts"],
                f"прайс, «Renunță»: строки снова плитки, ничего не съехало (открытых {n_open}, от верха таблицы {r0} → {r1},"
                f" сдвиги {d['shifts']})")

        # 4. удаление строки: строка той же высоты, отмена — на месте корзины, ниже ничего не съезжает
        first = "document.querySelector('.tf tbody tr[data-row]:not(.tf-new):has(.tf-pen)')"
        self.js(f"{first}.scrollIntoView({{block: 'center'}}); 1")
        time.sleep(0.3)
        self.js("(() => { const r = Array.from(document.querySelectorAll('.tf tbody tr[data-row]:not(.tf-new)'))"
                ".find((x) => !x.querySelector('.tf-chip.mute')); r.querySelector('.tf-pen').click(); return 1; })()")
        time.sleep(0.4)
        trash = "document.querySelector('.tf tbody tr.tf-open .tf-del')"
        row = f"{trash}.closest('tr')"
        nxt = "document.querySelector('.tf tbody tr.tf-gone, .tf tbody tr.tf-open:has(.tf-del)').nextElementSibling"
        r0, n0, t0 = self.at(row), self.at(nxt), self.at(trash)
        self.tap(trash, 0.8)
        d = self.tap("Array.from(document.querySelectorAll('dialog.dp-ask button')).find((b) => b.textContent.includes('Șterge'))", 0.6)
        row = "document.querySelector('.tf tbody tr.tf-gone')"
        undo = f"{row}.querySelector('.tf-act .tf-undo')"
        u = self.at(undo)
        near = bool(u) and abs((u[0] + u[2] / 2) - (t0[0] + t0[2] / 2)) <= 2 and abs((u[1] + u[3] / 2) - (t0[1] + t0[3] / 2)) <= 2
        self.ok(self.at(row) == r0 and self.at(nxt) == n0 and not d["shifts"],
                f"прайс, удаление: строка той же высоты, следующая на месте ({r0} → {self.at(row)}, {n0} → {self.at(nxt)},"
                f" сдвиги {d['shifts']})")
        self.ok(near and u[0] + u[2] <= self.at(row)[0] + self.at(row)[2],
                f"прайс, удаление: отмена стоит на месте корзины и в строке целиком (корзина {t0}, отмена {u})")
        self.tap(undo, 0.4)
        # после отмены правки нет и полоса погашена (`inert`): строку закрывает её «Gata»
        self.js("document.querySelectorAll('.tf tbody tr.tf-open .tf-pen').forEach((b) => b.click()); 1")
        time.sleep(0.3)

        # 5. полоса записи: проявляется, у прокрученной до низа страницы запись ничего не сдвигает
        bar = "document.querySelector('.tf .tf-save')"
        last = "Array.from(document.querySelectorAll('.tf tbody tr[data-row] .tf-price')).at(-1)"
        lastpen = "Array.from(document.querySelectorAll('.tf tbody tr[data-row] .tf-pen')).at(-1)"
        look = ("() => { const b = " + bar + "; return b ? [Number(getComputedStyle(b).opacity), getComputedStyle(b).visibility,"
                " Math.round(b.getBoundingClientRect().top)] : null; }")
        self.js("window.scrollTo(0, document.documentElement.scrollHeight); 1")
        time.sleep(0.3)
        self.js(f"{lastpen}.click(); 1")
        time.sleep(0.4)
        n_open = self.js("document.querySelectorAll('.tf tbody tr.tf-open').length")
        d = self.type_in(last, str(4321 + self.round), 0.5, look)   # своё число у каждого прохода: иначе правки нет
        ops = [s[0] for s in d["samples"] if s and s[1] == "visible"]
        fade = [r for r in d["runs"] if "tf-save" in r["target"] and r["name"] == "opacity"]
        self.ok(bool(ops) and ops[0] < 0.5 and ops[-1] == 1 and bool(fade) and not d["shifts"],
                f"прайс, полоса записи: проявляется переходом с первой правкой ({ops[:1]} … {ops[-1:]}, переходов {len(fade)},"
                f" открытых строк {n_open})")
        self.js("window.scrollTo(0, document.documentElement.scrollHeight); 1")
        time.sleep(0.3)
        # строка, а не поле: после записи строка снова плитка, поля в ней нет — место то же
        lastrow = f"{last}.closest('tr')"
        self.js(f"window.__mcRow = {lastrow}; 1")
        lastrow = "window.__mcRow"
        y0, s0 = self.at(lastrow), self.js("Math.round(scrollY)")
        x, y = self.page.center(BY_TEXT.format(sel=".tf .tf-save button", text="Salvează"))
        self.js("__mc.sample = null; __mc.reset(); 1")
        for t in ("mousePressed", "mouseReleased"):
            m("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)
        self.cdp.drain(1.0)
        d = self.take()
        posts = [r["status"] for r in d["res"] if r["name"].startswith("/api/tarife")]
        self.ok(posts == [200] and self.at(lastrow) == y0 and self.js("Math.round(scrollY)") == s0 and not d["shifts"],
                f"прайс, запись внизу страницы: ничего не съехало (строка {y0} → {self.at(lastrow)}, прокрутка {s0} →"
                f" {self.js('Math.round(scrollY)')}, ответ {posts}, сдвиги {d['shifts']})")
        self.ok(self.js(f"(() => {{ const b = {bar}; return !b || getComputedStyle(b).visibility === 'hidden' }})()"),
                "прайс: после записи полосы не видно")
        self.js("window.scrollTo(0, 0); 1")
        time.sleep(0.3)

        # 6. окно категории: одной высоты с отказом и без; три закрытия гаснут
        cat = "document.querySelector('dialog.tf-dlg:not(.tf-imp)')"
        cbox = BOX.format(dlg=cat)
        ren = BY_TEXT.format(sel=".tf .rg-btn", text="Redenumește")
        self.tap(rail.format(i=1), 0.4)
        seen = self.tap(ren, 0.8, cbox)["samples"]
        seen += self.type_in(f"{cat}.querySelector('input')", "", 0.2, cbox)["samples"]
        seen += self.tap(BY_TEXT.format(sel="dialog.tf-dlg .rg-dlg-f button", text="Salvează"), 0.4, cbox)["samples"]
        said = self.js(f"{cat}.querySelector('.st-err').textContent")
        seen += self.type_in(f"{cat}.querySelector('input')", "Terapie", 0.2, cbox)["samples"]
        sizes = sorted({(s[0], s[1]) for s in seen if s and s[2]})
        self.ok(bool(said) and len(sizes) == 1, f"окно категории: место и высота одни с отказом «{said}» и без ({sizes})")
        self.fades("окно категории, Esc", cat, self.key("Escape", 27, 0.8, cbox))
        self.tap(ren, 0.8)
        self.fades("окно категории, крестик", cat, self.tap(f"{cat}.querySelector('.rg-x')", 0.8, cbox))
        self.tap(ren, 0.8)
        self.type_in(f"{cat}.querySelector('input')", f"Terapie {self.round}", 0.2)
        self.fades("окно категории, после записи", cat,
                   self.tap(BY_TEXT.format(sel="dialog.tf-dlg .rg-dlg-f button", text="Salvează"), 1.2, cbox))

        # 7. окно импорта: место и высота одни до файла, со сравнением и на каждой вкладке; вкладки не толкают соседей
        imp = "document.querySelector('dialog.tf-imp')"
        ibox = BOX.format(dlg=imp)
        btn = BY_TEXT.format(sel=".tf .rg-btn", text="Importă")
        self.tap(rail.format(i=0), 0.4)
        seen = self.tap(btn, 0.8, ibox)["samples"]
        seen += self.file_in(csv_file, 2.0, ibox)["samples"]
        tabs = f"{imp}.querySelectorAll('.tf-imp-tabs button')"
        n = self.js(f"{tabs}.length")
        self.ok(n == 4, f"окно импорта: файл проверен, вкладок сравнения {n}")
        # края вкладок — в долях пикселя: округление прямоугольника делает из 1/64 px целый пиксель
        edges = f"JSON.stringify(Array.from({tabs}).map((b) => {{ const r = b.getBoundingClientRect(); return [r.left, r.right]; }}).flat())"
        rows = []
        for i in (1, 2, 3, 0):
            seen += self.tap(f"{tabs}[{i}]", 0.35, ibox)["samples"]
            rows.append(json.loads(self.js(edges)))
        spread = max(max(col) - min(col) for col in zip(*rows))
        sizes = sorted({(s[0], s[1]) for s in seen if s and s[2]})
        self.ok(len(sizes) == 1, f"окно импорта: место и высота одни до файла, со сравнением и на вкладках ({sizes})")
        self.ok(spread < 0.5, f"окно импорта: нажатая вкладка не толкает соседей (края вкладок гуляют на {spread:.2f} px)")
        self.fades("окно импорта, Esc", imp, self.key("Escape", 27, 0.8, ibox))
        self.tap(btn, 0.8)
        self.fades("окно импорта, крестик", imp, self.tap(f"{imp}.querySelector('.rg-x')", 0.8, ibox))
        self.tap(btn, 0.8)
        self.file_in(csv_file, 2.0)
        d = self.tap(BY_TEXT.format(sel="dialog.tf-imp .rg-dlg-f button", text="Importă:"), 2.5, ibox)
        runs = [r["status"] for r in d["res"] if "/import/run" in r["name"]]
        self.ok(runs == [200], f"окно импорта: импорт прошёл ({runs})")
        self.fades("окно импорта, после импорта", imp, d)

        # 8. уход с правкой — вопрос своим окном, проявляется
        ask = ("() => { const d = document.querySelector('dialog.dp-ask'); return d && d.open ? Number(getComputedStyle(d).opacity) : null; }")
        self.js("document.querySelectorAll('.tf tbody tr[data-row] .tf-pen')[1].click(); 1")
        time.sleep(0.3)
        self.type_in("document.querySelectorAll('.tf tbody tr[data-row] .tf-price')[0]", "1111", 0.3)
        d = self.tap(BY_TEXT.format(sel="nav a, .side a", text="Pacienți"), 0.6, ask)
        ops = [s for s in d["samples"] if s is not None]
        self.ok(bool(ops) and ops[0] < 0.5 and ops[-1] == 1 and self.js("location.pathname") == "/admin/tarife",
                f"уход с правкой: вопрос проявляется, экран остался ({ops[:1]} … {ops[-1:]})")
        self.esc()
        time.sleep(0.5)

        # 9. без движения: полоса встаёт и уходит без перехода
        m("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        try:
            self.tap(BY_TEXT.format(sel=".tf .tf-save button", text="Renunță"), 0.4)
            self.js("document.querySelectorAll('.tf tbody tr[data-row] .tf-pen')[1].click(); 1")
            time.sleep(0.3)
            d = self.type_in("document.querySelectorAll('.tf tbody tr[data-row] .tf-price')[0]", "2222", 0.4, look)
            first = next((s for s in d["samples"] if s and s[1] == "visible"), None)
            slow = [r for r in d["runs"] if "tf-save" in r["target"] and r["dur"] > 0]
            self.ok(first is not None and first[0] == 1 and not slow,
                    f"без движения: полоса записи встаёт целиком с первого кадра ({first}, переходов {len(slow)})")
            self.tap(BY_TEXT.format(sel=".tf .tf-save button", text="Renunță"), 0.3)
            d = self.tap(btn, 0.4, ibox)
            first = next((s for s in d["samples"] if s), None)
            self.ok(first is not None and first[3] == 1, f"без движения: окно импорта стоит целиком с первого кадра ({first})")
            d = self.key("Escape", 27, 0.3, ibox)
            self.ok(self.js(f"{imp} === null") and not [r for r in d["runs"] if r["dur"] > 0 and r["target"].startswith("dialog")],
                    "без движения: окно импорта ушло из дерева без перехода")
        finally:
            m("Emulation.setEmulatedMedia", features=[])

        # 10. «Setări › Servicii»: плитка ↔ правка карандашом — строка той же высоты, соседняя на месте, «Gata» там же
        self.page.go("/admin/settings/services")
        time.sleep(1.2)
        srow = "document.querySelectorAll('.dp-react-root table.set tbody tr')[1]"
        snext = f"{srow}.nextElementSibling"
        spen = f"{srow}.querySelector('td.sv-act .sv-ib')"
        self.js(f"{spen}.scrollIntoView({{block: 'center'}}); 1")   # `tap` ставит кнопку в центр сам — до замера
        time.sleep(0.3)
        s0, t0, b0 = self.at(srow), self.at(snext), self.at(spen)
        d = self.tap(spen, 0.6)
        opened = self.js(f"!!{srow}.querySelector('input[type=text]')")
        self.ok(opened and self.at(srow) == s0 and self.at(snext) == t0 and self.at(spen) == b0 and not d["shifts"],
                f"Setări › Servicii, карандаш: строка открыта той же высоты, соседняя и кнопка на месте ({s0} → {self.at(srow)},"
                f" {t0} → {self.at(snext)}, {b0} → {self.at(spen)}, сдвиги {d['shifts']})")
        d = self.tap(spen, 0.6)
        self.ok(self.js(f"!{srow}.querySelector('input[type=text]')") and self.at(srow) == s0 and not d["shifts"],
                f"Setări › Servicii, «Gata»: строка снова плитка той же высоты ({self.at(srow)}, сдвиги {d['shifts']})")
        self.round += 1

    def picker(self) -> None:
        if not self.pid:
            raise SystemExit("стенд: фиша с планом не засеяна — сценарий picker не прогнан")
        lst = ("() => {{ const f = {field}; const l = document.querySelector('.dp-svc-list'); const d = f.closest('dialog');"
               " const a = f.getBoundingClientRect(); const b = l ? l.getBoundingClientRect() : null;"
               " return [Math.round(a.top), Math.round(a.left), b ? Math.round(b.top - a.bottom) : null, b ? Math.round(b.height) : 0,"
               " d ? d.offsetTop : -1, d ? d.offsetHeight : -1]; }}")

        def clear(field: str) -> None:
            self.type_in(field, "", 0.2)
            self.js("document.activeElement && document.activeElement.blur(); 1")
            time.sleep(0.2)

        def drive(where: str, field: str) -> None:
            """Щелчок, ↓, набор (список меняет высоту), Esc, набор и Enter: поле, окно и список на местах."""
            s = lst.format(field=field)
            clear(field)
            seen = self.tap(field, 0.4, s)["samples"]
            seen += self.key("ArrowDown", 40, 0.25, s)["samples"]
            seen += self.chars("coroana", 0.4, s)["samples"]
            grew = sorted({x[3] for x in seen if x and x[2] is not None})
            d = self.key("Escape", 27, 0.3, s)
            seen += d["samples"]
            esc_ok = self.js("!!document.querySelector('.dp-svc-list')") is False and (
                where == "фиша" or where == "шаблон" or self.js(f"!!{field}.closest('dialog[open]')"))
            clear(field)
            self.tap(field, 0.3)
            seen += self.chars("coroana zirc", 0.3, s)["samples"]
            seen += self.key("Enter", 13, 0.5, s)["samples"]
            picked = self.js(f"{field}.value")
            frames = [x for x in seen if x]
            places = sorted({(x[0], x[1], x[4], x[5]) for x in frames})
            gaps = sorted({x[2] for x in frames if x[2] is not None})
            self.ok(len(places) == 1, f"поиск услуги, {where}: поле и окно на месте весь сеанс (поле, окно: {places[:3]})")
            self.ok(len(grew) > 1 and len(gaps) == 1 and 0 <= gaps[0] <= 8,
                    f"поиск услуги, {where}: список меняет высоту ({grew[:4]}) и стоит под полем ({gaps})")
            self.ok(esc_ok and picked == "Coroană din zirconiu",
                    f"поиск услуги, {where}: Esc закрыл только список, Enter выбрал строку («{picked}»)")

        # уход со страницы с черновиком спрашивал бы Edge (beforeunload) — сценарий не о нём
        hook = self.cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=NO_UNLOAD)["identifier"]
        try:
            self._picker(drive)
        finally:
            self.cdp.cmd("Page.removeScriptToEvaluateOnNewDocument", identifier=hook)

    def _picker(self, drive) -> None:
        # 1. форма плана фиши
        self.page.go(f"/admin/patient/{self.pid}?tab=plan")
        time.sleep(0.8)
        self.tap("document.querySelector('.plan-add > button')", 0.6)
        drive("фиша", "document.querySelector('.dp-svc input')")
        # 2. «Editează procedura»
        edit = "document.querySelector('dialog.dp-plan-edit')"
        self.tap("document.querySelector('.plan-row .pact .dp-more')", 0.5)
        self.tap(BY_TEXT.format(sel=".dp-cmenu [role=menuitem]", text="Editează"), 0.8)
        drive("«Editează procedura»", f"{edit}.querySelector('.dp-svc input')")
        self.esc()
        time.sleep(0.6)
        # 3. «Adaugă în plan · dintele 36» с одонтограммы
        self.page.go(f"/admin/patient/{self.pid}/odontograma")
        time.sleep(1.4)
        self.tap("document.querySelector('.odop .arch .tooth-btn[data-n=\"36\"]')", 0.5, button="right")
        self.tap(BY_TEXT.format(sel=".dp-cmenu [role=menuitem]", text="Adaugă în plan"), 0.8)
        drive("окно с зуба", "document.querySelector('dialog.dp-plan-dlg .dp-svc input')")
        self.esc()
        time.sleep(0.6)
        # 4. строка шаблона в «Setări › Șabloane › Plan de tratament»
        self.page.go("/admin/settings/templates?tab=plan")
        time.sleep(1.0)
        drive("шаблон", "document.querySelectorAll('.pt-table .dp-svc input')[1]")
        # 5. окно в стиле Sticlă: у окна backdrop-filter, и `fixed` внутри него считался бы от окна —
        #    список уезжал на высоту окна вниз и резался краем. Прогон стилем Clar этого не видит, поэтому
        #    окно правки здесь проходится и в Sticlă (стиль возвращается прежним).
        was = self.js("document.documentElement.dataset.style")
        if was != "sticla":
            theme = {"primary": "#0E9F8A", "custom": "", "menu": "soft"}
            r = self.client.post_json("/api/settings/theme", {"style": "sticla", **theme})
            try:
                self.ok(r.msg == "ok_theme", f"поиск услуги: стиль Sticlă включён ({r.msg})")
                self.page.go(f"/admin/patient/{self.pid}?tab=plan")
                time.sleep(0.8)
                self.tap("document.querySelector('.plan-row .pact .dp-more')", 0.5)
                self.tap(BY_TEXT.format(sel=".dp-cmenu [role=menuitem]", text="Editează"), 0.8)
                drive("«Editează procedura» в Sticlă", f"{edit}.querySelector('.dp-svc input')")
                self.esc()
                time.sleep(0.6)
            finally:
                self.client.post_json("/api/settings/theme", {"style": was or "clar", **theme})

    def patient(self) -> None:
        """Выбор фиши в окнах записи: «Recenți», поиск, ↓, Esc, Enter, «Alt pacient», совпавший
        номер — окно не двигается и не меняет высоту ни в одном состоянии, список стоит под полем
        в верхнем слое; в Clar и Sticlă, в окне шапки и в окне свободного часа."""
        smp = ("() => { const d = document.querySelector('dialog[open]'); if (!d) return null;"
               " const f = d.querySelector('.dp-pick-chip, span.dp-pick:not(.has-pill) > input[role=combobox],"
               " span.dp-pick > input[role=combobox]'); const l = document.querySelector('.dp-pick-list');"
               " const a = f ? f.getBoundingClientRect() : null; const b = l ? l.getBoundingClientRect() : null;"
               " return [d.offsetTop, d.offsetHeight, a && b ? Math.round(b.top - a.bottom) : null,"
               " l ? l.matches(':popover-open') : null]; }")
        name = "document.querySelector('dialog[open] input[role=combobox]')"
        phone = "document.querySelector('dialog[open] input[placeholder=\"Telefon\"]')"

        def drive(where: str, opener: str) -> None:
            seen = self.tap(opener, 0.9, smp)["samples"]
            seen += self.tap(name, 0.8, smp)["samples"]
            recent = self.js("!!document.querySelector('.dp-pick-list .dp-pick-head')")
            seen += self.chars("proba", 0.8, smp)["samples"]
            seen += self.key("ArrowDown", 40, 0.3, smp)["samples"]
            seen += self.key("Escape", 27, 0.3, smp)["samples"]
            esc_ok = self.js("!document.querySelector('.dp-pick-list') && !!document.querySelector('dialog[open]')")
            seen += self.key("ArrowDown", 40, 0.5, smp)["samples"]
            seen += self.key("Enter", 13, 0.5, smp)["samples"]
            chip = self.js("(() => { const c = document.querySelector('dialog[open] .dp-pick-chip'); return c ? c.getAttribute('aria-label') : ''; })()")
            seen += self.tap("document.querySelector('dialog[open] .dp-pick-x')", 0.5, smp)["samples"]
            seen += self.tap(phone, 0.3, smp)["samples"]
            seen += self.chars("069770001", 1.2, smp)["samples"]
            pill = self.js("(() => { const b = document.querySelector('dialog[open] .dp-pick-pill'); return b ? b.textContent : ''; })()")
            frames = [x for x in seen if x]
            places = sorted({(x[0], x[1]) for x in frames})
            gaps = sorted({x[2] for x in frames if x[2] is not None})
            tops = {x[3] for x in frames if x[3] is not None}
            self.ok(len(places) == 1, f"выбор фиши, {where}: окно на месте и одной высоты весь сеанс ({places[:4]})")
            self.ok(recent and bool(gaps) and all(0 <= g <= 8 for g in gaps) and tops == {True},
                    f"выбор фиши, {where}: «Recenți» и поиск — список под полем ({gaps}) в верхнем слое ({tops})")
            self.ok(esc_ok and chip.startswith("Proba Miscare"),
                    f"выбор фиши, {where}: Esc закрыл только список, Enter выбрал фишу («{chip}»)")
            self.ok(pill.startswith("Fișă existentă: Proba Miscare 1"), f"выбор фиши, {where}: совпавший номер подсказан («{pill}»)")
            self.esc()
            time.sleep(0.6)

        was = self.js("document.documentElement.dataset.style") or "clar"
        theme = {"primary": "#0E9F8A", "custom": "", "menu": "soft"}
        try:
            for style in dict.fromkeys((was, "sticla")):
                if style != was:
                    r = self.client.post_json("/api/settings/theme", {"style": style, **theme})
                    self.ok(r.msg == "ok_theme", f"выбор фиши: стиль {style} включён ({r.msg})")
                self.home()
                drive(f"окно шапки · {style}", "document.querySelector('.top .newbtn')")
                self.home()
                drive(f"окно свободного часа · {style}",
                      "Array.from(document.querySelectorAll('.gcell[data-free=\"all\"]:not([disabled])')).at(-1)")
        finally:
            if was != "sticla":
                self.client.post_json("/api/settings/theme", {"style": was, **theme})

    def scenario(self, name: str, polls: int) -> None:
        print(f"[{self.label}] {name}")
        self.home()
        self.idle(polls) if name == "idle" else getattr(self, name)()


def seed_start(now: datetime, day: list[int] | None, hours: int) -> int:
    """Первый час засева: самое РАННЕЕ окно из `hours` часовых записей внутри рабочего
    дня клиники `day` = [открытие, закрытие], где начало каждой записи не ближе двух
    часов от `now` (у режима стилей, `hours` > 3, — часа: покой он не меряет, а шесть
    часов с зазором в два после полудня в день 7–21 не влезают). Раннее — значит у
    верха сетки: щелчок по блоку почти не прокручивает страницу, и раскладка экрана
    одна в любой час запуска.
    ⛔ Окна нет (выходной, короткий день) — отказ словами: стенд НЕ прогнан, а не зелёный."""
    if not day:
        raise SystemExit(f"засев: {now:%d.%m} у клиники выходной — записать некуда, стенд не прогнан")
    t = now.hour + now.minute / 60
    gap = 2 if hours <= 3 else 1
    for h0 in range(day[0], day[1] - hours + 1):
        if all(abs(h - t) >= gap for h in range(h0, h0 + hours)):
            return h0
    raise SystemExit(f"засев: в часах клиники {day[0]}–{day[1]} нет {hours} ч записей не ближе {gap} ч"
                     f" от {now:%H:%M} — стенд не прогнан")


def seed(c: Client, clinic: pathlib.Path, hours: int = 3) -> None:
    """Записи на сегодня (по три врача на час), не ближе двух часов от «сейчас»: в
    покое у них нет ни минутных порогов, ни прошедшего на глазах начала. Режим
    стилей сеет больше часов — сценарии статуса проходят по записям в каждом стиле.
    Часы — из `clinic.json` сервера (`seed_start`)."""
    now = datetime.now(TZ)
    week = json.loads(clinic.read_text(encoding="utf-8"))["hours"]
    h0 = seed_start(now, week.get(("mon", "tue", "wed", "thu", "fri", "sat", "sun")[now.weekday()]), hours)
    print(f"  засев: {hours} ч с {h0:02d}:00 (сейчас {now:%H:%M})")
    day = now.date().isoformat()
    n = 0
    for dh in range(hours):
        for dk in ("d2", "d3", "d4"):
            n += 1
            r = c.post_json("/api/schedule/appointments", {
                "date": day, "time": f"{h0 + dh:02d}:00", "doctor": dk, "service": "pain",
                "name": f"Proba Miscare {n}", "phone": f"06977{n:04d}"})
            if r.status != 200:
                raise SystemExit(f"засев не удался ({h0 + dh:02d}:00 {dk}): {r.status} {r.body[:120]}")


def seed_link(s1: Server) -> None:
    """Premium 2а до старта сервера: файл лицензии с правом `sms_link` (ключ прогона) и галочки ссылки и
    плашки ответов в clinic.json — как у клиники Premium, включившей их на экране SMS."""
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg["sms"] = {**(cfg.get("sms") or {}), "link": {"confirm": True, "notify": True}}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    plink_license(s1.dir, {"url": "http://127.0.0.1:9/", "token": "stand-" + "z" * 40}, {"sms_link": 400})


def seed_plan(c: Client) -> tuple[int, str]:
    """Фиша с планом лечения и шаблоны плана клиники — путём клиники; id фиши и имя
    услуги прайса с ценой одним числом (под ней окно правки показывает подсказку)."""
    r = c.post_json("/api/settings/plan-templates", {"new": PLAN_TPLS})
    if r.msg != "ok_set":
        raise SystemExit(f"засев: шаблоны плана не сохранились: {r.status} {r.body[:160]}")
    pid = new_patient(c, "Proba Plan Miscare", "069778800")
    for body in ({"procedure": "Coroană de probă", "tooth": "26", "price": "3000"},
                 {"procedure": "Detartraj de probă", "price": "700"}):
        r = c.post_json(f"/api/patients/{pid}/plan", body)
        if r.status != 200:
            raise SystemExit(f"засев: позиция плана не записалась: {r.status} {r.body[:160]}")
    priced = [s["label"] for s in json.loads(r.body)["data"]["appoint"]["services"] if s["price"] is not None]
    if not priced:
        raise SystemExit("засев: в прайсе клиники нет услуги с ценой одним числом — сценарий plan не прогнан")
    return pid, priced[0]


# Прайс засева: категории и строки «только план» — путём клиники (POST /api/tarife).
TARIFE_CATS = {
    "Terapie": [f"Restaurare pe {n} suprafețe – {m}" for m in ("compozit", "fluid", "ionomer") for n in (1, 2, 3)],
    "Endodonție": [f"Tratament endodontic – {n} canale" for n in (1, 2, 3, 4)] + ["Pansament calmant", "Ax radicular"],
    "Protetică": [f"Coroană {m}" for m in ("din zirconiu", "metalo-ceramică", "E.max", "provizorie", "telescopică")],
    "Chirurgie": [f"Extracție {m}" for m in ("monoradicular", "pluriradicular", "molar de minte", "rest radicular")],
}
# Окна, стоящие на странице с черновиком, спрашивали бы Edge при уходе: сценарию поиска услуги это не нужно.
NO_UNLOAD = ("(() => { const add = window.addEventListener; window.addEventListener = function (t, ...r) {"
             " if (t === 'beforeunload') return; return add.call(this, t, ...r); }; })()")


def seed_tarife(c: Client) -> None:
    cats = [{"key": f"k{i}", "name": n} for i, n in enumerate(TARIFE_CATS)]
    new = [{"ro": ro, "ru": "", "price": str(300 + 50 * j), "cat": f"k{i}"}
           for i, rows in enumerate(TARIFE_CATS.values()) for j, ro in enumerate(rows)]
    new.append({"ro": "Consultație de probă fără categorie", "ru": "", "price": "150", "cat": ""})
    r = c.post_json("/api/tarife", {"cats_new": cats, "new": new})
    if r.status != 200:
        raise SystemExit(f"засев: прайс не записался: {r.status} {r.body[:160]}")


def price_csv(folder: pathlib.Path, n: int) -> pathlib.Path:
    """Файл импорта: новые строки в новых категориях, две изменённые цены, две строки с ошибкой.
    Имена — свои у каждого прохода: второй стиль импортирует снова, а не «нечего импортировать»."""
    rows = ["Categoria;Denumire;Preț"]
    for k, cat in enumerate(("Igienă", "Ortodonție", "Radiologie")):
        rows += [f"{cat} {n};Procedură de import {n}.{k}.{i};{100 + 10 * i}" for i in range(14)]
    rows += [f"Terapie;{TARIFE_CATS['Terapie'][0]};{555 + n}", f"Chirurgie;{TARIFE_CATS['Chirurgie'][0]};{666 + n}"]
    rows += [";;100", f"Igienă {n};;200"]
    path = folder / f"pret-{n}.csv"
    path.write_text("".join(r + chr(10) for r in rows), encoding="utf-8")
    return path


def visits_book(folder: pathlib.Path, n: int) -> pathlib.Path:
    """Файл импорта с записями: 48 пациентов на неделю вперёд и в прошлом, три врача клиники и
    незнакомый (шаг «Medici»), строки без часа, пересечение у одного врача. Имена и телефоны — свои у
    каждого прохода: второй стиль импортирует снова, а не «există deja»."""
    import pimport_samples as S
    from datetime import date as _date, time as _time, timedelta as _td
    today = datetime.now(TZ).date()
    docs = ["Activ Doi", "Activ Trei", "Activ Patru", "Popescu"]
    rows = [["Nume", "Telefon", "Data programării", "Ora", "Medic", "Procedură"]]
    for i in range(48):
        day = today + _td(days=7 + i % 5) if i % 6 else today - _td(days=40 + i)
        hour = None if i % 9 == 4 else (4, _time(8 + (i // 4) % 10, 30 * (i % 2)))
        rows.append([f"Importescu{n} Pacient{i}", f"0697{n % 10}{i:04d}", (1, _date(day.year, day.month, day.day)),
                     hour, docs[i % 4], "Consultație" if i % 3 else None])
    path = folder / f"programari-{n}.xlsx"
    path.write_bytes(S.timed_book(rows))
    return path


def broken_tree(css: str = "", patch: tuple[str, str, str] | None = None, swap: tuple[str, str] | None = None) -> pathlib.Path:
    """Копия `bot/` со сломанным правилом: дописка в конец panel.css, замена в
    panel.css (`swap`) или замена в файле движка (`patch`: путь, было, стало).
    ⛔ Правится КОПИЯ; чего ломать уже нет — стенд устарел вместе с кодом."""
    dst = pathlib.Path(tempfile.mkdtemp(prefix="dp_motion_")) / "bot"
    shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    sheet = dst / "app" / "static" / "css" / "panel.css"
    if swap:
        text = sheet.read_text(encoding="utf-8")
        if swap[0] not in text:
            raise SystemExit(f"пара: в panel.css нет {swap[0]!r} — стенд устарел вместе с CSS")
        sheet.write_text(text.replace(swap[0], swap[1], 1), encoding="utf-8", newline="")
    if css:
        with open(sheet, "ab") as f:
            f.write(("\n" + css + "\n").encode("utf-8"))
    if patch:
        p = dst / patch[0]
        text = p.read_text(encoding="utf-8")
        if patch[1] not in text:
            raise SystemExit(f"пара: в {patch[0]} нет {patch[1]!r} — стенд устарел вместе с кодом")
        p.write_text(text.replace(patch[1], patch[2], 1), encoding="utf-8", newline="")
    return dst


# (сценарий, чем сломано, как сломать) — каждая обязана покраснеть СВОИМ сценарием
PAIRS = [
    ("idle", "«сейчас» в конверте канала", {"patch": (
        "app/core/api.py", 'out = {"screen": screen, "date": d.isoformat(), "live": state is not None}',
        'out = {"screen": screen, "date": d.isoformat(), "live": state is not None, "now": __import__("time").time()}')}),
    ("idle", "бесконечный пульс цифры вкладки", {"css": "@keyframes mc-pulse{50%{opacity:.6}}.fl-tab b{animation:mc-pulse 1s infinite}"}),
    ("dialog", "окно без перехода", {"css": "dialog[open]{transition:none !important}"}),
    ("answer", "галочка «Vin» без движения", {"css": ".gappt.vin .gvin{animation:none !important}"}),
    ("answer", "плашка ответа без затухания", {"css": ".toastbox .dp-ans-w{transition:none !important}"}),
    ("status", "вид выключенной кнопки без задержки", {"css": ".savebtn.ag-next:disabled,.dk-btn:disabled,.dp-free-btn:disabled{transition:none !important}"}),
    ("menu", "меню без перехода", {"css": ".dp-cmenu{transition:none !important}"}),
    ("toast", "въезд ответа снова под .anim", {"swap": (" .toastbox .banner{animation:dp-toast .3s ease both}",
                                                         " .anim .toastbox .banner{animation:dp-toast .3s ease both}")}),
    ("reduce", "появление окна без охраны reduced-motion", {"css": "dialog[open]{transition:opacity var(--dur-fast) ease !important}"
                                                               "@starting-style{dialog[open]{opacity:0}}"}),
    ("leave", "смыкание выключено", {"css": ".fl-list{--motion-flip:none}"}),
    ("leave", "призрака ушедшей строки нет", {"css": ".fl-row.leaving{display:none !important}"}),
    ("close", "окно без затухания", {"css": "dialog{transition:none !important}"}),
    ("close", "окно модально, пока гаснет", {"js": "document.addEventListener('cancel', (e) => { if (e.target.tagName === 'DIALOG')"
                                                " { e.preventDefault(); setTimeout(() => e.target.close(), 200); } }, true);"}),
    ("close", "меню не гаснет", {"css": ".dp-cmenu.out{opacity:1 !important}"}),
    ("close", "плашка не гаснет", {"css": ".toastbox.out{opacity:1 !important}"}),
    ("move", "переезд блока выключен", {"css": ".gridbody{--motion-flip:none}"}),
    ("stats", "графики Statistici без проявления", {"css": ".dp-react-root.anim .spark{animation:none !important}"}),
    ("stats", "столбцы Statistici не растут", {"css": ".anim .stx-bar{animation:none !important}"}),
    ("stats", "вход Statistici играет и на смене периода", {"css": ".stx-bar{animation:stx-grow-y .55s both !important}"}),
    ("print", "призрак строки на листе", {"css": "@media print{.fl-row.leaving{display:flex !important;animation:fl-out 9s both !important}}"}),
    ("plan", "хозяин снимает окно в кадре закрытия", {"js": "(() => { const real = window.matchMedia.bind(window);"
                                                         " window.matchMedia = (q) => (/prefers-reduced-motion/.test(q)"
                                                         " ? { matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},"
                                                         " addListener() {}, removeListener() {}, dispatchEvent: () => false } : real(q)); })();"}),
    ("plan", "высота окна шаблона по содержимому", {"css": ".dp-react-root .dp-plan-tpl .tp-win{height:auto !important}"
                                                        ".dp-react-root .dp-plan-tpl .tp-warn[aria-hidden]{display:none !important}"}),
    ("plan", "подсказка прайса в окне правки без места", {"css": ".dp-react-root .dp-plan-edit .pe-note{min-height:0 !important}"}),
    ("plan", "гаснущее окно на листе", {"css": "@media print{dialog:not([open]){display:block !important}}"}),
    ("tile", "подъём на :hover вместо пометки", {"css": ".gappt:not(:hover){translate:none !important}"
                                                      ".gappt:hover{translate:0 var(--lift-block) !important}"}),
    ("tile", "блок не поднимается", {"css": ".gappt[data-hov]{translate:none !important}"}),
    ("tile", "в миг хвата блок не на своём месте", {"css": ".gridbody[data-dragging] .gappt{translate:0 -9px !important}"}),
    ("tile", "окно не сворачивается в блок", {"css": "dialog[data-grow]:not([open]){transform:none !important}"}),
    ("tile", "окно уходит без своего перехода", {"css": "dialog[data-grow]:not([open]){transition:transform var(--dur-fast) ease !important}"}),
    ("tile", "клиенту сказано «движения нет»", {"js": "(() => { const real = window.matchMedia.bind(window);"
                                                   " window.matchMedia = (q) => (/prefers-reduced-motion/.test(q)"
                                                   " ? { matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},"
                                                   " addListener() {}, removeListener() {}, dispatchEvent: () => false } : real(q)); })();"}),
    ("event", "вспышки «a venit» нет", {"css": ".gappt.moved[data-st=\"waiting\"] .gfx{animation:none !important}"}),
    ("event", "пульс «în cabinet» без конца", {"css": ".gappt[data-st=\"arrived\"] .gfx::before{content:'';position:absolute;left:0;"
                                                    "top:0;bottom:0;width:6px;background:var(--bar);"
                                                    "animation:g-beat .44s ease-in-out infinite !important}"}),
    ("event", "завершённый блок не переворачивается", {"css": ".gappt.moved[data-st=\"done\"]{animation:dp-moved-g 1.2s ease !important}"}),
    ("event", "переворот на листе", {"css": "@media print{.gappt.moved[data-st=\"done\"]{animation:g-flip 9s !important}}"}),
    ("agenda", "нажатая кнопка вида шире — соседняя сдвигается", {"css": ".ag-view button::after{content:none !important}"}),
    ("agenda", "переключатель вида у свёрнутого блока", {"css": ".dp-react-root .agenda.dp-fold:not([open]) > summary .ag-view"
                                                             "{display:inline-flex !important}"}),
    ("focus", "клиент не снимает фокус с открывшего окно", {"js": "HTMLElement.prototype.blur = function () {};"}),
    ("pimport", "подсказки блока визитов прячутся на время проверки", {"css": ".pi[aria-busy=true] .pi-visits > .hint"
                                                                         "{display:none !important}"}),
    ("pimport", "полоса шагов выше на шаге «Medici»", {"css": ".pi:has(.pi-docs) .pi-steps{margin-top:12px !important}"}),
    ("tarife", "окно импорта по содержимому", {"css": "dialog.tf-imp .rg-dlg-b{height:auto !important}"}),
    ("tarife", "нажатая вкладка импорта шире", {"css": "dialog.tf-imp .tf-imp-tabs>button::after{content:none !important}"}),
    ("tarife", "поле поиска забирает свободное место ряда", {"css": ".tf .tf-find{flex:1 1 220px !important}"}),
    ("tarife", "число найденного в потоке, без места", {"css": ".tf .tf-find{display:flex !important;gap:8px}"
                                                      ".tf .tf-find>span{position:static !important;translate:none !important}"
                                                      ".tf .tf-find>span:empty{display:none !important}"
                                                      ".tf .tf-find .dp-fld{padding-right:12px !important}"}),
    ("tarife", "полоса записи снимается без правки", {"css": ".tf .tf-save.off{display:none !important}"}),
    ("tarife", "полоса записи без перехода", {"css": ".tf .tf-save{transition:none !important}"}),
    ("tarife", "пометка удаления строкой под именем", {"css": ".tf .tf-tbl tr.tf-gone td:first-child::after"
                                                       "{content:'se șterge la salvare';display:block;font-size:12px}"}),
    ("tarife", "отмена удаления шире корзины", {"css": ".tf .tf-tbl .rg-ib.tf-undo{width:auto !important}"
                                                  ".tf .tf-tbl .rg-ib.tf-undo::after{content:' Anulează';font-size:13px}"}),
    ("tarife", "плитка ниже строки правки", {"css": ".tf .tf-val{height:auto !important;line-height:1.2 !important}"
                                              ".tf .tf-tbl tr:not(.tf-open) td.tf-act>*{height:22px !important}"}),
    ("tarife", "в правке у строки одна кнопка вместо двух мест", {"css": ".tf .tf-tbl tr.tf-open td.tf-act>.tf-pen{display:none !important}"}),
    ("tarife", "плитка Setări без галочек врачей", {"css": "table.set .dp-svc-docs input:disabled{display:none !important}"}),
    ("tarife", "строка отказа окна категории без места", {"css": "dialog.tf-dlg .st-err:empty{display:none !important}"}),
    ("tarife", "полоса записи проявляется и без движения", {"css": ".tf .tf-save{transition:opacity .15s ease !important}"}),
    ("picker", "подсказка прайса в окне с зуба без места", {"css": "dialog.dp-plan-dlg .pd-note{min-height:0 !important}"}),
    ("picker", "список услуг в потоке окна", {"css": ".dp-svc-list{position:static !important}"}),
    ("picker", "список услуг не в верхнем слое", {"js": "delete HTMLElement.prototype.showPopover;"}),
    ("patient", "плашка выбранной фиши выше поля", {"css": ".dp-pick-chip{height:auto !important;padding:10px !important}"}),
    ("patient", "дата рождения при выбранной фише снята без места", {"css": ".dp-pick-off{display:none !important}"}),
    ("patient", "список фиш не в верхнем слое", {"js": "delete HTMLElement.prototype.showPopover;"}),
]


def run_tree(cdp: CDP, bot: pathlib.Path | None, label: str, names, polls: int, styles=(), js: str = "") -> tuple[int, list[str]]:
    """js — скрипт, который ломает КЛИЕНТ на каждой новой странице этого прогона (пара
    без копии дерева); снимается по выходе — сессия CDP одна на все прогоны."""
    answer = "answer" in names
    s1 = Server(keep_dir=True, **({"bot": bot} if bot else {}), **({"env": dict(KEY_ENV)} if answer else {}))
    if answer:
        seed_link(s1)
    hook = None
    try:
        if js:
            hook = cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=js)["identifier"]
        with s1:
            c = Client(s1.url).login()
            seed(c, s1.clinic, 6 if styles else 3)
            run = Run(cdp, s1.url, label, c, datetime.now(TZ).date().isoformat())
            run.data_dir = s1.dir
            if "plan" in names or "picker" in names:
                run.pid, run.listed = seed_plan(c)
            if "tarife" in names or "picker" in names:
                seed_tarife(c)
            if "tarife" in names or "picker" in names or "pimport" in names:
                run.price_dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_motion_csv_"))
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=OPEN_AGENDA)
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=INSTR)
            if styles:
                for style in styles:
                    r = c.post_json("/api/settings/theme", {"style": style, "primary": "#0E9F8A", "custom": "", "menu": "soft"})
                    if r.msg != "ok_theme":
                        raise SystemExit(f"стиль {style} не сохранился: {r.msg}")
                    run.label = f"{label} · {style}"
                    # названные ключом --only сценарии — в каждом стиле; без него — набор стилей
                    for name in (names if len(names) < len(SCENARIOS) else STYLE_SCENARIOS):
                        run.scenario(name, polls)
            else:
                for name in names:
                    run.scenario(name, polls)
            errs = cdp.errors()
            run.ok(not errs, f"ошибок консоли нет ({errs[:3]})")
            return run.n, run.bad
    finally:
        if hook:
            cdp.cmd("Page.removeScriptToEvaluateOnNewDocument", identifier=hook)
        s1.drop()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", action="store_true")
    ap.add_argument("--styles", default="")
    ap.add_argument("--polls", type=int, default=3)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    names = [n for n in SCENARIOS if not a.only or n in a.only.split(",")]
    styles = [s for s in a.styles.split(",") if s]
    profile = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "dp-edge-motion-check")
    shutil.rmtree(profile, ignore_errors=True)
    proc, ws = start_edge(profile, port=PORT)
    blind: list[str] = []
    ran = 0
    try:
        cdp = CDP(ws)
        for dom in ("Page", "Runtime", "Network"):
            cdp.cmd(f"{dom}.enable")
        cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
        total, bad = run_tree(cdp, None, "дерево", names, a.polls, styles)
        print(f"\n{'OK ' if not bad else 'RED'} дерево: {total - len(bad)}/{total}" + ("" if not bad else " — " + "; ".join(bad[:6])))
        if a.pair:
            for name, what, how in PAIRS:
                if a.only and name not in a.only.split(","):
                    continue
                ran += 1
                how = dict(how)
                js = how.pop("js", "")
                copy = broken_tree(**how) if how else None
                try:
                    _n, red = run_tree(cdp, copy, f"пара · {what}", [name], min(a.polls, 2), js=js)
                finally:
                    if copy:
                        shutil.rmtree(copy.parent, ignore_errors=True)
                seen = bool(red)
                print(f"пара {name}: {what} — {'видна (красное: ' + red[0][:90] + ')' if seen else 'НЕ ВИДНА — стенд слеп'}\n")
                if not seen:
                    blind.append(f"{name}: {what}")
    finally:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    okay = not bad and not blind
    tail = f"движение: {total - len(bad)}/{total} утверждений" + (f", стилей {len(styles)}" if styles else "")
    if a.pair:
        tail += f", пар {ran - len(blind)}/{ran} краснеют"
    print(("OK  " if okay else "RED ") + tail + ("" if okay else " — " + "; ".join((bad + ["слепая пара " + b for b in blind])[:4])))
    return 0 if okay else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
