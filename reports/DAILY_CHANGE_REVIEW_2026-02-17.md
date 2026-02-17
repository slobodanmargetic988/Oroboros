# Daily Change Review — 2026-02-17

## Scope i metod
- Opseg: svi commit-i od `2026-02-17 00:00` do trenutnog `HEAD` na `main`.
- Ukupno commit-a u opsegu: 23.
- Fokus: uskladjenost sa trazenim izmenama iz danasnjeg toka rada (preview flow, approvals, CORS/env, worker hardening, docs/nav).
- Van opsega: necommitovane izmene (`frontend/src/pages/RunDetailsPage.vue`, `infra/web-preview-1/index.html`, `infra/web-preview-2/index.html`, `infra/web-preview-3/index.html`).

## Glavni nalazi (prioritetno)

### [P1] Nestabilan test zbog environment-zavisnog ocekivanja
- Lokacija: `worker/tests/test_codex_runner.py:30`
- Problem: test ocekuje da je prvi token komande tacno `"codex"`, ali je danas uvedeno resolvovanje na apsolutnu putanju binara (npr. `/Applications/Codex.app/Contents/Resources/codex`).
- Efekat: test pada na masinama gde je Codex binary discoverable van PATH fallback-a, iako je funkcionalnost ispravna.
- Dokaz: `python3 -m pytest -q tests/test_codex_runner.py ...` -> 1 fail (`test_build_command_from_template`).
- Preporuka: asertovati da je `Path(command[0]).name == "codex"` ili proveravati sufiks/ekvivalenciju, umesto hard-coded stringa.

### [P2] `.DS_Store` je i dalje tracked u repou
- Lokacija: `.DS_Store`
- Problem: iako je dodato ignorisanje u `.gitignore`, fajl ostaje versioned jer je prethodno commitovan.
- Efekat: nepotreban noise i konflikti u historiji.
- Preporuka: ukloniti iz index-a (`git rm --cached .DS_Store`) i zadrzati ignore pravilo.

### [P3] Prazan tehnicki artefakt u root-u
- Lokacija: `COMMIT_REVIEW_TASKS.md`
- Problem: fajl je 0-byte i nema funkcionalnu vrednost.
- Efekat: blagi repozitorijum noise.
- Preporuka: obrisati ako nije deo namernog procesa.

---

## Verifikacija testovima (targeted)

### Backend
- Komanda:
  - `cd backend && python3 -m pytest -q tests/test_events_api.py tests/test_artifacts_api.py tests/test_runs_resilience.py tests/test_slot_lease_manager.py tests/test_approvals_merge_gate.py`
- Rezultat: `19 passed`.

### Worker
- Komanda:
  - `cd worker && python3 -m pytest -q tests/test_codex_runner.py tests/test_main_env_loading.py tests/test_orchestrator_validation_pipeline.py`
- Rezultat: `19 passed, 1 failed` (gore navedeni P1).

---

## Uskladjenost sa trazenim izmenama

### 1) MYO-43 stabilizacija kreiranja run-a i smoke wrapper
- Commit-i: `50e8302`, `99b1d65`
- Status: Implementirano.
- Napomena: validacija `created_by` uvedena (422 za nepostojeceg korisnika), testovi dodati.

### 2) Dokumentacija (user/dev/config/prereq/faq/db) i vizuelna dorada
- Commit-i: `d92a720`, `961dbd1`, `970ed86`, `2ec2ee0`, `276feb2`
- Status: Implementirano.
- Napomena: dokumenti prebaceni da se serviraju iz `frontend/public/docs` (ispravno za static serving kroz frontend).

### 3) Sticky meni + docs navigacija
- Commit: `970ed86`
- Status: Implementirano.
- Napomena: dodati dropdown + close on outside click/ESC i na Codex i u HTML guide stranicama.

### 4) CORS za lokal/prod i env dokumentacija
- Commit: `f56a069`
- Status: Implementirano.
- Napomena: backend uvodi `CORS_ALLOWED_ORIGINS_CSV`; primeri za lokal i produkciju dodati.

### 5) Auto-commit po run-u + cleanup grana/worktree na cancel/reject
- Commit: `2bf7a23`
- Status: Implementirano.
- Napomena: uveden `delete_run_branch`, force remove worktree, i event/audit trag.

### 6) Run expire/resume i sekcijska navigacija na Run Details
- Commit: `ddd4ffa`
- Status: Implementirano.

### 7) Link statusa run-a sa slot TTL expiracijom (PREVIEW_EXPIRED)
- Commit: `ed770b9`
- Status: Implementirano.
- Napomena: status transition + recovery metadata upisani pri isteku lease-a.

### 8) Worker startup resiliency (.env autoload + codex binary discovery)
- Commit-i: `2311eb4`, `e27b436`
- Status: Implementirano.
- Napomena: funkcionalno dobro; test mismatch je jedini otvoren problem (P1).

### 9) Run details UX popravke (max width + artifact log linkovi)
- Commit: `09b1ca8`
- Status: Implementirano.
- Napomena: artifact content endpoint radi uz path allow-list i link verifikaciju prema run-u.

### 10) Enforced commit + preview publish workflow
- Commit: `7b0ce80` (+ hardening u `b9e4575`)
- Status: Implementirano.
- Napomena: danasnji tok je pokrio commit invariant i publish fallback logiku.

### 11) Git hygiene za preview/worktree
- Commit-i: `1c56b09`, `414e986`, `94ccd68`, `06a0add`
- Status: Delimicno.
- Napomena: `.worktrees/` je ispravno ignorisan i cleanup uradjen; `.DS_Store` i dalje tracked (P2).

### 12) Worker-generated promene (home ruta)
- Commit-i: `87fd71d`, `a3c09e9`
- Status: Implementirano i merge-ovano.

### 13) Approval UX modalizacija + timeline payload collapse + worker execution hardening
- Commit: `b9e4575`
- Status: Implementirano.
- Napomena: approve iz `preview_ready` i reject u terminal stanjima su pokriveni backend-om i testovima.

---

## Commit-by-commit napomena (kratko)
- `50e8302` — dobra validacija i test pokrivenost; uskladjeno sa trazenim MYO-43 fixom.
- `99b1d65` — operativni rollback runbook dodat.
- `1039ce9` — vizuelna animacija Codex page; bez backend rizika.
- `276feb2`, `2ec2ee0` — MYO-44 checklist i dopuna opisa.
- `d92a720`, `961dbd1` — guides + worker preview reset uvodjenje i testovi; funkcionalno relevantno, ne samo docs.
- `970ed86` — docs relokacija u frontend/public i sticky nav; funkcionalno ispravno.
- `f56a069` — CORS konfigurabilnost + docs primeri; kljucna lokal/prod korekcija.
- `2bf7a23` — auto-commit i branch/worktree cleanup; znacajan quality pomak.
- `ddd4ffa` — expire/resume endpointi + UI nav.
- `ed770b9` — slot TTL -> run expired link; trazena semantika ispunjena.
- `2311eb4` — ucitavanje `worker/.env` defaulta pre startup-a.
- `e27b436` — codex binary autodiscovery; funkcionalno dobro, test mismatch (P1).
- `09b1ca8` — artifact logs preko API i 90vw limit.
- `7b0ce80` — enforce commit + publish preview; dodata failure reason semantika.
- `1c56b09`, `414e986`, `94ccd68`, `06a0add` — hygiene commitovi; ostavljen tracked `.DS_Store`.
- `87fd71d`, `a3c09e9` — worker-generated home page + merge.
- `b9e4575` — approval modal UX, timeline collapse, run execution hardening.

---

## Zakljucak
- Funkcionalno: danasnji zahtevi su u velikoj meri implementirani i povezani u konzistentan runtime tok.
- Otvoreno pre finalnog “clean” stanja:
  1. Popraviti environment-agnostic asert u `worker/tests/test_codex_runner.py:30`.
  2. Izbaciti `.DS_Store` iz tracked fajlova.
  3. Odluka oko praznog `COMMIT_REVIEW_TASKS.md` (zadrzati samo ako je deo procesa).
