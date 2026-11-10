if isServer() then return end
local Ground=require 'CVP_GroundRope'
local Scene=CVPGroundRopeScene or {items={}}
CVPGroundRopeScene=Scene
local materials={['Base.Rope']=true,['Base.HeavyChain']=true,['Base.HeavyChain_Hook']=true}
local function empty(t) for _ in pairs(t) do return false end;return true end
local function remove(entry)
    if CVPFreeRopeScene then for i in ipairs(entry.curves) do CVPFreeRopeScene.remove(entry.id..':'..i) end end
end
function Scene.square(square)
    if not square then return end
    local objects=square:getWorldObjects()
    for i=0,objects:size()-1 do local object=objects:get(i);local item=object:getItem()
        if item and materials[item:getFullType()] and not Scene.items[object] then
            local recipe=item:getModData().CVPGroundRope
            local curves=Ground.points(recipe,square:getX(),square:getY(),square:getZ(),item:getFullType())
            if curves then Scene.items[object]={item=item,square=square,curves=curves,id='ground:'..item:getID()} end
        end
    end
end
function Scene.tick()
    if not CVPFreeRopeScene then return end
    -- One bootstrap for an already loaded world; subsequent discoveries use
    -- chunk loading and the vanilla AddItemToMap packet's OnObjectAdded event.
    if not Scene.scanned then
        Scene.scanned=true
        for id=0,getNumActivePlayers()-1 do local p=getSpecificPlayer(id)
            if p then local x,y,z=math.floor(p:getX()),math.floor(p:getY()),math.floor(p:getZ())
                for dx=-26,26 do for dy=-26,26 do Scene.square(getCell():getGridSquare(x+dx,y+dy,z)) end end
            end
        end
    end
    if empty(Scene.items) then return end
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    local visible=not options or options:getOption('ShowRopes'):getValue()
    for object,entry in pairs(Scene.items) do local sq=entry.square
        if entry.item:getWorldItem()~=object or getCell():getGridSquare(sq:getX(),sq:getY(),sq:getZ())~=sq
            or not sq:getWorldObjects():contains(object) then
            remove(entry);Scene.items[object]=nil
        end
    end
    -- Remove old carriers before drawing: pickup/drop can replace the world
    -- object in one frame while keeping the original inventory item's ID.
    for _,entry in pairs(Scene.items) do
        if not visible then if entry.drawn then remove(entry) end;entry.drawn=false
        elseif not entry.drawn then
            for i,points in ipairs(entry.curves) do CVPFreeRopeScene.update(entry.id..':'..i,points,entry.item:getFullType()~='Base.Rope') end
            entry.drawn=true
        end
    end
end
local function project(x,y,z,id)
    if CVPViewpoint and CVPViewpoint.active() then
        if CVPViewpoint.project(x,y,z) then return CVPViewpoint.screenX(),CVPViewpoint.screenY() end
        return
    end
    local zoom=getCore():getZoom(id)
    return (IsoUtils.XToScreen(x,y,z,0)-IsoCamera.getOffX(id))/zoom+IsoCamera.getScreenLeft(id),
        (IsoUtils.YToScreen(x,y,z,0)-IsoCamera.getOffY(id))/zoom+IsoCamera.getScreenTop(id)
end
local function clearHover()
    if Scene.hover and CVPFreeRopeScene then CVPFreeRopeScene.remove('ground:pickup-marker');Scene.hover=nil end
end
function Scene.draw()
    if empty(Scene.items) then clearHover();return end
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    local highlights=options and options:getOption('ShowHighlights')
    if highlights and not highlights:getValue() then clearHover();return end
    if CVPFeedback then for _ in pairs(CVPFeedback.previews or {}) do clearHover();return end end
    local mx,my=getMouseX(),getMouseY();local best,distance,playerID=nil,64,nil
    for id=0,getNumActivePlayers()-1 do local player=getSpecificPlayer(id)
        if player then for _,entry in pairs(Scene.items) do
            local dx,dy=entry.square:getX()-player:getX(),entry.square:getY()-player:getY()
            if entry.drawn and entry.item:getWorldItem() and entry.square:getZ()==math.floor(player:getZ()) and dx*dx+dy*dy<=30^2
                and (not entry.square.isCanSee or entry.square:isCanSee(id)) then
                for _,curve in ipairs(entry.curves) do
                    local ax,ay
                    for _,p in ipairs(curve) do local bx,by=project(p.x,p.y,p.z/3,id)
                        if ax and bx then
                            local dx,dy=bx-ax,by-ay;local norm=dx*dx+dy*dy
                            local t=norm>0 and math.max(0,math.min(1,((mx-ax)*dx+(my-ay)*dy)/norm)) or 0
                            local d=(mx-ax-t*dx)^2+(my-ay-t*dy)^2
                            if d<distance then best=entry;distance=d;playerID=id end
                        end
                        ax,ay=bx,by
                    end
                end
            end
        end end
    end
    if best then
        local sq=best.square;local x,y=project(sq:getX()+.5,sq:getY()+.5,sq:getZ()+.05,playerID)
        if x then
            if CVPFreeRopeScene and (not Scene.hover or Scene.hover.square~=sq or Scene.hover.player~=playerID) then
                clearHover()
                local points={};for _,corner in ipairs({{.08,.08},{.92,.08},{.92,.92},{.08,.92},{.08,.08}}) do
                    points[#points+1]={x=sq:getX()+corner[1],y=sq:getY()+corner[2],z=sq:getZ()*3+.04}
                end
                CVPFreeRopeScene.update('ground:pickup-marker',points,false);Scene.hover={square=sq,player=playerID}
                if CVPFreeRopeScene.highlight then CVPFreeRopeScene.highlight('ground:pickup-marker',playerID,true) end
            end
            local material=getText(best.item:getFullType()=='Base.Rope' and 'IGUI_CVP_Rope' or 'IGUI_CVP_Chain')
            local text=getText('IGUI_CVP_GroundPickup',material);local tm=getTextManager()
            tm:DrawStringCentre(UIFont.Small,x+1,y+1,text,0,0,0,1)
            tm:DrawStringCentre(UIFont.Small,x,y,text,1,.9,.3,1)
            return
        end
    end
    clearHover()
end
function Scene.reset()
    if CVPFreeRopeScene then CVPFreeRopeScene.remove('ground:pickup-marker') end
    Scene.hover=nil
    for _,entry in pairs(Scene.items) do remove(entry) end
    Scene.items={};Scene.scanned=nil
end
function Scene.added(object) if object then Scene.square(object:getSquare()) end end
for name,fn in pairs({OnTick=Scene.tick,LoadGridsquare=Scene.square,OnObjectAdded=Scene.added,
    OnPostUIDraw=Scene.draw,OnGameStart=Scene.reset}) do
    if Events[name] then
        Scene.handlers=Scene.handlers or {}
        if Scene.handlers[name] then Events[name].Remove(Scene.handlers[name]) end
        Scene.handlers[name]=fn;Events[name].Add(fn)
    end
end
return Scene
