<template>
  <aside class="route-badge-shell" aria-live="polite">
    <button
      type="button"
      class="route-badge-toggle"
      :aria-expanded="panelOpen ? 'true' : 'false'"
      aria-controls="route-runs-panel"
      @click="togglePanel"
    >
      {{ t("routeRuns.toggle") }}
      <span class="route-badge-count">{{ relatedRuns.length }}</span>
    </button>

    <section v-if="panelOpen" id="route-runs-panel" class="route-badge-panel">
      <div class="route-badge-head">
        <p class="route-badge-title">{{ t("routeRuns.toggle") }}</p>
        <button type="button" class="route-badge-minimize" @click="closePanel">{{ t("routeRuns.hide") }}</button>
      </div>
      <p class="route-badge-path">{{ normalizedCurrentRoute }}</p>
      <p v-if="loadError" class="route-badge-error" role="alert">{{ loadError }}</p>

      <p v-if="loading && !relatedRuns.length" class="route-badge-empty">{{ t("routeRuns.loading") }}</p>
      <ul v-else-if="relatedRuns.length" class="route-badge-links">
        <li v-for="run in relatedRuns.slice(0, 4)" :key="run.id">
          <RouterLink :to="`/codex/runs/${run.id}`">
            {{ run.title }}
          </RouterLink>
          <span :class="statusChipClass(run.status)">{{ run.status }}</span>
        </li>
      </ul>
      <p v-else class="route-badge-empty">{{ t("routeRuns.empty") }}</p>

      <RouterLink
        v-if="relatedRuns.length"
        class="route-badge-more"
        :to="`/codex?route=${encodeURIComponent(normalizedCurrentRoute)}`"
      >
        {{ t("routeRuns.openRelated") }}
      </RouterLink>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  filterRunsByRoute,
  normalizeRoutePath,
  RunItem,
  RunListResponse,
  statusChipClass,
} from "../lib/runs";
import { useI18n } from "../lib/i18n";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const PANEL_OPEN_STORAGE_KEY = "codex.route_runs.open";

const route = useRoute();
const { t } = useI18n();
const runs = ref<RunItem[]>([]);
const loading = ref(false);
const loadError = ref("");
const panelOpen = ref(false);
let pollHandle: ReturnType<typeof setInterval> | null = null;

const normalizedCurrentRoute = computed(() => normalizeRoutePath(route.fullPath || route.path));
const relatedRuns = computed(() => filterRunsByRoute(runs.value, normalizedCurrentRoute.value));

async function refreshRuns() {
  loading.value = true;
  loadError.value = "";

  const params = new URLSearchParams({
    limit: "200",
    offset: "0",
  });

  try {
    const response = await fetch(`${apiBaseUrl}/api/runs?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Runs fetch failed (${response.status})`);
    }

    const payload = (await response.json()) as RunListResponse;
    runs.value = payload.items;
  } catch (error) {
    loadError.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

function persistPanelState(): void {
  window.localStorage.setItem(PANEL_OPEN_STORAGE_KEY, panelOpen.value ? "1" : "0");
}

function togglePanel(): void {
  panelOpen.value = !panelOpen.value;
  persistPanelState();
}

function closePanel(): void {
  panelOpen.value = false;
  persistPanelState();
}

watch(
  () => route.fullPath,
  () => {
    void refreshRuns();
  },
);

onMounted(() => {
  panelOpen.value = window.localStorage.getItem(PANEL_OPEN_STORAGE_KEY) === "1";
  void refreshRuns();
  pollHandle = setInterval(() => {
    void refreshRuns();
  }, 6000);
});

onUnmounted(() => {
  if (pollHandle) {
    clearInterval(pollHandle);
  }
});
</script>

<style scoped>
.route-badge-shell {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 40;
  display: grid;
  gap: 0.55rem;
  justify-items: end;
}

.route-badge-toggle {
  border: 1px solid #1e293b;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 999px;
  padding: 0.5rem 0.8rem;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 14px 30px rgba(2, 6, 23, 0.45);
}

.route-badge-panel {
  width: min(360px, calc(100vw - 2rem));
  background: #0f172a;
  color: #e2e8f0;
  border: 1px solid #1e293b;
  border-radius: 12px;
  padding: 0.8rem;
  display: grid;
  gap: 0.55rem;
  box-shadow: 0 14px 30px rgba(2, 6, 23, 0.45);
}

.route-badge-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.route-badge-title {
  margin: 0;
  font-size: 0.82rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #94a3b8;
}

.route-badge-count {
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  font-size: 0.78rem;
  background: #1d4ed8;
  color: #dbeafe;
}

.route-badge-minimize {
  border: 1px solid #334155;
  background: #0b1327;
  color: #cbd5e1;
  border-radius: 8px;
  padding: 0.16rem 0.45rem;
  font-size: 0.75rem;
  cursor: pointer;
}

.route-badge-path {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.82rem;
  color: #cbd5e1;
}

.route-badge-error {
  margin: 0;
  color: #fca5a5;
  font-size: 0.8rem;
}

.route-badge-empty {
  margin: 0;
  color: #cbd5e1;
  font-size: 0.82rem;
}

.route-badge-links {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.45rem;
}

.route-badge-links li {
  display: flex;
  justify-content: space-between;
  gap: 0.55rem;
  align-items: center;
}

.route-badge-links a {
  color: #e2e8f0;
  text-decoration: none;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-badge-links a:hover {
  text-decoration: underline;
}

.route-badge-more {
  color: #93c5fd;
  font-size: 0.84rem;
  text-decoration: none;
}

.route-badge-more:hover {
  text-decoration: underline;
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
</style>
