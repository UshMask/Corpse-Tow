"""Corrupt saves may lose towing, never inventories or the ability to attach anew."""
import copy
import unittest
from test_link_runtime import migration_environment
from test_link_graph import environment, plain
from test_link_runtime import environment as runtime


def recovery(lua):
    lua.execute('''
        resets=0
        CVPEquipmentPersistence.resetInvalidStore=function()
            resets=resets+1
            if failBackup then error('backup refused') end
            backup=clone(persisted)
            if failReset then error('replace refused') end
            persisted={version=3,rows={},graph={version=1,revision=0,links={}},discardLegacy=true}
            return clone(persisted)
        end
    ''')


class UpgradeRecoveryTests(unittest.TestCase):
    def test_published_078_ledger_loads_and_returns_original_once_sp_server(self):
        from unittest.mock import patch
        from pathlib import Path
        import test_equipment as equipment
        import test_link_graph as graph
        root=Path('releases/0.7.8/Workshop/Contents/mods/CorpseProxyLab/42/media/lua/shared')
        with patch.object(equipment,'SOURCE',(root/'CVP_Equipment.lua').read_text(encoding='utf-8-sig')), patch.object(graph,'GRAPH',(root/'CVP_LinkGraph.lua').read_text(encoding='utf-8-sig')):
            old=graph.environment(storage=True)
            old.execute("key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))")
            saved=plain(old.globals().persisted); key=old.globals().key
        for role in ('sp','server'):
            with self.subTest(role=role):
                current=graph.environment(saved,storage=True)
                current.globals().server=role=='server'
                current.globals().key=key
                current.execute("assert(E.links().links.link and writes==0); restored=assert(E.get(key)); assert(E.get(key)==restored)")
                self.assertEqual(plain(current.globals().persisted),saved)
                current.execute("assert(E.release(key,destination,transfer,{link={id='link',revision=1}})); assert(destination.rows[1]==restored and #destination.rows==1); assert(not E.release(key,destination,transfer))")

    def saved(self):
        l=environment(storage=True)
        l.execute("key=assert(E.hold(original,transfer,{link={id='link',a=bodyEnd('A'),b=ground(2),owner='alice'}}))")
        return plain(l.globals().persisted)

    def test_corrupt_store_resets_once_and_accepts_new_links_after_restart(self):
        for kind in ('row','equipment','clock','metadata'):
            with self.subTest(kind=kind):
                saved=self.saved()
                if kind=='row': saved['rows']['bad']={'state':'held'}
                elif kind=='equipment': saved['graph']['links']['link']['equipment']='missing'
                elif kind=='clock': saved['bodyClocks']['A']['elapsed']=-1
                else: saved['rows']['bad']={'metadata':12}
                l=environment(saved,storage=True);recovery(l)
                l.execute('assert(next(E.links().links)==nil and resets==1 and decodes==0 and transfers==0);assert(E.links() and resets==1)')
                self.assertEqual(plain(l.globals().backup),saved)
                fresh=environment(plain(l.globals().persisted),storage=True);recovery(fresh)
                fresh.execute('''
                    assert(next(E.members('old-car',{old=true}))==nil)
                    body.md.CVPTether={version=2};assert(E.observeBody(body));assert(body.md.CVPTether==nil)
                    key=assert(E.hold(original,transfer,{link={id='new',a=bodyEnd('B'),b=ground(2),owner='alice'}}))
                    assert(E.links().links.new and resets==0 and E.get(key)==original)
                ''')

    def test_healthy_store_is_not_reset(self):
        l=environment(self.saved(),storage=True);recovery(l)
        l.execute('assert(E.links().links.link and resets==0 and writes==0)')

    def test_backup_or_replace_failure_keeps_old_data_and_inventory(self):
        for failure in ('failBackup','failReset'):
            saved=self.saved();saved['rows']['bad']={}
            l=environment(saved,storage=True);recovery(l);l.globals()[failure]=True
            l.execute('assert(not E.links());assert(original.owner==source and decodes==0 and transfers==0)')
            self.assertEqual(plain(l.globals().persisted),saved)

    def test_read_failure_or_future_version_never_resets(self):
        l=environment(storage=True);recovery(l)
        l.execute("CVPEquipmentPersistence.read=function() error('disk unavailable') end;assert(not E.links() and resets==0)")
        l=environment({'version':99,'rows':{}},storage=True);recovery(l)
        l.execute('assert(not E.links() and resets==0)')

    def test_orphan_alpha_marker_clears_without_deleting_body_or_loot(self):
        l=runtime()
        l.execute('''
            body.md.CVPTether={version=1};local inv=body:getContainer()
            run();assert(body.md.CVPTether==nil and body:getContainer()==inv)
            assert(H.resolve(A,player))
        ''')

    def test_valid_unloaded_legacy_chain_is_not_discarded(self):
        l=migration_environment()
        l.execute('''
            legacy(2);local md=body.md.CVPTether
            assert(E.observeBody(body));assert(body.md.CVPTether==md)
        ''')


if __name__=='__main__': unittest.main()
