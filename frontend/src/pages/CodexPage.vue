<template>
  <div class="codex-page">
    <header class="hero">
      <p class="eyebrow">Ouroboros</p>
      <h1>Codex Runs Inbox</h1>
      <p class="subhead">Create a run request, watch status updates, and refresh inbox data in real time.</p>
    </header>

    <section class="panel">
      <h2>Create Run</h2>
      <form class="composer" @submit.prevent="submitPrompt">
        <label>
          Prompt
          <textarea v-model="prompt" rows="5" placeholder="Describe the change you want to make" required />
        </label>

        <div class="row">
          <label>
            Route Context
            <input v-model="route" type="text" placeholder="/codex" />
          </label>
          <label>
            Note
            <input v-model="note" type="text" placeholder="Optional reviewer note" />
          </label>
        </div>

        <label>
          Metadata (JSON)
          <input v-model="metadataText" type="text" placeholder='{"source":"codex-page"}' />
        </label>

        <div class="actions">
          <button :disabled="submitting" type="submit">{{ submitting ? "Submitting..." : "Submit Prompt" }}</button>
          <span class="hint">POST /api/runs</span>
        </div>

        <p v-if="submitError" class="error">{{ submitError }}</p>
      </form>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>Runs Inbox</h2>
        <div class="panel-controls">
          <label>
            Status Filter
            <select v-model="statusFilter" @change="refreshRuns">
              <option value="">All</option>
              <option v-for="status in commonStatuses" :key="status" :value="status">{{ status }}</option>
            </select>
          </label>
          <button @click="refreshRuns">Refresh</button>
        </div>
      </div>

      <div class="route-filter-row">
        <label>
          Route Filter
          <input
            v-model="routeFilter"
            type="text"
            placeholder="/codex"
          />
        </label>
        <button @click="applyCurrentRouteFilter">Use Current Route</button>
        <button @click="clearRouteFilter">Clear Route Filter</button>
      </div>

      <div class="meta-row">
        <span>Total: {{ total }}</span>
        <span>Visible: {{ visibleRuns.length }}</span>
        <span>Offset: {{ offset }}</span>
        <span>Limit: {{ limit }}</span>
        <span>Last sync: {{ lastSyncLabel }}</span>
      </div>

      <div v-if="currentRouteRuns.length" class="related-panel">
        <p class="related-head">
          Related to current route <code>{{ currentRoutePath }}</code>
        </p>
        <ul class="related-links">
          <li v-for="run in currentRouteRuns.slice(0, 5)" :key="`related-${run.id}`">
            <RouterLink :to="`/codex/runs/${run.id}`">{{ run.title }}</RouterLink>
            <span :class="statusChipClass(run.status)">{{ run.status }}</span>
          </li>
        </ul>
      </div>

      <ul v-if="visibleRuns.length" class="runs-list">
        <li v-for="run in visibleRuns" :key="run.id" class="run-item">
          <div class="run-top">
            <strong>{{ run.title }}</strong>
            <div class="run-actions">
              <RouterLink class="details-link" :to="`/codex/runs/${run.id}`">View details</RouterLink>
              <span :class="statusChipClass(run.status)">{{ run.status }}</span>
            </div>
          </div>
          <p class="run-prompt">{{ run.prompt }}</p>
          <div class="run-meta">
            <span>ID: {{ run.id }}</span>
            <span>Route: <code>{{ getRunRoute(run) }}</code></span>
            <span v-if="isRunRelatedToRoute(getRunRoute(run), currentRoutePath)" class="route-badge">On this page</span>
            <span>Note: {{ run.context?.note || "-" }}</span>
          </div>
        </li>
      </ul>
      <p v-else class="empty">No runs found for current filter settings.</p>

      <div class="pager">
        <button :disabled="offset === 0" @click="prevPage">Previous</button>
        <button :disabled="offset + limit >= total" @click="nextPage">Next</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  filterRunsByRoute,
  getRunRoute,
  isRunRelatedToRoute,
  makeRunTitle,
  normalizeRoutePath,
  RunItem,
  RunListResponse,
  statusChipClass,
} from "../lib/runs";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const viewRoute = useRoute();

const prompt = ref("");
const route = ref("/codex");
const note = ref("");
const metadataText = ref('{"source":"codex-page"}');
const submitting = ref(false);
const submitError = ref("");

const runs = ref<RunItem[]>([]);
const total = ref(0);
const limit = ref(10);
const offset = ref(0);
const statusFilter = ref("");
const routeFilter = ref("");
const lastSync = ref<Date | null>(null);

const commonStatuses = [
  "queued",
  "planning",
  "editing",
  "testing",
  "preview_ready",
  "needs_approval",
  "approved",
  "merging",
  "deploying",
  "merged",
  "failed",
  "canceled",
  "expired",
];

const lastSyncLabel = computed(() => {
  if (!lastSync.value) {
    return "not yet";
  }
  return lastSync.value.toLocaleTimeString();
});
const currentRoutePath = computed(() => normalizeRoutePath(viewRoute.fullPath || viewRoute.path));
const visibleRuns = computed(() => {
  const filterRoute = routeFilter.value.trim();
  if (!filterRoute) {
    return runs.value;
  }
  return filterRunsByRoute(runs.value, filterRoute);
});
const currentRouteRuns = computed(() => filterRunsByRoute(runs.value, currentRoutePath.value));

let pollHandle: ReturnType<typeof setInterval> | null = null;

function parseMetadata(): Record<string, unknown> | undefined {
  const raw = metadataText.value.trim();
  if (!raw) {
    return undefined;
  }

  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Metadata JSON must be an object");
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(`Invalid metadata JSON: ${(error as Error).message}`);
  }
}

async function submitPrompt() {
  submitError.value = "";
  submitting.value = true;

  try {
    const metadata = parseMetadata();
    const payload = {
      title: makeRunTitle(prompt.value),
      prompt: prompt.value,
      route: route.value || undefined,
      note: note.value || undefined,
      metadata,
    };

    const response = await fetch(`${apiBaseUrl}/api/runs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Run create failed (${response.status})`);
    }

    prompt.value = "";
    note.value = "";
    await refreshRuns();
  } catch (error) {
    submitError.value = (error as Error).message;
  } finally {
    submitting.value = false;
  }
}

async function refreshRuns() {
  const params = new URLSearchParams({
    limit: String(limit.value),
    offset: String(offset.value),
  });

  if (statusFilter.value) {
    params.append("status", statusFilter.value);
  }
  const filterRoute = routeFilter.value.trim();
  if (filterRoute) {
    params.append("route", normalizeRoutePath(filterRoute));
  }

  const response = await fetch(`${apiBaseUrl}/api/runs?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Run list fetch failed (${response.status})`);
  }

  const payload = (await response.json()) as RunListResponse;
  runs.value = payload.items;
  total.value = payload.total;
  limit.value = payload.limit;
  offset.value = payload.offset;
  lastSync.value = new Date();
}

function applyCurrentRouteFilter() {
  routeFilter.value = currentRoutePath.value;
  offset.value = 0;
  void refreshRuns();
}

function clearRouteFilter() {
  if (!routeFilter.value) {
    return;
  }
  routeFilter.value = "";
  offset.value = 0;
  void refreshRuns();
}

function syncRouteFilterFromQuery() {
  const value = viewRoute.query.route;
  if (typeof value === "string" && value.trim()) {
    routeFilter.value = normalizeRoutePath(value);
    return;
  }
  routeFilter.value = "";
}

async function nextPage() {
  if (offset.value + limit.value >= total.value) {
    return;
  }
  offset.value += limit.value;
  await refreshRuns();
}

async function prevPage() {
  if (offset.value === 0) {
    return;
  }
  offset.value = Math.max(0, offset.value - limit.value);
  await refreshRuns();
}

onMounted(async () => {
  syncRouteFilterFromQuery();
  await refreshRuns();
  pollHandle = setInterval(() => {
    void refreshRuns();
  }, 5000);
});

watch(
  () => viewRoute.query.route,
  () => {
    syncRouteFilterFromQuery();
    offset.value = 0;
    void refreshRuns();
  },
);

onUnmounted(() => {
  if (pollHandle) {
    clearInterval(pollHandle);
  }
});
</script>

<style scoped>
.codex-page {
  max-width: 980px;
  margin: 0 auto;
  padding: 2.5rem 1.2rem 3rem;
  display: grid;
  gap: 1.2rem;
}

.hero {
  background: linear-gradient(120deg, #0f172a, #164e63);
  color: #e2e8f0;
  border-radius: 14px;
  padding: 1.4rem 1.6rem;
}

.eyebrow {
  margin: 0;
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  opacity: 0.8;
}

.hero h1 {
  margin: 0.2rem 0 0.4rem;
}

.subhead {
  margin: 0;
  opacity: 0.9;
}

.panel {
  background: #ffffff;
  border: 1px solid #d9e2ec;
  border-radius: 12px;
  padding: 1rem;
}

.panel h2 {
  margin-top: 0;
}

.composer {
  display: grid;
  gap: 0.8rem;
}

.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.8rem;
}

label {
  display: grid;
  gap: 0.35rem;
  font-size: 0.9rem;
  color: #334155;
}

textarea,
input,
select,
button {
  font: inherit;
}

textarea,
input,
select {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0.55rem 0.65rem;
  background: #f8fafc;
}

button {
  border: 0;
  background: #0f766e;
  color: #f8fafc;
  border-radius: 10px;
  padding: 0.55rem 0.9rem;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.hint {
  color: #64748b;
  font-size: 0.84rem;
}

.error {
  margin: 0;
  color: #b91c1c;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.panel-controls {
  display: flex;
  align-items: end;
  gap: 0.6rem;
}

.route-filter-row {
  margin-bottom: 0.8rem;
  display: flex;
  align-items: end;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.route-filter-row label {
  min-width: 240px;
  flex: 1;
}

.meta-row {
  display: flex;
  gap: 0.8rem;
  color: #64748b;
  font-size: 0.84rem;
  margin-bottom: 0.8rem;
  flex-wrap: wrap;
}

.related-panel {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  border-radius: 10px;
  padding: 0.7rem;
  margin-bottom: 0.8rem;
}

.related-head {
  margin: 0 0 0.45rem;
  color: #1e3a8a;
  font-size: 0.85rem;
}

.related-links {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.4rem;
}

.related-links li {
  display: flex;
  justify-content: space-between;
  gap: 0.55rem;
  align-items: center;
}

.related-links a {
  color: #1d4ed8;
  font-weight: 600;
  text-decoration: none;
}

.related-links a:hover {
  text-decoration: underline;
}

.runs-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 0.6rem;
}

.run-item {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  padding: 0.75rem;
  background: #f8fbff;
}

.run-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
}

.run-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.details-link {
  color: #0f766e;
  font-size: 0.82rem;
  font-weight: 600;
}

.run-prompt {
  margin: 0.5rem 0;
  color: #334155;
}

.run-meta {
  display: flex;
  gap: 0.8rem;
  color: #64748b;
  font-size: 0.82rem;
  flex-wrap: wrap;
}

.route-badge {
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 600;
  background: #dbeafe;
  border: 1px solid #93c5fd;
  color: #1e40af;
}

.chip {
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.76rem;
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

.empty {
  margin: 0;
  color: #64748b;
}

.pager {
  margin-top: 0.8rem;
  display: flex;
  gap: 0.5rem;
}

@media (max-width: 800px) {
  .row,
  .panel-head {
    grid-template-columns: 1fr;
    display: grid;
  }

  .panel-controls {
    align-items: stretch;
  }

  .route-filter-row {
    align-items: stretch;
  }
}
</style>
