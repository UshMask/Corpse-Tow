-- One presentation queue shared by SP and MP. Only the supplied authority API
-- changes links/items; every next stage waits for its acknowledgement.
local Action=require 'CVP_AttachAction'
local Feedback=require 'CVP_Feedback'
local G=require 'CVP_LinkGraph'
local message=require 'CVP_LinkMessages'
require 'Vehicles/TimedActions/ISPathFindAction'
local Actions={};Actions.__index=Actions
function Actions.new(api) return setmetatable({api=api,jobs=setmetatable({},{__mode='k'})},Actions) end
function Actions:begin(p,total,kind,after)
    local previous=self.jobs[p]
    if previous and not previous.finished then previous:finish(false,nil,'IGUI_CVP_CancelledQueue') end
    local job={player=p,after=after,feedback=Feedback.begin(p,total,kind),guard={},references={},api=self.api}
    job.visualId='preparing:'..p:getUsername()
    self.jobs[p]=job
    function job:reference(ref)
        if not ref then return end
        local owned=self.references[ref]
        if not owned then
            owned=G.copy(ref);self.references[ref]=owned;self.references[owned]=owned
        end
        return owned
    end
    function job:sample(ref)
        return self.api.host.actionSample(self:reference(ref))
    end
    function job:finish(ok,result,why)
        if self.finished then return end;self.finished=true
        local cancel=self.cancelRequest;self.cancelRequest=nil
        if not ok and cancel then cancel() end
        if CVPFreeRopeScene then CVPFreeRopeScene.remove(self.visualId) end
        if ok and self.feedback.total==1 then Feedback.progress(self.feedback,1) end
        if not ok and not why then why='IGUI_CVP_QueueStopped' end
        Feedback.finish(self.feedback,why and message(why) or nil)
        if self.after then self.after(ok,result,why) end
    end
    function job:valid(target)
        target=target and self:reference(target)
        local targetPoint
        if self.finished or self.feedback.cancelled then return 'IGUI_CVP_CancelledQueue' end
        if p:isDead() then return 'IGUI_CVP_Dead' end
        if p:getVehicle() or require('CVP_Horse').mounted(p) then return 'IGUI_CVP_LeaveVehicle' end
        local reason=self.api.ready();if reason then return reason end
        for _,row in ipairs(self.guard) do
            local point,reason=self:sample(row.ref)
            if not point then return reason or 'IGUI_CVP_Unavailable' end
            if row.ref==target then targetPoint=point end
            if G.actionMoved(row.ref.kind,point,row.point) then return 'IGUI_CVP_BodyMoved' end
            if row.ref.kind=='horse' and not require('CVP_Horse').stopped(self.api.host.horse(row.ref)) then return 'IGUI_CVP_StopHorse' end
            if row.ref.kind=='vehicle' then
                local v=self.api.host.vehicle(row.ref)
                if not v or math.abs(v:getCurrentSpeedKmHour())>1 then return 'IGUI_CVP_StopVehicle' end
            end
        end
        if self.gear and self.api.host.item(p,self.gear:getID())~=self.gear then return 'IGUI_CVP_NeedGear' end
        if target and not targetPoint then
            local reason;targetPoint,reason=self:sample(target)
            if not targetPoint then return reason or 'IGUI_CVP_Unavailable' end
        end
        return nil,targetPoint
    end
    function job:watch(ref)
        ref=self:reference(ref)
        local point,reason=self:sample(ref);if not point then self:finish(false,nil,reason or 'IGUI_CVP_Unavailable');return false end
        self.guard[#self.guard+1]={ref=ref,point=G.copy(point)};return true
    end
    function job:request(name,args,nextStep)
        local target=args.target and self:reference(args.target)
        local why=self:valid(target);if why then self:finish(false,nil,why);return end
        if args.target and args.target.kind=='body' then
            args=G.copy(args);args.target=G.copy(target)
        end
        self.waiting=getTimestampMs()
        local phase=self.feedback.phase
        local answered=false
        local cancel=self.api.request(p,name,args,function(ok,result,reason)
            if answered then return end;answered=true;self.cancelRequest=nil;self.waiting=nil;self.feedback.phase=phase
            if self.finished then return end
            if not ok then self:finish(false,nil,reason);return end
            if self.feedback.cancelled then self:finish(false,result,'IGUI_CVP_CancelledQueue');return end
            if name=='command' then self.feedback.notice=args.op=='take' and 'IGUI_CVP_EndInHands' or nil end
            if name=='prepare' or name=='ropePrepare' then
                local confirmed=type(result)=='table' and result.reference
                if type(confirmed)~='table' or type(result.token)~='string' or confirmed.kind~=target.kind
                    or target.point and confirmed.point~=target.point then self:finish(false,nil,'invalid preparation reply');return end
                if target.kind=='body' then
                    local accepted,why=self.api.host.confirmBody(target,confirmed)
                    if not accepted then self:finish(false,nil,why);return end
                end
                self.visualSource=G.copy(target);result=result.token
            elseif name=='create' then
                self.visualSource=nil
                if CVPFreeRopeScene then CVPFreeRopeScene.remove(self.visualId) end
            end
            nextStep(result)
        end)
        if not answered then self.cancelRequest=cancel end
    end
    function job:stage(ref,gear,removing,nextStep)
        ref=self:reference(ref)
        self.visualMaterial=gear and gear:getFullType() or self.visualMaterial or 'Base.Rope'
        local why,point=self:valid(ref);if why then self:finish(false,nil,why);return end
        self.feedback.endpoint=G.copy(point)
        local body=ref.kind=='body' and self.api.host.body(ref) or nil
        local vehicle=ref.kind=='vehicle' and self.api.host.vehicle(ref) or nil
        local endpoint=body and 'body' or vehicle and 'vehicle' or 'ground'
        local arrived=false
        local function arrival()
            if arrived or self.finished then return end;arrived=true
            local action=Action:new(p,body,vehicle,gear,function() return self:valid(ref) end,function() end,
                removing,ref.point,function(ok,reason)
                    if not ok then self:finish(false,nil,reason);return end
                    nextStep()
                end,endpoint,function() return self:sample(ref) end)
            if body then action.resolveBody=function() return self.api.host.actionBody(ref) end end
            if not action:isValid() then self:finish(false,nil,action.invalidWhy);return end
            action.visualModel=getItemStaticModel and getItemStaticModel(self.visualMaterial)
            ISTimedActionQueue.add(action)
        end
        local square=getCell():getGridSquare(math.floor(point.x),math.floor(point.y),math.floor(point.z))
        if square and p:getSquare() and p:getSquare():canReachTo(square)
            and math.floor(p:getZ())==math.floor(point.z) and (p:getX()-point.x)^2+(p:getY()-point.y)^2<=2.25 then arrival();return end
        local locations={}
        if not vehicle then locations={point.x,point.y,math.floor(point.z)} end
        for i=0,7 do local angle=i*math.pi/4
            locations[#locations+1]=point.x+math.cos(angle)*.85
            locations[#locations+1]=point.y+math.sin(angle)*.85;locations[#locations+1]=math.floor(point.z)
        end
        local path=ISPathFindAction:pathToNearest(p,locations);local stop=path.stop
        local start=path.start
        path.start=function(a)
            if start then start(a) end
            if gear and a.setOverrideHandModels then a:setOverrideHandModels(gear,nil) end
            if not gear and getItemStaticModel and a.setOverrideHandModelsString then
                a:setOverrideHandModelsString(getItemStaticModel(self.visualMaterial),nil)
            end
        end
        path.stop=function(a)
            local why=self:valid() or 'IGUI_CVP_CancelledQueue'
            stop(a);if not arrived then self:finish(false,nil,why) end
        end
        path.forceCancel=function() self:finish(false,nil,self:valid() or 'IGUI_CVP_CancelledQueue') end
        path:setOnFail(function() self:finish(false,nil,'IGUI_CVP_NoPath') end)
        path:setOnComplete(arrival);ISTimedActionQueue.add(path)
    end
    function job:createAt(target,gear,token,onCreated)
        self:stage(target,gear,false,function()
            self:request('create',{token=token,target=target},onCreated)
        end)
    end
    return job
end
function Actions:update()
    for p,job in pairs(self.jobs) do
        if not job.finished then
            if job.feedback.cancelled or p:isDead() or p:getVehicle() or require('CVP_Horse').mounted(p) then job:finish(false,nil,job:valid())
            elseif job.waiting and getTimestampMs()-job.waiting>10000 then job:finish(false,nil,'IGUI_CVP_ResultUnknown')
            elseif job.waiting and getTimestampMs()-job.waiting>=750 then job.feedback.phase='IGUI_CVP_SaveWaiting' end
        end
        if job.finished then self.jobs[p]=nil end
        if not job.finished and CVPVisualAttachment and CVPFreeRopeScene then
            local source=job.visualSource and self.api.host.sample(job.visualSource)
            local hand={};local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
            local visible=not options or options:getOption('ShowRopes'):getValue()
            if source and visible and CVPVisualAttachment.hand(p,hand) then
                local mid={x=(source.x+hand.x)/2,y=(source.y+hand.y)/2,
                    z=math.max(math.floor(hand.z)*3+.035,(source.z+hand.z)*1.5-.18)}
                CVPFreeRopeScene.update(job.visualId,{{x=source.x,y=source.y,z=source.z*3},mid,
                    {x=hand.x,y=hand.y,z=hand.z*3}},job.visualMaterial~='Base.Rope')
                CVPFreeRopeScene.vehicle(job.visualId,source.kind=='vehicle' and self.api.host.vehicle(source) or nil,true,source.point)
            else CVPFreeRopeScene.remove(job.visualId) end
        end
    end
end
function Actions:create(p,a,b,gear,after)
    local job=self:begin(p,1,'attach',after);job.gear=gear
    if not gear then job:finish(false,nil,'IGUI_CVP_NeedGear');return job end
    if not job:watch(a) or not job:watch(b) then return job end
    job:stage(a,gear,false,function()
        job:request('prepare',{target=a,gear=gear:getID()},function(token)
            job:stage(b,gear,false,function()
                job:request('create',{token=token,target=b},function(result) job:finish(true,result) end)
            end)
        end)
    end)
    return job
end
function Actions:command(p,id,revision,side,op,target,after,gear)
    local job=self:begin(p,1,op=='remove' and 'detach' or 'attach',after)
    if op=='extend' then
        if not gear then job:finish(false,nil,'IGUI_CVP_NeedGear');return job end
        job.gear=gear
    end
    local link=self.api.graph().links[id]
    if not link or link.revision~=revision then job:finish(false,nil,'IGUI_CVP_ConnectionChanged');return job end
    job.visualMaterial=link.material
    local selected=link[side]
    if not selected then job:finish(false,nil,'IGUI_CVP_ConnectionChanged');return job end
    local at=op=='bind' and target or selected
    if op=='release' and selected.kind=='horse' and not self.api.host.sample(selected) then
        at=link[side=='a' and 'b' or 'a']
    end
    if not at or not job:watch(at) then return job end
    local valid=job.valid
    job.valid=function(j,target)
        local why,point=valid(j,target);if why then return why end
        local current=self.api.graph().links[id]
        if not current or current.revision~=revision then return 'IGUI_CVP_ConnectionChanged' end
        return nil,point
    end
    job:stage(at,gear,op=='remove' or op=='release',function()
        job:request('command',{id=id,revision=revision,side=side,op=op,target=target,gear=gear and gear:getID()},function(result) job:finish(true,result) end)
    end)
    return job
end
-- Reuse the original connection: walk to its loose end, take it, then bind.
-- Cancellation after take leaves the end held; never recreate/refund material.
function Actions:reconnect(p,id,revision,side,target,after,gear)
    local job=self:begin(p,1,'reconnect',after)
    local row=self.api.graph().links[id]
    if not row or row.revision~=revision or not row[side] or row[side].kind~='ground' then
        job:finish(false,nil,'IGUI_CVP_ConnectionChanged');return job
    end
    job.visualMaterial=row.material;job.gear=gear
    if not job:watch(row[side]) or not job:watch(target) then return job end
    local targetGuard=job.guard[2];local expectedKind='ground'
    local valid=job.valid
    job.valid=function(j,target)
        local why,point=valid(j,target);if why then return why end
        local current=self.api.graph().links[id];local e=current and current[side]
        if not current or current.revision~=revision or not e or e.kind~=expectedKind
            or expectedKind=='held' and e.holder~=p:getUsername() then return 'IGUI_CVP_ConnectionChanged' end
        return nil,point
    end
    job:stage(row[side],nil,false,function()
        local function bind()
            job.guard={targetGuard}
            job:stage(target,gear,false,function()
                job:request('command',{id=id,revision=revision,side=side,op='bind',target=target,gear=gear and gear:getID()},
                    function(result) job:finish(true,result) end)
            end)
        end
        -- A short held end would be dropped before reaching the farther target.
        -- Visit the tail, then carry the new inventory rope to the target instead.
        if gear then bind() else
            job:request('command',{id=id,revision=revision,side=side,op='take'},function()
                revision=revision+1;expectedKind='held';bind()
            end)
        end
    end)
    return job
end
function Actions:batch(p,root,targets,gear,sequential,after)
    local count=math.min(#targets,#gear,sequential and require('CVP_World').maxChain() or math.huge)
    local job=self:begin(p,count,'bodies',after)
    if count==0 then job:finish(false,nil,'IGUI_CVP_NeedGear');return job end
    if not job:watch(root) then return job end
    local rootGuard=job.guard[1];local rows={};local results={}
    for i=1,count do
        if not job:watch(targets[i]) then return job end
        rows[i]={target=job:reference(targets[i]),gear=gear[i],guard=job.guard[#job.guard]}
    end
    local function guards(first,source)
        job.guard={rootGuard}
        for i=first,count do job.guard[#job.guard+1]=rows[i].guard end
        if source~=root then return job:watch(source) end
        return true
    end
    local visit
    visit=function(i,source)
        if i>count then job:finish(true,results);return end
        local row=rows[i];job.gear=row.gear
        if not guards(i,source) then return end
        local function second()
            if row.token then job.visualSource=G.copy(source) end
            job:createAt(row.target,row.gear,row.token,function(result)
                results[#results+1]=result;job.gear=nil;Feedback.progress(job.feedback,i,'IGUI_CVP_VisitBodies')
                visit(i+1,sequential and row.target or root)
            end)
        end
        if sequential then
            job:stage(source,row.gear,false,function()
                job:request('prepare',{target=source,gear=row.gear:getID()},function(token) row.token=token;second() end)
            end)
        else second() end
    end
    local prepare
    prepare=function(i)
        if i>count then visit(1,root);return end
        local row=rows[i];job.gear=row.gear
        job:stage(root,row.gear,false,function()
            job:request('prepare',{target=root,gear=row.gear:getID()},function(token)
                row.token=token;prepare(i+1)
            end)
        end)
    end
    if sequential then visit(1,root) else prepare(1) end
    return job
end
-- One queue, one physical rope per shared 12 m budget. The authority measures
-- every section again; client planning is only a convenience, never a claim.
function Actions:continuation(p,root,targets,separate,selectedId,index)
    local graph=self.api.graph();index=index or G.index(graph)
    local horse=root.kind=='horse'
    local car=horse and self.api.host.horse(root) or not horse and self.api.host.vehicle(root);if not car then return end
    local key=root.key or car:getModData().CVPVehicleKey or ('sql:'..tostring(car:getSqlId()))
    local spare=#require('CVP_Batch').equipment(p,'Base.Rope')>0
    local best,bestDistance;local choices,listed={},{}
    for _,edge in ipairs((horse and index.byHorse or index.byVehicle)[key] or {}) do
        if horse or graph.links[edge.id][edge.side].point==(root.point or 'hitch') then
            local branch=G.branch(graph,index,edge.id,edge.side)
            local row,e,count=branch.last,branch.endpoint,#branch.bodies
            if e.kind=='body' then
                local spool=index.spools[row.equipment]
                if (not selectedId or row.id==selectedId) and row.allocation and not row.returning and count<require('CVP_World').maxChain()
                    and require('CVP_World').canDetach(p,{owner=row.owner}) then
                    local at=self.api.host.sample(e)
                    if at then for _,target in ipairs(targets) do
                        local pos=self.api.host.sample(target)
                        local d=pos and math.max(.1,G.distance(at,pos))
                        if not index.byBody[target.key] and d and math.floor(at.z)==math.floor(pos.z) and d<=G.capacity
                            and (d<=G.capacity-spool.used+1e-7 or not separate and spare)
                            then
                            local choice={id=row.id,source=G.copy(e),count=count}
                            if not listed[row.id] then choices[#choices+1]=choice;listed[row.id]=true end
                            if not bestDistance or d<bestDistance or d==bestDistance and row.id<best.id then
                                best=choice;bestDistance=d
                            end
                        end
                    end end
                end
            end
        end
    end
    return best,choices
end
function Actions:ropeBatch(p,root,targets,after,separate,selectedId)
    local job=self:begin(p,#targets,'bodies',after)
    local pool={};for _,e in ipairs(targets) do pool[#pool+1]=job:reference(e) end
    local used={};local count=0;local branchCount=0;local source=job:reference(root);local last
    local resume=selectedId~=false and self:continuation(p,root,targets,separate,selectedId)
    if selectedId and not resume then job:finish(false,nil,'IGUI_CVP_ConnectionChanged');return job end
    if resume then source=resume.source;last=resume.id;branchCount=resume.count end
    local visit
    local function restart()
        source=job:reference(root);last=nil;branchCount=0;visit()
    end
    visit=function()
        if #pool==0 then job:finish(true);return end
        if branchCount>=require('CVP_World').maxChain() then
            if separate then restart() else job:finish(true) end;return
        end
        local cursor,reason=job:sample(source)
        if not cursor then job:finish(false,nil,reason or 'IGUI_CVP_Unavailable');return end
        local best,dist
        local graph=self.api.graph();local index=G.index(graph)
        for i,e in ipairs(pool) do
            local at=job:sample(e)
            local occupied=e.key and index.byBody[e.key]
            local d=at and math.max(.1,G.distance(cursor,at))
            if not occupied and d and d<=G.capacity and (not dist or d<dist) then best,dist=i,d end
        end
        if not best then
            if separate and last then restart() else job:finish(true) end;return
        end
        local previous=last and graph.links[last]
        local spool=previous and index.spools[previous.equipment]
        local reuse=spool and G.capacity-spool.used+1e-7>=dist and previous or nil
        if separate and last and not reuse then restart();return end
        local target=table.remove(pool,best)
        local gear
        if not reuse then
            for _,item in ipairs(require('CVP_Batch').equipment(p,'Base.Rope')) do
                if not used[item:getID()] then gear=item;break end
            end
            if not gear then job:finish(count>0,nil,last and 'IGUI_CVP_NeedAnotherRope' or 'IGUI_CVP_NeedRope');return end
        end
        job.guard={};job.gear=gear
        if not job:watch(root) or not job:watch(source) or not job:watch(target) then return end
        job:stage(source,gear,false,function()
            local args={target=source,gear=gear and gear:getID(),link=reuse and reuse.id,revision=reuse and reuse.revision}
            job:request('ropePrepare',args,function(token)
                job:createAt(target,gear,token,function(result)
                    if gear then used[gear:getID()]=true end
                    job.gear=nil;last=result.id;source=target;count=count+1;branchCount=branchCount+1
                    Feedback.progress(job.feedback,count,'IGUI_CVP_VisitBodies');visit()
                end)
            end)
        end)
    end
    visit();return job
end
function Actions:carry(p,first,gear,after)
    local job=self:begin(p,1,'attach',after);job.gear=gear
    if not gear then job:finish(false,nil,'IGUI_CVP_NeedGear');return job end
    if not job:watch(first) then return job end
    job:stage(first,gear,false,function()
        job:request('prepare',{target=first,gear=gear:getID()},function(token)
            job:request('create',{token=token,target={kind='ground'}},function(result)
                -- If taking the new end is refused, the already-created ground
                -- end remains real; no rollback can duplicate the original item.
                job.gear=nil
                job:request('command',{id=result.id,revision=result.revision,side='b',op='take'},function()
                    job:finish(true,result)
                end)
            end)
        end)
    end)
    return job
end
function Actions:rewire(p,root,after)
    local job=self:begin(p,0,'rewire',after)
    if not job:watch(root) then return job end
    job:stage(root,nil,false,function()
        job:request('rewirePrepare',{target=root},function(plan)
            job.feedback.total=#plan.rows
            for _,e in ipairs(plan.steps) do if not job:watch(e) then return end end
            local step
            step=function(i)
                job:stage(plan.steps[i],nil,false,function()
                    job:request('rewireVisit',{token=plan.token},function(result)
                        Feedback.progress(job.feedback,math.floor(i/2),'IGUI_CVP_RewirePreparing')
                        if result.done then job:finish(true) else step(i+1) end
                    end)
                end)
            end
            step(2)
        end)
    end)
    return job
end
function Actions:release(p,ends,after,remove,kind)
    local job=self:begin(p,#ends,kind or (remove and 'collect' or 'detach'),after);local i=0
    local function nextEnd()
        i=i+1;local entry=ends[i]
        if not entry then job:finish(true);return end
        local row=self.api.graph().links[entry.id]
        if not row or row.revision~=entry.revision then job:finish(false,nil,'IGUI_CVP_ConnectionChanged');return end
        local normalized={}
        if remove then
            local index=G.index(self.api.graph())
            for _,side in ipairs({'a','b'}) do local e=row[side]
                if e.kind=='joint' then for _,edge in ipairs(index.byJoint[e.key] or {}) do
                    if edge.id~=row.id then normalized[edge.id]=true end
                end end
            end
        end
        job.guard={};if not job:watch(row[entry.side]) then return end
        job:stage(row[entry.side],nil,true,function()
            job:request('command',{id=entry.id,revision=entry.revision,side=entry.side,op=remove and 'remove' or 'release'},function()
                for n=i+1,#ends do local pending=ends[n]
                    if normalized[pending.id] then
                        local updated=self.api.graph().links[pending.id]
                        if updated and updated.revision==pending.revision+1 then pending.revision=updated.revision end
                    end
                end
                Feedback.progress(job.feedback,i);nextEnd()
            end)
        end)
    end
    nextEnd();return job
end
return Actions
