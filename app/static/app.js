/* -----------------------------
   LocalStorage-backed chats + auto titles + sidebar toggle
------------------------------ */

const LS_KEY = "rag_webui_state_v1";
const SIDEBAR_KEY = "rag_webui_sidebar_collapsed_v1";

function nowIso() {
  return new Date().toISOString();
}

function uid() {
  return "c_" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

function defaultConversation() {
  return {
    id: uid(),
    title: "New chat",
    created_at: nowIso(),
    updated_at: nowIso(),
    history: [],
    settings: {
      persist_dir: "./rag_db",
      collection_name: "papers",
      k: 5,
      return_context: true,
    },
  };
}

function autoTitleFromMessage(text) {
  if (!text) return "New chat";
  const cleaned = String(text)
    .replace(/[^\w\s]/g, "")
    .replace(/\s+/g, " ")
    .trim();

  if (!cleaned) return "New chat";
  const words = cleaned.split(" ").slice(0, 6);
  const title = words.join(" ");
  return title.charAt(0).toUpperCase() + title.slice(1);
}

let state = {
  activeId: null,
  conversations: [],
};

/* -----------------------------
   DOM
------------------------------ */
const layoutEl = document.querySelector(".layout");
const toggleSidebarBtn = document.getElementById("toggleSidebarBtn");
const showSidebarFloatingBtn = document.getElementById("showSidebarFloatingBtn");

const chatEl = document.getElementById("chat");
const errorEl = document.getElementById("error");

const form = document.getElementById("askForm");
const messageInput = document.getElementById("message");

const persistDirInput = document.getElementById("persistDir");
const collectionNameInput = document.getElementById("collectionName");
const kInput = document.getElementById("k");
const showContextInput = document.getElementById("showContext");

const clearBtn = document.getElementById("clearBtn");

const pdfFilesInput = document.getElementById("pdfFiles");
const indexBtn = document.getElementById("indexBtn");
const indexStatusEl = document.getElementById("indexStatus");

const convoListEl = document.getElementById("convoList");
const newChatBtn = document.getElementById("newChatBtn");
const renameChatBtn = document.getElementById("renameChatBtn");
const deleteChatBtn = document.getElementById("deleteChatBtn");

/* -----------------------------
   Helpers
------------------------------ */
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setError(msg) {
  if (!errorEl) return;
  if (!msg) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  } else {
    errorEl.hidden = false;
    errorEl.textContent = msg;
  }
}

function setIndexStatus(text, kind) {
  if (!indexStatusEl) return;
  indexStatusEl.textContent = text || "";
  indexStatusEl.classList.remove("ok", "error");
  if (kind) indexStatusEl.classList.add(kind);
}

function getActiveConversation() {
  return state.conversations.find((c) => c.id === state.activeId) || null;
}

function saveState() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(state));
  } catch (e) {
    console.warn("Failed to save state:", e);
  }
}

function loadState() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return false;

    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.conversations)) return false;

    state = {
      activeId: parsed.activeId || null,
      conversations: parsed.conversations || [],
    };

    if (state.conversations.length === 0) {
      const c = defaultConversation();
      state.conversations = [c];
      state.activeId = c.id;
    }

    if (!state.conversations.some((c) => c.id === state.activeId)) {
      state.activeId = state.conversations[0].id;
    }

    return true;
  } catch (e) {
    console.warn("Failed to load state:", e);
    return false;
  }
}

function ensureState() {
  const ok = loadState();
  if (!ok) {
    const c = defaultConversation();
    state.conversations = [c];
    state.activeId = c.id;
    saveState();
  }
}

/* -----------------------------
   Sidebar collapse
------------------------------ */
function setSidebarCollapsed(collapsed) {
  if (!layoutEl) return;
  layoutEl.classList.toggle("sidebar-collapsed", collapsed);

  if (toggleSidebarBtn) {
    toggleSidebarBtn.textContent = collapsed ? "Show" : "Hide";
  }

  if (showSidebarFloatingBtn) {
    showSidebarFloatingBtn.hidden = !collapsed;
  }

  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  } catch {}
}

function initSidebarState() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {}
  setSidebarCollapsed(collapsed);
}

/* -----------------------------
   Rendering
------------------------------ */
function bubbleElFromMessage(msg) {
  const role = msg.role;
  const content = msg.content;

  const div = document.createElement("div");
  div.className = `bubble ${role}`;

  let inner = `
    <div class="role">${escapeHtml(role)}</div>
    <div class="content">${escapeHtml(content)}</div>
  `;

  // Retrieved sources dropdown under assistant
  if (role === "assistant" && Array.isArray(msg.contexts) && msg.contexts.length > 0) {
    const itemsHtml = msg.contexts.map((ctx, idx) => {
      const title = ctx?.metadata?.source || ctx?.metadata?.paper_id || `Source ${idx + 1}`;
      const section = ctx?.metadata?.section || "";
      const chunkId = ctx?.id || ctx?.metadata?.chunk_id || "";
      const meta = [title, section, chunkId].filter(Boolean).join(" • ");
      const text = ctx?.text || "";

      return `
        <div class="ctx">
          <div class="ctx-meta">${escapeHtml(meta)}</div>
          <div class="ctx-text">${escapeHtml(text)}</div>
        </div>
      `;
    }).join("");

    inner += `
      <details class="ctx-details">
        <summary>Retrieved sources (${msg.contexts.length})</summary>
        <div class="ctx-list">${itemsHtml}</div>
      </details>
    `;
  }

  div.innerHTML = inner;
  return div;
}

function addBubble(role, content) {
  if (!chatEl) return null;
  const el = bubbleElFromMessage({ role, content, contexts: [] });
  chatEl.appendChild(el);
  chatEl.scrollTop = chatEl.scrollHeight;
  return el;
}

function renderChat(history) {
  if (!chatEl) return;
  chatEl.innerHTML = "";
  for (const msg of history || []) {
    chatEl.appendChild(bubbleElFromMessage(msg));
  }
  chatEl.scrollTop = chatEl.scrollHeight;
}

function renderConversationList() {
  if (!convoListEl) return;
  convoListEl.innerHTML = "";

  const ordered = [...state.conversations].sort((a, b) => {
    const ta = a.updated_at || a.created_at || "";
    const tb = b.updated_at || b.created_at || "";
    return tb.localeCompare(ta);
  });

  ordered.forEach((c) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "convo-item" + (c.id === state.activeId ? " active" : "");
    item.setAttribute("data-id", c.id);

    const title = c.title || "Untitled";
    const preview =
      c.history && c.history.length
        ? String(c.history[c.history.length - 1].content || "").slice(0, 60)
        : "No messages yet";

    item.innerHTML = `
      <div class="convo-title">${escapeHtml(title)}</div>
      <div class="convo-preview">${escapeHtml(preview)}</div>
    `;

    item.addEventListener("click", () => setActiveConversation(c.id));
    convoListEl.appendChild(item);
  });
}

/* -----------------------------
   Settings sync per conversation
------------------------------ */
function applyConversationSettingsToUI(conv) {
  const s = conv?.settings || {};
  if (persistDirInput) persistDirInput.value = s.persist_dir ?? "./rag_db";
  if (collectionNameInput) collectionNameInput.value = s.collection_name ?? "papers";
  if (kInput) kInput.value = String(s.k ?? 5);
  if (showContextInput) showContextInput.checked = Boolean(s.return_context ?? true);
}

function readSettingsFromUI() {
  return {
    persist_dir: persistDirInput?.value || "./rag_db",
    collection_name: collectionNameInput?.value || "papers",
    k: Number(kInput?.value || 5),
    return_context: Boolean(showContextInput?.checked),
  };
}

function syncSettingsToActiveConversation() {
  const conv = getActiveConversation();
  if (!conv) return;
  conv.settings = readSettingsFromUI();
  conv.updated_at = nowIso();
  saveState();
  renderConversationList();
}

function setActiveConversation(id) {
  const conv = state.conversations.find((c) => c.id === id);
  if (!conv) return;

  state.activeId = id;
  saveState();

  setError(null);
  renderConversationList();
  applyConversationSettingsToUI(conv);
  renderChat(conv.history || []);
}

/* -----------------------------
   API calls
------------------------------ */
async function askApi(message, priorHistory, settings) {
  setError(null);

  const payload = {
    message,
    history: priorHistory || [],
    persist_dir: settings.persist_dir,
    collection_name: settings.collection_name,
    k: settings.k,
    return_context: settings.return_context,
  };

  const resp = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Server error (${resp.status}): ${text}`);
  }

  return resp.json();
}

async function runIndexing() {
  const files = pdfFilesInput?.files;
  if (!files || files.length === 0) {
    setIndexStatus("Select one or more PDF files first.", "error");
    return;
  }

  setError(null);
  setIndexStatus("Uploading PDFs and building index. This can take a few minutes for large files...", null);
  if (indexBtn) indexBtn.disabled = true;

  try {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);

    const settings = readSettingsFromUI();
    fd.append("persist_dir", settings.persist_dir);
    fd.append("collection_name", settings.collection_name);

    const resp = await fetch("/api/index", { method: "POST", body: fd });
    const data = await resp.json().catch(() => ({}));

    if (!resp.ok || !data.ok) {
      const msg = data.error || `Indexing failed (HTTP ${resp.status}).`;
      setIndexStatus(msg, "error");
      if (data.errors && data.errors.length) {
        setIndexStatus(
          msg + "\n\nDetails:\n" + data.errors.map((e) => `- ${e.file}: ${e.error}`).join("\n"),
          "error"
        );
      }
      return;
    }

    const summary =
      `Done.\n` +
      `PDFs saved: ${data.pdfs_saved}\n` +
      `PDFs converted to TEI: ${data.pdfs_converted}\n` +
      `Chunks indexed: ${data.chunks_indexed}\n` +
      `Collection: ${data.collection_name}\n` +
      `Persist dir: ${data.persist_dir}\n` +
      `Ingest run: ${data.ingest_run}`;

    setIndexStatus(summary, "ok");
    if (pdfFilesInput) pdfFilesInput.value = "";
  } catch (err) {
    setIndexStatus(err?.message || String(err), "error");
  } finally {
    if (indexBtn) indexBtn.disabled = false;
  }
}

/* -----------------------------
   Events
------------------------------ */
if (toggleSidebarBtn) {
  toggleSidebarBtn.addEventListener("click", () => {
    const collapsed = layoutEl?.classList.contains("sidebar-collapsed");
    setSidebarCollapsed(!collapsed);
  });
}

if (showSidebarFloatingBtn) {
  showSidebarFloatingBtn.addEventListener("click", () => setSidebarCollapsed(false));
}

if (form) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const conv = getActiveConversation();
    if (!conv) return;

    const message = (messageInput?.value || "").trim();
    if (!message) return;

    // save latest settings
    conv.settings = readSettingsFromUI();

    const priorHistory = (conv.history || []).slice();

    // optimistic UI
    addBubble("user", message);
    const thinkingEl = addBubble("assistant", "Thinking…");

    if (messageInput) {
      messageInput.value = "";
      messageInput.focus();
    }

    try {
      const data = await askApi(message, priorHistory, conv.settings);

      // Use server history as canonical
      conv.history = Array.isArray(data.history) ? data.history : (conv.history || []);
      conv.updated_at = nowIso();

      // Auto-title after first exchange
      if ((conv.title === "New chat" || !conv.title) && conv.history.length >= 2) {
        const firstUserMsg = conv.history.find((m) => m.role === "user");
        if (firstUserMsg?.content) conv.title = autoTitleFromMessage(firstUserMsg.content);
      }

      saveState();
      renderConversationList();
      renderChat(conv.history);
      setError(null);
    } catch (err) {
      if (thinkingEl && thinkingEl.parentNode) thinkingEl.parentNode.removeChild(thinkingEl);
      setError(err?.message || String(err));
    }
  });
}

if (clearBtn) {
  clearBtn.addEventListener("click", () => {
    const conv = getActiveConversation();
    if (!conv) return;
    conv.history = [];
    conv.updated_at = nowIso();
    saveState();
    renderConversationList();
    renderChat(conv.history);
    setError(null);
    messageInput?.focus();
  });
}

if (indexBtn) indexBtn.addEventListener("click", runIndexing);

if (newChatBtn) {
  newChatBtn.addEventListener("click", () => {
    const c = defaultConversation();
    c.settings = readSettingsFromUI();
    state.conversations.push(c);
    state.activeId = c.id;
    saveState();

    renderConversationList();
    applyConversationSettingsToUI(c);
    renderChat(c.history);
    setError(null);
    messageInput?.focus();
  });
}

if (renameChatBtn) {
  renameChatBtn.addEventListener("click", () => {
    const conv = getActiveConversation();
    if (!conv) return;

    const current = conv.title || "New chat";
    const next = prompt("Rename conversation:", current);
    if (!next) return;

    conv.title = next.trim().slice(0, 80) || current;
    conv.updated_at = nowIso();
    saveState();
    renderConversationList();
  });
}

if (deleteChatBtn) {
  deleteChatBtn.addEventListener("click", () => {
    const conv = getActiveConversation();
    if (!conv) return;

    const ok = confirm(`Delete "${conv.title || "this conversation"}"? This cannot be undone.`);
    if (!ok) return;

    state.conversations = state.conversations.filter((c) => c.id !== conv.id);

    if (state.conversations.length === 0) {
      const c = defaultConversation();
      c.settings = readSettingsFromUI();
      state.conversations = [c];
      state.activeId = c.id;
    } else {
      state.activeId = state.conversations[0].id;
    }

    saveState();
    renderConversationList();
    setActiveConversation(state.activeId);
  });
}

/* Persist settings changes into current conversation */
[persistDirInput, collectionNameInput, kInput, showContextInput].forEach((el) => {
  if (!el) return;
  el.addEventListener("change", syncSettingsToActiveConversation);
  el.addEventListener("input", syncSettingsToActiveConversation);
});

/* -----------------------------
   Init
------------------------------ */
ensureState();
renderConversationList();
setActiveConversation(state.activeId);
initSidebarState();
