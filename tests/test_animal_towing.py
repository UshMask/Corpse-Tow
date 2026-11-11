"""Animal corpses use existing graph/authority; no replacement corpse or inventory."""
import unittest
from test_link_simulation import environment
from test_link_multiplayer import Network

ANIMAL = '''
    body.isAnimal=function() return true end
    body.isZombie=function() return false end
    body.getWeight=function() return 450 end
    SandboxVars.CorpseProxyLab.AllowPlayerCorpses=false
    body.getHumanVisual=function() error('human appearance requested for animal') end
    if H then H.discover() end
'''

class AnimalTowingTests(unittest.TestCase):
    def test_mass_refresh_and_existing_resistance(self):
        l=environment();l.execute(ANIMAL+'''
            local L=require 'CVP_Load';local r={body=body}
            local loot=L.mass(body:getContainer())-75
            L.refresh(r,0);assert(r.mass==450+loot)
            body.getWeight=function() return 2 end
            local due=r.nextMassRefresh;assert(due>0 and due<=1000)
            L.refresh(r,due-1);assert(r.mass==450+loot)
            L.refresh(r,due);assert(r.mass==2+loot)
            assert(L.impulse(450,10,1500,.05)>L.impulse(75,10,1500,.05))
            for _,weight in ipairs({0,-1,0/0,math.huge}) do
                body.getWeight=function() return weight end;r.nextMassRefresh=nil
                L.refresh(r,2000);assert(r.mass==75+loot)
            end
            assert(require('CVP_Abrasion').snapshot(body)==nil)
            assert(require('CVP_ClothingWear').snapshot(body)==nil)
            intact(body)
        ''')

    def test_sp_movement_restore_and_return(self):
        l=environment();l.execute(ANIMAL+'''
            assert(World.towable(body));local id=link(C,A,rope)
            local before=body.x
            for i=1,40 do car.x=car.x+.04;step() end
            assert(body.x>before+.1);intact(body)
            assert(S:load());assert(S.graph.links[id].b.key=='A')
            edit(id,'remove','a');assert(rope:getContainer()==storage);intact(body)
            body.isPlayer=function() return true end
            local endpoint,why=H.resolve(A,player)
            assert(not endpoint and why=='player bodies disabled')
        ''')

    def test_mp_animal_movement_and_physics_owner(self):
        n=Network();s=n.server
        for l in (s,*n.clients.values()):l.execute(ANIMAL)
        s.execute('root=link(C,A,rope)');n.publish()
        n.clients['owner'].execute('physicsOwner=true')
        n.clients['friend'].execute('physicsOwner=false')
        for _ in range(40):n.tick(.035)
        s.execute('assert(body.x>0 and #impulses==0);assert(rope:getContainer()~=storage)')
        n.clients['owner'].execute('assert(body.x>0 and #impulses>0)')
        n.clients['friend'].execute('assert(body.x>0 and #impulses==0)')
        s.execute("beside(S.graph.links[root].a);assert(R:command(player,{id=root,revision=S.graph.links[root].revision,side='a',op='remove'}));assert(rope:getContainer()==storage)")
        n.publish()


    def test_cancel_animal_action_keeps_items_sp_and_mp(self):
        from test_link_actions import scene
        for client in (False,True):
            for stage in range(4):
                l=scene(client);l.globals().stage=stage;l.execute(ANIMAL+''' 
                    player.x=-5;car.x=6;local job=Actions:create(player,A,C,rope)
                    for i=1,stage do finishStage() end
                    local action=queued;action:stop();action:perform()
                    assert(job.finished and next(S.graph.links)==nil and rope:getContainer()==storage)
                    intact(body)
                ''')

    def test_animal_removed_from_world_preserves_chain_and_equipment(self):
        from test_link_runtime import environment as runtime
        l=runtime();l.execute(ANIMAL+'''
            local root=link(C,A,rope);local tail=link(A,B,chain);run()
            body.sq:removeCorpse(body);run()
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint')
            assert(E.get(S.graph.links[root].equipment)==rope and E.get(S.graph.links[tail].equipment)==chain)
            assert(body.inv:getItems():size()==1);intact(body2)
        ''')

    def test_animal_menu_carry_and_return(self):
        n=Network();s=n.server;c=n.clients['owner']
        for l in (s,*n.clients.values()):l.execute(ANIMAL)
        c.execute("menu(body);choose('IGUI_CVP_LinkStartCarry')");n.finish();n.publish()
        s.execute("local _,row=next(S.graph.links);assert(row.a.key=='A' and row.b.kind=='held')")
        c.execute("menu(body);choose('IGUI_CVP_LinkRemoveRope')");n.finish();n.publish()
        s.execute('assert(not next(S.graph.links) and rope:getContainer()==storage)')
