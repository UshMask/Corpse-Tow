"""Second-rope ownership, partial returns, and usable extended distances."""
import unittest
from test_link_graph import environment, plain
from test_link_runtime import environment as runtime


def ledger(saved=None):
    l=environment(saved,storage=True)
    l.execute('''
        function base()
            primary=assert(E.hold(original,transfer,{link={id='section',a=bodyEnd('A'),b=ground(3),owner=player.key}}))
            extra=item({id=43,type='Base.Rope',condition=27,name='extension',weight=.7,modData={tag='second'}})
            source:AddItem(extra)
        end
        function extend()
            local row=E.links().links.section
            return E.hold(extra,transfer,{extend={id='section',revision=row.revision,owner=player.key}})
        end
        function remove()
            return E.releaseLink('section',E.links().links.section.revision,destination,transfer)
        end
    ''')
    return l


class LinkExtensionTests(unittest.TestCase):
    def test_sp_menu_approaches_extends_from_nested_bag_and_returns_both_ropes(self):
        from test_link_client import client
        l=client();l.execute('''
            id=link(C,A,rope);bag=item('Base.Bag_DuffelBag');bag.kind='InventoryContainer';bag.inv=container()
            bag.getInventory=function(s) return s.inv end;storage:AddItem(bag)
            extra=item('Base.Rope');extra.md={tag='nested extra'};bag.inv:AddItem(extra)
            player.x=5;menu(body);choose('IGUI_CVP_LinkExtend');completeJob()
            assert(S.graph.links[id].extension and E.get(S.graph.links[id].extension)==extra)
            assert(player.x<2 and bag.inv:getItems():size()==0)
            menu(body);for _,opt in ipairs(options) do assert(opt.label~=getText('IGUI_CVP_LinkExtend')) end
            local remove
            for _,opt in ipairs(options) do if opt.label==getText('IGUI_CVP_LinkRemoveRopeSection') then remove=opt end end
            assert(remove and remove.toolTip.description==getText('IGUI_CVP_RemoveExtendedHint'))
            remove.run();completeJob()
            assert(rope:getContainer()==storage and extra:getContainer()==storage and extra.md.tag=='nested extra')
            assert(not next(S.graph.links));intact(body)
        ''')

    def test_cancelled_extension_action_never_consumes_second_rope(self):
        from test_link_client import client
        l=client();l.execute('''
            id=link(C,A,rope);local before=equipmentCopy(S.graph)
            extra=item('Base.Rope');storage:AddItem(extra);player.x=5
            menu(body);choose('IGUI_CVP_LinkExtend');ISTimedActionQueue.clear(player)
            assert(activeJob().finished and extra:getContainer()==storage and not S.graph.links[id].extension)
            assert(S.graph.links[id].revision==before.links[id].revision)
        ''')

    def test_multiplayer_menu_replicates_extension_and_exact_item_returns(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server;c=n.clients['owner']
        for l in (s,*n.clients.values()):
            l.execute("extra=item('Base.Rope');extra.md={tag='second rope'};storage:AddItem(extra)")
        s.execute('id=link(C,A,rope)');n.publish()
        c.execute("menu(body);choose('IGUI_CVP_LinkExtend')");n.finish();n.publish()
        s.execute('local row=S.graph.links[id];assert(row.extension and require("CVP_Equipment").get(row.extension)==extra)')
        for l in n.clients.values():l.execute('local _,row=next(CVPMPClient.graph.links);assert(row.extension and row.length>12)')
        c.execute("menu(body);choose('IGUI_CVP_LinkRemoveRopeSection')");n.finish();n.publish()
        s.execute('assert(rope:getContainer()==storage and extra:getContainer()==storage and not next(S.graph.links))')
        c.execute('assert(storage:getItems():size()==3 and storage:getItemWithID(extra.id):getModData().tag=="second rope")')
        for l in n.clients.values():l.execute('assert(not next(CVPMPClient.graph.links))')

    def test_extend_adds_twelve_metres_and_returns_both_original_states(self):
        l=ledger();l.execute('''
            base();secondary=assert(extend());local graph=E.links();local row=graph.links.section
            assert(row.equipment==primary and row.extension==secondary and row.length==15)
            assert(G.capacityFor(row)==24 and E.linkReady(row)==original and E.get(secondary)==extra)
            graph=assert(G.take(graph,'section',row.revision,'b',player.key))
            graph=assert(G.bind(graph,'section',graph.links.section.revision,'b',carEnd('car',23),player.key))
            assert(graph.links.section.length==23 and not G.bind(graph,'section',graph.links.section.revision,'b',carEnd('car',25),player.key))
            assert(remove());assert(destination:getItemWithID(42)==original and destination:getItemWithID(43)==extra)
            assert(#destination.rows==2 and not next(E.links().links) and not next(persisted.rows))
        ''')
        self.assertEqual(l.globals().extra.state.name,'extension')
        self.assertEqual(l.globals().original.state.condition,63)

    def test_third_rope_chains_foreign_owner_and_duplicate_key_are_rejected(self):
        for case in ('third','chain','owner','duplicate'):
            with self.subTest(case=case):
                l=ledger();l.execute('base()')
                if case=='third':
                    l.execute("assert(extend());extra=item({id=44,type='Base.Rope'});source:AddItem(extra)")
                elif case=='chain':l.execute("extra.state.type='Base.HeavyChain'")
                elif case=='owner':l.execute("player.key='other'")
                else:l.execute('forcedKey=primary')
                before=plain(l.globals().persisted)
                l.execute('assert(not extend());assert(extra.owner==source and #destination.rows==0)')
                self.assertEqual(before,plain(l.globals().persisted))

    def test_failed_second_take_restores_original_section_without_returning_primary(self):
        l=ledger();l.execute('''
            base();local oldLength=E.links().links.section.length
            local normal=transfer;transfer=function(i,a,b) if i==extra then return false,'refused' end;return normal(i,a,b) end
            local key,why=extend();assert(not key and why)
            local row=E.links().links.section
            assert(row.length==oldLength and not row.extension and E.get(primary)==original and extra.owner==source)
            transfer=normal;assert(extend());assert(remove());assert(#destination.rows==2)
        ''')

    def test_failed_commit_keeps_second_rope_pending_until_recovery(self):
        l=ledger();l.execute('''
            base();failWriteAt=writes+2
            local key,why=extend();assert(key and why)
            assert(not E.linkReady(E.links().links.section) and not extra.owner:getCharacter())
            assert(E.recover(player));assert(E.linkReady(E.links().links.section)==original)
            assert(E.get(key)==extra and E.links().links.section.length==15)
            assert(remove());assert(#destination.rows==2)
        ''')

    def test_partial_return_survives_fresh_vm_and_does_not_duplicate_first_rope(self):
        a=ledger();a.execute('''
            base();assert(extend());local normal=transfer
            transfer=function(i,src,dst) if i==extra and dst==destination then return false,'second refused' end;return normal(i,src,dst) end
            assert(not remove());local row=E.links().links.section
            assert(row.returning and #destination.rows==1 and destination.rows[1]==original)
            assert(E.get(row.extension)==extra and not E.linkReady(row))
            assert(not G.take(E.links(),'section',row.revision,'b',player.key))
            assert(not G.extend(E.links(),'section',row.revision,'another',player.key))
        ''')
        b=ledger(plain(a.globals().persisted))
        b.globals().first=b.table_from(plain(a.globals().original.state),recursive=True)
        b.execute('''
            source:Remove(original);destination:AddItem(item(first))
            assert(remove());assert(#destination.rows==2 and not next(E.links().links))
            assert(destination:getItemWithID(42).state.name=='original')
            assert(destination:getItemWithID(43).state.name=='extension')
            assert(not E.releaseLink('section',1,destination,transfer));assert(#destination.rows==2)
        ''')

    def test_return_write_failure_preserves_delivered_original_and_can_retry(self):
        l=ledger();l.execute('''
            base();assert(extend());failWriteAt=writes+3
            assert(not remove());assert(#destination.rows==1 and destination.rows[1]==original)
            assert(E.links().links.section.returning and not E.get(primary))
            assert(remove());assert(#destination.rows==2 and not next(E.links().links))
        ''')

    def test_fresh_save_restores_both_native_payloads_and_fixed_length(self):
        a=ledger();a.execute('base();assert(extend())')
        expected=[plain(a.globals().original.state),plain(a.globals().extra.state)]
        b=ledger(plain(a.globals().persisted));b.execute('''
            source:Remove(original);local row=E.links().links.section
            assert(row.length==15 and row.extension and E.linkReady(row))
            assert(remove());assert(#destination.rows==2)
        ''')
        actual=[plain(b.globals().destination.rows[i].state) for i in (1,2)]
        self.assertEqual(expected,actual)

    def test_disconnect_can_drop_held_end_while_second_take_is_unresolved(self):
        l=ledger();l.execute('''
            base();local graph=E.links();local held=assert(G.take(graph,'section',1,'b',player.key))
            assert(E.editLinks(held,graph.revision));failCheckpoint=true
            local key,why=extend();assert(key and why)
            graph=E.links();local dropped=assert(G.dropHolders(graph,player.key))
            assert(E.editLinks(dropped,graph.revision));assert(E.links().links.section.b.kind=='ground')
            failCheckpoint=false;assert(E.recover(player));assert(remove());assert(#destination.rows==2)
        ''')

    def test_extended_section_can_tow_beyond_old_eighteen_metre_cutoff(self):
        l=runtime();l.execute('''
            local id=link(C,A,rope);local extra=item('Base.Rope');storage:AddItem(extra)
            beside(S.graph.links[id].b)
            assert(R:command(player,{id=id,revision=S.graph.links[id].revision,side='b',op='extend',gear=extra:getID()}))
            edit(id,'release','a');edit(id,'take','a')
            player.x=21;player.y=0;run()
            assert(S.graph.links[id].a.kind=='held')
            car.x=21;edit(id,'bind','a',C)
            assert(S.graph.links[id].length>20 and S.graph.links[id].length<=24)
            for i=1,30 do car.x=car.x+.05;run() end
            assert(S.graph.links[id].a.kind=='vehicle' and body.x>.1)
            intact(body);assert(E.get(S.graph.links[id].extension)==extra)
        ''')

    def test_unresolved_extension_does_not_stop_an_independent_train(self):
        l=runtime();l.execute('''
            local first=link(C,A,rope);local second=link(C,B,chain)
            local extra=item('Base.Rope');storage:AddItem(extra);beside(S.graph.links[first].b)
            equipmentCheckpointFailure=true
            assert(not R:command(player,{id=first,revision=S.graph.links[first].revision,side='b',op='extend',gear=extra:getID()}))
            body.md.CorpseTowingVehicleToken='other-mod'
            for i=1,30 do car.x=car.x+.05;run() end
            assert(body2.x>-2.9 and S.graph.links[second].a.kind=='vehicle')
            assert(S.graph.links[first].extension and not E.linkReady(S.graph.links[first]))
            equipmentCheckpointFailure=false;now=now+5000;run()
            assert(S.graph.links[first].b.kind=='ground' and E.linkReady(S.graph.links[first]))
        ''')


if __name__=='__main__':unittest.main()
