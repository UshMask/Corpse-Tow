import unittest
from test_link_client import client
from test_continuous_rope import SCENE

MOCK = '''
BW=require 'CVP_BodyWear';
function recover() now=now+5000;BW.observe(R);return BW.recover(R) end
nativeSkeletons=0;nativeRemovals=0
for _,b in ipairs(bodies) do
 b.isPlayer=function(s) return s.playerBody==true end
 b.isSkeleton=function(s) return s.skeleton==true end
end
CVPBodyWearNative={
 skeleton=function(b)
  if failSkeleton then return false end
  if not b.skeleton then b.skeleton=true;b.inv.rows={};nativeSkeletons=nativeSkeletons+1 end
  return true
 end,
 remove=function(b,sq)
  assert(not S.index.byBody[b.md.CVPBodyKey],'body removed before durable tether edit')
  if failRemove then return false end
  if b.world then sq:removeCorpse(b);nativeRemovals=nativeRemovals+1 end
  return true
 end}
function travel(b,n)
 local before={x=b.x,y=b.y,z=b.z};move(b,b.x+n,b.y)
 BW.committed({records={{body=b,before=before}}})
end
SandboxVars.CorpseProxyLab.BodyWear=true;SandboxVars.CorpseProxyLab.BodyWearRate=3
'''

class BodyWearTests(unittest.TestCase):
    def test_notice_only_after_success_not_failed_retry(self):
        l=client();l.execute(MOCK+'''
            link(C,A,rope);notices={}
            BW.notify=function(_,b,stage) notices[#notices+1]=stage end
            body.md.CVPBodyWear={distance=500,stage=0,pending=1}
            failSkeleton=true;assert(not recover());assert(#notices==0)
            failSkeleton=false;assert(recover());assert(#notices==1 and notices[1]==1)
            assert(recover());assert(#notices==1)
            body.md.CVPBodyWear.pending=2
            failRemove=true;assert(not recover());assert(#notices==1)
            failRemove=false;assert(recover());assert(#notices==2 and notices[2]==2)
            assert(recover());assert(#notices==2,'removed corpse notified again after discovery')
        ''')

    def test_pending_failure_or_unloaded_body_does_not_stop_other_trains(self):
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable):
                l=client();l.globals().unavailable=unavailable;l.execute(MOCK+'''
                    local a=link(C,A,rope);local b=link(C,B,chain)
                    body.md.CVPBodyWear={distance=500,stage=0,pending=1}
                    local native=CVPBodyWearNative.skeleton;local attempts=0
                    CVPBodyWearNative.skeleton=function(b)
                        if b==body then attempts=attempts+1;return false end
                        return native(b)
                    end
                    BW.observe(R);local square=body.sq
                    if unavailable then body.sq=nil end
                    local x=body2.x;local stopped=body.x
                    for i=1,80 do now=now+50;car.x=car.x+.05;assert(R:tick({player},.05)) end
                    assert(body2.x>x+.1 and body.x==stopped)
                    assert(attempts<=1 and R.wearError and not R.error)
                    assert(S.index.byBody.A and E.get(S.graph.links[a].equipment)==rope)
                    body.sq=square;CVPBodyWearNative.skeleton=native
                    now=now+6000;assert(R:tick({player},.05))
                    assert(body.skeleton and not R.simulation.wearPending[body])
                    assert(nativeSkeletons==1)
                    edit(a,'remove','a');edit(b,'remove','a')
                    assert(rope:getContainer()==storage and chain:getContainer()==storage)
                ''')

    def test_failed_body_does_not_prevent_another_pending_body_finishing(self):
        l=client();l.execute(MOCK+'''
            local a=link(C,A,rope);local b=link(C,B,chain)
            body.md.CVPBodyWear={distance=500,stage=0,pending=1}
            body2.md.CVPBodyWear={distance=250,stage=1,pending=2};body2.skeleton=true
            CVPBodyWearNative.skeleton=function() error('injected native failure') end
            assert(not recover())
            assert(body.world and not body2.world and nativeRemovals==1)
            assert(S.index.byBody.A and not S.index.byBody.B)
            assert(E.get(S.graph.links[a].equipment)==rope and E.get(S.graph.links[b].equipment)==chain)
            edit(a,'remove','a');edit(b,'remove','a')
            assert(rope:getContainer()==storage and chain:getContainer()==storage)
        ''')

    def test_stages_destroy_loot_then_remove_cargo_while_tail_moves(self):
        for key in ('A','B','D'):
            with self.subTest(key=key):
                l=client();l.execute(SCENE+MOCK);l.globals().key=key
                l.execute('''
                    local b=H.body({key=key});b.md.CVPBodyWear={distance=499,stage=0}
                    travel(b,1);assert(recover());assert(b.skeleton and #b.inv.rows==0)
                    assert(S.index.byBody[key] and b.world,'skeleton stage must remain attached')
                    b.md.CVPBodyWear.distance=249;travel(b,1);assert(recover())
                    assert(not b.world and not S.index.byBody[key]);local x=third.x
                    tow(100);if key~='D' then assert(third.x>x+.1,'tail stopped after wear') end
                    for _,id in ipairs(ids) do assert(E.get(S.graph.links[id].equipment)) end
                    for _,id in ipairs(ids) do edit(id,'remove','a') end
                    assert(rope:getContainer()==storage and chain:getContainer()==storage and extra:getContainer()==storage)
                    assert(nativeSkeletons==1 and nativeRemovals==1)
                ''')

    def test_disabled_stationary_teleport_and_player_protection(self):
        l=client();l.execute(MOCK+'''
            travel(body,0);travel(body,5);assert(not body.md.CVPBodyWear)
            SandboxVars.CorpseProxyLab.BodyWear=false;travel(body,1);assert(not body.md.CVPBodyWear)
            SandboxVars.CorpseProxyLab.BodyWear=true;body.playerBody=true;travel(body,1);assert(not body.md.CVPBodyWear)
            body.playerBody=false;travel(body,1);assert(body.md.CVPBodyWear.distance==1)
            clientMode=true;travel(body,1);assert(body.md.CVPBodyWear.distance==1)
        ''')

    def test_ledger_failure_keeps_body_then_retry_is_idempotent(self):
        l=client();l.execute(SCENE+MOCK+'''
            body.md.CVPBodyWear={distance=250,stage=1,pending=2};body.skeleton=true
            local commit=S.commit;S.commit=function() return false,'injected write failure' end
            assert(not recover());assert(body.world and S.index.byBody.A and nativeRemovals==0)
            S.commit=commit;failRemove=true;assert(not recover())
            assert(body.world and not S.index.byBody.A and next(S.index.byJoint))
            failRemove=false;assert(recover());assert(recover())
            assert(nativeRemovals==1 and not body.world)
            for _,id in ipairs(ids) do assert(E.get(S.graph.links[id].equipment)) end
        ''')

    def test_marker_failure_does_not_delete_loot_and_pending_survives_reload(self):
        l=client();l.execute(MOCK+'''
            local checkpoint=CVPEquipmentPersistence.checkpointSquare
            body.md.CVPBodyWear={distance=500,stage=0,pending=1}
            CVPEquipmentPersistence.checkpointSquare=function() return false end
            assert(not recover());assert(not body.skeleton and nativeSkeletons==0)
            CVPEquipmentPersistence.checkpointSquare=checkpoint
            R.simulation.wearPending={};assert(recover());assert(body.skeleton)
            assert(body.md.CVPBodyWear.stage==1 and not body.md.CVPBodyWear.pending)
            assert(recover());assert(nativeSkeletons==1)
        ''')

if __name__=='__main__': unittest.main()
