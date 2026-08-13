const tg = window.Telegram?.WebApp;

const categoryTints = [
  "rgba(200,255,98,.12)",
  "rgba(102,182,255,.13)",
  "rgba(255,127,200,.13)",
  "rgba(146,117,255,.15)",
  "rgba(255,155,98,.14)",
  "rgba(255,255,255,.09)",
];

const state = {
  category: null,
  filter: "all",
  query: "",
  items: [],
  stats: null,
  searchTimer: null,
  itemsLoaded: false,
  requestId: 0,
  actionDrag: null,
  categories: [],
  aiEnabled: false,
  selectionMode: false,
  selectedIds: new Set(),
  reminderTarget: null,
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
  manageCategoriesButton: document.querySelector("#manageCategoriesButton"),
  categoryManager: document.querySelector("#categoryManager"),
  categoryManagerClose: document.querySelector("#categoryManagerClose"),
  categoryCreateForm: document.querySelector("#categoryCreateForm"),
  categoryIconInput: document.querySelector("#categoryIconInput"),
  categoryNameInput: document.querySelector("#categoryNameInput"),
  categoryManagerList: document.querySelector("#categoryManagerList"),
  selectModeButton: document.querySelector("#selectModeButton"),
  bulkBar: document.querySelector("#bulkBar"),
  bulkCount: document.querySelector("#bulkCount"),
  selectAllButton: document.querySelector("#selectAllButton"),
  cancelSelectionButton: document.querySelector("#cancelSelectionButton"),
  smartReminderModal: document.querySelector("#smartReminderModal"),
  smartReminderForm: document.querySelector("#smartReminderForm"),
  smartReminderInput: document.querySelector("#smartReminderInput"),
  bulkCategoryModal: document.querySelector("#bulkCategoryModal"),
  bulkCategoryList: document.querySelector("#bulkCategoryList"),
  privacyButton: document.querySelector("#privacyButton"),
  privacyModal: document.querySelector("#privacyModal"),
  deleteAccountButton: document.querySelector("#deleteAccountButton"),
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
  await Promise.all([loadCategories(), loadMe()]);
  await Promise.all([loadStats(), loadItems()]);
}

function bindEvents() {
  elements.searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitSearch();
  });
  elements.searchInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    submitSearch();
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
  elements.manageCategoriesButton.addEventListener("click", () => {
    elements.categoryManager.hidden = !elements.categoryManager.hidden;
  });
  elements.categoryManagerClose.addEventListener("click", () => {
    elements.categoryManager.hidden = true;
  });
  elements.categoryCreateForm.addEventListener("submit", createCategory);
  elements.categoryManagerList.addEventListener("submit", renameCategory);
  elements.selectModeButton.addEventListener("click", () => setSelectionMode(!state.selectionMode));
  elements.selectAllButton.addEventListener("click", toggleSelectAll);
  elements.cancelSelectionButton.addEventListener("click", () => setSelectionMode(false));
  elements.bulkBar.addEventListener("click", handleBulkAction);
  elements.smartReminderForm.addEventListener("submit", submitSmartReminder);
  elements.bulkCategoryList.addEventListener("click", handleBulkCategory);
  elements.privacyButton.addEventListener("click", () => openModal(elements.privacyModal));
  elements.deleteAccountButton.addEventListener("click", deleteAccount);
  document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-close-modal]");
    if (closer) closeModal(document.getElementById(closer.dataset.closeModal));
    if (event.target.classList.contains("modal-backdrop")) closeModal(event.target);
  });
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
  elements.itemsList.addEventListener("submit", handleTitleSubmit);
  elements.itemsList.addEventListener("click", handleVideoAction);
  elements.itemsList.addEventListener("input", handleVideoSeek);
  elements.itemsList.addEventListener("wheel", handleActionsWheel, { passive: false });
  elements.itemsList.addEventListener("pointerdown", beginActionDrag);
  elements.itemsList.addEventListener("pointermove", moveActionDrag);
  elements.itemsList.addEventListener("pointerup", endActionDrag);
  elements.itemsList.addEventListener("pointercancel", endActionDrag);
  elements.itemsList.addEventListener("keydown", handleActionsKeydown);
}

function submitSearch() {
  clearTimeout(state.searchTimer);
  const query = elements.searchInput.value.trim();
  elements.searchInput.blur();
  requestAnimationFrame(() => {
    if (document.activeElement === elements.searchInput) elements.searchInput.blur();
  });
  runSearch(query);
}

async function loadMe() {
  try {
    const me = await api("/api/me");
    state.aiEnabled = me.ai_enabled;
    elements.searchMode.textContent = me.ai_enabled
      ? "AI-поиск понимает смысл, контекст и формулировки"
      : "Поиск работает по ключевым словам · AI-режим можно подключить позже";
  } catch (error) {
    showToast(error.message);
  }
}

async function loadCategories() {
  try {
    const payload = await api("/api/categories");
    state.categories = payload.categories;
    renderCategoryManager();
    if (state.stats) renderCategories();
  } catch (error) {
    showToast(error.message);
  }
}

function categoryById(categoryId) {
  return state.categories.find((category) => category.id === categoryId);
}

function categoryName(categoryId) {
  return categoryById(categoryId)?.name || "Без категории";
}

async function createCategory(event) {
  event.preventDefault();
  const name = elements.categoryNameInput.value.trim();
  const icon = elements.categoryIconInput.value.trim() || "🗂";
  if (!name) return;
  const submit = event.submitter;
  try {
    if (submit) submit.disabled = true;
    await api("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name, icon }),
    });
    elements.categoryNameInput.value = "";
    await loadCategories();
    await loadStats();
    renderItems();
    showToast("Категория создана");
  } catch (error) {
    showToast(error.message);
  } finally {
    if (submit) submit.disabled = false;
  }
}

async function renameCategory(event) {
  const form = event.target.closest("[data-category-rename]");
  if (!form) return;
  event.preventDefault();
  const input = form.querySelector("input");
  const submit = form.querySelector("button");
  const name = input.value.trim();
  if (!name) return;
  try {
    submit.disabled = true;
    await api(`/api/categories/${encodeURIComponent(form.dataset.categoryRename)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    await loadCategories();
    await loadStats();
    renderItems();
    if (state.category) elements.libraryTitle.textContent = categoryName(state.category);
    showToast("Название сохранено");
  } catch (error) {
    showToast(error.message);
  } finally {
    submit.disabled = false;
  }
}

function renderCategoryManager() {
  elements.categoryManagerList.innerHTML = state.categories.map((category) => `
    <form class="category-rename" data-category-rename="${escapeAttribute(category.id)}">
      <span class="category-rename-icon">${escapeHtml(category.icon)}</span>
      <input value="${escapeAttribute(category.name)}" maxlength="40" aria-label="Название категории ${escapeAttribute(category.name)}" required />
      <button type="submit">Сохранить</button>
    </form>
  `).join("");
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
  elements.categoryGrid.innerHTML = state.categories.map((category, index) => `
    <button
      class="category-card ${state.category === category.id ? "active" : ""}"
      data-category="${category.id}"
      style="--category-tint:${categoryTints[index % categoryTints.length]}"
    >
      <span class="category-icon">${escapeHtml(category.icon)}</span>
      <span class="category-name">${escapeHtml(category.name)}</span>
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
    elements.libraryTitle.textContent = state.category ? categoryName(state.category) : "Сохранения";
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
  const visibleIds = new Set(state.items.map((item) => item.id));
  state.selectedIds = new Set([...state.selectedIds].filter((itemId) => visibleIds.has(itemId)));
  if (!state.items.length) {
    elements.itemsList.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">⌁</span>
        Здесь пока пусто.<br />Перешли боту сообщение или измени фильтр.
      </div>`;
    renderSelectionBar();
    return;
  }
  elements.itemsList.innerHTML = state.items.map((item) => renderItem(item)).join("");
  renderSelectionBar();
}

function renderItem(item) {
  const title = escapeHtml(item.title);
  const filenameTitle = item.kind === "video" && item.file_name && item.title === item.file_name;
  const editableVideoTitle = item.kind === "video"
    ? `<button class="item-title video-topic" data-action="edit-title" aria-label="Изменить тему видео">${title}<span aria-hidden="true">✎</span></button>`
    : "";
  const titleElement = editableVideoTitle || (filenameTitle
    ? ""
    : item.url
    ? `<a class="item-title" href="${escapeAttribute(item.url)}" target="_blank" rel="noopener">${title}</a>`
    : `<span class="item-title">${title}</span>`);
  const excerpt = item.text && item.text !== item.title
    ? `<p class="item-excerpt">${escapeHtml(item.text)}</p>`
    : "";
  const summary = item.summary
    ? `<div class="item-summary"><b>Кратко</b><br>${escapeHtml(item.summary)}</div>`
    : "";
  const recognized = item.recognized_text
    ? `<details class="recognized-content"><summary>${item.recognition_kind === "transcript" ? "Расшифровка" : item.recognition_kind === "ocr" ? "Распознано на изображении" : "Текст документа"}</summary><p>${escapeHtml(item.recognized_text)}</p></details>`
    : "";
  const source = item.source_chat || item.source_author;
  const reminder = item.reminder_at
    ? `<span class="meta-dot"></span><span class="reminder-label">⏰ ${formatDate(item.reminder_at)}</span>`
    : "";
  const media = item.has_media ? renderMediaLauncher(item) : "";
  return `
    <article class="item-card ${item.read ? "read" : ""} ${state.selectionMode ? "selection-mode" : ""} ${state.selectedIds.has(item.id) ? "selected" : ""}" data-item-id="${item.id}">
      ${state.selectionMode ? `<button class="selection-toggle" data-action="select" aria-label="${state.selectedIds.has(item.id) ? "Убрать из выбранного" : "Выбрать карточку"}">${state.selectedIds.has(item.id) ? "✓" : ""}</button>` : ""}
      <div class="item-top">
        <button class="category-chip" data-action="category" aria-expanded="false">
          ${escapeHtml(categoryName(item.category))} <span aria-hidden="true">⌄</span>
        </button>
        <button class="favorite-button ${item.favorite ? "active" : ""}" data-action="favorite" aria-label="Избранное">${item.favorite ? "★" : "☆"}</button>
      </div>
      ${renderCategoryPicker(item)}
      ${titleElement}
      ${item.kind === "video" ? renderTitleEditor(item) : ""}
      ${media}
      ${excerpt}
      ${summary}
      ${recognized}
      <div class="item-meta">
        <span>${formatDate(item.created_at)}</span>
        ${source ? `<span class="meta-dot"></span><span>${escapeHtml(source)}</span>` : ""}
        ${reminder}
      </div>
      <div class="item-actions" tabindex="0" aria-label="Действия с сохранением">
        <button class="action-button" data-action="read">${item.read ? "↩ Не прочитано" : "✓ Прочитано"}</button>
        <button class="action-button" data-action="tomorrow">⏰ Завтра</button>
        <button class="action-button" data-action="month">Через месяц</button>
        <button class="action-button" data-action="smart-reminder">Когда угодно…</button>
        ${item.reminder_at ? '<button class="action-button reminder-cancel" data-action="cancel-reminder">🔕 Отменить</button>' : ""}
        <button class="action-button" data-action="category">📂 Категория</button>
        ${item.kind === "video" ? '<button class="action-button" data-action="edit-title">✎ Тема</button>' : ""}
        <button class="action-button" data-action="summary">${state.aiEnabled ? "✨ AI-кратко" : "✨ Кратко"}</button>
        ${item.has_media ? `<button class="action-button" data-action="recognize">${recognitionLabel(item)}</button>` : ""}
        <button class="action-button danger" data-action="delete">Удалить</button>
      </div>
    </article>`;
}

function renderTitleEditor(item) {
  return `
    <form class="video-topic-editor" data-title-editor hidden>
      <input
        value="${escapeAttribute(item.title === "Видео" ? "" : item.title)}"
        maxlength="300"
        placeholder="Например, Моменталка на банан"
        aria-label="Название темы видео"
        required
      />
      <button type="submit">Сохранить</button>
      <button type="button" data-action="cancel-title">Отмена</button>
    </form>`;
}

function renderCategoryPicker(item) {
  return `
    <div class="category-picker" data-category-picker hidden>
      <span class="category-picker-title">Переместить в категорию</span>
      <div class="category-options">
        ${state.categories.map((category) => `
          <button
            class="category-option ${item.category === category.id ? "active" : ""}"
            data-action="category-choice"
            data-category-value="${category.id}"
          >
            <span>${escapeHtml(category.icon)}</span>${escapeHtml(category.name)}${item.category === category.id ? " ✓" : ""}
          </button>
        `).join("")}
      </div>
    </div>`;
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
          ${item.kind !== "video" && item.file_name ? `<small>${escapeHtml(item.file_name)}</small>` : ""}
        </span>
      </button>
    </div>`;
}

function recognitionLabel(item) {
  if (item.recognized_text) return "↻ Распознать заново";
  if (item.kind === "photo") return "▧ Распознать текст";
  if (["audio", "voice", "video"].includes(item.kind)) return "◉ Расшифровать";
  return "▤ Извлечь текст";
}

function setSelectionMode(enabled) {
  state.selectionMode = enabled;
  state.selectedIds.clear();
  elements.selectModeButton.classList.toggle("active", enabled);
  elements.selectModeButton.textContent = enabled ? "Готово" : "Выбрать";
  renderItems();
}

function toggleItemSelection(itemId) {
  if (state.selectedIds.has(itemId)) state.selectedIds.delete(itemId);
  else state.selectedIds.add(itemId);
  renderItems();
  tg?.HapticFeedback?.selectionChanged?.();
}

function toggleSelectAll() {
  const visibleIds = state.items.map((item) => item.id);
  const allSelected = visibleIds.length && visibleIds.every((id) => state.selectedIds.has(id));
  state.selectedIds = new Set(allSelected ? [] : visibleIds);
  renderItems();
}

function renderSelectionBar() {
  elements.bulkBar.hidden = !state.selectionMode;
  elements.bulkCount.textContent = state.selectedIds.size;
  const allSelected = state.items.length && state.items.every((item) => state.selectedIds.has(item.id));
  elements.selectAllButton.textContent = allSelected ? "Снять все" : "Выбрать все";
  elements.bulkBar.querySelectorAll("[data-bulk-action]").forEach((button) => {
    button.disabled = state.selectedIds.size === 0;
  });
}

async function handleBulkAction(event) {
  const button = event.target.closest("[data-bulk-action]");
  if (!button || !state.selectedIds.size) return;
  const operation = button.dataset.bulkAction;
  if (operation === "move") {
    elements.bulkCategoryList.innerHTML = state.categories.map((category) => `
      <button type="button" data-bulk-category="${escapeAttribute(category.id)}">
        <span>${escapeHtml(category.icon)}</span>${escapeHtml(category.name)}
      </button>`).join("");
    openModal(elements.bulkCategoryModal);
    return;
  }
  if (operation === "remind") {
    state.reminderTarget = { kind: "bulk" };
    openSmartReminder();
    return;
  }
  if (operation === "delete") {
    const confirmed = await askConfirm(`Удалить выбранные сохранения (${state.selectedIds.size})?`);
    if (!confirmed) return;
  }
  await runBulkOperation(operation);
}

async function runBulkOperation(operation, extra = {}) {
  const ids = [...state.selectedIds];
  try {
    const result = await api("/api/bulk/items", {
      method: "POST",
      body: JSON.stringify({ item_ids: ids, operation, ...extra }),
    });
    showToast(`Обновлено сохранений: ${result.affected}`);
    setSelectionMode(false);
    await Promise.all([loadStats(), state.query ? runSearch(state.query) : loadItems()]);
  } catch (error) {
    showToast(error.message);
  }
}

async function handleBulkCategory(event) {
  const button = event.target.closest("[data-bulk-category]");
  if (!button) return;
  closeModal(elements.bulkCategoryModal);
  await runBulkOperation("move", { category: button.dataset.bulkCategory });
}

function openSmartReminder() {
  elements.smartReminderInput.value = "";
  openModal(elements.smartReminderModal);
  setTimeout(() => elements.smartReminderInput.focus(), 80);
}

async function submitSmartReminder(event) {
  event.preventDefault();
  const text = elements.smartReminderInput.value.trim();
  if (!text || !state.reminderTarget) return;
  const submit = event.submitter;
  try {
    submit.disabled = true;
    const timezoneOffset = -new Date().getTimezoneOffset();
    if (state.reminderTarget.kind === "bulk") {
      closeModal(elements.smartReminderModal);
      await runBulkOperation("remind", {
        reminder_text: text,
        timezone_offset_minutes: timezoneOffset,
      });
    } else {
      const updated = await api(`/api/items/${state.reminderTarget.itemId}/reminder`, {
        method: "POST",
        body: JSON.stringify({ text, timezone_offset_minutes: timezoneOffset }),
      });
      replaceItem(updated);
      closeModal(elements.smartReminderModal);
      showToast(`Напомню ${formatReminderDate(updated.reminder_at)}`);
    }
  } catch (error) {
    showToast(error.message);
  } finally {
    submit.disabled = false;
  }
}

function openModal(modal) {
  modal.hidden = false;
  document.body.classList.add("modal-open");
}

function closeModal(modal) {
  if (!modal) return;
  modal.hidden = true;
  if (!document.querySelector(".modal-backdrop:not([hidden])")) document.body.classList.remove("modal-open");
}

async function deleteAccount() {
  const first = await askConfirm("Удалить профиль и ВСЕ сохранения? Это нельзя отменить.");
  if (!first) return;
  const confirmation = window.prompt("Для окончательного подтверждения введи слово УДАЛИТЬ");
  if (!confirmation) return;
  try {
    elements.deleteAccountButton.disabled = true;
    await api("/api/account", {
      method: "DELETE",
      body: JSON.stringify({ confirmation }),
    });
    closeModal(elements.privacyModal);
    state.items = [];
    state.categories = [];
    renderItems();
    showToast("Все данные удалены");
    tg?.close?.();
  } catch (error) {
    showToast(error.message);
  } finally {
    elements.deleteAccountButton.disabled = false;
  }
}

async function handleItemAction(event) {
  const actions = event.target.closest(".item-actions");
  if (actions?.dataset.suppressClick === "true") {
    event.preventDefault();
    delete actions.dataset.suppressClick;
    return;
  }
  const button = event.target.closest("[data-action]");
  const card = event.target.closest("[data-item-id]");
  if (!card) return;
  const itemId = Number(card.dataset.itemId);
  const item = state.items.find((candidate) => candidate.id === itemId);
  if (!item) return;
  if (state.selectionMode && !button) {
    event.preventDefault();
    toggleItemSelection(itemId);
    return;
  }
  if (!button) return;
  const action = button.dataset.action;

  try {
    button.disabled = true;
    if (action === "select") {
      toggleItemSelection(itemId);
    } else if (state.selectionMode) {
      toggleItemSelection(itemId);
    } else if (action === "favorite") {
      await updateItem(itemId, { favorite: !item.favorite }, "Избранное обновлено");
    } else if (action === "read") {
      await updateItem(itemId, { read: !item.read }, "Статус обновлён");
    } else if (action === "tomorrow" || action === "month") {
      const date = new Date();
      date.setDate(date.getDate() + (action === "tomorrow" ? 1 : 30));
      await updateItem(itemId, { reminder_at: date.toISOString() }, "Напоминание поставлено");
    } else if (action === "cancel-reminder") {
      await updateItem(itemId, { clear_reminder: true }, "Напоминание отменено");
    } else if (action === "smart-reminder") {
      state.reminderTarget = { kind: "item", itemId };
      openSmartReminder();
    } else if (action === "category") {
      const picker = card.querySelector("[data-category-picker]");
      if (picker) {
        const willOpen = picker.hidden;
        picker.hidden = !willOpen;
        card.querySelectorAll('[data-action="category"]').forEach((trigger) => {
          trigger.setAttribute("aria-expanded", String(willOpen));
        });
        if (willOpen) {
          picker.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
    } else if (action === "category-choice") {
      const category = button.dataset.categoryValue;
      if (!categoryById(category)) throw new Error("Неизвестная категория");
      await updateItem(itemId, { category }, `Перемещено: ${categoryName(category)}`);
    } else if (action === "edit-title") {
      const editor = card.querySelector("[data-title-editor]");
      if (editor) {
        editor.hidden = false;
        editor.querySelector("input")?.focus();
      }
    } else if (action === "cancel-title") {
      const editor = card.querySelector("[data-title-editor]");
      if (editor) editor.hidden = true;
    } else if (action === "summary") {
      showToast(state.aiEnabled ? "AI готовит краткое содержание…" : "Готовлю краткое содержание…");
      const updated = await api(`/api/items/${itemId}/summary`, { method: "POST" });
      replaceItem(updated);
      showToast("Суммаризация готова");
    } else if (action === "recognize") {
      showToast("Распознаю содержимое…");
      const updated = await api(`/api/items/${itemId}/recognize`, { method: "POST" });
      replaceItem(updated);
      showToast("Содержимое распознано и добавлено в поиск");
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

async function handleTitleSubmit(event) {
  const editor = event.target.closest("[data-title-editor]");
  const card = event.target.closest("[data-item-id]");
  if (!editor || !card) return;
  event.preventDefault();
  const input = editor.querySelector("input");
  const submit = editor.querySelector('button[type="submit"]');
  const title = input?.value.trim() || "";
  if (!title) {
    showToast("Название не может быть пустым");
    return;
  }
  try {
    submit.disabled = true;
    input.blur();
    await updateItem(Number(card.dataset.itemId), { title }, "Название видео обновлено");
  } catch (error) {
    showToast(error.message);
  } finally {
    submit.disabled = false;
  }
}

async function openMedia(item, card) {
  const slot = card.querySelector("[data-media-slot]");
  if (!slot) return;
  slot.classList.add("loading");
  let media;
  try {
    media = await api(`/api/items/${item.id}/media-url`);
  } finally {
    slot.classList.remove("loading");
  }
  const source = escapeAttribute(media.url);
  const title = escapeAttribute(item.title);
  if (item.kind === "video") {
    slot.innerHTML = `
      <div class="video-player" data-video-player>
        <video class="item-video" data-video-action="toggle" playsinline preload="metadata" src="${source}" aria-label="${title}"></video>
        <button class="video-close" data-video-action="close" aria-label="Свернуть плеер">×</button>
        <button class="video-big-play" data-video-action="toggle" aria-label="Воспроизвести видео">▶</button>
        <span class="video-buffering" aria-hidden="true"></span>
        <div class="video-controls">
          <button class="video-control" data-video-action="toggle" aria-label="Воспроизвести">▶</button>
          <span class="video-time" data-video-current>0:00</span>
          <input class="video-progress" data-video-progress type="range" min="0" max="1000" value="0" aria-label="Позиция видео" />
          <span class="video-time" data-video-duration>0:00</span>
          <button class="video-control" data-video-action="mute" aria-label="Выключить звук">🔊</button>
          <button class="video-control" data-video-action="fullscreen" aria-label="На весь экран">⛶</button>
        </div>
      </div>`;
    setupVideoPlayer(slot.querySelector("[data-video-player]"));
  } else if (item.kind === "audio" || item.kind === "voice") {
    slot.innerHTML = `<audio class="item-audio" controls preload="metadata" src="${source}" aria-label="${title}"></audio>`;
  } else if (item.kind === "photo") {
    slot.innerHTML = `<img class="item-media" loading="lazy" src="${source}" alt="${title}" />`;
  } else {
    slot.innerHTML = `<a class="media-file" href="${source}" target="_blank" rel="noopener">Открыть ${escapeHtml(media.file_name || "файл")} ↗</a>`;
  }
}

function setupVideoPlayer(player) {
  if (!player) return;
  const video = player.querySelector("video");
  const progress = player.querySelector("[data-video-progress]");
  const current = player.querySelector("[data-video-current]");
  const duration = player.querySelector("[data-video-duration]");
  const toggleButtons = player.querySelectorAll('[data-video-action="toggle"]');
  const muteButton = player.querySelector('[data-video-action="mute"]');

  const updatePlaybackState = () => {
    const playing = !video.paused && !video.ended;
    player.classList.toggle("playing", playing);
    toggleButtons.forEach((button) => {
      if (button === video) return;
      button.textContent = playing ? "❚❚" : "▶";
      button.setAttribute("aria-label", playing ? "Поставить на паузу" : "Воспроизвести");
    });
  };
  const updateTimeline = () => {
    const total = Number.isFinite(video.duration) ? video.duration : 0;
    const value = total ? Math.round((video.currentTime / total) * 1000) : 0;
    progress.value = String(value);
    progress.style.setProperty("--video-progress", `${value / 10}%`);
    current.textContent = formatDuration(video.currentTime);
    duration.textContent = formatDuration(total);
  };

  video.addEventListener("loadedmetadata", () => {
    player.classList.toggle("portrait", video.videoHeight > video.videoWidth);
    updateTimeline();
  });
  video.addEventListener("timeupdate", updateTimeline);
  video.addEventListener("durationchange", updateTimeline);
  video.addEventListener("play", updatePlaybackState);
  video.addEventListener("pause", updatePlaybackState);
  video.addEventListener("ended", updatePlaybackState);
  video.addEventListener("waiting", () => player.classList.add("buffering"));
  video.addEventListener("playing", () => player.classList.remove("buffering"));
  video.addEventListener("canplay", () => player.classList.remove("buffering"));
  video.addEventListener("error", () => {
    player.classList.remove("buffering");
    showToast("Не удалось загрузить видео");
  });
  video.addEventListener("volumechange", () => {
    const muted = video.muted || video.volume === 0;
    muteButton.textContent = muted ? "🔇" : "🔊";
    muteButton.setAttribute("aria-label", muted ? "Включить звук" : "Выключить звук");
  });
}

async function handleVideoAction(event) {
  const control = event.target.closest("[data-video-action]");
  if (!control) return;
  const player = control.closest("[data-video-player]");
  const card = control.closest("[data-item-id]");
  const video = player?.querySelector("video");
  if (!player || !card || !video) return;
  const item = state.items.find((candidate) => candidate.id === Number(card.dataset.itemId));
  if (!item) return;

  event.preventDefault();
  const action = control.dataset.videoAction;
  if (action === "toggle") {
    if (video.paused || video.ended) {
      await video.play().catch(() => showToast("Нажми ещё раз, чтобы запустить видео"));
    } else {
      video.pause();
    }
  } else if (action === "mute") {
    video.muted = !video.muted;
  } else if (action === "fullscreen") {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else if (player.requestFullscreen) {
        await player.requestFullscreen();
      } else if (video.webkitEnterFullscreen) {
        video.webkitEnterFullscreen();
      }
    } catch {
      showToast("Полноэкранный режим недоступен");
    }
  } else if (action === "close") {
    video.pause();
    const slot = player.closest("[data-media-slot]");
    if (slot) slot.outerHTML = renderMediaLauncher(item);
  }
}

function handleVideoSeek(event) {
  const progress = event.target.closest("[data-video-progress]");
  if (!progress) return;
  const video = progress.closest("[data-video-player]")?.querySelector("video");
  if (!video || !Number.isFinite(video.duration)) return;
  video.currentTime = (Number(progress.value) / 1000) * video.duration;
}

function handleActionsWheel(event) {
  const scroller = event.target.closest(".item-actions");
  if (!scroller || scroller.scrollWidth <= scroller.clientWidth) return;
  const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
  if (!delta) return;
  const previous = scroller.scrollLeft;
  const maximum = scroller.scrollWidth - scroller.clientWidth;
  const next = Math.max(0, Math.min(maximum, previous + delta));
  if (next === previous) return;
  event.preventDefault();
  scroller.scrollLeft = next;
}

function beginActionDrag(event) {
  if (event.pointerType !== "mouse" || event.button !== 0) return;
  const scroller = event.target.closest(".item-actions");
  if (!scroller || scroller.scrollWidth <= scroller.clientWidth) return;
  state.actionDrag = {
    scroller,
    pointerId: event.pointerId,
    startX: event.clientX,
    startScroll: scroller.scrollLeft,
    moved: false,
  };
}

function moveActionDrag(event) {
  const drag = state.actionDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const distance = event.clientX - drag.startX;
  if (Math.abs(distance) > 4) {
    if (!drag.moved) {
      drag.scroller.setPointerCapture?.(event.pointerId);
    }
    drag.moved = true;
    drag.scroller.classList.add("dragging");
    drag.scroller.scrollLeft = drag.startScroll - distance;
    event.preventDefault();
  }
}

function endActionDrag(event) {
  const drag = state.actionDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (drag.moved && drag.scroller.hasPointerCapture?.(event.pointerId)) {
    drag.scroller.releasePointerCapture(event.pointerId);
  }
  drag.scroller.classList.remove("dragging");
  if (drag.moved) {
    drag.scroller.dataset.suppressClick = "true";
    setTimeout(() => delete drag.scroller.dataset.suppressClick, 300);
  }
  state.actionDrag = null;
}

function handleActionsKeydown(event) {
  const scroller = event.target.closest(".item-actions");
  if (!scroller || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  scroller.scrollBy({ left: event.key === "ArrowRight" ? 110 : -110, behavior: "smooth" });
}

function formatDuration(value) {
  if (!Number.isFinite(value) || value < 0) return "0:00";
  const total = Math.floor(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
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

function formatReminderDate(value) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
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
