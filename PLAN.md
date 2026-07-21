# AgentInfra — North Star Plan & Engineering Constitution

> **Status:** Living document. Version 1.1 — 2026-07-19 (restructured after adversarial self-review:
> Phase 15 split into 15a/15b, execution reordered around product proof, eval harness added, CI pulled forward).
> **Audience:** Every model and engineer that touches this repo. Read this before you write code.
> **Authority:** This document governs *direction and standards*. It does not override `AGENTS.md`
> (workspace governance) or `memories/invariants.md` (hard constraints). Where they conflict,
> the invariants win and this document must be corrected.

---

## 0. How to use this document

This is the "holy guide." It exists so that any lower-capability model picking up a task can act
**without re-deriving the whole architecture** and without repeating mistakes already understood.

Rules for implementers:

1. **Do not regress an invariant to close a ticket.** If a task seems to require breaking
   `memories/invariants.md` (ephemeral infra, no static keys, teardown safety), stop and flag it.
2. **Every increment ships with: a test, an acceptance criterion met, and a docs/handoff update.**
   No "it worked in the pod once" as proof. See §7 (Definition of Done).
3. **Prefer correctness and honesty in naming over impressive naming.** If a component is a Postgres
   loop, do not call it a "Databricks medallion pipeline." Misnamed components have already caused
   confusion in this repo (see §3).
4. **Follow the execution order in §6/§10, and start from the quick-start queue (§6.0).** Each phase
   lists its *goal*, *scope*, *acceptance criteria*, and *low-level notes*. Cheap security hygiene
   (15a) lands immediately; the expensive hardening (15b/16) lands before any external user touches
   the system — but not before the product's core bet is proven (17–19).
5. **When you finish an increment, update `memories/implementation.md` and `handoff/handoff.md`.**
   That is the existing state protocol and it works; keep it.

---

## 1. What this product actually is

Strip away the framing and AgentInfra is **two products fused together**:

- **Product A — an agentic platform substrate.** A secure, multi-tenant, stateful LangGraph runtime
  on Kubernetes with an LLM gateway, secrets management, auth, streaming, and human-in-the-loop
  approvals. This is the "infra" that was built first and is the more mature half.

- **Product B — an autonomous data-onboarding pipeline.** Given a Business Requirement Document
  (BRD), a chain of specialist agents profiles the source, conforms it to an enterprise canonical
  model (IBM BDW), produces a source-to-target mapping (STM), and generates deployable data-pipeline
  code (Databricks Asset Bundles). A human approves the mapping before code is generated/run.

The **strategic bet worth making** is Product B, *riding on* Product A. The market pain is real:
enterprise data teams spend months hand-writing profiling, conformance mappings, and ingestion code
for every new source. An agent that turns a BRD + sample data into a reviewed, deployable,
lineage-tracked pipeline is a genuine wedge.

**Positioning statement (proposed):**
> *AgentInfra turns a business requirement and a data sample into a reviewed, governed, deployable
> data pipeline — profiling, canonical mapping, and code generation done by agents, approved by humans.*

Everything in this roadmap is oriented toward making Product B enterprise-credible while keeping
Product A as the trustworthy, cheap-to-operate substrate underneath it.

---

## 2. Current architecture (as-built inventory)

This is what exists today, stated plainly so no one has to reverse-engineer it.

### 2.1 Infrastructure (ephemeral, Terraform-managed)
- **EKS 1.31**, 2× `t3.medium` nodes (min 2 / max 3), private subnets, single NAT gateway, 2 AZs.
- **RDS PostgreSQL 15.7**, `db.t3.micro`, single-AZ, private. Serves *two* roles: LangGraph
  checkpointer **and** the pipeline's target "warehouse."
- **Kong** (DB-less, Helm) exposed as a **public LoadBalancer over plain HTTP**. Runs the
  `ai-proxy` plugin to reach Bedrock, plus rate-limiting and CORS.
- **HashiCorp Vault** in **dev mode** (in-memory, hardcoded root token).
- **AWS Cognito** user pool for auth; **S3** landing bucket; **ECR** for the agent image.
- **Bedrock** `us.amazon.nova-lite-v1:0` as the only model.
- Lifecycle: `make bootstrap` → `deploy-security` → `write-secret` → `configure-vault-auth` →
  `configure-bedrock-auth` → `build-and-push` → `deploy-agent`, and `make teardown` (with careful
  ELB/ENI/SG orphan purging). **The teardown discipline is genuinely good and must be preserved.**

### 2.2 Agent core (FastAPI + LangGraph, one pod, `replicas: 1`)
- `SupervisorAgent`: routes a prompt to `infra` / `code` / `research` specialists via an LLM
  classifier at `temperature=0`.
- `DatabricksPipelineGraph`: linear chain
  `ba_analyst → profiler → conformer → mapper → dab_generator`, with
  `interrupt_before=["dab_generator"]` for human approval of the mapping.
- Endpoints: `/chat`, `/chat/stream` (SSE), `/chat/approve`, `/pipeline/analyse`,
  `/pipeline/approve`, `/pipeline/run`, `/metrics`, `/chat/history`.
- `PipelineRunner`: the thing that *actually moves data* — reads JSON from S3, applies string-matched
  transform rules in Python, and writes to Postgres `bronze_*` / `silver_*` tables.

### 2.3 The three new layers (Product B), mapped to reality
| Layer (as you named it) | What it is in code | Maturity |
|---|---|---|
| **Business layer** | `BAAnalystAgent` — BRD → value-stream JSON | Prompt-only, no validation |
| **Semantics layer** | `SilverModelAgent` + `STMMappingAgent` — conform to IBM BDW, produce STM | Prompt-only, **ungrounded** (no real BDW reference) |
| **Orchestration / modelling / profiling / DAB** | `DataProfilerAgent`, `DABGeneratorAgent`, `DatabricksPipelineGraph`, `PipelineRunner` | Graph works; **codegen is not executed**; runner is a Postgres loop |

### 2.4 Frontend
- Vite + React dashboard, Cognito login, chat + "Databricks Ingest" tab with editable mapping table,
  file explorer for generated DAB, and a live pipeline-state timeline.
- **Config is hardcoded** in `App.jsx`: the ELB URL, Cognito client ID, region.

---

## 3. Stress test — where this breaks, ranked

This is the honest part. The system demos well and the engineering instincts are sound, but several
load-bearing claims in the README/memories are **aspirational, not true today**. Enterprise buyers
will find these in the first security review. They are listed worst-first.

### 3.1 Security claims that are currently false (BLOCKERS for "enterprise-grade")

1. **"Keyless" Bedrock access is actually a static IAM access key.** `eks.tf` creates
   `aws_iam_user.bedrock_user` with `AmazonBedrockFullAccess` and a long-lived
   `aws_iam_access_key`, injected into a k8s secret for Kong. This directly violates the
   "no permanent static keys" invariant. *And* the node role *also* has `AmazonBedrockFullAccess`,
   so there are two over-privileged paths to Bedrock.
2. **There is no IRSA. Pods inherit the node role.** The code and comments say "IRSA pattern," but
   S3/Bedrock access comes from the **node instance role** reachable via IMDS (hop-limit raised to 2
   specifically to enable this). Every pod on the node gets `AmazonBedrockFullAccess` +
   S3 read/write/delete. This is the classic confused-deputy / pod-escape blast radius.
3. **Vault is dev-mode with a hardcoded root token** (`root-vault-token` in both
   `vault-values.yaml` and the `Makefile`). In-memory, no HA, no TLS, no audit log, no unseal.
   Every "production Vault (Raft, TLS, audit)" claim in `poc_architecture.md` is unmet.
4. **RDS password is hardcoded in plaintext in Terraform** (`postgresSecurePass123!`) and committed
   to git and stored in state. This is a credential leak, not a "dev credential."
5. **All traffic is plain HTTP over a public LoadBalancer.** Cognito JWTs, prompts, and BRDs
   (potentially sensitive business data) travel in cleartext. "TLS 1.3 everywhere" is false.
6. **Auth silently fails open.** `verify_token()` returns `"default_user"` when the header is
   missing *or* when JWKS hasn't loaded, and decodes with `verify_aud=False`. Any request with no
   token is accepted as a shared `default_user` — which also means that user's threads are a shared
   bucket. Multi-tenant isolation is defeated by its own fallback.
7. **Claimed Postgres Row-Level Security does not exist.** Tenant isolation is only a
   `f"{user_id}:{session_id}"` thread-id prefix. Anyone who can forge/guess a thread id, or who
   lands on `default_user`, crosses the tenant boundary. No RLS, no per-tenant DB role.
8. **CORS is `origins: "*"` with `credentials: true`** — an invalid, maximally permissive combo.

### 3.2 The Product-B "Databricks" story is currently theater

9. **The DAB is generated but never deployed or executed.** `DABGeneratorAgent` emits
   `databricks.yml` + PySpark as LLM *text*. Nothing validates the YAML, and no
   `databricks bundle deploy` ever runs. The actual data movement is `PipelineRunner`, a Python
   loop writing to Postgres. So the headline capability ("generate deployable Databricks pipelines")
   is unproven end-to-end.
10. **It is not a medallion architecture.** `PipelineRunner` writes the **same rows** into both
    `bronze_*` and `silver_*`, and **`DROP TABLE ... CREATE TABLE` on every run**. Bronze should be
    append-only raw; silver should be deduplicated/conformed/typed. There is no separation, no
    history, no idempotency, no upsert/merge, no incremental load, no partitioning.
11. **The transformation engine is string matching.** `"HASH" in rule.upper()`,
    `"DECIMAL" in rule.upper()`, `rule.startswith("lit(")`. This cannot represent real Spark SQL and
    will silently mis-transform anything the heuristics don't anticipate.
12. **The IBM BDW conformance is ungrounded.** `SilverModelAgent` asks Nova Lite to invent BDW
    subject areas and attribute names from memory. There is **no reference model, no vector lookup,
    no validation** (the `databricks_automation_plan.md` mentions a "semantic vector lookup" that was
    never built). BDW attribute names hallucinated by an LLM are worse than useless in a regulated
    bank — they look authoritative and are wrong.
13. **Data-quality expectations are generated and then ignored.** `DataProfilerAgent` produces
    `data_quality_expectations`, but nothing enforces them at load time.
14. **Structured outputs are parsed by stripping ``` fences and `json.loads`.** No Pydantic schema,
    no repair loop. One malformed field from the model empties the whole stage
    (`return {"mappings": []}` → the run silently produces nothing).

### 3.3 Platform / scaling gaps

15. **`replicas: 1`, no HPA, no PodDisruptionBudget.** The whole "horizontal scaling / failover"
    rationale for moving to Postgres checkpointing is unrealized. A single pod restart drops
    in-flight streams.
16. **Metrics are in-process module globals**, reset on restart, not aggregated across replicas, and
    not a real Prometheus client. There is no scrape config, no Grafana, no alerting despite the docs.
17. **One underpowered model for everything.** Nova Lite routes *and* does enterprise semantic
    conformance *and* generates PySpark. Conformance and codegen are exactly the tasks that need a
    frontier model (Claude). The gateway already supports multi-model — this is a config away.
18. **No CI/CD, no automated tests.** The only "tests" are `scratch/*` mock scripts. Every fix in the
    git log is a hot-patch verified by `kubectl exec`. This does not scale and is not auditable.
19. **Python 3.9 base image** (past EOL since October 2025) and unpinned upper bounds on core libs
    (`langgraph>=…`) — reproducibility risk.
20. **RDS is single-AZ `db.t3.micro`** doing double duty as checkpointer *and* warehouse. Fine for a
    cost-capped demo; conflates two very different workloads and has no HA.

### 3.4 What is genuinely good (keep and build on)
- Ephemeral bootstrap/teardown with orphan-ELB purging — disciplined, cost-aware, reproducible.
- Clean SOLID-ish separation: gateway / secrets / agent-core / model adapter.
- Supervisor-specialist decomposition and the LangGraph HITL interrupt pattern.
- Postgres checkpointer for durable thread state.
- SSE token streaming with reasoning drawers and specialist badges — good UX foundation.
- The state protocol (`memories/` + `handoff/`) is an effective agent-continuity mechanism.

---

## 4. Guiding principles for the enterprise build

1. **Grounded over generative for anything a regulator will read.** Canonical mappings, DQ rules,
   and lineage must be backed by a reference model and validated schemas — the LLM proposes, a
   deterministic layer disposes.
2. **Every artifact is validated before it is trusted.** Agent outputs pass through Pydantic/JSON
   Schema. Generated code is linted, compiled, and (in a sandbox) dry-run before it is offered as
   "deployable."
3. **Human-in-the-loop is a feature, not a formality.** Approvals must be meaningful, diffable, and
   audited (who approved what, when, on what evidence).
4. **Secretless and least-privilege by construction.** IRSA per workload, scoped policies, no static
   keys, no wildcard `FullAccess`, no plaintext secrets in git or state.
5. **Cheap to run, safe to destroy.** Preserve the ephemeral model. Enterprise-readiness must not
   require an always-on bill; it must be *provable* on a spun-up stack and torn down cleanly.
6. **Lineage and audit are first-class.** Nothing an enterprise data platform does is untraceable:
   source → bronze → silver → target, plus which agent/model/prompt produced each decision.

---

## 5. Target architecture (where each layer must land)

```
                       ┌───────────────────────────────────────────────┐
                       │  Frontend (React) — runtime-injected config,   │
                       │  approval diffs, lineage viewer, run history   │
                       └───────────────┬───────────────────────────────┘
                                       │  HTTPS (TLS, ACM cert on ALB/Kong)
                       ┌───────────────▼───────────────────────────────┐
                       │  Edge: Kong — JWT (fail-closed), WAF, rate     │
                       │  limit, scoped CORS, per-tenant quotas         │
                       └───────────────┬───────────────────────────────┘
                                       │ mTLS in-mesh
        ┌──────────────────────────────▼──────────────────────────────┐
        │  Agent Core (LangGraph, HPA'd, IRSA)                          │
        │  ┌───────────────┐  ┌──────────────────────────────────────┐ │
        │  │ Supervisor    │  │ Data-Onboarding Graph (Product B)     │ │
        │  │ + specialists │  │ BA → Profiler → Conformer → Mapper →  │ │
        │  └───────────────┘  │ Validator → CodeGen → Deploy → Verify │ │
        │        │            └──────────────┬───────────────────────┘ │
        │        │  Model router (Claude for reasoning/codegen,         │
        │        │  Nova/Haiku for routing/cheap steps)                 │
        └────────┼────────────────────────────┬────────────────────────┘
                 │                             │
     ┌───────────▼─────────┐     ┌─────────────▼──────────────┐   ┌──────────────────┐
     │ Vault (HA, Raft,    │     │ Canonical Model Service     │   │ Execution target │
     │ TLS, audit)         │     │ (IBM BDW reference + vector │   │ Databricks (DAB  │
     │ IRSA-scoped secrets │     │  search + schema registry)  │   │ deploy) / Spark  │
     └─────────────────────┘     └─────────────────────────────┘   └──────────────────┘
                 │                             │                             │
     ┌───────────▼─────────┐     ┌─────────────▼──────────────┐   ┌──────────▼───────┐
     │ RDS: control-plane  │     │ Lineage & metadata store    │   │ Object store /   │
     │ state (checkpointer, │    │ (runs, approvals, mappings, │   │ lakehouse tables │
     │ audit) — separate    │    │  DQ results, provenance)    │   │ (bronze/silver)  │
     └─────────────────────┘     └─────────────────────────────┘   └──────────────────┘
```

Key moves from today → target:
- Split RDS's two jobs: **control-plane state** vs **data/lineage metadata** vs **actual lakehouse**.
- Insert a **deterministic Validator** stage between mapping and codegen.
- Add a real **Canonical Model Service** so conformance is grounded, not hallucinated.
- Make **CodeGen → Deploy → Verify** a real, sandboxed loop with a Databricks (or local Spark)
  execution target — so "deployable pipeline" is demonstrably true.
- **Model router** so the expensive model is used only where it earns its cost.

---

## 6. Roadmap — phased execution

**Execution order:** `15a → 17 → 18 → 19 → 15b → 16 → 20 → 21 → 22 → 23`.

The rationale: at the current stage (pre-customer, solo, ~$170 credit envelope) the existential risk
is **not** failing a security questionnaire — it is that the core bet (BRD → grounded mapping →
*runnable* code) doesn't prove out. So the order is: (1) close the cheap, embarrassing security
findings and put engineering guardrails in place (15a — days of work); (2) prove the product
(17–19); (3) complete the expensive hardening and tenancy work before any external user touches the
system (15b, 16); (4) make it operable, then sellable (20–23). Each phase is independently
shippable and testable on an ephemeral stack.

> Numbering continues from the existing `memories/implementation.md` (last completed = Phase 14).

---

### §6.0 Quick-start queue — the first ten increments, in order

For the implementer who wants an unambiguous starting point. Each is a small, self-contained PR.

1. **Fail-closed auth:** `verify_token` rejects missing/invalid tokens and unavailable JWKS
   (401/503, never `default_user`); verify `aud`/`client_id`; explicit env-gated dev bypass,
   off by default. Ship with 401 tests for every `/chat/*` and `/pipeline/*` route.
2. **Kill the static Bedrock key:** delete `aws_iam_user.bedrock_user` + access key; point Kong
   `ai-proxy` at node-role credentials (IMDS) for now; scope the node's Bedrock policy from
   `FullAccess` down to `bedrock:InvokeModel` on the specific model ARN(s). (Full IRSA comes in 15b.)
3. **Rotate + externalize the RDS password:** `random_password` → Vault/Secrets Manager, outputs
   marked `sensitive`, hardcoded string removed from git going forward.
4. **Scope CORS** to the known frontend origin(s); drop `*` + `credentials: true`.
5. **CI skeleton (GitHub Actions):** ruff/black, mypy, pytest, `terraform validate` + tflint,
   gitleaks. Red blocks merge. (Heavy CI — image scanning, auto-deploy — stays in Phase 21.)
6. **First unit tests:** `pipeline_runner` transform semantics + agent JSON-parsing paths.
7. **Stable domain:** Route53 zone + wildcard ACM cert + a bootstrap `make` step (or external-dns)
   that upserts an alias record to the fresh ELB. Add frontend **runtime config injection**
   (config endpoint / env-baked `config.json`) — this ends the per-bootstrap hardcoded-URL churn
   visible in the git log, and is the prerequisite for TLS in 15b.
8. **Pydantic contracts + repair loop** for all five pipeline-agent outputs (start of Phase 18).
9. **Golden BRD fixtures + first mapping-accuracy eval** wired into CI (start of the Phase 18 eval
   harness).
10. **pgvector reference-store spike** with a small owned canonical model subset (start of Phase 17).

---

### Phase 15a — Security Hygiene & Engineering Guardrails `[IMMEDIATE — days, not weeks]`
**Goal:** Close the cheap, embarrassing findings and install the guardrails every later phase
depends on. This is quick-start items 1–6 of §6.0, formalized.

**Scope & low-level notes:**
- **Fail-closed auth.** `verify_token` must reject when no token is present and when JWKS is
  unavailable (return 401/503, never `default_user`). Verify `aud`/`client_id`. Keep a *separate,
  explicit* dev bypass gated behind an env flag that is off by default and never set in cluster.
- **Kill the static Bedrock key.** Delete `aws_iam_user.bedrock_user` + access key. Interim path:
  Kong `ai-proxy` uses node-role credentials via IMDS (it already can), with the node's Bedrock
  policy scoped from `FullAccess` down to `bedrock:InvokeModel` on the specific model ARN(s).
  The full per-workload IRSA migration is Phase 15b.
- **Secrets out of git and state.** RDS password → generated (`random_password`) → stored in Vault /
  AWS Secrets Manager → referenced. Mark Terraform outputs `sensitive`. Rotate the leaked password
  and scrub history if this repo is ever public.
- **Scope CORS** to the known frontend origin(s); drop `*` + `credentials`.
- **CI skeleton (GitHub Actions):** ruff/black, mypy, pytest, `terraform validate` + tflint,
  gitleaks secret-scanning. Red blocks merge. This lands *now* — the models implementing Phases
  17–20 are exactly who need lint/type/test gates. (Image scanning, auto-deploy, and observability
  stay in Phase 21.)
- **First real tests:** unit tests for `pipeline_runner` transform semantics and the agents'
  JSON-parsing paths, running in CI.
- **Stable domain + runtime config:** Route53 zone, wildcard ACM cert, and a bootstrap step that
  upserts a DNS alias to the fresh ELB; frontend reads a runtime config (endpoint or baked
  `config.json`) instead of hardcoded ELB URL / Cognito client id / region. Prerequisite for TLS
  in 15b, and ends the per-bootstrap frontend-edit churn.

**Acceptance criteria:**
- A request with no/invalid JWT gets 401 on every `/pipeline/*` and `/chat/*` route (tested in CI).
- `grep`/gitleaks for access keys and plaintext passwords in the repo returns nothing.
- No IAM identity in the account holds `AmazonBedrockFullAccess`.
- A red CI check blocks merge; the test suite runs on every PR.
- A fresh `make bootstrap` requires **zero** frontend source edits to point at the new stack.

---

### Phase 15b — Full Identity & Transport Hardening `[before first external user]`
**Goal:** Make the remaining security claims in the README *true*, or delete the claims.
Deliberately deferred until after 17–19: production-mode Vault and full IRSA on a
torn-down-nightly cluster is real operational friction for zero benefit while there are no
external users. Do not let it slip past the first design-partner conversation.

**Scope & low-level notes:**
- **Real IRSA per workload; strip the node role.** IAM roles trusted by the EKS OIDC provider,
  annotated onto dedicated ServiceAccounts (`agent-core-sa`, Kong). Node role keeps only
  EKS/CNI/ECR. S3, Bedrock, and DB access move to per-SA roles with resource-scoped policies.
  Lower IMDS hop-limit back to 1.
- **Vault production mode.** Move off dev mode: Raft storage, auto-unseal (AWS KMS), TLS, audit
  device. If full HA is too costly for the ephemeral model, run a single-node Raft+TLS+KMS-unseal
  instance and document the gap explicitly — but no hardcoded root token. Automate init/unseal in
  `make deploy-security` so the ephemeral workflow stays one-command.
- **TLS at the edge.** HTTPS listener on the Kong LoadBalancer (or front with an ALB) using the
  Phase 15a wildcard cert. Redirect HTTP→HTTPS. Frontend on HTTPS.

**Acceptance criteria:**
- A pod other than `agent-core-sa` cannot call Bedrock or read the landing bucket (verified).
- Vault has no static root token in any file; audit device logs every secret read.
- Traffic to the LB on port 80 redirects to 443; port 443 serves a valid cert.
- `make bootstrap → deploy-security → teardown` still works end-to-end unattended.

---

### Phase 16 — Tenant Isolation & Data Governance `[before first external user]`
**Goal:** Real multi-tenancy, not a string prefix.

**Scope & low-level notes:**
- Introduce an explicit **tenant/org id** (Cognito custom claim or group), separate from `user_id`.
- Enforce isolation in the data layer: **Postgres RLS** on checkpoint/lineage tables keyed by
  `tenant_id`, and a per-tenant DB role — not application-level filtering alone.
- Partition S3 and lakehouse paths by tenant; scope IRSA policies per tenant prefix where feasible.
- Add an **audit log** table: every analyse/approve/run/deploy with actor, tenant, timestamp,
  input hash, model+prompt version, and outcome.
- PII handling: classify BRD/source fields, and make hashing/masking of PII columns a *policy*
  enforced by the Validator (Phase 18), not an LLM suggestion.
- **PII-to-model-provider control.** BRDs and customer sample data currently flow to Bedrock via
  Kong. Name the control explicitly: document Bedrock's no-training / data-retention posture as the
  current answer, and roadmap optional pre-prompt PII redaction for tenants that require it. An
  enterprise reviewer will ask this before they ask about RLS.

**Acceptance criteria:**
- Tenant A cannot read Tenant B's threads, mappings, or tables even with a valid token (test).
- Every state-changing endpoint writes an immutable audit row.

---

### Phase 17 — Grounded Canonical Model Service (Semantics layer, done right)
**Goal:** Conformance backed by a real reference model, not hallucination.

**Scope & low-level notes:**
- Stand up a **reference schema store** for the canonical model (start with a curated subset of IBM
  BDW subject areas/entities/attributes relevant to the target value streams — or a neutral canonical
  model you control if BDW licensing is a concern; decide in §9).
- Add **vector search** (pgvector on the existing Postgres is the cheapest path) over canonical
  attributes with descriptions. `SilverModelAgent` retrieves candidate targets and must **choose from
  retrieved options**, not invent names.
- Maintain a **schema registry** so every bronze/silver/target schema is versioned and diffable.
- Confidence scoring per mapping; low-confidence mappings are flagged for the human reviewer.

**Acceptance criteria:**
- Every `target_attribute` in an STM exists in the reference store (validated, not free text).
- Reviewer UI shows, for each mapping, the retrieved canonical candidates + confidence.

---

### Phase 18 — Deterministic Validation & Contract Layer
**Goal:** Nothing downstream trusts raw LLM text.

**Scope & low-level notes:**
- Define **Pydantic models** for every stage output (`ValueStream`, `BronzeSchema`, `SilverModel`,
  `MappingMatrix`, `BundleFiles`). Parse with a **repair loop** (re-prompt on validation failure,
  bounded retries) instead of `return {"mappings": []}`.
- Add a **Validator node** between `mapper` and codegen that checks: every source column is accounted
  for; types are compatible; surrogate-key/hash rules are well-formed; DQ expectations are
  representable; no target-column collisions (the dedup logic in `PipelineRunner` proves this class of
  bug is real).
- Replace string-matched transforms with a **typed transform DSL** (a small, enumerable set of
  operations: `direct`, `cast(type)`, `sha256`, `to_timestamp(fmt)`, `literal`, `trim`, …) that both
  the runner and the codegen compile from. The LLM emits DSL, not free-form Spark strings.
- **Eval harness (quality, not just shape).** Contracts validate *structure*; this validates
  *correctness* — the thing the product is actually sold on. Build: golden BRD fixtures with
  expected-mapping baselines; a mapping-accuracy metric (per-field precision/recall against
  baseline); regression evals that run in CI whenever a prompt or model changes, with a merge-gate
  threshold. Without this, Phase 20's model swaps are unmeasurable and any prompt tweak can
  silently degrade every mapping.
- **Prompt versioning.** Prompts live in the repo as versioned artifacts (not inline string
  literals); each run records the prompt content hash and model id, feeding the Phase 16 audit log.
  A prompt change is a diffable PR that triggers the eval suite.

**Acceptance criteria:**
- A malformed model response never silently produces an empty pipeline; it either repairs or fails
  loudly with a typed error surfaced to the UI.
- Transform semantics are identical between the local runner and the generated Spark code (golden
  tests).
- The eval suite runs in CI; a change that drops mapping accuracy below the baseline threshold
  blocks merge.
- Every pipeline run's audit trail includes the exact prompt hashes and model ids used per stage.

---

### Phase 19 — Real Execution Target (make "deployable" true)
**Goal:** Close the gap between generated code and executed pipeline.

**Scope & low-level notes:**
- Pick the execution substrate (decide in §9): **Databricks** (deploy the DAB for real via
  `databricks bundle validate/deploy` against an ephemeral workspace or Databricks Free Edition) or a
  **local Spark/Delta** target that runs the same generated PySpark. Either way, the generated code
  must *run*, not just render.
- Fix the medallion semantics in whichever runner is authoritative:
  - **Bronze:** append-only, raw + ingestion metadata, no drops.
  - **Silver:** deduplicated, typed, conformed, **MERGE/upsert** on business keys, with the DQ
    expectations from Phase 18 *enforced* (quarantine failing rows).
  - Support incremental loads and multiple files per entity (Autoloader semantics or a manifest).
- `validate` the generated `databricks.yml` against the bundle schema before it is ever shown as
  "ready."

**Acceptance criteria:**
- One command takes an approved mapping to a *running* job that lands correct bronze **and** distinct,
  conformed silver, with DQ failures quarantined — demonstrated on the ephemeral stack.
- Re-running is idempotent (no drops; merge produces the same result).

---

### Phase 20 — Model Router & Cost/Quality Tiering
**Goal:** Right model for each task; enforce cost governance the docs already promise.

**Scope & low-level notes:**
- Route by task class through the gateway: **Claude (frontier)** for conformance, mapping, and
  codegen; **Haiku/Nova** for routing and cheap extraction. Make it config, not code changes
  (the LSP/DIP design already supports this).
- Turn on the gateway's **token quotas per tenant** and **semantic caching** that
  `poc_architecture.md` describes but never enabled.
- Track **cost per run** (tokens × price) and surface it in the run history.

**Acceptance criteria:**
- Per-tenant daily token cap enforced at the gateway (test a breach → 429).
- Run history shows model(s) used and estimated cost per stage.

---

### Phase 21 — Observability, CD & Reliability
**Goal:** Stop hot-patching in the pod. Make releases auditable and safe.
(The basic CI gate — lint, types, tests, tf-validate, gitleaks — already landed in Phase 15a;
this phase adds the heavy half.)

**Scope & low-level notes:**
- **CD + supply chain:** on merge to `main` → build/push image, `kubectl rollout`. Add
  `checkov`/`trivy` (IaC + image CVE scan) and `yamllint` to the pipeline.
- **Real Prometheus** (`prometheus-client`), scrape config, Grafana dashboards, and alerts. Replace
  the module-global metrics. Add OpenTelemetry traces (LangSmith optional) across the graph.
- **Reliability:** `replicas ≥ 2`, HPA on CPU/RPS, PodDisruptionBudget, readiness gating on Vault+DB.
  Validate that Postgres-checkpointer streams survive a pod kill (the reason it was built).
- **Connection-pool budget.** Today `SupervisorAgent` and `DatabricksPipelineGraph` each open their
  own `ConnectionPool(max_size=10)`; a `db.t3.micro` allows ~87 connections. Before enabling HPA,
  consolidate to one shared pool per pod and size it as
  `replicas_max × pools_per_pod × max_size < db_max_connections`, or the scale-out test will fail
  with connection exhaustion that looks like random 500s.
- **Reproducibility:** bump base image off 3.9 (→ 3.12), pin dependency upper bounds, lockfile.

**Acceptance criteria:**
- A red test blocks merge; a green merge auto-deploys; the image is scanned.
- Killing a pod mid-pipeline resumes cleanly from the checkpointer (test).

---

### Phase 22 — Product Surface & Self-Serve Onboarding
**Goal:** Turn the demo dashboard into a product.

**Scope & low-level notes:**
- (Runtime config injection and the stable domain moved to Phase 15a — done long before this phase.)
- **Approval UX with diffs:** show mapping changes, confidence, retrieved canonical candidates, and
  DQ preview; capture reviewer comments into the audit log.
- **Lineage viewer:** source → bronze → silver → target, per field, with the transform applied.
- **Run history & re-run:** list past runs, statuses, costs, and artifacts; one-click re-run.
- **Connector inputs beyond a single JSON file:** at minimum CSV/Parquet and a JDBC source sampler;
  a real BRD upload (PDF/docx) parsed into the BA stage.

**Acceptance criteria:**
- A new tenant can log in, upload a BRD + sample, review a grounded mapping, approve, deploy, and see
  lineage — with zero code edits and no hardcoded config.

---

### Phase 23 — Enterprise Readiness & Compliance Posture
**Goal:** Answer the security questionnaire without lying.

**Scope & low-level notes:**
- Data residency/region controls; encryption at rest verified (RDS/S3/EBS KMS) and in transit.
- Backup/restore + retention for lineage/audit; documented RPO/RTO.
- Access reviews, SSO/SAML option for enterprise IdPs (federate Cognito).
- SBOM, dependency and container CVE gates in CI; secret-scanning in CI (gitleaks).
- A written threat model and a data-handling/DPA position for customer data in BRDs and samples.

**Acceptance criteria:**
- A one-page control matrix (encryption, auth, audit, isolation, backup, CVE policy) that maps each
  control to code/infra evidence — all "implemented," none "planned."

---

## 7. Cross-cutting standards (Definition of Done)

Every increment, in every phase, is "done" only when **all** of these hold:

1. **Tested.** New logic has unit tests; pipeline changes have a golden end-to-end test on the
   ephemeral stack. No `kubectl exec` as the only proof.
2. **Validated I/O.** Any new agent output has a Pydantic/JSON-Schema contract and a repair path.
3. **Secure by default.** No new static secret, no widened IAM, no new public/plaintext surface. If a
   change touches auth or IAM, it names the blast radius it opens or closes.
4. **Observed.** New failure modes emit a metric and a structured log line.
5. **Documented.** `memories/implementation.md` phase entry + `handoff/handoff.md` updated; any
   README claim you made true (or found false) is corrected in the same PR.
6. **Cost-aware & reversible.** Provisioned via Terraform, destroyed cleanly by `make teardown`,
   with the incremental cost noted.
7. **Honestly named.** Components are named for what they do.

---

## 8. Invariants for implementers (do not violate)

- Ephemeral infra: full `make bootstrap` / `make teardown`; no reliance on long-lived cluster state.
- No permanent static AWS keys; AWS via SSO locally and IRSA in-cluster.
- No secrets in git, Terraform state (unmasked), or images.
- Teardown safety chain (`pre-teardown → purge-orphans → destroy → clean`) must keep working; test it
  after any infra change that adds a LoadBalancer, ENI, or SG.
- Human approval gate stays mandatory for: mapping approval, and any destructive/infra-mutating
  action. Approvals are audited.
- Budget guardrail: the stack must be demonstrable within the ~$160–180 credit envelope and left at
  $0 idle after teardown.

---

## 9. Open decisions (resolve before the dependent phase)

1. **Canonical model licensing — treat as a LEGAL RISK, not just an architecture choice.** IBM BDW
   is proprietary licensed IP. Marketing "conforms to IBM BDW" while shipping LLM-reconstructed BDW
   attribute names is legal exposure on top of being technically ungrounded. (Blocks Phase 17.)
   *Recommendation:* build a small owned canonical model first; treat BDW as a pluggable pack that
   is only enabled for customers who hold a BDW license.
2. **Execution substrate.** Databricks (Free Edition / ephemeral workspace) vs local Spark+Delta vs
   keep Postgres as the reference runtime. (Blocks Phase 19.) *Recommendation:* make the generated
   PySpark runnable on **local Spark+Delta** in CI for cheap proof, and support Databricks deploy as
   the enterprise target — same generated code, two backends.
3. **State store split.** When to separate checkpointer DB from lineage/warehouse DB. (Affects
   Phases 16/19.) *Recommendation:* separate at Phase 16; keep both on one RDS instance but distinct
   databases/roles until scale demands otherwise.
4. **Model spend ceiling.** What per-tenant/day token cap is acceptable given the credit envelope
   once Claude is in the loop? (Blocks Phase 20.)
5. **Compliance target.** Which framework are we actually claiming (SOC 2 direction? internal only?)
   — this sizes Phase 23.

---

## 10. Sequencing summary

```
15a Hygiene + CI + domain ──── cheap fixes & guardrails, land immediately (days)
             │
17 Grounded semantics ──┐
18 Validation/contracts │─ prove the product: the core bet made correct
   + eval harness       │  instead of plausible-looking
19 Real execution ──────┘
             │
15b Full hardening ─┐
16 Tenancy/governance ┴─ complete before the FIRST EXTERNAL USER touches the system
             │
20 Model router/cost ─┐
21 Obs/CD/reliability ┴─ makes it operable and affordable at scale
             │
22 Product surface ───┐
23 Compliance posture ─┴─ makes it sellable
```

Two truths held in tension, in this order: (1) the existential risk today is the product bet, so
prove 17–19 before paying for expensive hardening; (2) a polished pipeline on top of hallucinated
mappings and fail-open auth is a liability, so the cheap hygiene (15a) is non-negotiable and lands
first, and 15b/16 are hard gates before anyone external gets access. The eval harness in Phase 18
is the single highest-leverage engineering asset in this plan — it is what makes every later prompt,
model, and cost decision measurable.

---

*Maintainers: update the version line and the phase entries as work lands. If reality and this
document disagree, reality wins — fix the document in the same PR that changed reality.*
