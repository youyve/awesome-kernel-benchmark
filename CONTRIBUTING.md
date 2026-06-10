# Contributing

Thanks for helping keep this catalog complete and accurate. The tables in `README.md` are **generated** — do not edit them by hand.

## The one rule

**Edit [`data/benchmarks.yaml`](data/benchmarks.yaml), then regenerate:**

```bash
pip install -r requirements.txt
python3 scripts/generate.py            # rewrites README.md + data/benchmarks.json
python3 scripts/generate.py --check    # validate only (use this in CI / before committing)
```

Commit the YAML change **and** the regenerated `README.md` + `data/benchmarks.json` together.

## Adding an entry

Copy this template into the `benchmarks:` list and fill it in. Field meanings and the controlled vocabularies are in [`SCHEMA.md`](SCHEMA.md).

```yaml
  - id: my-benchmark            # unique kebab-case slug
    name: My Benchmark
    year: "2025"
    org: Lab / Company
    layer: substrate-suite      # agent-benchmark | substrate-suite | dataset | tooling
    abstraction: kernel         # micro | kernel | fused-op | operator | proxy-app | application | suite | dataset | harness
    family: classic-gpu-suite   # see SCHEMA.md (agent benchmarks: agent-benchmark)
    motifs: [dense-LA, reduction-scan]   # multi-tag, Berkeley 13 + DL extensions
    measures: [correctness, performance]
    bottleneck: compute
    languages: [CUDA]           # or programming_models: [Triton]
    hardware: [NVIDIA]
    verify: yes                 # yes | no | partial  (built-in correctness oracle)
    ships_kernels: yes          # yes | no | partial  (re-runnable reference kernels)
    used_by_agents: [SomeAgent] # LLM kernel-agents that evaluate on it (omit if none)
    code: https://github.com/...
    paper: https://arxiv.org/abs/...
    license: MIT
    status: active
    notes: "One line on why it matters for kernel agents."
```

## Inclusion criteria

Include a benchmark if **a kernel agent could plausibly be evaluated on, fine-tuned against, or asked to optimize/translate it.** That spans purpose-built agent harnesses, classic GPU/HPC suites, DL operator micro-benchmarks, sparse/graph/stencil suites, roofline microbenchmarks, compiler/HLS test suites, and the datasets/tooling around them.

Quality over coverage:
- **Prefer entries with a canonical, reachable URL** and, ideally, a paper. Verify the link works.
- **`used_by_agents` is the high-value field** — populate it with a citable agent/paper, or leave it empty to mark a coverage gap (both are useful signals).
- **Fill `verify` and `ships_kernels`** — they determine whether a suite is anti-gaming and auditable.
- **Multi-motif is normal.** Don't force a single bucket; tag every motif the suite genuinely exercises.

## Provenance, dedup & liveness

- **Don't double-count repackaged suites.** SPEC ACCEL derives from Parboil/Rodinia/NPB; the many KernelBench derivatives reuse its tasks. Note the lineage in `notes` rather than inflating counts.
- **Recurring kernels** (SpMV, SGEMM, BFS, FFT, stencil) appear in many suites — list the suite, not each kernel.
- **Track liveness** with `status` (`active`/`maintained`/`archived`/`retired`). Catalogs rot; keeping the source in git + YAML is the durability strategy.

## PR checklist

- [ ] Edited `data/benchmarks.yaml` only (not the generated tables).
- [ ] `python3 scripts/generate.py --check` passes (0 errors).
- [ ] Ran `python3 scripts/generate.py` and committed the updated `README.md` + `data/benchmarks.json`.
- [ ] New vocabulary values (motif/hardware/family) are also added to `scripts/generate.py` + `SCHEMA.md`.
- [ ] Canonical URL verified reachable.
