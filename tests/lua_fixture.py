"""Fresh engine model; does not execute another test suite."""

def create_world():
    from pathlib import Path
    import json
    from lupa.lua51 import LuaRuntime
    L=LuaRuntime()
    L.execute(Path('tests/fixtures/engine_fixture.lua').read_text())
    translations=json.loads(Path('CorpseProxyLab/42/media/lua/shared/Translate/RU/IG_UI.json').read_text(encoding='utf-8'))
    def get_text(key,*args):
     text=translations[key]
     for n,arg in enumerate(args,1):
      text=text.replace('%'+str(n),str(arg))
     return text
    L.globals().getText=get_text
    L.execute('''
    function isDebugEnabled() return true end
    function addBloodSplat() end
    package.preload['TimedActions/ISBaseTimedAction']=function()
     ISBaseTimedAction={}
     function ISBaseTimedAction:derive() local c={};c.__index=c;return setmetatable(c,{__index=self}) end
     function ISBaseTimedAction.new(cls,p) return setmetatable({character=p},cls) end
     function ISBaseTimedAction:setActionAnim(a) self.anim=a end
     function ISBaseTimedAction:setAnimVariable(k,v) self[k]=v end
     function ISBaseTimedAction:setOverrideHandModels() end
     function ISBaseTimedAction.stop() end
     function ISBaseTimedAction.perform() end
    end
    package.preload['TimedActions/ISTimedActionQueue']=function()
     ISTimedActionQueue={clear=function(p) if queued and queued.character==p then queued:stop() end end,add=function(a) queued=a;if a.isPath and not deferPath then a:start();a:perform();return end;if not deferAction and a:isValid() then a:start();if a.complete and not isClient() then a:complete() end;a:perform() end end}
    end
    package.preload['Vehicles/TimedActions/ISPathFindAction']=function()
     ISPathFindAction={}
     function ISPathFindAction:pathToLocationF(p,x,y,z)
      local a={character=p,x=x,y=y,z=z,isPath=true}
      function a:setOnComplete(fn) self.onComplete=fn end
      function a:setOnFail(fn) self.onFail=fn end
      function a:isValid() return true end
      function a:start() end
      function a:stop() self.stopped=true end
      function a:perform()
       if self.stopped then return end
       if noPath then self.onFail();self:stop();return end
       self.character.x=self.x;self.character.y=self.y
       if self.onComplete then self.onComplete() end
      end
      return a
     end
     function ISPathFindAction:pathToNearest(p,locations)
      return self:pathToLocationF(p,locations[1],locations[2],locations[3])
     end
    end
    luautils={walkAdj=function(p) if noPath then return false end;if p.x>3 then p.x=1 end;return true end}
    player.faceLocationF=function() end;player.faceThisObject=function() end;player.shouldBeTurning=function() return false end;player.reportEvent=function() end
    player.playSound=function() return 1 end;player.stopOrTriggerSound=function() end
    sq.canReachTo=function() return not unreachable end
    function ZombRand(max) randomID=(randomID or 100000)+1;return forcedRandom or randomID end
    SandboxVars={CorpseProxyLab={VehicleDrag=true}}
    function list(t) return {size=function() return #t end,get=function(_,i) return t[i+1] end,contains=function(_,v) for _,a in ipairs(t) do if a==v then return true end end return false end} end
    function container()
     local c={rows={}}
     c.getType=function(s) return s.type or 'inventory' end
     c.getCharacter=function(s) if s.parent and s.parent.getInventory then return s.parent end;local outer=s.containingItem and s.containingItem:getContainer();return outer and outer:getCharacter() end
     c.getParent=function(s) return s.parent end
     c.getItems=function(s) return list(s.rows) end
     c.getItemWithID=function(s,id) for _,i in ipairs(s.rows) do if i.id==id then return i end end end
     c.getItemWithIDRecursiv=function(s,id) local found=s:getItemWithID(id);if found then return found end;for _,i in ipairs(s.rows) do if i.inv then found=i.inv:getItemWithIDRecursiv(id);if found then return found end end end end
     c.AddItem=function(s,i) if type(i)=='string' then i=item(i) end;local existing=s:getItemWithID(i.id);if existing then return existing end;assert(not i.owner,'item already in container');s.rows[#s.rows+1]=i;i.owner=s;if i.inv then i.inv.containingItem=i end;return i end
     c.Remove=function(s,i) for n,a in ipairs(s.rows) do if a==i then table.remove(s.rows,n);i.owner=nil;return end end end
     return c
    end
    nextItem=0
    function item(t,w)
     nextItem=nextItem+1
     return {id=nextItem,t=t,w=w or 1,md={},getID=function(s) return s.id end,setID=function(s,id) s.id=id end,getDeadBodyObject=function(s) return s.deadBody end,getFullType=function(s) return s.t end,getCondition=function() return 80 end,getActualWeight=function(s) return s.w end,setActualWeight=function(s,v) s.w=v end,isCustomWeight=function(s) return s.custom or false end,setCustomWeight=function(s,v) s.custom=v end,getContainer=function(s) return s.owner end,getWorldItem=function(s) return s.worldItem end,getModData=function(s) return s.md end,storeInByteData=function(s,b) s.saved={};for _,v in ipairs(b.inv.rows) do s.saved[#s.saved+1]=v.id end end}
    end
    storage=container();storage.parent=player;player.getInventory=function() return storage end
    sq.getX=function() return 0 end;sq.getY=function() return 0 end;sq.getZ=function() return 0 end
    sq.getLightInfo=function() return {} end
    sq.removeCorpse=function(_,b) if removeFail then error('remove failure') end;b.world=false end
    sq.addCorpse=function(_,b) if addFail then error('add failure') end;assert(not b.world);b.world=true end
    sq.getStaticMovingObjects=function() local visible={};for _,b in ipairs(bodies) do if b.world then visible[#visible+1]=b end end;return list(visible) end
    function corpse()
     local b=actor('IsoDeadBody',0,0);b.world=true;b.inv=container();b.inv.parent=b;b.inv:AddItem(item('Base.Watch',1));b.carrier=item('Base.CorpseMale',20)
     b.getContainer=function(s) return s.inv end;b.getItem=function() error('must not create an inventory corpse') end
     b.md={};b.getModData=function(s) return s.md end;b.invalidateRenderChunkLevel=function(s) s.invalidations=(s.invalidations or 0)+1 end
     b.getStaticMovingObjectIndex=function(s) return s.world and 0 or -1 end
     b.isBeingGrappled=function() return false end;b.isFakeDead=function() return false end
     b.isSkeleton=function(s) return s.skeleton==true end
     b.isZombie=function() return true end;b.isPlayer=function() return false end;b.isAnimal=function() return false end
     b.getDiedBoneTransforms=function(s) return s.pose end
     b.setFakeDead=function(s,v) s.fakeDead=v end;b.setReanimateTime=function(s,v) s.reanimateTime=v end
     b.getAngle=function() return 0 end;b.setDoRender=function() end
     b.setForwardDirectionAngle=function(s,a) s.angle=a end;b.invalidateCorpse=function(s) s.cached=nil end
     b.render=function(s) if s.renderFail then error('render failure') end;s.renders=(s.renders or 0)+1;s.cached=s.cached or s.angle or 0 end
     bodies[#bodies+1]=b;return b
    end
    bodies={};body=corpse();body2=corpse()
    rope=item('Base.Rope');chain=item('Base.HeavyChain',3);rope.getDisplayName=function() return getText('IGUI_CVP_Rope') end;chain.getDisplayName=function() return getText('IGUI_CVP_Chain') end;storage:AddItem(rope);storage:AddItem(chain)
    car.md={};car.getModData=function(s) return s.md end
    car.isLocalPhysicSim=function() return true end
    car.isDoingOffroad=function() return offroad or false end
    car.getMass=function() return 1000 end
    car.getLinearVelocity=function() return {x=function() return 10 end,z=function() return 0 end} end
    -- The MP test stand hands a key to every online player (tools/mp-test/.../CVP_MPTestServer.lua).
    car.createVehicleKey=function() return {getModData=function() return {} end,getFullType=function() return 'Base.CarKey' end,getID=function() return 9001 end} end
    impulses={};car.applyImpulseGeneric=function(_,x,y,z,dx,dy,dz,amount) assert(dx<0 and dy==0 and dz==0);impulses[#impulses+1]=amount end
    player.getPrimaryHandItem=function() return nil end;player.getSecondaryHandItem=function() return nil end
    player.md={};player.getModData=function(s) return s.md end
    options={};context.addOption=function(_,label,p,f,...) local args={...};local o={label=label,run=function() if f then f(p,unpack(args)) end end};if f and label~=getText('IGUI_CVP_Rope') and label~=getText('IGUI_CVP_Chain') and label~=getText('IGUI_CVP_HookChain') then options[#options+1]=o end;_.children=_.children or {};_.children[#_.children+1]=o;return o end
    ISContextMenu={getNew=function(_,parent) return setmetatable({children={},parent=parent},{__index=context}) end}
    context.insertOptionBefore=function(self,before,label,p,f,...)
     local opt=self:addOption(label,p,f,...);table.remove(self.children)
     local at=#self.children+1;for i,v in ipairs(self.children) do if v.label==before then at=i;break end end
     table.insert(self.children,at,opt);return opt
    end
    context.removeOptionByName=function(self,label) for i=#self.children,1,-1 do if self.children[i].label==label then table.remove(self.children,i) end end end
    context.addSubMenu=function(_,opt,sub) opt.subMenu=sub end
    ISWorldObjectContextMenu.addToolTip=function() return {} end
    ISWorldObjectContextMenu.initWorldItemHighlightOption=function(o,b) o.body=b end
    IsoObjectPicker={Instance={PickVehicle=function() return pickedVehicle end}}
    function getMouseX() return 0 end
    function getMouseY() return 0 end
    function getMouseXScaled() return 0 end
    function getMouseYScaled() return 0 end
    function menu(b) menuTarget=b or body;options={};context.children={};callbacks.OnFillWorldObjectContextMenu(0,context,{b or body},false) end
    function click(pattern) if pattern=='(верёвка)' then pattern=getText('IGUI_CVP_Rope') elseif pattern=='(цепь)' then pattern=getText('IGUI_CVP_Chain') end; for _,o in ipairs(options) do if string.find(o.label,pattern,1,true) and not o.label:find(getText('IGUI_CVP_QuickTail',''),1,true) and (not o.body or o.body==menuTarget) then assert(not o.notAvailable);o.run();return end end;error('missing menu '..pattern) end
    function menuBranch(node,label)
     for _,o in ipairs(node.children or {}) do if o.label==label then return o end end
    end
    function batchMenu(sequential)
     pickedVehicle=car;menu();pickedVehicle=nil
     local sub=assert(menuBranch(context,getText('IGUI_CVP_OtherWays'))).subMenu
     local opt=assert(menuBranch(sub,getText(sequential and 'IGUI_CVP_AutoSequence' or 'IGUI_CVP_AutoMaterial')))
     assert(not opt.notAvailable);opt.run()
    end
    function tailMenu(b)
     menu(b)
     for _,opt in ipairs(context.children) do
      if opt.label:find(getText('IGUI_CVP_QuickTail',''):gsub(' %%s*$',''),1,true)==1 then assert(not opt.notAvailable);opt.run();return end
     end
     error('missing tail action')
    end
    function carMenu() pickedVehicle=car;menu();pickedVehicle=nil end
    function tick() now=now+100;callbacks.OnTick() end
    function resetPositions() player.x=0;player.y=0;car.x=2;car.y=0;body.x=0;body.y=0;body2.x=0;body2.y=0 end
    package.preload['CVP_Overlay']=function() return {install=function() end} end
    ''')
    L.execute(r'''
    grid={}
    function gridSquare(x,y,z)
     local key=x..':'..y..':'..z
     if grid[key] then return grid[key] end
     local q={rows={},ground={},x=x,y=y,z=z}
     q.getWorldObjects=function(s) return list(s.ground) end
     q.AddWorldInventoryItem=function(s,i)
      assert(not i:getContainer() and not i:getWorldItem());local o={item=i,square=s}
      o.getItem=function(v) return v.item end;o.getSquare=function(v) return v.square end
      s.ground[#s.ground+1]=o;i.worldItem=o;return o
     end
     q.getX=function(s) return s.x end;q.getY=function(s) return s.y end;q.getZ=function(s) return s.z end
     q.isSolid=function() return blocked or false end;q.isSolidTrans=function() return false end;q.TreatAsSolidFloor=function() return true end
     q.isBlockedTo=function() return blocked or false end;q.canReachTo=function() return not unreachable end
     q.getStaticMovingObjects=function(s) local rows={};for _,b in ipairs(s.rows) do if b.world then rows[#rows+1]=b end end;return list(rows) end
     q.removeCorpse=function(s,b) if removeFail then error('remove failure') end;for i,v in ipairs(s.rows) do if v==b then table.remove(s.rows,i);break end end;b.world=false;if b.pose then b.pose.released=true;b.pose=nil end end
     q.addCorpse=function(s,b) if addFail==s then error('add failure') end;assert(not list(s.rows):contains(b),'duplicate square membership');s.rows[#s.rows+1]=b;b.world=true;b.sq=s end
     q.isCanSee=function() return true end
     grid[key]=q;return q
    end
    cell.getGridSquare=function(_,x,y,z) if unloaded then return nil end;return gridSquare(x,y,z) end
    sq=gridSquare(0,0,0)
    player.getSquare=function(s) return gridSquare(math.floor(s.x),math.floor(s.y),s.z) end
    for _,b in ipairs(bodies) do
     b.getSquare=function(s) return s.sq end;b.setSquare=function(s,q) s.sq=q end
     b.getStaticMovingObjectIndex=function(s) return s.world and s.sq and list(s.sq.rows):contains(s) and 0 or -1 end
     sq:addCorpse(b)
    end
    function resetPositions()
     player.x=0;player.y=0;car.x=2;car.y=0
     for _,b in ipairs({body,body2}) do
      if b.world then b.sq:removeCorpse(b) end
      b.x=0;b.y=0;b.sq=sq
      for _,q in pairs(grid) do for i=#q.rows,1,-1 do if q.rows[i]==b then table.remove(q.rows,i) end end end
      sq:addCorpse(b)
     end
    end
    function worldCount(b)
     local count=0;for _,q in pairs(grid) do for _,v in ipairs(q.rows) do if v==b and v.world then count=count+1 end end end
     return count
    end
    CVPWorldNative={removePreservingPose=function(q,b)
     local pose=b.pose;b.pose=nil
     local ok,err=pcall(q.removeCorpse,q,b,false);b.pose=pose
     if not ok then error(err) end
    end,version=function() return 'test-native' end,
    -- Record resistance requests; this fixture does not simulate the native physics queue.
    applyVehicleResistance=function(v,amount)
     local velocity=v:getLinearVelocity();local x,z=velocity:x(),velocity:z()
     local speed=math.sqrt(x*x+z*z)
     if amount>0 and amount<math.huge and speed>=.02 then impulses[#impulses+1]=amount end
    end,
    applyVehicleImpulse=function(v,...) v:applyImpulseGeneric(...) end}
    ''')
    L.execute((Path(__file__).parent/'fixtures/native_world.lua').read_text(encoding='utf-8'))
    L.execute((Path(__file__).parent/'fixtures/native_rope.lua').read_text(encoding='utf-8'))
    def equipment_plain(value):
     if hasattr(value,'items'):
      return {key:equipment_plain(part) for key,part in value.items()}
     return value
    def equipment_encode(value):
     state={key:equipment_plain(value[key]) for key in ('id','t','w','md','custom','state') if value[key] is not None}
     return json.dumps(state,sort_keys=True,ensure_ascii=True)
    def equipment_decode(payload):
     state=json.loads(payload)
     result=L.globals().item(state['t'],state['w'])
     for key,value in state.items():
      result[key]=L.table_from(value,recursive=True) if isinstance(value,dict) else value
     return result
    L.globals().equipmentEncode=equipment_encode
    L.globals().equipmentDecode=equipment_decode
    L.execute('''
    function equipmentCopy(value)
     if type(value)~='table' then return value end
     local result={};for key,part in pairs(value) do result[key]=equipmentCopy(part) end;return result
    end
    ItemContainer={new=container}
    CVPItemNative={encode=function(i) return equipmentEncode(i) end,decode=function(p) return equipmentDecode(p) end}
    equipmentWrites=0;equipmentCheckpoints=0
    worldHours=0;function getGameTime() return {getWorldAgeHours=function() return worldHours end} end
    CVPEquipmentPersistence={
     read=function() return equipmentCopy(equipmentDisk) end,
     write=function(value) if equipmentWriteFailure then error('ledger write failed') end;equipmentWrites=equipmentWrites+1;equipmentDisk=equipmentCopy(value);return true end,
     playerKey=function(p)
      p.md=p.md or {};if not p.md.CVPEquipmentPlayerKey then p.md.CVPEquipmentPlayerKey=getRandomUUID() end
      return p.md.CVPEquipmentPlayerKey
     end,
     checkpointPlayer=function(p) assert(p:getInventory());if equipmentCheckpointFailure then error('outcome unknown') end;equipmentCheckpoints=equipmentCheckpoints+1;return true end,
     checkpointSquare=function(q) assert(q);if equipmentCheckpointFailure then error('outcome unknown') end;equipmentCheckpoints=equipmentCheckpoints+1;return true end
    }
    for _,name in ipairs({'write','playerKey','checkpointPlayer','checkpointSquare'}) do
     local method=name
     CVPEquipmentPersistence[method..'Async']=function(...) return {value=CVPEquipmentPersistence[method](...)} end
    end
    CVPEquipmentPersistence.poll=function() return 1 end
    CVPEquipmentPersistence.result=function(ticket) return ticket.value end
    function serializeEquipment() return equipmentCopy(equipmentDisk) end
    function loadEquipment(saved)
     equipmentDisk=equipmentCopy(saved);CVPEquipmentRuntime=nil;package.loaded['CVP_Equipment']=nil
    end
    function takeGround(i,destination)
     local o=assert(i:getWorldItem());local q=o:getSquare()
     for n,v in ipairs(q.ground) do if v==o then table.remove(q.ground,n);break end end
     i.worldItem=nil;destination:AddItem(i)
    end
    ''')
    return L


def create_current_fixture():
    """Register only shipped modules; entry points are executed by each scenario."""
    from pathlib import Path
    lua=create_world()
    root=Path('CorpseProxyLab/42/media/lua')
    for directory in ('shared','client'):
        for path in sorted((root/directory).glob('CVP_*.lua')):
            if path.stem=='CVP_Overlay':
                continue  # Engine UI is modeled above, not started by unit tests.
            lua.execute("package.preload[...]=assert(loadstring(select(2,...)))",path.stem,
                        path.read_text(encoding='utf-8-sig'))
    return lua


def copy_packet(value):
    """Copy serialized Lua data across isolated model VMs."""
    if hasattr(value, 'items'):
        return {k: copy_packet(v) for k, v in value.items()}
    return value
