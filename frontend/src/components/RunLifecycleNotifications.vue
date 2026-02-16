<template>
  <div class="notification-root">
    <section v-if="toasts.length" class="toast-stack" aria-live="polite" aria-label="Run lifecycle notifications">
      <article v-for="item in toasts" :key="`toast-${item.id}`" class="toast-item">
        <div class="toast-top">
          <strong>{{ item.title }}</strong>
          <button type="button" class="icon-btn" @click="dismissToast(item.id)">x</button>
        </div>
        <p class="toast-message">{{ item.message }}</p>
        <div class="toast-meta">
          <RouterLink :to="`/codex/runs/${item.run_id}`" @click="markSeen(item.id)">Open run details</RouterLink>
          <span :class="statusChipClass(item.status)">{{ item.status }}</span>
        </div>
      </article>
    </section>

    <aside class="inbox-shell">
      <button type="button" class="inbox-toggle" :aria-expanded="inboxOpen ? 'true' : 'false'" aria-controls="run-notification-inbox" @click="toggleInbox">
        Notifications
        <span v-if="unseenCount" class="inbox-count">{{ unseenCount }}</span>
      </button>

      <section v-if="inboxOpen" id="run-notification-inbox" class="inbox-panel" aria-label="Notifications inbox">
        <header class="inbox-head">
          <p>Run Notifications</p>
          <div class="inbox-actions">
            <button class="mini-btn" :disabled="!notifications.length" @click="markAllSeen">Mark all seen</button>
            <button class="mini-btn" :disabled="!notifications.length" @click="clearNotifications">Clear</button>
          </div>
        </header>

        <p class="inbox-user">User: <code>{{ userId }}</code></p>
        <p v-if="loadError" class="inbox-error" role="alert">{{ loadError }}</p>

        <p v-if="loading && !notifications.length" class="empty">Loading notifications...</p>
        <ul v-else-if="notifications.length" class="inbox-list">
          <li
            v-for="item in notifications"
            :key="item.id"
            :class="item.seen ? 'inbox-item' : 'inbox-item inbox-item-unseen'"
          >
            <div class="inbox-item-top">
              <RouterLink :to="`/codex/runs/${item.run_id}`" @click="markSeen(item.id)">{{ item.title }}</RouterLink>
              <span :class="statusChipClass(item.status)">{{ item.status }}</span>
            </div>
            <p class="inbox-message">{{ item.message }}</p>
            <div class="inbox-item-meta">
              <span>{{ formatDate(item.created_at) }}</span>
              <button class="mini-btn" :disabled="item.seen" @click="markSeen(item.id)">Mark seen</button>
            </div>
          </li>
        </ul>
        <p v-else class="empty">No notifications yet.</p>
      </section>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import { RunItem, RunListResponse, RunStatus, statusChipClass } from "../lib/runs";

interface RunNotificationItem {
  id: string;
  run_id: string;
  title: string;
  status: RunStatus;
  message: string;
  created_at: string;
  seen: boolean;
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const USER_ID_STORAGE_KEY = "codex.user_id";
const NOTIFICATION_STORAGE_PREFIX = "codex.run_notifications.v1";
const WATCHED_STATUSES = new Set(["preview_ready", "failed", "merged", "canceled"]);

const notifications = ref<RunNotificationItem[]>([]);
const toasts = ref<RunNotificationItem[]>([]);
const inboxOpen = ref(false);
const loading = ref(false);
const loadError = ref("");
const userId = ref("local-user");
const previousRunStatusById = ref<Record<string, string>>({});

let initialized = false;
let pollHandle: ReturnType<typeof setInterval> | null = null;
const toastTimeoutById = new Map<string, number>();

const unseenCount = computed(() => notifications.value.filter((item) => !item.seen).length);

function resolveUserId(): string {
  const envUser = typeof import.meta.env.VITE_CODEX_USER_ID === "string" ? import.meta.env.VITE_CODEX_USER_ID.trim() : "";
  const storedUser = window.localStorage.getItem(USER_ID_STORAGE_KEY)?.trim() ?? "";
  const resolved = envUser || storedUser || "local-user";
  window.localStorage.setItem(USER_ID_STORAGE_KEY, resolved);
  return resolved;
}

function notificationsStorageKey(): string {
  return `${NOTIFICATION_STORAGE_PREFIX}.${userId.value}`;
}

function loadNotificationsFromStorage(): void {
  try {
    const raw = window.localStorage.getItem(notificationsStorageKey());
    if (!raw) {
      notifications.value = [];
      return;
    }
    const parsed = JSON.parse(raw) as RunNotificationItem[];
    if (!Array.isArray(parsed)) {
      notifications.value = [];
      return;
    }
    notifications.value = parsed
      .filter((item) => item && typeof item.id === "string" && typeof item.run_id === "string")
      .slice(0, 200);
  } catch {
    notifications.value = [];
  }
}

function persistNotifications(): void {
  window.localStorage.setItem(notificationsStorageKey(), JSON.stringify(notifications.value.slice(0, 200)));
}

function statusMessage(status: RunStatus): string {
  const normalized = status.toLowerCase();
  if (normalized === "preview_ready") {
    return "Run is preview-ready and can be reviewed.";
  }
  if (normalized === "failed") {
    return "Run failed and needs attention.";
  }
  if (normalized === "merged") {
    return "Run was merged successfully.";
  }
  if (normalized === "canceled") {
    return "Run was canceled.";
  }
  return `Run transitioned to ${status}.`;
}

function createNotificationFromRun(run: RunItem): RunNotificationItem {
  return {
    id: `${run.id}:${run.status}:${run.updated_at}`,
    run_id: run.id,
    title: run.title,
    status: run.status,
    message: statusMessage(run.status),
    created_at: run.updated_at,
    seen: false,
  };
}

function enqueueToast(item: RunNotificationItem): void {
  toasts.value = [item, ...toasts.value.filter((toast) => toast.id !== item.id)].slice(0, 4);

  const existingTimeout = toastTimeoutById.get(item.id);
  if (existingTimeout) {
    window.clearTimeout(existingTimeout);
  }

  const timeoutId = window.setTimeout(() => {
    dismissToast(item.id);
  }, 6500);
  toastTimeoutById.set(item.id, timeoutId);
}

function addNotification(item: RunNotificationItem): void {
  const existing = notifications.value.find((entry) => entry.id === item.id);
  if (existing) {
    return;
  }

  notifications.value = [item, ...notifications.value].slice(0, 200);
  persistNotifications();
  enqueueToast(item);
}

function markSeen(id: string): void {
  let changed = false;
  notifications.value = notifications.value.map((item) => {
    if (item.id !== id || item.seen) {
      return item;
    }
    changed = true;
    return {
      ...item,
      seen: true,
    };
  });

  if (changed) {
    persistNotifications();
  }
  dismissToast(id);
}

function markAllSeen(): void {
  notifications.value = notifications.value.map((item) => ({
    ...item,
    seen: true,
  }));
  persistNotifications();
  toasts.value = [];
  toastTimeoutById.forEach((timeoutId) => {
    window.clearTimeout(timeoutId);
  });
  toastTimeoutById.clear();
}

function dismissToast(id: string): void {
  toasts.value = toasts.value.filter((item) => item.id !== id);
  const timeoutId = toastTimeoutById.get(id);
  if (timeoutId) {
    window.clearTimeout(timeoutId);
    toastTimeoutById.delete(id);
  }
}

function clearNotifications(): void {
  notifications.value = [];
  persistNotifications();
  toasts.value = [];
  toastTimeoutById.forEach((timeoutId) => {
    window.clearTimeout(timeoutId);
  });
  toastTimeoutById.clear();
}

function toggleInbox(): void {
  inboxOpen.value = !inboxOpen.value;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

async function refreshRunsForNotifications(): Promise<void> {
  if (!initialized) {
    loading.value = true;
  }
  loadError.value = "";

  const params = new URLSearchParams({
    limit: "200",
    offset: "0",
  });

  try {
    const response = await fetch(`${apiBaseUrl}/api/runs?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Run notifications fetch failed (${response.status})`);
    }

    const payload = (await response.json()) as RunListResponse;
    const nextStatusMap: Record<string, string> = {};

    payload.items.forEach((run) => {
      const currentStatus = run.status.toLowerCase();
      const previousStatus = previousRunStatusById.value[run.id]?.toLowerCase();

      nextStatusMap[run.id] = run.status;

      if (!WATCHED_STATUSES.has(currentStatus)) {
        return;
      }

      if (!initialized) {
        return;
      }

      if (previousStatus === currentStatus) {
        return;
      }

      addNotification(createNotificationFromRun(run));
    });

    previousRunStatusById.value = nextStatusMap;
    initialized = true;
  } catch (error) {
    loadError.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

function handleInboxHotkeys(event: KeyboardEvent): void {
  if (event.key === "Escape" && inboxOpen.value) {
    event.preventDefault();
    inboxOpen.value = false;
  }
}

onMounted(() => {
  userId.value = resolveUserId();
  loadNotificationsFromStorage();

  void refreshRunsForNotifications();
  pollHandle = setInterval(() => {
    void refreshRunsForNotifications();
  }, 5000);
  window.addEventListener("keydown", handleInboxHotkeys);
});

onUnmounted(() => {
  if (pollHandle) {
    clearInterval(pollHandle);
  }
  window.removeEventListener("keydown", handleInboxHotkeys);

  toastTimeoutById.forEach((timeoutId) => {
    window.clearTimeout(timeoutId);
  });
  toastTimeoutById.clear();
});
</script>

<style scoped>
.notification-root {
  position: fixed;
  z-index: 60;
  inset: 0;
  pointer-events: none;
}

.toast-stack {
  position: fixed;
  top: 1rem;
  right: 1rem;
  width: min(360px, calc(100vw - 2rem));
  display: grid;
  gap: 0.6rem;
  pointer-events: auto;
}

.toast-item {
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  background: #ffffff;
  padding: 0.7rem;
  box-shadow: 0 16px 28px rgba(15, 23, 42, 0.25);
  display: grid;
  gap: 0.45rem;
}

.toast-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.45rem;
}

.icon-btn {
  border: 0;
  background: transparent;
  color: #334155;
  font-size: 0.85rem;
  cursor: pointer;
}

.toast-message {
  margin: 0;
  color: #475569;
  font-size: 0.85rem;
}

.toast-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}

.toast-meta a {
  color: #0f766e;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.84rem;
}

.toast-meta a:hover {
  text-decoration: underline;
}

.inbox-shell {
  position: fixed;
  left: 1rem;
  bottom: 1rem;
  width: min(420px, calc(100vw - 2rem));
  pointer-events: auto;
  display: grid;
  gap: 0.5rem;
}

.inbox-toggle {
  justify-self: start;
  border: 0;
  border-radius: 999px;
  background: #0f172a;
  color: #f8fafc;
  padding: 0.45rem 0.8rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.inbox-count {
  border-radius: 999px;
  background: #ef4444;
  color: #ffffff;
  padding: 0.1rem 0.45rem;
  font-size: 0.74rem;
}

.inbox-panel {
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 16px 28px rgba(15, 23, 42, 0.2);
  padding: 0.7rem;
  display: grid;
  gap: 0.6rem;
  max-height: min(520px, 68vh);
}

.inbox-head {
  display: flex;
  justify-content: space-between;
  gap: 0.6rem;
  align-items: center;
}

.inbox-head p {
  margin: 0;
  font-weight: 600;
}

.inbox-actions {
  display: flex;
  gap: 0.4rem;
}

.inbox-user {
  margin: 0;
  color: #64748b;
  font-size: 0.78rem;
}

.inbox-error {
  margin: 0;
  color: #b91c1c;
  font-size: 0.82rem;
}

.inbox-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.55rem;
  overflow: auto;
}

.inbox-item {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  padding: 0.55rem;
  display: grid;
  gap: 0.4rem;
}

.inbox-item-unseen {
  border-color: #1d4ed8;
  background: #eff6ff;
}

.inbox-item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.55rem;
}

.inbox-item-top a {
  text-decoration: none;
  color: #0f172a;
  font-weight: 600;
}

.inbox-item-top a:hover {
  text-decoration: underline;
}

.inbox-message {
  margin: 0;
  color: #475569;
  font-size: 0.84rem;
}

.inbox-item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
  color: #64748b;
  font-size: 0.78rem;
}

.mini-btn {
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  border-radius: 8px;
  padding: 0.25rem 0.45rem;
  font-size: 0.74rem;
  cursor: pointer;
}

.mini-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.empty {
  margin: 0;
  color: #64748b;
  font-size: 0.84rem;
}

.chip {
  border-radius: 999px;
  padding: 0.14rem 0.45rem;
  font-size: 0.72rem;
  font-weight: 600;
  border: 1px solid transparent;
}

.chip-neutral {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #334155;
}

.chip-success {
  background: #dcfce7;
  border-color: #86efac;
  color: #166534;
}

.chip-warn {
  background: #fef3c7;
  border-color: #fcd34d;
  color: #92400e;
}

.chip-danger {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #991b1b;
}

@media (max-width: 760px) {
  .toast-stack,
  .inbox-shell {
    width: calc(100vw - 1rem);
    right: 0.5rem;
    left: 0.5rem;
  }

  .inbox-panel {
    max-height: min(440px, 60vh);
  }
}
</style>
