from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


class OptionalViewpoint(unittest.TestCase):
    def bridge(self, setup=''):
        lua=LuaRuntime();lua.execute(setup)
        bridge=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Viewpoint.lua').read_text())
        return lua,bridge

    def test_absent_viewpoint_is_a_noop(self):
        _,bridge=self.bridge()
        bridge.track(None);bridge.untrack(None);bridge.clear()

    def test_loader_exposes_adapter_before_first_body(self):
        lua,bridge=self.bridge('''
            calls=0; installs=0
            CVPViewpointLoader={install=function()
                installs=installs+1
                CVPViewpoint={track=function() calls=calls+1 end}
            end}
        ''')
        bridge.track(None);bridge.track(None)
        self.assertEqual(lua.globals().installs,1)
        self.assertEqual(lua.globals().calls,2)

    def test_unavailable_integration_does_not_interrupt_body_operations(self):
        lua,bridge=self.bridge('''
            warnings=0;print=function() warnings=warnings+1 end
            CVPViewpointLoader={install=function() error('unavailable') end}
        ''')
        bridge.track(None);bridge.untrack(None);bridge.clear()
        self.assertEqual(lua.globals().warnings,1)
