-- Shared bounded authority/vehicle-owner clock. All intervals are seconds.
local C={}
function C.advance(self,dt,now,clock)
    local incoming=math.max(0,dt)
    if not clock and self.motionWallTime then incoming=math.max(0,(now-self.motionWallTime)/1000) end
    if self.motionWallTime and now<self.motionWallTime then
        self.motionElapsed=0;self.motionCorrection=true;incoming=0
    end
    self.motionWallTime=now
    if clock and self.motionPhysicsTime then
        incoming=clock>=self.motionPhysicsTime and (clock-self.motionPhysicsTime)/1000 or 0
        if clock<self.motionPhysicsTime then self.motionElapsed=0;self.motionCorrection=true end
    end
    self.motionPhysicsTime=clock or nil
    self.lastPhysicsElapsed=incoming
    self.peakPhysicsElapsed=math.max(self.peakPhysicsElapsed or 0,incoming)
    if incoming>.1 then self.longPhysicsIntervals=(self.longPhysicsIntervals or 0)+1 end
    local pending=(self.motionElapsed or 0)+incoming
    if pending>.5 then
        self.clippedPhysicsIntervals=(self.clippedPhysicsIntervals or 0)+1
        self.motionCorrection=true;pending=.5
    end
    local steps=math.min(50,math.floor(pending/.01+1e-9))
    local elapsed=steps*.01
    self.motionElapsed=math.max(0,pending-elapsed)
    return elapsed,steps
end
return C
