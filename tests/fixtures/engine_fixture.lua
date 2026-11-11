
function isClient() return false end; function isServer() return false end
callbacks={};messages={};now=0; deaths=0; held=false; bodies={}
Events=setmetatable({}, {__index=function(t,k) local e={Add=function(f) callbacks[k]=f end};rawset(t,k,e);return e end})
function list(t) return {size=function() return #t end,get=function(_,i) return t[i+1] end,remove=function() end} end
function instanceof(o,k) return o.kind==k end
function getTimestampMs() return now end
function getRandomUUID()
 uuidSequence=(uuidSequence or 0)+1
 return string.format('00000000-0000-4000-8000-%012d',uuidSequence)
end
inv={getItems=function() return list({{getID=function() return 11 end,getFullType=function() return 'Base.Rope' end,getCondition=function() return 80 end}}) end}
sq={getStaticMovingObjects=function() return list(bodies) end,isSolid=function() return blocked or false end,isSolidTrans=function() return false end,TreatAsSolidFloor=function() return true end,isBlockedTo=function() return false end}
function actor(kind,x,y)
 return {kind=kind,x=x,y=y,z=0,getX=function(s) return s.x end,getY=function(s) return s.y end,getZ=function(s) return s.z end,setX=function(s,v) s.x=v end,setY=function(s,v) s.y=v end,setZ=function(s,v) s.z=v end,getSquare=function() return sq end,setCurrent=function() end,setSquare=function() end,setOnFloor=function() end,setForwardDirection=function() end,setTargetAndCurrentDirection=function(s,x,y) s.facingX=x;s.facingY=y end,getDirectionAngleRadians=function() return 0 end,getAnimationPlayer=function() return setmetatable({}, {__index=function() error("AnimationPlayer is opaque to Lua") end}) end,setTargetGrapplePos=function() end}
end
body=actor('IsoDeadBody',0,0)
body.getContainer=function() return inv end
body.getStaticMovingObjectIndex=function() return 0 end
body.isBeingGrappled=function() return false end
body.isFakeDead=function() return false end
body.isZombie=function() return true end
body.isPlayer=function() return false end
body.isAnimal=function() return false end
bodies={body}
car=actor('BaseVehicle',2,0); car.getCurrentSpeedKmHour=function() return speed or 0 end
car.getScript=function() return {getName=function() return 'TestCar' end,getExtents=function() return {z=function() return 4 end} end} end
car.getWorldPos=function(s,a,b,c,out) out.xx=s.x;out.yy=s.y end
Vector3f={new=function() return {x=function(s) return s.xx end,y=function(s) return s.yy end} end}
player=actor('IsoPlayer',0,0);player.getVehicle=function() return driving and car or nil end;player.isDraggingCorpse=function() return false end;player.isDead=function() return false end;player.Say=function(_,s) messages[#messages+1]=s end
function getPlayer() return player end;function getSpecificPlayer() return player end
cell={getGridSquare=function() return sq end,getVehicles=function() return {iterator=function() local pending=true;return {hasNext=function() return pending end,next=function() pending=false;return car end} end} end,getSurvivorList=function() return list({}) end}
function getCell() return cell end
IsoSurvivor={new=function()
 local p=actor('IsoSurvivor',0,0)
 p.setInvisible=function() end;p.setCollidable=function() end;p.setDoContinueGrapple=function() end;p.removeFromWorld=function() end;p.removeFromSquare=function() end
 p.pickUpCorpse=function()
   target=actor('IsoZombie',0,0);target.getInventory=function() return inv end
   target.isBeingGrappled=function() return held end
   target.getCurrentStateName=function() return actorState or 'CorpseDragged' end
   target.hasHitReaction=function() return hit or false end
   target.getHitReaction=function() return hit and 'Vehicle' or '' end
   target.isReanimatedForGrappleOnly=function() return true end
   target.die=function() deaths=deaths+1;body.x=target.x;body.y=target.y;bodies={body} end
   held=true;bodies={}
 end
 p.getGrapplingTarget=function() return target end
 p.LetGoOfGrappled=function() held=false end
 return p
end}
ISWorldObjectContextMenu={initWorldItemHighlightOption=function() end}
context={addOption=function(_,label,p,f,b,v) option=function() f(p,b,v) end;return {} end}
