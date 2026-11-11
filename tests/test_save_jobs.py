"""Persistence waits span ticks; ownership is still transferred by the existing ledger."""
import unittest
from test_equipment import vm, plain

DELAY = r"""
Jobs=require 'CVP_SaveJobs'
for _,name in ipairs({'write','playerKey','checkpointPlayer','checkpointSquare'}) do
 local method=name
 CVPEquipmentPersistence[method..'Async']=function(...)
  local args={...};return {run=function() return CVPEquipmentPersistence[method](unpack(args)) end,polls=0}
 end
end
CVPEquipmentPersistence.poll=function(t)
 t.polls=t.polls+1
 if t.polls<3 then return 0 end
 if not t.done then t.value=t.run();t.done=true end
 return 1
end
CVPEquipmentPersistence.result=function(t) assert(t.done);return t.value end
function drain(job)
 for i=1,100 do if Jobs.advance(job) then return end end
 error('job did not complete')
end
function holdJob()
 replies=0
 job=Jobs.new(function() local key,why=E.hold(original,transfer);return key~=nil and why==nil,key,why end,
 function(ok,key,why) replies=replies+1;answer={ok=ok,key=key,why=why} end,
 function() return cancelled and 'cancelled' end)
end
"""

class SaveJobTests(unittest.TestCase):
 def test_durable_intent_precedes_transfer_and_ack_precedes_completion_sp_mp(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    local events={};local write=CVPEquipmentPersistence.write
    CVPEquipmentPersistence.write=function(data)
     local state='empty';for _,row in pairs(data.rows) do state=row.state end
     events[#events+1]='write:'..state;return write(data)
    end
    local checkpoint=CVPEquipmentPersistence.checkpointPlayer
    CVPEquipmentPersistence.checkpointPlayer=function(p)
     events[#events+1]='checkpoint';return checkpoint(p)
    end
    local move=transfer;transfer=function(...)
     events[#events+1]='transfer';return move(...)
    end
    holdJob();drain(job);assert(answer.ok)
    assert(table.concat(events,',')=='write:taking,transfer,checkpoint,write:held')
    events={}
    local returning=Jobs.new(function() return E.release(answer.key,destination,transfer) end,
     function(ok) assert(ok);events[#events+1]='reply' end)
    drain(returning)
    assert(table.concat(events,',')=='write:returning,transfer,checkpoint,write:empty,reply')
    assert(destination.rows[1]==original and #source.rows==0)
   """)

 def test_missing_async_ticket_or_ack_releases_job_without_losing_pending_item(self):
  for role in ('sp','server'):
   for failure in ('ticket','poll','result'):
    l=vm(role=role);l.execute(DELAY);l.globals().failure=failure
    l.execute(r"""
     holdJob()
     for i=1,100 do Jobs.advance(job);if failure=='ticket' and job.committed or failure~='ticket' and original.owner~=source then break end end
     assert(job.committed and not job.done)
     local native=CVPEquipmentPersistence
     local key,poll,result=native.playerKeyAsync,native.poll,native.result
     if failure=='ticket' then native.playerKeyAsync=function() return nil end
     elseif failure=='poll' then native.poll=function() return nil end
     else native.result=function() return nil end end
     drain(job);assert(job.done and not answer.ok and replies==1)
     assert(persisted.rows[answer.key] and not E.get(answer.key))
     native.playerKeyAsync=key;native.poll=poll;native.result=result
     now=10000;assert(E.recover(player))
     if failure=='ticket' then assert(not persisted.rows[answer.key] and original.owner==source and #source.rows==1)
     else assert(E.get(answer.key)==original and #source.rows==0) end
     assert(original.state.modData.nested.n==7)
    """)

 def test_disconnected_return_owner_keeps_original_escrow_for_retry(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    local key=assert(E.hold(original,transfer));local before=transfers
    local job=Jobs.new(function() return E.release(key,destination,transfer) end,
      function(ok) result=ok end)
    for i=1,100 do Jobs.advance(job);if job.committed then break end end
    assert(job.committed and not job.done)
    local available=CVPEquipmentPersistence.playerKeyAsync
    CVPEquipmentPersistence.playerKeyAsync=function() return nil end
    drain(job);assert(result==false and #destination.rows==0 and transfers==before)
    assert(persisted.rows[key].state=='returning' and not E.get(key))
    CVPEquipmentPersistence.playerKeyAsync=available
    now=10000;assert(E.recover(target));assert(E.get(key)==original)
    assert(E.release(key,destination,transfer));assert(destination.rows[1]==original and #destination.rows==1)
   """)

 def test_reconnected_actor_resolves_unmoved_intent_without_duplicate_owner(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    holdJob()
    for i=1,100 do Jobs.advance(job);if job.committed then break end end
    local actorKey=player.key;player.key=nil -- native identity unavailable after disconnect
    drain(job);assert(not answer.ok and transfers==0 and original.owner==source)
    assert(persisted.rows[answer.key].state=='taking')
    -- Engine login loads a NEW actor/item instance from its saved inventory.
    local loaded=item(clone(original.state));source=container();player=actor(actorKey,source);source:AddItem(loaded)
    now=10000;assert(E.recover(player))
    assert(not persisted.rows[answer.key] and not E.get(answer.key))
    assert(#source.rows==1 and source.rows[1]==loaded and #CVPEquipmentRuntime.container.rows==0)
    assert(loaded.state.id==42 and loaded.state.condition==63 and loaded.state.modData.nested.n==7)
   """)

 def test_deferred_hold_and_return_preserve_original_sp_mp(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    holdJob();assert(not Jobs.advance(job));assert(replies==0 and original.owner==source)
    drain(job);assert(replies==1 and answer.ok and E.get(answer.key)==original)
    local key=answer.key
    local returning=Jobs.new(function() return E.release(key,destination,transfer) end,
      function(ok) assert(ok);replies=replies+1 end)
    assert(not Jobs.advance(returning));assert(replies==1)
    drain(returning);assert(replies==2 and destination.rows[1]==original and #source.rows==0)
    assert(original.state.condition==63 and original.state.modData.nested.n==7)
    Jobs.advance(returning);assert(replies==2)
   """)
 def test_cancel_before_transfer_and_finish_after_durable_intent(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    holdJob();assert(not Jobs.advance(job));cancelled=true;drain(job)
    assert(not answer.ok and transfers==0 and original.owner==source and replies==1)
    cancelled=nil;holdJob()
    for i=1,100 do Jobs.advance(job);if job.committed then break end end
    assert(job.committed and not job.done);cancelled=true;drain(job)
    assert(answer.ok and E.get(answer.key)==original and #source.rows==0)
   """)
 def test_write_failure_at_each_hold_stage_preserves_one_item(self):
  for role in ('sp','server'):
   for failure in (1,2):
    l=vm(role=role);l.execute(DELAY);l.globals().failWriteAt=failure
    l.execute(r"""
     holdJob();drain(job);assert(not answer.ok and replies==1);local decoded=decodes
     failWriteAt=nil;now=10000;assert(E.recover(player))
     local total=#source.rows+#destination.rows
     for key in pairs(persisted and persisted.rows or {}) do if E.get(key) then total=total+1 end end
     assert(total==1 and decodes==decoded and original.state.modData.nested.n==7)
    """)
 def test_checkpoint_failure_keeps_pending_record_until_recovery(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    failCheckpoint=true;holdJob();drain(job)
    assert(not answer.ok and answer.key and not E.get(answer.key));local decoded=decodes
    failCheckpoint=nil;now=10000;assert(E.recover(player))
    assert(E.get(answer.key)==original and #source.rows==0 and decodes==decoded)
   """)

 def test_runtime_reentrant_completion_keeps_next_transaction_isolated(self):
  from test_link_multiplayer import vm as network_vm
  l=network_vm(True);l.execute(DELAY);l.execute(r"""
   local movements,refreshes=0,0
   local refresh=S.refresh;S.refresh=function(...) refreshes=refreshes+1;return refresh(...) end
   R.simulation.tick=function() movements=movements+1;return {},{} end
   R.request=function() assert(Jobs.call('checkpointSquare',{}));return true end
   local replies=0
   R:submit(player,'fixture',{},function(ok)
    assert(ok);replies=replies+1
    R:submit(player,'second',{},function(ok) assert(ok);replies=replies+1 end)
   end)
   assert(R.saveJob and replies==0)
   R:tick({player},.016);R:tick({player},.016)
   assert(R.saveJob and replies==1 and refreshes==0 and movements==2)
   R:tick({player},.016)
   assert(R.saveJob and replies==1 and refreshes==0 and movements==3)
   R:tick({player},.016);assert(not R.saveJob and replies==2)
  """)

 def test_item_changed_during_intent_is_not_consumed_with_stale_payload(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    holdJob()
    for i=1,100 do Jobs.advance(job);if job.committed then break end end
    assert(job.committed and not job.done and original.owner==source)
    original.state.condition=21;original.state.modData.nested.n=99
    drain(job);assert(not answer.ok and original.owner==source and #source.rows==1 and transfers==0)
    assert(original.state.condition==21 and original.state.modData.nested.n==99)
    for _ in pairs(persisted.rows) do error('cancelled item retained') end
   """)
 def test_delivered_item_moved_during_wait_is_not_reissued(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    key=assert(E.hold(original,transfer));replies=0
    local job=Jobs.new(function() return E.release(key,destination,transfer) end,
      function(ok) result=ok;replies=replies+1 end)
    for i=1,100 do Jobs.advance(job);if original.owner==destination then break end end
    assert(not job.done and original.owner==destination)
    destination:Remove(original);source:AddItem(original)
    drain(job);assert(result and replies==1 and original.owner==source and #source.rows==1)
    assert(E.recover(target));assert(not persisted.rows[key] and not E.get(key))
   """)

 def test_disconnect_before_intent_cancels_but_committed_job_finishes(self):
  from test_link_multiplayer import vm as network_vm
  for committed in (False, True):
   l=network_vm(True);l.execute(DELAY);l.globals().committed=committed
   l.execute(r"""
    R.request=function()
     local ok,why=Jobs.call('checkpointSquare',{})
     if not ok then return false,nil,why end
     applied=(applied or 0)+1;return true
    end
    R:submit(player,'fixture',{},function(ok,_,why) answer={ok=ok,why=why} end)
    R.saveJob.committed=committed
    R:submit(player2,'fixture',{},function(ok) secondAnswer=ok end)
    assert(#R.saveQueue==1)
    for i=1,4 do R:tick({player2},.016) end
    assert(answer and answer.ok==committed)
    assert((applied or 0)==(committed and 1 or 0))
    if not committed then assert(answer.why=='player disconnected') end
    assert(rope:getContainer()==storage and otherRope:getContainer()==player2.inv)
   """)


class PersistenceWriteContractTests(unittest.TestCase):
 """Only an explicit confirming result may publish a durable ledger entry."""
 def test_sync_write_accepts_only_confirmed_true(self):
  for role in ('sp','server'):
   for outcome in ('nil','false','throw','invalid-envelope'):
    with self.subTest(role=role,outcome=outcome):
     l=vm(role=role);l.globals().outcome=outcome
     l.execute(r"""
      if outcome=='nil' then CVPEquipmentPersistence.write=function() return nil end
      elseif outcome=='false' then CVPEquipmentPersistence.write=function() return false end
      elseif outcome=='throw' then CVPEquipmentPersistence.write=function() error('disk failure') end
      else CVPEquipmentPersistence.writeEnvelope=function() return nil end end
      local key,err=E.hold(original,transfer)
      assert(not key and err,tostring(err))
      assert(transfers==0 and original.owner==source and #source.rows==1)
      for _ in pairs((persisted and persisted.rows) or {}) do error('unconfirmed write exposed a row') end
     """)
 def test_write_envelope_classification_controls_durability(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(r"""
    local write=CVPEquipmentPersistence.write
    CVPEquipmentPersistence.writeEnvelope=function() return {status='failed',reason='disk full'} end
    local key,err=E.hold(original,transfer)
    assert(not key and err and string.find(err,'disk full'),tostring(err))
    assert(transfers==0 and original.owner==source)
    CVPEquipmentPersistence.writeEnvelope=function(data)
     if write(data) then return {status='confirmed'} end
     return {status='failed',reason='not confirmed'}
    end
    key=assert(E.hold(original,transfer))
    assert(persisted.rows[key].state=='held' and E.get(key)==original and #source.rows==0)
   """)
 def test_async_write_without_confirmed_result_never_completes(self):
  for role in ('sp','server'):
   for kind in ('nil','false'):
    with self.subTest(role=role,result=kind):
     l=vm(role=role);l.execute(DELAY);l.globals().kind=kind
     l.execute(r"""
      CVPEquipmentPersistence.writeAsync=function() return {} end
      CVPEquipmentPersistence.poll=function() return 1 end
      CVPEquipmentPersistence.result=function() if kind=='nil' then return nil end;return false end
      holdJob();drain(job)
      assert(not answer.ok and replies==1 and transfers==0 and original.owner==source)
      assert(persisted==nil)
     """)
 def test_incompatible_bridge_stops_job_before_read_or_transfer(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    CVPEquipmentPersistence.capabilities=function()
     return {ok=false,status='incompatible',reason='missing method checkpointSquare(IsoGridSquare)',features={}}
    end
    holdJob();drain(job)
    assert(not answer.ok and answer.why and string.find(answer.why,'equipment bridge incompatible',1,true),tostring(answer.why))
    assert(transfers==0 and original.owner==source and backendCalls==0 and writes==0 and persisted==nil)
    assert(not job.committed)
   """)
 def test_unconfirmed_final_write_stays_pending_and_recovers_once(self):
  for role in ('sp','server'):
   l=vm(role=role);l.execute(DELAY);l.execute(r"""
    local write=CVPEquipmentPersistence.write
    local attempts=0
    CVPEquipmentPersistence.write=function(data)
     attempts=attempts+1
     if attempts==2 then return nil end
     return write(data)
    end
    holdJob();drain(job)
    assert(not answer.ok and answer.key,tostring(answer.why))
    assert(transfers==1 and original.owner==CVPEquipmentRuntime.container)
    assert(persisted.rows[answer.key] and persisted.rows[answer.key].state=='taking')
    now=10000;assert(E.recover(player))
    assert(E.get(answer.key)==original and persisted.rows[answer.key].state=='held')
    assert(#CVPEquipmentRuntime.container.rows==1 and #source.rows==0)
   """)

class PostTransferRecoveryTests(unittest.TestCase):
 """Reload the actor and ledger independently at the transfer/save boundary."""
 def pending(self, role, returning):
  l=vm(role=role);l.execute(DELAY);l.globals().returning=returning
  l.execute(r"""
   if returning then
    key=assert(E.hold(original,transfer));owner=target
    job=Jobs.new(function() return E.release(key,destination,transfer) end,
      function(ok) answer={ok=ok};replies=(replies or 0)+1 end)
   else owner=player;holdJob() end
   for i=1,100 do
    Jobs.advance(job)
    if returning and original.owner==destination or not returning and original.owner~=source then break end
   end
   assert(not job.done)
   ownerKey=owner.key;owner.key=nil
   local checkpoint=CVPEquipmentPersistence.checkpointPlayerAsync
   CVPEquipmentPersistence.checkpointPlayerAsync=function(p)
    if p==owner then return nil end;return checkpoint(p)
   end
   drain(job);assert(not answer.ok and replies==1)
   key=key or answer.key
   assert(persisted.rows[key] and not E.get(key))
   assert(original.owner==(returning and destination or CVPEquipmentRuntime.container))
   assert(original.state.condition==63 and original.state.modData.nested.n==7)
  """)
  return l

 def test_receipt_and_inventory_recovery_matrix_sp_mp(self):
  for role in ('sp','server'):
   for returning in (False,True):
    for restart in (False,True):
     for saved_receipt in (False,True):
      for present in (False,True):
       with self.subTest(role=role,returning=returning,restart=restart,receipt=saved_receipt,present=present):
        a=self.pending(role,returning)
        b=vm(plain(a.globals().persisted),role=role,seed=False) if restart else a
        b.globals().key=a.globals().key;b.globals().ownerKey=a.globals().ownerKey
        b.globals().present=present;b.globals().savedReceipt=saved_receipt
        b.globals().returning=returning;b.globals().restart=restart
        b.globals().token=a.globals().persisted['rows'][a.globals().key]['receipt']
        b.globals().state=b.table_from(plain(a.globals().original['state']),recursive=True)
        b.execute(r"""
         local fresh=container();local actor=actor(ownerKey,fresh)
         if present then fresh:AddItem(item(clone(state))) end
         if savedReceipt then actor.md.CVPEquipmentReceipts={[token]=true} end
         local before=decodes;local ok,why=E.recover(actor)
         if not returning and savedReceipt and present then
          assert(not ok and (why=='equipment receipt conflicts with inventory' or why=='duplicate equipment owner'))
          assert(not E.get(key) and decodes==before and #fresh.rows==1)
         elseif present or returning and savedReceipt then
          assert(ok and not persisted.rows[key] and not E.get(key))
          assert(#fresh.rows==(present and 1 or 0) and decodes==before)
          assert(not actor.md.CVPEquipmentReceipts or not actor.md.CVPEquipmentReceipts[token])
         elseif not returning and (savedReceipt or not restart) then
          assert(ok);local held=assert(E.get(key))
          assert(held.state.condition==63 and held.state.modData.nested.n==7)
          assert(#fresh.rows==0 and #CVPEquipmentRuntime.container.rows==1)
          assert(decodes==before+(restart and 1 or 0))
         else
          assert(not ok and why=='equipment transfer outcome unresolved')
          assert(persisted.rows[key] and not E.get(key) and decodes==before)
         end
        """)

 def test_final_ledger_failure_receipt_survives_and_recovers_once(self):
  for role in ('sp','server'):
   for returning in (False,True):
    a=vm(role=role);a.execute(DELAY);a.globals().returning=returning
    a.execute(r"""
     if returning then key=assert(E.hold(original,transfer)) end
     failWriteAt=writes+2
     if returning then
      owner=target;assert(not E.release(key,destination,transfer))
     else owner=player;key=E.hold(original,transfer) end
     assert(persisted.rows[key] and owner.md.CVPEquipmentReceipts[persisted.rows[key].receipt])
    """)
    b=vm(plain(a.globals().persisted),role=role,seed=False)
    b.globals().key=a.globals().key;b.globals().returning=returning
    b.globals().savedMD=b.table_from(plain(a.globals().owner['md']),recursive=True)
    b.globals().state=b.table_from(plain(a.globals().original['state']),recursive=True)
    b.execute(r"""
     local owner=returning and target or player;owner.md=savedMD
     if returning then destination:AddItem(item(state)) end
     assert(E.recover(owner));assert(E.recover(owner))
     if returning then assert(#destination.rows==1 and decodes==0 and not persisted.rows[key])
     else assert(E.get(key) and decodes==1 and #source.rows==0) end
    """)

 def test_stale_receipt_cannot_authorize_another_operation(self):
  a=self.pending('server',False)
  b=vm(plain(a.globals().persisted),role='server',seed=False)
  b.globals().key=a.globals().key
  b.execute(r"""
   player.md.CVPEquipmentReceipts={['old-operation']=true}
   local ok,why=E.recover(player)
   assert(not ok and why=='equipment transfer outcome unresolved' and decodes==0)
  """)
  # Old journals have no proof even when the player has a similarly named marker.
  saved=plain(a.globals().persisted);token=saved['rows'][a.globals().key].pop('receipt')
  c=vm(saved,role='server',seed=False);c.globals().token=token
  c.execute("player.md.CVPEquipmentReceipts={[token]=true};assert(not E.recover(player) and decodes==0)")

 def test_completed_receipts_are_cleaned_after_crash(self):
  a=vm();a.execute("key=assert(E.hold(original,transfer))")
  b=vm(plain(a.globals().persisted),seed=False);b.globals().key=a.globals().key
  b.execute(r"""
   player.md.CVPEquipmentReceipts={[key]=true,['older-return']=true}
   assert(E.recover(player));assert(player.md.CVPEquipmentReceipts==nil)
   assert(E.get(key) and decodes==1)
  """)
