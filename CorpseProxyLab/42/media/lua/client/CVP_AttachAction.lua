require 'TimedActions/ISBaseTimedAction'
require 'TimedActions/ISTimedActionQueue'
local Action=ISBaseTimedAction:derive('CVPAttachAction')
local Geometry=require 'CVP_Geometry'

function Action:invalidReason()
    if self.done then return self.cancelled and 'IGUI_CVP_CancelledQueue' or nil end
    if self.cancelled then return 'IGUI_CVP_CancelledQueue' end
    local p,b=self.character,self.body
    if self.resolveBody and (not b or not b:getSquare() or b:getStaticMovingObjectIndex()<0) then
        local current=self.resolveBody()
        if current then b=current;self.body=current end
    end
    local why,checkedPoint=self.check(p,b,self.vehicle,self.gear);if why then return why end
    if self.endpoint=='vehicle' then
        if not Geometry.nearAnchor(p,self.vehicle,self.point) then return 'IGUI_CVP_NoPath' end
        return
    end
    local e,square
    if self.sample then
        -- Graph actions validate the same attachment and square as the authority.
        local reason;e=checkedPoint
        if not e then e,reason=self.sample() end
        if not e then return reason or 'IGUI_CVP_Unavailable' end
        square=e and getCell():getGridSquare(math.floor(e.x),math.floor(e.y),math.floor(e.z))
    else
        if not b or b:getStaticMovingObjectIndex()<0 then return 'IGUI_CVP_Unavailable' end
        e={x=b:getX(),y=b:getY(),z=b:getZ()};square=b:getSquare()
    end
    if not e or not square or not p:getSquare() then return 'IGUI_CVP_Unavailable' end
    if math.floor(p:getZ())~=math.floor(e.z) then return 'IGUI_CVP_BodyFloor' end
    if not p:getSquare():canReachTo(square) then return 'IGUI_CVP_NoPath' end
    local limit=(self.sample or self.endpoint=='ground') and 2.25 or 9
    if (p:getX()-e.x)^2+(p:getY()-e.y)^2>limit then return 'IGUI_CVP_ActionTooFar' end
end
function Action:isValid()
    self.invalidWhy=self:invalidReason()
    return self.invalidWhy==nil
end
function Action:faceAttachment()
    if self.endpoint=='ground' then
        local e=self.sample();if e then self.character:faceLocationF(e.x,e.y) end;return
    end
    if self.endpoint=='vehicle' then
        local x,y=Geometry.anchor(self.vehicle,self.point);self.character:faceLocationF(x,y);return
    end
    local method=self.point=='neck' and self.body.getGrabHeadPosition or self.body.getGrabLegsPosition
    if self.character.faceLocationF and method and Vector2f then
        self.footPoint=self.footPoint or Vector2f.new()
        local point=method(self.body,self.footPoint)
        self.character:faceLocationF(point:x(),point:y())
    else self.character:faceThisObject(self.body) end
end
function Action:waitToStart()
    self:faceAttachment()
    return self.character:shouldBeTurning()
end
function Action:update()
    self:faceAttachment()
end
function Action:start()
    self:setActionAnim(self.endpoint=='vehicle' and 'VehicleTrailer' or 'Loot')
    if not self.gear and self.visualModel then self:setOverrideHandModelsString(self.visualModel,nil)
    else self:setOverrideHandModels(self.gear,nil) end
    if self.endpoint~='vehicle' then
        self:setAnimVariable('LootPosition','Low')
        self.character:reportEvent('EventLootItem')
    end
end
function Action:notifyAfter(ok,why)
    if self.after and not self.notified then self.notified=true;self.after(ok,why) end
end
function Action:stop()
    local why=self.invalidWhy or self:invalidReason() or 'IGUI_CVP_CancelledQueue'
    self.cancelled=true
    ISBaseTimedAction.stop(self)
    self:notifyAfter(false,why)
end
function Action:forceCancel()
    local why=self.invalidWhy or self:invalidReason() or 'IGUI_CVP_CancelledQueue'
    self.cancelled=true;self:notifyAfter(false,why)
end
function Action:commitOnce()
    if self.done then return false end
    if not self:isValid() then return false end
    self.done=true
    self.commit(self.character,self.body,self.vehicle,self.gear)
    return true
end
-- Build 42 treats a class-level complete() as a native server timed action.
-- Our closures are local presentation; MP uses the existing validated CVP RPC.
-- Without complete(), LuaTimedActionNew selects custom remote synchronization.
if not isClient() then Action.complete=Action.commitOnce end
function Action:perform()
    -- Client-only presentation action. MP commits through our validated RPC,
    -- never by editing local containers; SP complete() remains exactly-once.
    self:commitOnce()
    ISBaseTimedAction.perform(self)
    self:notifyAfter(self.done==true,not self.done and (self.invalidWhy or 'IGUI_CVP_Unavailable') or nil)
end
function Action:new(p,b,v,gear,check,commit,removing,point,after,endpoint,sample)
    local o=ISBaseTimedAction.new(self,p)
    o.body=b;o.vehicle=v;o.gear=gear;o.check=check;o.commit=commit
    o.removing=removing==true
    o.point=point or 'feet';o.after=after;o.endpoint=endpoint or 'body';o.sample=sample
    o.stopOnWalk=true;o.stopOnRun=true;o.maxTime=o.removing and 60 or 100
    return o
end
return Action
