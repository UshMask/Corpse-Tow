"""Ground-rendered ends remain actionable without an IsoObject under the cursor."""
from pathlib import Path
import unittest
from test_link_client import client
from test_link_actions import scene


class LooseEndPickTests(unittest.TestCase):
    def test_inactive_viewpoint_falls_back_to_player_projection_with_negative_tiles(self):
        l=client(); l.execute('''
            local menu=require 'CVP_Menu'
            Viewpoint={Mouse={worldX=function() return nil end,worldY=function() return nil end}}
            player.getPlayerNum=function() return 1 end
            function getMouseX() return 123 end;function getMouseY() return 456 end
            function screenToIsoX(index,x,y,z) assert(index==1 and x==123 and y==456);return -.2 end
            function screenToIsoY() return -1.2 end
            assert(menu.groundSquare(player,context)==gridSquare(-1,-2,0))
        ''')

    def test_empty_ground_click_can_take_cancel_and_return_original_chain_sp_mp(self):
        for mp in (False, True):
            with self.subTest(mp=mp):
                l=scene(mp)
                l.execute("package.preload.CVP_LinkMenu=assert(loadstring(...))",
                          Path('CorpseProxyLab/42/media/lua/client/CVP_LinkMenu.lua').read_text(encoding='utf-8-sig'))
                l.execute('''
                    local mode=clientMode;clientMode=false
                    player.getPlayerNum=function() return 0 end
                    local id=link(C,A,chain);edit(id,'release','a');clientMode=mode
                    local e=S.graph.links[id].a
                    function getMouseX() return 100 end;function getMouseY() return 200 end
                    function screenToIsoX() return e.x end
                    function screenToIsoY() return e.y end
                    local menu=require('CVP_LinkMenu').new(api,Actions)
                    local function select(key)
                        options={};context.children={};menu:fill(player,context,{})
                        for _,o in ipairs(options) do if o.label==getText(key) then
                            assert(not o.notAvailable);o.run();return assert(Actions.jobs[player])
                        end end
                        error('missing action: '..key)
                    end
                    local job=select('IGUI_CVP_LinkTakeChain')
                    require('CVP_Feedback').cancel(player);Actions:update()
                    assert(S.graph.links[id].a.kind=='ground' and chain:getContainer()~=storage)
                    job=select('IGUI_CVP_LinkTakeChain');assert(finishJob(job))
                    clientMode=false -- The ledger is deliberately unavailable on MP clients.
                    assert(S.graph.links[id].a.kind=='held' and E.get(S.graph.links[id].equipment)==chain)
                    clientMode=mode
                    job=select('IGUI_CVP_LinkRemoveChain');assert(finishJob(job))
                    assert(not S.graph.links[id] and chain:getContainer()==storage)
                    local count=0;for _,item in ipairs(storage.rows) do if item==chain then count=count+1 end end
                    assert(count==1);intact(body)
                ''')

    def test_viewpoint_ground_ray_overrides_isometric_coordinates_and_hit_objects(self):
        l=client(); l.execute('''
            local id=link(C,A,chain);edit(id,'release','a');local e=S.graph.links[id].a
            Viewpoint={Mouse={worldX=function() return e.x end,worldY=function() return e.y end}}
            car.getPoly=function() return {containsPoint=function() return false end} end
            function screenToIsoX() error('must use Viewpoint ray') end
            function screenToIsoY() error('must use Viewpoint ray') end
            options={};context.children={}
            callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return gridSquare(40,40,0) end}},false)
            choose('IGUI_CVP_LinkTakeChain');completeJob();assert(S.graph.links[id].a.kind=='held')
        ''')

    def test_other_tile_and_floor_do_not_select_nearby_ends(self):
        l=client(); l.execute('''
            local id=link(C,A,chain);edit(id,'release','a');local e=S.graph.links[id].a
            function screenToIsoX() return e.x+5 end
            function getMouseX() return 100 end;function getMouseY() return 200 end
            function screenToIsoY() return e.y end
            options={};context.children={}
            callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function()
                return gridSquare(math.floor(e.x),math.floor(e.y),0) end}},false)
            for _,o in ipairs(options) do assert(o.label~=getText('IGUI_CVP_LinkTakeChain')) end
            screenToIsoX=function() return e.x end;e.z=e.z+1
            options={};context.children={};callbacks.OnFillWorldObjectContextMenu(0,context,{},false)
            for _,o in ipairs(options) do assert(o.label~=getText('IGUI_CVP_LinkTakeChain')) end
        ''')


if __name__ == '__main__':
    unittest.main()
