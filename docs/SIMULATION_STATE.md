# Simulation state ownership

## Multiplayer responsibilities

The server owns attachment identity, permissions, equipment transfers, the link
graph, saved lengths, corpse simulation/collisions, wear, authoritative loads,
durable writes and recovery. Clients request actions, never authoritative poses
or inventory outcomes. Preliminary client checks improve feedback but do not
replace server validation.

Clients own menus, approach paths and animations, interpolation of received
corpse poses, cosmetic rope shape, visual attachments, camera transforms and
rendering. Cosmetic rope geometry is neither simulated on the dedicated server
nor sent through the protocol.

Vehicle resistance is the deliberate exception to a simple server/client split:
the server computes the authoritative towing load; the engine's current vehicle
physics owner applies it. Geometric client prediction is currently disabled:
legacy aggregate estimates do not create a force when server load is zero.
Other clients do not apply the force. Moving that integration unconditionally
to the server would fight the game's vehicle ownership model.

SP uses the same authority and snapshot playback with zero presentation delay,
without transport or client-side writes to authoritative body positions. These responsibilities do not imply equal SP/MP performance.

## Multiplayer snapshot preparation

The original snapshot preparation optimization kept the wire format intact.
The later unification below uses protocol 13; page limits, interest radius,
heartbeat and recovery lifetimes remain unchanged.

- The body-to-simulation-record lookup is rebuilt when the published records
  table changes, including partial rebuilds after missing bodies.
- Sorted link/body keys are shared across recipients and reused until membership
  changes. The cache stores only keys, not poses or visibility. Every recipient
  still gets current proximity filtering and complete connected trains.
- Each snapshot retains its own page order and lazily prepared body rows with
  appearance omitted. Those rows are shared only by recipients that acknowledged
  that appearance revision; full rows remain available for recovery.
- Snapshot values are read-only after capture. Transport metadata belongs to a
  new per-recipient page envelope. Vehicle samples can be shared within a snapshot;
  live simulation or graph scratch tables must not be repurposed as packet buffers.

## Authority tick

The authority keeps the following order:

1. Retry pending recovery, including before disabled/zero-time returns.
2. Rebuild topology if necessary; publish its cache key only after success.
3. Prepare BodySpread from the published groups.
4. Validate each group and read its live poses immediately before calculation.
5. Calculate candidates without moving engine bodies.
6. Apply candidates through WorldBridge, journaling each body before mutation.
7. Record committed sources, finish calculation, then apply effects and loads.

| State | Owner and lifetime |
| --- | --- |
| Actual pose and square membership | Original engine body; Java performs movement |
| Groups and record identity | Lua; rebuilt on topology/discovery changes |
| Spread fleet layout | Lua; tied to the published groups object |
| Velocity, angular velocity, takeup, constraint readiness | Java in persistent mode; released to Lua on rebuild or Lua-mode entry |
| Candidate pose and load outputs | Solver publishes to Lua for commit and consumers |
| Before poses and pending group journal | Lua until commit or successful recovery |
| Expected pose after a failed write | Lua; prevents overwriting unrelated movement on a later retry |
| Trajectory recovery | Lua; not part of numeric solver history |

A rebuild invalidates its cache key before releasing history. Missing bodies leave
the key invalid even when a partial group layout has been published. Exceptions
must force a new build; this is not a claim that reused records are transactional.

The solver choice is shared by spread preparation and obstacle-cache creation for
one active tick. Lua-mode entry publishes native history before clearing reset
commands. Resetting motion and resetting a rope constraint remain distinct.
The production native path requires solvePersistent/release; solve remains a
nonpersistent entry point for reference validation.

Recovery has three separate scopes: numeric history inside TowingSolver, one-body
square transition inside WorldBridge, and the group journal inside Lua. A failure
in one scope must not silently discard another scope's pending work. Failed group
rollback stays pending, blocks simulation, and prevents Runtime.save from flushing.

No physics constants, save schemas, or trajectory recovery thresholds are changed
by this ownership refactor. Lua engine models exercise orchestration; they do not
replace native validation. New regression scenarios have not yet been run.


The authority uses the bounded 10 ms accumulator described in package B below.
Load integration consumes the calculated interval once, rather than replaying the
last force on skipped authority ticks.
Ordinary service advancement follows solves; commands and deletion checks remain
immediate. Rope shape updates are capped separately, not native render callbacks.
Effects due in one group are passed to each consumer as a batch at the existing
staggered half-second cadence. The directed-chain experiments were rejected by
stationary dense-chain tests; the coupled solver remains in use.


## Shared result contract, frame schema 1 / wire protocol 13

`CVP_SimulationFrame.capture` freezes the accepted result after simulation and
world pose application. Both SP and server runtime publish it as `simulationFrame`.
It contains a local simulation sequence, graph revision, `sampledAt` in milliseconds,
`intervalSeconds`, copied body poses and source samples, and vehicle loads in newtons. Body rows also identify correction-only results.
`sourceSampledAt` records the actual committed source time; recovery can leave an
older committed source. This package does not change interpolation or recovery timing.
The transport sequence remains distinct from the local simulation sequence.

The existing Java solver return and internal `loadMass` records retain their legacy
scale; `CVP_LinkSimulation` converts once by `9.81 * 0.65` at the boundary.
Every runtime load after that boundary is a resistance force in newtons.
`Load.impulse` integrates `forceN * dt` (newton-seconds), with the existing momentum
cap. There is no additional friction coefficient in the application layer.

MP sends `resistanceForceN`, `intervalSeconds` for the averaging window, vehicle ID
and owner. The force is averaged over that window, not an impulse to replay.
Frame schema/time/interval must agree across all pages before assembly. Protocol
13 deliberately rejects older peers rather than interpreting a mass as a force.
Save schemas, equipment ownership and rollback are unchanged. Reconnect still
uses the complete snapshot mechanism. Playback changes are described below.


## Authority clock and correction-only motion (package B)

SP and MP authority use the same 10 ms accumulator and at most 50 substeps per
update. SP supplies engine physics time; MP supplies elapsed server time. The
fractional remainder is retained and subtracted from trajectory playback time.
Each solved load interval is applied/integrated once, including server load windows.

Trajectory recovery, capped catch-up, clock discontinuities, take-up shortening and
the numerical fallback do not turn positional correction into kinetic velocity.
Candidate positions still pass normal gap, swept obstacle and group
application/rollback checks; after acceptance velocities retain only the free
predictor. Normal converged constraint motion updates velocity and reaction.
Spacing applies only while that substep's tether is taut; an unattached or slack
body already coasting does not gain sideways motion from the spacing solver.

When a coupled solve cannot converge, its constraint impulse is unreliable. During
ordinary towing only, the fallback estimates ground-friction resistance from each
connected body's displacement along the moving anchor, capped at that body's
nominal friction. Slack/disconnected or stationary bodies contribute nothing; no
acceleration force is inferred. This estimate is not the converged solver reaction.
Trajectory corrections and take-up shortening still publish zero load. Bodies
stopped by ground friction also stay at rest under a sub-threshold spring pull,
but resume moving once the pull exceeds that threshold.

The free predictor reuses numeric fields in the existing body pass; no second
physical solve or per-body allocation is added. Java history checkpoint and Lua
world-pose rollback remain the owners of error recovery. Runtime performance and
visual behavior require separate in-game confirmation; compilation is not evidence
of absence of regressions.


## Shared playback and network separation (packages C and D)

The implementation path is complete; live acceptance is still outstanding.

- `CVP_Motion` owns the same bounded pose/source buffer, clock mapping, parent
  order and train alignment in SP and MP. SP consumes the latest committed
  snapshot with zero delay; MP keeps its 250 ms interpolation delay. Targets are
  compact reusable records; appearance payloads are not copied into playback.
  The eight numeric sample slots are recycled after warm-up, and all body draw
  offsets are submitted to Java in one batch per tick. Vehicle attachment reads
  are shared by roots using the same attachment during that presentation update.
- Each root compares the interpolated solver source with the current displayed
  vehicle's world attachment. Its entire train receives one translation; child
  bodies never independently chase the car. Intermediate joints share it, with
  bindings rebuilt only when topology or playback record identity changes.
- `BodyPresentation` applies this translation to stock draw/picker arguments,
  shadows, mouse hit coordinates and Viewpoint model matrices/bounds. It does not change body positions,
  squares, angles, collision data or save records. MP still places confirmed
  interpolated replicas as before; the extra correction remains render-only.
  The optional cached-corpse chunk-texture mode keeps native positions instead
  of introducing per-frame chunk invalidations; standard dynamic stock rendering
  and Viewpoint use the bounded correction.
- Correction is bounded to 8 world cells, never extrapolated across floors. An
  older committed source (>500 ms) or excessive divergence marks visual recovery:
  remove the correction and suppress affected rope segments instead of drawing
  an indefinitely stretched rope. MP requests the existing full sync, throttled
  to its normal recovery cadence. Detachment, failed placement, missing bodies,
  epoch changes and presentation errors clear draw offsets.
- `CVP_SimulationClock` is shared by authority advancement and MP owner-side load
  integration. It retains fractional 10 ms time, bounds catch-up at 500 ms and
  marks clock resets/long gaps. Server input is no longer pre-clipped, so recovery
  detection sees the real gap. MP discards stale load catch-up on discontinuity.
- A load carries owner ID, observed owner generation, transport sequence, sample
  time and interval. The current physical owner alone integrates force in newtons.
  Out-of-order packets/generations are rejected. Losing local ownership blocks the
  cached load until fresh feedback; epochs clear all ownership history. Force is
  unchanged for 250 ms, then fades linearly to zero by 1000 ms without feedback.
- Protocol 13 has `state` (complete graph/appearance/recovery), `motion` (poses,
  dynamic endpoint coordinates/lengths and obstacles for a confirmed revision)
  and independently assembled `loads`. Appearance acknowledgements retain their
  existing contract: first appearance or a changed revision uses a full snapshot;
  ordinary motion omits acknowledged cosmetic/clothing payloads.
- Motion is validated and assembled atomically against its confirmed topology.
  Newer sequences supersede incomplete older movement; unknown revisions,
  membership changes and invalid baselines request full sync. Commands, result
  barriers, body transfers, durable writes and rollback keep their existing paths.

Both server and all clients require protocol 13 and the rebuilt JAR. No save
migration is needed. `CVP_LoadPrediction` is retained solely as a historical
harness adapter; production has no load predictor or prediction-state allocation.

Limits: render correction follows the engine-exposed vehicle attachment; subframe
vehicle projection remains the native rope renderer's responsibility. It cannot
remove all network latency or make SP and MP cost identical. Stock FBO/camera
paths, Viewpoint, owner handoff, packet loss, save/load and long chains still need
in-game acceptance. Lua syntax parsing and production Java compilation were the
only executable checks; no tests, benchmarks, game launch or installation occurred.


## Follow-up static review (2026-11-01)

Confirmed source-level contradictions corrected without running scenarios:

- Recovery preserves free-predictor velocity only when collision accepted it.
  A blocked single body keeps zero velocity/angular velocity in both Java and Lua.
- Snapshot time advances on disabled/zero-step/no-group returns after pending
  rollback has been restored. The committed-source time remains separate.
- Frame poses carry an internal original-body identity reference. SP checks it;
  server transport uses an old pose only when that same object is still resolved.
  The reference is not included in wire rows or save data.
- Playback resets history when parent or attachment identity changes. Source
  freshness also uses advancing presentation time, so losing snapshots cannot
  leave a frozen source apparently fresh while the car continues moving.
- Server load generations increase monotonically across vehicle-object replacement
  within an epoch. A replaced client replica blocks its cached load once and can
  resume on fresh feedback; it no longer extends that block indefinitely. Only
  vehicles in the currently confirmed graph can receive a load.
- One incomplete full baseline is retained against later packets of the same
  revision, avoiding starvation while appearance acknowledgements are pending.
  A different revision/epoch may replace it; ordinary motion still prefers the
  newest complete sequence. Old/retired packets do not trigger needless sync.

Production Java compilation and Lua 5.1 parsing are the validation boundary for
this review. No tests, benchmarks, game execution or installed-mod update.


## Completed-frame presentation (2026-11-02)

Authority publishes SimulationFrame after endpoint maintenance and wear recovery.
The frame includes owned endpoint values and body poses, including stationary
body-only links with no solver record. Unchanged zero-step ticks reuse the frame
unless held endpoints need updating. Transactional save ticks retain their existing
mutation restrictions. The wire format remains unchanged: graph endpoint coordinates
and body poses are encoded from the same completed frame where available.

MP endpoint histories use the same snapshot timestamps and 250 ms display delay as
body histories. Attachment identity/revision changes reset that section's history;
epoch/clock resets discard endpoint history. Body endpoints are transformed from
attachment-local coordinates by the selected body pose, so turning does not mix
live world poses with delayed knots. Failed/missing replicas suppress their ropes.

The previous entire-train translation toward a live vehicle is removed. The engine
still owns vehicle rendering and the native renderer aligns only the vehicle end
with its captured visual attachment (or the current physical attachment if capture
is absent). This is an explicit latency boundary, NOT a claim that the local MP
vehicle and delayed server bodies share a physical time. Held-hand decoration also
continues to attach to the displayed player's hand.

Cosmetic rope integration remains capped at 60 Hz. Between shape steps a native
endpoint update moves both ends together without integrating the cosmetic solver
or feeding display corrections into physics. Published arrays remain immutable for
queued frames; moving geometry needs a new array, unchanged geometry reuses it.

Validation: production JAR compilation and syntax-only parsing of 56 Lua modules.
No tests, benchmarks, game launches or live installation for this change. Previous
runtime test helpers may require contract updates; no suite pass is claimed.
# Checkpoint limitations (2026-11-02, updated 2026-11-09)

This is a development checkpoint, not a release acceptance. The 15 high-speed
body-spacing subcase errors in two test methods reported on 2026-11-02 were
classified on 2026-11-09 as a stale test model: the discrete test paired a
100 Hz-quantized anchor displacement with an unquantized display dt, the
constant-speed fixture overstretched one grasp before the first step, and 216 km/h
exceeded the vanilla 120 km/h maxSpeed cap. The fixture/driver were corrected, the
216 km/h input is kept as a safety-only stress test, and no production physics,
Lua, Java or JAR changed. `tests/test_body_spread.py` is 14 tests OK. Full evidence:
`local/runs/bodyspread-final-20261109/`. This does not claim spacing quality above
~40-45 m/s: the rigid wrap limit cycle there is a recorded, unfixed limitation.

Still open from the 02.11 checkpoint: in the live 32-body chain, 6 of 78 sampled
frames reported zero resistance with connected bodies; correction and slack phases
were not ruled out. The observed two-body slow-stop displacement also requires a
matched repeat. The isolated evidence and full logs are in
`local/runs/chain-spread-investigation-20261102/`; those local results are not part
of the Git commit. No test thresholds were relaxed.

