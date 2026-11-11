-- Shared SP/MP context routing. Actions retain their existing validation/queues.
local World=require 'CVP_World'
local Feedback=require 'CVP_Feedback'
local M={}
M.types={'Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'}
M.labels={['Base.Rope']='IGUI_CVP_Rope',['Base.HeavyChain']='IGUI_CVP_Chain',['Base.HeavyChain_Hook']='IGUI_CVP_HookChain'}
function M.preference(id,values,fallback)
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    local option=options and options:getOption(id)
    return option and values[option:getValue()] or fallback
end
function M.material(p,strict,available)
    local found,seen={},{}
    local function scan(inv)
        if seen[inv] then return end;seen[inv]=true
        local items=inv:getItems()
        for i=0,items:size()-1 do local item=items:get(i);local t=item:getFullType()
            if M.labels[t] and p:getPrimaryHandItem()~=item and p:getSecondaryHandItem()~=item then found[t]=true end
            if instanceof(item,'InventoryContainer') then scan(item:getInventory()) end
        end
    end
    if available then found=available else scan(p:getInventory()) end
    local preferred=M.preference('PreferredMaterial',M.types,p:getModData().CVPMaterial)
    if strict and M.labels[preferred] then return preferred,found end
    if found[preferred] then return preferred,found end
    for _,t in ipairs(M.types) do if found[t] then return t,found end end
    return M.labels[preferred] and preferred or 'Base.Rope',found
end
function M.sub(context,label,body)
    local opt=context:addOption(label,nil,nil)
    local sub=ISContextMenu:getNew(context)
    context:addSubMenu(opt,sub)
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    if body and (not options or options:getOption('ShowHighlights'):getValue()) then ISWorldObjectContextMenu.initWorldItemHighlightOption(opt,body) end
    return sub,opt
end
function M.lazySub(context,label,build)
    local sub,opt=M.sub(context,label)
    local built=false
    local visible,clear=sub.setVisible,sub.clear
    local function restore() sub.setVisible=visible;sub.clear=clear end
    local function populate()
        if built then return end
        build(sub);built=true;restore()
    end
    opt.onHighlightParams={}
    opt.onHighlight=function(_,_,enabled) if enabled then populate() end end
    -- Also covers opening a joypad submenu before its first highlight frame.
    if visible then sub.setVisible=function(self,value) if value then populate() end;return visible(self,value) end end
    -- Native context menus are pooled. An unopened submenu must not retain its
    -- builder when clear() returns it to vanilla or another mod.
    if clear then sub.clear=function(self,...) built=true;restore();return clear(self,...) end end
    return sub
end
function M.reason(opt,reason)
    opt.notAvailable=reason~=nil
    if reason then
        local tip=ISWorldObjectContextMenu.addToolTip()
        tip.description=reason;opt.toolTip=tip
    end
    return opt
end
function M.hint(option,text)
    if option.notAvailable then return end
    local tip=ISWorldObjectContextMenu.addToolTip()
    tip.description=text;option.toolTip=tip
end
function M.highlight(option,bodies,vehicle,ordered,endpoints)
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    if options and not options:getOption('ShowHighlights'):getValue() then return end
    local rows={}
    for _,body in ipairs(bodies) do
        local row={}
        ISWorldObjectContextMenu.initWorldItemHighlightOption(row,body)
        rows[#rows+1]=row
    end
    option.onHighlightParams={}
    option.onHighlight=function(opt,menu,enabled)
        Feedback.preview(opt,menu,enabled,bodies,vehicle,ordered,endpoints)
        for _,row in ipairs(rows) do
            if row.onHighlight then row.onHighlight(row,menu,enabled,unpack(row.onHighlightParams)) end
        end
    end
end
-- A free end is rendered geometry, not an IsoObject in the context hit list.
function M.groundSquare(p,context)
    if JoypadState and JoypadState.players[p:getPlayerNum()+1] then return end
    local z=math.floor(p:getZ());local x,y
    local mouse=Viewpoint and Viewpoint.Mouse
    if mouse and mouse.worldX and mouse.worldY then
        local ok,wx,wy=pcall(function() return mouse.worldX(),mouse.worldY() end)
        if not ok then return end
        x,y=wx,wy
    end
    if x==nil and y==nil and screenToIsoX and screenToIsoY then
        local mx=getMouseX and getMouseX() or context.x
        local my=getMouseY and getMouseY() or context.y
        if mx==nil or my==nil then return end
        x=screenToIsoX(p:getPlayerNum(),mx,my,z)
        y=screenToIsoY(p:getPlayerNum(),mx,my,z)
    end
    if type(x)~='number' or type(y)~='number' or x~=x or y~=y
        or math.abs(x)>10000000 or math.abs(y)>10000000 then return end
    return getCell():getGridSquare(math.floor(x),math.floor(y),z)
end
-- Capture the chosen end when opening the menu, before walking changes position.
function M.vehiclePoint(p,car,where,clicked)
    local geometry=require 'CVP_Geometry'
    local rx,ry,rz=geometry.anchor(car,'hitch')
    local fx,fy,fz=geometry.anchor(car,'front')
    local x,y=where:getX(),where:getY()
    if clicked and not (JoypadState and JoypadState.players[p:getPlayerNum()+1]) then
        local mx,my=getMouseX(),getMouseY()
        if CVPViewpoint and CVPViewpoint.active and CVPViewpoint.active() then
            if CVPViewpoint.project(rx,ry,rz+.15) then
                local sx,sy=CVPViewpoint.screenX(),CVPViewpoint.screenY()
                if CVPViewpoint.project(fx,fy,fz+.15) then
                    local tx,ty=CVPViewpoint.screenX(),CVPViewpoint.screenY()
                    return (mx-tx)^2+(my-ty)^2<(mx-sx)^2+(my-sy)^2 and 'front' or 'hitch'
                end
            end
        elseif screenToIsoX and screenToIsoY then
            x=screenToIsoX(p:getPlayerNum(),mx,my,car:getZ())
            y=screenToIsoY(p:getPlayerNum(),mx,my,car:getZ())
        end
    end
    return (x-fx)^2+(y-fy)^2<(x-rx)^2+(y-ry)^2 and 'front' or 'hitch'
end
local function insideFace(face,x,y)
    local sign
    for i=1,4 do local a,b=face[i],face[i%4+1]
        local cross=(b.x-a.x)*(y-a.y)-(b.y-a.y)*(x-a.x)
        if math.abs(cross)>.001 then
            local current=cross>0
            if sign~=nil and sign~=current then return false end
            sign=current
        end
    end
    return sign~=nil
end
function M.vehicleScreenHit(car,x,y)
    if not CVPViewpoint or not CVPViewpoint.active or not CVPViewpoint.active() then return false end
    x,y=x or getMouseX(),y or getMouseY()
    local ext=car:getScript():getExtents();local base,top={},{}
    local out=Vector3f.new()
    for i,corner in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}}) do
        car:getWorldPos(corner[1]*ext:x()/2,0,corner[2]*ext:z()/2,out)
        for level,points in ipairs({base,top}) do
            local z=car:getZ()+(level-1)*ext:y()/2.44949
            if not CVPViewpoint.project(out:x(),out:y(),z) then return false end
            points[i]={x=CVPViewpoint.screenX(),y=CVPViewpoint.screenY()}
        end
    end
    if insideFace(top,x,y) then return true end
    for i=1,4 do local j=i%4+1
        if insideFace({base[i],base[j],top[j],top[i]},x,y) then return true end
    end
    return false
end
function M.viewpointVehicle(p)
    local mouse=Viewpoint and Viewpoint.Mouse
    if not mouse or not mouse.worldX or not mouse.worldY then return end
    local x,y=mouse.worldX(),mouse.worldY()
    if type(x)~='number' or type(y)~='number' or x~=x or y~=y then return end
    local vehicles=getCell():getVehicles():iterator();local found
    while vehicles:hasNext() do local car=vehicles:next()
        if car:getSquare() and math.floor(car:getZ())==math.floor(p:getZ())
            and (car:getX()-p:getX())^2+(car:getY()-p:getY())^2<=144
            and (car:getPoly():containsPoint(x,y) or M.vehicleScreenHit(car)) then
            -- Overlapping vehicles are ambiguous; do not choose by list order.
            if found then return end
            found=car
        end
    end
    return found
end
function M.begin(p,context,objects,focused,available)
    local v=p:getVehicle()
    local clicked={};local any=false;local count=0
    local joypad=JoypadState and JoypadState.players[p:getPlayerNum()+1]
    if not v and joypad then
        v=ISVehicleMenu.getVehicleToInteractWith(p)
    elseif not v and IsoObjectPicker then
        local picker=IsoObjectPicker.Instance
        -- Viewpoint patches these same native entry points for its camera ray.
        -- Corpse picking applies zoom internally; vehicle picking takes scaled coordinates.
        local body=picker.PickCorpse and picker:PickCorpse(getMouseX(),getMouseY())
        if World.towable(body) then clicked[body]=true;any=true;count=1
        else v=picker:PickVehicle(getMouseXScaled(),getMouseYScaled()) or M.viewpointVehicle(p) end
    end
    if not v and not any then
        -- Explicit corpse objects are valid fallback targets; a tile is not a hit
        -- on every corpse lying on it. Ground clicks use the nearby submenu.
        for _,o in ipairs(objects) do
            if World.towable(o) and not clicked[o] then clicked[o]=true;any=true;count=count+1 end
        end
    end
    local root=context
    if focused or not v and not any then root=M.sub(context,getText(focused and 'IGUI_CVP_MoreActions' or 'IGUI_CVP_TowingMenu')) end
    if Feedback.active[p] then
        local opt=root:addOption(getText('IGUI_CVP_CancelQueue'),nil,function() Feedback.cancel(p) end)
        M.hint(opt,getText('IGUI_CVP_QueueCancelHint'))
    end
    local material,available=M.material(p,false,available)
    local scope={material=material,available=available,vehicle=v,clicked=clicked,bodyClick=any,bodyCount=count,root=root,vehicles={},bodies={},active=Feedback.active[p]}
    local best=36
    if not focused and not v and not any then
        local cars=getCell():getVehicles():iterator()
        while cars:hasNext() do local car=cars:next()
            local d=(car:getX()-p:getX())^2+(car:getY()-p:getY())^2
            if car:getSquare() and math.floor(car:getZ())==math.floor(p:getZ()) and d<=best then scope.primary=car;best=d end
        end
    end
    function scope:allows(b) return (not focused and not self.bodyClick) or self.clicked[b]==true end
    function scope:vehicleMenu(car)
        if self.vehicle or self.primary==car then return self.root end
        if not self.vehicles[car] then
            local name=car:getScript():getName()
            name=(getTextOrNull and getTextOrNull('IGUI_VehicleName'..name)) or name
            self.vehicles[car]=M.sub(self.root,name)
        end
        return self.vehicles[car]
    end
    function scope:bodyMenu(b,index)
        if self.bodyClick and self.bodyCount==1 then return self.root end
        if not self.bodies[b] then
            local root=self.root
            if self.vehicle then
                self.selected=self.selected or M.sub(root,getText('IGUI_CVP_SelectedBodyMenu'))
                root=self.selected
            end
            self.bodies[b]=M.sub(root,getText('IGUI_CVP_BodyMenu',tostring(index)),b)
        end
        return self.bodies[b]
    end
    return scope
end
return M
