import { createRouter, createWebHistory } from "vue-router";

import CodexPage from "./pages/CodexPage.vue";
import RunDetailsPage from "./pages/RunDetailsPage.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: "/codex",
    },
    {
      path: "/codex",
      component: CodexPage,
    },
    {
      path: "/codex/runs/:runId",
      component: RunDetailsPage,
    },
  ],
});

export default router;
