"""Free endpoints and independent body chains: rules, races and durable ownership."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
from test_equipment import vm as equipment_vm, plain

GRAPH = Path('CorpseProxyLab/42/media/lua/shared/CVP_LinkGraph.lua').read_text(encoding='utf-8-sig')


def environment(saved=None, storage=False):
    lua = equipment_vm(saved) if storage else LuaRuntime()
    lua.globals().graphSource = GRAPH
    lua.execute('''
        package.preload['CVP_LinkGraph']=function() return assert(loadstring(graphSource))() end
        G=require 'CVP_LinkGraph';graph=G.empty()
        function bodyEnd(key,x,y,z) return {kind='body',key=key,point='feet',x=x or 0,y=y or 0,z=z or 0} end
        function carEnd(key,x,y,z) return {kind='vehicle',key=key,point='hitch',x=x or 0,y=y or 0,z=z or 0} end
        function ground(x,y,z) return {kind='ground',x=x or 0,y=y or 0,z=z or 0} end
        function add(id,a,b,limit,material)
            graph=assert(G.create(graph,id,a,b,'gear-'..id,material or 'Base.Rope','alice',limit))
        end
        function release(id,side)
            local link=graph.links[id]
            graph=assert(G.releaseEnd(graph,id,link.revision,side,link[side],'alice'))
        end
        function take(id,side,actor,others)
            graph=assert(G.take(graph,id,graph.links[id].revision,side,actor or 'alice',others))
        end
    ''')
    return lua


class LinkGraphTests(unittest.TestCase):
    def test_branch_order_reversed_links_joints_and_independent_vehicle_roots(self):
        l=environment();l.execute('''            local joint={kind='joint',key='knot',x=1,y=0,z=0}
            add('root',bodyEnd('A'),carEnd('V'))
            add('middle',joint,bodyEnd('A'))
            add('tail',bodyEnd('B'),joint)
            local front=carEnd('V');front.point='front'
            add('other',front,bodyEnd('C'))
            local index=assert(G.index(graph))
            local branch=G.branch(graph,index,'root','b')
            assert(table.concat(branch.ids,',')=='root,middle,tail')
            assert(#branch.bodies==2 and branch.bodies[1].key=='A' and branch.bodies[2].key=='B')
            assert(branch.last==graph.links.tail and branch.endpoint==graph.links.tail.a)
            local other=G.branch(graph,index,'other','a')
            assert(#other.ids==1 and #other.bodies==1 and other.endpoint.key=='C')
            local reverse=G.branch(graph,index,'tail','a')
            assert(table.concat(reverse.ids,',')=='tail,middle,root')
            assert(reverse.endpoint.kind=='vehicle' and #reverse.bodies==1)
        ''')

    def test_branch_stops_at_ground_held_and_unconnected_joint_without_mutation(self):
        l=environment();l.execute('''            local horse={kind='horse',key='H',point='harness',x=0,y=0,z=0}
            add('root',horse,bodyEnd('A'));add('tail',bodyEnd('A'),ground(1,0,0))
        ''')
        before=plain(l.globals().graph)
        l.execute('''            local branch=G.branch(graph,assert(G.index(graph)),'root','a')
            assert(#branch.ids==2 and #branch.bodies==1 and branch.endpoint.kind=='ground')
        ''')
        self.assertEqual(plain(l.globals().graph),before)
        l.execute('''            take('tail','b')
            local branch=G.branch(graph,assert(G.index(graph)),'root','a')
            assert(branch.endpoint.kind=='held' and #branch.ids==2)
            graph.links.tail.b={kind='joint',key='end-knot',x=1,y=0,z=0}
            branch=G.branch(graph,assert(G.index(graph)),'root','a')
            assert(branch.endpoint.kind=='joint' and #branch.bodies==1)
        ''')

    def test_rebind_uses_only_unallocated_shared_rope(self):
        l=environment();l.execute('''
            graph=assert(G.create(graph,'root',carEnd('car'),bodyEnd('A',3),'rope','Base.Rope','alice',32,true))
            graph=assert(G.create(graph,'tail',bodyEnd('A',3),bodyEnd('B',5),'rope','Base.Rope','alice',32,true))
            release('root','a')
            local original=graph
            local rebound=assert(G.bind(graph,'root',2,'a',carEnd('car',-4),'alice',false,32))
            assert(rebound.links.root.allocation==7 and rebound.links.tail.allocation==2)
            assert(G.index(rebound).spools.rope.used==9)
            assert(original.links.root.allocation==3 and original.links.root.a.kind=='ground')
            local failed,why=G.bind(graph,'root',2,'a',carEnd('car',-8),'alice',false,32)
            assert(not failed and why=='too far')
            assert(graph.links.root.revision==2 and graph.links.tail.allocation==2)
        ''')

    def test_advance_reports_no_change_and_preserves_snapshot_on_failure(self):
        l = environment()
        l.execute('''
            add('x',carEnd('car'),bodyEnd('A',2))
            local original=graph.links.x
            local row,drop,why=G.advance(original,{a=carEnd('car'),b=bodyEnd('A',2)},{})
            assert(row==original and not drop and not why)
            row,drop,why=G.advance(original,{a=carEnd('car',5)},{})
            assert(row==original and why=='unloaded endpoint' and original.a.x==0)
            row,drop,why=G.advance(original,{a=carEnd('car',5,0,1),b=bodyEnd('A',2)},{})
            assert(row==original and why=='different floors' and original.a.z==0)
            original.returning=true
            assert(G.advance(original,{a=carEnd('car',5)},{})==original)
        ''')

    def test_advanced_snapshot_does_not_alias_input_endpoints_or_samples(self):
        l = environment()
        l.execute('''
            add('x',carEnd('car'),bodyEnd('A',2))
            local original=graph.links.x;local samples={a=carEnd('car',1),b=bodyEnd('A',3)}
            local row=G.advance(original,samples,{})
            assert(row~=original and row.a.x==1 and row.b.x==3)
            row.a.x=99;row.b.x=98
            assert(original.a.x==0 and original.b.x==2 and samples.a.x==1 and samples.b.x==3)
            assert(row.equipment==original.equipment and row.revision==original.revision)
        ''')

    def test_authority_attached_motion_is_atomic_and_preserves_configuration(self):
        l=environment();l.execute('''
            add('x',carEnd('car'),bodyEnd('A',2))
            local link=graph.links.x;local a,b=link.a,link.b
            local length,revision,equipment=link.length,link.revision,link.equipment
            for _,sample in ipairs({{}, {a=ground(3)},
                {a=ground(3),b=ground(5,0,1)}, {a=ground(0/0),b=ground(5)}}) do
                local row,drop,why,changed=G.advance(link,sample,{},true)
                assert(row==link and why and not changed and not drop)
                assert(a.x==0 and b.x==2 and a.z==0 and b.z==0)
            end
            for _,kinds in ipairs({{'vehicle','body'},{'body','body'},{'joint','body'},{'body','horse'}}) do
                a.kind,b.kind=kinds[1],kinds[2]
                local sample={a=ground(a.x+1),b=ground(b.x+1)}
                local expected=G.advance(G.copy(link),sample,{})
                local row,drop,why,changed=G.advance(link,sample,{},true)
                assert(row==link and row.a==a and row.b==b and changed and not drop and not why)
                assert(a.x==expected.a.x and b.x==expected.b.x)
                assert(link.length==length and link.revision==revision and link.equipment==equipment)
                assert(select(4,G.advance(link,sample,{},true))==false)
            end
            link.returning=true
            local x=a.x;G.advance(link,{a=ground(x+1),b=ground(b.x+1)},{},true)
            assert(a.x==x)
        ''')

    def test_body_chain_exists_without_vehicle_and_keeps_equipment(self):
        l = environment()
        l.execute('''
            add('one',bodyEnd('A',0),bodyEnd('B',2))
            add('two',bodyEnd('B',2),bodyEnd('C',4))
            local idx=assert(G.index(graph));assert(#idx.byBody.B==2 and next(idx.byVehicle)==nil)
            assert(graph.links.one.length==2 and graph.links.one.equipment=='gear-one')
            release('one','b')
            assert(graph.links.one.b.kind=='ground' and graph.links.two.a.key=='B')
            assert(graph.links.two.b.key=='C' and graph.links.two.equipment=='gear-two')
            assert(#G.index(graph).byBody.B==1)
        ''')

    def test_vehicle_detach_keeps_entire_body_chain(self):
        l = environment()
        l.execute('''
            add('root',carEnd('car'),bodyEnd('A',2))
            add('tail',bodyEnd('A',2),bodyEnd('B',4))
            release('root','a')
            assert(graph.links.root.b.key=='A' and graph.links.tail.b.key=='B')
            assert(next(G.index(graph).byVehicle)==nil)
            graph=assert(G.bind(graph,'root',2,'a',carEnd('new-car',-2),'alice'))
            assert(graph.links.root.a.key=='new-car' and graph.links.root.length==4)
            assert(graph.links.tail.length==2)
        ''')

    def test_only_selected_end_changes_and_failed_rebind_keeps_it_free(self):
        l = environment()
        l.execute('''
            add('x',bodyEnd('A'),bodyEnd('B',2));release('x','b')
            assert(not G.bind(graph,'x',2,'b',bodyEnd('A',1),'alice'))
            assert(graph.links.x.b.kind=='ground' and graph.links.x.revision==2)
            assert(not G.bind(graph,'x',2,'b',bodyEnd('C',30),'alice'))
            assert(graph.links.x.a.key=='A' and graph.links.x.b.kind=='ground')
        ''')

    def test_two_players_cannot_take_same_end_and_one_player_holds_one(self):
        l = environment()
        l.execute('''
            add('x',bodyEnd('A'),ground(2));add('y',bodyEnd('B',5),ground(7))
            local stale=graph.links.x.revision;take('x','b')
            assert(not G.take(graph,'x',stale,'b','bob',true))
            assert(not G.take(graph,'x',2,'b','bob',true))
            assert(not G.take(graph,'y',1,'b','alice'))
            assert(not G.releaseEnd(graph,'x',2,'b',ground(2),'bob',true))
            assert(not G.bind(graph,'x',2,'b',carEnd('car',3),'bob',true))
            assert(not G.remove(graph,'x',2,'bob',true))
            take('y','b','bob',true)
            assert(G.index(graph).held.alice.id=='x' and G.index(graph).held.bob.id=='y')
        ''')

    def test_carry_pays_out_rebind_refits_but_towing_never_pays_out(self):
        l = environment()
        l.execute('''
            add('x',bodyEnd('A'),ground(2));take('x','b')
            local moved,dropped=G.advance(graph.links.x,{a=bodyEnd('A'),b=ground(8)},{alice=true})
            assert(not dropped and moved.length==8 and moved.b.x==8)
            assert(graph.links.x.length==2) -- samples cannot mutate persisted state
            graph.links.x=moved
            graph=assert(G.bind(graph,'x',2,'b',carEnd('car',5),'alice'))
            assert(graph.links.x.length==5 and graph.links.x.equipment=='gear-x')
            moved=G.advance(graph.links.x,{a=bodyEnd('A'),b=carEnd('car',9)},{})
            assert(moved.length==5 and moved.a.x==0 and moved.b.x==9)
        ''')

    def test_overreach_drops_without_moving_player_or_body(self):
        for source_moves in (False, True):
            l = environment(); l.globals().sourceMoves = source_moves
            l.execute('''
                add('x',bodyEnd('A'),ground(2));take('x','b')
                local samples={a=bodyEnd('A',sourceMoves and -20 or 0),b=ground(sourceMoves and 2 or 20)}
                local moved,dropped=G.advance(graph.links.x,samples,{alice=true})
                assert(dropped and moved.b.kind=='ground' and moved.b.holder==nil)
                assert(moved.a.x==samples.a.x and samples.b.x==(sourceMoves and 2 or 20))
                assert(moved.length==2 and moved.revision==3)
            ''')

    def test_seat_death_disconnect_and_reload_release_claim(self):
        l = environment()
        l.execute('''
            add('x',bodyEnd('A'),ground(2));take('x','b')
            local dropped=G.advance(graph.links.x,{a=bodyEnd('A'),b=ground(3)},{alice=false})
            assert(dropped.b.kind=='ground' and dropped.b.x==2)
            local out,changed=G.dropHolders(graph,'bob');assert(not changed and out.links.x.b.kind=='held')
            out,changed=G.dropHolders(graph,'alice');assert(changed and out.links.x.b.kind=='ground')
            local fresh=G.dropHolders(graph);assert(fresh.links.x.b.kind=='ground' and not G.index(fresh).held.alice)
            assert(graph.links.x.b.kind=='held')
        ''')

    def test_ground_end_trails_at_fixed_length_without_flying(self):
        l = environment()
        l.execute('''
            add('x',carEnd('car',0,0,.3),ground(2))
            local length=graph.links.x.length
            local moved=G.advance(graph.links.x,{a=carEnd('car',10,0,.3)},{})
            assert(math.abs(G.distance(moved.a,moved.b)-length)<1e-8)
            assert(moved.b.z==0 and moved.a.z==.3 and moved.length==length)
        ''')

    def test_unloaded_target_does_not_delete_or_reposition_link(self):
        l = environment()
        l.execute('''
            add('x',bodyEnd('A'),ground(2));take('x','b')
            local moved,dropped,reason=G.advance(graph.links.x,{b=ground(20)},{alice=true})
            assert(reason=='unloaded endpoint' and not dropped)
            assert(moved.b.kind=='held' and moved.b.x==2 and moved.equipment=='gear-x')
        ''')

    def test_cycles_branches_two_vehicles_and_floor_changes_rejected(self):
        l = environment()
        l.execute('''
            add('x',bodyEnd('A'),bodyEnd('B',2));add('y',bodyEnd('B',2),bodyEnd('C',4))
            assert(not G.create(graph,'loop',bodyEnd('C',4),bodyEnd('A'),'g','Base.Rope','alice'))
            assert(not G.create(graph,'branch',bodyEnd('B',2),bodyEnd('D',5),'g','Base.Rope','alice'))
            assert(not G.create(graph,'self',bodyEnd('D'),bodyEnd('D'),'g','Base.Rope','alice'))
            add('root',carEnd('car',-2),bodyEnd('A'))
            assert(not G.create(graph,'second-car',bodyEnd('C',4),carEnd('other',6),'g','Base.Rope','alice'))
            assert(not G.create(graph,'floor',bodyEnd('D'),ground(1,0,1),'g','Base.Rope','alice'))
            local moved,drop,why=G.advance(graph.links.root,{a=carEnd('car',-2,0,1),b=bodyEnd('A')},{})
            assert(why=='different floors' and moved.a.z==0)
            -- Parallel roots are legal; joining their tails would close a loop
            -- through the vehicle, even when the player carries an existing end.
            add('parallel',carEnd('car',-2),bodyEnd('D',5))
            local joined,reason=G.create(graph,'cross',bodyEnd('C',4),bodyEnd('D',5),'g','Base.Rope','alice')
            assert(not joined and reason=='loop')
            add('loose',bodyEnd('C',4),ground(5));take('loose','b')
            local revision=graph.revision;local link=graph.links.loose
            joined,reason=G.bind(graph,'loose',link.revision,'b',bodyEnd('D',5),'alice')
            assert(not joined and reason=='loop')
            local occupied=bodyEnd('B',2);occupied.point='neck'
            joined,reason=G.bind(graph,'loose',link.revision,'b',occupied,'alice')
            assert(not joined and reason=='body branch')
            assert(graph.revision==revision and graph.links.loose==link and link.b.kind=='held')
            assert(link.equipment=='gear-loose' and G.index(G.copy(graph)))
        ''')

    def test_limits_are_per_chain_and_lowering_never_erases_existing_links(self):
        l = environment()
        l.execute('''
            add('x',carEnd('car'),bodyEnd('A',2),1)
            add('y',carEnd('car'),bodyEnd('B',-2),1)
            assert(not G.create(graph,'tail',bodyEnd('A',2),bodyEnd('C',4),'g','Base.Rope','alice',1))
            add('tail',bodyEnd('A',2),bodyEnd('C',4),0)
            release('x','a') -- dismantling remains possible after lowering the limit
            assert(graph.links.tail and graph.links.y)
        ''')

    def test_saved_chain_order_does_not_affect_topology(self):
        l = environment()
        l.execute('''
            for i=1,32 do add('link-'..i,bodyEnd('b'..i,i/4),bodyEnd('b'..(i+1),(i+1)/4),0) end
            local reloaded=G.copy(graph);assert(G.index(reloaded))
            assert(not G.withinLimit(G.index(reloaded),'link-1',32))
            assert(G.withinLimit(G.index(reloaded),'link-1',33))
            release('link-16','a');assert(G.index(graph) and graph.links['link-17'])
        ''')

    def test_invalid_payloads_rejected_without_recursive_copy(self):
        for code in ("target.x=0/0", "target.z=math.huge", "target.point='invented'",
                     "target.extra=target", "target.holder=target", "target.key=''", "target.kind='player'"):
            with self.subTest(code=code):
                l = environment(); l.execute("target=bodyEnd('A');"+code+";assert(not G.create(graph,'x',target,ground(2),'g','Base.Rope','alice'))")
        l = environment(); l.execute("graph.extra=graph;assert(not G.index(graph))")

    def test_material_identity_and_endpoint_copies(self):
        for material in ('Base.Rope','Base.HeavyChain','Base.HeavyChain_Hook'):
            l = environment();l.globals().material = material
            l.execute('''local a=bodyEnd('A');local b=ground(2)
                add('x',a,b,32,material);a.x=99;b.kind='held'
                assert(graph.links.x.a.x==0 and graph.links.x.b.kind=='ground' and graph.links.x.material==material)
                assert(not G.create(graph,'dup',bodyEnd('B'),ground(1),'gear-x',material,'alice'))
            ''')


class LinkGraphStorageTests(unittest.TestCase):
    def legacy(self):
        l=environment(storage=True)
        l.execute('''
            metadata.connection.a={kind='vehicle',key='old-car',point='hitch'}
            metadata.connection.b.point='feet';metadata.length=3.5;metadata.slot=1
            key=assert(E.hold(original,transfer,context));assert(E.observeBody(body))
            old=clone(body.md.CVPTether)
            imports={{key=key,id='connection-one',a=carEnd('old-car'),b=bodyEnd('body-one',2),owner='alice'}}
        ''')
        return l

    def test_legacy_import_keeps_length_id_and_original_item(self):
        l=self.legacy()
        l.execute('''
            local before=transfers;assert(E.migrateLinks(imports));assert(E.get(key)==original and transfers==before)
            local g=E.links();assert(g.links['connection-one'].length==3.5 and g.links['connection-one'].equipment==key)
            assert(persisted.rows[key].legacy.bodyKey=='body-one' and persisted.rows[key].bodyKey==nil)
            assert(E.observeBody(body) and body.md.CVPTether==nil and not persisted.rows[key].legacy)
            assert(not E.migrateLinks(imports) and E.get(key)==original)
            assert(next(E.members('old-car',{}))==nil)
        ''')

    def test_old_chunk_cannot_resurrect_migrated_connection_after_restart(self):
        first=self.legacy();first.execute('assert(E.migrateLinks(imports))')
        second=environment(plain(first.globals().persisted),storage=True)
        second.globals().old=second.table_from(plain(first.globals().old),recursive=True)
        second.globals().key=first.globals().key
        second.execute('''
            body.md.CVPTether=old;assert(E.observeBody(body));assert(body.md.CVPTether==nil)
            assert(E.links().links['connection-one'].length==3.5)
            assert(E.get(key) and decodes==1)
        ''')

    def test_legacy_chunk_checkpoint_failure_retains_recovery_marker(self):
        l=self.legacy()
        l.execute('''
            assert(E.migrateLinks(imports));failCheckpoint=true
            assert(not E.observeBody(body) and persisted.rows[key].legacy)
            assert(E.get(key)==original and E.links().links['connection-one'])
            body.md.CVPTether=clone(old);failCheckpoint=false;now=6000
            assert(E.observeBody(body) and body.md.CVPTether==nil and not persisted.rows[key].legacy)
        ''')

    def test_return_before_old_chunk_cleanup_keeps_tombstone(self):
        l=self.legacy()
        l.execute('''
            assert(E.migrateLinks(imports))
            assert(E.release(key,destination,transfer,{link={id='connection-one',revision=1}}))
            assert(next(E.links().links)==nil and persisted.rows[key].state=='released' and persisted.rows[key].legacy)
            assert(E.observeBody(body) and body.md.CVPTether==nil and persisted.rows[key]==nil)
            assert(destination.rows[1]==original)
        ''')

    def test_failed_import_never_changes_old_binding(self):
        for code in ('failWrite=true',"imports[1].a.key='wrong-car'", "imports[1].b.key='wrong-body'", "imports[1].b.point='neck'"):
            with self.subTest(code=code):
                l=self.legacy();l.execute(code+''';assert(not E.migrateLinks(imports))
                    assert(persisted.version==2 and persisted.rows[key].bodyKey=='body-one')
                    assert(E.get(key)==original and body.md.CVPTether.connection.id=='connection-one')
                ''')

    def test_atomic_claim_before_item_transfer_and_full_return(self):
        l = environment(storage=True)
        l.execute('''
            key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))
            assert(persisted.version==3 and persisted.graph.links.link.equipment==key)
            assert(E.get(key)==original and #source.rows==0)
            assert(not E.release(key,destination,transfer))
            assert(E.release(key,destination,transfer,{link={id='link',revision=1}}))
            assert(next(E.links().links)==nil and destination.rows[1]==original)
            assert(not E.release(key,destination,transfer,{link={id='link',revision=1}}))
        ''')

    def test_edit_and_stale_claim_do_not_move_or_duplicate_items(self):
        l = environment(storage=True)
        l.execute('''
            key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))
            local before=transfers;local old=E.links()
            local a=assert(G.take(old,'link',1,'b','alice'))
            local b=assert(G.take(old,'link',1,'b','bob',true))
            assert(E.editLinks(a,old.revision));assert(not E.editLinks(b,old.revision))
            a.links.link.b.holder='changed-copy'
            assert(E.links().links.link.b.holder=='alice' and transfers==before and E.get(key)==original)
            local removed=assert(G.remove(E.links(),'link',2,'alice'))
            assert(not E.editLinks(removed,E.links().revision))
        ''')

    def test_failed_graph_write_preserves_previous_binding_and_equipment(self):
        l = environment(storage=True)
        l.execute('''
            key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))
            local old=E.links();local changed=assert(G.take(old,'link',1,'b','alice'))
            failWrite=true;assert(not E.editLinks(changed,old.revision));failWrite=false
            assert(E.links().links.link.b.kind=='ground' and E.get(key)==original)
        ''')

    def test_rejected_new_connection_does_not_take_material(self):
        l = environment(storage=True)
        l.execute('''
            assert(not E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=bodyEnd('A'),owner='alice'}}))
            assert(original.owner==source and transfers==0 and persisted==nil)
            failWrite=true
            assert(not E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))
            assert(original.owner==source and transfers==0)
        ''')

    def test_failed_transfer_compensation_removes_only_canceled_link(self):
        l = environment(storage=True)
        l.execute('''
            source.refuseRemove=true
            assert(not E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))
            assert(next(E.links().links)==nil and original.owner==source)
        ''')

    def test_failed_return_keeps_connection_addressable_and_retryable(self):
        l = environment(storage=True)
        l.execute('''
            key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))
            destination.refuseAdd=true
            assert(not E.release(key,destination,transfer,{link={id='link',revision=1}}))
            assert(E.links().links.link and E.get(key)==original)
            destination.refuseAdd=nil
            assert(E.release(key,destination,transfer,{link={id='link',revision=1}}))
            assert(next(E.links().links)==nil and destination.rows[1]==original)
        ''')

    def test_fresh_vm_restores_graph_and_exact_item_once(self):
        first = environment(storage=True)
        first.execute("key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))")
        second = environment(plain(first.globals().persisted),storage=True)
        second.globals().key = first.globals().key
        second.execute('''
            local graph=E.links();assert(graph.links.link.a.key=='A' and graph.links.link.b.kind=='ground')
            restored=assert(E.get(key));assert(restored==E.get(key) and decodes==1)
            assert(E.release(key,destination,transfer,{link={id='link',revision=1}}))
            assert(next(E.links().links)==nil)
        ''')
        self.assertEqual(plain(first.globals().original['state']),plain(second.globals().restored['state']))

    def test_corrupt_graph_is_rejected_before_decode_or_item_transfer(self):
        first = environment(storage=True)
        first.execute("key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))")
        saved = plain(first.globals().persisted)
        saved['graph']['links']['link']['equipment']='missing'
        second = environment(saved,storage=True)
        second.execute('assert(not E.links() and decodes==0 and transfers==0)')


if __name__=='__main__':unittest.main()
