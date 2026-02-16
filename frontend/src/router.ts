import { createRouter, createWebHistory } from "vue-router";

import CodexPage from "./pages/CodexPage.vue";

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
  ],
});

export default router;
