"""The remote stand must never delete ordinary objects or bypass link release."""
from pathlib import Path
import unittest
from test_link_multiplayer import vm

SOURCE=Path('tools/mp-test/mod/42/media/lua/server/CVP_MPTestServer.lua')

def stand():
    l=vm(True)
    l.execute('''
        getFileReader=function() return {readLine=function() return 'ecea4c1b' end,close=function() end} end
        fixtureState={};ModData={getOrCreate=function() return fixtureState end}
        player.getAccessLevel=function() return access or 'admin' end
    ''')
    l.execute(SOURCE.read_text(encoding='utf-8'))
    return l

class MPTestStandTests(unittest.TestCase):
    def test_requires_admin_valid_count_and_unloaded_scene_is_preserved(self):
        l=stand();l.execute('''
            assert(CVPMPTestServer.plan(player,0).count==0)
            access='none';assert(not pcall(CVPMPTestServer.plan,player,32));access='admin'
            assert(not pcall(CVPMPTestServer.plan,player,2))
            fixtureState.count=1
            assert(not pcall(CVPMPTestServer.reset,player,0))
            assert(worldCount(body)==1 and worldCount(body2)==1)
        ''')

    def test_reset_refuses_existing_links_and_foreign_material(self):
        l=stand();l.execute('''
            root=link(C,A,rope)
            body.md.CVPMPTest=true;car.md.CVPMPTest=true
            fixtureState.count=1;fixtureState.vehicle=true
            assert(not pcall(CVPMPTestServer.plan,player,0),'ordinary rope must be preserved')
            rope.md.CVPMPTest=true
            local plan=CVPMPTestServer.plan(player,0)
            assert(#plan.ends==1 and plan.ends[1].id==root)
            assert(not pcall(CVPMPTestServer.reset,player,0),'attached fixture must not be deleted')
            assert(S.graph.links[root] and worldCount(body)==1)
            assert(require('CVP_Equipment').get(S.graph.links[root].equipment)==rope)
        ''')

    def test_reset_refuses_foreign_loot_before_mutation(self):
        l=stand();l.execute('''
            body.md.CVPMPTest=true;fixtureState.count=1;player.x=128;player.y=220
            local ok,why=pcall(CVPMPTestServer.reset,player,0)
            assert(not ok and tostring(why):find('foreign loot',1,true),tostring(why))
            assert(worldCount(body)==1 and body.inv:getItems():size()==1)
        ''')

    def test_detached_fixture_rope_is_still_collected_before_reset(self):
        l=stand();l.execute('''
            root=link(C,A,rope);rope.md.CVPMPTest=true
            local row=S.graph.links[root]
            assert(S:releaseSystem({{id=root,revision=row.revision,side='a',where=row.a}}))
            row=S.graph.links[root]
            assert(S:releaseSystem({{id=root,revision=row.revision,side='b',where=row.b}}))
            local plan=CVPMPTestServer.plan(player,0)
            assert(#plan.ends==1 and plan.ends[1].id==root)
            assert(not pcall(CVPMPTestServer.reset,player,0))
        ''')

    def test_module_is_inert_without_test_marker(self):
        l=vm(True);l.execute('getFileReader=function() return nil end')
        l.execute(SOURCE.read_text(encoding='utf-8'))
        self.assertIsNone(l.globals().CVPMPTestServer)

    def test_zero_one_thirty_two_and_reset_preserve_unmarked_objects(self):
        for count in (0,1,32):
            l=stand();l.globals().count=count
            l.execute('''
                player.x=128;player.y=220
                IsoDirections={N='N'};sentBodies=0;fixtureCars={}
                CVPNetwork.bodies=function()
                    local result={};for _,b in ipairs(bodies) do if b.world then result[#result+1]=b end end
                    return list(result)
                end
                local vehicles=cell.getVehicles
                cell.getVehicles=function()
                    local all={car};for _,v in ipairs(fixtureCars) do if not v.removed then all[#all+1]=v end end
                    return {iterator=function() local i=0;return {hasNext=function() return i<#all end,next=function() i=i+1;return all[i] end} end}
                end
                addVehicleDebug=function(_,_,_,sq)
                    local v=setmetatable({md={},sq=sq},{__index=car})
                    v.getPartCount=function() return 0 end;v.getMaxPassengers=function() return 0 end
                    v.repair=function() end;v.setHotwired=function() end
                    v.permanentlyRemove=function(s) s.removed=true end
                    fixtureCars[#fixtureCars+1]=v;return v
                end
                createRandomDeadBody=function(sq)
                    local b=corpse();b.world=false;sq:addCorpse(b);b.x=sq:getX();b.y=sq:getY()
                    b.netID=tostring(100000+#bodies);return b
                end
                sendCorpse=function() sentBodies=sentBodies+1 end
                local result=CVPMPTestServer.reset(player,count)
                assert(#result.targets==count and #result.gear==count and sentBodies==count)
                assert(fixtureState.count==count and fixtureState.vehicle)
                CVPMPTestServer.reset(player,0)
                assert(fixtureState.count==0 and fixtureState.vehicle)
                assert(worldCount(body)==1 and worldCount(body2)==1 and not car.removed)
                assert(storage:getItems():contains(rope) and storage:getItems():contains(chain))
            ''')

if __name__=='__main__':unittest.main()
