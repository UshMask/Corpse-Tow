-- UI-only state: never moves bodies, transfers equipment or changes authority.
local Geometry=require 'CVP_Geometry'
local F=CVPFeedback or {active={},last={},previews={}}
CVPFeedback=F
F.wear=F.wear or {}
function F.wearNotice(data)
    if type(data)~='table' or (data.stage~=1 and data.stage~=2)
        or type(data.x)~='number' or type(data.y)~='number' or type(data.z)~='number' then return end
    for id=0,getNumActivePlayers()-1 do local p=getSpecificPlayer(id)
        if p and math.floor(p:getZ())==math.floor(data.z) and (p:getX()-data.x)^2+(p:getY()-data.y)^2<=35^2 then
            local old=F.wear[id];local now=getTimestampMs()
            local count=old and old.stage==data.stage and now<old.expires and old.count+1 or 1
            F.wear[id]={stage=data.stage,count=count,expires=now+4000}
        end
    end
end
if Events.OnServerCommand then
    if F.wearHandler then Events.OnServerCommand.Remove(F.wearHandler) end
    F.wearHandler=function(module,name,data)
        if module=='CVP' and name=='wearNotice' then F.wearNotice(data) end
    end
    Events.OnServerCommand.Add(F.wearHandler)
end
function F.begin(p,total,kind)
    local old=F.active[p];if old then old.cancelled=true end
    local token={player=p,total=total,done=0,kind=kind or 'attach'}
    F.active[p]=token;return token
end
function F.progress(token,done,phase)
    if not token or token.cancelled then return end
    token.done=done;token.phase=phase
end
function F.finish(token,reason)
    if not token or token.finished then return end
    token.finished=true;token.reason=reason;token.expires=getTimestampMs()+6000
    if F.active[token.player]==token then F.active[token.player]=nil end
    F.last[token.player]=token
end
function F.cancel(p)
    local token=F.active[p];if not token then return end
    token.cancelled=true
    F.finish(token,'IGUI_CVP_CancelledQueue')
    ISTimedActionQueue.clear(p)
end
local function highlight(preview,id,enabled)
    local link=preview and preview.endpoints and preview.endpoints.linkId
    if link and CVPFreeRopeScene and CVPFreeRopeScene.highlight then
        CVPFreeRopeScene.highlight(link,id,enabled)
        CVPFreeRopeScene.highlight(preview.endpoints.bindingA or 'binding:'..link..':a',id,enabled)
        CVPFreeRopeScene.highlight(preview.endpoints.bindingB or 'binding:'..link..':b',id,enabled)
    end
end
function F.preview(option,menu,enabled,bodies,vehicle,ordered,endpoints)
    local id=menu.player or 0
    if enabled then
        highlight(F.previews[id],id,false)
        F.previews[id]={option=option,bodies=bodies,vehicle=vehicle,ordered=ordered,menu=menu,endpoints=endpoints}
        highlight(F.previews[id],id,true)
    elseif F.previews[id] and F.previews[id].option==option then highlight(F.previews[id],id,false);F.previews[id]=nil end
end
local function project(x,y,z,id)
    local cell=getCell and getCell()
    local square=cell and cell:getGridSquare(math.floor(x),math.floor(y),math.floor(z))
    if square and square.isCanSee and not square:isCanSee(id) then return end
    if CVPViewpoint and CVPViewpoint.active() then
        if CVPViewpoint.project(x,y,z) then return CVPViewpoint.screenX(),CVPViewpoint.screenY() end
        return
    end
    local zoom=getCore():getZoom(id)
    return (IsoUtils.XToScreen(x,y,z,0)-IsoCamera.getOffX(id))/zoom+IsoCamera.getScreenLeft(id),
        (IsoUtils.YToScreen(x,y,z,0)-IsoCamera.getOffY(id))/zoom+IsoCamera.getScreenTop(id)
end
local function empty(t) for _ in pairs(t) do return false end;return true end
local function showSuccess()
    local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
    local mode=options and options:getOption('Notifications')
    return not mode or mode:getValue()~=2
end
function F.draw()
    if empty(F.active) and empty(F.last) and empty(F.previews) and empty(F.wear) then return end
    local now=getTimestampMs()
    for p,token in pairs(F.last) do if token.finished and now>=token.expires then F.last[p]=nil end end
    for id,notice in pairs(F.wear) do if now>=notice.expires then F.wear[id]=nil end end
    if empty(F.active) and empty(F.last) and empty(F.previews) and empty(F.wear) then return end
    local tm=getTextManager();local occupied={}
    local function label(id,x,y,text)
        local left,top=IsoCamera.getScreenLeft(id),IsoCamera.getScreenTop(id)
        if not x or x<left or y<top or x>left+IsoCamera.getScreenWidth(id) or y>top+IsoCamera.getScreenHeight(id) then return end
        local width=tm.MeasureStringX and tm:MeasureStringX(UIFont.Small,text) or #text*6
        occupied[id]=occupied[id] or {}
        for _,box in ipairs(occupied[id]) do
            if math.abs(y-box.y)<18 and math.abs(x-box.x)<(width+box.width)/2+5 then return end
        end
        occupied[id][#occupied[id]+1]={x=x,y=y,width=width}
        tm:DrawStringCentre(UIFont.Small,x+1,y+1,text,0,0,0,1)
        tm:DrawStringCentre(UIFont.Small,x,y,text,1,.9,.3,1)
    end
    for id,preview in pairs(F.previews) do
        local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
        local setting=options and options:getOption('ShowHighlights')
        if setting and not setting:getValue() or preview.menu.isVisible and not preview.menu:isVisible() then
            highlight(preview,id,false);F.previews[id]=nil
        else
            local v=preview.vehicle
            local explicit=false;for _,e in ipairs(preview.endpoints or {}) do if e.kind=='vehicle' then explicit=true end end
            if v and v:getSquare() and not explicit then local x,y,z=Geometry.anchor(v);x,y=project(x,y,z+.15,id);label(id,x,y,getText('IGUI_CVP_HitchMarker')) end
            for _,e in ipairs(preview.endpoints or {}) do
                local x,y=project(e.x,e.y,e.z,id);label(id,x,y,getText(e.kind=='vehicle' and (e.point=='front' and 'IGUI_CVP_FrontMarker' or 'IGUI_CVP_RearMarker') or 'IGUI_CVP_LinkEndMarker'))
            end
            if preview.ordered then for n,b in ipairs(preview.bodies) do
                if b:getSquare() then local x,y=project(b:getX(),b:getY(),b:getZ(),id);label(id,x,y,tostring(n)) end
            end end
        end
    end
    for id=0,getNumActivePlayers()-1 do local p=getSpecificPlayer(id)
        local notice=F.wear[id]
        if notice and getTimestampMs()<notice.expires then
            label(id,IsoCamera.getScreenLeft(id)+IsoCamera.getScreenWidth(id)/2,IsoCamera.getScreenTop(id)+60,
                getText(notice.stage==1 and 'IGUI_CVP_WearSkeleton' or 'IGUI_CVP_WearGone',tostring(notice.count)))
        end
        local token=F.active[p] or F.last[p]
        if token and token.finished and not token.reason and token.endpoint and now<token.expires-4800 and showSuccess() then
            local options=PZAPI and PZAPI.ModOptions and PZAPI.ModOptions:getOptions('CorpseProxyLab')
            local setting=options and options:getOption('ShowHighlights')
            if not setting or setting:getValue() then local e=token.endpoint;local x,y=project(e.x,e.y,e.z,id);label(id,x,y,'○') end
        end
        if token and (not token.finished or getTimestampMs()<token.expires)
            and (not token.finished or token.reason or showSuccess()) then
            local keys={detach='IGUI_CVP_ReleaseProgress',cargo='IGUI_CVP_CargoProgress',collect='IGUI_CVP_CollectProgress',reconnect='IGUI_CVP_ReconnectProgress',bodies='IGUI_CVP_BodiesProgress',rewire='IGUI_CVP_RewireProgress'}
            local text=getText(keys[token.kind] or 'IGUI_CVP_TieProgress',tostring(token.done),tostring(token.total))
            if token.finished and not token.reason and token.notice then text=getText(token.notice) end
            if token.phase and not token.finished then text=text..' — '..getText(token.phase) end
            if not token.finished then text=text..' — '..getText('IGUI_CVP_RightClickStops') end
            if token.reason then text=text..' — '..getText(token.reason) end
            label(id,IsoCamera.getScreenLeft(id)+IsoCamera.getScreenWidth(id)/2,IsoCamera.getScreenTop(id)+80,text)
        end
    end
end
if Events.OnGameStart then
    if F.resetHandler then Events.OnGameStart.Remove(F.resetHandler) end
    F.resetHandler=function()
        for id,preview in pairs(F.previews) do highlight(preview,id,false) end
        F.active={};F.last={};F.previews={};F.wear={}
    end
    Events.OnGameStart.Add(F.resetHandler)
end
if Events.OnPostUIDraw then
    if F.drawHandler then Events.OnPostUIDraw.Remove(F.drawHandler) end
    F.drawFailure=nil
    F.drawHandler=function()
        if F.drawFailure then return end
        local ok,err=pcall(F.draw)
        if not ok then
            for id,preview in pairs(F.previews) do highlight(preview,id,false) end
            F.drawFailure=tostring(err);print('[CVP] Action hints disabled: '..F.drawFailure)
        end
    end
    Events.OnPostUIDraw.Add(F.drawHandler)
end
return F
