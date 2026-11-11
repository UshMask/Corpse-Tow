"""Game Kahlua omits global next; standard Lua fixtures must not mask that."""
import unittest
from test_link_runtime import migration_environment
from test_link_runtime import environment
from test_link_service import service


class KahluaCompatibility(unittest.TestCase):
    def test_legacy_migration_without_next(self):
        for version in (2,3):
            with self.subTest(version=version):
                l=migration_environment()
                l.execute("legacy(%d);next=nil;run();assert(not body.md.CVPTether and not body2.md.CVPTether);intact(body);intact(body2)" % version)

    def test_publish_frame_without_next_preserves_held_endpoint_updates(self):
        l=environment()
        l.execute("""
            local frame=require('CVP_SimulationFrame');local captures=0
            frame.capture=function() captures=captures+1;return {revision=S.graph.revision} end
            R.motionUpdated=false;R.simulationFrame={revision=S.graph.revision}
            S.index.held={};next=nil
            R:publishFrame(100,{});assert(captures==0)
            S.index.held.player=true
            R:publishFrame(101,{});assert(captures==1)
        """)

    def test_attach_without_next(self):
        l=service()
        l.execute("next=nil;local id=create({kind='body',key='B'});assert(E.links().links[id]);assert(E.get(E.links().links[id].equipment)==original);assert(S.pending[player.key]==nil)")

    def test_empty_migration_without_next_does_not_write(self):
        l=environment()
        l.execute('next=nil;local before=equipmentWrites;assert(E.migrateLinks({}));assert(equipmentWrites==before)')


if __name__=='__main__':unittest.main()
