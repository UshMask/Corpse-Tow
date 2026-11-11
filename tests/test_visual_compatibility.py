"""Optional presentation failures and native corpse handling must not break towing."""
import unittest

from test_core_lifecycle import environment
from test_multiplayer import vm


class VisualCompatibilityTests(unittest.TestCase):
    def test_grapple_after_external_move_releases_saved_link(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    assert(attach())
                    local loot=body.inv.rows[1]
                    body.sq:removeCorpse(body);body.x=1
                    gridSquare(1,0,0):addCorpse(body)
                    body.isBeingGrappled=function() return true end
                    now=now+100
                    if serverMode then CVPMPServer.tick() else callbacks.OnTick() end
                    assert(#links()==0 and not body.md.CVPTether,'grapple left a saved tether')
                    assert(body.x==1 and body.inv.rows[1]==loot and (serverMode and rope:getWorldItem() or not serverMode and rope.owner==storage))
                    assert(worldCount(body)==1)
                ''')

    def test_failed_render_calls_disable_once_and_leave_world_link_usable(self):
        lua = environment(False)
        lua.execute('''
            local calls={};local view=require 'CVP_Viewpoint'
            CVPViewpoint={}
            CVPRopeScene={untrack=function() end,clear=function() end}
            for _,name in ipairs({'track','untrack','clear','project'}) do
                CVPViewpoint[name]=function()
                    calls[name]=(calls[name] or 0)+1;error('incompatible visual bridge')
                end
            end
            CVPRopeScene.update=function()
                calls.rope=(calls.rope or 0)+1;error('incompatible rope renderer')
            end
            assert(attach());local saved=body.md.CVPTether
            for i=1,3 do now=now+100;callbacks.OnTick() end
            assert(#links()==1 and body.md.CVPTether==saved and rope.owner==CVPEquipmentRuntime.container)
            assert(not links()[1].failed and worldCount(body)==1)
            view.project(0,0,0);view.project(0,0,0)
            view.clear();view.clear()
            assert(detach() and #links()==0 and rope.owner==storage)
            view.untrack(body)
            for _,name in ipairs({'track','untrack','clear','project','rope'}) do
                assert(calls[name]==1, name..' retried failed renderer')
            end
        ''')

    def test_client_render_failure_does_not_skip_other_bodies(self):
        lua = vm(False)
        lua.execute('''
            local core=require 'CVP_Core'
            local calls=0
            CVPRopeScene.update=function() calls=calls+1;error('renderer unavailable') end
            for _,b in ipairs({body,body2}) do
                local md=core.metadata(require('CVP_World').vehicleKey(car),rope,1,'feet',b)
                CVPMPClient.links[b.netID]={received=now,target={
                    x=2,y=0,z=0,angle=0,vehicle=7,slot=1,length=3,
                    footX=-.65,footY=0,gearType='Base.Rope',gearID=rope.id,
                    connection=md.connection}}
            end
            now=now+100;CVPMPClient.tick()
            assert(calls==1,'renderer calls: '..tostring(calls))
            for _,b in ipairs({body,body2}) do
                assert(CVPMPClient.links[b.netID].initialized and b.md.CVPTether)
            end
        ''')

    def test_client_does_not_reposition_grappled_or_removed_body(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                lua = vm(False)
                lua.globals().removed = removed
                lua.execute('''
                    local core=require 'CVP_Core'
                    local md=core.metadata(require('CVP_World').vehicleKey(car),rope,1,'feet',body)
                    body.md.CVPTether=md
                    if removed then body.world=false;CVPNetwork.find=function() return body end
                    else body.isBeingGrappled=function() return true end end
                    CVPMPClient.links[body.netID]={received=now,target={
                        x=2,y=0,z=0,angle=0,vehicle=7,slot=1,length=3,
                        footX=-.65,footY=0,gearType='Base.Rope',gearID=rope.id,
                        connection=md.connection}}
                    local x,y=body.x,body.y
                    now=now+100;CVPMPClient.tick()
                    assert(body.x==x and body.y==y and body.md.CVPTether==md)
                    assert(body.world==not removed)
                ''')


if __name__ == '__main__':
    unittest.main()
