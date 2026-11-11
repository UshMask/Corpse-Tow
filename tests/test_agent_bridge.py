"""Current read-only bridge: local guards, framing, I/O retry and singleton polling."""
import json
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
from test_link_client import client

SOURCE = Path('CVPAgent/42/media/lua/client/CVPA_Bridge.lua')


def bridge():
    lua = client()
    lua.execute(r'''
        files={};writes=0;captures=0;registrations=0
        Events.OnRenderTick={Add=function(fn)
            registrations=registrations+1;callbacks.OnRenderTick=fn
        end}
        function getFileWriter(name)
            if failWrite then error('simulated file locked') end
            return {write=function(_,s) files[name]=s;writes=writes+1 end,close=function() end}
        end
        function getFileReader(name)
            if not files[name] then return end;local rows={}
            for line in files[name]:gmatch('(.-)\n') do rows[#rows+1]=line end
            local i=0;return {readLine=function() i=i+1;return rows[i] end,close=function() end}
        end
        CVPFreeRopeScene.error=function() return '' end
        CVPFreeRopeScene.count=function() return 0 end
        CVPFreeRopeScene.captures=function() captures=captures+1;return captures end
        CVPFreeRopeScene.segments=function() return 0 end
    ''')
    lua.execute("package.preload['PZT_Control']=assert(loadstring(...))", Path('tools/pz-test/mod/42/media/lua/shared/PZT_Control.lua').read_text())
    lua.execute(SOURCE.read_text(encoding='utf-8-sig'))
    return lua


def request(lua, identity, command='corpse.status', session=None):
    session = lua.globals().CVPAgent.session if session is None else session
    lua.globals().files['PZTest/request.txt'] = f'{identity}\n{session}\n{command}\n\nEND\n'
    lua.execute('now=now+250;callbacks.OnRenderTick()')
    response = lua.globals().files['PZTest/response.txt']
    return json.loads(response) if response else None


class AgentBridgeTests(unittest.TestCase):
    def test_multiplayer_and_debug_guards(self):
        source = SOURCE.read_text(encoding='utf-8-sig')
        for mode in ('client', 'server', 'nodebug'):
            with self.subTest(mode=mode):
                lua = LuaRuntime()
                lua.execute("mode=...;function isClient() return mode=='client' end;function isServer() return mode=='server' end;function isDebugEnabled() return mode~='nodebug' end", mode)
                lua.execute(source)
                self.assertIsNone(lua.globals().CVPAgent)
        lua = bridge()
        lua.execute('function isClient() return true end')
        self.assertIsNone(request(lua, 'after-mode-change'))
        self.assertEqual(lua.globals().writes, 0)

    def test_framing_and_json_diagnostics(self):
        lua = bridge()
        invalid = ('partial\n', 'id\n*\nstatus\n\nEND\nextra\n',
                   'x' * 1025 + '\n*\nstatus\n\nEND\n', '!\n*\nstatus\n\nEND\n')
        for text in invalid:
            lua.globals().files['PZTest/request.txt'] = text
            lua.execute('now=now+250;callbacks.OnRenderTick()')
            self.assertEqual(lua.globals().writes, 0)
        message = 'quoted "name" \\ path\nрусский'
        lua.globals().CVPRuntime.visualError = message
        response = request(lua, 'ready', session=lua.globals().CVPAgent.session)
        self.assertTrue(response['ok'])
        self.assertEqual(response['result']['visualError'], message)
        response = request(lua, 'eval', 'eval')
        self.assertFalse(response['ok'])
        self.assertEqual(response['error'], 'unknown command')

    def test_failed_write_replays_result_without_repeating_read_or_callback(self):
        lua = bridge()
        lua.execute(SOURCE.read_text(encoding='utf-8-sig'))
        self.assertEqual(lua.globals().registrations, 1)
        lua.globals().failWrite = True
        self.assertIsNone(request(lua, 'once', 'corpse.scene-status'))
        self.assertEqual(lua.globals().captures, 1)
        lua.globals().failWrite = False
        response = request(lua, 'once', 'corpse.scene-status')
        self.assertTrue(response['ok'])
        self.assertEqual(response['result']['captures'], 1)
        self.assertEqual(lua.globals().captures, 1)
        writes = lua.globals().writes
        self.assertEqual(request(lua, 'once', 'corpse.scene-status'), response)
        self.assertEqual(lua.globals().writes, writes)
        lua.execute('intact(body);intact(body2);assert(rope:getContainer()==storage and chain:getContainer()==storage)')


if __name__ == '__main__':
    unittest.main()
