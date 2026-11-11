"""Motion packet validation with the game's available Lua globals."""
import unittest
from lua_fixture import create_current_fixture


class MotionPageRuntimeTests(unittest.TestCase):
    def test_motion_pages_without_next(self):
        lua = create_current_fixture()
        lua.execute('''
            local W=require 'CVP_LinkWire'
            next=nil -- Confirmed absent in the live B42.21 Kahlua environment.
            local p={frameSchema=1,sampledAt=100,intervalSeconds=.01,
                epoch='e',session='s',sequence=1,revision=0,count=1,page=1,
                ready=true,links={},bodies={},loads={},geometry={}}
            assert(W.motionPage(p),'empty motion heartbeat must be accepted')
            p.geometry={{id='rope',revision=1,length=2,
                a={x=0,y=0,z=0},b={x=2,y=0,z=0}}}
            assert(W.motionPage(p),'valid rope geometry must be accepted')
            p.links={true};assert(not W.motionPage(p),'motion cannot carry graph links')
            p.links={[2]=true};assert(not W.motionPage(p),'sparse links must be rejected')
            p.links={};p.geometry[1].length=0
            assert(not W.motionPage(p),'invalid geometry must still be rejected')
        ''')


if __name__ == '__main__':
    unittest.main()
