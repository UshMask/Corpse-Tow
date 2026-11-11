-- Opt-in, bounded, aggregated performance diagnostics for Corpse Tow.
--
-- Design rules
--  * Disabled by default and ZERO overhead when disabled: production modules never
--    call into this file. Disabled means the module is loaded but no wrapper is
--    installed, so the hot path is unchanged.
--  * enable() installs method wrappers for the phases/counters below; disable()
--    removes them. Wrappers are the only instrumentation, so tests that replace a
--    method themselves still see the original when diagnostics are off.
--  * Everything is bounded: fixed ring buffers per phase (default 256 samples),
--    fixed maps of phases/counters/gauges (defaults 32/96/32). Overflow increments
--    `diagnostics.overflow` instead of growing memory.
--  * No per-frame printing. report()/toJson()/snapshot() are explicit pulls; the
--    caller decides where the data goes. Never write to disk from Lua.
--
-- API
--    D.enabled() -> boolean
--    D.enable({ samples=256, maxPhases=32, maxCounters=96, maxGauges=32,
--               memory=true, memoryEveryTicks=120,
--               clock=function() return milliseconds end })
--    D.disable()
--    D.reset()                       -- clears aggregates, keeps enabled state
--    D.time(phase, fn, ...)          -- if enabled: sample elapsed ms for fn(...)
--    D.mark()                        -- returns start time or nil when disabled
--    D.timeTo(phase, mark)           -- record elapsed ms from mark
--    D.sample(phase, milliseconds)   -- record a pre-measured duration
--    D.latency(metric, milliseconds) -- same store, intended for action->confirm ms
--    D.count(metric, n, unit)        -- bounded counter (default n=1, unit='count')
--    D.bytes(scope, n)               -- convenience counter named network.bytes.estimate
--    D.gauge(name, value, unit)      -- last-value metric with min/max
--    D.bind(name, object)            -- explicit handle for adapters (MP server/client)
--    D.hookPhase(owner, key, name)   -- attach one custom phase; returns true/false
--    D.snapshot() -> table           -- aggregated report (documented format below)
--    D.report() -> string            -- deterministic text table for logs
--    D.toJson(snapshot?) -> string   -- bounded JSON serializer for local/runs files
--
-- Report format (snapshot; stable field names, suitable for local/runs JSON):
--    { schema='cvp-diagnostics', version=1, enabled=true,
--      elapsedMs=<number>,                 -- since enable() or reset()
--      phases={ { name=, unit='ms', count=, totalMs=, min=, median=, p95=, p99=,
--                 max=, mean=, samples=, dropped= }, ... },
--      counters={ { name=, unit=, count= }, ... },
--      gauges={ { name=, unit=, value=, min=, max=, samples= }, ... },
--      memory={ available=, unit='KB', start=, last=, min=, max=, samples= },
--      hooks={ installed=, unavailable={...} },
--      notes={ ... } }
--    Percentiles use the nearest-rank method on the bounded ring, include only the
--    samples still retained (dropped counts evicted ones), and are descriptive.
--    Counter units are part of the contract: 'ms' for sampled phases, 'bytes' only
--    for network.bytes.estimate, 'count' or an explicit unit otherwise.
--
-- Counters the multiplayer layer can feed without editing this file:
--    D.count('network.capture.frames'), D.count('network.capture.links', n),
--    D.count('network.publish.frames'), D.count('network.publish.pages', n),
--    D.count('network.publish.bodies', n), D.count('network.publish.links', n),
--    D.bytes('network.publish', byteEstimate), D.latency('network.ack.wait', ms).
--    All of these are all labelled estimates/observations, never measured wire size.
--
-- Hooks are best-effort: a missing module/native class is recorded in
-- hooks.unavailable instead of raising, so the same module works in SP, MP client,
-- dedicated server and the offline Lua test model.
local D = {version = 1, on = false, schema = 'cvp-diagnostics'}
local DEFAULT_SAMPLES = 256
local DEFAULT_MAX_PHASES = 32
local DEFAULT_MAX_COUNTERS = 96
local DEFAULT_MAX_GAUGES = 32

local function defaultClock()
    if getTimestampMs then return getTimestampMs() end
    if os and os.clock then return os.clock() * 1000 end
    return 0
end

local function newStore(limit)
    return {values = {}, size = limit, count = 0, nextIndex = 1, dropped = 0, sum = 0}
end

local function push(store, value)
    if type(value) ~= 'number' or value ~= value then return end
    local values = store.values
    if store.count < store.size then
        store.count = store.count + 1
    else
        store.dropped = store.dropped + 1
        store.sum = store.sum - (values[store.nextIndex] or 0)
    end
    values[store.nextIndex] = value
    store.nextIndex = store.nextIndex % store.size + 1
    store.sum = store.sum + value
end

-- Nearest-rank percentile over a sorted copy of the retained samples.
local function percentile(sorted, count, fraction)
    if count <= 0 then return nil end
    local index = math.floor((count - 1) * fraction + 0.5) + 1
    if index < 1 then index = 1 end
    if index > count then index = count end
    return sorted[index]
end

local function summarize(store, unit)
    local values = {}
    for i = 1, store.count do values[i] = store.values[i] end
    table.sort(values)
    local count = store.count
    if count == 0 then
        return {count = 0, samples = 0, dropped = store.dropped, unit = unit}
    end
    local total = 0
    for i = 1, count do total = total + values[i] end
    local mean = total / count
    local variance = 0
    for i = 1, count do variance = variance + (values[i] - mean) * (values[i] - mean) end
    return {
        count = count,
        samples = count,
        dropped = store.dropped,
        unit = unit,
        min = values[1],
        median = percentile(values, count, 0.50),
        p95 = percentile(values, count, 0.95),
        p99 = percentile(values, count, 0.99),
        max = values[count],
        mean = mean,
        stdDev = math.sqrt(variance / count),
        total = total,
    }
end

local function resetTable(t)
    for key in pairs(t) do t[key] = nil end
end

D.bound = {}
-- Installed wrappers are lifecycle state, not measurement state: reset() must
-- never forget them or disable() cannot restore the original methods.
D.installed = {}
D.unavailable = {}

function D.enabled() return D.on == true end

function D.reset()
    D.phases = {}
    D.phaseOrder = {}
    D.counters = {}
    D.counterOrder = {}
    D.gauges = {}
    D.gaugeOrder = {}
    D.phaseOverflow = 0
    D.counterOverflow = 0
    D.gaugeOverflow = 0
    D.memory = {available = false, start = nil, last = nil, min = nil, max = nil, samples = 0}
    D.startedAt = D.clock()
    D.tickCount = 0
end

local function configure(options)
    options = options or {}
    D.sampleLimit = math.max(16, math.min(4096, tonumber(options.samples) or DEFAULT_SAMPLES))
    D.maxPhases = math.max(4, math.min(128, tonumber(options.maxPhases) or DEFAULT_MAX_PHASES))
    D.maxCounters = math.max(8, math.min(512, tonumber(options.maxCounters) or DEFAULT_MAX_COUNTERS))
    D.maxGauges = math.max(4, math.min(128, tonumber(options.maxGauges) or DEFAULT_MAX_GAUGES))
    D.memoryEnabled = options.memory ~= false
    D.memoryEveryTicks = math.max(1, tonumber(options.memoryEveryTicks) or 120)
    D.clock = type(options.clock) == 'function' and options.clock or defaultClock
    D.notes = options.notes or {}
end
D.clock = defaultClock

local function phaseStore(name)
    local store = D.phases[name]
    if store then return store end
    if #D.phaseOrder >= D.maxPhases then
        D.phaseOverflow = D.phaseOverflow + 1
        return nil
    end
    store = newStore(D.sampleLimit)
    D.phases[name] = store
    D.phaseOrder[#D.phaseOrder + 1] = name
    return store
end
D._phaseStore = phaseStore

-- Record one duration sample in milliseconds.
function D.sample(name, milliseconds)
    if not D.on then return end
    local store = phaseStore(name)
    if store then push(store, milliseconds) end
end

function D.latency(name, milliseconds) return D.sample(name, milliseconds) end

function D.count(name, n, unit)
    if not D.on then return end
    local row = D.counters[name]
    if not row then
        if #D.counterOrder >= D.maxCounters then
            D.counterOverflow = D.counterOverflow + 1
            return
        end
        row = {name = name, count = 0, unit = unit or 'count'}
        D.counters[name] = row
        D.counterOrder[#D.counterOrder + 1] = name
    end
    if unit and row.unit == 'count' then row.unit = unit end
    row.count = row.count + (tonumber(n) or 1)
end

function D.bytes(scope, n)
    D.count('network.bytes.estimate' .. (scope and ('.' .. scope) or ''), n, 'bytes (estimate)')
end

function D.gauge(name, value, unit)
    if not D.on then return end
    if type(value) ~= 'number' or value ~= value then return end
    local row = D.gauges[name]
    if not row then
        if #D.gaugeOrder >= D.maxGauges then
            D.gaugeOverflow = D.gaugeOverflow + 1
            return
        end
        row = {name = name, unit = unit or 'count', samples = 0}
        D.gauges[name] = row
        D.gaugeOrder[#D.gaugeOrder + 1] = name
    end
    row.value = value
    row.samples = row.samples + 1
    if row.min == nil or value < row.min then row.min = value end
    if row.max == nil or value > row.max then row.max = value end
end

function D.mark()
    if not D.on then return nil end
    return D.clock()
end

function D.timeTo(name, mark)
    if not D.on or mark == nil then return end
    local elapsed = D.clock() - mark
    local store = phaseStore(name)
    if store then push(store, elapsed) end
end

function D.time(name, fn, ...)
    if not D.on then return fn(...) end
    local mark = D.clock()
    local a, b, c, d = fn(...)
    D.timeTo(name, mark)
    return a, b, c, d
end

function D.bind(name, object)
    D.bound[name] = object
    return object ~= nil
end

-- Estimate a captured simulation frame's wire cost. Clearly an estimate: the
-- model counts payload fields at 4 bytes per number + 1 byte kind/point + key
-- length; the real serializer may differ. Used only when diagnostics are enabled.
function D.estimateFrameBytes(frame)
    if type(frame) ~= 'table' then return 0 end
    local bytes = 16
    local endpoints = 0
    for _, ends in pairs(frame.endpoints or {}) do
        for _, side in ipairs({'a', 'b'}) do
            local e = ends[side]
            if e then endpoints = endpoints + 1; bytes = bytes + 18 + #tostring(e.key or '') end
        end
    end
    for _ in pairs(frame.bodies or {}) do bytes = bytes + 40 end
    for _ in pairs(frame.loads or {}) do bytes = bytes + 12 end
    for _ in pairs(frame.obstacles or {}) do bytes = bytes + 12 end
    return bytes, endpoints
end

-- Providers resolve real runtime handles in SP, MP client, dedicated server and
-- the offline model. They are evaluated when enable() installs hooks.
local providers = {}
providers.authority = function()
    return D.bound.authority or (CVPRuntime and CVPRuntime.authority)
        or R or (CVPMPServer and CVPMPServer.authority)
end
providers.simulation = function()
    local a = providers.authority()
    return D.bound.simulation or (a and a.simulation) or Sim
end
providers.service = function()
    local a = providers.authority()
    return D.bound.service or (a and a.service) or S
end
providers.host = function()
    local a = providers.authority()
    return D.bound.host or (a and a.host) or H
end
providers.presentation = function()
    return D.bound.presentation or (CVPRuntime and CVPRuntime.presentation) or Renderer
end
providers.simulationFrame = function() return require('CVP_SimulationFrame') end
providers.linkGraph = function() return require('CVP_LinkGraph') end
providers.obstacles = function() return require('CVP_LinkObstacles') end
providers.joints = function() return require('CVP_LinkJoints') end
providers.core = function() return require('CVP_Core') end
providers.constraints = function() return require('CVP_GroupConstraints') end
providers.rope = function() return require('CVP_Rope') end
providers.load = function() return require('CVP_Load') end
providers.equipment = function() return require('CVP_Equipment') end
providers.mpServer = function() return CVPMPServer end
providers.mpClient = function() return CVPMPClient end
providers.worldNative = function() return CVPWorldNative end
providers.skeletonNative = function() return CVPSkeletonNative end
providers.ropeScene = function() return CVPFreeRopeScene end
providers.network = function() return CVPNetwork end
providers.motion = function() return D.bound.motion or (CVPRuntime and CVPRuntime.motion) end
D.providers = providers

local function resolveProvider(name)
    local provider = providers[name]
    if not provider then return nil end
    local ok, value = pcall(provider)
    if not ok then return nil end
    return value
end

local function installHook(spec)
    local owner = resolveProvider(spec.provider)
    if type(owner) ~= 'table' and type(owner) ~= 'userdata' then
        D.unavailable[#D.unavailable + 1] = spec.provider .. '.' .. spec.key .. ' (provider)'
        return false
    end
    local ok, original = pcall(function() return owner[spec.key] end)
    if not ok or type(original) ~= 'function' then
        D.unavailable[#D.unavailable + 1] = spec.provider .. '.' .. spec.key .. ' (missing)'
        return false
    end
    local hadRaw = false
    if type(owner) == 'table' then hadRaw = rawget(owner, spec.key) ~= nil end
    local wrapper
    local maxSamples = nil
    if spec.kind == 'phase' or spec.kind == 'hostSamples' then
        wrapper = function(...)
            local mark = D.clock()
            local a, b, c = original(...)
            local elapsed = D.clock() - mark
            local store = phaseStore(spec.name)
            if store then push(store, elapsed) end
            if spec.kind == 'hostSamples' then D.count('host.samples.calls') end
            return a, b, c
        end
    elseif spec.kind == 'miss' then
        wrapper = function(...)
            local mark = D.clock()
            local a, b, c = original(...)
            local store = phaseStore(spec.name)
            if store then push(store, D.clock() - mark) end
            if a == nil or a == false then D.count(spec.counter or (spec.name .. '.misses')) end
            return a, b, c
        end
    elseif spec.kind == 'count' then
        wrapper = function(...)
            D.count(spec.counter or spec.name)
            return original(...)
        end
    elseif spec.kind == 'simTick' then
        wrapper = function(self, graph, index, dt, ...)
            local mark = D.clock()
            local a, b = original(self, graph, index, dt, ...)
            local elapsed = D.clock() - mark
            local store = phaseStore(spec.name)
            if store then push(store, elapsed) end
            D.count('sim.tick.calls')
            local records, groups = 0, 0
            for _, group in pairs(self.groups or {}) do
                groups = groups + 1
                records = records + #group.records
            end
            D.gauge('sim.groups', groups)
            D.gauge('sim.records', records)
            local steps = math.max(1, math.ceil((tonumber(dt) or 0) * 100 - 1e-9))
            D.count('sim.bodyLoopPasses.estimated', records * steps)
            D.count('sim.linkLoopPasses.estimated', records * steps)
            D.count('sim.solveSteps', steps * groups)
            return a, b
        end
    elseif spec.kind == 'simBuild' then
        wrapper = function(self, ...)
            local mark = D.clock()
            local a, b, c = original(self, ...)
            local store = phaseStore(spec.name)
            if store then push(store, D.clock() - mark) end
            D.count('sim.planRebuilds')
            return a, b, c
        end
    elseif spec.kind == 'captureFrame' then
        wrapper = function(...)
            local mark = D.clock()
            local frame = original(...)
            local elapsed = D.clock() - mark
            local store = phaseStore(spec.name)
            if store then push(store, elapsed) end
            D.count('capture.frames')
            if type(frame) == 'table' then
                local endpoints = 0
                for _ in pairs(frame.endpoints or {}) do endpoints = endpoints + 1 end
                local bodies = 0
                for _ in pairs(frame.bodies or {}) do bodies = bodies + 1 end
                local loads = 0
                for _ in pairs(frame.loads or {}) do loads = loads + 1 end
                local obstacles = 0
                for _ in pairs(frame.obstacles or {}) do obstacles = obstacles + 1 end
                D.gauge('capture.links', endpoints)
                D.gauge('capture.bodies', bodies)
                D.gauge('capture.loads', loads)
                D.gauge('capture.obstacles', obstacles)
                D.count('capture.links.total', endpoints)
                local estimate = D.estimateFrameBytes(frame)
                D.bytes('capture', estimate)
            end
            return frame
        end
    elseif spec.kind == 'publishFrame' then
        wrapper = function(self, ...)
            local mark = D.clock()
            local a, b, c = original(self, ...)
            local store = phaseStore(spec.name)
            if store then push(store, D.clock() - mark) end
            D.count('publish.frames')
            local frame = self and self.simulationFrame
            if type(frame) == 'table' then
                local links, bodies, loads = 0, 0, 0
                for _ in pairs(frame.endpoints or {}) do links = links + 1 end
                for _ in pairs(frame.bodies or {}) do bodies = bodies + 1 end
                for _ in pairs(frame.loads or {}) do loads = loads + 1 end
                D.count('publish.links.total', links)
                D.gauge('publish.links', links)
                D.gauge('publish.bodies', bodies)
                D.gauge('publish.loads', loads)
                D.bytes('publish', D.estimateFrameBytes(frame))
            end
            return a, b, c
        end
    elseif spec.kind == 'action' then
        wrapper = function(self, player, name, args, callback)
            if type(callback) ~= 'function' then return original(self, player, name, args, callback) end
            local mark = D.clock()
            D.count('action.requests')
            local function measured(ok, result, reason)
                D.count(ok and 'action.confirmed' or 'action.rejected')
                D.sample('action.latency', D.clock() - mark)
                return callback(ok, result, reason)
            end
            return original(self, player, name, args, measured)
        end
    elseif spec.kind == 'runtimeTick' then
        wrapper = function(self, ...)
            local mark = D.clock()
            local a, b, c = original(self, ...)
            local store = phaseStore(spec.name)
            if store then push(store, D.clock() - mark) end
            D.tickCount = D.tickCount + 1
            D.count('tick.calls')
            D.sampleMemory()
            return a, b, c
        end
    else
        wrapper = original
    end
    local assigned = pcall(function() owner[spec.key] = wrapper end)
    if not assigned then
        D.unavailable[#D.unavailable + 1] = spec.provider .. '.' .. spec.key .. ' (read-only)'
        return false
    end
    D.installed[#D.installed + 1] = {owner = owner, key = spec.key, original = original, hadRaw = hadRaw}
    return true
end

D._installHook = installHook

function D.sampleMemory()
    if not D.memoryEnabled or not D.memory then return end
    if D.tickCount % D.memoryEveryTicks ~= 0 then return end
    if D.memory.checked == nil then
        local ok = pcall(collectgarbage, 'count')
        D.memory.available = ok == true
        D.memory.checked = true
        if not ok then return end
    end
    if not D.memory.available then return end
    local ok, value = pcall(collectgarbage, 'count')
    if not ok or type(value) ~= 'number' then D.memory.available = false; return end
    local memory = D.memory
    memory.samples = memory.samples + 1
    memory.last = value
    if memory.start == nil then memory.start = value end
    if memory.min == nil or value < memory.min then memory.min = value end
    if memory.max == nil or value > memory.max then memory.max = value end
end

function D.hookPhase(owner, key, name)
    return D.hook(owner, key, name, 'phase')
end

-- Explicit phase attachment for a known table (adapters, tests, MP layer).
function D.hook(owner, key, name, kind, counter)
    if type(owner) ~= 'table' or type(owner[key]) ~= 'function' then return false end
    local saved = providers.custom
    providers.custom = function() return owner end
    local ok = installHook({provider = 'custom', key = key, name = name, kind = kind or 'phase', counter = counter})
    providers.custom = saved
    return ok
end

local BUILTIN_HOOKS = {
    {provider = 'authority', key = 'tick', name = 'tick', kind = 'runtimeTick'},
    {provider = 'authority', key = 'simulate', name = 'tick.simulate', kind = 'phase'},
    {provider = 'authority', key = 'publishFrame', name = 'publish', kind = 'publishFrame'},
    {provider = 'authority', key = 'samples', name = 'tick.samples', kind = 'phase'},
    {provider = 'authority', key = 'discover', name = 'tick.discover', kind = 'phase'},
    {provider = 'authority', key = 'skeletons', name = 'tick.skeletons', kind = 'phase'},
    {provider = 'authority', key = 'submit', name = 'action.submit', kind = 'action'},
    {provider = 'authority', key = 'save', name = 'save.runtime', kind = 'phase'},
    {provider = 'simulation', key = 'tick', name = 'sim.tick', kind = 'simTick'},
    {provider = 'simulation', key = 'build', name = 'sim.build', kind = 'simBuild'},
    {provider = 'simulation', key = 'apply', name = 'sim.apply', kind = 'phase'},
    {provider = 'service', key = 'tick', name = 'service.tick', kind = 'phase'},
    {provider = 'service', key = 'refresh', name = 'service.refresh', kind = 'phase'},
    {provider = 'service', key = 'flush', name = 'service.flush', kind = 'phase'},
    {provider = 'service', key = 'releaseSystem', name = 'service.releaseSystem', kind = 'phase'},
    {provider = 'simulationFrame', key = 'capture', name = 'capture', kind = 'captureFrame'},
    {provider = 'presentation', key = 'update', name = 'presentation.update', kind = 'phase'},
    {provider = 'host', key = 'samples', name = 'host.samples', kind = 'hostSamples'},
    {provider = 'host', key = 'body', name = 'host.body', kind = 'miss', counter = 'host.body.misses'},
    {provider = 'host', key = 'vehicle', name = 'host.vehicle', kind = 'miss', counter = 'host.vehicle.misses'},
    {provider = 'host', key = 'bodyPoint', name = 'host.bodyPoint', kind = 'phase'},
    {provider = 'host', key = 'sample', name = 'host.sample', kind = 'phase'},
    {provider = 'linkGraph', key = 'index', name = 'graph.index', kind = 'count', counter = 'graph.indexBuilds'},
    {provider = 'linkGraph', key = 'advance', name = 'graph.advance', kind = 'count', counter = 'graph.advanceCalls'},
    {provider = 'obstacles', key = 'check', name = 'obstacles.check', kind = 'count', counter = 'obstacles.checks'},
    {provider = 'obstacles', key = 'new', name = 'obstacles.new', kind = 'count', counter = 'obstacles.caches'},
    {provider = 'joints', key = 'length', name = 'joints.length', kind = 'count', counter = 'joints.lengthCalls'},
    {provider = 'core', key = 'advance', name = 'core.advance', kind = 'count', counter = 'core.advanceCalls'},
    {provider = 'constraints', key = 'step', name = 'constraints.step', kind = 'count', counter = 'constraints.stepCalls'},
    {provider = 'rope', key = 'separate', name = 'rope.separate', kind = 'count', counter = 'rope.separateCalls'},
    {provider = 'load', key = 'refresh', name = 'load.refresh', kind = 'count', counter = 'load.refreshCalls'},
    {provider = 'equipment', key = 'editLinks', name = 'equipment.editLinks', kind = 'count', counter = 'equipment.editLinksCalls'},
    {provider = 'network', key = 'find', name = 'network.find', kind = 'count', counter = 'bridge.networkFindCalls'},
    {provider = 'worldNative', key = 'move', name = 'bridge.worldMove', kind = 'count', counter = 'bridge.worldMoveCalls'},
    {provider = 'worldNative', key = 'applyPoses', name = 'bridge.applyPoses', kind = 'count', counter = 'bridge.applyPosesCalls'},
    {provider = 'worldNative', key = 'beginRead', name = 'bridge.beginRead', kind = 'count', counter = 'bridge.beginReadCalls'},
    {provider = 'worldNative', key = 'readPoses', name = 'bridge.readPoses', kind = 'count', counter = 'bridge.readPosesCalls'},
    {provider = 'skeletonNative', key = 'sync', name = 'bridge.skeletonSync', kind = 'count', counter = 'bridge.skeletonSyncCalls'},
    {provider = 'ropeScene', key = 'shape', name = 'bridge.ropeShape', kind = 'count', counter = 'bridge.ropeShapeCalls'},
    {provider = 'ropeScene', key = 'endpoints', name = 'bridge.ropeEndpoints', kind = 'count', counter = 'bridge.ropeEndpointsCalls'},
    {provider = 'ropeScene', key = 'update', name = 'bridge.ropeUpdate', kind = 'count', counter = 'bridge.ropeUpdateCalls'},
    {provider = 'ropeScene', key = 'vehicle', name = 'bridge.ropeVehicle', kind = 'count', counter = 'bridge.ropeVehicleCalls'},
    {provider = 'mpServer', key = 'tick', name = 'mp.server.tick', kind = 'phase'},
    {provider = 'mpServer', key = 'capture', name = 'mp.server.capture', kind = 'phase'},
    {provider = 'mpServer', key = 'publish', name = 'mp.server.publish', kind = 'phase'},
    {provider = 'mpClient', key = 'tick', name = 'mp.client.tick', kind = 'phase'},
    {provider = 'motion', key = 'pushEndpoints', name = 'motion.pushEndpoints', kind = 'phase'},
    {provider = 'motion', key = 'endpoints', name = 'motion.endpoints', kind = 'phase'},
}

function D.enable(options)
    -- An enable after a normal disable restarts cleanly. If a previous restore
    -- failed, retry it here instead of stacking a second wrapper on an owner.
    if D.on then D.disable() end
    if #D.installed > 0 then D.disable() end
    configure(options)
    D.on = true
    D.reset()
    D.unavailable = {}
    for _, spec in ipairs(BUILTIN_HOOKS) do installHook(spec) end
    D.hookCount = #D.installed
    return D.snapshot()
end

function D.disable()
    if not D.on and #D.installed == 0 then return false end
    D.on = false
    local restored = true
    for i = #D.installed, 1, -1 do
        local entry = D.installed[i]
        local ok = pcall(function()
            if entry.hadRaw then entry.owner[entry.key] = entry.original
            else entry.owner[entry.key] = nil end
        end)
        if ok then
            D.installed[i] = nil
        else
            -- Keep the entry so a later disable/enable can retry the restore.
            restored = false
            D.unavailable[#D.unavailable + 1] = 'restore:' .. tostring(entry.key)
        end
    end
    if #D.installed == 0 then D.hookCount = 0 end
    return restored
end

local function elapsedMs()
    return math.max(0, D.clock() - (D.startedAt or D.clock()))
end

function D.snapshot()
    local phases = {}
    for _, name in ipairs(D.phaseOrder) do
        local summary = summarize(D.phases[name], 'ms')
        summary.name = name
        summary.elapsedMs = elapsedMs()
        if summary.count > 0 and summary.elapsedMs > 0 then
            summary.perSecond = summary.count * 1000 / summary.elapsedMs
        end
        phases[#phases + 1] = summary
    end
    local counters = {}
    for _, name in ipairs(D.counterOrder) do
        local row = D.counters[name]
        counters[#counters + 1] = {name = name, unit = row.unit, count = row.count}
    end
    local gauges = {}
    for _, name in ipairs(D.gaugeOrder) do
        local row = D.gauges[name]
        gauges[#gauges + 1] = {name = name, unit = row.unit, value = row.value,
            min = row.min, max = row.max, samples = row.samples}
    end
    local memory = {available = D.memory and D.memory.available or false, unit = 'KB',
        start = D.memory and D.memory.start, last = D.memory and D.memory.last,
        min = D.memory and D.memory.min, max = D.memory and D.memory.max,
        samples = D.memory and D.memory.samples or 0}
    local unavailable = {}
    for i, name in ipairs(D.unavailable) do unavailable[i] = name end
    return {
        schema = D.schema,
        version = D.version,
        enabled = D.on,
        elapsedMs = elapsedMs(),
        phases = phases,
        counters = counters,
        gauges = gauges,
        memory = memory,
        hooks = {installed = D.hookCount or #D.installed, unavailable = unavailable},
        overflow = {phases = D.phaseOverflow or 0, counters = D.counterOverflow or 0, gauges = D.gaugeOverflow or 0},
        notes = D.notes,
    }
end

local function formatNumber(value, digits)
    if type(value) ~= 'number' then return tostring(value) end
    local power = 10 ^ (digits or 3)
    return string.format('%.' .. tostring(digits or 3) .. 'f', math.floor(value * power + 0.5) / power)
end

function D.report()
    local snapshot = D.snapshot()
    local lines = {'[cvp diagnostics] enabled=' .. tostring(snapshot.enabled)
        .. ' elapsedMs=' .. formatNumber(snapshot.elapsedMs, 0)
        .. ' hooks=' .. tostring(snapshot.hooks.installed)}
    lines[#lines + 1] = 'phases (ms): name count min median p95 p99 max mean'
    for _, row in ipairs(snapshot.phases) do
        if row.count > 0 then
            lines[#lines + 1] = string.format('%s count=%d min=%s median=%s p95=%s p99=%s max=%s mean=%s',
                row.name, row.count, formatNumber(row.min), formatNumber(row.median),
                formatNumber(row.p95), formatNumber(row.p99), formatNumber(row.max), formatNumber(row.mean))
        end
    end
    lines[#lines + 1] = 'counters: name unit count'
    for _, row in ipairs(snapshot.counters) do
        lines[#lines + 1] = string.format('%s unit=%s count=%s', row.name, row.unit, formatNumber(row.count, 0))
    end
    lines[#lines + 1] = 'gauges: name unit value min max'
    for _, row in ipairs(snapshot.gauges) do
        lines[#lines + 1] = string.format('%s unit=%s value=%s min=%s max=%s', row.name, row.unit,
            formatNumber(row.value), formatNumber(row.min), formatNumber(row.max))
    end
    lines[#lines + 1] = 'memory: available=' .. tostring(snapshot.memory.available)
        .. ' unit=KB last=' .. tostring(snapshot.memory.last)
    return table.concat(lines, '\n')
end

local function jsonEscape(text)
    text = tostring(text)
    text = text:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t')
    return '"' .. text .. '"'
end

local function jsonEncode(value, out, depth)
    if depth and depth > 8 then out[#out + 1] = 'null'; return end
    local valueType = type(value)
    if valueType == 'nil' then out[#out + 1] = 'null'
    elseif valueType == 'boolean' then out[#out + 1] = value and 'true' or 'false'
    elseif valueType == 'number' then
        if value ~= value or value == math.huge or value == -math.huge then out[#out + 1] = 'null'
        else out[#out + 1] = string.format('%.6f', value) end
    elseif valueType == 'string' then out[#out + 1] = jsonEscape(value)
    elseif valueType == 'table' then
        local isArray = true
        local count = 0
        for _ in pairs(value) do count = count + 1 end
        for key in pairs(value) do
            if type(key) ~= 'number' or key ~= math.floor(key) or key < 1 or key > count then isArray = false; break end
        end
        out[#out + 1] = isArray and '[' or '{'
        local first = true
        if isArray then
            for i = 1, count do
                if not first then out[#out + 1] = ',' end
                first = false
                jsonEncode(value[i], out, (depth or 0) + 1)
            end
        else
            local keys = {}
            for key in pairs(value) do keys[#keys + 1] = tostring(key) end
            table.sort(keys)
            for _, key in ipairs(keys) do
                local item = value[key]
                if item == nil then item = value[tonumber(key)] end
                if not first then out[#out + 1] = ',' end
                first = false
                out[#out + 1] = jsonEscape(key); out[#out + 1] = ':'
                jsonEncode(item, out, (depth or 0) + 1)
            end
        end
        out[#out + 1] = isArray and ']' or '}'
    else out[#out + 1] = 'null' end
end

function D.toJson(snapshot)
    local out = {}
    jsonEncode(snapshot or D.snapshot(), out, 0)
    return table.concat(out)
end

D.reset()
return D
