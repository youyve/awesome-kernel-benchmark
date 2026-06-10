#!/usr/bin/env python3
"""Generate the human-readable tables in README.md from data/benchmarks.yaml.

data/benchmarks.yaml is the single source of truth. This script validates it
against the controlled vocabularies below, renders the faceted views
(Layer-1 / Layer-2 tables, motif x family coverage matrix, agent<->substrate
map, summary stats), injects them into README.md between <!-- BEGIN:X -->/
<!-- END:X --> markers, and exports a stdlib-readable data/benchmarks.json.

Usage:
    python3 scripts/generate.py            # validate + write README.md + json
    python3 scripts/generate.py --check    # validate only, non-zero exit on error

Requires: PyYAML  (pip install -r requirements.txt)
"""
from __future__ import annotations
import argparse, json, os, sys
from collections import Counter, defaultdict

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install -r requirements.txt")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "benchmarks.yaml")
JSON_OUT = os.path.join(ROOT, "data", "benchmarks.json")
README = os.path.join(ROOT, "README.md")

# ---------------------------------------------------------------- vocabularies
LAYERS = ["agent-benchmark", "substrate-suite", "dataset", "tooling"]

# Layer-2 families in display order: (id, heading, blurb, matrix-code)
FAMILIES = [
    ("polyhedral",              "Polyhedral & loop-nest suites",            "Affine loop nests (PolyBench lineage); clean reference outputs make correctness trivial to check.", "POLY"),
    ("hpc-mini-app",            "HPC proxy & mini-apps",                    "DOE/NASA mini-apps: small, science-representative, almost all ship a verification figure-of-merit.", "HPC"),
    ("classic-gpu-suite",       "Classic GPU / heterogeneous suites",       "The pre-DL GPU canon (Berkeley-dwarf coverage) plus multi-language supersets (HeCBench, SYCL-Bench).", "GPU"),
    ("graph-suite",             "Graph-analytics suites",                   "Irregular / amorphous-data-parallel kernels with strong optimized baselines.", "GRAPH"),
    ("dl-micro",                "DL operator micro-benchmarks & vendor baselines", "The 'reference kernel you must beat' — cuDNN/cuBLAS, Triton tutorials, FlashAttention, etc.", "DLOP"),
    ("tensor-compiler",         "Tensor-compiler & autotuning substrates",  "Search / learned-cost-model substrates and the autoscheduled baselines agents are compared against.", "TC"),
    ("sparse-la",               "Sparse linear algebra & tensors",          "Sparse matrices/tensors and the SpMV/SpMM/SDDMM kernels over them.", "SPARSE"),
    ("stencil-spectral",        "Stencil, spectral & PDE",                  "Structured-grid stencils, FFT/spectral, and the DSLs/compilers that target them.", "STEN"),
    ("numerical-microbenchmark","Numerical & roofline microbenchmarks",     "FLOPS / bandwidth / roofline probes that calibrate the hardware ceilings agents reason about.", "NUM"),
    ("compiler-test-suite",     "Compiler, HLS & language test suites",     "Codegen substrates: LLVM test-suite, SPEC ACCEL/OMP, and HLS benchmark suites.", "COMP"),
    ("dl-system",               "DL system & end-to-end benchmarks",        "Model-level / framework-level suites that bound end-to-end targets.", "DLSYS"),
    ("serving-inference",       "LLM serving & inference benchmarks",       "Serving harnesses defining the TTFT/TPOT/throughput metrics that attention/MoE kernels move.", "SERV"),
    ("emerging-accelerator",    "Emerging & domestic accelerators",         "NPU / IPU / Tenstorrent / Cambricon / Moore Threads / RISC-V substrates and their agents.", "ACCEL"),
]
FAMILY_IDS = [f[0] for f in FAMILIES]
FAMILY_CODE = {f[0]: f[3] for f in FAMILIES}
FAMILY_HEADING = {f[0]: f[1] for f in FAMILIES}

ABSTRACTION = ["micro", "kernel", "fused-op", "operator", "proxy-app",
               "application", "suite", "dataset", "harness"]

# Berkeley 13 motifs (Asanovic et al., EECS-2006-183) + DL/utility extensions.
MOTIFS = [
    "dense-LA", "sparse-LA", "spectral", "n-body", "structured-grid",
    "unstructured-grid", "monte-carlo", "graph-traversal", "dynamic-programming",
    "combinational-logic", "branch-and-bound", "graphical-models",
    "finite-state-machine", "mapreduce",
    # DL / utility extensions (documented in SCHEMA.md):
    "attention", "reduction-scan", "elementwise", "data-movement", "mixed",
]
MEASURES = ["correctness", "performance", "portability", "scalability", "energy"]
BOTTLENECK = ["compute", "bandwidth", "latency", "communication", "mixed", "n/a"]
VERIFY = ["yes", "no", "partial"]
SHIPS = ["yes", "no", "partial"]
STATUS = ["active", "maintained", "archived", "retired", "unknown"]

REQUIRED = ["id", "name", "year", "org", "layer", "abstraction", "family",
            "motifs", "hardware", "code"]

VERIFY_BADGE = {"yes": "✅", "partial": "◐", "no": "—"}
SHIPS_BADGE = {"yes": "✅", "partial": "◐", "no": "—"}

# --------------------------------------------------------------------- loading
def load():
    with open(DATA, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    entries = doc["benchmarks"]
    # YAML 1.1 parses bare yes/no as booleans; coerce back to strings.
    for e in entries:
        for f in ("verify", "ships_kernels"):
            if isinstance(e.get(f), bool):
                e[f] = "yes" if e[f] else "no"
    return entries


def validate(entries):
    errors, warnings = [], []
    seen = set()
    for e in entries:
        tag = e.get("id") or e.get("name") or "<unknown>"
        for f in REQUIRED:
            if not e.get(f):
                errors.append(f"{tag}: missing required field '{f}'")
        if e.get("id") in seen:
            errors.append(f"duplicate id: {e['id']}")
        seen.add(e.get("id"))
        if e.get("layer") not in LAYERS:
            errors.append(f"{tag}: bad layer '{e.get('layer')}'")
        if e.get("abstraction") not in ABSTRACTION:
            warnings.append(f"{tag}: unknown abstraction '{e.get('abstraction')}'")
        fam = e.get("family")
        if e.get("layer") != "agent-benchmark" and fam not in FAMILY_IDS:
            errors.append(f"{tag}: bad family '{fam}' (layer={e.get('layer')})")
        for m in e.get("motifs", []):
            if m not in MOTIFS:
                warnings.append(f"{tag}: unknown motif '{m}'")
        for m in e.get("measures", []):
            if m not in MEASURES:
                warnings.append(f"{tag}: unknown measure '{m}'")
        if e.get("bottleneck") and e["bottleneck"] not in BOTTLENECK:
            warnings.append(f"{tag}: unknown bottleneck '{e['bottleneck']}'")
        if e.get("verify") and e["verify"] not in VERIFY:
            warnings.append(f"{tag}: bad verify '{e['verify']}'")
        if e.get("ships_kernels") and e["ships_kernels"] not in SHIPS:
            warnings.append(f"{tag}: bad ships_kernels '{e['ships_kernels']}'")
        if e.get("status") and e["status"] not in STATUS:
            warnings.append(f"{tag}: unknown status '{e['status']}'")
    return errors, warnings


# ------------------------------------------------------------------ rendering
def link(e):
    return f"[{e['name']}]({e['code']})"


def joinlist(xs, sep=" · "):
    return sep.join(xs) if xs else "—"


def render_stats(entries):
    n = len(entries)
    by_layer = Counter(e["layer"] for e in entries)
    sub = [e for e in entries if e["layer"] != "agent-benchmark"]
    by_fam = Counter(e["family"] for e in sub)
    hw = Counter(h for e in entries for h in e.get("hardware", []))
    out = [
        f"**{n} benchmarks** · {by_layer.get('agent-benchmark',0)} purpose-built agent benchmarks · "
        f"{len(sub)} substrate / dataset / tooling entries across {len([f for f in FAMILY_IDS if by_fam.get(f)])} families.",
        "",
        "| Layer | Count |",
        "|:---|---:|",
    ]
    for lyr in LAYERS:
        if by_layer.get(lyr):
            out.append(f"| {lyr} | {by_layer[lyr]} |")
    out += ["", "| Top hardware targets | Entries |", "|:---|---:|"]
    for h, c in hw.most_common(8):
        out.append(f"| {h} | {c} |")
    return "\n".join(out)


def render_layer1(entries):
    rows = sorted([e for e in entries if e["layer"] == "agent-benchmark"],
                  key=lambda e: (e.get("year", ""), e["name"]))
    out = ["| Benchmark | Year | Abstraction | Motifs | Hardware | Verify | Runs on (substrate) |",
           "|:---|:---:|:---|:---|:---|:---:|:---|"]
    for e in rows:
        out.append("| {nm} | {yr} | {ab} | {mo} | {hw} | {vf} | {sub} |".format(
            nm=link(e), yr=e.get("year", ""), ab=e.get("abstraction", ""),
            mo=joinlist(e.get("motifs", [])), hw=joinlist(e.get("hardware", [])),
            vf=VERIFY_BADGE.get(e.get("verify"), "—"),
            sub=joinlist(e.get("substrates", []), ", ")))
    return "\n".join(out)


def render_layer2(entries):
    blocks = []
    for fam, heading, blurb, _code in FAMILIES:
        rows = sorted([e for e in entries
                       if e["layer"] != "agent-benchmark" and e["family"] == fam],
                      key=lambda e: (e.get("year", ""), e["name"]))
        if not rows:
            continue
        blocks.append(f"### {heading}\n\n{blurb}\n")
        blocks.append("| Suite | Year · Org | Motifs | Languages / model | Verify | Ships | Used by (agents) |")
        blocks.append("|:---|:---|:---|:---|:---:|:---:|:---|")
        for e in rows:
            blocks.append("| {nm} | {yr} · {org} | {mo} | {pm} | {vf} | {sh} | {ag} |".format(
                nm=link(e), yr=e.get("year", ""), org=e.get("org", "")[:42],
                mo=joinlist(e.get("motifs", [])),
                pm=joinlist(e.get("programming_models", []) or e.get("languages", [])),
                vf=VERIFY_BADGE.get(e.get("verify"), "—"),
                sh=SHIPS_BADGE.get(e.get("ships_kernels"), "—"),
                ag=joinlist(e.get("used_by_agents", []), ", ")))
        blocks.append("")
    return "\n".join(blocks).rstrip()


def render_matrix(entries):
    sub = [e for e in entries if e["layer"] != "agent-benchmark"]
    counts = defaultdict(lambda: defaultdict(int))
    for e in sub:
        for m in e.get("motifs", []):
            counts[m][e["family"]] += 1
    fams = [f for f in FAMILY_IDS if any(counts[m][f] for m in MOTIFS)]
    header = "| Motif \\ Family | " + " | ".join(FAMILY_CODE[f] for f in fams) + " | Σ |"
    sep = "|:---|" + "".join(":--:|" for _ in fams) + ":--:|"
    out = [header, sep]
    for m in MOTIFS:
        rowtot = sum(counts[m][f] for f in fams)
        if rowtot == 0:
            continue
        cells = " | ".join(str(counts[m][f] or "") for f in fams)
        out.append(f"| {m} | {cells} | {rowtot} |")
    legend = "  \n".join(f"`{FAMILY_CODE[f]}` = {FAMILY_HEADING[f]}"
                         for f in fams)
    return "\n".join(out) + "\n\n<sub>" + legend + "</sub>"


def render_agentmap(entries):
    rows = []
    # substrate -> agents
    for e in sorted(entries, key=lambda e: e["name"]):
        ag = e.get("used_by_agents", [])
        if ag and e["layer"] != "agent-benchmark":
            rows.append((e["name"], e["family"], ", ".join(ag),
                         SHIPS_BADGE.get(e.get("ships_kernels"), "—")))
    out = ["| Substrate | Family | Used by (kernel agents) | Ships kernels |",
           "|:---|:---|:---|:---:|"]
    for nm, fam, ag, sh in rows:
        out.append(f"| {nm} | {fam} | {ag} | {sh} |")
    return "\n".join(out)


SECTIONS = {
    "STATS": render_stats,
    "LAYER1": render_layer1,
    "LAYER2": render_layer2,
    "MATRIX": render_matrix,
    "AGENTMAP": render_agentmap,
}


def inject(readme_text, key, content):
    begin, end = f"<!-- BEGIN:{key} -->", f"<!-- END:{key} -->"
    if begin not in readme_text or end not in readme_text:
        raise SystemExit(f"README is missing markers for {key}")
    pre = readme_text.split(begin)[0]
    post = readme_text.split(end, 1)[1]
    note = "<!-- generated by scripts/generate.py — do not edit by hand -->"
    return f"{pre}{begin}\n{note}\n\n{content}\n\n{end}{post}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only")
    args = ap.parse_args()

    entries = load()
    errors, warnings = validate(entries)
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(f"{len(errors)} validation error(s)")
    print(f"validated {len(entries)} entries ({len(warnings)} warning(s))")

    if args.check:
        return

    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with open(README, encoding="utf-8") as fh:
        txt = fh.read()
    for key, fn in SECTIONS.items():
        txt = inject(txt, key, fn(entries))
    with open(README, "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(f"wrote README.md and data/benchmarks.json")


if __name__ == "__main__":
    main()
