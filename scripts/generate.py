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
SCORECARD_DATA = os.path.join(ROOT, "data", "scorecard.yaml")
JSON_OUT = os.path.join(ROOT, "data", "benchmarks.json")
READMES = [os.path.join(ROOT, "README.md"), os.path.join(ROOT, "README.zh.md")]

# ---------------------------------------------------------------- vocabularies
LAYERS = ["agent-benchmark", "substrate-suite", "dataset", "tooling"]

# Layer-2 families in display order (ordered by relevance to kernel agents,
# most-reached-for first): (id, plain-language heading, "use this for" blurb,
# matrix-code). IDs are stable; only the display layer is plain-language.
FAMILIES = [
    ("dl-micro",                "DL operators & vendor baselines",          "The kernels your agent must beat: cuDNN/cuBLAS, FlashAttention, Triton tutorials, Liger. Use as reference implementations and speedup denominators.", "DLOP"),
    ("tensor-compiler",         "Tensor compilers & autotuners",            "Machine-generated baselines (TVM/Ansor, Hidet, CUTLASS profiler). Use when you want your agent compared against autotuned — not just eager — code.", "TC"),
    ("serving-inference",       "LLM serving benchmarks",                   "Where kernel wins become end-to-end wins: TTFT/TPOT/throughput harnesses (vLLM, SGLang). Use to show a kernel matters at the serving level.", "SERV"),
    ("dl-system",               "Whole-model DL benchmarks",                "Model-level suites (MLPerf, TorchBench, TorchInductor). Use to bound end-to-end impact of kernel-level changes.", "DLSYS"),
    ("sparse-la",               "Sparse linear algebra",                    "SpMV/SpMM/SDDMM kernels and the matrix collections (SuiteSparse, DLMC) they run on. Irregular memory patterns — a hard, under-benchmarked motif.", "SPARSE"),
    ("stencil-spectral",        "Stencils, FFT & PDE",                      "Structured-grid stencils, FFT/spectral kernels, and their DSLs (Halide, Devito). Classic memory-bound optimization targets with clean verification.", "STEN"),
    ("graph-suite",             "Graph analytics (irregular)",              "BFS/PageRank/connected-components with strong optimized baselines (Gunrock, GAPBS). Use to test agents beyond dense regular loops.", "GRAPH"),
    ("polyhedral",              "Dense loop nests (PolyBench lineage)",     "Regular affine loop kernels (GEMM-like, stencils) with trivially checkable outputs — the easiest substrate to verify, and the most-used in agent papers.", "POLY"),
    ("hpc-mini-app",            "HPC proxy & mini-apps",                    "DOE/NASA mini-apps (NPB, XSBench, LULESH): small, science-representative, almost all ship a built-in verification figure-of-merit.", "HPC"),
    ("classic-gpu-suite",       "Classic GPU suites (pre-DL canon)",        "Rodinia, SHOC, Parboil, HeCBench: the broad-coverage GPU canon. HeCBench alone gives one kernel in 4+ programming models.", "GPU"),
    ("numerical-microbenchmark","Peak & roofline probes",                   "STREAM, ERT, mixbench, gpu-burn: measure what the hardware can actually do. The calibration layer any ceiling-relative metric depends on.", "NUM"),
    ("compiler-test-suite",     "Compiler & HLS test suites",               "LLVM test-suite, SPEC ACCEL/OMP, MachSuite: codegen substrates with strict correctness baked in.", "COMP"),
    ("emerging-accelerator",    "NPU & emerging accelerators",              "Ascend, Cambricon, Tenstorrent, IPU substrates — where vendor-kernel scarcity makes agents most valuable and baselines weakest.", "ACCEL"),
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

SCORE_GRADES = {"strong": "●", "partial": "◐", "weak": "○", "none": "—", "unknown": "?"}
SCORE_FIELDS = ["oracle", "timing", "budget"]   # graded enums; baseline/use_when are text


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


def load_scorecard():
    if not os.path.exists(SCORECARD_DATA):
        return {}
    with open(SCORECARD_DATA, encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("scorecard", {}) or {}


def validate_scorecard(entries, scorecard):
    errors = []
    ids = {e["id"] for e in entries if e["layer"] == "agent-benchmark"}
    for sid, row in scorecard.items():
        if sid not in ids:
            errors.append(f"scorecard: '{sid}' is not a Layer-1 benchmark id")
            continue
        for f in SCORE_FIELDS:
            if row.get(f) not in SCORE_GRADES:
                errors.append(f"scorecard {sid}: bad {f} grade '{row.get(f)}'")
        for f in ("baseline", "use_when", "evidence"):
            if not row.get(f):
                errors.append(f"scorecard {sid}: missing '{f}'")
    return errors


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


def render_scorecard(entries, scorecard):
    """Methodology scorecard: HOW each Layer-1 benchmark measures, graded only
    where primary evidence (harness code / paper) was actually read."""
    l1 = {e["id"]: e for e in entries if e["layer"] == "agent-benchmark"}
    graded = [(sid, row) for sid, row in scorecard.items() if sid in l1]
    graded.sort(key=lambda kv: (l1[kv[0]].get("year", ""), l1[kv[0]]["name"]))

    out = ["| Benchmark | Year | Hardware | Oracle | Timing | Baseline | Budget | Pick this if… |",
           "|:---|:---:|:---|:---:|:---:|:---|:---:|:---|"]
    for sid, row in graded:
        e = l1[sid]
        out.append("| {nm} | {yr} | {hw} | {o} | {t} | {bl} | {bu} | {uw} |".format(
            nm=f"[{e['name']}]({row['evidence']})", yr=e.get("year", ""),
            hw=joinlist(e.get("hardware", [])),
            o=SCORE_GRADES[row["oracle"]], t=SCORE_GRADES[row["timing"]],
            bl=row["baseline"], bu=SCORE_GRADES[row["budget"]],
            uw=row["use_when"]))

    ungraded = sorted((e for sid, e in l1.items() if sid not in scorecard),
                      key=lambda e: (e.get("year", ""), e["name"]))
    legend = ("**Grades** (criteria in [`data/scorecard.yaml`](data/scorecard.yaml) / "
              "[`SCHEMA.md`](SCHEMA.md)): ● strong · ◐ partial · ○ weak · — none · ? unverified. "
              "Grades are assigned ONLY from primary evidence (harness source / paper) — "
              "no benchmark is graded from its README claims.")
    not_yet = ("**Not yet graded** (" + str(len(ungraded)) + "): " +
               ", ".join(link(e) for e in ungraded) +
               ". PRs grading these against the criteria are the most valuable contribution this list can receive.")
    return "\n".join(out) + "\n\n" + legend + "\n\n" + not_yet


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
    "STATS": lambda en, sc: render_stats(en),
    "SCORECARD": lambda en, sc: render_scorecard(en, sc),
    "LAYER1": lambda en, sc: render_layer1(en),
    "LAYER2": lambda en, sc: render_layer2(en),
    "MATRIX": lambda en, sc: render_matrix(en),
    "AGENTMAP": lambda en, sc: render_agentmap(en),
}


def inject(readme_text, key, content):
    begin, end = f"<!-- BEGIN:{key} -->", f"<!-- END:{key} -->"
    if begin not in readme_text or end not in readme_text:
        return readme_text  # a README variant may omit some sections
    pre = readme_text.split(begin)[0]
    post = readme_text.split(end, 1)[1]
    note = "<!-- generated by scripts/generate.py — do not edit by hand -->"
    return f"{pre}{begin}\n{note}\n\n{content}\n\n{end}{post}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only")
    args = ap.parse_args()

    entries = load()
    scorecard = load_scorecard()
    errors, warnings = validate(entries)
    errors += validate_scorecard(entries, scorecard)
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(f"{len(errors)} validation error(s)")
    print(f"validated {len(entries)} entries, {len(scorecard)} scorecard rows "
          f"({len(warnings)} warning(s))")

    if args.check:
        return

    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump({"benchmarks": entries, "scorecard": scorecard}, fh,
                  indent=2, ensure_ascii=False)
        fh.write("\n")

    for readme in READMES:
        if not os.path.exists(readme):
            continue
        with open(readme, encoding="utf-8") as fh:
            txt = fh.read()
        for key, fn in SECTIONS.items():
            txt = inject(txt, key, fn(entries, scorecard))
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(txt)
        print(f"wrote {os.path.basename(readme)}")
    print("wrote data/benchmarks.json")


if __name__ == "__main__":
    main()
