local Menu=require 'CVP_Menu'
local Batch=require 'CVP_Batch'
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local G=require 'CVP_LinkGraph'
local Horse=require 'CVP_Horse'
local Presentation=require 'CVP_LinkPresentation'
local message=require 'CVP_LinkMessages'
local M={};M.__index=M
function M.new(api,actions) return setmetatable({api=api,actions=actions},M) end
local function reference(body)
    return {kind='body',key=body:getModData().CVPBodyKey,native=CVPNetwork.id(body),point='feet'}
end
local function carReference(car,key,point)
    -- The host decides which identity is authoritative in SP or MP.
    return {kind='vehicle',key=key,native=car:getId(),point=point or 'hitch'}
end
local function distance(p,e) return (p:getX()-e.x)^2+(p:getY()-e.y)^2 end
local function lengthHint(option,needed,available)
    if not needed then return end
    local tip=option.toolTip or ISWorldObjectContextMenu.addToolTip()
    local text=getText('IGUI_CVP_LengthHint',string.format('%.1f',needed),string.format('%.1f',available))
    if needed>available then text=text..' <LINE> '..getText('IGUI_CVP_ShortLengthHint',string.format('%.1f',needed-available)) end
    tip.description=tip.description and (tip.description..' <LINE> '..text) or text
    option.toolTip=tip
end
-- One explicit context per menu opening; builders share no module-global state.
local Context={};Context.__index=Context

function Context:option(parent,label,why,fn,bodies,vehicle,ends,primary)
    local context,common=self.context,self.common
    local opt
    if primary then
        opt=context:insertOptionBefore(getText('IGUI_CVP_MoreActions'),label,nil,fn)
    else opt=parent:addOption(label,nil,fn) end
    Menu.reason(opt,(common or why) and getText(message(common or why)) or nil)
    if bodies or vehicle or ends then Menu.highlight(opt,bodies or {},vehicle,false,ends) end
    return opt
end

function Context:permission(link)
    local p=self.p
    local owner=link.owner;if owner=='legacy:unowned' then owner=nil end
    return not World.canDetach(p,{owner=owner}) and 'IGUI_CVP_OtherOwner' or nil
end

function Context:bodyReason(body)
    return body and body:isPlayer() and not World.playerBodiesAllowed() and 'IGUI_CVP_PlayerBodiesDisabled'
        or body and (World.foreignTowed(body) or body:isBeingGrappled() or body:getModData().CVPTether) and 'IGUI_CVP_Unavailable' or nil
end

function Context:component(ref,stopAtCar)
    local index,components=self.index,self.components
    local name=ref.key and (ref.kind..':'..ref.key);local seen={};local car=false
    if name and not stopAtCar and components[name] then return components[name][1],components[name][2] end
    if not name or not index.nodes[name] then return seen,car end
    local queue={name};seen[name]=true;local at=1
    while at<=#queue do local n=index.nodes[queue[at]];at=at+1
        if G.tractor(n) then car=true end
        if not stopAtCar or not G.tractor(n) then
            for _,edge in ipairs(n.edges) do if not seen[edge.other] then seen[edge.other]=true;queue[#queue+1]=edge.other end end
        end
    end
    if not stopAtCar then local result={seen,car};for key in pairs(seen) do components[key]=result end end
    return seen,car
end

function Context:endMenu(parent,link,side,primary,choiceParent,choiceLabel,skipRelease)
    local api,actions,p,index,owner=self.api,self.actions,self.p,self.index,self.owner
    local held,extension=self.held,self.extension
    local obstruction=api.obstacle and api.obstacle(link.id)
    if obstruction then self:option(parent,getText(obstruction),obstruction,function() end) end
    local e=link[side];local sample=api.host.sample(e)
    local body=e.kind=='body' and api.host.body(e);local car=e.kind=='vehicle' and api.host.vehicle(e)
    local why=self:permission(link) or not sample and 'IGUI_CVP_Unavailable'
    if e.kind=='held' and e.holder~=owner then why='IGUI_CVP_LinkHeldByOther' end
    local editWhy=why or link.returning and 'IGUI_CVP_LinkReturnPending'
    local function command(op) return function() actions:command(p,link.id,link.revision,side,op,nil,self.finish) end end
    local actionParent=choiceParent or parent;local selectedOption
    if e.kind=='ground' then
        selectedOption=self:option(actionParent,choiceLabel or getText(link.material=='Base.Rope' and 'IGUI_CVP_LinkTakeRope' or 'IGUI_CVP_LinkTakeChain'),editWhy or not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
            or held and 'IGUI_CVP_LinkHandsOccupied',command('take'),body and {body},car,sample and {sample},primary and not held)
    elseif e.kind=='held' then
        selectedOption=self:option(actionParent,choiceLabel or getText(link.material=='Base.Rope' and 'IGUI_CVP_DropHeldRope' or 'IGUI_CVP_DropHeldChain'),editWhy,command('drop'),nil,nil,sample and {sample},primary)
        Menu.hint(selectedOption,getText(link.material=='Base.Rope' and 'IGUI_CVP_HeldRopeHint' or 'IGUI_CVP_HeldChainHint'))
    elseif not skipRelease then
        selectedOption=self:option(actionParent,choiceLabel or getText('IGUI_CVP_LinkRelease'),editWhy,command('release'),body and {body},car,sample and {sample},primary)
        Menu.hint(selectedOption,getText('IGUI_CVP_ReleaseEndHint'))
    end
    local affected,points={},{linkId=link.id,bindingA=Presentation.bindingId(link,'a'),bindingB=Presentation.bindingId(link,'b')};local vehicle
    for _,endSide in ipairs({'a','b'}) do local endRef=link[endSide]
        if endRef.kind=='body' then local b=api.host.body(endRef);if b then affected[#affected+1]=b end
        elseif endRef.kind=='vehicle' then vehicle=api.host.vehicle(endRef) end
        local pos=api.host.sample(endRef);if pos then points[#points+1]=pos end
    end
    if selectedOption then Menu.highlight(selectedOption,affected,vehicle,false,points) end
    if e.kind=='ground' then
        -- The picked ground point alone cannot distinguish overlapping loose
        -- ropes. Show what this end actually pulls, including the whole tail.
        local opposite=link[side=='a' and 'b' or 'a']
        local connected=self:component(opposite,true);local attached={}
        for name in pairs(connected) do local node=index.nodes[name]
            if node and node.kind=='body' then local b=api.host.body(node)
                if b then attached[#attached+1]=b end
            end
        end
        Menu.highlight(selectedOption,attached,vehicle,false,points)
        if opposite.kind=='ground' then Menu.hint(selectedOption,getText('IGUI_CVP_LooseTetherHint')) end
    elseif choiceParent then Menu.highlight(selectedOption,affected,vehicle,false,points) end
    local removeKey=link.material~='Base.Rope' and 'IGUI_CVP_LinkRemoveChain'
        or (link.allocation or link.extension) and 'IGUI_CVP_LinkRemoveRopeSection' or 'IGUI_CVP_LinkRemoveRope'
    local remove=self:option(parent,getText(removeKey),why,command('remove'),affected,vehicle,points,false)
    local remaining=link.allocation and #index.spools[link.equipment].ids-1 or 0
    Menu.hint(remove,remaining>0 and getText('IGUI_CVP_RemoveSharedHint',tostring(remaining))
        or link.extension and getText('IGUI_CVP_RemoveExtendedHint') or getText('IGUI_CVP_LinkRemoveHint'))
    if link.material=='Base.Rope' and not link.extension then
        self:option(parent,getText('IGUI_CVP_LinkExtend'),editWhy or link.allocation and 'IGUI_CVP_SharedRopeExtend' or not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
            or not extension and 'IGUI_CVP_NeedAnotherRope',function()
                actions:command(p,link.id,link.revision,side,'extend',nil,self.finish,extension)
            end,affected,vehicle,points)
    end
end

function Context:targetChoice(ref,label,source,body,car)
    local api,p,index=self.api,self.p,self.index
    local held,heldLink,gear=self.held,self.heldLink,self.gear
    local edges=ref.kind=='body' and index.byBody[ref.key]
    local from=source or heldLink and heldLink[held.side=='a' and 'b' or 'a']
    if held and car and from and from.kind=='ground' then label=getText('IGUI_CVP_LinkBindLooseCar') end
    local connected,hasCar=self:component(from or {})
    local _,targetCar=self:component(ref)
    local topology=edges and #edges>=2 and 'IGUI_CVP_LinkFullBody'
        or ref.key and connected[ref.kind..':'..ref.key] and 'IGUI_CVP_LinkLoop'
        or hasCar and (G.tractor(ref) or targetCar) and 'IGUI_CVP_LinkTwoCars'
    local a,b=from and api.host.sample(from),api.host.sample(ref)
    local needed=a and b and G.distance(a,b)
    local available=heldLink and G.bindCapacity(heldLink,index) or G.capacity
    local why=heldLink and (self:permission(heldLink) or heldLink.returning and 'IGUI_CVP_LinkReturnPending')
        or not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
        or not held and not gear and 'IGUI_CVP_NeedSelectedMaterial'
        or ref.kind=='horse' and (not Horse.enabled() and 'IGUI_CVP_HorseDisabled' or not Horse.stopped(api.host.horse(ref)) and 'IGUI_CVP_StopHorse')
        or self:bodyReason(body)
        or car and math.abs(car:getCurrentSpeedKmHour())>1 and 'IGUI_CVP_StopVehicle'
        or topology or a and b and math.floor(a.z)~=math.floor(b.z) and 'IGUI_CVP_BodyFloor'
        or needed and needed>available and 'IGUI_CVP_LinkTooFar' or nil
    local highlights=body and {body} or {}
    if source and source.kind=='body' then local b=api.host.body(source)
        if b and b~=body then highlights[#highlights+1]=b end
    end
    return {label=label,why=why,bodies=highlights,needed=needed,available=available}
end

function Context:target(parent,ref,label,source,body,car,primary)
    local actions,p,index=self.actions,self.p,self.index
    local held,heldLink,gear=self.held,self.heldLink,self.gear
    local reuse
    if not held and source and source.kind=='body' then
        local target=self.api.host.sample(ref)
        for _,edge in ipairs(index.byBody[source.key] or {}) do
            local link=self.graph.links[edge.id];local side=edge.side=='a' and 'b' or 'a'
            local origin=self.api.host.sample(link[edge.side])
            local free=link[side]
            if free.kind=='ground' and not link.returning and not self:permission(link)
                and target and origin and math.floor(target.z)==math.floor(origin.z)
                and G.distance(origin,target)<=G.bindCapacity(link,index)
                and distance(p,free)<=144 then
                if not reuse or link.id<reuse.link.id then reuse={link=link,side=side} end
            end
        end
    end
    local choice
    if reuse then
        self.held={id=reuse.link.id,side=reuse.side};self.heldLink=reuse.link
        choice=self:targetChoice(ref,label,source,body,car)
        self.held=held;self.heldLink=heldLink
    else choice=self:targetChoice(ref,label,source,body,car) end
    local opt=self:option(parent,choice.label,choice.why,function()
        if reuse then actions:reconnect(p,reuse.link.id,reuse.link.revision,reuse.side,ref,self.finish)
        elseif held then actions:command(p,held.id,heldLink.revision,held.side,'bind',ref,self.finish)
        elseif source and source.kind=='body' and not index.byBody[source.key] and ref.kind=='vehicle' and gear and gear:getFullType()=='Base.Rope' then
            actions:ropeBatch(p,ref,{source},self.finish,false,false)
        else actions:create(p,source,ref,gear,self.finish) end
    end,choice.bodies,car,car and {self.api.host.sample(ref)},primary)
    if not held and not reuse and gear then Menu.hint(opt,getText('IGUI_CVP_NewMaterialHint',getText(Menu.labels[gear:getFullType()]))) end
    lengthHint(opt,choice.needed,choice.available)
    return opt
end

-- Continue an existing shared rope through the same queue used at the vehicle.
-- Multiple eligible tails require an explicit choice; never silently switch trains.
function Context:continueBody(parent,ref,body,primary)
    if self.held or self.index.byBody[ref.key] then return end
    local choices={}
    -- The tail may be near the player while its vehicle is beyond the normal menu radius.
    local vehicles=getCell():getVehicles():iterator()
    while vehicles:hasNext() do local car=vehicles:next()
        for _,point in ipairs({'hitch','front'}) do
            local root=carReference(car,self.api.host.vehicleKey and self.api.host.vehicleKey(car),point)
            local _,tails=self.actions:continuation(self.p,root,{ref},false,nil,self.index)
            for _,tail in ipairs(tails or {}) do
                choices[#choices+1]={root=root,tail=tail,car=car}
            end
        end
    end
    if #choices==0 then return end
    table.sort(choices,function(a,b) return a.tail.id<b.tail.id end)
    local sub=parent
    if #choices>1 then
        local opt=self:option(parent,getText('IGUI_CVP_ContinueTrain'),nil,nil,{body},nil,nil,primary)
        sub=ISContextMenu:getNew(self.context);self.context:addSubMenu(opt,sub)
    end
    for i,row in ipairs(choices) do
        local source=self.api.host.body(row.tail.source)
        local why=self:bodyReason(body) or not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
            or math.abs(row.car:getCurrentSpeedKmHour())>1 and 'IGUI_CVP_StopVehicle'
        local name=row.car:getScript():getName()
        name=(getTextOrNull and getTextOrNull('IGUI_VehicleName'..name)) or name
        local label=#choices==1 and getText('IGUI_CVP_ContinueTrain')
            or getText('IGUI_CVP_TrainVehicleChoice',tostring(i),name)
        local opt=self:option(sub,label,why,function()
            self.actions:ropeBatch(self.p,row.root,{ref},self.finish,false,row.tail.id)
        end,source and {source,body} or {body},row.car,
            {self.api.host.sample(row.tail.source),self.api.host.sample(ref)},primary and #choices==1)
        local link=self.graph.links[row.tail.id]
        local available=G.capacity-self.index.spools[link.equipment].used
        local needed=math.max(.1,G.distance(self.api.host.sample(row.tail.source),self.api.host.sample(ref)))
        Menu.hint(opt,getText(needed<=available+1e-7 and 'IGUI_CVP_ContinueReuseHint' or 'IGUI_CVP_ContinueNewRopeHint'))
        lengthHint(opt,needed,available)
    end
    return true
end

function Context:bodyChoices(b)
    local p,index,point,held,gear=self.p,self.index,self.point,self.held,self.gear
    local cars=self.cars
    local ref=reference(b);local edges={}
    for i,edge in ipairs(index.byBody[ref.key] or {}) do edges[i]=edge end
    ref.point=point or ref.point
    table.sort(edges,function(a,b) return a.id<b.id end)
    local _,hasCar=self:component(ref);local vehicleChoices={}
    if not held and #edges<2 and not hasCar then for _,car in ipairs(cars) do
        local anchor=Menu.vehiclePoint(p,car,b,false)
        local x,y,z=Geometry.anchor(car,anchor);local d=(x-b:getX())^2+(y-b:getY())^2
        if math.floor(z)==math.floor(b:getZ()) and d<=G.capacity^2 then
            vehicleChoices[#vehicleChoices+1]={car=car,anchor=anchor,distance=math.sqrt((x-p:getX())^2+(y-p:getY())^2),
                stopped=math.abs(car:getCurrentSpeedKmHour())<=1}
        end
    end end
    table.sort(vehicleChoices,function(a,b)
        if a.stopped~=b.stopped then return a.stopped end
        return a.distance<b.distance or a.distance==b.distance and a.car:getId()<b.car:getId()
    end)
    local nearestHorse,horseDistance
    if not held and #edges<2 and not hasCar and Horse.enabled() then
        for _,horse in ipairs(Horse.all()) do local at=Horse.sample(horse)
            local d=at and (at.x-b:getX())^2+(at.y-b:getY())^2
            if d and math.floor(at.z)==math.floor(b:getZ()) and d<=G.capacity^2 and (not horseDistance or d<horseDistance) then
                nearestHorse=horse;horseDistance=d
            end
        end
    end
    return {ref=ref,edges=edges,vehicles=vehicleChoices,horse=nearestHorse,
        carryWhy=not World.towingEnabled() and 'IGUI_CVP_TowingDisabled' or self:bodyReason(b) or not gear and 'IGUI_CVP_NeedSelectedMaterial' or nil}
end

function Context:bodyMenu(b,n)
    local api,actions,p,context,graph=self.api,self.actions,self.p,self.context,self.graph
    local index,scope,point,held,gear=self.index,self.scope,self.point,self.held,self.gear
    local bodies=self.bodies
    local parent=scope:bodyMenu(b,n);local choice=self:bodyChoices(b)
    local ref,edges,vehicleChoices,nearestHorse=choice.ref,choice.edges,choice.vehicles,choice.horse
    local single=scope.bodyCount==1
    local continuation=self:continueBody(parent,ref,b,single)
    local reconnect=not held and self:reconnectMenu(parent,ref,nil,b,single and not continuation)
    reconnect=reconnect or continuation
    if held then self:target(parent,ref,getText('IGUI_CVP_LinkBindBody'),nil,b,nil,single) end
    local carMenu=parent
    if #vehicleChoices>1 then
        local opt=self:option(parent,getText('IGUI_CVP_ToVehicleMenu'),nil,nil,{b},nil,nil,single and not reconnect)
        carMenu=ISContextMenu:getNew(context);context:addSubMenu(opt,carMenu)
    end
    for _,choice in ipairs(vehicleChoices) do
        local car,anchor=choice.car,choice.anchor
        local name=car:getScript():getName();name=(getTextOrNull and getTextOrNull('IGUI_VehicleName'..name)) or name
        local from=G.copy(ref);from.point=point or Geometry.nearestPoint(b,car,anchor)
        local label=#vehicleChoices==1 and getText('IGUI_CVP_AttachCar')
            or getText('IGUI_CVP_VehicleChoice',name,string.format('%.1f',choice.distance))
        local root=carReference(car,api.host.vehicleKey and api.host.vehicleKey(car),anchor)
        local opt=self:target(carMenu,root,label,from,b,car,single and not reconnect and #vehicleChoices==1)
        local tip=opt.toolTip or ISWorldObjectContextMenu.addToolTip()
        tip.description=(tip.description or '')..' <LINE> '..getText(anchor=='front' and 'IGUI_CVP_FrontMarker' or 'IGUI_CVP_RearMarker')
            ..' · '..getText('IGUI_CVP_PlayerToAnchor',string.format('%.1f',choice.distance));opt.toolTip=tip
    end
    if nearestHorse then
        local target=Horse.sample(nearestHorse)
        self:target(parent,target,getText('IGUI_CVP_AttachHorse',nearestHorse:getFullName()),G.copy(ref),b,nil,single and not reconnect)
    end
    if not held and #edges<2 then
        local why=choice.carryWhy
        local main=single and #edges==0 and #vehicleChoices==0 and not nearestHorse and not reconnect
        local label=getText('IGUI_CVP_LinkStartCarry')
        local opt=self:option(parent,label,why,function() actions:carry(p,ref,gear,self.finish) end,{b},nil,nil,main)
        if gear then Menu.hint(opt,getText('IGUI_CVP_NewMaterialHint',getText(Menu.labels[gear:getFullType()]))) end
    end
    if #edges>0 then
        local ends={};local why
        for _,edge in ipairs(edges) do local link=graph.links[edge.id]
            why=why or self:permission(link)
            ends[#ends+1]={id=link.id,revision=link.revision,side=edge.side}
        end
        local middle=#edges>1
        local opt=self:option(parent,getText(middle and 'IGUI_CVP_DetachBodyMiddle' or 'IGUI_CVP_DetachBody'),why,function()
            actions:release(p,{ends[1]},self.finish)
        end,{b},nil,nil,single)
        Menu.hint(opt,getText(middle and 'IGUI_CVP_DetachBodyMiddleHint' or 'IGUI_CVP_DetachBodyHint'))
    end
    for i,edge in ipairs(edges) do local link=graph.links[edge.id]
        local at=parent;local label=getText('IGUI_CVP_LinkSection',getText(Menu.labels[link.material]),tostring(i))
        if #edges>1 then
            local opt;at,opt=Menu.sub(parent,label)
            Menu.highlight(opt,{b},nil,false,{api.host.sample(link.a),api.host.sample(link.b)})
        end
        -- Releasing either body endpoint unloads the entire body; only offer
        -- that action once above, not as a misleading single-end operation.
        self:endMenu(at,link,edge.side,false,nil,nil,true)
        local other=edge.side=='a' and 'b' or 'a'
        if link[other].kind=='horse' and not api.host.sample(link[other]) then
            self:option(at,getText('IGUI_CVP_ReleaseMissingHorse'),self:permission(link),function()
                actions:command(p,link.id,link.revision,other,'release',nil,self.finish)
            end,{b})
        end
    end
    if not held and #edges<2 then
        local connected,sourceCar=self:component(ref);local choices={}
        for m,other in ipairs(bodies) do local otherRef=reference(other);local otherEdges=index.byBody[otherRef.key] or {}
            local _,otherCar=self:component(otherRef)
            if other~=b and not connected['body:'..tostring(otherRef.key)] and #otherEdges<2 and not (sourceCar and otherCar) then
                choices[#choices+1]={body=other,ref=otherRef,number=m}
            end
        end
        if #choices>0 then
            -- Captured targets are revalidated by the existing action queue.
            Menu.lazySub(parent,getText('IGUI_CVP_LinkOtherBody'),function(sub)
                for _,row in ipairs(choices) do row.ref.point=point or row.ref.point
                    self:target(sub,row.ref,getText('IGUI_CVP_BodyMenu',tostring(row.number)),ref,row.body)
                end
            end)
        end
    end
end

function Context:reconnectMenu(parent,ref,car,body,primary)
    local api,actions,p,context,graph=self.api,self.actions,self.p,self.context,self.graph
    local index=self.index
    local at=api.host.sample(ref);if not at then return end
    local visualCar=ref.kind=='vehicle' and car or nil
    if primary==nil then primary=true end
    local _,targetCar=self:component(ref)
    local choices={}
    for _,link in pairs(graph.links) do for _,side in ipairs({'a','b'}) do
        local e=link[side];local opposite=link[side=='a' and 'b' or 'a']
        if e.kind=='ground' and math.floor(e.z)==math.floor(at.z)
            and (e.x-at.x)^2+(e.y-at.y)^2<=64 and distance(p,e)<=144 then
            local connected,hasCar=self:component(opposite)
            if body or opposite.kind=='body' or opposite.kind=='joint' then
                local pos=api.host.sample(opposite);local selected={};local count=0
                for name in pairs(connected) do local node=index.nodes[name]
                    if node and node.kind=='body' then count=count+1;local b=api.host.body(node)
                        if b then selected[#selected+1]=b end
                    end
                end
                if body then selected[#selected+1]=body end
                local available=G.bindCapacity(link,index)
                local needed=pos and G.distance(pos,at)
                local gear=body and link.material=='Base.Rope' and needed and needed>available
                    and needed<=available+G.capacity and self.equipment('Base.Rope')[1] or nil
                local why=self:permission(link) or link.returning and 'IGUI_CVP_LinkReturnPending'
                    or self:bodyReason(body)
                    or body and #(index.byBody[ref.key] or {})>=2 and 'IGUI_CVP_LinkFullBody'
                    or connected[ref.kind..':'..tostring(ref.key)] and 'IGUI_CVP_LinkLoop'
                    or hasCar and (G.tractor(ref) or targetCar) and 'IGUI_CVP_LinkTwoCars'
                    or not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
                    or ref.kind=='horse' and not Horse.enabled() and 'IGUI_CVP_HorseDisabled'
                    or (ref.kind=='horse' and not Horse.stopped(car)) and 'IGUI_CVP_StopHorse'
                    or (ref.kind=='vehicle' and math.abs(car:getCurrentSpeedKmHour())>1) and 'IGUI_CVP_StopVehicle'
                    or not pos and 'IGUI_CVP_Unavailable'
                    or pos and math.floor(pos.z)~=math.floor(at.z) and 'IGUI_CVP_BodyFloor'
                    or needed and needed>available and not gear and 'IGUI_CVP_LinkTooFar'
                choices[#choices+1]={link=link,side=side,bodies=selected,count=count,point=e,why=why,gear=gear,distance=G.distance(e,at),needed=pos and G.distance(pos,at)}
            end
        end
    end end
    table.sort(choices,function(a,b) return a.distance<b.distance or a.distance==b.distance and (a.link.id<b.link.id or a.link.id==b.link.id and a.side<b.side) end)
    local nearest=choices[1]
    for _,row in ipairs(choices) do if not row.why then nearest=row;break end end
    if nearest and #choices>1 then
        local opt=self:option(parent,getText('IGUI_CVP_ReconnectNearest'),nearest.why,function()
            actions:reconnect(p,nearest.link.id,nearest.link.revision,nearest.side,ref,self.finish,nearest.gear)
        end,nearest.bodies,visualCar,{nearest.point,at},primary and not body)
        Menu.hint(opt,getText('IGUI_CVP_ReconnectChoice',tostring(nearest.count),getText(Menu.labels[nearest.link.material]),tostring(math.floor(nearest.distance+.5))))
        if nearest.gear then Menu.hint(opt,getText('IGUI_CVP_ContinueNewRopeHint')) end
        lengthHint(opt,nearest.needed,G.bindCapacity(nearest.link,index)+(nearest.gear and G.capacity or 0))
    end
    local sub=parent
    if #choices>1 then
        local opt=self:option(parent,getText('IGUI_CVP_ReconnectChoose'),nil,nil,nil,visualCar,nil,primary and body~=nil)
        sub=ISContextMenu:getNew(context);context:addSubMenu(opt,sub)
    end
    for i,row in ipairs(choices) do
        local label=#choices==1 and getText(body and 'IGUI_CVP_ReconnectBody' or ref.kind=='horse' and 'IGUI_CVP_ReconnectHorse' or 'IGUI_CVP_ReconnectTrain')
            or getText('IGUI_CVP_ReconnectChoice',tostring(row.count),getText(Menu.labels[row.link.material]),tostring(math.floor(row.distance+.5)))
        local opt=self:option(sub,label,row.why,function()
            actions:reconnect(p,row.link.id,row.link.revision,row.side,ref,self.finish,row.gear)
        end,row.bodies,visualCar,{row.point,at},#choices==1 and primary)
        Menu.hint(opt,getText('IGUI_CVP_ReconnectHint'))
        if row.gear then Menu.hint(opt,getText('IGUI_CVP_ContinueNewRopeHint')) end
        lengthHint(opt,row.needed,G.bindCapacity(row.link,index)+(row.gear and G.capacity or 0))
    end
    return #choices>0
end

function Context:tractorChoices(car,isHorse,ref,tractorPoint,tractorWhy)
    local actions,p,index,scope,point=self.actions,self.p,self.index,self.scope,self.point
    local bodies=self.bodies
    local targets,selected={},{};local ax,ay=tractorPoint.x,tractorPoint.y
    for _,b in ipairs(bodies) do if World.towable(b) and not b:isPlayer() and not index.byBody[b:getModData().CVPBodyKey]
        and not b:getModData().CVPTether and not World.foreignTowed(b) and not b:isBeingGrappled()
        and (b:getX()-ax)^2+(b:getY()-ay)^2<=64 then
        local target=reference(b);target.point=point or (not isHorse and Geometry.nearestPoint(b,car,ref.point)) or 'feet'
        targets[#targets+1]=target;selected[#selected+1]=b
    end end
    local ropes=self.equipment('Base.Rope')
    local continuation=(scope.material~='Base.Rope' or #ropes==0) and actions:continuation(p,ref,targets,true)
    local useRope=scope.material=='Base.Rope' or continuation
    local commonWhy=tractorWhy or not World.towingEnabled() and 'IGUI_CVP_TowingDisabled'
        or #targets==0 and 'IGUI_CVP_NoNearby'
    local ropeWhy=commonWhy or #ropes==0 and not continuation and 'IGUI_CVP_NeedRope'
    local items=self.equipment(scope.material)
    return {targets=targets,bodies=selected,ropes=ropes,useRope=useRope,
        commonWhy=commonWhy,ropeWhy=ropeWhy,items=items,
        why=commonWhy or #items==0 and 'IGUI_CVP_NeedGear'}
end

function Context:tractorMenu(car,isHorse)
    local api,actions,p,context,graph=self.api,self.actions,self.p,self.context,self.graph
    local index,scope,owner,held=self.index,self.scope,self.owner,self.held
    local ref
    if isHorse then ref=Horse.sample(car) else ref=carReference(car,api.host.vehicleKey and api.host.vehicleKey(car),Menu.vehiclePoint(p,car,p,scope.vehicle==car)) end
    if not ref then return end
    local parent=scope.root;local ends={}
    local visualCar=not isHorse and car or nil
    local tractorPoint=api.host.sample(ref)
    local tractorWhy=isHorse and (not Horse.enabled() and 'IGUI_CVP_HorseDisabled' or not Horse.stopped(car) and 'IGUI_CVP_StopHorse')
        or not isHorse and math.abs(car:getCurrentSpeedKmHour())>1 and 'IGUI_CVP_StopVehicle' or nil
    local edges=isHorse and (index.byHorse[ref.key] or {}) or index.byVehicle[ref.key] or index.byVehicle[car:getModData().CVPVehicleKey] or {}
    for _,edge in ipairs(edges) do local why=api.obstacle and api.obstacle(edge.id)
        if why then self:option(parent,getText(why),why,function() end);break end
    end
    for _,edge in ipairs(edges) do local link=graph.links[edge.id]
        if not self:permission(link) then ends[#ends+1]={id=link.id,revision=link.revision,side=edge.side} end
    end
    if held then self:target(parent,ref,getText(isHorse and 'IGUI_CVP_LinkBindHorse' or 'IGUI_CVP_LinkBindCar'),nil,nil,visualCar,true) end
    if not held then
        local methods=Menu.sub(parent,getText('IGUI_CVP_AttachMethods'))
        local choice=self:tractorChoices(car,isHorse,ref,tractorPoint,tractorWhy)
        local targets,selected,ropes=choice.targets,choice.bodies,choice.ropes
        local useRope,commonWhy,ropeWhy=choice.useRope,choice.commonWhy,choice.ropeWhy
        local shared=self:option(methods,getText('IGUI_CVP_SharedMethod'),ropeWhy,
            function() actions:ropeBatch(p,ref,targets,self.finish) end,selected,visualCar,{tractorPoint})
        Menu.hint(shared,getText('IGUI_CVP_SharedRopeHint'))
        local primaryLabel=getText(#edges>0 and 'IGUI_CVP_AddNearestBodies' or 'IGUI_CVP_TieNearestBodies')
        if useRope and #targets>0 then
            local opt=self:option(parent,primaryLabel,ropeWhy,
                function() actions:ropeBatch(p,ref,targets,self.finish,true) end,selected,visualCar,{tractorPoint},true)
            Menu.hint(opt,getText('IGUI_CVP_SeparateTrainsHint'))
        end
        local grouped=self:option(methods,getText('IGUI_CVP_TieSeparateTrains'),ropeWhy or #ropes==0 and not actions:continuation(p,ref,targets,true) and 'IGUI_CVP_NeedRope',
            function() actions:ropeBatch(p,ref,targets,self.finish,true) end,selected,visualCar)
        Menu.hint(grouped,getText('IGUI_CVP_SeparateTrainsHint'))
        local items,why=choice.items,choice.why
        if not useRope and #targets>0 then
            self:option(parent,primaryLabel,why,
                function() actions:batch(p,ref,targets,items,true,self.finish) end,selected,visualCar,{tractorPoint},true)
        end
        self:reconnectMenu(parent,ref,car)
        local preview={};for i=1,math.min(#selected,#items) do preview[i]=selected[i] end
        local quick=self:option(methods,getText('IGUI_CVP_QuickNearby',getText(Menu.labels[scope.material]),tostring(#preview)),why,
            function() actions:batch(p,ref,targets,items,false,self.finish) end,preview,visualCar)
        Menu.highlight(quick,preview,visualCar,true)
        Menu.hint(quick,getText('IGUI_CVP_QuickNearbyHint'))
        local function ordered(items)
            local pool={};for i,e in ipairs(targets) do pool[i]=e end
            local route={};local cursor=api.host.sample(ref)
            local limit=math.min(#pool,#items,World.maxChain())
            while #route<limit do
                local best,dist
                for i,e in ipairs(pool) do local point=api.host.sample(e)
                    local d=point and G.distance(cursor,point)
                    if d and d<=G.capacity and (not dist or d<dist) then best,dist=i,d end
                end
                if not best then break end
                local e=table.remove(pool,best);route[#route+1]=e;cursor=api.host.sample(e)
            end
            return route
        end
        local route=ordered(items);local routeBodies={}
        for _,e in ipairs(route) do routeBodies[#routeBodies+1]=api.host.body(e) end
        local advanced=methods
        local seq=self:option(advanced,getText('IGUI_CVP_QuickSequence',getText(Menu.labels[scope.material]),tostring(#route)),why or #route==0 and 'IGUI_CVP_NoNearby',function()
            actions:batch(p,ref,route,items,true,self.finish)
        end,routeBodies,visualCar)
        Menu.highlight(seq,routeBodies,visualCar,true)
        Menu.hint(seq,getText('IGUI_CVP_QuickSequenceHint'))
        local mixed=self.equipment()
        if #mixed>#items then
            local mixedBodies={};for i=1,math.min(#selected,#mixed) do mixedBodies[i]=selected[i] end
            self:option(advanced,getText('IGUI_CVP_AutoMaterial'),commonWhy,function() actions:batch(p,ref,targets,mixed,false,self.finish) end,mixedBodies,visualCar)
            local mixedRoute=ordered(mixed);local mixedOrdered={}
            for _,e in ipairs(mixedRoute) do mixedOrdered[#mixedOrdered+1]=api.host.body(e) end
            local auto=self:option(advanced,getText('IGUI_CVP_AutoSequence'),commonWhy or #mixedRoute==0 and 'IGUI_CVP_NoNearby',function()
                actions:batch(p,ref,mixedRoute,mixed,true,self.finish)
            end,mixedOrdered,visualCar)
            Menu.highlight(auto,mixedOrdered,visualCar,true)
        end
    end
    if #edges>0 and not isHorse then
        local plan,why=require('CVP_LinkRewire').plan(graph,index,api.host,car,
            {key=owner,allowOthers=not SandboxVars.CorpseProxyLab or SandboxVars.CorpseProxyLab.AllowDetachOthers~=false})
        local selected={};if plan then for _,row in ipairs(plan.rows) do selected[#selected+1]=api.host.body(row.b) end end
        local opt=self:option(parent,getText('IGUI_CVP_Rewire'),why,function() actions:rewire(p,ref,self.finish) end,selected,visualCar)
        if plan then Menu.highlight(opt,selected,visualCar,true);Menu.hint(opt,getText('IGUI_CVP_RewireHint')) end
    end
    if #edges>0 then
        -- A train ends at the car: other roots are independent choices.
        local roots={};for _,edge in ipairs(edges) do roots[#roots+1]=edge end
        table.sort(roots,function(a,b) return a.id<b.id end)
        local trains,allBodies,removeAll={},{},{};local allWhy,releaseWhy
        for _,root in ipairs(roots) do
            releaseWhy=releaseWhy or self:permission(graph.links[root.id])
            local train={root={id=root.id,revision=graph.links[root.id].revision,side=root.side},bodies={},count=0}
            local branch=G.branch(graph,index,root.id,root.side)
            for _,id in ipairs(branch.ids) do allWhy=allWhy or self:permission(graph.links[id]) end
            train.count=#branch.bodies
            for _,ref in ipairs(branch.bodies) do
                local body=api.host.body(ref)
                if body then train.bodies[#train.bodies+1]=body;allBodies[#allBodies+1]=body end
            end
            -- Remove the tail first; cancellation leaves the untouched root connected.
            for i=#branch.ids,1,-1 do local link=graph.links[branch.ids[i]]
                local side=link.a.kind=='body' and 'a' or 'b'
                if G.tractor(link.a) then side='a' elseif G.tractor(link.b) then side='b' end
                removeAll[#removeAll+1]={id=link.id,revision=link.revision,side=side}
            end
            trains[#trains+1]=train
        end
        local choices=parent
        if #trains>1 then
            local opt=self:option(parent,getText('IGUI_CVP_DetachTrainChoose'),nil,nil,allBodies,visualCar,nil,true)
            choices=ISContextMenu:getNew(context);context:addSubMenu(opt,choices)
        end
        local detachKey=#trains>1 and 'IGUI_CVP_DetachCargo'
            or isHorse and 'IGUI_CVP_DetachFromHorse' or 'IGUI_CVP_DetachFromCar'
        local detach=self:option(choices,getText(detachKey),releaseWhy,
            function() actions:release(p,ends,self.finish,false,'cargo') end,allBodies,visualCar,{tractorPoint},#trains==1)
        local detachHint=#trains>1 and 'IGUI_CVP_DetachCargoHint' or 'IGUI_CVP_DetachFromHint'
        Menu.hint(detach,getText(detachHint))
        if #trains>1 then for i,train in ipairs(trains) do
            local label=train.count==0 and getText('IGUI_CVP_EmptyTether',getText(Menu.labels[graph.links[train.root.id].material]))
                or getText('IGUI_CVP_TrainChoice',tostring(i),tostring(train.count))
            self:option(choices,label,self:permission(graph.links[train.root.id]),
                function() actions:release(p,{train.root},self.finish,false,'cargo') end,train.bodies,visualCar)
        end end
        local dismantle=self:option(parent,getText('IGUI_CVP_DismantleAll'),allWhy,
            function() actions:release(p,removeAll,self.finish,true) end,allBodies,visualCar)
        Menu.hint(dismantle,getText('IGUI_CVP_DismantleAllHint'))
    end

end

function Context:fill()
    local objects=self.objects
    local p,context,graph,scope,point=self.p,self.context,self.graph,self.scope,self.point
    local held,heldLink,bodies,cars=self.held,self.heldLink,self.bodies,self.cars
    local picked=Menu.groundSquare(p,context)
    -- Native animal picking includes the model above its ground square.
    local fetch=ISWorldObjectContextMenu and ISWorldObjectContextMenu.fetchVars
    local animals=fetch and fetch.clickedAnimals or {}
    for _,horse in ipairs(Horse.all()) do
        local clicked=false
        for _,object in ipairs(objects) do if object==horse then clicked=true end end
        for _,animal in ipairs(animals) do if animal==horse then clicked=true end end
        if clicked or not scope.bodyClick and not scope.vehicle and picked and horse:getSquare()==picked then
            self.horseClicked=true;self:tractorMenu(horse,true)
        end
    end
    for n,b in ipairs(bodies) do
        if not self.horseClicked and scope:allows(b) and (scope.bodyClick or not scope.vehicle) then self:bodyMenu(b,n) end
    end
    if not scope.bodyClick and not self.horseClicked then
        for _,car in ipairs(cars) do if car==scope.vehicle then self:tractorMenu(car,false) end end
        local ends={}
        local squares={}
        if not scope.vehicle then
            local picked=Menu.groundSquare(p,context)
            if picked then squares[picked]=true
            else for _,o in ipairs(objects) do
                if o.getSquare then local sq=o:getSquare();if sq then squares[sq]=true end end
            end end
        end
        for _,link in pairs(graph.links) do for _,side in ipairs({'a','b'}) do local e=link[side]
            if e.kind=='ground' and math.floor(e.z)==math.floor(p:getZ()) and distance(p,e)<=144
                and squares[getCell():getGridSquare(math.floor(e.x),math.floor(e.y),math.floor(e.z))] then ends[#ends+1]={link=link,side=side,e=e} end
        end end
        table.sort(ends,function(a,b) return a.link.id<b.link.id or a.link.id==b.link.id and a.side<b.side end)
        if #ends==0 and not held and not scope.vehicle and not scope.active and not self.horseClicked then
            context:removeOptionByName(getText('IGUI_CVP_MoreActions'));return
        end
        local choicesMenu
        if #ends>1 and not held then
            local opt=self:option(scope.root,getText('IGUI_CVP_ChooseLoose'),nil,nil,nil,nil,nil,true)
            choicesMenu=ISContextMenu:getNew(context);context:addSubMenu(opt,choicesMenu)
        end
        for i,row in ipairs(ends) do
            local parent=scope.root;local label=getText('IGUI_CVP_LinkLoose',getText(Menu.labels[row.link.material]),tostring(i))
            if #ends>1 then
                local opt;parent,opt=Menu.sub(scope.root,label)
                Menu.highlight(opt,{},nil,false,{row.e})
            end
            self:endMenu(parent,row.link,row.side,#ends==1,choicesMenu,choicesMenu and label)
        end
    end
    if held then self:endMenu(scope.root,heldLink,held.side,true) end
end

function M:fill(p,context,objects)
    local api,actions=self.api,self.actions;local graph=api.graph();local index=G.index(graph)
    if not index then return end
    local all=Batch.equipment(p);local byMaterial,available={},{}
    for _,item in ipairs(all) do
        local kind=item:getFullType()
        byMaterial[kind]=byMaterial[kind] or {};table.insert(byMaterial[kind],item);available[kind]=true
    end
    local function equipment(kind) return kind and (byMaterial[kind] or {}) or all end
    local scope=Menu.begin(p,context,objects,true,available);local owner=p:getUsername()
    local point=Menu.preference('AttachmentPoint',{'auto','feet','neck'},p:getModData().CVPPoint)
    if point~='feet' and point~='neck' then point=nil end
    local held=index.held[owner];local heldLink=held and graph.links[held.id]
    local gear=equipment(scope.material)[1]
    local extension=equipment('Base.Rope')[1]
    local common=api.ready() or (p:getVehicle() or Horse.mounted(p)) and 'IGUI_CVP_LeaveVehicle' or nil
    local bodies={};local all=CVPNetwork.bodies()
    for i=0,all:size()-1 do local b=all:get(i)
        if World.towable(b) and b:getSquare() and b:getStaticMovingObjectIndex()>=0
            and math.floor(b:getZ())==math.floor(p:getZ()) and (b:getX()-p:getX())^2+(b:getY()-p:getY())^2<=144 then bodies[#bodies+1]=b end
    end
    table.sort(bodies,function(a,b)
        local da=(a:getX()-p:getX())^2+(a:getY()-p:getY())^2;local db=(b:getX()-p:getX())^2+(b:getY()-p:getY())^2
        return da<db or da==db and CVPNetwork.id(a)<CVPNetwork.id(b)
    end)
    local cars={};local iterator=getCell():getVehicles():iterator()
    while iterator:hasNext() do local v=iterator:next()
        if v:getSquare() and (not scope.vehicle or v==scope.vehicle) and math.floor(v:getZ())==math.floor(p:getZ())
            and (v:getX()-p:getX())^2+(v:getY()-p:getY())^2<=144 then cars[#cars+1]=v end
    end
    table.sort(cars,function(a,b) return (a:getX()-p:getX())^2+(a:getY()-p:getY())^2<(b:getX()-p:getX())^2+(b:getY()-p:getY())^2 end)
    local view=setmetatable({
        api=api,actions=actions,p=p,context=context,graph=graph,
        index=index,scope=scope,owner=owner,point=point,held=held,
        heldLink=heldLink,gear=gear,extension=extension,common=common,bodies=bodies,
        cars=cars,components={},objects=objects,
        equipment=equipment,
        finish=function(ok,result,why)
            if not ok then print('[CVP action] '..tostring(why));p:Say(getText(message(why))) end
        end,
    },Context)
    view:fill()
end
return M
