<template>
  <div class="run-details-page" role="main" :aria-busy="loading ? 'true' : 'false'">
    <header class="hero">
      <div>
        <p class="eyebrow">Codex Run</p>
        <h1>Run Details</h1>
        <p class="subhead">Timeline, validation checks, logs, artifacts, and review decisions for a single run.</p>
      </div>
      <div class="hero-links">
        <RouterLink class="back-link" to="/home">Home</RouterLink>
        <RouterLink class="back-link" to="/codex">Back to Inbox</RouterLink>
      </div>
    </header>

    <section class="details-nav panel" aria-label="Run details sections">
      <nav class="details-nav-links">
        <button
          v-for="section in sectionLinks"
          :key="section.id"
          type="button"
          :class="['details-nav-btn', activeSectionId === section.id ? 'details-nav-btn-active' : '']"
          @click="scrollToSection(section.id)"
        >
          {{ section.label }}
        </button>
      </nav>
    </section>

    <section id="summary" class="panel">
      <div class="panel-head">
        <h2>Run Summary</h2>
        <button type="button" :disabled="loading" aria-keyshortcuts="Alt+R" @click="refreshDetails">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </button>
      </div>

      <p v-if="loadError" class="error" role="alert">{{ loadError }}</p>
      <p v-else-if="loading && !run" class="empty">Loading run details...</p>

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

    <section id="change-review" class="panel">
      <h2>Change Review</h2>
      <div class="review-grid">
        <div>
          <h3>File Diff View</h3>
          <ul v-if="fileDiffEntries.length" class="diff-list">
            <li v-for="entry in fileDiffEntries" :key="`${entry.source}:${entry.path}`" class="diff-item">
              <div class="diff-item-head">
                <code>{{ entry.path }}</code>
                <span class="diff-stats">
                  <span class="stat-add">+{{ entry.additions ?? 0 }}</span>
                  <span class="stat-del">-{{ entry.deletions ?? 0 }}</span>
                </span>
              </div>
              <p class="diff-source">Source: {{ entry.source }}</p>
              <details v-if="entry.patch" class="diff-patch">
                <summary>Show patch snippet</summary>
                <pre>{{ entry.patch }}</pre>
              </details>
            </li>
          </ul>
          <p v-else class="empty">No file-level diff payload found yet for this run.</p>
        </div>

        <div class="migration-panel" :class="migrationWarning ? 'migration-warning' : 'migration-safe'">
          <h3>Migration Warning</h3>
          <p v-if="migrationWarning">
            Migration-related files are present in the diff. Require explicit DB review before merge.
          </p>
          <p v-else>No migration files detected in current diff payload.</p>

          <ul v-if="migrationFiles.length" class="migration-list">
            <li v-for="path in migrationFiles" :key="path">
              <code>{{ path }}</code>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section id="failure-reasons" class="panel">
      <h2>Failure Reasons</h2>
      <ul v-if="failureReasons.length" class="failure-list">
        <li v-for="reason in failureReasons" :key="reason">{{ reason }}</li>
      </ul>
      <p v-else class="empty">No failure reasons recorded for this run.</p>
    </section>

    <section id="checks-summary" class="panel">
      <h2>Checks Summary</h2>
      <div class="checks-summary-row">
        <span class="summary-chip summary-chip-neutral">Total {{ checksSummary.total }}</span>
        <span class="summary-chip summary-chip-success">Passed {{ checksSummary.passed }}</span>
        <span class="summary-chip summary-chip-danger">Failed {{ checksSummary.failed }}</span>
        <span class="summary-chip summary-chip-warn">Running {{ checksSummary.running }}</span>
        <span class="summary-chip summary-chip-neutral">Pending {{ checksSummary.pending }}</span>
      </div>
    </section>

    <section id="validation-checks" class="panel">
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
          <a v-if="check.artifact_uri" :href="buildArtifactHref(check.artifact_uri)" target="_blank" rel="noreferrer">
            Open check artifact/log
          </a>
        </li>
      </ul>
      <p v-else class="empty">No validation checks found for this run.</p>
    </section>

    <section id="lifecycle-actions" class="panel">
      <h2>Approval Actions</h2>
      <div class="decision-actions">
        <button class="btn-approve" type="button" :disabled="!canApproveRun || actionBusy" @click="openActionModal('approve')">
          {{ actionBusy ? "Submitting..." : "Approve Run" }}
        </button>
        <button class="btn-reject" type="button" :disabled="!canRejectRun || actionBusy" @click="openActionModal('reject')">
          {{ actionBusy ? "Submitting..." : "Reject Run" }}
        </button>
        <button class="btn-expire" type="button" :disabled="!canExpireRun || actionBusy" @click="openActionModal('expire')">
          {{ actionBusy ? "Submitting..." : "Expire Run" }}
        </button>
        <button class="btn-resume" type="button" :disabled="!canResumeRun || actionBusy" @click="openActionModal('resume')">
          {{ actionBusy ? "Submitting..." : "Resume Run" }}
        </button>
      </div>
      <p class="approval-status">
        Current run status: <strong>{{ run?.status ?? "unknown" }}</strong>
      </p>
      <p class="lifecycle-hint">
        Approve is available in <code>preview_ready</code> and <code>needs_approval</code>. Reject is disabled in <code>merged</code>.
      </p>
      <p class="lifecycle-hint">
        Decision History records approve/reject actions. Expire/resume appear in Timeline events.
      </p>

      <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
      <p v-if="actionSuccess" class="success" role="status">{{ actionSuccess }}</p>

      <h3>Decision History</h3>
      <ul v-if="approvals.length" class="approvals-list">
        <li v-for="approval in approvals" :key="approval.id" class="approval-item">
          <div class="approval-top">
            <span :class="statusChipClass(approval.decision)">{{ approval.decision }}</span>
            <span>{{ formatDateTime(approval.created_at) }}</span>
          </div>
          <p class="approval-meta">Reviewer: {{ approval.reviewer_id || "n/a" }}</p>
          <p v-if="approval.reason" class="approval-reason">{{ approval.reason }}</p>
        </li>
      </ul>
      <p v-else class="empty">No approvals/rejections recorded for this run yet.</p>
    </section>

    <div
      v-if="activeActionModal"
      class="action-modal-overlay"
      role="presentation"
      @click.self="closeActionModal"
      @keydown="handleModalKeydown"
    >
      <section
        ref="modalDialogRef"
        :class="['action-modal', `action-modal-${activeActionModal}`]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="action-modal-title"
      >
        <div class="action-modal-head">
          <h3 id="action-modal-title">{{ actionModalTitle }}</h3>
          <button class="btn-modal-close" type="button" :disabled="actionBusy" aria-label="Close dialog" @click="closeActionModal">
            Close
          </button>
        </div>

        <p class="action-modal-subhead">{{ actionModalSubhead }}</p>

        <div v-if="activeActionModal === 'approve'" class="action-modal-grid">
          <label>
            Reviewer ID (optional)
            <input v-model="reviewerId" data-autofocus type="text" placeholder="reviewer user id" />
          </label>
          <label>
            Approve reason (optional)
            <textarea v-model="approveReason" rows="2" placeholder="Reason for approval" />
          </label>
        </div>

        <div v-if="activeActionModal === 'reject'" class="action-modal-grid">
          <label>
            Reviewer ID (optional)
            <input v-model="reviewerId" data-autofocus type="text" placeholder="reviewer user id" />
          </label>
          <label>
            Reject reason (required)
            <textarea v-model="rejectReason" rows="2" placeholder="Reason for rejection" />
          </label>
          <label>
            Failure reason code
            <select v-model="rejectFailureReasonCode">
              <option v-for="code in failureReasonCodes" :key="code" :value="code">{{ code }}</option>
            </select>
          </label>
        </div>

        <div v-if="activeActionModal === 'expire'" class="action-modal-grid">
          <label>
            Expire reason (optional)
            <input v-model="expireReason" data-autofocus type="text" placeholder="Reason for manual expiration" />
          </label>
        </div>

        <div v-if="activeActionModal === 'resume'" class="action-modal-grid">
          <p class="lifecycle-hint">This creates a queued child run from the current failed/expired run.</p>
        </div>

        <p v-if="modalError" class="error" role="alert">{{ modalError }}</p>
        <p v-if="modalSuccess" class="success" role="status">{{ modalSuccess }}</p>

        <div class="action-modal-actions">
          <button class="btn-secondary" type="button" :disabled="actionBusy" @click="closeActionModal">Cancel</button>
          <button
            v-if="activeActionModal === 'approve'"
            class="btn-approve"
            type="button"
            :disabled="!canApproveRun || actionBusy"
            @click="approveRun"
          >
            {{ actionBusy ? "Submitting..." : "Approve Run" }}
          </button>
          <button
            v-if="activeActionModal === 'reject'"
            class="btn-reject"
            type="button"
            :disabled="!canRejectRun || actionBusy"
            @click="rejectRun"
          >
            {{ actionBusy ? "Submitting..." : "Reject Run" }}
          </button>
          <button
            v-if="activeActionModal === 'expire'"
            class="btn-expire"
            type="button"
            :disabled="!canExpireRun || actionBusy"
            @click="expireRun"
          >
            {{ actionBusy ? "Submitting..." : "Expire Run" }}
          </button>
          <button
            v-if="activeActionModal === 'resume'"
            class="btn-resume"
            type="button"
            :disabled="!canResumeRun || actionBusy"
            @click="resumeRun"
          >
            {{ actionBusy ? "Submitting..." : "Resume Run" }}
          </button>
        </div>
      </section>
    </div>

    <section id="artifacts" class="panel">
      <h2>Artifact Links</h2>
      <ul v-if="artifactLinks.length" class="artifact-list">
        <li v-for="artifact in artifactLinks" :key="`${artifact.source}:${artifact.uri}`">
          <a :href="buildArtifactHref(artifact.uri)" target="_blank" rel="noreferrer">{{ artifact.label }}</a>
          <span class="artifact-source">{{ artifact.source }}</span>
        </li>
      </ul>
      <p v-else class="empty">No artifact links available for this run.</p>
    </section>

    <section id="timeline" class="panel">
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
          <details v-if="event.payload" class="event-payload-details">
            <summary>Show payload JSON</summary>
            <pre class="event-payload">{{ stringifyPayload(event.payload) }}</pre>
          </details>
        </li>
      </ol>
      <p v-else class="empty">No timeline events found for this run.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  extractArtifactLinks,
  extractFailureReasons,
  extractFileDiffEntries,
  hasMigrationWarning,
  RunEventItem,
  RunItem,
  statusChipClass,
  summarizeChecks,
  ValidationCheckItem,
} from "../lib/runs";

interface ApprovalItem {
  id: number;
  run_id: string;
  reviewer_id: string | null;
  decision: string;
  reason: string | null;
  created_at: string;
}

type ActionModalName = "approve" | "reject" | "expire" | "resume";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const route = useRoute();
const router = useRouter();
const run = ref<RunItem | null>(null);
const events = ref<RunEventItem[]>([]);
const checks = ref<ValidationCheckItem[]>([]);
const approvals = ref<ApprovalItem[]>([]);
const loading = ref(true);
const loadError = ref("");
const lastSync = ref<Date | null>(null);

const reviewerId = ref("");
const approveReason = ref("");
const rejectReason = ref("");
const expireReason = ref("");
const rejectFailureReasonCode = ref("POLICY_REJECTED");
const actionBusy = ref(false);
const actionError = ref("");
const actionSuccess = ref("");
const modalError = ref("");
const modalSuccess = ref("");
const activeActionModal = ref<ActionModalName | null>(null);
const modalDialogRef = ref<HTMLElement | null>(null);
const modalLastFocused = ref<HTMLElement | null>(null);
const activeSectionId = ref("summary");

const failureReasonCodes = [
  "WAITING_FOR_SLOT",
  "VALIDATION_FAILED",
  "CHECKS_FAILED",
  "MERGE_CONFLICT",
  "MIGRATION_FAILED",
  "DEPLOY_HEALTHCHECK_FAILED",
  "PREVIEW_PUBLISH_FAILED",
  "AGENT_TIMEOUT",
  "AGENT_CANCELED",
  "PREVIEW_EXPIRED",
  "POLICY_REJECTED",
  "UNKNOWN_ERROR",
];

let pollHandle: ReturnType<typeof setInterval> | null = null;
let sectionObserver: IntersectionObserver | null = null;

const runId = computed(() => String(route.params.runId ?? ""));
const artifactLinks = computed(() => extractArtifactLinks(checks.value, events.value));
const failureReasons = computed(() => extractFailureReasons(events.value, checks.value));
const fileDiffEntries = computed(() => extractFileDiffEntries(events.value));
const migrationWarning = computed(() => hasMigrationWarning(fileDiffEntries.value));
const migrationFiles = computed(() => {
  const paths = fileDiffEntries.value
    .map((entry) => entry.path)
    .filter((path) => /(alembic|migrations?|migration|\.sql$)/i.test(path));
  return [...new Set(paths)];
});
const checksSummary = computed(() => summarizeChecks(checks.value));
const canApproveRun = computed(() => Boolean(run.value && ["preview_ready", "needs_approval"].includes(run.value.status)));
const canRejectRun = computed(() => Boolean(run.value && run.value.status !== "merged"));
const canExpireRun = computed(() =>
  Boolean(
    run.value &&
      ["queued", "planning", "editing", "testing", "preview_ready", "needs_approval", "approved"].includes(
        run.value.status,
      ),
  ),
);
const canResumeRun = computed(() => Boolean(run.value && ["failed", "expired"].includes(run.value.status)));
const lastSyncLabel = computed(() => (lastSync.value ? lastSync.value.toLocaleTimeString() : "not yet"));
const actionModalTitle = computed(() => {
  if (activeActionModal.value === "approve") {
    return "Approve Run";
  }
  if (activeActionModal.value === "reject") {
    return "Reject Run";
  }
  if (activeActionModal.value === "expire") {
    return "Expire Run";
  }
  if (activeActionModal.value === "resume") {
    return "Resume Run";
  }
  return "Run Action";
});
const actionModalSubhead = computed(() => {
  if (activeActionModal.value === "approve") {
    return "Approving will continue merge/deploy pipeline checks for this run.";
  }
  if (activeActionModal.value === "reject") {
    return "Rejecting records a decision and applies the selected failure reason code.";
  }
  if (activeActionModal.value === "expire") {
    return "Expire sets recoverable reason code PREVIEW_EXPIRED.";
  }
  if (activeActionModal.value === "resume") {
    return "Resume creates a queued child run from this failed/expired run.";
  }
  return "";
});
const sectionLinks = [
  { id: "summary", label: "Summary" },
  { id: "change-review", label: "Change Review" },
  { id: "failure-reasons", label: "Failures" },
  { id: "checks-summary", label: "Checks" },
  { id: "validation-checks", label: "Validation" },
  { id: "lifecycle-actions", label: "Actions" },
  { id: "artifacts", label: "Artifacts" },
  { id: "timeline", label: "Timeline" },
];

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

function buildArtifactHref(uri: string): string {
  const value = uri.trim();
  if (/^https?:\/\//i.test(value)) {
    return value;
  }
  if (/^s3:\/\//i.test(value)) {
    return value;
  }
  return `${apiBaseUrl}/api/runs/${encodeURIComponent(runId.value)}/artifacts/content?uri=${encodeURIComponent(value)}`;
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}) for ${url}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(url: string, payload: Record<string, unknown>): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Request failed (${response.status}) for ${url}: ${detail}`);
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
    const [runPayload, eventsPayload, checksPayload, approvalsPayload] = await Promise.all([
      fetchJson<RunItem>(`${apiBaseUrl}/api/runs/${runId.value}`),
      fetchJson<RunEventItem[]>(`${apiBaseUrl}/api/runs/${runId.value}/events`),
      fetchJson<ValidationCheckItem[]>(`${apiBaseUrl}/api/runs/${runId.value}/checks`),
      fetchJson<ApprovalItem[]>(`${apiBaseUrl}/api/runs/${runId.value}/approvals`),
    ]);

    run.value = runPayload;
    events.value = eventsPayload;
    checks.value = checksPayload;
    approvals.value = approvalsPayload;
    lastSync.value = new Date();
  } catch (error) {
    loadError.value = (error as Error).message;
  } finally {
    if (!silent) {
      loading.value = false;
    }
  }
}

function resetActionFeedback(): void {
  actionError.value = "";
  actionSuccess.value = "";
  modalError.value = "";
  modalSuccess.value = "";
}

function setActionError(message: string): void {
  actionError.value = message;
  modalError.value = message;
}

function setActionSuccess(message: string): void {
  actionSuccess.value = message;
  modalSuccess.value = message;
}

function openActionModal(modal: ActionModalName): void {
  if (actionBusy.value) {
    return;
  }
  resetActionFeedback();

  if (modal === "approve" && !canApproveRun.value) {
    setActionError("Run must be in preview_ready or needs_approval state before approving.");
    return;
  }
  if (modal === "reject" && !canRejectRun.value) {
    setActionError("Run is not loaded yet.");
    return;
  }
  if (modal === "expire" && !canExpireRun.value) {
    setActionError("Run cannot be manually expired in current state.");
    return;
  }
  if (modal === "resume" && !canResumeRun.value) {
    setActionError("Run must be failed or expired before resuming.");
    return;
  }

  modalLastFocused.value = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  activeActionModal.value = modal;
}

function closeActionModal(): void {
  if (actionBusy.value) {
    return;
  }
  activeActionModal.value = null;
}

function focusModalInitialTarget(): void {
  const dialog = modalDialogRef.value;
  if (!dialog) {
    return;
  }
  const target =
    dialog.querySelector<HTMLElement>("[data-autofocus]") ||
    dialog.querySelector<HTMLElement>("button, input, textarea, select, [tabindex]:not([tabindex='-1'])");
  target?.focus();
}

function handleModalKeydown(event: KeyboardEvent): void {
  if (!activeActionModal.value) {
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    closeActionModal();
    return;
  }
  if (event.key !== "Tab") {
    return;
  }

  const dialog = modalDialogRef.value;
  if (!dialog) {
    return;
  }
  const focusable = Array.from(
    dialog.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
    ),
  );
  if (!focusable.length) {
    event.preventDefault();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const current = document.activeElement as HTMLElement | null;

  if (event.shiftKey) {
    if (!current || current === first || !dialog.contains(current)) {
      event.preventDefault();
      last.focus();
    }
    return;
  }
  if (!current || current === last || !dialog.contains(current)) {
    event.preventDefault();
    first.focus();
  }
}

async function approveRun() {
  if (!run.value) {
    return;
  }

  resetActionFeedback();

  if (!canApproveRun.value) {
    setActionError("Run must be in preview_ready or needs_approval state before approving.");
    return;
  }

  actionBusy.value = true;
  try {
    await postJson<ApprovalItem>(`${apiBaseUrl}/api/runs/${run.value.id}/approve`, {
      reviewer_id: reviewerId.value.trim() || undefined,
      reason: approveReason.value.trim() || undefined,
    });

    setActionSuccess("Run approved successfully.");
    rejectReason.value = "";
    await refreshDetails({ silent: true });
  } catch (error) {
    setActionError((error as Error).message);
  } finally {
    actionBusy.value = false;
  }
}

async function rejectRun() {
  if (!run.value) {
    return;
  }

  resetActionFeedback();

  if (!canRejectRun.value) {
    setActionError("Run is not loaded yet.");
    return;
  }

  const reason = rejectReason.value.trim();
  if (!reason) {
    setActionError("Reject reason is required.");
    return;
  }

  actionBusy.value = true;
  try {
    await postJson<ApprovalItem>(`${apiBaseUrl}/api/runs/${run.value.id}/reject`, {
      reviewer_id: reviewerId.value.trim() || undefined,
      reason,
      failure_reason_code: rejectFailureReasonCode.value,
    });

    setActionSuccess("Run rejected successfully.");
    approveReason.value = "";
    await refreshDetails({ silent: true });
  } catch (error) {
    setActionError((error as Error).message);
  } finally {
    actionBusy.value = false;
  }
}

async function expireRun() {
  if (!run.value) {
    return;
  }

  resetActionFeedback();

  if (!canExpireRun.value) {
    setActionError("Run cannot be manually expired in current state.");
    return;
  }

  actionBusy.value = true;
  try {
    await postJson<RunItem>(`${apiBaseUrl}/api/runs/${run.value.id}/expire`, {
      reason: expireReason.value.trim() || undefined,
    });
    setActionSuccess("Run expired with PREVIEW_EXPIRED recoverable reason.");
    await refreshDetails({ silent: true });
  } catch (error) {
    setActionError((error as Error).message);
  } finally {
    actionBusy.value = false;
  }
}

async function resumeRun() {
  if (!run.value) {
    return;
  }

  resetActionFeedback();

  if (!canResumeRun.value) {
    setActionError("Run must be failed or expired before resuming.");
    return;
  }

  actionBusy.value = true;
  try {
    const child = await postJson<RunItem>(`${apiBaseUrl}/api/runs/${run.value.id}/resume`, {});
    setActionSuccess(`Child run queued: ${child.id}`);
    closeActionModal();
    await router.push(`/codex/runs/${child.id}`);
    await refreshDetails();
  } catch (error) {
    setActionError((error as Error).message);
  } finally {
    actionBusy.value = false;
  }
}

function scrollToSection(sectionId: string): void {
  const node = document.getElementById(sectionId);
  if (!node) {
    return;
  }
  activeSectionId.value = sectionId;
  node.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function setupSectionObserver(): Promise<void> {
  await nextTick();
  if (sectionObserver) {
    sectionObserver.disconnect();
    sectionObserver = null;
  }
  if (typeof window === "undefined" || !("IntersectionObserver" in window)) {
    return;
  }

  sectionObserver = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (!visible.length) {
        return;
      }
      const sectionId = visible[0]?.target?.id;
      if (sectionId) {
        activeSectionId.value = sectionId;
      }
    },
    {
      root: null,
      rootMargin: "-20% 0px -65% 0px",
      threshold: [0.1, 0.25, 0.5, 0.75],
    },
  );

  sectionLinks.forEach((section) => {
    const node = document.getElementById(section.id);
    if (node) {
      sectionObserver?.observe(node);
    }
  });
}

function isTypingTarget(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}

async function handleDetailsHotkeys(event: KeyboardEvent) {
  if (activeActionModal.value) {
    return;
  }
  if (isTypingTarget(event)) {
    return;
  }
  if (event.altKey && event.key.toLowerCase() === "r") {
    event.preventDefault();
    await refreshDetails();
  }
}

watch(runId, () => {
  void refreshDetails();
  void setupSectionObserver();
});

watch(activeActionModal, async (value) => {
  if (value) {
    await nextTick();
    focusModalInitialTarget();
    return;
  }
  await nextTick();
  modalLastFocused.value?.focus();
});

onMounted(() => {
  void refreshDetails();
  void setupSectionObserver();
  pollHandle = setInterval(() => {
    void refreshDetails({ silent: true });
  }, 5000);
  window.addEventListener("keydown", handleDetailsHotkeys);
});

onUnmounted(() => {
  if (pollHandle) {
    clearInterval(pollHandle);
  }
  if (sectionObserver) {
    sectionObserver.disconnect();
    sectionObserver = null;
  }
  window.removeEventListener("keydown", handleDetailsHotkeys);
});
</script>

<style scoped>
.run-details-page {
  width: min(90vw, 980px);
  max-width: 90vw;
  box-sizing: border-box;
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

.hero-links {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.4rem;
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

.panel h3 {
  margin: 0.35rem 0 0.6rem;
  font-size: 0.95rem;
}

.details-nav {
  position: sticky;
  top: 0.75rem;
  z-index: 10;
}

.details-nav-links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.details-nav-btn {
  background: #e2e8f0;
  color: #1e293b;
  border: 1px solid #cbd5e1;
  padding: 0.42rem 0.66rem;
}

.details-nav-btn-active {
  background: #0f766e;
  color: #f8fafc;
  border-color: #0f766e;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.8rem;
}

button,
textarea,
input,
select {
  font: inherit;
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

.review-grid {
  display: grid;
  gap: 0.9rem;
  grid-template-columns: 1.7fr 1fr;
}

.diff-list,
.checks-list,
.artifact-list,
.failure-list,
.approvals-list,
.migration-list {
  margin: 0;
  padding-left: 1.2rem;
  display: grid;
  gap: 0.55rem;
}

.diff-item,
.check-item,
.approval-item {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  padding: 0.7rem;
  background: #f8fbff;
  list-style: none;
}

.diff-item-head,
.check-top,
.approval-top {
  display: flex;
  justify-content: space-between;
  gap: 0.6rem;
  align-items: center;
}

.diff-stats {
  display: inline-flex;
  gap: 0.35rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.82rem;
}

.stat-add {
  color: #166534;
}

.stat-del {
  color: #991b1b;
}

.diff-source,
.approval-meta {
  margin: 0.35rem 0 0;
  color: #64748b;
  font-size: 0.82rem;
}

.diff-patch {
  margin-top: 0.45rem;
}

.diff-patch pre {
  margin: 0.45rem 0 0;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 0.6rem;
  overflow: auto;
  font-size: 0.78rem;
}

.migration-panel {
  border-radius: 10px;
  padding: 0.8rem;
  border: 1px solid;
}

.migration-warning {
  background: #fff7ed;
  border-color: #fdba74;
  color: #9a3412;
}

.migration-safe {
  background: #ecfdf5;
  border-color: #86efac;
  color: #166534;
}

.checks-summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.summary-chip {
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.78rem;
  font-weight: 600;
  border: 1px solid transparent;
}

.summary-chip-neutral {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #334155;
}

.summary-chip-success {
  background: #dcfce7;
  border-color: #86efac;
  color: #166534;
}

.summary-chip-warn {
  background: #fef3c7;
  border-color: #fcd34d;
  color: #92400e;
}

.summary-chip-danger {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #991b1b;
}

.check-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
  margin: 0.45rem 0;
  color: #64748b;
  font-size: 0.82rem;
}

.action-modal-grid {
  display: grid;
  gap: 0.65rem;
  margin-top: 0.65rem;
}

.action-modal-grid label {
  display: grid;
  gap: 0.3rem;
}

.action-modal-grid textarea,
.action-modal-grid input,
.action-modal-grid select {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0.55rem 0.65rem;
  background: #f8fafc;
}

.approval-status {
  margin: 0;
  color: #334155;
}

.decision-actions {
  margin-top: 0.8rem;
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.btn-approve {
  background: #166534;
}

.btn-reject {
  background: #b91c1c;
}

.btn-expire {
  background: #9f1239;
}

.btn-resume {
  background: #1d4ed8;
}

.lifecycle-hint {
  margin: 0.65rem 0 0;
  color: #475569;
  font-size: 0.84rem;
}

.approval-reason {
  margin: 0.35rem 0 0;
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
  margin: 0;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 0.6rem;
  overflow: auto;
  font-size: 0.78rem;
}

.event-payload-details {
  margin-top: 0.45rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  padding: 0.35rem 0.5rem;
}

.event-payload-details summary {
  cursor: pointer;
  color: #334155;
  font-size: 0.82rem;
  font-weight: 600;
}

.event-payload-details[open] summary {
  margin-bottom: 0.45rem;
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
  margin: 0.55rem 0 0;
  color: #b91c1c;
}

.success {
  margin: 0.55rem 0 0;
  color: #166534;
}

.action-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(15, 23, 42, 0.48);
  display: grid;
  place-items: center;
  padding: 1rem;
}

.action-modal {
  width: min(560px, 100%);
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 14px;
  padding: 1rem;
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.24);
}

.action-modal-approve {
  border-top: 4px solid #166534;
}

.action-modal-reject {
  border-top: 4px solid #b91c1c;
}

.action-modal-expire {
  border-top: 4px solid #9f1239;
}

.action-modal-resume {
  border-top: 4px solid #1d4ed8;
}

.action-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.action-modal-head h3 {
  margin: 0;
}

.btn-modal-close,
.btn-secondary {
  background: #e2e8f0;
  color: #1e293b;
}

.action-modal-subhead {
  margin: 0.5rem 0 0;
  color: #334155;
}

.action-modal-actions {
  margin-top: 0.85rem;
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  flex-wrap: wrap;
}

@media (max-width: 900px) {
  .review-grid {
    grid-template-columns: 1fr;
  }

  .event-top,
  .check-top,
  .approval-top {
    align-items: start;
    flex-direction: column;
  }
}

@media (max-width: 800px) {
  .hero {
    grid-template-columns: 1fr;
    display: grid;
  }

  .hero-links {
    align-items: flex-start;
  }

  .panel-head {
    flex-direction: column;
    align-items: start;
  }

  .summary-meta,
  .check-meta,
  .event-meta {
    gap: 0.5rem;
    flex-direction: column;
    align-items: start;
  }
}
</style>
