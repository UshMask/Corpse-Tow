# Corpse Tow — changelog

English player-facing release history. Entries below retain their original publication order. Release archives in `releases/` are historical evidence and are not rewritten.

## Corpse Tow 0.8.1 — prepared, not published

- Added Spanish translations for Spain, Mexico and Chile, including menu text and world settings.
- Fixed percent formatting in the Spanish carcass-wear description.
- Clarified context actions for untying a body, detaching a vehicle or horse, and removing rope or chain. Added short hints for attachment methods and display settings.

## Corpse Tow 0.8.0 — published 9 Nov 2026

User-reported manual MP acceptance on 9 Nov 2026. Detailed historical checks below apply to their respective development batches; no new full automated suite was run for publication.

Simulation and rendering changes:
- Shared SP/MP simulation clock and snapshot playback; isolate recovery corrections from physical velocity and resistance.
- Align each displayed train with its vehicle using bounded render-only translation in stock rendering and Viewpoint.
- Separate motion and force messages from full recovery snapshots. Apply fresh owner-specific force in newtons and fade expired feedback. Wire protocol 13 requires updating both server and clients; save schemas are unchanged.
- Production compilation and Lua syntax checks only for this batch; no tests or benchmarks were run.

- Reworked multiplayer vehicle trajectories and body playback; preserve recovery history when bodies are temporarily unloaded and retry discovery on fresh snapshots.
- Vehicle resistance now comes from the authoritative solver reaction; geometric mass-based prediction is disabled. Bodies, obstacles and detach limits remain server-controlled; update both server and clients.
- Corrected SP resistance sampling against physics movement time and improved dense-group spreading without aligning bodies to the vehicle axis.
- Fixed attachment selection and stale object references; simplified menu traversal and durable equipment handling. Server requests queue during saves, retaining cancellation and recovery checks.
- Reduced repeated endpoint reads and idle work. No specific FPS gain is claimed.

- Avoid redundant environment invalidation when a towed body moves within its current cell in native isometric rendering. Retain the existing path for cell transitions, cached corpse rendering and active Viewpoint; physics and save data are unchanged.
- Enabled by default; opt out with `-Dcvp.dynamicCorpses=false`. User-verified on 29 Oct 2026 in SP with 32 attached bodies, including ropes, fog and Viewpoint switching. Local MP checks passed with two Viewpoint clients and four bodies, including movement, camera switching, loot preservation and original rope returns; WAN and long sessions remain untested.

## Corpse Tow 0.7.8 — published 28 Oct 2026

[Русский](docs/release-notes/0.7.8-ru.txt) · [English](docs/release-notes/0.7.8-en.txt).

- Save waits for attachment and material returns now span game ticks, with deferred SP/MP results and duplicate-request protection.
- Continue an eligible train from a free body's menu; choose and highlight a train when several are available. Improved rope and remaining-length messages.
- Share visible vehicle attachments; prepare the isometric shader and VBO once per rope and skip identical segment lighting updates, retaining native fog and Viewpoint.
- Reduce curve allocations, redundant point submission, pose reads, angle updates, network snapshot preparation and work for disabled features.
- Preserve existing movement rules, rope curve shape and original material ownership. No specific FPS gain is claimed.

Update and fully restart both server and clients; ZombieBuddy's Java agent is required on both.

## Corpse Tow 0.7.7

Published and verified by Workshop download on 27 October 2026; all 64 files match.
[Русский](docs/release-notes/0.7.7-ru.txt) · [English](docs/release-notes/0.7.7-en.txt).

- Ropes now have a calmer but visible texture without the previous high-contrast dark bands. Fixed texture coordinates in the standard camera while retaining Viewpoint support.
- Added small solid rounded knots at body and Horse attachments. Vehicles keep a compact loop; fixed the loop stretching into an arc near the bumper.
- Moved visual feet and neck attachment points closer to human bodies. The knot and rope share the same visual endpoint; physical coordinates and link length are unchanged.
- Fixed residual jitter in stationary ropes: a settled visual curve now sleeps. Relative endpoint movement or a length change wakes it again.
- Fixed unwanted shape changes when both endpoints move together, including braking and reversing. Obstacle checks and body physics remain active.
- Held ends visually follow the right hand. An available hand shows a rope or chain model; occupied hands and existing item model overrides are preserved.
- After the first confirmed attachment, the acting player sees a rope running to their hand until attachment is completed. Cancellation, errors and replacement actions remove the temporary rope and item model. This preparatory connection is visible only to the acting player.
- Hovering over an action for a specific link highlights its rope and endpoints. Highlighting clears when the menu closes or changes and accounts for local players.
- Hovering over a loose rope marks its actual pickup tile. Fixed a hint error in the game's Lua runtime; hidden tiles are not highlighted.
- Reduced overlapping labels. Added a brief successful-action marker and an “End in hand” notification; “Important only” suppresses success messages. Updated Russian and English text.
- Reduced redundant save writes and index rebuilding. Coordinate checkpoints no longer recreate working groups; equipment is still returned only after a successful write, with retry recovery preserved after failures.
- Multiplayer no longer performs a full object scan on every snapshot; periodic reconciliation remains. Unrelated objects no longer invalidate prepared link data; reduced repeated Horse and legacy-save checks.
- The body cache is bounded and uses weak references, and clears when the world changes or unloads. Object identity checks remain in place.
- The Java solver reuses angle calculations and body-path checking buffers. Obstacle geometry and towing rules are preserved; no specific FPS gain is claimed.

Update the server and all clients, then fully restart them: the Java component has changed. Viewpoint is optional; no separate adapter needs to be enabled.

## Corpse Tow 0.7.6

Published and verified by Workshop download on 27 October 2026. See
[release status](docs/RELEASE_STATUS.md) for checks and remaining coverage limits.

Expanded change notes; text-only Steam edit on 27 October 2026. [Русская версия](docs/release-notes/0.7.6-ru.txt).

- Fixed rope jitter at moving vehicle attachment points: attachment positions now match the vehicle rendering in the same frame. Removed premature waiting for render preparation.
- Fixed Viewpoint rope visibility outside the character's facing direction on explored, unobstructed ground. Obstacle visibility checks are retained.
- Fixed rope rendering order relative to fog in the stock isometric camera.
- Added animal carcass towing, including batch attachment. Resistance accounts for carcass weight; disabling player-corpse towing no longer blocks animals.
- Added optional carcass wear with adjustable intensity. At normal intensity, the first 100 m do not reduce the meat ratio; losses then increase in steps, up to 10%. Age, hides and inventory contents remain unchanged; human clothing wear and abrasion do not apply to carcasses.
- Bodies on separate vehicle tethers spread within dense groups while retaining their lateral order, without forming rows relative to the vehicle axis. Added an enable switch, width and intensity settings.
- Spreading only acts during actual pulling: slack ropes do not move bodies, and lateral correction preserves attachment distance without adding velocity. Body chains and Horse are excluded; this does not guarantee collision-free spacing.
- Removed repeated body sorting while the lateral order remains unchanged.
- Added client-side simplified rope rendering: fewer segments and visual calculation passes without changing towing physics.
- Added an Important only notification mode: hides completion messages while retaining errors and action progress.
- Removed repeated validation of unchanged towing-item data on reads. Validation before writing and protection against modified data are retained.
- Intermediate-joint placement now runs only for groups that actually contain those joints.
- Fixed the carcass-wear tooltip formatting error and added Russian and English labels for the new settings.

Update the server and all clients, then fully restart them to load the updated Java component. Viewpoint remains optional. The jitter fix concerns attachment rendering synchronization; it does not eliminate all movement jumps caused by network delays.

## Corpse Tow 0.7.5

- Reworked rope controls and context menus, with common actions easier to reach and clearer connection feedback.
- Fully detached ropes and chains become items on the ground that can be picked up and reused.
- Updated the towing simulation for connected groups of bodies.
- Reduced repeated work during towing and unnecessary multiplayer updates.
- Improved recovery from lost multiplayer commands and delayed body positions after detaching.
- Expanded in-game settings for towing, body and clothing wear, and visual effects.
- Added recovery for damaged old towing data. Invalid connections may be cleared; the original equipment data is backed up before a reset.
- Fixed rope visibility in isometric view.

**Updating**
Update the server and all clients together, then fully restart them. This release includes an updated Java component.

## Corpse Tow 0.7.4

- Worn-out clothing is removed from worn slots but remains in the corpse inventory. Bag contents and player corpses are protected.
- Added brief notifications when remains wear away.
- Connection menus explain unavailable actions and show required and available rope length.
- Loose ends can be reattached to bodies, using spare length from a shared rope.
- Fixed incorrect turning at negative angles, including multiplayer smoothing.

**Updating**
Update the server and all clients together, then fully restart them.

## Corpse Tow 0.7.3

- Built Project Viewpoint support into the main mod. The separate support entry is no longer needed; it remains as a placeholder for existing mod lists.
- Fixed automatic startup of the Viewpoint integration. Viewpoint remains optional, and normal isometric ropes remain available.
- Removed repeated engine debug messages caused by vehicle towing resistance.

**Updating**
Update the server and all clients together, then fully restart them. ZombieBuddy may ask you to approve the updated Java module.

## Corpse Tow 0.7.2

- Smoothed multiplayer movement when network updates arrive unevenly.
- Reduced unnecessary detachment during brief delays in vehicle updates, while retaining obstacle and distance checks.
- Added compatibility with Corpse Plow Attachment 0.3.2: attached bodies are skipped by Plow, and Tow waits until Plow finishes moving a body.
- Reduced repeated body sorting and vehicle attachment-point calculations.

**Updating**
Update the server and all clients together, then fully restart them.

## Corpse Tow 0.7.1

- Added front and rear vehicle attachment points; the selected point is saved with the connection.
- Removing a body from the middle of a chain keeps the remaining bodies connected and preserves rope length.
- Added optional body wear with three rates: dragged zombie bodies become skeletons and can eventually disappear. The tether stays connected.
- Body wear is disabled by default. When enabled, skeletonization destroys ALL clothing and inventory contents, including items inside bags. Player bodies and towing equipment are protected.
- Added Sparse, Normal and Dense blood trails, independently of clothing and body wear.
- Improved connection error messages, automatic reconnection and synchronization of body appearance.
- Reduced repeated processing of blood, dirt and wear effects.

**Updating**
Back up your world. Update the server and all clients together, then fully restart them. For this version, update the optional Viewpoint support mod together with the main mod.

## Corpse Tow 0.7.0

- Reduced repeated movement calculations, environment checks and multiplayer updates when towing large groups.
- Moved common actions directly into the context menu and grouped advanced options under Other actions. Added group highlighting and clearer RU/EN labels and tooltips.
- Moved preferred material and attachment point to client settings. Added in-game gameplay settings for single-player; multiplayer uses server settings.
- Added blood trails, gradual blood and dirt buildup, and clothing wear with three rates. Clothing wear preserves items and bag contents and excludes player corpses.
- Added separate settings for visual effects, clothing wear and horse towing. The body limit can be disabled.
- Added basic Horse support through the same attachment menus, without changing horse speed or stamina.
- Improved resistance transfer through bodies in contact; detached or slack groups no longer add unnecessary vehicle drag.
- Improved rope rendering in isometric view and Project Viewpoint, action cancellation and multiplayer reconnection.

**Updating**
Back up your world. Update the server and all clients together, then fully restart them.

## Corpse Tow 0.6.4

- Empty tethers are no longer offered as body chains when reconnecting to a vehicle.
- Selecting a loose end highlights its connected bodies; empty tethers are labelled separately.
- Fixed a multiplayer case where an available vehicle was reported as unavailable.

## Corpse Tow 0.6.3

- Several bodies can share one rope within its available length. Sequential batch tying continues with the next rope when needed.
- Added batch options for separate attachments or independent body chains, with highlighting of the selected group.
- Loose ends can be selected on the ground, and detached body chains can be reconnected from the vehicle menu.
- Added extension of individual rope links with a second rope.
- Blocked body chains stop and resume when the path clears. Ropes do not wrap around corners.
- Reduced repeated work with large chains and fixed resistance transfer through bodies in contact.
- Fixed rope positions and depth in isometric view and Project Viewpoint, missing menus, detach errors and recovery from rendering errors.

**Updating**
Back up your complete world. Update the server and all clients together, then fully restart them. Downgrading a world with shared ropes to 0.4.1 is unsupported.

## Corpse Tow 0.4.1

- Fixed repeated errors when loading worlds with existing attachments.
- Fixed an error when creating new rope or chain links.

**Updating**
Update the server and all clients together, then fully restart them.

## Corpse Tow 0.4.0

- Pick up, carry, drop and reattach loose rope and chain ends.
- Connect bodies before attaching a vehicle, then disconnect the vehicle without breaking the body chain.
- Release either end independently, or remove the whole link to recover the original item.
- Carry loose ends up to 12 m; attaching fixes the link length. Entering a vehicle, dying, leaving or exceeding the length releases a held end.
- Added migration of older attachments and updated multiplayer handling.

**Updating**
Back up your world. Update the server and all clients together, then fully restart them.

## Corpse Tow 0.3.1

- Tethered skeletons no longer disappear from age-based cleanup, including in body chains.
- Detaching resumes the remaining cleanup timer; the pause is saved with the world.
- Normal decomposition is unchanged. This does not protect bodies from fire or manual removal.

**Updating**
Update the server and all clients together, then fully restart them.

## Corpse Tow 0.3.0

- Ropes and chains retain their original properties when attached, detached, or moved to another attachment.
- Detaching returns the tether item to your inventory or the ground.
- Existing 0.2 attachments are preserved when loading a save.
- Attachments can still be removed when towing is disabled.
- Improved multiplayer smoothing and body-chain movement.

## Corpse Tow 0.2.0

- Marked completion of the batch attachment, cancellation and reattachment milestone.
- The default body limit is 32; it is controlled through world or server settings.
- Gameplay behavior remains based on 0.1.7.

**Updating**
Update the server and all clients together, then fully restart them.

## Corpse Tow 0.1.7

- Prevented the same corpse from being attached by both Corpse Tow and Corpse Towing.
- Fixed corpse selection at different zoom levels and approaching bodies in multiplayer.
- Fixed leftover links after detaching bodies.
- Improved synchronization after reconnecting and with large numbers of attached bodies.
- Preserved body chains and tether items while their vehicle is outside the loaded area.

## Corpse Tow 0.1.6

- Added body-to-body chains, sequential attachment and tether lengths fitted to the attachment distance.
- Added context-sensitive menus, material selection and target highlighting.
- Fixed vehicle resistance in single-player and smoothed body-chain movement.
- Improved release of obstructed tails and transfer of tether items.

**Updating**
Existing attachments reset with this update; bodies, loot and tether items are preserved. Update the server and all clients together, then fully restart them.

## Corpse Tow 0.1.5

- Fixed stale attachment markers in multiplayer.
- Towing weight now updates when corpse loot changes.
- Vehicle resistance increases gradually as tethers tighten.
- Reduced corpse movement lag behind the vehicle in multiplayer.

## Corpse Tow 0.1.4

- Improved slack rope and chain movement when reversing toward bodies.
- Smoothed rope visuals.
- Removed towing and tying sounds.

## Corpse Tow 0.1.3 — Name and cover

- Renamed the mod to Corpse Tow [B42] and updated its cover.
- Technical mod IDs remain unchanged.

## Corpse Tow 0.1.3 — Player corpses and server settings

- Added support for player corpses.
- Added configurable multiplayer towing limits.

## Corpse Tow 0.1.3

- Improved rope tension, chain stability, and multiplayer movement.
- Added automatic leg or neck attachment and two-step tying.
- Added batch attachment and detachment.
- Vehicle resistance now depends on load and terrain.
- Updated visuals, animations, and sounds.
- Added Russian and English interface text and optional Project Viewpoint support.

## Corpse Tow 0.1.2

- Added leg and neck attachment options.
- Clarified how close you need to be on foot to attach a body.

## Corpse Tow Maintenance update

- No change details were recorded for this upload. Its contents could not be reliably reconstructed from the available release records.

## Corpse Tow 0.1.1

- Fixed the multiplayer attachment menu on Build 42.
- Smoothed corpse movement in multiplayer.

## Corpse Tow 0.1.0

- Initial public release of vehicle corpse towing with ropes and chains.
- Requires ZombieBuddy with its Java agent.

## Local milestones not published separately

These changes reached Steam as part of 0.6.3.

### 0.6.1

- Fixed an unavailable Lua function that prevented creating links and migrating old attachments.

### 0.6.0

- Added straight-line obstacle checks: blocked groups stop and resume when the path clears.
- Unloaded paths wait for the area to load; ropes do not wrap around corners.
- Failed reattachment preserves the previous links and equipment.

### 0.5.0

- Added extension of an individual rope link with a second rope, from 12 to 24 m.
- Both original ropes retain their properties and are returned when the link is removed.
- Chains cannot be extended.
