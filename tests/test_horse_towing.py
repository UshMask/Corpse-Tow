"""Optional Horse bridge and unchanged equipment/authority contracts."""
import unittest
from test_link_runtime import environment
from test_link_graph import plain


def install_horse(l):
    l.execute('''
        horse=actor('IsoAnimal',2,0);horse.md={};horse.dead=false
        horse.getAnimalID=function() return 1001 end
        horse.getFullName=function() return 'Horse' end
        horse.getModData=function(s) return s.md end
        horse.isDead=function(s) return s.dead end
        horse.getDirectionAngle=function() return 0 end
        horse.getMovementSpeed=function() return horseSpeed or 0 end
        horse.getVariableBoolean=function() return mountedMoving or false end
        horses={horse};rider=player;mounted=false
        function getActivatedMods() return {contains=function(_,id) return id=='Horse' and not missingHorse end} end
        package.preload['HorseMod/HorseManager']=function() return {horses=horses} end
        package.preload['HorseMod/Mounts']=function() return {
            getRider=function() return rider end,hasMount=function(p) return mounted and p==player end} end
        Horse=require 'CVP_Horse';T=Horse.sample(horse);(H or CVPMPClient.host).discover()
    ''')
    return l


def horse_environment():
    return install_horse(environment())


class HorseTowingTests(unittest.TestCase):
    def test_registry_rejects_duplicates_and_retains_dead_anchor_without_scan(self):
        l=horse_environment();l.execute("""
            assert(H.horse(T)==horse)
            local all=Horse.all;Horse.all=function() error('unexpected scan') end
            assert(H.horse(T)==horse);Horse.all=all
            local duplicate=setmetatable({}, {__index=horse})
            horses[2]=duplicate;H.discover();assert(not H.horse(T))
            horses[2]=nil;H.discover();assert(H.horse(T)==horse)
            horse.dead=true;horses[1]=nil;H.discover();assert(H.horse(T)==horse)
            horse.getSquare=function() return nil end;assert(not H.horse(T))
        """)

    def test_horse_model_click_uses_native_animal_pick(self):
        from test_link_client import client
        l=install_horse(client());l.execute('''
            ISWorldObjectContextMenu=ISWorldObjectContextMenu or {}
            ISWorldObjectContextMenu.fetchVars={clickedAnimals={horse}}
            pickedVehicle=car
            menu({})
            choose('IGUI_CVP_TieNearestBodies')
            completeJob()
            local found=false
            for _,row in pairs(S.graph.links) do
                found=found or row.a.kind=='horse' or row.b.kind=='horse'
            end
            assert(found);intact(body)
        ''')

    def test_horse_model_click_over_corpse_keeps_horse_action(self):
        from test_link_client import client
        l=install_horse(client());l.execute('''
            ISWorldObjectContextMenu.fetchVars={clickedAnimals={horse}}
            menu(body)
            choose('IGUI_CVP_TieNearestBodies');completeJob()
            local found=false
            for _,row in pairs(S.graph.links) do
                found=found or row.a.kind=='horse' or row.b.kind=='horse'
            end
            assert(found);intact(body)
        ''')

    def test_saved_horse_link_loads_without_horse_mod_and_can_be_released(self):
        first=horse_environment();first.execute("savedID=link(T,A,rope);assert(R:save())")
        second=environment(plain(first.globals().equipmentDisk))
        second.globals().savedID=first.globals().savedID
        second.execute('''
            assert(S.graph.links[savedID].a.kind=='horse');H.discover()
            assert(equipmentDisk.bodyClocks.A.paused)
            Sim:tick(S.graph,S.index,.05,now)
            beside(S.graph.links[savedID].b)
            assert(S:command(player,{id=savedID,revision=1,side='a',op='release'}))
            assert(S.graph.links[savedID].a.kind=='ground')
            assert(not equipmentDisk.bodyClocks.A.paused)
            assert(not storage:getItems():contains(rope));intact(body)
        ''')

    def test_sp_menu_attaches_to_horse_through_timed_action_queue(self):
        from test_link_client import client
        l=install_horse(client());l.execute('''
            menu(body)
            local label=getText('IGUI_CVP_AttachHorse','Horse')
            local direct=assert(menuBranch(context,label));assert(not direct.subMenu)
            direct.run()
            completeJob()
            local found=false
            for _,row in pairs(S.graph.links) do
                found=found or row.a.kind=='horse' or row.b.kind=='horse'
            end
            assert(found);intact(body)
        ''')

    def test_server_horse_snapshot_is_accepted_by_both_clients(self):
        from test_link_multiplayer import Network
        n=Network()
        install_horse(n.server)
        for c in n.clients.values(): install_horse(c)
        n.server.execute('horseLink=link(T,A,rope);publish()')
        n.pump()
        for c in n.clients.values():
            c.execute('''
                local found=false
                for _,row in pairs(CVPMPClient.graph.links) do found=found or row.a.kind=='horse' end
                assert(found)
            ''')
    def test_rider_tows_without_vehicle_impulses_and_riderless_pauses(self):
        l=horse_environment();l.execute('''
            local id=link(T,A,rope);link(A,B,chain)
            Sim:tick(S.graph,S.index,.05,now)
            local x=body:getX();horse.x=horse.x+.4
            local requests,loads=Sim:tick(S.graph,S.index,.05,now)
            assert(body:getX()>x and #requests==0)
            for _ in pairs(loads) do error('horse must not receive vehicle load') end
            x=body:getX();rider=nil;horse.x=horse.x+.4
            Sim:tick(S.graph,S.index,.05,now);assert(body:getX()==x)
            rider=player;SandboxVars.CorpseProxyLab.HorseTowing=false
            Sim:tick(S.graph,S.index,.05,now);assert(body:getX()==x and S.graph.links[id])
            intact(body);intact(body2)
        ''')

    def test_unload_reload_keeps_identity_and_original_equipment(self):
        l=horse_environment();l.execute('''
            local id=link(T,A,rope);local x=body:getX()
            horses[1]=nil;H.discover();Sim:tick(S.graph,S.index,.05,now)
            assert(body:getX()==x and S.graph.links[id]);assert(R:save())
            horses[1]=horse;H.discover();horse.x=horse.x+.4
            Sim:tick(S.graph,S.index,.05,now);assert(body:getX()>x)
            local e=S.graph.links[id].b;beside(e)
            assert(S:command(player,{id=id,revision=S.graph.links[id].revision,side='b',op='remove'}))
            assert(storage:getItems():contains(rope));intact(body)
        ''')

    def test_mounted_actor_and_moving_horse_cannot_attach(self):
        l=horse_environment();l.execute('''
            beside(T);mounted=true
            assert(not S:prepare(player,T,rope:getID()))
            mounted=false;mountedMoving=true
            assert(not S:prepare(player,T,rope:getID()))
            mountedMoving=false;assert(S:prepare(player,T,rope:getID()))
        ''')

    def test_second_tractor_is_rejected_and_horse_packets_validate(self):
        l=horse_environment();l.execute('''
            link(T,A,rope)
            local out,err=G.create(S.graph,'second',H.sample(A),H.sample(C),'second-gear','Base.Rope','player',32)
            assert(not out and err=='two vehicles')
            local W=require 'CVP_LinkWire';assert(W.ref(T))
            assert(not W.ref({kind='horse',native=1001}))
            assert(not W.ref({kind='horse',key='1001',point='hitch'}))
        ''')

    def test_death_releases_horse_end_without_refunding_material(self):
        l=horse_environment();l.execute('''
            local id=link(T,A,rope);H.horse(T);horse.dead=true;horses[1]=nil
            local requests=R:removedEnds();assert(#requests==1)
            assert(S:releaseSystem(requests));assert(S.graph.links[id].a.kind=='ground')
            assert(not storage:getItems():contains(rope));intact(body)
        ''')

    def test_mount_drops_held_end_without_detaching_horse_link(self):
        l=horse_environment();l.execute('''
            local id=link(T,A,rope);beside(S.graph.links[id].b)
            assert(S:command(player,{id=id,revision=1,side='b',op='release'}))
            assert(S:command(player,{id=id,revision=2,side='b',op='take'}))
            mounted=true;assert(R:players({player}))
            assert(S.graph.links[id].a.kind=='horse' and S.graph.links[id].b.kind=='ground')
        ''')


if __name__=='__main__': unittest.main()
