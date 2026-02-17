<template>
  <div class="home-shell">
    <nav class="codex-menu" aria-label="Ouroboros docs">
      <ul class="menu-list">
        <li class="menu-item">
          <a class="menu-link menu-link-active" href="/home">Home</a>
        </li>
        <li class="menu-item">
          <a class="menu-link" href="/codex">Codex Inbox</a>
        </li>
        <li ref="menuContainerRef" class="menu-item">
          <button
            type="button"
            class="menu-trigger"
            aria-haspopup="true"
            :aria-expanded="menuOpen ? 'true' : 'false'"
            @click="toggleMenu"
          >
            Guides <span class="menu-caret">▾</span>
          </button>
          <div v-if="menuOpen" class="menu-panel">
            <a href="/docs/public-user-guide.html" @click="closeMenu">Public User Guide</a>
            <a href="/docs/developer-architecture-guide.html" @click="closeMenu">Developer Architecture Guide</a>
            <a href="/docs/configuration-guide.html" @click="closeMenu">Configuration Guide</a>
            <a href="/docs/platform-prerequisites-guide.html" @click="closeMenu">Platform Prerequisites Guide</a>
            <a href="/docs/database-usage-guide.html" @click="closeMenu">Database Usage Guide</a>
            <a href="/docs/faq.html" @click="closeMenu">FAQ</a>
          </div>
        </li>
      </ul>
    </nav>

    <main class="home-page" role="main">
      <section class="home-panel">
        <p class="eyebrow">Ouroboros</p>
        <h1>Home</h1>
        <p class="placeholder">
          This is your starting point. Use Cmd+K to open up a prompt and ask it to make changes, new pages, or whatever
          you like.
        </p>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

const menuOpen = ref(false);
const menuContainerRef = ref<HTMLElement | null>(null);

function toggleMenu() {
  menuOpen.value = !menuOpen.value;
}

function closeMenu() {
  menuOpen.value = false;
}

function handleDocumentClick(event: MouseEvent) {
  const target = event.target as Node | null;
  if (!target) {
    return;
  }
  if (menuContainerRef.value?.contains(target)) {
    return;
  }
  closeMenu();
}

function handleDocumentKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    closeMenu();
  }
}

onMounted(() => {
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleDocumentKeydown);
});

onUnmounted(() => {
  document.removeEventListener("click", handleDocumentClick);
  document.removeEventListener("keydown", handleDocumentKeydown);
});
</script>

<style scoped>
.home-shell {
  min-height: 100%;
}

.home-page {
  max-width: 980px;
  margin: 0 auto;
  padding: 1.2rem 1.2rem 3rem;
}

.codex-menu {
  position: sticky;
  top: 0;
  z-index: 90;
  border-bottom: 1px solid #d8e2ec;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(6px);
  padding: 0.55rem clamp(0.8rem, 3vw, 1.6rem);
}

.menu-list {
  list-style: none;
  margin: 0 auto;
  padding: 0;
  max-width: 980px;
  display: flex;
  align-items: center;
  gap: 0.55rem;
}

.menu-item {
  position: relative;
  display: block;
}

.menu-trigger {
  cursor: pointer;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #f8fafc;
  color: #0f172a;
  font-size: 0.9rem;
  font-weight: 600;
  padding: 0.45rem 0.7rem;
}

.menu-caret {
  margin-left: 0.3rem;
}

.menu-link {
  display: inline-block;
  text-decoration: none;
  color: #0f172a;
  font-size: 0.9rem;
  font-weight: 600;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #f8fafc;
  padding: 0.45rem 0.7rem;
}

.menu-link:hover {
  background: #eff6ff;
  color: #1e40af;
}

.menu-link-active {
  border-color: #93c5fd;
  color: #1e3a8a;
}

.menu-panel {
  position: absolute;
  z-index: 20;
  margin-top: 0.45rem;
  min-width: 280px;
  display: grid;
  gap: 0.2rem;
  border: 1px solid #d8e2ec;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.12);
  padding: 0.4rem;
}

.menu-panel a {
  color: #1e293b;
  text-decoration: none;
  border-radius: 8px;
  padding: 0.42rem 0.5rem;
  font-size: 0.9rem;
}

.menu-panel a:hover {
  background: #eff6ff;
  color: #1e40af;
}

.home-panel {
  background: #ffffff;
  border: 1px solid #d9e2ec;
  border-radius: 12px;
  padding: 1.2rem 1.1rem;
}

.eyebrow {
  margin: 0;
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #334155;
}

h1 {
  margin: 0.5rem 0;
}

.placeholder {
  margin: 0;
  color: #475569;
  line-height: 1.6;
}
</style>
