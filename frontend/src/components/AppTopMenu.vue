<template>
  <nav class="app-menu" :aria-label="t('menu.aria')">
    <ul class="menu-list">
      <li class="menu-item">
        <RouterLink class="menu-link" :class="{ 'menu-link-active': isHomeRoute }" to="/home">
          {{ t("menu.home") }}
        </RouterLink>
      </li>
      <li class="menu-item">
        <RouterLink class="menu-link" :class="{ 'menu-link-active': isCodexRoute }" to="/codex">
          {{ t("menu.codexInbox") }}
        </RouterLink>
      </li>
      <li ref="menuContainerRef" class="menu-item">
        <button
          type="button"
          class="menu-trigger"
          aria-haspopup="true"
          :aria-expanded="menuOpen ? 'true' : 'false'"
          @click="toggleMenu"
        >
          {{ t("menu.guides") }} <span class="menu-caret">▾</span>
        </button>
        <div v-if="menuOpen" class="menu-panel">
          <a href="/docs/public-user-guide.html" @click="closeMenu">{{ t("menu.guidePublic") }}</a>
          <a href="/docs/developer-architecture-guide.html" @click="closeMenu">{{ t("menu.guideDeveloper") }}</a>
          <a href="/docs/configuration-guide.html" @click="closeMenu">{{ t("menu.guideConfig") }}</a>
          <a href="/docs/platform-prerequisites-guide.html" @click="closeMenu">{{ t("menu.guidePlatform") }}</a>
          <a href="/docs/database-usage-guide.html" @click="closeMenu">{{ t("menu.guideDatabase") }}</a>
          <a href="/docs/faq.html" @click="closeMenu">{{ t("menu.guideFaq") }}</a>
        </div>
      </li>
      <li class="menu-item language-selector">
        <span class="language-label">{{ t("menu.language") }}</span>
        <div class="language-actions">
          <button
            type="button"
            class="lang-btn"
            :class="{ 'lang-btn-active': locale === 'en' }"
            @click="setLocale('en')"
          >
            {{ t("menu.english") }}
          </button>
          <button
            type="button"
            class="lang-btn"
            :class="{ 'lang-btn-active': locale === 'sr' }"
            @click="setLocale('sr')"
          >
            {{ t("menu.serbian") }}
          </button>
        </div>
      </li>
    </ul>
  </nav>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";

import { useI18n } from "../lib/i18n";

const route = useRoute();
const { locale, setLocale, t } = useI18n();
const menuOpen = ref(false);
const menuContainerRef = ref<HTMLElement | null>(null);

const isHomeRoute = computed(() => route.path.startsWith("/home"));
const isCodexRoute = computed(() => route.path.startsWith("/codex"));

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
.app-menu {
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

.language-selector {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.language-label {
  font-size: 0.8rem;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.language-actions {
  display: inline-flex;
  gap: 0.3rem;
}

.lang-btn {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #f8fafc;
  color: #0f172a;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.28rem 0.58rem;
  cursor: pointer;
}

.lang-btn-active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
}

@media (max-width: 780px) {
  .menu-list {
    flex-wrap: wrap;
  }

  .language-selector {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }
}
</style>
