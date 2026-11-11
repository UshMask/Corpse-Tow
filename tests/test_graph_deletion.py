"""Deletion-path free-end normalization and graph invariants (acceptance section 2).

Confirmed bug: a shared rope vehicle--bodyA--bodyB, detach middle body A (both
adjacent links become a joint), then delete the vehicle--joint section.  The
remaining link keeps kind='joint' on its now one-edge end because the
CVP_Equipment deletion paths (releaseLink reservation delete, release->finish,
extension return) remove graph rows directly and never run the
releaseOrphanJoints() normalization that CVP_LinkGraph.remove() applies.

These tests use the real modules through the 0.4 client entry point
(test_link_client.client): menu -> action queue -> service -> equipment ledger.
The isolated G.remove() path is already correct and is deliberately not used as
the thing under test here.
"""
import unittest
from test_link_client import client
from test_link_graph import environment, plain
from test_link_runtime import environment as runtime_environment

# Shared helpers. Only definitions: every test injects them into its own VM.
PREAMBLE = r'''
function groundMenu()
    options={};context.children={}
    callbacks.OnFillWorldObjectContextMenu(0,context,{{getSquare=function() return player:getSquare() end}},false)
end
function option(key)
    local label=getText(key);local fallback
    for _,opt in ipairs(options) do if opt.label==label then
        if not opt.notAvailable then return opt end
        fallback=fallback or opt
    end end
    return fallback
end
function tap(key)
    local opt=assert(option(key),'missing menu option '..key)
    opt.run()
    return completeJob()
end
function linksCount()
    local n=0;for _ in pairs(S.graph.links) do n=n+1 end;return n
end
function rowsWithItemID(id)
    local n=0;for _,row in pairs(CVPEquipmentRuntime.data.rows) do if row.id==id then n=n+1 end end;return n
end
function sumAllocations(key)
    local used=0
    for _,row in pairs(S.graph.links) do if row.equipment==key then used=used+(row.allocation or 0) end end
    return used
end
-- No cycles / invalid branch / two tractors / overallocation (G.index), plus
-- the section-2 invariant G.index cannot express: a joint is a pass-through
-- node and must keep exactly two edges after a committed topology change.
function invariantProblems(graph)
    graph=graph or S.graph
    local problems={}
    local idx,why=G.index(graph)
    if not idx then problems[#problems+1]='index: '..tostring(why);return problems end
    for key,spool in pairs(idx.spools) do
        if spool.used>G.capacity+1e-7 then problems[#problems+1]='spool over capacity '..tostring(key) end
    end
    for id,row in pairs(graph.links) do
        if row.allocation and row.allocation>G.capacity+1e-7 then problems[#problems+1]='allocation over capacity '..id end
    end
    for key,edges in pairs(idx.byJoint) do
        if #edges~=2 then problems[#problems+1]='dangling joint '..tostring(key)..' edges='..#edges end
    end
    return problems
end
function assertInvariants(tag,graph)
    local problems=invariantProblems(graph)
    assert(#problems==0,(tag or 'graph')..' invariant: '..table.concat(problems,';'))
end
function freeSide(row,kind)
    if row.a.kind==kind then return 'a' elseif row.b.kind==kind then return 'b' end
end
function sharedRootAndTail()
    local root,tail
    for id,row in pairs(S.graph.links) do
        if row.a.kind=='vehicle' or row.b.kind=='vehicle' then root=id else tail=id end
    end
    assert(root and tail,'expected a vehicle root and a body tail')
    return root,tail
end
function tieShared()
    carMenu();choose('IGUI_CVP_TieNearestBodies');completeJob()
end
function detachMiddle(b)
    menu(b);choose('IGUI_CVP_DetachBodyMiddle');completeJob()
end
-- Remove one section through the real action queue -> service -> ledger.
function sectionRemove(id,side)
    local job=CVPRuntime.actions:command(player,id,S.graph.links[id].revision,side,'remove')
    completeJob()
    assert(job.feedback.reason==nil,'section remove failed: '..tostring(job.feedback.reason))
end
function addThirdBody()
    local b=corpse();b.netID='103';b.md.CVPBodyKey='C'
    b.getSquare=body.getSquare;b.setSquare=body.setSquare
    b.getStaticMovingObjectIndex=body.getStaticMovingObjectIndex;b.getAngle=body.getAngle
    b.world=false;sq:addCorpse(b);move(b,-6,0);H.discover();return b
end
-- After detaching middle body B of car--A--B--C: root(car--A), middle(A--joint), tail(joint--C).
function chainSections()
    local root,middle,tail
    for id,row in pairs(S.graph.links) do
        if row.a.kind=='vehicle' or row.b.kind=='vehicle' then root=id
        else
            local other=row.a.kind=='joint' and row.b or row.a
            if other.key=='A' then middle=id elseif other.key=='C' then tail=id end
        end
    end
    assert(root and middle and tail,'expected three shared sections')
    return root,middle,tail
end
function removalSide(row)
    for _,side in ipairs({'a','b'}) do
        local kind=row[side].kind
        if kind=='body' or kind=='vehicle' or kind=='horse' then return side end
    end
    return 'a'
end
'''


def scenario():
    """Real client entry point plus the shared deletion helpers."""
    l = client()
    l.execute(PREAMBLE)
    return l


class GraphDeletionTests(unittest.TestCase):
    # ------------------------------------------------------------------ section 2
    def test_removing_vehicle_joint_section_normalizes_remaining_end(self):
        """The reproduced bug: remaining end must be ground, neighbours/rope intact."""
        l = scenario()
        l.execute('''
            tieShared()
            local root,tail=sharedRootAndTail()
            local key=S.graph.links[tail].equipment
            assert(S.graph.links[root].equipment==key,'shared rope split across equipment keys')
            assert(S.graph.links[root].allocation and S.graph.links[tail].allocation,'sections not shared')
            assert(math.abs(sumAllocations(key)-G.index(S.graph).spools[key].used)<1e-7,'spool ledger mismatch')
            detachMiddle(body)
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint','middle detach did not create a joint')
            assert(S.graph.links[root].b.key==S.graph.links[tail].a.key,'adjacent ends do not share the joint key')
            assert(linksCount()==2,'links after detach '..linksCount())
            sectionRemove(root,freeSide(S.graph.links[root],'vehicle'))
            assert(S.graph.links[root]==nil,'removed section is still in the graph')
            assert(linksCount()==1,'links after remove '..linksCount())
            local row=assert(S.graph.links[tail],'remaining section lost')
            assert(row.a.kind=='ground','remaining end kind='..row.a.kind..' (expected ground)')
            assert(row.b.kind=='body' and row.b.key=='B','neighbouring end changed: '..row.b.kind..' '..tostring(row.b.key))
            assert(row.allocation==3,'remaining allocation '..tostring(row.allocation))
            assert(math.abs(row.length-3)<1e-9,'remaining length '..tostring(row.length))
            assertInvariants('after vehicle--joint section removal')
            local index=assert(G.index(S.graph))
            local spool=assert(index.spools[key],'spool claim lost')
            assert(math.abs(spool.used-3)<1e-7 and #spool.ids==1,'spool used='..tostring(spool.used)..' ids='..#spool.ids)
            local original=assert(E.get(key),'original rope lost from the ledger')
            assert(original:getID()==rope:getID(),'original rope replaced by another item')
            assert(rowsWithItemID(rope:getID())==1,'original ledger rows='..rowsWithItemID(rope:getID()))
            assert(rope:getContainer()~=storage,'rope returned before the last section')
            assert(storage:getItemWithID(rope:getID())==nil,'rope duplicated into the inventory')
            local diskLink=assert(equipmentDisk.graph.links[tail],'durable graph lost the remaining section')
            assert(diskLink.a.kind=='ground','durable graph end kind='..diskLink.a.kind..' (expected ground)')
            assert(equipmentDisk.graph.links[root]==nil,'durable graph kept the removed section')
        ''')

    def test_remaining_ground_end_taken_dropped_and_rebound(self):
        """After the section delete the freed end is a real pickable ground end."""
        l = scenario()
        l.execute('''
            tieShared()
            local root,tail=sharedRootAndTail()
            local key=S.graph.links[tail].equipment
            detachMiddle(body)
            sectionRemove(root,freeSide(S.graph.links[root],'vehicle'))
            assert(S.graph.links[tail].a.kind=='ground','remaining end kind='..S.graph.links[tail].a.kind)
            beside(S.graph.links[tail].a)
            groundMenu()
            tap('IGUI_CVP_LinkTakeRope')
            assert(S.graph.links[tail].a.kind=='held' and S.graph.links[tail].a.holder=='player',
                'take failed, kind='..S.graph.links[tail].a.kind)
            menu(body)
            tap('IGUI_CVP_DropHeldRope')
            assert(S.graph.links[tail].a.kind=='ground','drop failed, kind='..S.graph.links[tail].a.kind)
            groundMenu()
            tap('IGUI_CVP_LinkTakeRope')
            assert(S.graph.links[tail].a.kind=='held','second take failed, kind='..S.graph.links[tail].a.kind)
            menu(body)
            tap('IGUI_CVP_LinkBindBody')
            local row=assert(S.graph.links[tail],'remaining section lost after bind')
            assert(row.a.kind=='body' and row.a.key=='A','bind end '..row.a.kind..' '..tostring(row.a.key))
            assert(row.b.kind=='body' and row.b.key=='B','neighbour end '..row.b.kind..' '..tostring(row.b.key))
            assert(row.allocation==3,'allocation after bind '..tostring(row.allocation))
            assert(row.length>=.1 and row.length<=row.allocation+1e-9,'length after bind '..tostring(row.length))
            assertInvariants('after take/drop/bind')
            local original=assert(E.get(key),'original rope lost during take/drop/bind')
            assert(original:getID()==rope:getID(),'original rope replaced')
            assert(rowsWithItemID(rope:getID())==1,'original ledger rows='..rowsWithItemID(rope:getID()))
            assert(rope:getContainer()~=storage,'rope returned while still bound')
            assert(linksCount()==1,'unexpected extra links '..linksCount())
        ''')

    def test_fresh_fixture_restores_ground_end_and_item_ownership(self):
        """Save+reload from the persisted ledger restores a pickable ground end."""
        l = scenario()
        l.execute('''
            tieShared()
            local root,tail=sharedRootAndTail()
            key=S.graph.links[tail].equipment
            linkID=tail;ropeID=rope:getID()
            detachMiddle(body)
            sectionRemove(root,freeSide(S.graph.links[root],'vehicle'))
            assert(S.graph.links[tail].a.kind=='ground','remaining end kind='..S.graph.links[tail].a.kind)
            local diskLink=assert(equipmentDisk.graph.links[tail],'durable graph lost the remaining section')
            assert(diskLink.a.kind=='ground','durable graph end kind='..diskLink.a.kind)
            assert(diskLink.allocation==3 and math.abs(diskLink.length-3)<1e-9,'durable section metrics changed')
        ''')
        disk = plain(l.globals().equipmentDisk)
        key = l.globals().key
        link_id = l.globals().linkID
        rope_id = l.globals().ropeID
        self.assertIn(link_id, disk['graph']['links'])
        second = runtime_environment(disk)
        second.globals().linkID = link_id
        second.globals().ropeID = rope_id
        second.globals().key = key
        second.execute('''
            local link=assert(S.graph.links[linkID],'restored graph lost the remaining section')
            assert(link.a.kind=='ground','restored end kind='..link.a.kind)
            assert(link.b.kind=='body' and link.b.key=='B','restored neighbour changed')
            assert(link.allocation==3 and math.abs(link.length-3)<1e-9,'restored metrics changed')
            local original=assert(E.get(key),'restored item lost')
            assert(original:getID()==ropeID,'restored item identity changed')
            local rows=0;for _,row in pairs(CVPEquipmentRuntime.data.rows) do if row.id==ropeID then rows=rows+1 end end
            assert(rows==1,'restored row count='..rows)
            beside(S.graph.links[linkID].a)
            local ok,why=S:command(player,{op='take',id=linkID,revision=S.graph.links[linkID].revision,side='a'})
            assert(ok,why)
            assert(S.graph.links[linkID].a.kind=='held','take after reload failed, kind='..S.graph.links[linkID].a.kind)
            ok,why=S:command(player,{op='remove',id=linkID,revision=S.graph.links[linkID].revision,side='a'})
            assert(ok,why)
            assert(not next(S.graph.links),'links remain after removing the restored section')
            assert(storage:getItemWithID(ropeID),'item not returned after removing the restored section')
            local count=0
            for i=0,storage:getItems():size()-1 do if storage:getItems():get(i):getID()==ropeID then count=count+1 end end
            assert(count==1,'returned item count='..count)
        ''')

    # ------------------------------------------------------------------ section 2
    def test_shared_section_removal_orders_return_item_only_after_last(self):
        """last-to-first, first-to-last and middle-first orders; graph normalized each commit."""
        orders = {
            'last-to-first': ('last', 'middle', 'root'),
            'first-to-last': ('root', 'middle', 'last'),
            'middle-first': ('middle', 'root', 'last'),
        }
        for name, order in orders.items():
            with self.subTest(order=name):
                l = scenario()
                l.execute('''
                    addThirdBody()
                    tieShared()
                    assert(linksCount()==3,'expected three shared sections, got '..linksCount())
                    detachMiddle(body2)
                    root,middle,last=chainSections()
                    key=S.graph.links[root].equipment
                    for _,id in ipairs({root,middle,last}) do
                        assert(S.graph.links[id].equipment==key,'equipment split across sections')
                        assert(S.graph.links[id].allocation,'section is not part of the shared spool')
                    end
                    assertInvariants('after middle body detach')
                ''')
                for step, section in enumerate(order, 1):
                    l.globals().sectionName = section
                    l.globals().step = step
                    l.execute('''
                        local id=assert(_G[sectionName],'missing section variable '..sectionName)
                        local row=assert(S.graph.links[id],'section already gone '..sectionName)
                        sectionRemove(id,removalSide(row))
                        assert(S.graph.links[id]==nil,'section still present '..sectionName)
                        assertInvariants('after removing '..sectionName)
                        assert(linksCount()==3-step,'links after '..sectionName..': '..linksCount())
                        if step<3 then
                            local original=assert(E.get(key),'original item lost after '..sectionName)
                            assert(original:getID()==rope:getID(),'original item replaced after '..sectionName)
                            assert(rowsWithItemID(rope:getID())==1,'original row count='..rowsWithItemID(rope:getID()))
                            assert(math.abs(sumAllocations(key)-G.index(S.graph).spools[key].used)<1e-7,'spool mismatch after '..sectionName)
                            assert(rope:getContainer()~=storage,'item returned before the last section after '..sectionName)
                            assert(storage:getItemWithID(rope:getID())==nil,'item duplicated into inventory after '..sectionName)
                        end
                    ''')
                l.execute('''
                    assert(linksCount()==0,'sections remain: '..linksCount())
                    assertInvariants('after the last section')
                    assert(rope:getContainer()==storage,'item not returned after the last section')
                    assert(storage:getItemWithID(rope:getID())==rope,'original item not exactly returned')
                    assert(not E.get(key),'ledger claim remains after the last section')
                    local rows=0;for _,row in pairs(CVPEquipmentRuntime.data.rows) do if row.id==rope:getID() then rows=rows+1 end end
                    assert(rows==0,'ledger row remains after the last section: '..rows)
                ''')

    # ------------------------------------------------------------------ section 3
    def test_single_item_removal_normalizes_neighbouring_joint_end(self):
        """Single-section path: E.releaseLink -> E.release -> finish deletes the row."""
        l = scenario()
        l.execute('''
            local root=link(C,A,rope)
            local tail=link(A,B,chain)
            local ropeKey=S.graph.links[root].equipment
            local chainKey=S.graph.links[tail].equipment
            detachMiddle(body)
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint','middle detach did not create a joint')
            assert(S.graph.links[root].b.key==S.graph.links[tail].a.key,'adjacent ends do not share the joint key')
            sectionRemove(root,freeSide(S.graph.links[root],'vehicle'))
            assert(S.graph.links[root]==nil,'removed single section is still in the graph')
            local neighbour=assert(S.graph.links[tail],'neighbouring chain section lost')
            assert(neighbour.a.kind=='ground','neighbouring joint end kind='..neighbour.a.kind..' (expected ground)')
            assertInvariants('after single-item section removal')
            assert(neighbour.b.kind=='body' and neighbour.b.key=='B','neighbouring body end changed')
            assert(rope:getContainer()==storage,'single rope not returned exactly')
            assert(storage:getItemWithID(rope:getID())==rope,'single rope returned twice or replaced')
            assert(rowsWithItemID(rope:getID())==0,'ledger row remains for the returned single rope')
            assert(chain:getContainer()~=storage and E.get(chainKey),'neighbouring chain returned early or lost')
            assert(linksCount()==1,'unexpected link count '..linksCount())
        ''')

    def test_extended_link_removal_returns_both_originals_and_normalizes_neighbour(self):
        """Extension path: E.releaseLink returns both originals, then deletes the row."""
        l = scenario()
        l.execute('''
            extra=item('Base.Rope');storage:AddItem(extra)
            local root=link(C,A,rope)
            local job=CVPRuntime.actions:command(player,root,S.graph.links[root].revision,'a','extend',nil,nil,extra)
            completeJob()
            assert(job.feedback.reason==nil,'extend failed: '..tostring(job.feedback.reason))
            local extension=S.graph.links[root].extension
            assert(extension,'link was not extended')
            local ropeKey=S.graph.links[root].equipment
            local tail=link(A,B,chain)
            local chainKey=S.graph.links[tail].equipment
            detachMiddle(body)
            assert(S.graph.links[root].b.kind=='joint' and S.graph.links[tail].a.kind=='joint','middle detach did not create a joint')
            sectionRemove(root,freeSide(S.graph.links[root],'vehicle'))
            assert(S.graph.links[root]==nil,'extended section is still in the graph')
            local neighbour=assert(S.graph.links[tail],'neighbouring chain section lost')
            assert(neighbour.a.kind=='ground','neighbouring joint end kind='..neighbour.a.kind..' (expected ground)')
            assertInvariants('after extended-link removal')
            assert(rope:getContainer()==storage,'first original rope not returned')
            assert(extra:getContainer()==storage,'extension rope not returned')
            assert(storage:getItemWithID(rope:getID())==rope,'first original rope duplicated or replaced')
            assert(storage:getItemWithID(extra:getID())==extra,'extension rope duplicated or replaced')
            local rows=0
            for _,row in pairs(CVPEquipmentRuntime.data.rows) do
                if row.id==rope:getID() or row.id==extra:getID() then rows=rows+1 end
            end
            assert(rows==0,'ledger rows remain for returned extension originals: '..rows)
            assert(chain:getContainer()~=storage and E.get(chainKey),'neighbouring chain lost')
            assert(linksCount()==1,'unexpected link count '..linksCount())
        ''')

    def test_unfinished_shared_return_recovers_once_without_graph_damage(self):
        """Failed final checkpoint then E.recover: no duplicate, graph still normalized."""
        l = environment(storage=True)
        l.execute(PREAMBLE)
        l.execute('''
            key=assert(E.hold(original,transfer,{link={id='a',a=carEnd('car'),b={kind='joint',key='knot',x=2,y=0,z=0},
                owner=player.key,shared=true}}))
            local old=E.links()
            assert(E.editLinks(assert(G.create(old,'b',{kind='joint',key='knot',x=2,y=0,z=0},
                bodyEnd('B',4),key,'Base.Rope',player.key,32,true)),old.revision))
            assert(E.releaseLink('a',1,destination,transfer))
            local graph=E.links()
            local neighbour=assert(graph.links.b,'remaining section lost')
            assert(neighbour.a.kind=='ground','remaining end kind='..neighbour.a.kind..' (expected ground)')
            assertInvariants('after shared reservation delete',graph)
            local revision=neighbour.revision
            assert(#destination.rows==0 and E.get(key),'item returned before the last section')
            failCheckpoint=true
            assert(not E.releaseLink('b',revision,destination,transfer),'failed checkpoint returned success')
            failCheckpoint=false
            -- The failed checkpoint happened after delivery: the link must stay
            -- addressable and the original must exist exactly once (delivered),
            -- never a second copy in escrow.
            assert(E.links().links.b,'failed return dropped the link without an acknowledgement')
            assert(#destination.rows==1 and destination.rows[1]==original,'failed return lost the delivered original')
            assertInvariants('after failed final return',E.links())
            assert(E.recover(target),'recovery failed')
            assert(not next(E.links().links),'recovered graph keeps the link')
            assert(#destination.rows==1 and destination.rows[1]==original,'recovery duplicated or moved the original')
            assert(not E.releaseLink('b',revision,destination,transfer),'second return duplicated the item')
            assert(#destination.rows==1,'exported duplicate item')
        ''')

    def test_graph_invariants_hold_across_deletion_paths(self):
        """The invariant checker covers cycles/branches/vehicles/budget/joints."""
        l = scenario()
        l.execute('''
            local function bodyEnd(key,x,y) return {kind='body',key=key,point='feet',x=x or 0,y=y or 0,z=0} end
            local function carEnd(key,x,y) return {kind='vehicle',key=key,point='hitch',x=x or 0,y=y or 0,z=0} end
            local function jointEnd(key,x,y) return {kind='joint',key=key,x=x or 0,y=y or 0,z=0} end
            local function row(id,a,b,equipment,material,allocation)
                return {id=id,revision=1,a=a,b=b,equipment=equipment,material=material or 'Base.Rope',
                    owner='player',length=G.distance(a,b),allocation=allocation}
            end
            local function problems(links) return invariantProblems({version=1,revision=1,links=links}) end
            assert(#problems({valid=row('valid',carEnd('car'),bodyEnd('A',2),'g')})==0,'valid graph rejected')
            local two=problems({a=row('a',carEnd('car'),bodyEnd('A',2),'g1'),
                b=row('b',bodyEnd('A',2),carEnd('other',4),'g2')})
            assert(#two==1 and two[1]:find('two vehicles',1,true),'two-tractor graph not rejected: '..table.concat(two,','))
            local branch=problems({a=row('a',carEnd('car'),bodyEnd('A',2),'g1'),
                b=row('b',bodyEnd('A',2),bodyEnd('B',3),'g2'),
                c=row('c',bodyEnd('A',2),bodyEnd('C',4),'g3')})
            assert(#branch==1 and branch[1]:find('branch',1,true),'body branch not rejected: '..table.concat(branch,','))
            local loop=problems({a=row('a',bodyEnd('A',2),bodyEnd('B',3),'g1'),
                b=row('b',bodyEnd('B',3),bodyEnd('C',4),'g2'),
                c=row('c',bodyEnd('C',4),bodyEnd('A',2),'g3')})
            assert(#loop==1 and loop[1]:find('loop',1,true),'cycle not rejected: '..table.concat(loop,','))
            local over=problems({a=row('a',carEnd('car'),bodyEnd('A',2),'rope','Base.Rope',8),
                b=row('b',bodyEnd('A',2),bodyEnd('B',3),'rope','Base.Rope',8)})
            assert(#over==1 and (over[1]:find('exhausted',1,true) or over[1]:find('capacity',1,true)),
                'overallocated spool not rejected: '..table.concat(over,','))
            local dangling=problems({a=row('a',jointEnd('knot',2),bodyEnd('A',3),'g')})
            assert(#dangling==1 and dangling[1]:find('dangling joint',1,true),'one-edge joint not rejected: '..table.concat(dangling,','))
            -- The same detector runs against the live committed graph throughout deletions.
            tieShared()
            local root,tail=sharedRootAndTail()
            assertInvariants('after shared tie')
            detachMiddle(body)
            assertInvariants('after middle body detach')
            sectionRemove(root,freeSide(S.graph.links[root],'vehicle'))
            assertInvariants('after committed vehicle--joint delete')
            assert(S.graph.links[tail].a.kind=='ground','remaining end kind='..S.graph.links[tail].a.kind)
        ''')


if __name__ == '__main__':
    unittest.main()
