const tg = window.Telegram?.WebApp;

const categories = [
  { id: "links", label: "Ссылки", icon: "↗", tint: "rgba(102,182,255,.13)" },
  { id: "watch", label: "Посмотреть", icon: "▶", tint: "rgba(255,127,200,.13)" },
  { id: "development", label: "Разработка", icon: "⌘", tint: "rgba(146,117,255,.15)" },
  { id: "buy", label: "Купить", icon: "◇", tint: "rgba(255,155,98,.14)" },
  { id: "read", label: "Почитать", icon: "≡", tint: "rgba(200,255,98,.12)" },
  { id: "files", label: "Файлы", icon: "▱", tint: "rgba(255,255,255,.09)" },
];

const categoryNames = Object.fromEntries([
  ["inbox", "Без категории"],
  ...categories.map((category) => [category.id, category.label]),
]);

const state = {
  category: null,
  filter: "all",
  query: "",
  items: [],
  stats: null,
  searchTimer: null,
  itemsLoaded: false,
  requestId: 0,
};

const elements = {
  categoryGrid: document.querySelector("#categoryGrid"),
  totalCount: document.querySelector("#totalCount"),
  itemsList: document.querySelector("#itemsList"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  searchClear: document.querySelector("#searchClear"),
  searchMode: document.querySelector("#searchMode"),
  refreshButton: document.querySelector("#refreshButton"),
  filterRow: document.querySelector("#filterRow"),
  resultsLabel: document.querySelector("#resultsLabel"),
  libraryTitle: document.querySelector("#libraryTitle"),
  profileBadge: document.querySelector("#profileBadge"),
  toast: document.querySelector("#toast"),
};

function authHeaders() {
  if (tg?.initData) return { "X-Telegram-Init-Data": tg.initData };
  return { "X-Dev-Telegram-User": "1" };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Ошибка ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function bootstrap() {
  tg?.ready();
  const desktopPlatforms = new Set(["tdesktop", "macos", "weba", "webk", "web"]);
  if (!desktopPlatforms.has((tg?.platform || "").toLowerCase())) {
    tg?.expand();
  }
  tg?.setHeaderColor?.("#0b0d12");
  tg?.setBackgroundColor?.("#0b0d12");

  const telegramUser = tg?.initDataUnsafe?.user;
  if (telegramUser) {
    const initials = `${telegramUser.first_name?.[0] || ""}${telegramUser.last_name?.[0] || ""}`;
    elements.profileBadge.textContent = initials || "SB";
  }

  bindEvents();
  await Promise.all([loadStats(), loadItems(), loadMe()]);
}

function bindEvents() {
  elements.searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch(elements.searchInput.value.trim());
  });
  elements.searchInput.addEventListener("input", () => {
    const query = elements.searchInput.value.trim();
    elements.searchClear.classList.toggle("visible", Boolean(query));
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => runSearch(query), 420);
  });
  elements.searchClear.addEventListener("click", () => {
    elements.searchInput.value = "";
    elements.searchClear.classList.remove("visible");
    runSearch("");
  });
  elements.refreshButton.addEventListener("click", refreshAll);
  elements.filterRow.addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    elements.filterRow.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item === button));
    loadItems();
  });
  elements.categoryGrid.addEventListener("click", (event) => {
    const card = event.target.closest("[data-category]");
    if (!card) return;
    state.category = state.category === card.dataset.category ? null : card.dataset.category;
    renderCategories();
    loadItems();
  });
  elements.itemsList.addEventListener("click", handleItemAction);
}

async function loadMe() {
  try {
    const me = await api("/api/me");
    elements.searchMode.textContent = me.ai_enabled
      ? "AI-поиск понимает смысл, контекст и формулировки"
      : "Поиск работает по ключевым словам · AI-режим можно подключить позже";
  } catch (error) {
    showToast(error.message);
  }
}

async function loadStats() {
  try {
    state.stats = await api("/api/stats");
    elements.totalCount.textContent = state.stats.total;
    renderCategories();
  } catch (error) {
    elements.categoryGrid.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderCategories() {
  if (!state.stats) return;
  elements.categoryGrid.innerHTML = categories.map((category) => `
    <button
      class="category-card ${state.category === category.id ? "active" : ""}"
      data-category="${category.id}"
      style="--category-tint:${category.tint}"
    >
      <span class="category-icon">${category.icon}</span>
      <span class="category-name">${category.label}</span>
      <span class="category-count">${state.stats.categories?.[category.id] || 0}</span>
    </button>
  `).join("");
}

async function loadItems() {
  const requestId = ++state.requestId;
  setLoading();
  state.query = "";
  const params = new URLSearchParams({ limit: "50" });
  if (state.category) params.set("category", state.category);
  if (state.filter === "favorites") params.set("favorite", "true");
  if (state.filter === "unread") params.set("unread", "true");
  try {
    const payload = await api(`/api/items?${params}`);
    if (requestId !== state.requestId) return;
    state.items = payload.items;
    elements.resultsLabel.textContent = state.category ? "КАТЕГОРИЯ" : "ПОСЛЕДНИЕ";
    elements.libraryTitle.textContent = state.category ? categoryNames[state.category] : "Сохранения";
    renderItems();
  } catch (error) {
    if (requestId === state.requestId) renderError(error);
  } finally {
    if (requestId === state.requestId) clearLoading();
  }
}

async function runSearch(query) {
  state.query = query;
  if (query.length < 2) {
    await loadItems();
    return;
  }
  const requestId = ++state.requestId;
  setLoading();
  try {
    const payload = await api(`/api/search?q=${encodeURIComponent(query)}&limit=50`);
    if (requestId !== state.requestId) return;
    state.items = payload.items;
    elements.resultsLabel.textContent = payload.mode === "semantic" ? "AI-ПОИСК" : "ПОИСК";
    elements.libraryTitle.textContent = `Результаты · ${payload.items.length}`;
    renderItems();
  } catch (error) {
    if (requestId === state.requestId) renderError(error);
  } finally {
    if (requestId === state.requestId) clearLoading();
  }
}

function renderItems() {
  state.itemsLoaded = true;
  if (!state.items.length) {
    elements.itemsList.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">⌁</span>
        Здесь пока пусто.<br />Перешли боту сообщение или измени фильтр.
      </div>`;
    return;
  }
  elements.itemsList.innerHTML = state.items.map((item) => renderItem(item)).join("");
}

function renderItem(item) {
  const title = escapeHtml(item.title);
  const titleElement = item.url
    ? `<a class="item-title" href="${escapeAttribute(item.url)}" target="_blank" rel="noopener">${title}</a>`
    : `<span class="item-title">${title}</span>`;
  const excerpt = item.text && item.text !== item.title
    ? `<p class="item-excerpt">${escapeHtml(item.text)}</p>`
    : "";
  const summary = item.summary
    ? `<div class="item-summary"><b>Кратко</b><br>${escapeHtml(item.summary)}</div>`
    : "";
  const source = item.source_chat || item.source_author;
  const reminder = item.reminder_at
    ? `<span class="meta-dot"></span><span class="reminder-label">⏰ ${formatDate(item.reminder_at)}</span>`
    : "";
  const media = item.has_media ? renderMediaLauncher(item) : "";
  return `
    <article class="item-card ${item.read ? "read" : ""}" data-item-id="${item.id}">
      <div class="item-top">
        <span class="category-chip">${escapeHtml(categoryNames[item.category] || "Без категории")}</span>
        <button class="favorite-button ${item.favorite ? "active" : ""}" data-action="favorite" aria-label="Избранное">${item.favorite ? "★" : "☆"}</button>
      </div>
      ${titleElement}
      ${media}
      ${excerpt}
      ${summary}
      <div class="item-meta">
        <span>${formatDate(item.created_at)}</span>
        ${source ? `<span class="meta-dot"></span><span>${escapeHtml(source)}</span>` : ""}
        ${reminder}
      </div>
      <div class="item-actions">
        <button class="action-button" data-action="read">${item.read ? "↩ Не прочитано" : "✓ Прочитано"}</button>
        <button class="action-button" data-action="tomorrow">⏰ Завтра</button>
        <button class="action-button" data-action="month">Через месяц</button>
        <button class="action-button" data-action="summary">✨ Кратко</button>
        <button class="action-button danger" data-action="delete">Удалить</button>
      </div>
    </article>`;
}

function renderMediaLauncher(item) {
  const labels = {
    video: ["▶", "Смотреть видео"],
    audio: ["♪", "Слушать аудио"],
    voice: ["◉", "Слушать голосовое"],
    photo: ["▧", "Открыть изображение"],
    file: ["↓", "Открыть файл"],
  };
  const [icon, label] = labels[item.kind] || labels.file;
  return `
    <div class="item-media-slot" data-media-slot>
      <button class="media-launcher" data-action="media">
        <span class="media-launcher-icon">${icon}</span>
        <span>
          <b>${label}</b>
          ${item.file_name ? `<small>${escapeHtml(item.file_name)}</small>` : ""}
        </span>
      </button>
    </div>`;
}

async function handleItemAction(event) {
  const button = event.target.closest("[data-action]");
  const card = event.target.closest("[data-item-id]");
  if (!button || !card) return;
  const itemId = Number(card.dataset.itemId);
  const item = state.items.find((candidate) => candidate.id === itemId);
  if (!item) return;
  const action = button.dataset.action;

  try {
    button.disabled = true;
    if (action === "favorite") {
      await updateItem(itemId, { favorite: !item.favorite }, "Избранное обновлено");
    } else if (action === "read") {
      await updateItem(itemId, { read: !item.read }, "Статус обновлён");
    } else if (action === "tomorrow" || action === "month") {
      const date = new Date();
      date.setDate(date.getDate() + (action === "tomorrow" ? 1 : 30));
      await updateItem(itemId, { reminder_at: date.toISOString() }, "Напоминание поставлено");
    } else if (action === "summary") {
      showToast("Готовлю краткое содержание…");
      const updated = await api(`/api/items/${itemId}/summary`, { method: "POST" });
      replaceItem(updated);
      showToast("Суммаризация готова");
    } else if (action === "media") {
      await openMedia(item, card);
    } else if (action === "delete") {
      const confirmed = await askConfirm("Удалить это сохранение?");
      if (!confirmed) return;
      await api(`/api/items/${itemId}`, { method: "DELETE" });
      state.items = state.items.filter((candidate) => candidate.id !== itemId);
      renderItems();
      await loadStats();
      showToast("Сохранение удалено");
    }
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function openMedia(item, card) {
  const slot = card.querySelector("[data-media-slot]");
  if (!slot) return;
  slot.classList.add("loading");
  const media = await api(`/api/items/${item.id}/media-url`);
  const source = escapeAttribute(media.url);
  const title = escapeAttribute(item.title);
  if (item.kind === "video") {
    slot.innerHTML = `<video class="item-media" controls playsinline preload="metadata" src="${source}" aria-label="${title}"></video>`;
  } else if (item.kind === "audio" || item.kind === "voice") {
    slot.innerHTML = `<audio class="item-audio" controls preload="metadata" src="${source}" aria-label="${title}"></audio>`;
  } else if (item.kind === "photo") {
    slot.innerHTML = `<img class="item-media" loading="lazy" src="${source}" alt="${title}" />`;
  } else {
    slot.innerHTML = `<a class="media-file" href="${source}" target="_blank" rel="noopener">Открыть ${escapeHtml(media.file_name || "файл")} ↗</a>`;
  }
}

async function updateItem(itemId, patch, notice) {
  const updated = await api(`/api/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  replaceItem(updated);
  await loadStats();
  showToast(notice);
}

function replaceItem(updated) {
  state.items = state.items.map((item) => item.id === updated.id ? updated : item);
  renderItems();
}

async function refreshAll() {
  elements.refreshButton.classList.add("loading");
  try {
    await Promise.all([loadStats(), state.query ? runSearch(state.query) : loadItems()]);
    showToast("Обновлено");
  } finally {
    elements.refreshButton.classList.remove("loading");
  }
}

function setLoading() {
  elements.itemsList.classList.add("loading");
  elements.itemsList.setAttribute("aria-busy", "true");
  if (!state.itemsLoaded) {
    elements.itemsList.innerHTML = `
      <div class="loading-state">
        <span class="loading-dot"></span>
        Загружаю сохранения…
      </div>`;
  }
}

function clearLoading() {
  elements.itemsList.classList.remove("loading");
  elements.itemsList.setAttribute("aria-busy", "false");
}

function renderError(error) {
  state.itemsLoaded = true;
  elements.itemsList.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => elements.toast.classList.remove("visible"), 2400);
}

function askConfirm(message) {
  if (tg?.showConfirm) {
    return new Promise((resolve) => tg.showConfirm(message, resolve));
  }
  return Promise.resolve(window.confirm(message));
}

function formatDate(value) {
  const date = new Date(value);
  const now = new Date();
  const sameYear = date.getFullYear() === now.getFullYear();
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(date).replace(" г.", "");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

bootstrap().catch((error) => renderError(error));
