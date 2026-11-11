"""Client diagnostics must not mistake missing sync for an old server."""
import unittest
from test_link_multiplayer import vm


class ConnectionDiagnosticsTests(unittest.TestCase):
    def test_wait_timeout_and_recovery(self):
        c = vm(False)
        c.execute('''
            local C=CVPMPClient
            assert(C.connectionReason('twoPointAttach')=='IGUI_CVP_SyncWaiting')
            now=now+11000
            assert(C.connectionReason()=='IGUI_CVP_ServerUnavailable')
            C.receive('state',{protocol=require('CVP_LinkWire').version,session=C.session,epoch='new',sequence=1,revision=0,page=1,count=1,ready=true,frameSchema=1,sampledAt=now,intervalSeconds=0,links={},bodies={},loads={}})
            assert(C.connectionReason('twoPointAttach')==nil)
            assert(C.connectionReason('rewire')==nil)
            now=now+11000
            assert(C.connectionReason()=='IGUI_CVP_SyncLost')
            C.receive('state',{protocol=require('CVP_LinkWire').version,session=C.session,epoch='new',sequence=2,revision=0,page=1,count=1,ready=true,frameSchema=1,sampledAt=now,intervalSeconds=0,links={},bodies={},loads={}})
            assert(C.connectionReason()==nil)
        ''')

    def test_mismatch_and_missing_native_preserve_saved_marker(self):
        c = vm(False)
        c.execute('''
            local C=CVPMPClient
            local marker={saved=true};body.md.CVPTether=marker
            C.receive('state',{protocol=1,rows={}})
            assert(C.connectionReason()=='IGUI_CVP_ProtocolMismatch')
            local finished=false;clientPackets={}
            C.api.request(player,'command',{},function(ok,_,reason)
                assert(not ok and reason=='IGUI_CVP_ProtocolMismatch');finished=true
            end)
            assert(finished and #clientPackets==0 and body.md.CVPTether==marker)
            C.receive('state',{protocol=require('CVP_LinkWire').version,session=C.session,epoch='new',sequence=1,revision=0,page=1,count=1,ready=true,frameSchema=1,sampledAt=now,intervalSeconds=0,links={},bodies={},loads={}})
            assert(C.connectionReason()==nil and body.md.CVPTether==marker)
            CVPWorldNative=nil
            assert(C.connectionReason()=='IGUI_CVP_NativeUnavailable')
        ''')
