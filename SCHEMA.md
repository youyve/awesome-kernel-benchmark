# Data schema & controlled vocabularies

[`data/benchmarks.yaml`](data/benchmarks.yaml) is the single source of truth. Every entry is one mapping in the top-level `benchmarks:` list. [`scripts/generate.py`](scripts/generate.py) validates each entry against the vocabularies below and renders the README tables; `--check` validates without writing.

This document is the **data dictionary**. The design follows multi-tag, faceted benchmark-taxonomy practice — Berkeley's 13 computational motifs ([EECS-2006-183](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2006/EECS-2006-183.pdf)) and the YAML-source-of-truth → generated-tables pattern of the [Herten et al. HPC benchmark survey](https://fzj-jsc.github.io/benchmark-survey/).

## Fields

| Field | Required | Type | Notes |
|:---|:---:|:---|:---|
| `id` | ✅ | string (slug) | Unique, kebab-case. Stable anchor; never reuse. |
| `name` | ✅ | string | Display name. |
| `full_name` | | string | Expanded/official name. |
| `year` | ✅ | string | First release year (quote it: `"2020"`). |
| `org` | ✅ | string | Authoring org/lab. |
| `layer` | ✅ | enum | See **layer** below. |
| `abstraction` | ✅ | enum | Primary axis — see **abstraction**. |
| `family` | ✅* | enum | Required for non-agent layers; see **family**. Agent benchmarks use `agent-benchmark`. |
| `motifs` | ✅ | list<enum> | Secondary axis; **multi-tag** — see **motifs**. |
| `measures` | | list<enum> | `correctness` · `performance` · `portability` · `scalability` · `energy`. |
| `bottleneck` | | enum | `compute` · `bandwidth` · `latency` · `communication` · `mixed` · `n/a` (roofline regime). |
| `programming_models` | | list<string> | Preferred over `languages` when a DSL/model is the point (Triton, SYCL, …). |
| `languages` | | list<string> | Source languages; used in tables if `programming_models` absent. |
| `hardware` | ✅ | list<enum> | See **hardware**. |
| `precision` | | list<string> | FP64 · FP32 · TF32 · FP16 · BF16 · FP8 · FP4 · INT8 · INT4. |
| `verify` | | `yes`/`no`/`partial` | Built-in correctness oracle (reference output / checksum / residual). |
| `ships_kernels` | | `yes`/`no`/`partial` | Ships re-runnable reference/solution kernels. |
| `used_by_agents` | | list<string> | LLM kernel-agent / GPU-code-LLM works using it as a substrate. Drives the [agent ↔ substrate map](README.md#agent--substrate-map). |
| `substrates` | | list<string> | (agent-benchmark only) classic suites the benchmark wraps/runs on. |
| `code` | ✅ | url | Canonical repo or project page. |
| `paper` | | url | Paper / arXiv / venue. |
| `license` | | string | SPDX-ish; benchmark's own license. |
| `status` | | enum | `active` · `maintained` · `archived` · `retired` · `unknown`. |
| `notes` | | string | One-line "why it matters" for kernel agents. |

> YAML 1.1 parses bare `yes`/`no` as booleans; the loader coerces `verify`/`ships_kernels` back to strings, so you may write them unquoted.

## Controlled vocabularies

### layer
What role the entry plays.
- `agent-benchmark` — a harness *designed* to score LLM kernel generation (Layer 1).
- `substrate-suite` — a classic suite agents are evaluated *on* / optimize / translate (Layer 2).
- `dataset` — inputs only, no kernels (e.g. SuiteSparse, DLMC, TenSet).
- `tooling` — a measurement harness with no fixed kernel set (e.g. NVBench, nvbandwidth, serving load testers).

### abstraction *(primary axis)*
Granularity, defined to keep tagging consistent:
`micro` (single arithmetic/bandwidth probe) · `kernel` (one GPU kernel) · `fused-op` (a fused operator sequence) · `operator` (a full DL operator/layer) · `proxy-app` (mini-app standing in for a real application) · `application` (full end-to-end model/app) · `suite` (curated collection) · `dataset` (inputs only) · `harness` (measurement framework).

### motifs *(secondary axis)* — Berkeley 13 + DL extensions
**Multi-tag and expected** — attention = `dense-LA` + `reduction-scan`; SpMV = `sparse-LA` + `graph-traversal`.

Berkeley 13 ([View from Berkeley](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2006/EECS-2006-183.pdf), extending Colella's 7):
`dense-LA` · `sparse-LA` · `spectral` · `n-body` · `structured-grid` · `unstructured-grid` · `monte-carlo` (Berkeley's MapReduce/Monte-Carlo) · `graph-traversal` · `dynamic-programming` · `combinational-logic` · `branch-and-bound` · `graphical-models` · `finite-state-machine` · `mapreduce`.

DL / utility extensions (the motifs predate deep learning):
`attention` · `reduction-scan` · `elementwise` · `data-movement` · `mixed` (use sparingly for genuinely multi-motif suites).

Assignments follow the suite's own paper where it self-classifies (OpenDwarfs, Rodinia); otherwise they are an editorial call per the Berkeley definitions.

### family *(Layer-2 grouping)*
`polyhedral` · `hpc-mini-app` · `classic-gpu-suite` · `graph-suite` · `dl-micro` · `tensor-compiler` · `sparse-la` · `stencil-spectral` · `numerical-microbenchmark` · `compiler-test-suite` · `dl-system` · `serving-inference` · `emerging-accelerator`. (Agent benchmarks: `agent-benchmark`.)

### hardware
`NVIDIA` · `AMD` · `Intel-GPU` · `CPU` · `Ascend-NPU` · `Trainium` · `TPU` · `IPU` · `Tenstorrent` · `Cambricon` · `MooreThreads` · `RISC-V` · `ARM` · `FPGA`. (Add new values here and in `SCHEMA.md` together.)

### Badges in generated tables
`✅` yes · `◐` partial · `—` no/none — for both **Verify** (correctness oracle) and **Ships** (re-runnable kernels).

## Methodology scorecard (`data/scorecard.yaml`)

A second data file grades **Layer-1 agent benchmarks only** on the methodology choices that separate trustworthy numbers from inflated ones. A row may exist **only** when the grader actually read primary evidence (harness source / paper) — README self-claims are never accepted. Keyed by the entry `id`.

| Field | Type | Meaning |
|:---|:---|:---|
| `oracle` | enum | correctness-oracle strength: `strong` ● (multi-shape/seed/edge-case or held-out tests, ≤1e-4 dtype-aware tolerance and/or fwd+bwd) · `partial` ◐ (meaningful hardening) · `weak` ○ (few random inputs, fixed shapes, loose tolerance) · `unknown` ? |
| `timing` | enum | timing rigor: `strong` ● (clock control + cache control + distribution stats) · `partial` ◐ (cache control or adaptive sampling, no clock lock) · `weak` ○ (bare event timing, fixed reps) · `unknown` ? |
| `budget` | enum | cost reporting: `strong` ● (multi-axis, sequential vs parallel) · `partial` ◐ (pass@k or one fixed budget point) · `none` — · `unknown` ? |
| `baseline` | string | what the speedup/score denominator actually is |
| `use_when` | string | one-line "pick this benchmark if …" |
| `evidence` | url | the primary source the grades are derived from |

Grading a new benchmark (with evidence links) is the most valuable PR this repository accepts.

## Validation

```bash
pip install -r requirements.txt
python3 scripts/generate.py --check   # errors → non-zero exit; warnings → stderr
```

Hard errors (block a PR): missing required field, duplicate `id`, bad `layer`, bad `family` on a non-agent entry. Unknown motif/measure/bottleneck/status values are warnings (so a deliberate vocabulary extension is visible in review, not silently accepted).
