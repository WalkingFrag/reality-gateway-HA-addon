const $ = (id) => document.getElementById(id);
const api = (path) => new URL(path, document.baseURI);
const badge = (el, text, tone) => { el.textContent = text; el.className = `badge ${tone}`; };
const fmtBytes = (value) => {
  if (!Number.isFinite(value)) return '—';
  if (value < 1024) return `${value} Б`;
  const units = ['КБ', 'МБ', 'ГБ', 'ТБ'];
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)) - 1, units.length - 1);
  return `${(value / 1024 ** (power + 1)).toFixed(1)} ${units[power]}`;
};
const fmtAge = (seconds) => {
  if (seconds == null) return 'Не было';
  if (seconds < 60) return `${seconds} с назад`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} мин назад`;
  return `${Math.floor(seconds / 3600)} ч назад`;
};

let draggedExit = null;
let savingOrder = false;

async function moveExit(exits, from, to) {
  if (savingOrder || from === to) return;
  const order = exits.map(item => item.id);
  order.splice(to, 0, order.splice(from, 1)[0]);
  savingOrder = true;
  try {
    const response = await fetch(api('api/exit-order'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({order}),
    });
    if (!response.ok) throw new Error();
    $('order-message').textContent = 'Приоритет сохранён. Активный маршрут отмечен в списке.';
  } catch {
    $('order-message').textContent = 'Не удалось сохранить порядок. Повторите перемещение.';
  } finally {
    savingOrder = false;
    await refresh();
  }
}

function renderExits(exits, current, routeOk) {
  if (draggedExit !== null || savingOrder) return;
  const list = $('exit-list'); list.replaceChildren();
  if (!exits.length) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = 'Контроллер пока не передал список туннелей.'; list.append(p); return; }
  exits.forEach((item, index) => {
    const row = document.createElement('div'); row.className = 'exit-row';
    const num = document.createElement('span'); num.className = 'exit-number'; num.textContent = String(index + 1).padStart(2, '0');
    const title = document.createElement('div');
    const name = document.createElement('strong'); name.className = 'exit-name'; name.textContent = item.label;
    const kind = document.createElement('small'); kind.className = 'exit-kind'; kind.textContent = item.kind === 'awg3' ? 'AmneziaWG 3.1' : 'VLESS + Reality';
    title.append(name, kind);
    const health = document.createElement('span'); health.className = `exit-health ${item.health}`;
    health.textContent = {healthy:'Доступен',unhealthy:'Недоступен',unknown:'Не проверяется'}[item.health] || 'Неизвестно';
    const active = document.createElement('span'); active.className = 'exit-active'; active.textContent = item.id === current ? (routeOk ? 'АКТИВЕН' : 'ВЫБРАН') : '';
    const controls = document.createElement('div');
    controls.className = 'exit-order';
    for (const [offset, symbol, label] of [[-1, '↑', 'Поднять'], [1, '↓', 'Опустить']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = symbol;
      button.setAttribute('aria-label', label + ' ' + item.label);
      button.disabled = index + offset < 0 || index + offset >= exits.length;
      button.addEventListener('click', () => moveExit(exits, index, index + offset));
      controls.append(button);
    }
    row.draggable = exits.length > 1;
    row.addEventListener('dragstart', event => {
      draggedExit = index;
      event.dataTransfer.setData('text/plain', item.id);
      event.dataTransfer.effectAllowed = 'move';
    });
    row.addEventListener('dragend', () => { draggedExit = null; });
    row.addEventListener('dragover', event => {
      if (draggedExit !== null) event.preventDefault();
    });
    row.addEventListener('drop', event => {
      if (draggedExit === null) return;
      event.preventDefault();
      const from = draggedExit;
      draggedExit = null;
      moveExit(exits, from, index);
    });
    active.append(controls);
    row.append(num, title, health, active); list.append(row);
  });
}

function renderSaved(extras) {
  const list = $('saved-list'); list.replaceChildren();
  if (!extras.length) { const p = document.createElement('p'); p.className = 'saved-empty'; p.textContent = 'Дополнительных VLESS пока нет.'; list.append(p); return; }
  extras.forEach((item) => {
    const row = document.createElement('div'); row.className = 'saved-item';
    const name = document.createElement('span'); name.textContent = item.label;
    const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Удалить'; button.setAttribute('aria-label', `Удалить ${item.label}`);
    button.addEventListener('click', async () => {
      if (!confirm(`Удалить «${item.label}»? Изменение вступит в силу после перезапуска аддона.`)) return;
      button.disabled = true;
      try {
        const response = await fetch(api(`api/vless/${encodeURIComponent(item.id)}`), {method:'DELETE', headers:{'X-Requested-With':'XMLHttpRequest'}});
        if (!response.ok) throw new Error('Не удалось удалить VLESS.');
        $('form-message').textContent = 'VLESS удалён. Перезапустите аддон для применения.';
        await refresh();
      } catch (error) { $('form-message').textContent = error.message; button.disabled = false; }
    });
    row.append(name, button); list.append(row);
  });
}

function renderAwg(exits) {
  const list = $('saved-awg-list'); list.replaceChildren();
  if (!exits.length) { const p = document.createElement('p'); p.className = 'saved-empty'; p.textContent = 'Выходов AWG, добавленных через панель, пока нет.'; list.append(p); return; }
  exits.forEach((item) => {
    const row = document.createElement('div'); row.className = 'saved-item';
    const name = document.createElement('span'); name.textContent = item.label;
    const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Удалить'; button.setAttribute('aria-label', `Удалить ${item.label}`);
    button.addEventListener('click', async () => {
      if (!confirm(`Удалить «${item.label}»? Изменение вступит в силу после перезапуска аддона.`)) return;
      button.disabled = true;
      try {
        const response = await fetch(api(`api/awg/${encodeURIComponent(item.id)}`), {method:'DELETE', headers:{'X-Requested-With':'XMLHttpRequest'}});
        if (!response.ok) throw new Error('Не удалось удалить AWG.');
        $('awg-message').textContent = 'AWG удалён. Перезапустите аддон для применения.';
        await refresh();
      } catch (error) { $('awg-message').textContent = error.message; button.disabled = false; }
    });
    row.append(name, button); list.append(row);
  });
}

function render(state) {
  $('poll-dot').className = `pulse ${state.online ? 'ok' : 'bad'}`;
  $('poll-label').textContent = state.online ? 'Данные обновлены' : 'Нет связи с контроллером';
  const selected = state.exits.find((item) => item.id === state.current);
  if (!state.online) {
    $('route-name').textContent = 'Нет данных'; $('route-detail').textContent = 'Контроллер маршрутов не отвечает. Проверьте журнал аддона.';
    $('route-path').textContent = 'Нет данных'; badge($('route-badge'), 'Нет связи', 'bad');
  } else if (!selected) {
    $('route-name').textContent = 'Нет активного выхода'; $('route-detail').textContent = 'Все проверяемые выходы недоступны. Трафик через WireGuard блокируется.';
    $('route-path').textContent = 'Блокировка'; badge($('route-badge'), 'Нет выхода', 'bad');
  } else {
    $('route-name').textContent = selected.label; $('route-path').textContent = selected.kind === 'awg3' ? 'AmneziaWG' : 'VLESS';
    if (!state.route_ok) { badge($('route-badge'), 'Маршрут не подтверждён', 'bad'); $('route-detail').textContent = 'Контроллер выбрал выход, но маршрут в таблице 100 не найден.'; }
    else if (selected.health === 'unknown') { badge($('route-badge'), 'Маршрут выбран', 'warn'); $('route-detail').textContent = 'Маршрут установлен. Доступность сервера в этом режиме не проверяется.'; }
    else { badge($('route-badge'), 'Трафик направлен', 'good'); $('route-detail').textContent = `${selected.kind === 'awg3' ? 'AmneziaWG 3.1' : 'VLESS + Reality'} · проверка выхода успешна · маршрут подтверждён`; }
  }
  const wg = state.wireguard;
  $('wg-handshake').textContent = fmtAge(wg.handshake_age_seconds);
  $('wg-rx').textContent = fmtBytes(wg.received_bytes);
  $('wg-tx').textContent = fmtBytes(wg.sent_bytes);
  const wgCopy = {
    recent: ['Был обмен', 'Недавний handshake с роутером. Туннель передавал данные.', 'good'],
    stale: ['Нет свежего обмена', 'Последний handshake устарел. При простое роутера это возможно.', 'warn'],
    waiting: ['Ожидание', 'Роутер ещё не установил WireGuard-соединение.', 'warn'],
    no_peer: ['Нет peer', 'Интерфейс wg0 есть, но peer роутера не найден.', 'bad'],
    unavailable: ['Нет данных', 'Не удалось получить состояние wg0.', 'bad'],
  }[wg.state] || ['Нет данных', 'Состояние WireGuard неизвестно.', 'bad'];
  badge($('wg-badge'), wgCopy[0], wgCopy[2]); $('wg-detail').textContent = wgCopy[1];
  $('restart-banner').hidden = !state.restart_required;
  renderExits(state.exits, state.current, state.route_ok);
  renderAwg(state.configured_awg || []); renderSaved(state.configured_vless);
}

async function refresh() {
  try {
    const response = await fetch(api('api/status'), {cache:'no-store'});
    if (!response.ok) throw new Error('status unavailable');
    render(await response.json());
  } catch (_) {
    render({online:false,current:null,route_ok:false,exits:[],configured_awg:[],configured_vless:[],restart_required:false,
      wireguard:{state:'unavailable',handshake_age_seconds:null,received_bytes:0,sent_bytes:0}});
  }
}

$('vless-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('add-button'); button.disabled = true; $('form-message').textContent = 'Проверяем ссылку…';
  try {
    const response = await fetch(api('api/vless'), {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}, body:JSON.stringify({url:$('vless-url').value.trim()})});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Не удалось сохранить VLESS.');
    $('vless-url').value = ''; $('form-message').textContent = `«${value.label}» добавлен. Перезапустите аддон для применения.`;
    await refresh();
  } catch (error) { $('form-message').textContent = error.message; }
  finally { button.disabled = false; }
});
$('awg-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('awg-add-button'); button.disabled = true; $('awg-message').textContent = 'Проверяем профиль…';
  try {
    const response = await fetch(api('api/awg'), {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
      body:JSON.stringify({name:$('awg-name').value.trim(),profile:$('awg-profile').value.trim()})});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Не удалось сохранить AWG.');
    $('awg-name').value = ''; $('awg-profile').value = '';
    $('awg-message').textContent = `«${value.label}» добавлен. Перезапустите аддон для применения.`;
    await refresh();
  } catch (error) { $('awg-message').textContent = error.message; }
  finally { button.disabled = false; }
});
refresh(); setInterval(refresh, 15000);
