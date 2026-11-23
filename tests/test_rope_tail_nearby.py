"""The vehicle's nearby-rope menu previews and runs a bounded tail route."""
import unittest

from test_link_client import client
from test_link_multiplayer import Network
from test_link_obstacles import WORLD


SCENE = '''
local host=H or CVPMPClient.host
host.discover()
rootPoint=assert(host.sample({kind='vehicle',native=17,point='hitch'}))
function nearVehicle()
    player.x=rootPoint.x;player.y=rootPoint.y
    player:getModData().CVPPoint='feet'
end
function place(b,dx,dy,z)
    local x,y=rootPoint.x+dx,rootPoint.y+(dy or 0)
    z=z or 0
    World.move(b,x,y,z,gridSquare(math.floor(x),math.floor(y),z))
end
function addBody(key,native,dx,dy,z)
    local b=corpse();b.md.CVPBodyKey=key;b.netID=native
    b.getSquare=body.getSquare;b.setSquare=body.setSquare
    b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
    sq:addCorpse(b);place(b,dx,dy,z)
    host.discover()
    return b
end
nearVehicle()
place(body,3);place(body2,6)
third=addBody('D','103',thirdDistance or 8.75)
function option(key)
    for _,opt in ipairs(options) do
        if opt.label==getText(key) then return opt end
    end
end
function preview(key,...)
    local opt=assert(option(key),key)
    assert(not opt.notAvailable,opt.toolTip and opt.toolTip.description)
    opt.onHighlight(opt,{player=0},true)
    local visible=require('CVP_Feedback').previews[0].bodies
    assert(#visible==select('#',...),key..': preview has '..#visible..' bodies')
    local found={}
    for _,b in ipairs(visible) do found[b]=true end
    for _,b in ipairs({...}) do assert(found[b],key..': preview omitted '..b.md.CVPBodyKey) end
    opt.onHighlight(opt,{player=0},false)
    return opt
end
function shape(graph,expectedLinks,expectedRoots,expectedSpools)
    local links,roots,spools=0,0,0
    for _,row in pairs(graph.links) do
        links=links+1
        if row.a.kind=='vehicle' then
            roots=roots+1;assert(row.a.point=='hitch')
        end
    end
    local index=assert(G.index(graph))
    for _,spool in pairs(index.spools) do
        spools=spools+1;assert(spool.used<=G.capacity+1e-7)
    end
    assert(links==expectedLinks,'connections: '..links)
    assert(roots==expectedRoots,'vehicle roots: '..roots)
    assert(spools==expectedSpools,'rope spools: '..spools)
    return index
end
'''


class NearbyRopeTailTests(unittest.TestCase):
    def test_primary_preview_and_queue_follow_three_bodies_on_one_rope(self):
        for distance in (7.5, 8.75):
            with self.subTest(third_distance=distance):
                l=client();l.globals().thirdDistance=distance
                l.execute(SCENE+'''
                    carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2,third).run()
                    local job=completeJob();assert(not job.feedback.reason)
                    local index=shape(S.graph,3,1,1)
                    local last=S.graph.links[index.byBody.D[1].id]
                    assert(last.a.key=='B' and last.b.key=='D')
                    assert(E.get(last.equipment)==rope and chain:getContainer()==storage)
                ''')

    def test_multiplayer_primary_preview_and_replicated_rope(self):
        n=Network()
        for vm in (n.server,*n.clients.values()):
            vm.execute(SCENE)
        owner=n.clients['owner']
        owner.execute("carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2,third).run()")
        self.assertIsNone(n.finish().feedback.reason)
        n.publish()
        n.server.execute('''
            local index=shape(S.graph,3,1,1)
            local last=S.graph.links[index.byBody.D[1].id]
            assert(last.a.key=='B' and require('CVP_Equipment').get(last.equipment)==rope)
        ''')
        for vm in n.clients.values():
            vm.execute('assert(shape(CVPMPClient.graph,3,1,1).byBody.D)')

    def test_add_nearest_can_start_at_existing_tail_without_spare_rope(self):
        l=client();l.execute(SCENE+'''
            place(third,16)
            carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2).run();completeJob()
            nearVehicle();place(third,8.75)
            carMenu();preview('IGUI_CVP_AddNearestBodies',third).run()
            local job=completeJob();assert(not job.feedback.reason)
            assert(shape(S.graph,3,1,1).byBody.D and chain:getContainer()==storage)
        ''')

    def test_first_body_and_new_train_still_start_near_vehicle(self):
        l=client();l.execute(SCENE+'''
            place(body,8.5);place(body2,9)
            carMenu()
            local opt=option('IGUI_CVP_TieNearestBodies')
            assert(not opt or opt.notAvailable)
            assert(not next(S.graph.links) and rope:getContainer()==storage)
        ''')

    def test_grappled_tail_cannot_be_resumed(self):
        l=client();l.execute(SCENE+'''
            place(third,16)
            carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2).run();completeJob()
            nearVehicle();place(third,8.75)
            body2.isBeingGrappled=function() return true end
            carMenu()
            local opt=option('IGUI_CVP_AddNearestBodies')
            assert(not opt or opt.notAvailable)
            assert(not shape(S.graph,2,1,1).byBody.D)
        ''')

    def test_preview_and_queue_exclude_occupied_foreign_and_other_floor_bodies(self):
        l=client();l.execute(SCENE+'''
            local occupied=addBody('occupied','104',1,2)
            addBody('other-end','105',2,2)
            player.getUsername=function() return 'another-player' end
            local existing=link({kind='body',key='occupied',point='feet'},
                {kind='body',key='other-end',point='feet'},chain)
            player.getUsername=function() return 'player' end
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            local external=addBody('foreign','106',1,1)
            external.md.CorpseTowingVehicleToken='foreign-mod'
            addBody('above','107',4,0,1)
            nearVehicle()
            carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2,third).run()
            local job=completeJob();assert(not job.feedback.reason)
            local index=shape(S.graph,4,1,2)
            assert(S.graph.links[existing].owner=='another-player')
            assert(#index.byBody.occupied==1 and not index.byBody.foreign and not index.byBody.above)
        ''')

    def test_blocked_tail_segment_is_skipped_for_clear_alternative(self):
        l=client();l.execute(WORLD+SCENE+'''
            local clear=addBody('clear','104',6,3.5)
            wallX=math.floor(rootPoint.x+7)
            carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2,clear).run()
            local job=completeJob();assert(not job.feedback.reason)
            local index=shape(S.graph,3,1,1)
            assert(index.byBody.clear and not index.byBody.D)
        ''')

    def test_mixed_owner_train_is_skipped_even_when_player_owns_tail(self):
        l=client();l.execute(SCENE+'''
            local function bind(a,b,gear)
                beside(a);local token=assert(S:prepare(player,a,gear:getID(),true))
                beside(b);local ok,id=S:create(player,token,b);assert(ok,id)
                return id
            end
            player.getUsername=function() return 'another-player' end
            local root=bind(C,A,rope)
            player.getUsername=function() return 'player' end
            local tailGear=item('Base.Rope');storage:AddItem(tailGear)
            local tail=bind(A,B,tailGear)
            SandboxVars.CorpseProxyLab.AllowDetachOthers=false
            nearVehicle();carMenu()
            local opt=option('IGUI_CVP_AddNearestBodies')
            assert(not opt or opt.notAvailable)
            assert(not shape(S.graph,2,1,2).byBody.D)

            local clear=addBody('clear','104',-5,0)
            local spare=item('Base.Rope');storage:AddItem(spare)
            carMenu();preview('IGUI_CVP_AddNearestBodies',clear).run()
            local job=completeJob();assert(not job.feedback.reason)
            local index=shape(S.graph,3,2,3)
            assert(index.byBody.clear and not index.byBody.D)
            assert(S.graph.links[root].owner=='another-player' and S.graph.links[tail].owner=='player')
        ''')

    def test_insufficient_length_and_spare_rope_modes(self):
        cases=(('IGUI_CVP_TieNearestBodies',False,1,1),
               ('IGUI_CVP_TieNearestBodies',True,2,2),
               ('IGUI_CVP_SharedMethod',True,2,1))
        for key,spare,links,roots in cases:
            with self.subTest(menu=key,spare=spare):
                l=client();l.globals().label=key;l.globals().spare=spare
                l.globals().links=links;l.globals().roots=roots
                l.execute(SCENE+'''
                    place(body,6.75);place(body2,0,7.50);place(third,16)
                    if spare then extra=item('Base.Rope');storage:AddItem(extra) end
                    carMenu()
                    if spare then preview(label,body,body2).run()
                    else preview(label,body).run() end
                    completeJob()
                    local index=shape(S.graph,links,roots,links)
                    assert(index.byBody.A and (index.byBody.B~=nil)==spare)
                    if spare then assert(extra:getContainer()~=storage) end
                ''')

    def test_chain_limit_still_caps_one_vehicle_train(self):
        l=client();l.execute(SCENE+'''
            SandboxVars.CorpseProxyLab.MaxBodiesPerChain=2
            carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2).run();completeJob()
            assert(not shape(S.graph,2,1,1).byBody.D)
        ''')

    def test_cancel_after_first_keeps_rope_and_stops_before_tail(self):
        l=client();l.execute(SCENE+'''
            local extra=item('Base.Rope');storage:AddItem(extra)
            carMenu();preview('IGUI_CVP_TieNearestBodies',body,body2,third).run()
            local job=activeJob()
            while not next(S.graph.links) do finishStage() end
            require('CVP_Feedback').cancel(player);CVPRuntime.actions:update()
            local index=shape(S.graph,1,1,1)
            assert(job.finished and job.feedback.reason=='IGUI_CVP_CancelledQueue')
            assert(index.byBody.A and not index.byBody.B and not index.byBody.D)
            assert(extra:getContainer()==storage)
        ''')

    def test_target_leaving_the_area_before_click_is_not_reported_as_tied(self):
        l=client();l.execute(SCENE+'''
            place(body2,16);place(third,16)
            carMenu();local opt=preview('IGUI_CVP_TieNearestBodies',body)
            place(body,16);opt.run()
            local job=completeJob()
            assert(job.feedback.reason=='IGUI_CVP_NoNearby' and job.feedback.done==0)
            assert(not next(S.graph.links) and rope:getContainer()==storage)
        ''')


if __name__=='__main__':
    unittest.main()
