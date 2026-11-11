-- Presentation only: keep the original item in inventory until both ends finish.
local Action=require 'CVP_AttachAction'
local Geometry=require 'CVP_Geometry'
require 'Vehicles/TimedActions/ISPathFindAction'
local Feedback=require 'CVP_Feedback'
local Tie={}
function Tie.start(p,b,v,gear,point,check,commit,after,mode)
    local ax,ay,az=Geometry.anchor(v)
    local bx,by=b:getX(),b:getY()
    local token=Feedback.active[p]
    local ended=false
    local function finish(ok,id,reason)
        if ended then return end;ended=true
        if after then after(ok,id,reason) end
    end
    local function valid()
        if token and token.cancelled then return 'IGUI_CVP_CancelledQueue' end
        if ended or p:isDead() or p:getVehicle() or not v:getSquare() or not b:getSquare()
            or b:getStaticMovingObjectIndex()<0 or math.abs(v:getCurrentSpeedKmHour())>1 then return 'changed' end
        local x,y,z=Geometry.anchor(v)
        if z~=az or (x-ax)^2+(y-ay)^2>.04 or (b:getX()-bx)^2+(b:getY()-by)^2>.04 then return 'moved' end
        return check(p,b,v,gear,true)
    end
    if valid() then finish(false);return end
    local function stage(endpoint,nextStep)
        if valid() then finish(false);return end
        local path
        if endpoint=='vehicle' then
            -- Native pathfinding chooses a reachable point outside vehicle collision.
            local locations={}
            for i=0,7 do local a=i*math.pi/4
                locations[#locations+1]=ax+math.cos(a)*.85
                locations[#locations+1]=ay+math.sin(a)*.85
                locations[#locations+1]=az
            end
            path=ISPathFindAction:pathToNearest(p,locations)
        else
            local z=b:getZ()
            path=ISPathFindAction:pathToNearest(p,{bx,by,z,bx+.65,by,z,bx-.65,by,z,bx,by+.65,z,bx,by-.65,z})
        end
        local completed=false
        local stop=path.stop
        path.stop=function(self) stop(self);if not completed then finish(false) end end
        path.forceCancel=function() if not completed then finish(false) end end
        path:setOnFail(function() finish(false,nil,'IGUI_CVP_NoPath') end)
        local function arrived()
            if completed or ended then return end;completed=true
            if valid() then finish(false);return end
            ISTimedActionQueue.add(Action:new(p,b,v,gear,valid,function() end,false,point,function(ok)
                if not ok or valid() then finish(false);return end
                nextStep()
            end,endpoint))
        end
        path:setOnComplete(arrived)
        if endpoint=='vehicle' and Geometry.nearAnchor(p,v) then arrived();return end
        ISTimedActionQueue.add(path)
    end
    local function complete(endpoint)
        if valid() then finish(false);return end
        -- In MP this callback completes only when the authoritative reply arrives.
        commit(endpoint,finish)
    end
    if mode=='prepareVehicle' then stage('vehicle',function() finish(true) end)
    elseif mode=='vehiclePrepared' then stage('body',function() complete('body') end)
    else stage('body',function() stage('vehicle',function() complete('vehicle') end) end) end
    return true
end
-- Two corpse endpoints: visit the existing tail first, then the new body.
function Tie.chain(p,b,source,v,gear,sourcePoint,point,check,commit,after)
    local bx,by,sx,sy=b:getX(),b:getY(),source:getX(),source:getY()
    local token=Feedback.active[p]
    local ended=false
    local function finish(ok,id,reason)
        if ended then return end;ended=true
        if after then after(ok,id,reason) end
    end
    local function valid()
        if token and token.cancelled then return 'IGUI_CVP_CancelledQueue' end
        if ended or p:isDead() or p:getVehicle() or not v:getSquare()
            or math.abs(v:getCurrentSpeedKmHour())>1 or not b:getSquare() or not source:getSquare()
            or b:getStaticMovingObjectIndex()<0 or source:getStaticMovingObjectIndex()<0
            or (b:getX()-bx)^2+(b:getY()-by)^2>.04
            or (source:getX()-sx)^2+(source:getY()-sy)^2>.04 then return 'changed' end
        return check()
    end
    local function stage(body,at,nextStep)
        if valid() then finish(false);return end
        local x,y,z=body:getX(),body:getY(),body:getZ()
        local path=ISPathFindAction:pathToNearest(p,{x,y,z,x+.65,y,z,x-.65,y,z,x,y+.65,z,x,y-.65,z})
        local arrived=false;local stop=path.stop
        path.stop=function(self) stop(self);if not arrived then finish(false) end end
        path.forceCancel=function() finish(false) end
        path:setOnFail(function() finish(false,nil,'IGUI_CVP_NoPath') end)
        path:setOnComplete(function()
            if arrived then return end
            if valid() then finish(false);return end
            arrived=true
            ISTimedActionQueue.add(Action:new(p,body,v,gear,valid,function() end,false,at,function(ok)
                if not ok or valid() then finish(false);return end
                nextStep()
            end))
        end)
        ISTimedActionQueue.add(path)
    end
    stage(source,sourcePoint,function()
        stage(b,point,function() if valid() then finish(false) else commit(finish) end end)
    end)
    return true
end
return Tie
