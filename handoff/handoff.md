# Handoff — 2026-07-13: E2E Medallion Pipeline Ingestion VERIFIED ✅

## Status: Phase 14 Complete

The full end-to-end medallion pipeline has been debugged and verified running on EKS.

## What Was Verified

```
Cognito Auth
    → POST /pipeline/analyse  (LLM generates 7 column mappings from BRD)
    → POST /pipeline/approve  (Human-in-the-loop approval persisted in LangGraph state)
    → POST /pipeline/run      (PipelineRunner reads S3 → transforms → writes PostgreSQL)
    → kubectl exec verification: bronze_transaction=5 rows, silver_transaction=5 rows
```

## Verified Output (in-pod DB query)
```
Columns: ['ac_txn_id', 'customer_id_hash', 'ac_id', 'transaction_amount',
          'transaction_timestamp', '_ingested_at', '_source_system', '_source_file']

Row 1: ('T-1001', '2c38c287...', 'ACC-01', Decimal('1500.50'), datetime(2026,7,12,10,15,30), ...)
Row 2: ('T-1002', '8fc09c59...', 'ACC-02', Decimal('25.00'),   datetime(2026,7,12,11,20), ...)
Row 3: ('T-1003', '059c67cc...', 'ACC-03', Decimal('340.75'),  datetime(2026,7,12,12,45,15), ...)
```

## Bugs Fixed This Session

| Error | Root Cause | Fix |
|-------|-----------|-----|
| `AttributeError: pipeline_orchestrator.db_config` → 500 | Attribute didn't exist on graph class | Module-level `_vault_secrets` dict, populated at startup |
| `No module named 'boto3'` → 500 | boto3 missing from requirements.txt | Added `boto3>=1.34.0` to `app/requirements.txt`; rebuilt image |
| `Unable to locate credentials` → 500 | IMDS hop-limit=1 blocks pod IAM cred fetching | `modify-instance-metadata-options --http-put-response-hop-limit 2` on all nodes; persisted in `aws_launch_template.node` |
| `Unable to locate credentials` (S3) | No S3 IAM policy on node role | Added `aws_iam_role_policy.node_s3_landing_access` inline policy to EKS node role |
| `column "_ingested_at" specified more than once` → 500 | LLM maps `_ingested_at` AND code hardcodes it | `seen_cols` dict deduplication in `pipeline_runner.py` |
| Empty `mapping_matrix` → 400 | Same `SESSION_ID` reused; LangGraph returned prior completed state | Timestamp-based `SESSION_ID = f"e2e-session-{int(time.time())}"` |

## Current Infrastructure State
- **EKS**: 2 nodes running (`agent-infra-cluster`), IMDS hop-limit=2 set
- **ECR image**: `agent-core:latest` — `sha256:009cffad...`
- **RDS**: `agentinfra` DB with `bronze_transaction` + `silver_transaction` tables populated
- **S3**: `agent-infra-landing-bucket-b5062800` contains `raw/transaction/transaction.json` (5 records)
- **Vault**: Keyless OIDC SA auth; Gemini + DB + Cognito secrets stored at `secret/gemini`
- **Kong**: AI Gateway + JWT auth enforced on all pipeline routes

## Git State
- Branch: `main`
- Latest commit: `42a99d5` — "fix: deduplicate target columns in pipeline_runner"
- All changes pushed to `https://github.com/ivavi9/agentinfra.git`

## Next Steps (Phase 15)
Implement Git-tracked CI/CD pipeline:
- `Jenkinsfile` with stages: lint (flake8/black/yamllint) → test → docker build → kubectl rollout
- Use GitHub Actions as a free alternative (no Harness/Jenkins server cost)
- Trigger on PR merge to `main`, deploy to EKS via `make build-and-push && kubectl rollout restart`
