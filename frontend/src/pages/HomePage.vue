<template>
  <div class="home-shell">
    <main class="home-page" role="main">
      <section class="home-panel">
        <p class="eyebrow">{{ t("home.eyebrow") }}</p>
        <h1>{{ t("home.title") }}</h1>
        <p class="placeholder">{{ t("home.placeholder") }}</p>
      </section>

      <section class="dev-welcome" :aria-label="t('home.devAria')">
        <p class="dev-kicker">{{ t("home.devKicker") }}</p>
        <h2>{{ t("home.devTitle") }}</h2>
        <p>{{ t("home.devBody") }}</p>
        <code class="dev-code">if (worksOnFirstTry) { console.log("suspicious"); }</code>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "../lib/i18n";

const { t } = useI18n();
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

.dev-welcome {
  margin-top: 1rem;
  background: linear-gradient(135deg, #fff7ed, #fffbeb);
  border: 1px solid #fed7aa;
  border-radius: 12px;
  padding: 1rem 1.1rem;
}

.dev-kicker {
  margin: 0;
  color: #9a3412;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 700;
}

h2 {
  margin: 0.45rem 0 0.6rem;
  color: #7c2d12;
  font-size: 1.05rem;
}

.dev-welcome p {
  margin: 0;
  line-height: 1.55;
  color: #7c2d12;
}

.dev-code {
  margin-top: 0.85rem;
  display: inline-block;
  border-radius: 8px;
  padding: 0.45rem 0.6rem;
  background: #431407;
  color: #fed7aa;
  font-size: 0.85rem;
}
</style>
