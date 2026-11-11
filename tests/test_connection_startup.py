import unittest
from pathlib import Path
from test_link_multiplayer import Network, vm, take
from test_link_runtime import environment


class ConnectionStartupTests(unittest.TestCase):
    def test_wait_starts_at_first_request_and_retries_without_response(self):
        c=vm(False)
        c.execute('''
            local C=CVPMPClient
            C.epoch=nil;C.started=nil;C.nextSync=0;clientPackets={}
            local p=getPlayer();getPlayer=function() return nil end
            now=90000;C.tick()
            assert(C.connectionReason()=='IGUI_CVP_SyncWaiting' and not C.started)
            getPlayer=function() return p end;C.tick()
            assert(C.started==now and #clientPackets==1)
            now=now+1999;C.tick();assert(#clientPackets==1)
            now=now+1;C.tick();assert(#clientPackets==2)
            now=now+8001;assert(C.connectionReason()=='IGUI_CVP_ServerUnavailable')
        ''')

    def test_healthy_heartbeats_suppress_sync_and_lost_connection_recovers(self):
        n=Network();c=n.clients['friend']
        for i in range(1,8):
            n.server.globals().now=100+i*1000
            n.publish()
            c.globals().now=100+i*1000
            c.execute('CVPMPClient.tick()')
            self.assertFalse(any(p['name']=='sync' for p in take(c,'clientPackets')))
        c.execute('now=now+3100;CVPMPClient.tick()')
        requests=take(c,'clientPackets')
        self.assertEqual(sum(p['name']=='sync' for p in requests),1)
        for p in requests: n.send(p)
        n.pump()
        self.assertIsNone(c.globals().CVPMPClient.connectionReason())

    def test_server_backend_error_has_distinct_reply_and_recovers(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('''
            savedBackend=CVPSkeletonNative;CVPSkeletonNative=nil
            CVPMPServer.authority.started=false
            now=now+1000;CVPMPServer.tick()
        ''')
        n.pump()
        self.assertEqual(c.globals().CVPMPClient.connectionReason(),'IGUI_CVP_ServerBackendMissing')
        s.execute('CVPSkeletonNative=savedBackend;now=now+6000;CVPMPServer.tick()')
        n.pump()
        self.assertIsNone(c.globals().CVPMPClient.connectionReason())
        c.execute('''
            local C=CVPMPClient
            C.receive('status',{protocol=require('CVP_LinkWire').version,session=C.session,
                epoch=C.epoch,sequence=C.sequence,error='runtime'})
            assert(C.connectionReason()==nil,'stale error replaced a healthy state')
        ''')
        s.execute("CVPMPServer.error='test storage failure';publish()")
        n.pump()
        self.assertEqual(c.globals().CVPMPClient.connectionReason(),'IGUI_CVP_ServerNotReady')

    def test_sp_does_not_register_mp_handshake(self):
        l=environment()
        l.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_MPClient.lua').read_text(encoding='utf-8-sig'))
        l.execute('assert(CVPMPClient==nil);intact(body);intact(body2)')


if __name__=='__main__': unittest.main()
