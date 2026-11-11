local Tie=require 'CVP_TieSequence'
local Feedback=require 'CVP_Feedback'
local World=require 'CVP_World'
local Geometry=require 'CVP_Geometry'
local A={}
function A.start(p,v,rows,check,commit)
    local token=Feedback.begin(p,#rows,'rewire')
    local ax,ay,az=Geometry.anchor(v)
    local captured={}
    for i,r in ipairs(rows) do captured[i]={x=r.body:getX(),y=r.body:getY(),md=World.data(r.body)} end
    local function valid()
        if p:isDead() or p:getVehicle() then return 'IGUI_CVP_LeaveVehicle' end
        if token.cancelled then return 'IGUI_CVP_CancelledQueue' end
        local x,y,z=Geometry.anchor(v)
        if math.abs(v:getCurrentSpeedKmHour())>1 or z~=az or (x-ax)^2+(y-ay)^2>.04 then return 'IGUI_CVP_StopVehicle' end
        for i,r in ipairs(rows) do local c=captured[i]
            local current=World.data(r.body)
            if not current or not c.md or current.connection.id~=c.md.connection.id or (r.body:getX()-c.x)^2+(r.body:getY()-c.y)^2>.04 then return 'IGUI_CVP_LetGo' end
        end
        return check()
    end
    local function stop(reason) Feedback.finish(token,reason or 'IGUI_CVP_QueueStopped') end
    local step
    step=function(i)
        local reason=valid();if reason then stop(reason);return end
        if i>#rows then
            commit(function(ok,reason) Feedback.finish(token,not ok and (reason or 'IGUI_CVP_QueueStopped') or nil) end)
            return
        end
        local r=rows[i];local gear=World.gear(r.body,captured[i].md)
        -- MP clients animate from the connection descriptor; equipment remains
        -- exclusively in the authoritative store and is checked by the server.
        if not gear and not isClient() then stop('IGUI_CVP_NeedGear');return end
        local function done(ok,id,why)
            if not ok then stop(why);return end
            Feedback.progress(token,i,'IGUI_CVP_RewirePreparing');step(i+1)
        end
        if i==1 then
            Tie.start(p,r.body,v,gear,r.point,valid,function(_,finish) finish(true) end,function(ok)
                if not ok then stop();return end
                Tie.start(p,r.body,v,gear,r.point,valid,function(_,finish) finish(true) end,done,'vehiclePrepared')
            end,'prepareVehicle')
        else Tie.chain(p,r.body,rows[i-1].body,v,gear,rows[i-1].point,r.point,valid,function(finish) finish(true) end,done) end
    end
    step(1)
end
return A
