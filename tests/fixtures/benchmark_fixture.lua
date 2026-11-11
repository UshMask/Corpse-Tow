-- Strict method arity catches Lua multiple-return arguments at Java boundaries.
next=nil
files={['CVPBenchmark-mode.txt']={'Off'}};outputs={};now=1000;speed=1;visible=false;worldReady=true
function getFileReader(name)
    local lines=files[name];if not lines then return end
    local i=0;return {readLine=function() i=i+1;return lines[i] end,close=function() end}
end
function getFileWriter(name)
    local allowed={ini=true,cfg=true,txt=true,log=true,json=true}
    if not allowed[name:match('%.([^%.]+)$')] or (failOutput and name:find('CVPBenchmark%-')) then return nil end
    return {write=function(self,text) outputs[name]=text end,close=function() end}
end
local renderCallbacks={}
Events={OnRenderTick={Add=function(fn) renderCallbacks[#renderCallbacks+1]=fn end},OnTick={Add=function(fn) tick=fn end},OnGameStart={Add=function(fn) start=fn end}}
function render() for _,fn in ipairs(renderCallbacks) do fn() end end
function getTimestampMs() return now end
function isDebugEnabled() return true end
function isClient() return false end;function isServer() return false end
function getWorld() return {getWorld=function() return 'CVP_QuickTest' end} end
player={x=100,y=100,z=0}
function player:getX() return self.x end;function player:getY() return self.y end;function player:getZ() return self.z end
function player:setX(x) self.x=x end;function player:setY(y) self.y=y end;function player:setZ(z) self.z=z end
function player:setCurrent(...) assert(select('#',...)==1,'setCurrent arity');self.square=(...) end
function player:getVehicle() return nil end
function player:setGodMod() end;function player:setGhostMode() end
function getPlayer() if worldReady then return player end end
function getGameSpeed() return speed end;function setGameSpeed(n) speed=n end
function getGameTime() return {setTimeOfDay=function() end} end
MainScreen={instance={isVisible=function() return visible end,inGame=true}}
KeybindId={MAIN_MENU=1}
function ToggleEscapeMenu() visible=not visible end
function getCore() return {getKey=function() return 1 end,getZoom=function() return 2 end,getScreenWidth=function() return 1280 end,getScreenHeight=function() return 720 end} end
vehicle={x=100,y=101}
function vehicle:getX() return self.x end;function vehicle:getY() return self.y end
function vehicle:setForceBrake() end;function vehicle:setPhysicsActive() end
function vehicle:attachmentExist() return true end
function vehicle:getAttachmentWorldPos(name,v) v.xx=self.x;v.yy=self.y end
Vector3f={new=function() return {x=function(self) return self.xx end,y=function(self) return self.yy end} end}
CVPBenchmarkNative={milliseconds=function() return now end,heapMB=function() return 128 end,
    moveVehicle=function(v,dx,dy) if failMotion then error('native motion failure') end;v.x=v.x+dx;v.y=v.y+dy end}
local squares={};created=0;removed=0
local function squareAt(x,y,z)
    local key=x..':'..y..':'..z
    if squares[key] then return squares[key] end
    local sq={bodies={}}
    function sq:isSolid() return obstructed end;function sq:isSolidTrans() return false end
    function sq:getDeadBodys() return {size=function() return #sq.bodies end,get=function(self,i) return sq.bodies[i+1] end} end
    function sq:removeCorpse(b)
        for i=#self.bodies,1,-1 do if self.bodies[i]==b then table.remove(self.bodies,i);b.index=-1;removed=removed+1;return end end
    end
    function sq:addCorpse(b) self.bodies[#self.bodies+1]=b;b.index=0;b.square=self end
    function sq:createCorpse(...)
        local argc=select('#',...)
        assert(argc==1 or (argc==2 and type((...))=='table'),'createCorpse arity');created=created+1
        local b={x=x,y=y,z=z,index=0,square=self}
        function b:isZombie() return true end
        function b:isPlayer() return false end
        b.modData={};function b:getModData() return self.modData end
        function b:setFakeDead() end;function b:setReanimateTime() end
        function b:getX() return self.x end;function b:getY() return self.y end
        function b:setX(v) self.x=v end;function b:setY(v) self.y=v end;function b:setZ(v) self.z=v end
        function b:setSquare(v) self.square=v end;function b:getSquare() return self.square end
        function b:getStaticMovingObjectIndex() return self.index end
        function b:removeFromWorld() end;function b:removeFromSquare() self.square:removeCorpse(self) end
        self.bodies[#self.bodies+1]=b;return b
    end
    squares[key]=sq;return sq
end
function getCell() return {getGridSquare=function(self,x,y,z) return squareAt(x,y,z) end,
    getVehicles=function() return {iterator=function()
        local pending=true
        return {hasNext=function() return pending end,next=function() assert(pending);pending=false;return vehicle end}
    end} end} end
function send(id,op,count,topology,motion)
    files['PZTest/request.txt']={id,PZTest.session,'benchmark.'..op,tostring(count or 0)..' '..(topology or 'loose')..' '..(motion or 'idle'),'END'}
    now=now+250;render()
    local r=PZTest.lastResponse
    return r.id..'\n'..tostring(r.ok)..'\n'..tostring(r.result or r.error)
end
