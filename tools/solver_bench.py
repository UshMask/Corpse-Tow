"""Reproducible old/new solve + solvePersistent API benchmark on the game JVM.

Defaults: 4 independent JVM forks, 4 AB/BA pairs/fork, 2 warmup sequences/API,
3000 warmup ticks and 6000 measured ticks/sequence. Short smoke example:
  .venv/Scripts/python.exe -B tools/solver_bench.py --forks 2 --repeats 2 \
      --warmup 1 --warmup-ticks 80 --ticks 120 --scenarios 0,12,14,16,17

Dependencies are read from private local/settings.json. All generated artifacts
stay in local/. report.json deliberately omits machine-specific dependency paths;
local compile logs contain actual commands. No production/JAR files are modified.

A pair compares whole deterministic sequences with fresh state, not alternating
calls on shared state. JVM forks are the independent experimental units; pairs
within a fork are correlated. Ratios are paired old/new, never ratios of minima.
API timing includes solver record reads/sync, world queries, physics and writes/
publication. Caller input table updates, seed reads, prepare/release and checksum
walks are timed separately. Additional clone-fixture Body.read/Body.write loop
microdiagnostics run after all primary measurements; these exclude group writes
and are NOT an additive decomposition of API cost. There is no pure-core or game
frame measurement. The idle scene is only a timer/loop no-call control, not solver work.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "cvp-solver-bench/2"
BASELINE_CLASS = "TowingSolverBaseline"
BASELINE_LUA_CLASS = "CVPSolverNativeBaseline"
RAW_SERIES = ("apiNs", "inputUpdateNs", "seedReadNs", "checksumNs")


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def canonical_sha256(path: Path) -> str:
    """Portable source identity, in addition to hashes of the actual compiled bytes."""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resolve_path(repo: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return (path if path.is_absolute() else repo / path).resolve()


def read_settings(repo: Path) -> tuple[Path, dict]:
    path = repo / "local/settings.json"
    if not path.is_file():
        raise SystemExit("missing local/settings.json")
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def classpath(game: Path, zombiebuddy: Path, viewpoint: Path | None, extra: list[Path]) -> str:
    parts = [str(path) for path in extra] + [str(game / "projectzomboid.jar"), str(game / "*"), str(zombiebuddy)]
    if viewpoint and viewpoint.is_file():
        parts.append(str(viewpoint))
    return ";".join(parts)


def run_step(cmd: list[str], cwd: Path, log_path: Path, label: str) -> str:
    started = time.perf_counter()
    with log_path.open("wb") as handle:
        handle.write((f"[solver_bench] {label}\ncommand: {subprocess.list2cmdline(cmd)}\n\n").encode("utf-8"))
        handle.flush()
        completed = subprocess.run(cmd, cwd=str(cwd), stdout=handle, stderr=subprocess.STDOUT)
        handle.write(f"\nexit: {completed.returncode}; seconds: {time.perf_counter()-started:.3f}\n".encode())
    if completed.returncode:
        raise SystemExit(f"{label} failed (exit {completed.returncode}); inspect local log {log_path.name}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def git_head(repo: Path) -> dict:
    # Metadata only; never include dirty filenames or personal paths in reports.
    def call(*args: str) -> str:
        try:
            result = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=10)
            return result.stdout.decode("utf-8", "replace").strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return {"head": call("rev-parse", "HEAD"), "branch": call("branch", "--show-current"),
            "dirty": bool(call("status", "--porcelain"))}


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank quantile (p95 of 20 samples is the 19th sorted sample)."""
    if not values or not 0 < q <= 1:
        raise ValueError("nonempty values and 0 < q <= 1 required")
    return sorted(values)[math.ceil(q * len(values)) - 1]


def describe(values: list[float]) -> dict:
    if not values:
        raise ValueError("empty sample")
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"n": len(values), "min": min(values), "median": statistics.median(values),
            "p95": percentile(values, .95), "p99": percentile(values, .99), "max": max(values),
            "mean": mean, "stdev": sd, "cv": sd / mean if mean else 0.0,
            "range": max(values) - min(values),
            "iqr": percentile(values, .75) - percentile(values, .25)}


def validate_fork(data: dict) -> bool:
    """Reject missing/truncated raw series and forged aggregate-only results."""
    if data.get("schema") != 2 or not data.get("scenarios"):
        raise ValueError("invalid benchmark schema or empty scenarios")
    ticks, repeats = data["ticks"], data["repeats"]
    if not isinstance(ticks, int) or ticks < 1 or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("invalid ticks/repeats")
    matched = True
    indices = set()
    for scene in data["scenarios"]:
        if scene["index"] in indices:
            raise ValueError("duplicate scene")
        indices.add(scene["index"])
        idle = scene["index"] == 17
        expected_modes = {"no-call"} if idle else {"solve", "solvePersistent"}
        if {m["api"] for m in scene["modes"]} != expected_modes or len(scene["modes"]) != len(expected_modes):
            raise ValueError("missing or duplicate API mode")
        for mode in scene["modes"]:
            if len(mode["pairs"]) != repeats:
                raise ValueError("wrong replica count")
            for rep, pair in enumerate(mode["pairs"]):
                expected_order = "AB" if (rep + data["orderOffset"]) % 2 == 0 else "BA"
                if pair["order"] != expected_order or pair["replica"] != rep:
                    raise ValueError("invalid AB/BA sequence")
                for side in ("baseline", "current"):
                    run = pair[side]
                    if run["apiCalls"] != scene["groups"] * ticks or (idle and run["apiCalls"]):
                        raise ValueError("wrong API call count")
                    for key in RAW_SERIES:
                        if len(run[key]) != ticks or any(type(x) is not int or x < 0 for x in run[key]):
                            raise ValueError(f"invalid raw series {key}")
                    for key in ("prepareNs", "releaseNs", "fixtureNs"):
                        if type(run[key]) is not int or run[key] < 0 or (idle and run[key] != 0):
                            raise ValueError(f"invalid lifecycle timing {key}")
                    diag = run["diagnostics"]
                    for key in ("sumSolverIterations", "gapTicks", "obstructedTicks", "unconvergedTicks", "fallbackTicks", "nonzeroLoadTicks"):
                        if type(diag[key]) is not int or diag[key] < 0 or (key.endswith("Ticks") and diag[key] > ticks):
                            raise ValueError(f"invalid diagnostic {key}")
                    for key in ("maxResidual", "maxAbsLoad"):
                        if not isinstance(diag[key], (int, float)) or not math.isfinite(diag[key]) or diag[key] < 0:
                            raise ValueError(f"invalid diagnostic {key}")
                    if idle and any(diag.values()):
                        raise ValueError("idle control reported solver work")
                    for key in ("checksum", "releasedChecksum"):
                        if not isinstance(run[key], str) or len(run[key]) != 16:
                            raise ValueError("missing checksum")
                        int(run[key], 16)
                same = all(pair["baseline"][key] == pair["current"][key]
                           for key in ("checksum", "releasedChecksum"))
                if pair["checksumsMatch"] != same:
                    raise ValueError("inconsistent checksum flag")
                matched &= same
    bridges = data["bridgeDiagnostics"]
    expected = {(s["index"], m["api"]) for s in data["scenarios"] for m in s["modes"] if m["api"] != "no-call"}
    if {(b["index"], b["api"]) for b in bridges} != expected or len(bridges) != len(expected):
        raise ValueError("missing or duplicate bridge diagnostic")
    for bridge in bridges:
        checksums = []
        for side in ("baseline", "current"):
            checksum = bridge[side]["checksum"]
            if not isinstance(checksum, str) or len(checksum) != 16:
                raise ValueError("invalid bridge checksum")
            int(checksum, 16)
            checksums.append(checksum)
            for key in ("bodyReadNs", "bodyPublicationNs"):
                values = bridge[side][key]
                if len(values) != min(ticks, 1000) or any(type(x) is not int or x < 0 for x in values):
                    raise ValueError("invalid bridge diagnostic series")
        matched &= checksums[0] == checksums[1]
    return matched and data.get("result") == "pass"


def checksums_reproducible(forks: list[dict]) -> bool:
    identities = {}
    for fork in forks:
        for scene in fork["scenarios"]:
            for mode in scene["modes"]:
                for pair in mode["pairs"]:
                    for side in ("baseline", "current"):
                        key = (scene["index"], mode["api"], side)
                        identities.setdefault(key, set()).add((pair[side]["checksum"], pair[side]["releasedChecksum"]))
    return bool(identities) and all(len(values) == 1 for values in identities.values())


def aggregate(forks: list[dict]) -> list[dict]:
    """Per-pair distributions + between-fork spread; never pool ticks as replicas."""
    if not forks:
        raise ValueError("no forks")
    layout = [(s["index"], m["api"]) for s in forks[0]["scenarios"] for m in s["modes"]]
    if any([(s["index"], m["api"]) for s in f["scenarios"] for m in s["modes"]] != layout for f in forks):
        raise ValueError("fork scenario/API mismatch")
    output = []
    for scene0 in forks[0]["scenarios"]:
        for mode0 in scene0["modes"]:
            replicas, per_fork = [], []
            for fork_id, fork in enumerate(forks):
                scene = next(s for s in fork["scenarios"] if s["index"] == scene0["index"])
                mode = next(m for m in scene["modes"] if m["api"] == mode0["api"])
                local = []
                for pair in mode["pairs"]:
                    row = {"fork": fork_id, "replica": pair["replica"], "order": pair["order"],
                           "checksums_match": pair["checksumsMatch"]}
                    for side in ("baseline", "current"):
                        run = pair[side]
                        row[side] = {key: describe(run[key]) for key in RAW_SERIES}
                        row[side].update({key: run[key] for key in ("fixtureNs", "prepareNs", "releaseNs", "diagnostics")})
                    ratios = {}
                    for stat in ("median", "p95", "p99", "max"):
                        denom = row["current"]["apiNs"][stat]
                        ratios[stat] = row["baseline"]["apiNs"][stat] / denom if denom else None
                    denom = sum(pair["current"]["apiNs"])
                    ratios["total"] = sum(pair["baseline"]["apiNs"]) / denom if denom else None
                    # No speedup claim for an empty timer/control loop.
                    row["paired_old_over_new"] = None if mode["api"] == "no-call" else ratios
                    replicas.append(row)
                    local.append(row)
                per_fork.append({"fork": fork_id,
                    "baseline_median_ns": statistics.median(r["baseline"]["apiNs"]["median"] for r in local),
                    "current_median_ns": statistics.median(r["current"]["apiNs"]["median"] for r in local),
                    "paired_total_ratio": (statistics.median(r["paired_old_over_new"]["total"] for r in local
                                              if r["paired_old_over_new"]["total"] is not None)
                                           if mode["api"] != "no-call" and all(r["paired_old_over_new"]["total"] is not None for r in local) else None)})
            output.append({"index": scene0["index"], "name": scene0["name"], "api": mode0["api"],
                "groups": scene0["groups"], "bodies_per_group": scene0["bodiesPerGroup"], "replicas": replicas,
                "order_sensitivity": {order: (describe([r["paired_old_over_new"]["total"] for r in replicas
                    if r["order"] == order and r["paired_old_over_new"] and r["paired_old_over_new"]["total"] is not None])
                    if any(r["order"] == order and r["paired_old_over_new"] and r["paired_old_over_new"]["total"] is not None for r in replicas) else None)
                    for order in ("AB", "BA")},
                "forks": per_fork, "between_fork_spread": {
                    "baseline_median_ns": describe([r["baseline_median_ns"] for r in per_fork]),
                    "current_median_ns": describe([r["current_median_ns"] for r in per_fork]),
                    "paired_total_ratio": (describe([r["paired_total_ratio"] for r in per_fork])
                                           if all(r["paired_total_ratio"] is not None for r in per_fork) else None)}})
    return output


def aggregate_bridges(forks: list[dict]) -> list[dict]:
    output = []
    for fork_id, fork in enumerate(forks):
        for bridge in fork["bridgeDiagnostics"]:
            row = {"fork": fork_id, "index": bridge["index"], "api": bridge["api"]}
            for side in ("baseline", "current"):
                row[side] = {key: describe(bridge[side][key]) for key in ("bodyReadNs", "bodyPublicationNs")}
            output.append(row)
    return output


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag, default in (("forks", 4), ("repeats", 4), ("warmup", 2), ("warmup-ticks", 3000), ("ticks", 6000)):
        parser.add_argument("--" + flag, type=int, default=default)
    parser.add_argument("--scenarios", help="comma-separated scene indices 0..17 (default all)")
    parser.add_argument("--label")
    parser.add_argument("--output", help="new/empty output directory under local/")
    args = parser.parse_args(argv)
    if args.warmup < 0 or min(args.forks, args.repeats, args.warmup_ticks, args.ticks) < 1:
        parser.error("forks/repeats/ticks/warmup-ticks must be positive; warmup >= 0")
    if args.scenarios is not None:
        try:
            values = [int(part.strip()) for part in args.scenarios.split(",")]
        except ValueError:
            parser.error("scenarios must be comma-separated integers")
        if not values or len(set(values)) != len(values) or any(v not in range(18) for v in values):
            parser.error("scenarios must be distinct indices 0..17")
        args.scenarios = ",".join(map(str, sorted(values)))
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    _, settings = read_settings(repo)
    paths = {key: resolve_path(repo, settings.get(key)) for key in ("Game", "Jdk", "ZombieBuddy", "Viewpoint")}
    for key in ("Game", "Jdk", "ZombieBuddy"):
        if not paths[key] or not paths[key].exists():
            raise SystemExit(f"missing dependency {key}; check private local/settings.json")
    game, jdk, buddy, viewpoint = (paths[key] for key in ("Game", "Jdk", "ZombieBuddy", "Viewpoint"))
    javac = jdk / "bin/javac.exe"
    java = game / "jre64/bin/java.exe"
    if not java.is_file():
        java = jdk / "bin/java.exe"
    if not javac.is_file() or not java.is_file():
        raise SystemExit("Java/Javac executable missing; check local/settings.json")
    run_dir = (resolve_path(repo, args.output) if args.output else
               repo / "local/runs" / ("solver-bench-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")))
    if not run_dir.is_relative_to((repo / "local").resolve()):
        raise SystemExit("--output must stay under local/")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise SystemExit("--output must be new or empty (will not overwrite prior artifacts)")
    classes, tests, baseline_src, home = (run_dir / name for name in ("classes", "tests", "baseline-src", "home"))
    for path in (classes, tests, baseline_src, home):
        path.mkdir(parents=True, exist_ok=True)
    current_source = repo / "CorpseProxyLab/source/cvpworld/TowingSolver.java"
    baseline_source = repo / "tests/fixtures/solver_baseline/TowingSolver.java"
    text = baseline_source.read_text(encoding="utf-8-sig")
    for old, new in (("public final class TowingSolver {", f"public final class {BASELINE_CLASS} {{"),
                     ('@LuaClass(name="CVPSolverNative")', f'@LuaClass(name="{BASELINE_LUA_CLASS}")')):
        if text.count(old) != 1:
            raise SystemExit("unexpected frozen baseline marker")
        text = text.replace(old, new)
    generated = baseline_src / f"{BASELINE_CLASS}.java"
    generated.write_text(text, encoding="utf-8")
    cp = classpath(game, buddy, viewpoint, [])
    sources = sorted(str(p) for p in (repo / "CorpseProxyLab/source").rglob("*.java"))
    run_step([str(javac), "-encoding", "UTF-8", "-cp", cp, "-d", str(classes), *sources],
             repo, run_dir / "compile-current.log", "compile current")
    run_step([str(javac), "-encoding", "UTF-8", "-cp", f"{classes};{cp}", "-d", str(classes), str(generated)],
             repo, run_dir / "compile-baseline.log", "compile baseline")
    run_step([str(javac), "-encoding", "UTF-8", "-cp", f"{classes};{cp}", "-d", str(tests),
              str(repo / "tests/BenchmarkTowingSolver.java")], repo, run_dir / "compile-harness.log", "compile harness")
    versions = {}
    for name, executable in (("java", java), ("javac", javac)):
        run_step([str(executable), "-version"], repo, run_dir / f"{name}-version.log", f"{name} version")
        # Version output only, excluding the private command header.
        versions[name] = (run_dir / f"{name}-version.log").read_text(encoding="utf-8", errors="replace").split("\n\n", 1)[1].splitlines()[0]
    forks = []
    for fork_id in range(args.forks):
        raw_path = run_dir / f"fork-{fork_id:02d}.json"
        command = [str(java), "--enable-native-access=ALL-UNNAMED", "-Xms256m", "-Xmx1024m",
                   f"-Duser.home={home}", f"-Dcvp.game={game}", "-cp", f"{tests};{classes};{cp}",
                   "cvpworld.BenchmarkTowingSolver", "--warmup", str(args.warmup),
                   "--warmup-ticks", str(args.warmup_ticks), "--ticks", str(args.ticks),
                   "--repeats", str(args.repeats), "--order-offset", str(fork_id % 2), "--json", str(raw_path)]
        if args.scenarios:
            command += ["--scenarios", args.scenarios]
        print(f"[solver_bench] JVM fork {fork_id + 1}/{args.forks}", flush=True)
        # A checksum failure exits nonzero but still leaves the raw report for diagnosis.
        run_step(command, repo, run_dir / f"fork-{fork_id:02d}.log", f"benchmark fork {fork_id}")
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        validate_fork(data)
        forks.append(data)
    reproducible = checksums_reproducible(forks)
    passed = all(validate_fork(f) for f in forks) and reproducible
    summaries = aggregate(forks)
    report = {"schema": SCHEMA, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "label": args.label,
        "result": "pass" if passed else "fail", "checksums_reproducible_across_replicas": reproducible,
        "settings": "local/settings.json (private paths omitted)",
        "parameters": {key: getattr(args, key) for key in ("forks", "repeats", "warmup", "warmup_ticks", "ticks", "scenarios")},
        "versions": {**versions, "git": git_head(repo)},
        "environment": {key: forks[0][key] for key in ("os", "arch", "availableProcessors", "javaVersion")},
        "jvm_options": ["--enable-native-access=ALL-UNNAMED", "-Xms256m", "-Xmx1024m"],
        "sha256": {"current_source": sha256_file(current_source), "baseline_source": sha256_file(baseline_source),
                   "compiled_classes": sha256_tree(classes),
                   "lua_shared_tree": sha256_tree(repo / "CorpseProxyLab/42/media/lua/shared"),
                   "harness": sha256_file(repo / "tests/BenchmarkTowingSolver.java"),
                   "runner": sha256_file(Path(__file__)),
                   "shipped_jar_context_only": sha256_file(repo / "CorpseProxyLab/42/media/java/CorpseProxyWorld.jar"),
                   "current_source_utf8_lf": canonical_sha256(current_source),
                   "baseline_source_utf8_lf": canonical_sha256(baseline_source),
                   "harness_utf8_lf": canonical_sha256(repo / "tests/BenchmarkTowingSolver.java"),
                   "game_jar": sha256_file(game / "projectzomboid.jar"),
                   "zombiebuddy": sha256_file(buddy), "viewpoint": sha256_file(viewpoint) if viewpoint else None},
        "raw_forks": [f"fork-{i:02d}.json" for i in range(args.forks)],
        "method": {"independent_unit": "fresh JVM fork; within-fork pairs are correlated",
            "order": "AB/BA alternates by pair and fork; A=frozen baseline B=current",
            "quantiles": "nearest-rank; median is arithmetic middle for even n",
            "ratio": "paired old/new; >1 means current faster; no ratio for idle control",
            "order_sensitivity": "descriptive AB vs BA pair ratios; pairs within a fork are correlated",
            "timer_control": "scene 17 retains empty call-loop timer ns; compare magnitude, never subtract or call it solver cost",
            "diagnostics": "existing published outputs read outside API timing; checksumNs includes these diagnostic reads",
            "timed_region": forks[0]["timingContract"],
            "limits": ["synthetic Kahlua/world fixtures, not actual game frame/FPS",
                       "warmup configured, not proof of JIT steady state; inspect longer runs",
                       "checksum walks excluded but influence cache/GC between ticks",
                       "4x32 are four independent valid 32-body groups, not a 128-body solver group",
                       "bridge costs are separate static-fixture diagnostics, not additive API decomposition; counters disabled",
                       "group timings sum calls within one synthetic tick; no scheduling/Lua bridge overhead",
                       "checksums compare old/new within each API, not stale persistent history against solve"]},
        "bridge_method": forks[0]["bridgeContract"], "bridge_diagnostics": aggregate_bridges(forks),
        "summaries": summaries}
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    with (run_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scene", "api", "fork", "replica", "order", "side", "median_ns", "p95_ns", "p99_ns", "max_ns", "paired_total_ratio", "checksums_match"])
        for scene in summaries:
            for pair in scene["replicas"]:
                for side in ("baseline", "current"):
                    stats = pair[side]["apiNs"]
                    writer.writerow([scene["name"], scene["api"], pair["fork"], pair["replica"], pair["order"], side,
                        *[stats[k] for k in ("median", "p95", "p99", "max")],
                        pair["paired_old_over_new"]["total"] if pair["paired_old_over_new"] else "", pair["checksums_match"]])
    for scene in summaries:
        spread = scene["between_fork_spread"]
        ratio = spread["paired_total_ratio"]
        print(f"[solver_bench] {scene['name']} {scene['api']} old/new paired ratio median="
              f"{ratio['median'] if ratio else 'n/a (no-call)'} checksums=match")
    print(f"[solver_bench] {'PASS' if passed else 'FAIL'}; report: {run_dir.relative_to(repo).as_posix()}/report.json")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
