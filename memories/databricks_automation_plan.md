# Next Phase Plan: Databricks Profiling, Conformance & DAB Generation Automation (v1.0)

This document details the step-by-step engineering plan to implement a multi-agent profiling, mapping, and coding automation flow on top of the existing **Supervisor-Specialist** framework.

---

## 1. Architectural Strategy

The goal is to intake a Business Requirement Document (BRD) detailing a **Value Stream**, analyze it through consecutive domain agents, conform it against standard **IBM Industry Models (BDW)**, and output ready-to-deploy **Databricks Asset Bundles (DABs)** for raw (Bronze) to conformed (Silver) pipeline ingestion.

### The Automated Workflow

```
[ BRD Upload ] ➔ [ BA Analyst Agent ] ➔ [ Data Profiler Agent ] ➔ [ Silver Model Agent ]
                                                                             │
                                                                             ▼
[ Deploy DAB ] 👤 [ Approve Mapping Gate ] 👤 🦄 ◀── [ STM Mapping Agent ]
```

---

## 2. Key Components & Implementation Steps

### Step 1: Schema Definitions and State Expansion
Extend `SupervisorState` or define a dedicated `AutomationState` type to handle the outputs of the new pipeline stages:
* `brd_document`: Raw input string.
* `value_stream_metadata`: JSON mapping entities, keys, and transaction rates.
* `bronze_schema`: Column layouts, types, nullability, and primary constraints.
* `silver_conformed`: Selected IBM BDW subject areas, target tables, and attribute types.
* `mapping_matrix`: Structural column mapping definitions, conversion types, and hashing logic.
* `approved`: Human-in-the-loop approval status flag.
* `generated_bundle_files`: File paths and contents of the compiled Databricks Asset Bundle (`databricks.yml`, Python ingestion files).

### Step 2: Implement the Specialist Agents
Create new agent modules in the `app/agents/` directory:
1. **`BAAnalystAgent`** ([app/agents/ba_analyst_agent.py](file:///Users/avikaushik/agentinfra/app/agents/ba_analyst_agent.py)): Extract structured entities, transactional volume SLAs, and business descriptors.
2. **`DataProfilerAgent`** ([app/agents/data_profiler_agent.py](file:///Users/avikaushik/agentinfra/app/agents/data_profiler_agent.py)): Define columns, primary constraints, partition strategies, and data quality check specifications (e.g., Great Expectations configurations) for the Bronze Delta table.
3. **`SilverModelAgent`** ([app/agents/silver_model_agent.py](file:///Users/avikaushik/agentinfra/app/agents/silver_model_agent.py)): Retrieve IBM BDW entity alignments using a reference schema mapping JSON or local semantic vector lookup.
4. **`STMMappingAgent`** ([app/agents/stm_mapping_agent.py](file:///Users/avikaushik/agentinfra/app/agents/stm_mapping_agent.py)): Map Bronze inputs to Silver columns, adding transformations (type conversions, trim, hashes for surrogate keys).
5. **`DABGeneratorAgent`** ([app/agents/dab_generator_agent.py](file:///Users/avikaushik/agentinfra/app/agents/dab_generator_agent.py)): Compile structural configurations (`databricks.yml`, PySpark scripts, and dbt SQL models).

### Step 3: Register Graph Nodes & Human-in-the-Loop Intercepts
Update the graph compiler in `app/agents/supervisor.py`:
* Define a new subgraph: `DatabricksPipelineGraph`.
* Add `ba_analyst`, `profiler`, `conformer`, `mapper`, and `dab_generator` nodes.
* Enforce human-in-the-loop validation using:
  `interrupt_before=["dab_generator"]`
  This halts execution immediately after the Source-to-Target mapping matrix is generated, prompting lead developer approval.

### Step 4: UI Dashboard Integrations
Add a new view/tab to the React developer dashboard:
1. **Pipeline Config & BRD Upload Area**: Drag-and-drop file upload for BRDs or value stream configurations.
2. **Source-to-Target Mapping Panel**: Renders the generated STM mapping as an interactive table allowing direct correction of target columns, datatypes, and hashes.
3. **Approve / Reject Controls**: Invokes the backend `/chat/approve` endpoint with `action="approve"` or `action="reject"` to continue graph execution.
4. **Compiled DAB File Explorer**: Displays file tree structures (`databricks.yml`, `src/notebooks/ingest.py`, etc.) with code copy buttons.

---

## 3. Verification & Local Integration Testing Plan

### Mock Verification (Local)
1. **End-to-End Ingestion Mock Run**: Verify that compiling a mock BRD yields the exact structured JSON mappings and dbt templates.
2. **Unit Testing**: Create test scripts checking that the `DABGeneratorAgent` outputs valid `databricks.yml` YAML files conforming to Databricks schema specifications.

### Real Ingestion Run (Databricks)
1. **Setup Workspace**: Provision a lightweight Databricks workspace dynamically.
2. **Deploy Bundle**: Execute `databricks bundle deploy` to push the generated DAB code into the workspace.
3. **Run Pipeline**: Trigger the Autoloader-to-Bronze and Bronze-to-Silver Spark jobs and verify records are correctly conformed and loaded into Delta tables.
