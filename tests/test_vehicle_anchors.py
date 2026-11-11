"""Front/rear anchors keep their identity through authority and saved links."""
import unittest
from test_link_client import client

SETUP = '''
car.getWorldPos=function(s,x,y,z,out) out.xx=s.x+z;out.yy=s.y end
car.attachmentExist=function(_,name) return name=='trailer' or name=='trailerfront' end
car.getAttachmentWorldPos=function(s,name,out)
 out.xx=s.x+(name=='trailerfront' and 2 or -2);out.yy=s.y;return out
end
front={kind='vehicle',key='sql:71',point='front'}
'''

class VehicleAnchorTests(unittest.TestCase):
    def test_timed_actions_use_selected_anchor_sp_mp(self):
        from test_link_actions import scene
        for mp in (False, True):
            for point in ('front', 'hitch'):
                l=scene(mp);l.execute(SETUP);l.globals().point=point
                l.execute("""
                    front.point=point
                    local job=Actions:create(player,front,A,rope)
                    assert(finishJob(job) and not job.feedback.reason)
                    local id,row=next(S.graph.links);assert(row.a.point==point)
                    local removing=Actions:command(player,id,row.revision,'a','release')
                    assert(finishJob(removing) and not removing.feedback.reason)
                    clientMode=false -- Inspect the authoritative ledger, not a client inventory copy.
                    assert(S.graph.links[id].a.kind=='ground' and E.get(row.equipment)==rope)
                    intact(body)
                """)

    def test_native_points_fallback_and_click_selection(self):
        l=client();l.execute(SETUP+'''
            local Geometry=require 'CVP_Geometry';local Menu=require 'CVP_Menu'
            assert(Geometry.anchor(car,'front')==car.x+2)
            assert(Geometry.anchor(car)==car.x-2)
            car.attachmentExist=function() return false end
            assert(Geometry.anchor(car,'front')==car.x+2)
            assert(Geometry.anchor(car)==car.x-2)
            player.x=car.x-5;player.y=car.y
            getMouseX=function() return car.x+3 end;getMouseY=function() return car.y end
            screenToIsoX=function(_,x) return x end;screenToIsoY=function(_,x,y) return y end
            assert(Menu.vehiclePoint(player,car,player,true)=='front','click wins over player side')
            assert(Menu.vehiclePoint(player,car,player,false)=='hitch','controller/player fallback')
            getMouseX=function() return car.x-3 end
            assert(Menu.vehiclePoint(player,car,player,true)=='hitch')
        ''')

    def test_front_and_rear_remain_distinct_after_save_and_sampling(self):
        l=client();l.execute(SETUP+'''
            local f=link(front,A,rope);local r=link(C,B,chain)
            local samples=H.samples(S.graph)
            assert(samples[f].a.point=='front' and samples[r].a.point=='hitch')
            assert(samples[f].a.x-samples[r].a.x==4,'cache must not merge anchor points')
            assert(S:flush());local saved=serializeEquipment();loadEquipment(saved)
            assert(S:load());assert(S.graph.links[f].a.point=='front')
            assert(S.graph.links[r].a.point=='hitch');assert(G.index(S.graph))
            local W=require 'CVP_LinkWire'
            assert(W.ref(front) and W.ref(C))
            assert(not W.ref({kind='vehicle',key='sql:71',point='roof'}))
            assert(not H.resolve({kind='vehicle',key='sql:71',point='roof'},player))
            local plan,why=require('CVP_LinkRewire').plan(S.graph,S.index,H,car,{key='player',allowOthers=true})
            assert(not plan and why=='IGUI_CVP_RewireSeparateAnchors')
        ''')

    def test_front_towing_and_release_keep_equipment(self):
        l=client();l.execute(SETUP+'''
            local id=link(front,A,rope);local key=S.graph.links[id].equipment
            local before=body.x
            for i=1,30 do car.x=car.x+.05;Sim:tick(S.graph,S.index,.05,now) end
            assert(body.x>before+.1 and Sim.records[id].source.point=='front')
            assert(E.get(key)==rope);intact(body)
            edit(id,'release','a')
            assert(S.graph.links[id].a.kind=='ground' and E.get(key)==rope)
            beside(front);local row=S.graph.links[id]
            assert(S:command(player,{id=id,revision=row.revision,side='a',op='bind',target=front}))
            assert(S.graph.links[id].a.point=='front' and E.get(key)==rope)
        ''')

    def test_multiplayer_snapshot_preserves_front_point(self):
        from test_link_multiplayer import Network
        n=Network()
        for vm in (n.server,*n.clients.values()): vm.execute(SETUP)
        n.server.execute("link(front,A,rope)")
        n.publish()
        for vm in n.clients.values():
            vm.execute("local _,row=next(CVPMPClient.graph.links);assert(row.a.point=='front')")

    def test_car_menu_captures_side_before_player_walks(self):
        l=client();l.execute(SETUP+'''
            getMouseX=function() return car.x+3 end;getMouseY=function() return car.y end
            screenToIsoX=function(_,x) return x end;screenToIsoY=function(_,x,y) return y end
            local chosen
            CVPRuntime.actions.ropeBatch=function(_,p,ref) chosen=ref end
            CVPRuntime.actions.batch=function(_,p,ref) chosen=ref end
            carMenu()
            local option
            for _,o in ipairs(context.children) do if o.label==getText('IGUI_CVP_TieNearestBodies') then option=o end end
            assert(option,'direct attach action')
            player.x=car.x-10
            option.run()
            assert(chosen and chosen.point=='front')
        ''')

if __name__ == '__main__': unittest.main()
