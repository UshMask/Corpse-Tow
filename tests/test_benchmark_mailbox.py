"""Shared transport contracts without a Corpse Tow runtime."""
import json
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
CORE=Path('tools/pz-test/mod/42/media/lua/shared/PZT_Control.lua')
def core(old=False):
    l=LuaRuntime();l.execute(Path('tests/fixtures/benchmark_fixture.lua').read_text())
    if old: l.execute("files['PZTest/request.txt']={'old','1000','change','','END'}")
    l.execute(CORE.read_text())
    l.execute("calls=0;PZTest.register('change',function() calls=calls+1;return calls end)")
    return l

def request(l,ident,command,session=None):
    session=session or l.globals().PZTest.session
    l.globals().files['PZTest/request.txt']=l.table_from([ident,session,command,'','END'])
    l.execute('now=now+250;render()')
    raw=l.globals().outputs['PZTest/response.txt']
    return json.loads(raw) if raw else None

class SharedMailboxTests(unittest.TestCase):
    def test_clean_control_requires_explicit_native_permission_and_stays_sp_only(self):
        for enabled,mp in ((False,False),(True,False),(True,True)):
            l=core();l.globals().allowed=enabled;l.globals().mp=mp
            l.execute('isDebugEnabled=function() return false end;isClient=function() return mp end;'
                'CVPBenchmarkNative={testControlEnabled=function() return allowed end}')
            request(l,'clean','change')
            self.assertEqual(l.globals().calls,1 if enabled and not mp else 0)

    def test_restart_and_stale_session_never_replay_mutations(self):
        l=core(old=True);l.execute('render();assert(calls==0)')
        self.assertFalse(request(l,'stale','change','previous')['ok'])
        self.assertEqual(l.globals().calls,0)
        self.assertTrue(request(l,'connect','hello','*')['result']['ready'])
        self.assertEqual(request(l,'new','change')['result'],1)
        request(l,'new','change');self.assertEqual(l.globals().calls,1)

    def test_pending_operation_survives_diagnostics_and_blocks_mutation(self):
        l=core();l.execute("PZTest.register('long',function() return 'started',true end)")
        self.assertEqual(request(l,'job','long')['state'],'running')
        self.assertFalse(request(l,'conflict','change')['ok'])
        self.assertTrue(request(l,'hello','hello','*')['ok'])
        l.execute("PZTest.complete('job',true,'finished')")
        self.assertEqual(json.loads(l.globals().outputs['PZTest/result-job.json'])['result'],'finished')
        self.assertEqual(request(l,'after','change')['result'],1)

    def test_failed_write_does_not_repeat_mutation(self):
        l=core();l.execute("originalWriter=getFileWriter;getFileWriter=function() error('locked') end")
        request(l,'once','change');self.assertEqual(l.globals().calls,1)
        l.execute('getFileWriter=originalWriter;now=now+250;render()')
        self.assertEqual(json.loads(l.globals().outputs['PZTest/response.txt'])['result'],1)
        request(l,'once','change');self.assertEqual(l.globals().calls,1)

    def test_completion_is_preserved_after_status(self):
        l=core();request(l,'change','change')
        before=l.globals().outputs['PZTest/result-change.json']
        request(l,'hello','hello','*')
        self.assertEqual(l.globals().outputs['PZTest/result-change.json'],before)
