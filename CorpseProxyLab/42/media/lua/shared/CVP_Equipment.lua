-- Authoritative ledger. Pending snapshots are decoded only after the loaded
-- inventory owner is checked and its exact native save is acknowledged.
if isClient() and not isServer() then return end
local E={}
local SaveJobs=require 'CVP_SaveJobs'
local Legacy=require 'CVP_Legacy'
local Data=require 'CVP_EquipmentData'
local materials,keyValid,copy,equal=Data.materials,Data.keyValid,Data.copy,Data.equal
local rowValid,validateStore=Data.rowValid,Data.validateStore
CVPEquipmentRuntime=CVPEquipmentRuntime or {}
local runtime=CVPEquipmentRuntime -- original instances survive Lua reload
local function authority() return not isClient() or isServer() end
local function owned(item,c)
    return c and item and item:getContainer()==c and c:getItems():contains(item) and c:getItemWithID(item:getID())==item
end
-- Only simulation reads share this index. Transfers retain the full ownership
-- check, and every tick rebuilds it from the actual hidden container.
function E.beginRead() runtime.reading=true;runtime.readIndex=nil end
function E.endRead() runtime.reading=nil;runtime.readIndex=nil end
local function heldOwned(item,c,readOnly)
    if not readOnly or not runtime.reading then return owned(item,c) end
    if not item or item:getContainer()~=c then return false end
    local items=c:getItems()
    if not runtime.readIndex or runtime.readSize~=items:size() then
        local ids={}
        for i=0,items:size()-1 do local v=items:get(i);local id=v:getID()
            if ids[id]==nil then ids[id]=v else ids[id]=false end
        end
        runtime.readIndex=ids;runtime.readSize=items:size()
    end
    return runtime.readIndex[item:getID()]==item
end
local function decode(row)
    local ok,item=pcall(CVPItemNative.decode,row.payload)
    if not ok or not item or item:getContainer() or item:getWorldItem() or item:getID()~=row.id or item:getFullType()~=row.type then return nil,'invalid equipment snapshot' end
    return item
end
local function index(r,graphIndex)
    r.ids={};r.bodies={};r.members=copy(r.data.legacyMembership or {})
    for key,row in pairs(r.data.rows) do
        if row.state~='released' then r.ids[row.id]=key end
        if row.bodyKey then r.bodies[row.bodyKey]=key elseif row.legacy then r.bodies[row.legacy.bodyKey]=key end
        local md=row.metadata;local vehicle=Legacy.vehicleKey(md)
        if vehicle then
            r.members[vehicle]=r.members[vehicle] or {}
            if row.state=='released' or md.ended then
                r.members[vehicle][md.connection.id]=nil
            else r.members[vehicle][md.connection.id]=md.parentConnection or true end
        end
    end
    r.graphIndex=graphIndex
end
local function prepare()
    if not authority() then return nil,'equipment store is authoritative only' end
    if not CVPEquipmentPersistence or not CVPItemNative or not ItemContainer then return nil,'equipment backend unavailable' end
    if runtime.data then
        if (runtime.data.version~=2 and runtime.data.version~=3) or type(runtime.data.rows)~='table' then return nil,'invalid equipment store' end
        return runtime
    end
    local ok,data=pcall(CVPEquipmentPersistence.read)
    if not ok then return nil,tostring(data) end
    if data==nil then data={version=2,rows={}} end
    -- Only a successfully read, known schema may be reset here. IO/backend
    -- failures and future versions remain errors, never a reason to erase data.
    if type(data)=='table' and data.version~=2 and data.version~=3 then return nil,'unsupported equipment store version' end
    local checked,shadow,reason,graphIndex=pcall(validateStore,data)
    if not checked or not shadow then
        if not CVPEquipmentPersistence.resetInvalidStore then return nil,tostring(checked and reason or shadow) end
        local reset,fresh=pcall(CVPEquipmentPersistence.resetInvalidStore)
        if not reset or type(fresh)~='table' then return nil,'equipment recovery failed: '..tostring(fresh) end
        data=fresh
        local valid,problem,idx=validateStore(data);if not valid then return nil,problem end;shadow=valid;graphIndex=idx
    end
    local good,container=pcall(ItemContainer.new);if not good or not container then return nil,'equipment container unavailable' end
    runtime.data=data;runtime.shadow=shadow;runtime.container=container;runtime.items={};runtime.owners={};runtime.retry={};index(runtime,graphIndex)
    return runtime
end
local function write(r,data)
    r.readIndex=nil
    local graphIndex
    if data.version==3 then
        local ready,problem,idx=require('CVP_LinkClocks').reconcile(data);if not ready then return false,problem end
        graphIndex=idx
    end
    local shadow,reason,idx=validateStore(data,graphIndex);if not shadow then return false,reason end
    local ok,result=SaveJobs.call('write',data)
    if not ok or result==false then return false,tostring(result) end
    r.data=data;r.shadow=shadow;index(r,idx);return true
end
local function replace(r,key,row)
    local data=copy(r.data);data.rows[key]=row
    if row then Legacy.forgetLegacy(data,row.metadata) end
    return write(r,data)
end
local function current(r,key,bodyKey)
    local row=r.data.rows[key]
    if not row then return nil,'equipment not found' end
    -- The shadow is fully validated on load/write. Exact equality still detects
    -- any later edit, without rescanning the encoded item on every tick.
    if not equal(row,r.shadow.rows[key]) then return nil,'equipment snapshot changed' end
    if bodyKey and row.bodyKey~=bodyKey and not (row.legacy and row.legacy.bodyKey==bodyKey) then return nil,'equipment body mismatch' end
    return row
end
local function getHeld(r,key,bodyKey,readOnly)
    local row,err=current(r,key,bodyKey);if not row then return nil,err end
    if row.state~='held' then return nil,'equipment transfer '..row.state..'; recovery required' end
    local item=r.items[key]
    if not item then
        item,err=decode(row);if not item then return nil,err end
        local ok=pcall(r.container.AddItem,r.container,item)
        r.readIndex=nil
        if not ok or not owned(item,r.container) then return nil,'equipment container rejected restore' end
        r.items[key]=item
    end
    if not heldOwned(item,r.container,readOnly) then return nil,'equipment ownership conflict' end
    return item
end
local function checkpoint(owner)
    local object=owner.kind=='player' and owner.object or owner.square
    if not object then return false,'equipment owner unavailable' end
    local ok,result=SaveJobs.call(owner.kind=='player' and 'checkpointPlayer' or 'checkpointSquare',object)
    if not ok or result~=true then runtime.retryAfter=(getTimestampMs and getTimestampMs() or 0)+5000 end
    return ok and result==true,not ok and tostring(result) or result~=true and 'equipment checkpoint not acknowledged' or nil
end
local function describe(c,body,ground,square)
    if ground then
        local sq=square or body and body:getSquare();if not sq then return nil,'equipment ground unavailable' end
        return {kind='ground',x=sq:getX(),y=sq:getY(),z=sq:getZ()},{kind='ground',square=sq}
    end
    local p=c and c.getCharacter and c:getCharacter()
    if p then
        local ok,key=SaveJobs.call('playerKey',p)
        if not ok or not keyValid(key) then return nil,'equipment player identity unavailable' end
        return {kind='player',key=key},{kind='player',object=p,container=p:getInventory()}
    end
    if body and c==body:getContainer() and body:getSquare() and keyValid(body:getModData().CVPBodyKey) then
        return {kind='body',key=body:getModData().CVPBodyKey},{kind='body',object=body,container=c,square=body:getSquare()}
    end
    return nil,'equipment owner unavailable'
end
local function matches(desc,owner)
    if not owner or owner.kind~=desc.kind then return false end
    if desc.kind=='player' then
        local ok,key=SaveJobs.call('playerKey',owner.object);return ok and key==desc.key
    elseif desc.kind=='body' then return owner.object:getSquare() and owner.object:getModData().CVPBodyKey==desc.key
    else return owner.square and owner.square:getX()==desc.x and owner.square:getY()==desc.y and owner.square:getZ()==desc.z end
end
local function find(owner,id)
    if owner.kind=='ground' then
        local objects=owner.square:getWorldObjects();local found
        for n=0,objects:size()-1 do local o=objects:get(n);local item=o:getItem()
            if item and item:getID()==id then if found then return nil,'duplicate equipment owner' end;found=item end
        end
        return found
    end
    local c=owner.container
    return c.getItemWithIDRecursiv and c:getItemWithIDRecursiv(id) or c:getItemWithID(id)
end
local function move(item,source,destination,transfer)
    transfer=transfer or require('CVP_Core').transfer
    local ok,accepted,err=pcall(transfer,item,source,destination)
    if not ok then return false,tostring(accepted) end
    if accepted~=true then return false,err or 'equipment transfer rejected' end
    if not owned(item,destination) or source:getItems():contains(item) then return false,'equipment transfer not confirmed' end
    return true
end
local function finish(r,key,release)
    local data=copy(r.data);local row=data.rows[key]
    -- A completed return/canceled take removes only this connection, never its
    -- neighbours. Keeping the graph until acknowledgement makes retries visible.
    local linkID=r.graphIndex and r.graphIndex.equipment[key]
    local link=linkID and data.graph.links[linkID]
    local keep=false
    if link and row.tailOriginal and not release then
        data.graph.links[linkID]=nil
        data.graph.links[row.tailOriginal.id]=copy(row.tailOriginal)
        data.graph.revision=data.graph.revision+1
    elseif link and link.extension and not release and link.extension==key then
        -- A rejected second take restores the original section exactly.
        link.extension=nil;link.length=assert(row.extensionLength);link.revision=link.revision+1
        data.graph.revision=data.graph.revision+1
    elseif link and link.extension and release then
        -- Retain both claims until both original items are acknowledged. A
        -- restart after the first return must not forget the second rope.
        assert(link.returning,'connection return was not prepared')
        keep=true;row.state='released';row.owner=nil;row.receipt=nil
        local first,second=data.rows[link.equipment],data.rows[link.extension]
        if first.state=='released' and second.state=='released' then
            data.graph.links[linkID]=nil;data.graph.revision=data.graph.revision+1
            for _,k in ipairs({link.equipment,link.extension}) do
                local entry=data.rows[k];if not entry.bodyKey and not entry.legacy then data.rows[k]=nil end
            end
        end
    elseif link then
        -- A ground return hands back the one original behind every reservation.
        local spool=r.graphIndex.spools[key]
        for _,id in ipairs(spool and spool.ids or {linkID}) do data.graph.links[id]=nil end
        data.graph.revision=data.graph.revision+1
    end
    if release then Legacy.markTail(data,row.metadata) end
    Legacy.forgetLegacy(data,row.metadata)
    row.state='released';row.owner=nil;row.receipt=nil
    -- Retain a tombstone until the corpse has durably forgotten its key.
    if not keep and not row.bodyKey and not row.legacy then data.rows[key]=nil end
    local ok,err=write(r,data);if ok then r.items[key]=nil;r.owners[key]=nil end;return ok,err
end
-- Stored in the same native player snapshot as the inventory. A positive
-- receipt proves a transfer even when its item was subsequently moved elsewhere.
local function receipt(row,owner,value)
    if not row.receipt then return nil end
    local md=owner.object:getModData()
    local receipts=md.CVPEquipmentReceipts
    if receipts~=nil and type(receipts)~='table' then error('invalid equipment receipts') end
    if value~=nil then
        if not receipts then receipts={};md.CVPEquipmentReceipts=receipts end
        receipts[row.receipt]=value or nil
    end
    return receipts and receipts[row.receipt]==true or false
end
local function clearReceipt(row,owner)
    if row.receipt then receipt(row,owner,false) end
end
local function recoverOne(r,key,owner)
    local row,err=current(r,key);if not row then return false,err end
    if row.state~='taking' and row.state~='returning' and row.state~='unresolved' then return false,'equipment is not pending' end
    if not row.owner or not matches(row.owner,owner) then return false,'equipment owner unavailable' end
    local item,why=find(owner,row.id);if why then return false,why end
    if item and item:getFullType()~=row.type then return false,'equipment owner identity conflict' end
    local original=r.items[key]
    local taking=row.state=='taking' or row.operation=='taking'
    local transferred=receipt(row,owner)
    local duplicate=item and original and original~=item and owned(original,r.container)
    -- A reloaded pre-take inventory wins over a volatile escrow copy only for
    -- receipt-aware transactions. Old ambiguous claims keep their strict guard.
    local cancelledTake=duplicate and row.receipt and taking and not transferred
    if duplicate and not cancelledTake then return false,'duplicate equipment owner' end
    if taking and transferred and item then return false,'equipment receipt conflicts with inventory' end
    local delivered=not taking and transferred
    local canRestore=taking and transferred
    if not item and not delivered and not canRestore and not owned(original,r.container)
        and not (original and not original:getContainer() and not original:getWorldItem()) then
        return false,'equipment transfer outcome unresolved'
    end
    local ok,reason=checkpoint(owner);if not ok then return false,reason end
    -- Never finish from an owner sample taken before a yielding save.
    if not matches(row.owner,owner) then return false,'equipment owner unavailable' end
    local currentItem,conflict=find(owner,row.id)
    if conflict or currentItem~=item or receipt(row,owner)~=transferred then
        return false,conflict or 'equipment transfer outcome unresolved'
    end
    if item or delivered then
        local done,why=finish(r,key,not taking)
        if done then
            if cancelledTake then r.container:Remove(original) end
            clearReceipt(row,owner)
        end
        return done,why
    end
    if not original and canRestore then
        original,reason=decode(row);if not original then return false,reason end
        r.items[key]=original
    end
    if not owned(original,r.container) then
        local added=pcall(r.container.AddItem,r.container,original)
        if not added or not owned(original,r.container) then return false,'equipment container rejected recovery' end
    end
    local updated=copy(row);updated.state='held';updated.owner=nil;updated.operation=nil;updated.extensionLength=nil;updated.tailOriginal=nil;updated.receipt=nil
    local done,why=replace(r,key,updated)
    if done then clearReceipt(row,owner) end
    return done,why
end
function E.hold(item,transfer,context)
    local r,err=prepare();if not r then return nil,err end
    if not item or not materials[item:getFullType()] then return nil,'unsupported equipment' end
    local source=item:getContainer()
    if item:getWorldItem() or not source or source:getType()=='floor' or not owned(item,source) or r.ids[item:getID()] then return nil,'equipment ownership conflict' end
    local ok,payload=pcall(CVPItemNative.encode,item);if not ok then return nil,tostring(payload) end
    local row={id=item:getID(),type=item:getFullType(),payload=payload,state='held'}
    if not rowValid(row) then return nil,'invalid equipment snapshot' end
    local checked,why=decode(row);if not checked then return nil,why end
    local key=getRandomUUID();if not keyValid(key) or r.data.rows[key] then return nil,'equipment key collision' end
    local body=context and context.body;local md=context and context.metadata
    if context and (context.link or context.extend) and (body or md)
        or context and context.link and context.extend then return nil,'mixed equipment binding' end
    if body or md then
        if not body or not md or not md.connection or not md.connection.b or not keyValid(md.connection.b.key)
            or body:getModData().CVPBodyKey~=md.connection.b.key or not body:getSquare() or r.bodies[md.connection.b.key] then return nil,'equipment body conflict' end
        row.bodyKey=md.connection.b.key;local copied,binding=pcall(copy,md);if not copied then return nil,tostring(binding) end
        binding.version=3;binding.equipmentKey=key;row.metadata=binding
        local saved,reason=checkpoint({kind='body',square=body:getSquare()});if not saved then return nil,reason end
    end
    local owner,live=describe(source,body);if not owner then return nil,live end;row.owner=owner;row.state='taking';row.operation='taking'
    if owner.kind=='player' then row.receipt=key end
    local saved,reason
    if context and context.extend then
        local spec=context.extend;local G=require('CVP_LinkGraph');local original=r.data.graph and r.data.graph.links[spec.id]
        if not original or row.type~='Base.Rope' then return nil,'only one extra rope' end
        local ready,problem=E.linkReady(original);if not ready then return nil,problem end
        local graph,why=G.extend(r.data.graph,spec.id,spec.revision,key,spec.owner,spec.allowOthers)
        if not graph then return nil,why end
        row.extensionLength=original.length
        local data=copy(r.data);data.graph=graph;data.rows[key]=row;saved,reason=write(r,data)
    elseif context and context.tail then
        local spec=context.tail;local G=require('CVP_LinkGraph')
        if row.type~='Base.Rope' then return nil,'material unavailable' end
        local original=r.data.graph and r.data.graph.links[spec.id]
        if not original then return nil,'stale connection' end
        local ready,problem=E.linkReady(original);if not ready then return nil,problem end
        row.tailOriginal=copy(original)
        local graph,why=G.joinTail(r.data.graph,spec.id,spec.revision,spec.side,spec.target,key,
            spec.owner,spec.allowOthers,spec.maxBodies,spec.opposite)
        if not graph then return nil,why end
        local data=copy(r.data);data.graph=graph;data.rows[key]=row;saved,reason=write(r,data)
    elseif context and context.link then
        local spec=context.link;local G=require('CVP_LinkGraph')
        local graph,why=G.create(r.data.graph or G.empty(),spec.id,spec.a,spec.b,key,row.type,spec.owner,spec.maxBodies,spec.shared)
        if not graph then return nil,why end
        local data=copy(r.data);data.version=3;data.graph=graph;data.rows[key]=row
        saved,reason=write(r,data)
    else saved,reason=replace(r,key,row) end
    if not saved then return nil,reason end
    r.items[key]=item;r.owners[key]=live
    -- A save may outlive the player connection. Never mutate its stale inventory.
    if not matches(row.owner,live) then return key,'equipment owner unavailable' end
    -- The player can change/move an item while the durable intent is being written.
    local encoded,currentPayload=pcall(CVPItemNative.encode,item)
    if not encoded or currentPayload~=payload then
        local resolved,reason=recoverOne(r,key,live)
        if resolved then return nil,'equipment snapshot changed' end
        return key,reason
    end
    local moved,failure=move(item,source,r.container,transfer)
    if not moved then
        if owned(item,r.container) then move(item,r.container,source,transfer) end
        if owned(item,source) then
            local resolved,reason=recoverOne(r,key,live)
            if resolved then return nil,failure end
            local unresolved=copy(r.data.rows[key]);unresolved.state='unresolved';replace(r,key,unresolved)
            return key,reason
        end
        return key,failure
    end
    receipt(row,live,true)
    local resolved,reason=recoverOne(r,key,live)
    if not resolved then return key,reason end
    return key
end
function E.get(key,bodyKey)
    local r,err=prepare();if not r then return nil,err end
    return getHeld(r,key,bodyKey,true)
end
function E.linkReady(link)
    if link.returning then return nil,'equipment return pending' end
    local item,why=E.get(link.equipment);if not item then return nil,why end
    if link.extension then local extra,err=E.get(link.extension);if not extra then return nil,err end end
    return item
end
function E.release(key,destination,transfer,context)
    local r,err=prepare();if not r then return false,err end
    local row,why=current(r,key);if not row then return false,why end
    local linkID=r.graphIndex and r.graphIndex.equipment[key]
    if linkID then
        local spool=r.graphIndex.spools[key]
        local ground=context and context.square and destination==nil
            and require('CVP_GroundRope').eligible(r.data.graph,r.graphIndex,key)
        if spool and #spool.ids>1 and not ground then return false,'connection still bound' end
        local expected=context and context.link
        if not expected or expected.id~=linkID or expected.revision~=r.data.graph.links[linkID].revision then return false,'connection still bound' end
        if r.data.graph.links[linkID].extension and not r.data.graph.links[linkID].returning then return false,'connection return required' end
    end
    local body=context and context.body
    if body and row.bodyKey~=body:getModData().CVPBodyKey then return false,'equipment body mismatch' end
    local item,reason=getHeld(r,key);if not item then return false,reason end
    if destination==r.container or destination and destination:getType()=='floor' then return false,'invalid equipment destination' end
    local owner,live=describe(destination,body,destination==nil,context and context.square);if not owner then return false,live end
    local present,conflict=find(live,row.id);if present or conflict then return false,'equipment destination conflict' end
    local updated=copy(row);updated.state='returning';updated.operation='returning';updated.owner=owner
    updated.receipt=owner.kind=='player' and getRandomUUID() or nil
    local oldShape
    if context and context.shape then
        oldShape=item:getModData().CVPGroundRope;item:getModData().CVPGroundRope=context.shape
        local ok,payload=pcall(CVPItemNative.encode,item)
        if not ok or type(payload)~='string' or #payload>22000 then
            item:getModData().CVPGroundRope=oldShape;return false,'ground equipment snapshot rejected'
        end
        updated.payload=payload
    end
    local saved,failure=replace(r,key,updated)
    if not saved then if context and context.shape then item:getModData().CVPGroundRope=oldShape end;return false,failure end
    r.owners[key]=live
    if not matches(updated.owner,live) then return false,'equipment owner unavailable' end
    local moved,moveError
    if destination then moved,moveError=move(item,r.container,destination,transfer)
    else
        moved,moveError=pcall(function()
            r.container:Remove(item);assert(not item:getContainer() and not r.container:getItems():contains(item),'equipment remove refused')
            live.square:AddWorldInventoryItem(item,0.5,0.5,0)
            assert(item:getWorldItem() and find(live,item:getID())==item,'equipment ground transfer not confirmed')
            if triggerEvent then triggerEvent('OnObjectAdded',item:getWorldItem()) end
        end)
    end
    local resolved,problem
    if moved then
        receipt(updated,live,true)
        resolved,problem=recoverOne(r,key,live)
    end
    -- A delivered player item may already have left this inventory. Keep its
    -- receipt and intent; do not compensate through an offline/stale actor.
    if moved and not resolved and updated.receipt then return false,problem end
    if not moved or not resolved then
        -- A failed call returns control to a player who can move the delivered
        -- item. Bring back the exact original before permitting absent recovery.
        if destination and owned(item,destination) then move(item,destination,r.container,transfer) end
        if not item:getContainer() and not item:getWorldItem() then pcall(r.container.AddItem,r.container,item) end
        if owned(item,r.container) and not find(live,row.id) then
            local ack,ackError=checkpoint(live)
            if ack then
                local restored,writeError=replace(r,key,copy(row))
                return false,not restored and writeError or moveError or problem
            end
            problem=ackError
        end
        local unresolved=copy(r.data.rows[key]);unresolved.state='unresolved'
        local marked,writeError=replace(r,key,unresolved)
        return false,not marked and writeError or moveError or problem
    end
    if body then E.observeBody(body) end
    return true
end
-- Called on the authority's slow discovery path. The square checkpoint and
-- ledger recovery above remain the only hand-off of ownership to the world.
-- Read the current working graph: persisted endpoint coordinates can lag behind it.
-- A real return still requires a successful flush before dropFree mutates the ledger.
function E.hasFreeWork(graph,idx)
    local r,err=prepare();if not r then return nil,err end
    local Ground=require 'CVP_GroundRope'
    for key in pairs(idx.equipment) do
        local row=r.data.rows[key]
        if row and ((row.state=='returning' or row.state=='unresolved') and row.owner and row.owner.kind=='ground'
            or row.state=='held' and Ground.eligible(graph,idx,key)) then return true end
    end
    return false
end
function E.dropFree()
    local r,err=prepare();if not r then return false,err end
    local Ground=require 'CVP_GroundRope';local keys={}
    for key in pairs(r.graphIndex and r.graphIndex.equipment or {}) do keys[#keys+1]=key end
    table.sort(keys)
    local failure
    for _,key in ipairs(keys) do
        local row=r.data.rows[key];local idx=r.graphIndex
        if row and idx.equipment[key] then
            if row.state=='returning' or row.state=='unresolved' then
                local owner=row.owner
                if owner and owner.kind=='ground' then
                    local sq=getCell():getGridSquare(owner.x,owner.y,owner.z)
                    if sq then local ok,why=recoverOne(r,key,{kind='ground',square=sq});if not ok then failure=why end end
                end
            elseif row.state=='held' and Ground.eligible(r.data.graph,idx,key) then
                local shape,x,y,z=Ground.recipe(r.data.graph,idx,key)
                local sq=getCell():getGridSquare(x,y,z)
                if sq then
                    local id=idx.equipment[key];local link=r.data.graph.links[id]
                    if link.extension and not link.returning then
                        local data=copy(r.data);data.graph.links[id].returning=true
                        data.graph.links[id].revision=link.revision+1;data.graph.revision=data.graph.revision+1
                        local ok,why=write(r,data);if not ok then return false,why end
                    end
                    local ok,why=E.release(key,nil,nil,{square=sq,shape=shape,
                        link={id=id,revision=r.data.graph.links[id].revision}})
                    if not ok then failure=why end
                end
            end
        end
    end
    return failure==nil,failure
end
function E.releaseLink(id,revision,destination,transfer)
    local r,err=prepare();if not r then return false,err end
    local link=r.data.graph and r.data.graph.links[id]
    if not link or link.revision~=revision then return false,'stale connection' end
    local spool=r.graphIndex.spools[link.equipment]
    if spool and #spool.ids>1 then
        local ready,why=E.linkReady(link);if not ready then return false,why end
        -- Delete only this reservation; the single original stays in escrow.
        local data=copy(r.data);data.graph.links[id]=nil;data.graph.revision=data.graph.revision+1
        return write(r,data)
    end
    if not link.extension then return E.release(link.equipment,destination,transfer,{link={id=id,revision=revision}}) end
    if not link.returning then
        local ready,why=E.linkReady(link);if not ready then return false,why end
        local data=copy(r.data);local row=data.graph.links[id]
        row.returning=true;row.revision=row.revision+1;data.graph.revision=data.graph.revision+1
        for _,side in ipairs({'a','b'}) do if row[side].kind=='held' then row[side].kind='ground';row[side].holder=nil end end
        local ok,problem=write(r,data);if not ok then return false,problem end
    end
    for _,key in ipairs({link.equipment,link.extension}) do
        if not r.data.graph.links[id] then return true end
        local row,why=current(r,key);if not row then return false,why end
        if row.state~='held' and row.state~='released' then
            local desc,live=describe(destination)
            if not desc then return false,live end
            local ok,problem=recoverOne(r,key,live);if not ok then return false,problem end
            row=r.data.rows[key]
        end
        if row and row.state~='released' then
            local ok,problem=E.release(key,destination,transfer,{link={id=id,revision=r.data.graph.links[id].revision}})
            if not ok then return false,problem end
        end
    end
    return true
end
function E.recover(owner)
    local r,err=prepare();if not r then return false,err end
    local live
    if owner and owner.getInventory then live={kind='player',object=owner,container=owner:getInventory()}
    elseif owner and owner.getContainer and owner.getModData and owner.getSquare then live={kind='body',object=owner,container=owner:getContainer(),square=owner:getSquare()}
    elseif owner and owner.getCharacter then local p=owner:getCharacter();if p then live={kind='player',object=p,container=p:getInventory()} end end
    if not live then return false,'equipment owner unavailable' end
    local keys={};for key,row in pairs(r.data.rows) do if row.owner and matches(row.owner,live) then keys[#keys+1]=key end end
    for _,key in ipairs(keys) do r.owners[key]=live end
    for _,key in ipairs(keys) do
        local ok,why=recoverOne(r,key,live);if not ok then return false,why end
    end
    -- A crash can occur after journal completion but before receipt cleanup.
    if live.kind=='player' then
        local md=live.object:getModData();local receipts=md.CVPEquipmentReceipts
        if type(receipts)=='table' then
            local pending={};for _,row in pairs(r.data.rows) do if row.receipt then pending[row.receipt]=true end end
            local kept={};local any=false
            for token,value in pairs(receipts) do if pending[token] then kept[token]=value;any=true end end
            md.CVPEquipmentReceipts=any and kept or nil
        end
    end
    return true
end
function E.observeBody(body)
    local r,err=prepare();if not r then return false,err end
    local md=body:getModData();local key=r.bodies[md.CVPBodyKey]
    if not key then
        local old=md.CVPTether
        if old~=nil then
            local valid,accepted=pcall(function() return require('CVP_World').valid(old) end)
            if r.data.discardLegacy or not valid or not accepted or old.ended or old.version==3 then md.CVPTether=nil end
        end
        return true
    end
    local row,reason=current(r,key,md.CVPBodyKey);if not row then return false,reason end
    if row.legacy then
        -- A graph import can precede the corpse's next chunk save. The ledger's
        -- marker prevents an old chunk from resurrecting the former attachment.
        local old=md.CVPTether
        if old then
            if type(old)~='table' or not old.connection or old.connection.id~=row.legacy.connection then return false,'legacy body marker conflict' end
            md.CVPTether=nil
        end
        local now=getTimestampMs and getTimestampMs() or 0
        if r.retry[key] and now<r.retry[key] then return false,'equipment recovery deferred' end
        local ok,why=checkpoint({kind='body',square=body:getSquare()})
        if not ok then r.retry[key]=now+5000;return false,why end
        local updated=copy(row);updated.legacy=nil
        if updated.state=='released' and not (r.graphIndex and r.graphIndex.equipment[key]) then updated=nil end
        local saved,err=replace(r,key,updated)
        if not saved then return false,err end;r.retry[key]=nil
        row=r.data.rows[key];if not row then return true end
    end
    -- Discovery can run for every visible corpse every frame. Failed native
    -- checkpoints get a bounded retry interval; held rows never checkpoint here.
    if row.state~='held' then
        local now=getTimestampMs and getTimestampMs() or 0
        if r.retryAfter and now<r.retryAfter or r.retry[key] and now<r.retry[key] then return false,'equipment recovery deferred' end
        r.retry[key]=now+5000
    end
    if row.state=='taking' or row.state=='returning' or row.state=='unresolved' then
        local owner=r.owners[key]
        if row.owner.kind=='body' and row.owner.key==md.CVPBodyKey then owner={kind='body',object=body,container=body:getContainer(),square=body:getSquare()}
        elseif row.owner.kind=='ground' then
            local sq=getCell():getGridSquare(row.owner.x,row.owner.y,row.owner.z);if sq then owner={kind='ground',square=sq} end
        end
        if owner then recoverOne(r,key,owner);row=r.data.rows[key] end
    end
    if not row then return true end
    if row.state=='released' then
        if r.graphIndex and r.graphIndex.equipment[key] then return true end
        if md.CVPTether then
            local old=md.CVPTether
            if old.equipmentKey==key or old.version==2 and old.connection and row.metadata and old.connection.id==row.metadata.connection.id then md.CVPTether=nil
            else return false,'equipment body metadata conflict' end
        end
        local ok,why=checkpoint({kind='body',square=body:getSquare()});if not ok then return false,why end
        local cleared,problem=replace(r,key,nil);if cleared then r.retry[key]=nil end;return cleared,problem
    end
    if row.metadata and (md.CVPTether==nil or md.CVPTether.equipmentKey==key or md.CVPTether.version==2) then
        if not equal(md.CVPTether,row.metadata) then md.CVPTether=copy(row.metadata) end
    end
    return true
end
-- A detached, unloaded body keeps its cumulative clock until its own chunk has
-- durably consumed it. A failed checkpoint/write leaves a retryable single row.
function E.observeClock(body,square)
    local r,err=prepare();if not r then return false,err end
    local key=body:getModData().CVPBodyKey
    local row=r.data.bodyClocks and r.data.bodyClocks[key]
    if not row or row.paused or r.graphIndex and r.graphIndex.byBody[key] then return true end
    local now=getTimestampMs();r.clockRetry=r.clockRetry or {}
    if r.clockRetry[key] and now<r.clockRetry[key] then return false,'body clock recovery deferred' end
    r.clockRetry[key]=now+5000
    if not CVPSkeletonNative then return false,'skeleton backend unavailable' end
    local ok,ready=pcall(CVPSkeletonNative.retire,body,row.epoch)
    if not ok or ready~=true then return false,'body clock not acknowledged' end
    local saved,why=checkpoint({kind='body',square=square or body:getSquare()});if not saved then return false,why end
    local data=copy(r.data);data.bodyClocks[key]=nil
    local saved,why=write(r,data);if saved then r.clockRetry[key]=nil end;return saved,why
end
function E.members(vehicle,legacyMembers)
    local r,err=prepare();if not r then return nil,err end
    if not keyValid(vehicle) then return nil,'invalid vehicle identity' end
    if r.data.discardLegacy then return {},nil,r.data end
    if not r.data.legacyMembership or r.data.legacyMembership[vehicle]==nil then
        local legacy={}
        if legacyMembers~=nil and type(legacyMembers)~='table' then return nil,'invalid legacy membership' end
        for id,parent in pairs(legacyMembers or {}) do
            if not keyValid(id) or parent~=true and not keyValid(parent) then return nil,'invalid legacy membership' end
            legacy[id]=parent
        end
        for _,row in pairs(r.data.rows) do local md=row.metadata
            if Legacy.vehicleKey(md)==vehicle then legacy[md.connection.id]=nil end
        end
        -- One-time migration of the unreleased prototype's retired-ID history.
        for id in pairs(r.data.retired and r.data.retired[vehicle] or {}) do legacy[id]=nil end
        local data=copy(r.data);data.legacyMembership=data.legacyMembership or {};data.legacyMembership[vehicle]=legacy
        if data.retired then
            data.retired[vehicle]=nil
            local empty=true;for _ in pairs(data.retired) do empty=false;break end
            if empty then data.retired=nil end
        end
        local saved,why=write(r,data);if not saved then return nil,why end
    end
    -- These maps are read-only for callers and rebuilt only on a ledger write.
    -- Once imported, the ledger wins over every older vehicle save.
    return r.members[vehicle] or {},nil,r.data
end
-- Detached connections are world-owned. Callers receive copies, never the ledger
-- or item payloads; compare-and-swap rejects stale commands from another client.
function E.links()
    local r,err=prepare();if not r then return nil,err end
    return copy(r.data.graph or require('CVP_LinkGraph').empty())
end
function E.linkRevision()
    local r,err=prepare();if not r then return nil,err end
    return r.data.graph and r.data.graph.revision or 0
end
function E.migrateLinks(entries)
    local r,err=prepare();if not r then return false,err end
    if #entries==0 then return true end
    local data,why=Legacy.import(copy(r.data),entries,function(key) return current(r,key) end,copy)
    if not data then return false,why end
    return write(r,data)
end
function E.editLinks(graph,expectedRevision)
    local r,err=prepare();if not r then return false,err end
    local old=r.data.graph or require('CVP_LinkGraph').empty()
    if old.revision~=expectedRevision or type(graph)~='table' or graph.revision~=expectedRevision+1 then return false,'stale graph' end
    local valid,why=require('CVP_LinkGraph').index(graph);if not valid then return false,why end
    -- Only a confirmed native return can delete a connection's equipment claim.
    for id,link in pairs(old.links) do
        if not graph.links[id] or graph.links[id].equipment~=link.equipment or graph.links[id].extension~=link.extension
            or graph.links[id].returning~=link.returning
            or graph.links[id].allocation~=link.allocation and not (link.allocation and graph.links[id].allocation
                and graph.links[id].allocation>=link.allocation) then return false,'equipment return required' end
    end
    for _,link in pairs(graph.links) do
        local previous=old.links[link.id];local dropped=false;local safe=previous and copy(previous)
        if not previous then
            local claim=r.graphIndex and r.graphIndex.equipment[link.equipment]
            local original=claim and old.links[claim]
            if not original or not original.allocation or not link.allocation or original.owner~=link.owner then
                return false,'equipment not available'
            end
        end
        if safe and link.revision==previous.revision+1 then
            for _,side in ipairs({'a','b'}) do
                if safe[side].kind=='held' and link[side].kind=='ground' then
                    safe[side].kind='ground';safe[side].holder=nil;dropped=true
                end
            end
            safe.revision=link.revision
        end
        local safeDrop=dropped and equal(safe,link)
        for _,key in ipairs({link.equipment,link.extension}) do
            local row,reason=current(r,key)
            if not row or row.bodyKey or row.state~='held' and not equal(link,previous) and not safeDrop then return false,reason or 'equipment not available' end
        end
    end
    local data=copy(r.data);data.version=3;data.graph=copy(graph)
    local saved,problem=write(r,data)
    return saved,problem,saved and valid or nil
end
return E
