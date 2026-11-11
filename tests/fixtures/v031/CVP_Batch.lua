-- One queued approach/action at a time. No item moves until normal attach commits.
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local Menu=require 'CVP_Menu'
local Feedback=require 'CVP_Feedback'
local Batch={jobs=setmetatable({},{__mode='k'})}
local materials={['Base.Rope']=1,['Base.HeavyChain']=2,['Base.HeavyChain_Hook']=3}
function Batch.equipment(p,material)
    local rows,seen={},{}
    local function collect(inv)
        if seen[inv] then return end;seen[inv]=true
        local items=inv:getItems()
        for i=0,items:size()-1 do local item=items:get(i)
            if materials[item:getFullType()] and (not material or item:getFullType()==material) and (not p.getPrimaryHandItem or p:getPrimaryHandItem()~=item)
                and (not p.getSecondaryHandItem or p:getSecondaryHandItem()~=item) then rows[#rows+1]=item end
            if instanceof(item,'InventoryContainer') then collect(item:getInventory()) end
        end
    end
    collect(p:getInventory())
    table.sort(rows,function(a,b)
        local x,y=materials[a:getFullType()],materials[b:getFullType()]
        return x<y or x==y and a:getID()<b:getID()
    end)
    return rows
end
function Batch.candidates(p,v)
    local rows,seen={},{};local ax,ay,az=Geometry.anchor(v)
    for x=math.floor(ax)-8,math.floor(ax)+8 do for y=math.floor(ay)-8,math.floor(ay)+8 do
        local sq=getCell():getGridSquare(x,y,math.floor(az))
        if sq then local bodies=sq:getStaticMovingObjects()
            for i=0,bodies:size()-1 do local b=bodies:get(i)
                if not seen[b] then
                    seen[b]=true
                    if World.towable(b) and b:isZombie() and not World.data(b) and not b:isBeingGrappled() and not World.foreignTowed(b)
                        and b:getStaticMovingObjectIndex()>=0 and math.floor(b:getZ())==math.floor(az)
                        and (ax-b:getX())^2+(ay-b:getY())^2<=64 then rows[#rows+1]=b end
                end
            end
        end
    end end
    table.sort(rows,function(a,b)
        return (p:getX()-a:getX())^2+(p:getY()-a:getY())^2<(p:getX()-b:getX())^2+(p:getY()-b:getY())^2
    end)
    return rows
end
function Batch.start(p,v,point,queue,count,material)
    if p:isDead() or p:getVehicle() or not v:getSquare() or math.abs(v:getCurrentSpeedKmHour())>1 then return end
    local bodies,gear=Batch.candidates(p,v),Batch.equipment(p,material)
    local ax,ay,az=Geometry.anchor(v)
    local job={rows={},index=0,phase='prepareVehicle'}
    for i=1,math.min(#bodies,#gear,math.max(0,World.maxChain())) do
        job.rows[i]={body=bodies[i],gear=gear[i],x=bodies[i]:getX(),y=bodies[i]:getY()}
    end
    job.feedback=Feedback.begin(p,#job.rows,'attach')
    Batch.jobs[p]=job
    local function step(ok,id,reason)
        if Batch.jobs[p]~=job then return end
        local x,y,z=Geometry.anchor(v)
        if job.feedback.cancelled or ok==false or p:isDead() or p:getVehicle() or not v:getSquare() or math.abs(v:getCurrentSpeedKmHour())>1
            or z~=az or (x-ax)^2+(y-ay)^2>.04 then
            Feedback.finish(job.feedback,reason or p:getVehicle() and 'IGUI_CVP_LeaveVehicle' or math.abs(v:getCurrentSpeedKmHour())>1 and 'IGUI_CVP_StopVehicle' or 'IGUI_CVP_QueueStopped')
            Batch.jobs[p]=nil;return
        end
        if ok and job.phase=='vehiclePrepared' then Feedback.progress(job.feedback,job.index,'IGUI_CVP_VisitBodies') end
        job.index=job.index+1
        if job.index>#job.rows and job.phase=='prepareVehicle' then
            job.index=1;job.phase='vehiclePrepared'
        end
        Feedback.progress(job.feedback,job.feedback.done,job.phase=='prepareVehicle' and 'IGUI_CVP_PrepareHitch' or 'IGUI_CVP_VisitBodies')
        local row=job.rows[job.index]
        if row and (row.body:getX()-row.x)^2+(row.body:getY()-row.y)^2<=.04
            and queue(p,row.body,v,row.gear,point,step,true,job.phase) then return end
        Feedback.finish(job.feedback,row and 'IGUI_CVP_QueueStopped' or nil)
        Batch.jobs[p]=nil
    end
    step()
end
-- Snapshot the selected vehicle's links; finish each action before approaching the next.
function Batch.release(p,v,rows,queue)
    table.sort(rows,function(a,b)
        return (p:getX()-a.body:getX())^2+(p:getY()-a.body:getY())^2
            <(p:getX()-b.body:getX())^2+(p:getY()-b.body:getY())^2
    end)
    local job={index=0,feedback=Feedback.begin(p,#rows,'detach')};Batch.jobs[p]=job
    local function step(ok,id,reason)
        if Batch.jobs[p]~=job then return end
        if job.feedback.cancelled or ok==false or p:isDead() or p:getVehicle() or not v:getSquare() or math.abs(v:getCurrentSpeedKmHour())>1 then
            Feedback.finish(job.feedback,reason or 'IGUI_CVP_QueueStopped');Batch.jobs[p]=nil;return
        end
        if ok then Feedback.progress(job.feedback,job.index) end
        job.index=job.index+1
        local row=rows[job.index]
        if row and queue(row,step) then return end
        Feedback.finish(job.feedback,row and 'IGUI_CVP_QueueStopped' or nil)
        Batch.jobs[p]=nil
    end
    step()
end
-- Only free tails are eligible; the caller supplies ownership/capacity checks.
function Batch.nearest(b,links,eligible)
    local best,dist=nil,64
    for _,r in pairs(links) do local source=r.body
        if source and source~=b and source:getSquare() and source:getStaticMovingObjectIndex()>=0
            and not source:isBeingGrappled() and math.floor(source:getZ())==math.floor(b:getZ()) then
            local d=(source:getX()-b:getX())^2+(source:getY()-b:getY())^2
            if d<=dist and eligible(r) then best,dist=r,d end
        end
    end
    return best
end
function Batch.update()
    for _,job in pairs(Batch.jobs) do if job.wait then job.wait() end end
end
-- Shared with the preview: material/capacity and route select the same bodies.
function Batch.preview(candidates,limit,v,sequential)
    local pool,selected={},{}
    for i,b in ipairs(candidates) do pool[i]=b end
    local x,y=Geometry.anchor(v)
    for i=1,math.min(#pool,limit) do
        local best,dist=1,nil
        if sequential then
            best=nil
            for n,b in ipairs(pool) do local d=(b:getX()-x)^2+(b:getY()-y)^2
                if d<=64 and (not dist or d<dist) then best,dist=n,d end
            end
        end
        if not best then break end
        local b=table.remove(pool,best);selected[#selected+1]=b;x,y=b:getX(),b:getY()
    end
    return selected
end
function Batch.sequential(p,v,queue,count,chain,material)
    local bodies,gear=Batch.candidates(p,v),Batch.equipment(p,material)
    local ax,ay,az=Geometry.anchor(v)
    local job={index=0,rows={}};Batch.jobs[p]=job
    for i,b in ipairs(Batch.preview(bodies,math.min(#gear,math.max(0,World.maxChain())),v,true)) do
        job.rows[i]={body=b,gear=gear[i],x=b:getX(),y=b:getY()}
    end
    job.feedback=Feedback.begin(p,#job.rows,'attach')
    local function valid()
        if Batch.jobs[p]~=job or job.feedback.cancelled then return false end
        local x,y,z=Geometry.anchor(v)
        return not p:isDead() and not p:getVehicle() and v:getSquare()
            and math.abs(v:getCurrentSpeedKmHour())<=1 and z==az
            and (x-ax)^2+(y-ay)^2<=.04
    end
    local function stop(reason) Feedback.finish(job.feedback,reason);if Batch.jobs[p]==job then Batch.jobs[p]=nil end end
    local advance
    advance=function(parent)
        job.wait=nil
        if not valid() then stop('IGUI_CVP_QueueStopped');return end
        job.index=job.index+1
        local row=job.rows[job.index]
        if not row or not row.body:getSquare()
            or (row.body:getX()-row.x)^2+(row.body:getY()-row.y)^2>.04 then stop(row and 'IGUI_CVP_QueueStopped' or nil);return end
        local function done(ok,id,reason)
            if Batch.jobs[p]~=job then return end
            if not ok or not id then stop(reason or 'IGUI_CVP_QueueStopped');return end
            Feedback.progress(job.feedback,job.index,'IGUI_CVP_VisitBodies')
            if job.index>=#job.rows then stop();return end
            local started=getTimestampMs()
            job.wait=function()
                if not valid() then stop('IGUI_CVP_QueueStopped');return end
                if getTimestampMs()-started>10000 then stop('IGUI_CVP_QueueTimeout');return end
                local r=chain.resolve(row.body)
                if r then
                    local descriptor=r.target and r.target.connection or r.connection
                    if not descriptor or descriptor.id~=id then stop('IGUI_CVP_QueueStopped');return end
                    advance(r)
                end
            end
            job.wait()
        end
        local queued
        if parent then queued=chain.queue(p,row.body,parent,row.gear,done)
        else
            Feedback.progress(job.feedback,0,'IGUI_CVP_PrepareHitch')
            queued=queue(p,row.body,v,row.gear,nil,function(ok,id,reason)
                if not valid() or not ok then done(false,nil,reason);return end
                Feedback.progress(job.feedback,0,'IGUI_CVP_VisitBodies')
                if not queue(p,row.body,v,row.gear,nil,done,true,'vehiclePrepared') then done(false) end
            end,true,'prepareVehicle')
        end
        if not queued then stop('IGUI_CVP_QueueStopped') end
    end
    advance()
end
function Batch.menu(p,context,queue,count,unavailable,chain,scope)
    if scope.bodyClick then return end
    local it=getCell():getVehicles():iterator()
    while it:hasNext() do local v=it:next()
        if (not scope.vehicle or scope.vehicle==v) and v:getSquare()
            and math.floor(v:getZ())==math.floor(p:getZ()) and (p:getX()-v:getX())^2+(p:getY()-v:getY())^2<=36 then
            local occupied=function() return count(v) end
            local available=#Batch.equipment(p)
            local candidates=Batch.candidates(p,v)
            local nearby=#candidates
            local capacity=math.max(0,World.maxChain())
            local amounts={}
            for _,t in ipairs({'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}) do
                amounts[t]=#Batch.equipment(p,t)
            end
            local reason=unavailable or p:getVehicle() and getText('IGUI_CVP_LeaveVehicle')
                or math.abs(v:getCurrentSpeedKmHour())>1 and getText('IGUI_CVP_StopVehicle')
                or available==0 and getText('IGUI_CVP_NeedGear')
                or nearby==0 and getText('IGUI_CVP_NoNearby') or nil
            local menu=scope:vehicleMenu(v)
            local t=scope.material
            local n=math.min(amounts[t] or 0,nearby,capacity)
            local quick=Menu.reason(menu:addOption(getText('IGUI_CVP_QuickNearby',getText(Menu.labels[t]),tostring(n)),nil,function()
                Batch.start(p,v,nil,queue,occupied,t)
            end),reason)
            local highlighted=Batch.preview(candidates,n,v,false)
            Menu.highlight(quick,highlighted,v,true)
            Menu.hint(quick,getText('IGUI_CVP_HintVehicleFirst',tostring(n)))
            scope:materialMenu()
            local more=Menu.sub(menu,getText('IGUI_CVP_OtherWays'))
            if chain then
                local selected=Batch.preview(candidates,n,v,true)
                local opt=Menu.reason(more:addOption(getText('IGUI_CVP_QuickSequence',getText(Menu.labels[t]),tostring(#selected)),nil,function()
                    Batch.sequential(p,v,queue,occupied,chain,t)
                end),reason)
                Menu.highlight(opt,selected,v,true)
            end
            local automatic=Menu.reason(more:addOption(getText('IGUI_CVP_AutoMaterial'),nil,function()
                Batch.start(p,v,nil,queue,occupied)
            end),reason)
            Menu.highlight(automatic,Batch.preview(candidates,math.min(available,capacity),v,false),v,true)
            Menu.hint(automatic,getText('IGUI_CVP_HintVehicleFirst',tostring(math.min(available,nearby,capacity))))
            if chain then
                local opt=Menu.reason(more:addOption(getText('IGUI_CVP_AutoSequence'),nil,function()
                    Batch.sequential(p,v,queue,occupied,chain)
                end),reason)
                Menu.highlight(opt,Batch.preview(candidates,math.min(available,capacity),v,true),v,true)
            end
        end
    end
end
return Batch
