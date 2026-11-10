-- SP entry point. Multiplayer uses the same authority/actions through its transport.
if isClient() or isServer() then return end
local Authority=require 'CVP_LinkRuntime'
local Actions=require 'CVP_LinkActions'
local Menu=require 'CVP_LinkMenu'
local Presentation=require 'CVP_LinkPresentation'
local View=require 'CVP_Viewpoint'
local Motion=require 'CVP_Motion'
local G=require 'CVP_LinkGraph'
-- Validate before replacing a running development session's dispatchers.
for name,module in pairs({CVP_LinkRuntime=Authority,CVP_LinkActions=Actions,CVP_LinkMenu=Menu,CVP_LinkPresentation=Presentation}) do
    assert(type(module)=='table' and type(module.new)=='function',name..' unavailable; keeping previous client handlers')
end
assert(type(View)=='table' and type(View.track)=='function','CVP_Viewpoint unavailable')
local state=CVPRuntime or {schema=4,authority=Authority.new(),dispatchers={},generation=0}
assert(state.schema==4,'CVP runtime schema changed; reload the save')
local authority=state.authority
local ropeVersion,skeletonVersion
local function nativeReason()
    if not CVPBodyPresentation or CVPBodyPresentation.version()~='1-shared-playback'
        or not CVPNetwork or not CVPWorldNative or not CVPItemNative or not CVPEquipmentPersistence
        or not CVPFreeRopeScene or not CVPFreeRopeScene.version
        or not CVPSkeletonNative or not CVPSkeletonNative.version then return 'IGUI_CVP_NativeUnavailable' end
    if ropeVersion~=CVPFreeRopeScene.version then
        if CVPFreeRopeScene.version()~='1-free-endpoints' then return 'IGUI_CVP_NativeUnavailable' end
        ropeVersion=CVPFreeRopeScene.version
    end
    if skeletonVersion~=CVPSkeletonNative.version then
        if CVPSkeletonNative.version()~='2-graph-clocks' then return 'IGUI_CVP_NativeUnavailable' end
        skeletonVersion=CVPSkeletonNative.version
    end
end
local api={host=authority.host}
function api.graph() return authority.service.graph or G.empty() end
function api.obstacle(id) return authority.simulation.obstacles[id] end
function api.ready()
    return nativeReason() or (not authority.started or state.error) and 'IGUI_CVP_Unavailable' or nil
end
function api.request(p,name,args,callback)
    local why=api.ready();if why then callback(false,nil,why);return end
    local job=authority:submit(p,name,args,callback)
    return function() authority:cancel(job) end
end
local actions=state.actions or Actions.new(api)
local menu=Menu.new(api,actions)
local presentation=state.presentation or Presentation.new(authority.host)
local function players()
    local rows={}
    for id=0,getNumActivePlayers()-1 do local p=getSpecificPlayer(id);if p then rows[#rows+1]=p end end
    return rows
end
local function report(err)
    if err and err~=state.error then print('[CVP] Authority: '..tostring(err)) end
    state.error=err
end
local function present(dt,points)
    local graph=api.graph();local frame=authority.simulationFrame
    local rows=state.motionRows or {};state.motionRows=rows
    if not frame or frame.revision~=graph.revision or authority.error then
        for key,r in pairs(rows) do Motion.unpresent(r,authority.host);View.untrack(r.body);rows[key]=nil end
        state.motionOrder=nil;state.motionFrame=nil;authority.host.visualJoints=nil;authority.host.displayBodies=nil
        return presentation:update(graph,frame and frame.revision==graph.revision and frame.endpoints or points,dt)
    end
    if state.motionFrame~=frame then
        local orderChanged=false
        for key,r in pairs(rows) do if not frame.bodies[key] then
            Motion.unpresent(r,authority.host);View.untrack(r.body);rows[key]=nil;orderChanged=true
        end end
        for key,s in pairs(frame.bodies) do
            local r=rows[key]
            if not r or not r.target or r.target.token~=s.token then
                if r then Motion.unpresent(r,authority.host);View.untrack(r.body) end
                r={};rows[key]=r;orderChanged=true
            end
            local target,changed=Motion.target(r,s)
            if changed then orderChanged=true end
            Motion.push(r,target,frame.sampledAt)
        end
        if orderChanged then state.motionOrder=nil end
        state.motionFrame=frame
    end
    if not state.motionOrder then
        state.motionOrder=Motion.ordered(rows)
        Motion.bindJoints(rows,graph,authority.service.index,authority.host)
    end
    authority.host.displayBodies=frame.bodies
    Motion.begin(authority.host,authority.host.now(),true)
    for _,r in ipairs(state.motionOrder) do
        local body=authority.host.body({key=r.id})
        if r.body~=body then
            Motion.unpresent(r,authority.host);if r.body then View.untrack(r.body) end
            r.body=body;if body then View.track(body) end
        end
        local pose=Motion.pose(r,frame.sampledAt,0)
        if not body then Motion.present(r,pose,rows,authority.host) end
        if body then
            -- SP displays the latest committed pose; it never moves originals.
            if body==r.target.object and body:getZ()==pose.z and math.abs(body:getX()-pose.x)+math.abs(body:getY()-pose.y)<.001 then
                Motion.present(r,pose,rows,authority.host)
            else
                r.drawDX=0;r.drawDY=0;r.visualRecovery=true;r.visualRoot=r
                Motion.unpresent(r,authority.host)
            end
        end
    end
    if CVPBodyPresentation then CVPBodyPresentation.update(state.motionOrder) end
    return presentation:update(graph,frame and frame.revision==graph.revision and frame.endpoints or points,dt)
end
local lastTick=getTimestampMs()
local handlers={}
function handlers.OnTick()
    local now=getTimestampMs();local dt=math.max(0,math.min((now-lastTick)/1000,.1));lastTick=now
    actions:update()
    local missing=nativeReason();if missing then report(missing);return end
    local ok,err,points=authority:tick(players,dt,true);report(not ok and err or nil)
    if authority.started then
        local called,success,why=pcall(present,dt,points)
        local issue=not called and success or not success and why or nil
        if issue and issue~=state.visualError then print('[CVP] Presentation: '..tostring(issue)) end
        if issue then
            if CVPBodyPresentation then CVPBodyPresentation.clear() end;authority.host.visualOffsets=nil;authority.host.visualJoints=nil;state.motionOrder=nil
        end
        state.visualError=issue
    end
end
function handlers.OnGameStart()
    View.clear();presentation:clear();state.tracked=nil;state.motionRows={};state.motionFrame=nil;state.motionOrder=nil
    authority.host.visualOffsets=nil;authority.host.visualJoints=nil;if CVPBodyPresentation then CVPBodyPresentation.clear() end
    lastTick=getTimestampMs()
    handlers.OnTick()
end
function handlers.OnSave()
    if authority.started then local ok,why=authority:save();report(not ok and why or nil) end
end
function handlers.OnCVPVehicleRemoved(vehicle) authority:vehicleRemoved(vehicle) end
function handlers.OnFillWorldObjectContextMenu(id,context,objects,test)
    if test then return end
    local p=getSpecificPlayer(id);if not p or p:isDead() then return end
    if api.ready() then
        local opt=context:addOption(getText('IGUI_CVP_TowingMenu'),nil,nil)
        require('CVP_Menu').reason(opt,getText(api.ready()));return
    end
    -- Refresh on user interaction as well as the bounded background discovery.
    authority.host.discover();menu:fill(p,context,objects)
end
for name in pairs(handlers) do if not state.dispatchers[name] then
    local eventName=name
    local dispatcher=function(...)
        local current=CVPRuntime
        if current and current.handlers[eventName] then return current.handlers[eventName](...) end
    end
    Events[name].Add(dispatcher);state.dispatchers[name]=dispatcher
end end
state.handlers=handlers;state.actions=actions;state.presentation=presentation;state.api=api
state.generation=state.generation+1;CVPRuntime=state
if isDebugEnabled() then
    CVPTest={graph=api.graph,authority=authority,actions=actions,generation=function() return state.generation end}
end
