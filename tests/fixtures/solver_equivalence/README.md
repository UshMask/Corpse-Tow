# Three-way solver equivalence oracle

Verification-only artifacts. Production code is never edited from here.

## Frozen baseline (task base a892 local HEAD source)

Extracted by the Lead into `tests/fixtures/solver_baseline/` and treated as immutable:

| file | SHA-256 |
| --- | --- |
| `tests/fixtures/solver_baseline/TowingSolver.java` | `DC04B22E89B820BB18CBE0C261FF21CA4EEC1BA7E7A317616B7FB63F0D24EA87` |
| `tests/fixtures/solver_baseline/CVP_GroupConstraints.lua` | `7E3E20D9686912C4D5AF5781F3C31B7313FC60D17196DA4F51D1929BF68E571F` |

These hashes are asserted by `tests/ValidateSolverEquivalence.java` and
`tests/test_solver_equivalence.py`; a change in either frozen file fails the oracle.

## `TowingSolverBaseline.java`

Generated test-only copy of the frozen Java source. Only two edits are applied so it
compiles and runs beside the live `cvpworld.TowingSolver`:

1. `public final class TowingSolver` → `public final class TowingSolverBaseline`
2. `@LuaClass(name="CVPSolverNative")` → `@LuaClass(name="CVPSolverNativeBaseline")`

`tests/test_solver_equivalence.py` regenerates that transform in memory and asserts
the committed fixture matches, so a stale copy cannot pass silently. The fixture is
compiled into a private validator directory (never into `CorpseProxyWorld.jar`).

## Three oracles

1. **old Java vs new Java** — frozen `TowingSolverBaseline` and live `TowingSolver`
   run on identical Kahlua record fixtures: persistent state, release/prepare
   round-trips, backend switches and failure rollback.
2. **old Lua vs new Lua** — frozen `CVP_GroupConstraints.lua` is loaded as module
   `CVP_GroupConstraintsBaseline` in the same Kahlua VM as the live module; both
   receive identical record fixtures and their full record/group outputs are compared.
3. **new Java vs new Lua** — per-tick parity against the shipped Lua group solver, plus
   a persistent-history parity sequence with a Lua backend switch and rollback.

Numeric comparisons use the existing strict `1e-13` absolute tolerance; booleans,
strings and nil/false are compared exactly.

## Scenario matrix (28 names)

rest/straight/turn/brake/reverse/slack↔taut, mass changes, 1/4/32 bodies,
identical 1/2/4 × 32-body chains, wall/unloaded/solid/tree obstruction,
unload/replacement, topology split/rejoin, backend switches (persistent release +
legacy call, and a one-tick Lua backend switch), reset-history, injected-exception
rollback. Each tick compares every published record field plus group outputs
(`nativeGap`, obstruction, fallback/recovery flags, residual, iterations, accumulated
load), and `release()` exposes the persistent history for comparison too.

## Controlled-scaling evidence

The oracle also times the live native backend for 1, 2 and 4 identical 32-body chains
under the same input (60 ticks, 2 substeps per tick) and proves every chain stays
bit-identical on translation-invariant state. Emitted as `SCALING ...` lines and
captured in `report.json` under `scaling`.

## Negative controls (how the oracle was validated)

The harness was proven to fail, not just to pass:

* a deliberately mutated frozen Java baseline was detected by oracle 1
  (`x` mismatch 5.3e-4 on `straight-1` tick 4);
* a deliberately mutated live Lua module (only reachable through the topology-change
  scenario) was detected by oracle 2;
* a genuinely older shipped JAR was rejected (`jarClassMatchesCompiled=false`,
  "stale shipped JAR"), and the Python runner asserts the enforced JAR class check;
* a Java compile failure makes the Python test fail with the `javac` log — it can
  never be skipped or reported as a Lua-only success.

## Run

```powershell
pwsh tools/Project.ps1 -Action build      # refresh CorpseProxyWorld.jar first
.venv\Scripts\python.exe tests\test_solver_equivalence.py
```

The Python runner discovers the JDK/game/ZombieBuddy from `local/settings.json`,
compiles the solver sources with the same `javac -encoding UTF-8` invocation the
native validator uses, runs `cvpworld.ValidateSolverEquivalence` in the game JVM,
and fails if Java did not compile/load. It also verifies the shipped JAR SHA-256 and
that the JAR's `cvpworld/TowingSolver.class` bytes match the freshly compiled class,
so a stale JAR cannot be reported as a pass. Per-run logs and `report.json` are
written under `local/runs/solver-equivalence-<timestamp>/`. A missing game/JDK/
ZombieBuddy raises a visible `unittest.SkipTest` unless `CVP_REQUIRE_NATIVE=1` is set,
which turns that environment problem into a failure.

## Final verification (2026-11-12 00:20, Stage 2 final tree)

| item | value |
| --- | --- |
| live `TowingSolver.java` | `814E08438E71DE4760CD1B95E7F5BD277F63D070F4D44F2E6BAAE9B28660A0D3` |
| live `CVP_GroupConstraints.lua` | `1B2BE7BE9FB6565BF65905298C6D7EDFEAC2C3D7CC26363D646B890E4EA1FF11` |
| `CorpseProxyWorld.jar` | `7497574794DF89E22843AAA3E05423AC0D11144D076813984E1F1E3125A24768` |
| `cvpworld/TowingSolver.class` in JAR | `4F68F1C7F54F0CF9D61835E49792DB70E31AA0F810E3B0680FB0B4EC8C4958E8` (equals freshly compiled class; strict check enforced) |

`Project.ps1 -Action build`: PASS, all native validators including `ValidateTowingSolver`.
`tests/test_solver_equivalence.py`: PASS — 1,551,505 compared values, max absolute
error `0.0`, 28/28 scenarios, no mismatches; logs under
`local/runs/solver-equivalence-20261112-002054/`.

Controlled scaling of the live native backend (60 ticks, 2 substeps/tick):

| chains | bodies | solve time | per body per tick | max cross-chain error |
| --- | --- | --- | --- | --- |
| 1 × 32 | 32 | 1.448 ms | 0.754 µs | 0.0 |
| 2 × 32 | 64 | 3.514 ms | 0.915 µs | 0.0 |
| 4 × 32 | 128 | 7.956 ms | 1.036 µs | 0.0 |

Obstruction/unload scenarios assert that the obstacle or unloaded gap was actually
triggered, so an all-clear comparison cannot masquerade as coverage.


