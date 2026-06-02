# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Install

```bash
pip install -e .          # Dev install
bflow --help              # CLI entry point
```

Python >=3.11 required. No test suite yet. No Makefile or tox.

## CLI

Entry point: `bflow` (defined in `pyproject.toml` → `benchflow.cli:main`). Key command groups:

- `bflow bootstrap [--single-cluster]` — install operators, Kueue, Grafana, MLflow
- `bflow experiment run <experiment.yaml>` — resolve + execute an experiment
- `bflow experiment resolve <experiment.yaml>` — resolve without running
- `bflow deploy / undeploy` — manage inference deployments
- `bflow benchmark` — run benchmarks directly
- `bflow metrics` — collect and view Prometheus/DCGM metrics
- `bflow artifacts` — collect benchmark artifacts
- `bflow mlflow` — upload results to MLflow
- `bflow profiles` — list/validate profiles
- `bflow watch` — monitor running executions

## Architecture

### Layers (bottom-up)

1. **contracts/** — shared frozen dataclasses at the orchestration/toolbox boundary: `ResolvedRunPlan`, `ExecutionContext`, `ExecutionSummary`, `BenchmarkOutcome`
2. **models.py** — all config dataclasses: `DeploymentProfile`, `BenchmarkProfile`, `MetricsProfile`, specs
3. **loaders.py** — YAML parsing, profile resolution, validation helpers
4. **plans.py** — resolves `Experiment` → `ResolvedRunPlan` (immutable execution document)
5. **toolbox/** — reusable operational actions (setup, deploy, benchmark, collect, upload). CLI commands delegate here.
6. **orchestration/** — Tekton PipelineRun rendering, submission, watch, cancellation (`tekton.py`, `service.py`)
7. **commands/** — Click command handlers. Thin — delegate into toolbox.

### Platform Backends

Three deployment platforms, each with deploy/setup/cleanup modules:

| Platform | Deploy | Setup | Cleanup |
|----------|--------|-------|---------|
| llm-d    | `deploy/llmd.py` | `setup/llmd.py` | `cleanup/llmd.py` |
| rhoai    | `deploy/rhoai.py` | `setup/rhoai.py` | `cleanup/rhoai.py` |
| rhaiis   | `deploy/rhaiis.py` | — | `cleanup/rhaiis.py` |

Dispatch happens in `toolbox/platform.py` based on `ResolvedRunPlan.deployment.platform`.

### Benchmark Backends

- **GuideLLM** (`benchmark/guidellm.py`) — primary, OpenAI-compatible HTTP backend
- **AIPerf** (`benchmark/aiperf.py`) — narrow path, Mooncake trace replay only

### Key Modules

| Module | Role |
|--------|------|
| `cluster.py` | kubectl/oc wrapper |
| `kueue.py` | Queue-based admission control |
| `remote_jobs.py` | Remote target cluster job execution |
| `mlflow_upload.py` | MLflow run creation, artifact/metric logging |
| `platform_state.py` | Cluster-wide setup state tracking via ConfigMap |
| `matrix.py` | Cartesian product expansion for matrix experiments |
| `install.py` | Bootstrap orchestration |
| `renderers/` | Kubernetes manifest rendering |
| `metrics/prometheus.py` | Prometheus metric queries |
| `metrics/viewer.py` | Grafana dashboard generation |
| `benchmark/processor/` | Result data processing |
| `benchmark/run_report.py` | Report generation |
| `benchmark/run_report_insights.py` | Insight extraction from results |

## Execution Flow

```
Experiment YAML → loaders → Experiment → plans → ResolvedRunPlan
  → orchestration/tekton (render PipelineRun) → Kubernetes
  → Tekton pipeline stages: resolve → setup → download → deploy → wait → benchmark → collect → upload → cleanup
  → MLflow (metrics + artifacts)
```

Matrix experiments expand into multiple child PipelineRuns admitted via Kueue.

## Profiles & Experiments

**Profiles** (`profiles/`): reusable YAML configs with `apiVersion: benchflow.io/v1alpha1`
- `benchmark/` — GuideLLM/AIPerf parameters (rates, token counts, duration)
- `deployment/` — platform-specific runtime config (replicas, TP, vLLM args, model storage)
- `metrics/` — metrics collection scope

**Experiments** (`experiments/`): combine model + deployment profile + benchmark profile. Lists in any field trigger matrix expansion.

## Cluster Topologies

- **Single cluster**: Tekton + Kueue + GPU workloads in same cluster
- **Management + target**: Tekton on management cluster, Jobs on remote targets via kubeconfig

## External Systems

- **Tekton** — pipeline orchestration (definitions in `tekton/`)
- **Kueue** — per-cluster admission control
- **MLflow** — experiment tracking, artifact storage (S3 backend)
- **Prometheus/Grafana** — GPU metrics (DCGM exporter)
- **HuggingFace** — model downloads
- **vLLM** — inference runtime

## Container Image

Built via GitHub Actions (`.github/workflows/build-images.yaml`), pushed to `ghcr.io/albertoperdomo2/benchflow`. Base image is `guidellm:nightly` with helm, helmfile, kustomize, oc added.

## Working Principles

See `AGENTS.md` for full principles. Key points:

- **RunPlan is the contract** — tasks consume the run plan, not flat parameter lists
- **Profiles over overrides** — new scenario = new profile, not inline overrides
- **One blessed path** — prefer narrow working slice over broad scaffold
- **Python owns logic** — Tekton stays thin, orchestration-focused
- **Toolbox is reusable** — CLI commands and task entrypoints delegate into `toolbox/`
- **Simplify before extending** — question changes that add knobs or alternate modes
