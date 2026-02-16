<template>
  <div class="run-details-page">
    <header class="hero">
      <div>
        <p class="eyebrow">Codex Run</p>
        <h1>Run Details</h1>
        <p class="subhead">Timeline, validation checks, logs, and artifacts for a single run.</p>
      </div>
      <RouterLink class="back-link" to="/codex">Back to Inbox</RouterLink>
    </header>

    <section class="panel">
      <div class="panel-head">
        <h2>Run Summary</h2>
        <button :disabled="loading" @click="refreshDetails">{{ loading ? "Refreshing..." : "Refresh" }}</button>
      </div>

      <p v-if="loadError" class="error">{{ loadError }}</p>

      <div v-if="run" class="summary-grid">
        <div>
          <strong>{{ run.title }}</strong>
          <p class="run-prompt">{{ run.prompt }}</p>
        </div>
        <div class="chip-wrap">
          <span :class="statusChipClass(run.status)">{{ run.status }}</span>
        </div>
        <div class="summary-meta">
          <span>ID: {{ run.id }}</span>
          <span>Route: {{ run.context?.route || run.route || "n/a" }}</span>
          <span>Slot: {{ run.slot_id || "n/a" }}</span>
          <span>Branch: {{ run.branch_name || "n/a" }}</span>
          <span>Commit: {{ run.commit_sha || "n/a" }}</span>
          <span>Updated: {{ formatDateTime(run.updated_at) }}</span>
          <span>Last sync: {{ lastSyncLabel }}</span>
        </div>
      </div>
      <p v-else-if="!loading" class="empty">Run details are unavailable.</p>
    </section>

    <section class="panel">
      <h2>Failure Reasons</h2>
      <ul v-if="failureReasons.length" class="failure-list">
        <li v-for="reason in failureReasons" :key="reason">{{ reason }}</li>
      </ul>
      <p v-else class="empty">No failure reasons recorded for this run.</p>
    </section>

    <section class="panel">
      <h2>Validation Checks</h2>
      <ul v-if="checks.length" class="checks-list">
        <li v-for="check in checks" :key="check.id" class="check-item">
          <div class="check-top">
            <strong>{{ check.check_name }}</strong>
            <span :class="statusChipClass(check.status)">{{ check.status }}</span>
          </div>
          <div class="check-meta">
            <span>Started: {{ formatDateTime(check.started_at) }}</span>
            <span>Ended: {{ formatDateTime(check.ended_at) }}</span>
            <span>Duration: {{ formatDuration(check.started_at, check.ended_at) }}</span>
          </div>
          <a v-if="check.artifact_uri" :href="check.artifact_uri" target="_blank" rel="noreferrer">
            Open check artifact/log
          </a>
        </li>
      </ul>
      <p v-else class="empty">No validation checks found for this run.</p>
    </section>

    <section class="panel">
      <h2>Artifact Links</h2>
      <ul v-if="artifactLinks.length" class="artifact-list">
        <li v-for="artifact in artifactLinks" :key="`${artifact.source}:${artifact.uri}`">
          <a :href="artifact.uri" target="_blank" rel="noreferrer">{{ artifact.label }}</a>
          <span class="artifact-source">{{ artifact.source }}</span>
        </li>
      </ul>
      <p v-else class="empty">No artifact links available for this run.</p>
    </section>

    <section class="panel">
      <h2>Timeline</h2>
      <ol v-if="events.length" class="timeline">
        <li v-for="event in events" :key="event.id">
          <div class="event-top">
            <strong>{{ event.event_type }}</strong>
            <span>{{ formatDateTime(event.created_at) }}</span>
          </div>
          <div class="event-meta">
            <span>From: {{ event.status_from || "-" }}</span>
            <span>To: {{ event.status_to || "-" }}</span>
          </div>
          <pre v-if="event.payload" class="event-payload">{{ stringifyPayload(event.payload) }}</pre>
        </li>
      </ol>
      <p v-else class="empty">No timeline events found for this run.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  extractArtifactLinks,
  extractFailureReasons,
  RunEventItem,
  RunItem,
  statusChipClass,
  ValidationCheckItem,
} from "../lib/runs";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const route = useRoute();
const run = ref<RunItem | null>(null);
const events = ref<RunEventItem[]>([]);
const checks = ref<ValidationCheckItem[]>([]);
const loading = ref(true);
const loadError = ref("");
const lastSync = ref<Date | null>(null);

let pollHandle: ReturnType<typeof setInterval> | null = null;

const runId = computed(() => String(route.params.runId ?? ""));
const artifactLinks = computed(() => extractArtifactLinks(checks.value, events.value));
const failureReasons = computed(() => extractFailureReasons(events.value, checks.value));
const lastSyncLabel = computed(() => (lastSync.value ? lastSync.value.toLocaleTimeString() : "not yet"));

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }

  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return value;
  }
  return timestamp.toLocaleString();
}

function formatDuration(startedAt: string | null, endedAt: string | null): string {
  if (!startedAt) {
    return "not started";
  }
  if (!endedAt) {
    return "running";
  }

  const start = new Date(startedAt).getTime();
  const end = new Date(endedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    return "n/a";
  }

  const diffMs = end - start;
  if (diffMs < 1000) {
    return `${diffMs} ms`;
  }
  if (diffMs < 60_000) {
    return `${(diffMs / 1000).toFixed(1)} s`;
  }
  return `${(diffMs / 60_000).toFixed(1)} min`;
}

function stringifyPayload(payload: Record<string, unknown>): string {
  return JSON.stringify(payload, null, 2);
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}) for ${url}`);
  }
  return (await response.json()) as T;
}

async function refreshDetails(options?: { silent?: boolean }) {
  const silent = options?.silent ?? false;
  if (!runId.value) {
    loadError.value = "Invalid run id in route.";
    return;
  }

  if (!silent) {
    loading.value = true;
  }
  loadError.value = "";

  try {
    const [runPayload, eventsPayload, checksPayload] = await Promise.all([
      fetchJson<RunItem>(`${apiBaseUrl}/api/runs/${runId.value}`),
      fetchJson<RunEventItem[]>(`${apiBaseUrl}/api/runs/${runId.value}/events`),
      fetchJson<ValidationCheckItem[]>(`${apiBaseUrl}/api/runs/${runId.value}/checks`),
    ]);

    run.value = runPayload;
    events.value = eventsPayload;
    checks.value = checksPayload;
    lastSync.value = new Date();
  } catch (error) {
    loadError.value = (error as Error).message;
  } finally {
    if (!silent) {
      loading.value = false;
    }
  }
}

watch(runId, () => {
  void refreshDetails();
});

onMounted(() => {
  void refreshDetails();
  pollHandle = setInterval(() => {
    void refreshDetails({ silent: true });
  }, 5000);
});

onUnmounted(() => {
  if (pollHandle) {
    clearInterval(pollHandle);
  }
});
</script>

<style scoped>
.run-details-page {
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
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: start;
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

.back-link {
  color: #e2e8f0;
  font-weight: 600;
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

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.8rem;
}

button {
  border: 0;
  background: #0f766e;
  color: #f8fafc;
  border-radius: 10px;
  padding: 0.55rem 0.9rem;
  cursor: pointer;
  font: inherit;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.summary-grid {
  display: grid;
  gap: 0.75rem;
}

.run-prompt {
  margin: 0.4rem 0 0;
  color: #334155;
}

.chip-wrap {
  display: flex;
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
  color: #64748b;
  font-size: 0.84rem;
}

.checks-list,
.artifact-list,
.failure-list {
  margin: 0;
  padding-left: 1.2rem;
  display: grid;
  gap: 0.55rem;
}

.check-item {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  padding: 0.7rem;
  background: #f8fbff;
  list-style: none;
}

.check-top {
  display: flex;
  justify-content: space-between;
  gap: 0.6rem;
  align-items: center;
}

.check-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
  margin: 0.45rem 0;
  color: #64748b;
  font-size: 0.82rem;
}

.artifact-source {
  color: #64748b;
  margin-left: 0.5rem;
  font-size: 0.8rem;
}

.timeline {
  margin: 0;
  padding-left: 1.2rem;
  display: grid;
  gap: 0.6rem;
}

.timeline li {
  border-left: 3px solid #cbd5e1;
  padding-left: 0.75rem;
  list-style: none;
}

.event-top {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  color: #0f172a;
}

.event-meta {
  margin: 0.35rem 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
  color: #64748b;
  font-size: 0.82rem;
}

.event-payload {
  margin: 0.45rem 0 0;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 0.6rem;
  overflow: auto;
  font-size: 0.78rem;
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

.error {
  margin: 0 0 0.5rem;
  color: #b91c1c;
}

@media (max-width: 800px) {
  .hero {
    grid-template-columns: 1fr;
    display: grid;
  }
}
</style>
