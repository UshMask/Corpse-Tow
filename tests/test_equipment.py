"""Durable ownership ledger with native codec/checkpoint boundaries modeled."""
import json
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

SOURCE = Path('CorpseProxyLab/42/media/lua/shared/CVP_Equipment.lua').read_text(encoding='utf-8-sig')

def plain(value):
    return {k: plain(v) for k,v in value.items()} if hasattr(value,'items') else value

def vm(saved=None,role='sp',seed=True,legacy=False):
    lua=LuaRuntime()
    lua.execute("package.preload.CVP_EquipmentData=assert(loadstring(...))", Path('CorpseProxyLab/42/media/lua/shared/CVP_EquipmentData.lua').read_text(encoding='utf-8-sig'))
    lua.execute("package.preload.CVP_SaveJobs=assert(loadstring(...))", Path("CorpseProxyLab/42/media/lua/shared/CVP_SaveJobs.lua").read_text())
    lua.execute("package.preload.CVP_Legacy=assert(loadstring(...))", Path('CorpseProxyLab/42/media/lua/shared/CVP_Legacy.lua').read_text(encoding='utf-8-sig'))
    lua.execute("package.preload.CVP_LinkGraph=assert(loadstring(...))", Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkGraph.lua').read_text(encoding='utf-8-sig'))
    lua.globals().client=role=='client';lua.globals().server=role=='server'
    lua.globals().seed=seed;lua.globals().persisted=lua.table_from(saved,recursive=True) if saved else None
    source=SOURCE
    if legacy:
        from legacy_fixture import legacy_operations
        source=legacy_operations('Equipment', source)
    lua.globals().moduleSource=source
    lua.execute("package.preload['CVP_LinkClocks']=assert(loadstring(...))",
                Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkClocks.lua').read_text(encoding='utf-8-sig'))
    lua.execute('''
    function isClient() return client end;function isServer() return server end
    now=0;function getTimestampMs() return now end
    worldHours=0;function getGameTime() return {getWorldAgeHours=function() return worldHours end} end
    function clone(v) if type(v)~='table' then return v end;local o={};for k,x in pairs(v) do o[k]=clone(x) end;return o end
    function list(rows) return {size=function() return #rows end,get=function(_,i) return rows[i+1] end,
     contains=function(_,i) for _,x in ipairs(rows) do if x==i then return true end end;return false end} end
    function container()
     local c={rows={}}
     function c:getType() return self.type or 'inventory' end
     function c:getCharacter() return self.character or self.outer and self.outer:getCharacter() end
     function c:getItems() return list(self.rows) end
     function c:getItemWithID(id) for _,v in ipairs(self.rows) do if v:getID()==id then return v end end end
     function c:getItemWithIDRecursiv(id)
      local v=self:getItemWithID(id);if v then return v end
      for _,i in ipairs(self.rows) do if i.inv then local v=i.inv:getItemWithIDRecursiv(id);if v then return v end end end
     end
     function c:AddItem(i) if self.refuseAdd then return end;assert(not i.owner and not self:getItemWithID(i:getID()));self.rows[#self.rows+1]=i;i.owner=self;return i end
     function c:Remove(i) if self.refuseRemove then return end;for n,v in ipairs(self.rows) do if v==i then table.remove(self.rows,n);i.owner=nil;return end end end
     return c
    end
    function item(state) return {state=state,getID=function(s) return s.state.id end,getFullType=function(s) return s.state.type end,
     getContainer=function(s) return s.owner end,getWorldItem=function(s) return s.worldItem end} end
    function actor(key,c) local p={key=key,inv=c,md={}};function p:getModData() return self.md end;function p:getInventory() return self.inv end;c.character=p;return p end
    source=container();destination=container();player=actor('source-player',source);target=actor('target-player',destination)
    sq={ground={}};function sq:getX() return 1 end;function sq:getY() return 2 end;function sq:getZ() return 0 end
    function sq:getWorldObjects() return list(self.ground) end
    function sq:AddWorldInventoryItem(i)
     if failGround then error('ground refused') end
     local o={getItem=function() return i end};self.ground[#self.ground+1]=o;i.worldItem=o;return o
    end
    cell={getGridSquare=function() return sq end};function getCell() return cell end
    function corpse(key)
     local b={md={CVPBodyKey=key},inv=container()}
     function b:getModData() return self.md end;function b:getContainer() return self.inv end;function b:getSquare() return sq end
     return b
    end
    body=corpse('body-one');metadata={version=3,gearID=42,gearType='Base.Rope',connection={id='connection-one',b={key='body-one'}}}
    context={body=body,metadata=metadata}
    ItemContainer={new=container};uuid=0
    function getRandomUUID() uuid=uuid+1;return forcedKey or ('equipment-'..uuid) end
    transfers=0;coreLoads=0;backendCalls=0;writes=0;checkpoints=0;trace={}
    function transfer(i,src,dst)
     transfers=transfers+1
     if not src:getItems():contains(i) or dst:getItemWithID(i:getID()) then return false,'conflict' end
     local ok=pcall(function() src:Remove(i);assert(not i.owner);dst:AddItem(i);assert(i.owner==dst) end)
     if not ok then if dst:getItems():contains(i) then dst:Remove(i) end;if not i.owner then src:AddItem(i) end;return false,'refused' end
     return true
    end
    package.preload['CVP_Core']=function() coreLoads=coreLoads+1;return {transfer=transfer} end
    function checkpoint(kind,owner)
     checkpoints=checkpoints+1;trace[#trace+1]='checkpoint-'..kind
     if failCheckpoint or failCheckpointAt==checkpoints then error('outcome unknown') end
     return true
    end
    CVPEquipmentPersistence={read=function() backendCalls=backendCalls+1;return clone(persisted) end,
     write=function(value) writes=writes+1;if failWrite or failWriteAt==writes then error('write failed') end;persisted=clone(value);trace[#trace+1]='write';return true end,
     playerKey=function(p) if failPlayerKey then error('identity checkpoint failed') end;return p.key end,
     checkpointPlayer=function(p) return checkpoint('player',p) end,checkpointSquare=function(q) return checkpoint('square',q) end}
    if seed then original=item({id=42,type='Base.Rope',condition=63,name='original',weight=1.25,modData={marker='keep',nested={n=7}}});source:AddItem(original) end
    function reload() E=assert(loadstring(moduleSource))() end
    ''')
    def encode(i): return json.dumps(plain(i['state']),sort_keys=True,ensure_ascii=True)
    def decode(p): return lua.globals().item(lua.table_from(json.loads(p),recursive=True))
    lua.globals().encodeMock=encode;lua.globals().decodeMock=decode
    lua.execute('''encodes=0;decodes=0;CVPItemNative={encode=function(i) encodes=encodes+1;return encodeMock(i) end,
     decode=function(p) decodes=decodes+1;return decodeMock(p) end};reload()''')
    return lua

class EquipmentTests(unittest.TestCase):
    def test_store_validation_needs_no_native_backend_and_does_not_mutate_data(self):
        lua=LuaRuntime()
        data=Path('CorpseProxyLab/42/media/lua/shared/CVP_EquipmentData.lua').read_text()
        lua.globals().Data=lua.execute(data)
        lua.execute("""
            local saved={version=2,rows={rope={id=42,type='Base.Rope',state='held',payload='original'}}}
            local before=Data.copy(saved);local shadow=assert(Data.validateStore(saved))
            assert(Data.equal(saved,before));shadow.rows.rope.payload='changed'
            assert(saved.rows.rope.payload=='original')
            saved.rows.duplicate=Data.copy(saved.rows.rope)
            before=Data.copy(saved);assert(not Data.validateStore(saved));assert(Data.equal(saved,before))
        """)

    def test_validated_shadow_reads_and_rejected_write_preserve_originals(self):
        for role in ('sp','server'):
            l=vm(role=role);l.execute('''
                key=assert(E.hold(original,transfer));local payload=CVPEquipmentRuntime.data.rows[key].payload
                local scans=0;local find=string.find
                string.find=function(s,pattern,...) if s==payload then scans=scans+1 end;return find(s,pattern,...) end
                for i=1,64 do assert(E.get(key)==original) end
                string.find=find;assert(scans==0,'unchanged payload rescanned during reads')
                local second=item({id=43,type='Base.Rope'});source:AddItem(second)
                local before=writes;local moved=transfers
                CVPEquipmentRuntime.data.rows[key].payload=''
                assert(not E.get(key))
                assert(not E.hold(second,transfer))
                assert(writes==before and transfers==moved and second.owner==source)
                assert(persisted.rows[key].payload==payload)
                CVPEquipmentRuntime.data.rows[key].payload=payload
                assert(E.get(key)==original);assert(E.release(key,destination,transfer))
                assert(destination.rows[1]==original)
            ''')

    def test_lazy_authority_and_original_instance(self):
        for role in ('sp','server'):
            l=vm(role=role);l.execute('''assert(backendCalls==0);next=nil
             key=assert(E.hold(original));assert(E.get(key)==original and #source.rows==0)
             assert(persisted.rows[key].state=='held');assert(E.release(key,destination))
             for _ in pairs(persisted.rows) do error('retained row') end
             assert(destination.rows[1]==original and not E.release(key,destination))''')
        l=vm(role='client');l.execute('assert(E==nil and backendCalls==0 and #source.rows==1)')
    def test_hot_reload_preserves_original(self):
        l=vm();l.execute('key=assert(E.hold(original,transfer));before=decodes;reload();assert(E.get(key)==original and decodes==before)')
    def test_fresh_runtime_restores_state_once(self):
        a=vm();a.execute('key=assert(E.hold(original,transfer))')
        b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
        b.execute('restored=assert(E.get(key));assert(E.get(key)==restored and decodes==1);assert(E.release(key,destination,transfer))')
        self.assertEqual(plain(a.globals().original['state']),plain(b.globals().restored['state']))
    def test_body_identity_barrier_and_authoritative_metadata(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer,context));assert(trace[1]=='checkpoint-square' and trace[2]=='write')
         assert(E.observeBody(body));local same=body.md.CVPTether;assert(same.equipmentKey==key)
         assert(E.observeBody(body) and body.md.CVPTether==same);assert(E.get(key,'body-one')==original and not E.get(key,'wrong'))
         assert(E.release(key,destination,transfer,context));assert(body.md.CVPTether==nil and persisted.rows[key]==nil)''')
    def test_pretransfer_failures_do_not_move_or_claim(self):
        for code in ('failWrite=true','failPlayerKey=true','failCheckpoint=true'):
            l=vm();l.execute(code+''';local key,err=E.hold(original,transfer,context);assert(not key and err)
             assert(transfers==0 and original.owner==source and persisted==nil)''')
    def test_world_floor_and_unknown_owner_rejected(self):
        for code in ("original.worldItem={}","source.type='floor'","source.character=nil"):
            l=vm();l.execute(code+''';assert(not E.hold(original,transfer));assert(transfers==0 and original.owner==source)''')
        l=vm();l.execute("key=assert(E.hold(original,transfer));destination.type='floor';assert(not E.release(key,destination,transfer) and E.get(key)==original)")
    def test_duplicate_ids_keys_and_body_binding(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer,context));local second=item({id=42,type='Base.HeavyChain'});source:AddItem(second)
         assert(not E.hold(second,transfer));source:Remove(second);second=item({id=43,type='Base.HeavyChain'});source:AddItem(second)
         forcedKey=key;assert(not E.hold(second,transfer));forcedKey=nil
         assert(not E.hold(second,transfer,context) and transfers==1 and second.owner==source)''')
    def test_invalid_codec_rejected_before_transfer(self):
        for override in ("error('invalid')","return string.rep('x',22001)","return '{}'", "return string.char(255)"):
            l=vm();l.execute('CVPItemNative.encode=function() '+override+' end;assert(not E.hold(original,transfer));assert(transfers==0 and original.owner==source)')
    def test_failed_hold_compensation_is_durable(self):
        l=vm();l.execute('''source.refuseRemove=true;assert(not E.hold(original,transfer));assert(original.owner==source)
         source.refuseRemove=nil
         local function bad(i,s,d) assert(transfer(i,s,d));error('after move') end
         assert(not E.hold(original,bad) and original.owner==source)
         for _ in pairs(persisted.rows) do error('retained canceled row') end''')
    def test_failed_compensation_remains_pending_until_ack(self):
        l=vm();l.execute('''local first=true;local function bad(i,s,d) if first then first=false;assert(transfer(i,s,d));error('moved') end;return false end
         key,err=E.hold(original,bad);assert(key and err and not E.get(key) and persisted.rows[key].state=='taking')
         assert(E.recover(player) and E.get(key)==original)''')
    def test_checkpoint_unknown_hold_never_decodes_before_recovery(self):
        a=vm();a.execute('failCheckpoint=true;key,err=E.hold(original,transfer);assert(key and err and not E.get(key))')
        b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
        b.execute('''assert(not E.get(key) and decodes==0);failCheckpoint=true;assert(not E.recover(player) and not E.get(key) and decodes==0)
         failCheckpoint=nil;assert(not E.recover(player));assert(not E.get(key) and decodes==0)''')
        a.execute('failCheckpoint=nil;assert(E.recover(player) and E.get(key)==original)')
    def test_recovery_taking_source_still_present_cancels_without_decode(self):
        a=vm();a.execute('failCheckpoint=true;key=E.hold(original,function() return false end);assert(key)')
        b=vm(plain(a.globals().persisted));b.globals().key=a.globals().key
        b.execute('assert(E.recover(player));assert(not E.get(key) and decodes==0 and #source.rows==1)')
    def test_return_write_failure_is_before_transfer(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer));before=transfers;failWrite=true
         assert(not E.release(key,destination,transfer) and E.get(key)==original and transfers==before)''')
    def test_refused_return_retriable(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer));destination.refuseAdd=true
         assert(not E.release(key,destination,transfer) and E.get(key)==original)
         destination.refuseAdd=nil;assert(E.release(key,destination,transfer))''')
    def test_moved_then_error_return_never_reissues(self):
        a=vm();a.execute('''key=assert(E.hold(original,transfer));local first=true
         assert(not E.release(key,destination,function(i,s,d) if not first then return false end;first=false;assert(transfer(i,s,d));error('moved') end))
         assert(original.owner==destination and not E.get(key) and persisted.rows[key].state=='unresolved')''')
        b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
        b.globals().returnedState=b.table_from(plain(a.globals().original['state']),recursive=True)
        b.execute('''destination:AddItem(item(returnedState));assert(not E.get(key) and decodes==0)
         assert(E.recover(target));assert(not E.get(key) and decodes==0 and #destination.rows==1)''')
    def test_returning_absent_after_restart_cannot_prove_no_delivery(self):
        a=vm();a.execute('key=assert(E.hold(original,transfer));failCheckpoint=true;assert(not E.release(key,destination,transfer))')
        b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
        b.execute('''assert(not E.get(key));assert(E.recover(player));assert(not E.get(key))
         failCheckpoint=true;assert(not E.recover(target));failCheckpoint=nil;assert(not E.recover(target));assert(not E.get(key) and decodes==0)''')
    def test_explicit_ground_return_and_failed_drop(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer,context));assert(E.observeBody(body));failGround=true
         assert(not E.release(key,nil,transfer,context));assert(E.get(key)==original and #sq.ground==0)
         failGround=nil;assert(E.release(key,nil,transfer,context))
         assert(#sq.ground==1 and sq.ground[1]:getItem():getID()==42 and not E.get(key))''')
    def test_released_tombstone_clears_stale_body_after_restart(self):
        a=vm();a.execute('''key=assert(E.hold(original,transfer,context));assert(E.observeBody(body));failCheckpointAt=checkpoints+2
         assert(E.release(key,destination,transfer,context));assert(persisted.rows[key].state=='released')''')
        b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
        b.execute('''body.md.CVPTether={version=3,equipmentKey=key};assert(E.observeBody(body));assert(not body.md.CVPTether and not persisted.rows[key] and decodes==0)''')
    def test_rewire_atomic_binding_and_metadata_identity(self):
        l=vm(legacy=True);l.execute('''key=assert(E.hold(original,transfer,context));E.observeBody(body);local old=body.md.CVPTether
         local md=clone(old);md.connection.id='rewired';failWrite=true
         assert(not E.updateBindings({{key=key,body=body,metadata=md}}));assert(E.observeBody(body) and body.md.CVPTether==old)
         failWrite=nil;assert(E.updateBindings({{key=key,body=body,metadata=md}}));E.observeBody(body)
         assert(body.md.CVPTether.connection.id=='rewired' and E.get(key)==original)''')
    def test_release_marks_tail_in_same_write(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer,context));child=corpse('body-two');second=item({id=43,type='Base.HeavyChain'});source:AddItem(second)
         childmd={version=3,parentConnection='connection-one',connection={id='connection-two',b={key='body-two'}}}
         childKey=assert(E.hold(second,transfer,{body=child,metadata=childmd}));assert(E.release(key,destination,transfer,context))
         assert(persisted.rows[childKey].metadata.ended==true);assert(E.observeBody(child) and child.md.CVPTether.ended==true)''')
    def test_pending_recovery_is_throttled_per_row(self):
        l=vm();l.execute('''failCheckpointAt=2;key=E.hold(original,transfer,context);assert(key);failCheckpoint=true
         E.observeBody(body);local before=checkpoints;for n=1,32 do E.observeBody(body) end;assert(checkpoints==before)
         now=5000;E.observeBody(body);assert(checkpoints==before+1)''')
    def test_orphan_metadata_clears_but_unsupported_or_changed_store_fails_closed(self):
        l=vm();l.execute("body.md.CVPTether={version=3,equipmentKey='unknown'};assert(E.observeBody(body) and body.md.CVPTether==nil and transfers==0)")
        l=vm({'version':99,'rows':{}});l.execute('assert(not E.hold(original,transfer) and transfers==0)')
        l=vm();l.execute('key=assert(E.hold(original,transfer));CVPEquipmentRuntime.data.rows[key].payload="bad";assert(not E.get(key))')
    def test_timeout_then_item_moved_cannot_reissue_after_restart(self):
        for write_failure in (False,True):
            a=vm();a.globals().failUnresolvedWrite=write_failure
            a.execute('''key=assert(E.hold(original,transfer));failCheckpoint=true
             local first=true;local function transferOnce(i,s,d)
              if not first then if failUnresolvedWrite then failWrite=true end;return false end
              first=false;return transfer(i,s,d)
             end
             assert(not E.release(key,destination,transferOnce));assert(original.owner==destination)
             destination:Remove(original);other=container();other:AddItem(original)''')
            b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
            b.execute('assert(not E.get(key));assert(not E.recover(target));assert(not E.get(key) and decodes==0)')
    def test_return_timeout_retains_delivery_receipt_until_retry(self):
        l=vm();l.execute('''key=assert(E.hold(original,transfer));failCheckpointAt=checkpoints+1
         assert(not E.release(key,destination,transfer));assert(not E.get(key) and destination.rows[1]==original)
         local row=persisted.rows[key];assert(row.state=='returning' and target.md.CVPEquipmentReceipts[row.receipt])
         assert(E.recover(target));assert(not persisted.rows[key] and #destination.rows==1)
         assert(not E.release(key,destination,transfer))''')
    def test_taking_error_then_original_moved_cannot_decode_after_restart(self):
        for write_failure in (False,True):
            a=vm();a.globals().failUnresolvedWrite=write_failure
            a.execute('''failCheckpoint=true
             key,err=E.hold(original,function()
              if failUnresolvedWrite then failWrite=true end
              return false,'transfer refused'
             end)
             assert(key and err and original.owner==source)
             source:Remove(original);other=container();other:AddItem(original)''')
            b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
            b.execute('assert(not E.get(key));assert(not E.recover(player));assert(not E.get(key) and decodes==0)')
    def test_authoritative_membership_survives_tombstone_cleanup(self):
        l=vm(legacy=True);l.execute('''assert(E.members('car-one',{sleeping=true}));metadata.connection.a={kind='vehicle',key='car-one'};key=assert(E.hold(original,transfer,context))
         E.observeBody(body);local md=clone(body.md.CVPTether);md.connection.id='connection-new'
         assert(E.updateBindings({{key=key,body=body,metadata=md}}));local active=E.members('car-one')
         assert(active['connection-new']==true and not active['connection-one'] and active.sleeping==true)
         assert(E.release(key,destination,transfer,context));active=E.members('car-one',{['connection-one']=true,['connection-new']=true})
         assert(not active['connection-new'] and not active['connection-one'] and active.sleeping==true and not persisted.retired)''')
    def test_hundred_rewires_keep_ledger_bounded_and_old_car_cannot_restore_ids(self):
        first=vm(seed=False,legacy=True)
        first.execute('''
         assert(E.members('car-one',{['sleeping-root']=true,['sleeping-child']='sleeping-root'}))
         group={}
         for i=1,32 do
          local b=corpse('body-'..i);local gear=item({id=100+i,type='Base.Rope'});source:AddItem(gear)
          local md={version=3,rootVehicle='car-one',connection={id='round-0-'..i,a={kind='vehicle',key='car-one'},b={key='body-'..i}}}
          local key=assert(E.hold(gear,transfer,{body=b,metadata=md}));group[i]={key=key,body=b,metadata=md}
         end
         local function entries(v) local n=0;for _,x in pairs(v) do n=n+1;if type(x)=='table' then n=n+entries(x) end end;return n end
         local bound=entries(persisted)
         for round=1,100 do
          for i,entry in ipairs(group) do entry.metadata.connection.id='round-'..round..'-'..i end
          assert(E.updateBindings(group));assert(entries(persisted)==bound and persisted.retired==nil)
          local members=E.members('car-one',{['obsolete-car-save-id']=true});local count=0
          for _ in pairs(members) do count=count+1 end
          assert(count==34 and members['sleeping-root']==true and members['sleeping-child']=='sleeping-root' and not members['obsolete-car-save-id'])
         end
        ''')
        second=vm(plain(first.globals().persisted),seed=False)
        second.execute('''local members=assert(E.members('car-one',{['round-0-1']=true,['obsolete-car-save-id']=true}))
         assert(not members['round-0-1'] and not members['obsolete-car-save-id'] and members['sleeping-root']==true)
         for i=1,32 do assert(members['round-100-'..i]==true) end
         assert(writes==0 and persisted.retired==nil)''')
    def test_prototype_retired_history_is_removed_on_first_vehicle_import(self):
        first=vm();first.execute("metadata.connection.a={kind='vehicle',key='car-one'};key=assert(E.hold(original,transfer,context))")
        saved=plain(first.globals().persisted);saved.pop('legacyMembership',None)
        saved['retired']={'car-one':{'retired-connection':True}}
        second=vm(saved,seed=False)
        second.execute('''local members=assert(E.members('car-one',{['retired-connection']=true,['connection-one']=true,sleeping=true}))
         assert(members['connection-one']==true and members.sleeping==true and not members['retired-connection'])
         assert(persisted.retired==nil and persisted.legacyMembership['car-one'].sleeping==true)''')
    def test_release_removes_sleeping_legacy_tail_without_touching_other_chain(self):
        l=vm();l.execute('''assert(E.members('car-one',{['connection-one']=true,child='connection-one',grandchild='child',other=true}))
         metadata.connection.a={kind='vehicle',key='car-one'};key=assert(E.hold(original,transfer,context))
         assert(E.release(key,destination,transfer,context));local members=E.members('car-one')
         assert(not members['connection-one'] and not members.child and not members.grandchild and members.other==true)''')
    def test_failed_first_membership_import_does_not_claim_vehicle(self):
        l=vm();l.execute('''failWrite=true;assert(not E.members('car-one',{sleeping=true}) and persisted==nil)
         failWrite=nil;assert(E.members('car-one',{sleeping=true}).sleeping==true)''')

class PersistenceReadContractTests(unittest.TestCase):
    """Lua-visible read outcomes: ok / missing / error / unsupported."""
    def test_read_failure_is_not_an_empty_journal(self):
        for role in ('sp','server'):
            for backend in ('envelope','legacy'):
                with self.subTest(role=role,backend=backend):
                    l=vm(role=role);l.globals().backend=backend
                    l.execute(r'''
                        resets=0
                        CVPEquipmentPersistence.resetInvalidStore=function() resets=resets+1;return {version=2,rows={}} end
                        if backend=='envelope' then
                            CVPEquipmentPersistence.readEnvelope=function() return {status='error',reason='disk unavailable'} end
                        else
                            CVPEquipmentPersistence.read=function() error('disk unavailable') end
                        end
                        local key,err=E.hold(original,transfer)
                        assert(not key and err and string.find(err,'disk unavailable'),tostring(err))
                        assert(resets==0 and transfers==0 and original.owner==source and #source.rows==1)
                    ''')
    def test_malformed_read_envelope_is_a_read_error(self):
        l=vm();l.execute(r'''
            resets=0
            CVPEquipmentPersistence.resetInvalidStore=function() resets=resets+1;return {version=2,rows={}} end
            CVPEquipmentPersistence.readEnvelope=function() return true end
            local key,err=E.hold(original,transfer)
            assert(not key and err and resets==0 and transfers==0 and #source.rows==1)
            CVPEquipmentPersistence.readEnvelope=function() return {status='ok',data='not a table'} end
            key,err=E.hold(original,transfer)
            assert(not key and err and resets==0 and transfers==0 and #source.rows==1)
            CVPEquipmentPersistence.readEnvelope=function() return {status='surprise'} end
            key,err=E.hold(original,transfer)
            assert(not key and err and resets==0 and transfers==0 and #source.rows==1)
        ''')
    def test_missing_journal_is_a_normal_first_run(self):
        for role in ('sp','server'):
            l=vm(role=role);l.execute(r'''
                CVPEquipmentPersistence.readEnvelope=function() return {status='missing',reason='equipment ledger missing'} end
                key=assert(E.hold(original,transfer))
                assert(persisted.rows[key].state=='held' and E.get(key)==original and #source.rows==0)
                assert(E.release(key,destination,transfer) and destination.rows[1]==original)
            ''')
    def test_unsupported_outcomes_never_reset_or_erase_the_journal(self):
        l=vm({'version':99,'rows':{}});l.execute(r'''
            resets=0
            CVPEquipmentPersistence.resetInvalidStore=function() resets=resets+1;return {version=2,rows={}} end
            CVPEquipmentPersistence.readEnvelope=function() return {status='unsupported',reason='unsupported equipment ledger world version'} end
            local key,err=E.hold(original,transfer)
            assert(not key and err and string.find(err,'unsupported'),tostring(err))
            assert(resets==0 and transfers==0 and persisted.version==99)
        ''')
        # A successful read of an unknown schema is still unsupported, never corruption.
        l=vm({'version':99,'rows':{}});l.execute(r'''
            resets=0
            CVPEquipmentPersistence.resetInvalidStore=function() resets=resets+1;return {version=2,rows={}} end
            CVPEquipmentPersistence.readEnvelope=function() return {status='ok',data=clone(persisted)} end
            local key,err=E.hold(original,transfer)
            assert(not key and err and string.find(err,'unsupported'),tostring(err))
            assert(resets==0 and transfers==0 and persisted.version==99)
        ''')
    def test_established_corruption_still_backs_up_and_resets_once(self):
        l=vm({'version':2,'rows':{'bad':{'state':'held'}}});l.execute(r'''
            resets,backup=0,nil
            CVPEquipmentPersistence.readEnvelope=function() return {status='ok',data=clone(persisted)} end
            CVPEquipmentPersistence.resetInvalidStore=function()
                resets=resets+1;backup=clone(persisted)
                persisted={version=2,rows={}}
                return clone(persisted)
            end
            key=assert(E.hold(original,transfer))
            assert(resets==1 and backup.rows.bad and persisted.rows[key].state=='held')
        ''')
    def test_failed_corruption_backup_keeps_the_original_journal(self):
        l=vm({'version':2,'rows':{'bad':{'state':'held'}}});l.execute(r'''
            CVPEquipmentPersistence.readEnvelope=function() return {status='ok',data=clone(persisted)} end
            CVPEquipmentPersistence.resetInvalidStore=function() error('backup refused') end
            local key,err=E.hold(original,transfer)
            assert(not key and err and string.find(err,'backup refused'),tostring(err))
            assert(transfers==0 and original.owner==source and persisted.rows.bad.state=='held')
        ''')

class PersistenceCapabilityTests(unittest.TestCase):
    """An installed bridge that cannot be verified must fail before any ledger IO."""
    def test_incompatible_bridge_stops_before_any_io(self):
        for role in ('sp','server'):
            with self.subTest(role=role):
                l=vm(role=role)
                l.execute(r'''
                    checks,resets=0,0
                    CVPEquipmentPersistence.capabilities=function()
                        checks=checks+1
                        return {ok=false,status='incompatible',
                            reason='missing field zombie.savefile.ServerPlayerDB.charactersToSave',
                            ledgerFormat='CVPEQ1',worldVersion=42,features={}}
                    end
                    CVPEquipmentPersistence.resetInvalidStore=function() resets=resets+1;return {version=2,rows={}} end
                    local key,err=E.hold(original,transfer)
                    assert(not key and err and string.find(err,'equipment bridge incompatible',1,true),tostring(err))
                    assert(string.find(err,'charactersToSave',1,true))
                    assert(checks==1 and backendCalls==0 and writes==0 and resets==0 and transfers==0)
                    assert(original.owner==source and #source.rows==1 and persisted==nil)
                    local got,why=E.get('missing-key')
                    assert(not got and why and string.find(why,'equipment bridge incompatible',1,true))
                    assert(checks==1 and backendCalls==0)
                ''')
    def test_incompatible_bridge_reason_is_printed_once(self):
        l=vm();l.execute(r'''
            logs={}
            print=function(message)
                if type(message)=='string' and string.find(message,'[CVP equipment]',1,true) then logs[#logs+1]=message end
            end
            CVPEquipmentPersistence.capabilities=function()
                return {ok=false,status='incompatible',
                    reason='missing class zombie.network.ServerPlayersVehicles',features={}}
            end
            for i=1,5 do
                local key,err=E.hold(original,transfer)
                assert(not key and err and string.find(err,'equipment bridge incompatible',1,true))
            end
            assert(#logs==1,tostring(#logs))
            assert(string.find(logs[1],'equipment bridge incompatible',1,true))
            assert(string.find(logs[1],'ServerPlayersVehicles',1,true))
        ''')
    def test_broken_capability_probe_fails_closed(self):
        for value in ("return nil", "return 'unexpected'", "error('probe failed')"):
            with self.subTest(value=value):
                l=vm()
                l.execute("CVPEquipmentPersistence.capabilities=function() "+value+" end")
                l.execute(r'''
                    local key,err=E.hold(original,transfer)
                    assert(not key and err and string.find(err,'equipment bridge incompatible',1,true),tostring(err))
                    assert(backendCalls==0 and writes==0 and transfers==0 and #source.rows==1)
                ''')
    def test_healthy_capability_table_allows_normal_operations(self):
        for role in ('sp','server'):
            l=vm(role=role);l.execute(r'''
                checks=0
                CVPEquipmentPersistence.capabilities=function()
                    checks=checks+1
                    return {ok=true,status='ok',ledgerFormat='CVPEQ1',worldVersion=42,
                        features={bridge=true,ledger=true,playerCheckpointMp=true,playerCheckpointSp=true,
                            squareCheckpointMp=true,squareCheckpointSp=true,skeletonLifetime=true,worldVersion=true}}
                end
                key=assert(E.hold(original,transfer))
                assert(E.get(key)==original and persisted.rows[key].state=='held')
                assert(checks==1 and backendCalls==1)
                assert(E.release(key,destination,transfer) and destination.rows[1]==original)
            ''')
    def test_old_jar_without_capabilities_uses_documented_fallback(self):
        l=vm();l.execute(r'''
            key=assert(E.hold(original,transfer))
            local bridge=CVPEquipmentRuntime.bridge
            assert(bridge and bridge.ok and bridge.legacy==true and bridge.status=='legacy')
            assert(persisted.rows[key].state=='held')
        ''')
    def test_capability_probe_is_cached_across_operations_and_reload(self):
        l=vm();l.execute(r'''
            checks=0
            CVPEquipmentPersistence.capabilities=function()
                checks=checks+1
                return {ok=true,status='ok',features={}}
            end
            key=assert(E.hold(original,transfer))
            for i=1,32 do assert(E.get(key)==original) end
            assert(E.release(key,destination,transfer))
            reload()
            assert(not E.get(key))
            assert(checks==1,tostring(checks))
        ''')

if __name__=='__main__': unittest.main()
