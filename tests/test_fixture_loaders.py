"""Current SP/MP boot must not silently read the archived controller."""
from pathlib import Path
from unittest.mock import patch
import unittest
from lua_fixture import create_world


class FixtureLoaderTests(unittest.TestCase):
    def test_world_model_does_not_load_gameplay_controllers(self):
        lua=create_world()
        lua.execute("assert(not package.preload.CVP_Core and not package.loaded.CVP_Menu and not CVPTest)")

    def test_current_sp_and_mp_work_without_archive_reads(self):
        from test_link_client import client
        from test_link_multiplayer import Network
        read=Path.read_text
        def current_only(path,*args,**kwargs):
            if 'v031' in path.parts:
                raise AssertionError('Current fixture accessed archived controller: '+str(path))
            return read(path,*args,**kwargs)
        with patch.object(Path,'read_text',current_only):
            lua=client()
            lua.execute("local e=require 'CVP_Equipment';assert(not e.updateBindings and not e.endTail and not require('CVP_Connection').chainSize)")
            lua.execute("local id=link(C,A,rope);tick();edit(id,'remove','b');assert(rope:getContainer()==storage);intact(body)")
            network=Network()
            network.server.execute('id=link(C,A,rope)')
            network.publish();network.tick(.05)
            network.server.execute("local row=S.graph.links[id];beside(row.b);assert(R:command(player,{id=id,revision=row.revision,side='b',op='remove'}));assert(rope:getContainer()==storage and worldCount(body)==1 and #body.inv.rows==1)")
            network.publish()
