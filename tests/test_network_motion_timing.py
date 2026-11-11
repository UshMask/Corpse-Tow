"""Render movement by capture time despite jitter, batching and clock offsets."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
from test_link_multiplayer import Network, take


def trace(fps, timed=True, batched=False):
    lua=LuaRuntime()
    motion=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
    # Server and client clocks intentionally have unrelated origins.
    origin=1_790_000_000_000
    arrivals=sorted((
        (t//200*200+250 if batched else t+100+[0,70,20,120,0][t//100%5]), t
    ) for t in range(0,4001,100))
    row=lua.table();clock=None;cursor=0;latest=-1;previous=None;speeds=[]
    for frame in range(fps*4+1):
        now=frame*1000/fps
        while cursor<len(arrivals) and arrivals[cursor][0]<=now:
            _,sent=arrivals[cursor];cursor+=1
            if sent<=latest:continue  # The transport already rejects old sequences.
            latest=sent
            if timed:clock=motion.syncClock(clock,origin+sent,now)
            motion.push(row,lua.table_from(dict(x=sent*.01,y=0,z=0,angle=0,vehicle=7)),
                        origin+sent if timed else now)
        if row.samples is None:continue
        pose=motion.pose(row,motion.time(clock,now) if timed else now)
        if 600<=now<=3500 and previous is not None:speeds.append((pose.x-previous)*fps)
        previous=pose.x
    return min(speeds),max(speeds)


class NetworkMotionTimingTests(unittest.TestCase):
    def test_client_clock_steps_rebase_instead_of_disabling_interpolation(self):
        for jump in (-60000,60000):
            with self.subTest(jump=jump):
                lua=LuaRuntime()
                motion=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
                clock=motion.syncClock(None,100000,200000)
                clock=motion.syncClock(clock,100100,200100+jump)
                self.assertAlmostEqual(motion.time(clock,200100+jump),100100)

    def test_clock_steps_reset_sample_timeline_in_same_server_session(self):
        for jump in (-60000,60000):
            with self.subTest(jump=jump):
                n=Network();s=n.server;c=n.clients['friend']
                s.execute('link(C,A,rope);now=100000;publish()')
                for p in take(s,'packets'): n.receive(p)
                s.globals().now=100100+jump
                c.execute('now=now+100')
                n.publish()
                c.globals().expected=s.globals().now
                c.execute('''
                    local C=CVPMPClient
                    local time=require('CVP_Motion').time(C.motionClock,now)
                    assert(math.abs(time-expected)<1,'clock step left playback on the old timeline')
                    assert(#C.rows.A.samples==1,'samples span different clock timelines')
                ''')

    def test_constant_server_speed_survives_jitter_reordering_and_batched_delivery(self):
        for fps in (30,60,120):
            for batched in (False,True):
                with self.subTest(fps=fps,batched=batched):
                    low,high=trace(fps,batched=batched)
                    self.assertGreater(low,9.9)
                    self.assertLess(high,10.6)

    def test_better_clock_reference_does_not_jump_or_reverse_playback(self):
        lua=LuaRuntime()
        lua.globals().M=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        lua.execute('''
            local clock=M.syncClock(nil,0,500)
            local previous=M.time(clock,500)
            for now=510,10000,10 do
                if now==600 then M.syncClock(clock,500,now) end
                local t=M.time(clock,now)
                assert(t>=previous and t-previous<=11,'clock correction jumped playback')
                previous=t
            end
            assert(math.abs(previous-9900)<1e-8,'clock never reached its new reference')
        ''')

    def test_real_client_handler_keeps_body_and_rope_end_moving_between_jittered_packets(self):
        n=Network();s=n.server;c=n.clients['friend']
        # Bootstrap Network uses zero-latency delivery. Start a fresh epoch so
        # the measured session establishes its clock over the simulated path.
        s.execute("CVPMPServer.epoch='jittered-session';root=link(C,A,rope)")
        packets=[]
        for t in range(0,4001,100):
            s.globals().sampleTime=t
            s.execute('''
                now=100+sampleTime;local x=sampleTime*.01
                World.move(body,x,0,0,gridSquare(math.floor(x),0,0));car.x=x
                -- This test supplies synthetic poses directly, bypassing runtime
                -- ticks; keep the endpoints coherent and discard the older frame.
                local link=S.graph.links[root]
                for _,side in ipairs({'a','b'}) do
                    local ref=link[side];local point=H.sample(ref)
                    ref.x=point.x;ref.y=point.y;ref.z=point.z
                end
                R.simulationFrame=nil
                publish()
            ''')
            page=next(p for p in take(s,'packets') if p['who']=='friend' and p['name']=='state')
            packets.append((t+100+[0,70,20,120,0][t//100%5],page))
        packets.sort(key=lambda row:row[0])
        cursor=0;previous=None;speeds=[];end_speeds=[];previous_end=None
        for frame in range(241):
            t=frame*1000/60;c.globals().now=100+t
            while cursor<len(packets) and packets[cursor][0]<=t:
                n.receive(packets[cursor][1]);cursor+=1
            # The remote vehicle is already smoothly replicated by the game.
            c.globals().car.x=max(0,(t-250)*.01)
            c.execute('CVPMPClient.tick()')
            x=c.globals().body.x
            # Ignore separate binding-detail meshes: inspect the rope itself.
            points=c.globals().drawn[s.globals().root]
            end=points[len(points)].x if points is not None else None
            if 600<=t<=3500:
                speeds.append((x-previous)*60)
                end_speeds.append((end-previous_end)*60)
            previous=x;previous_end=end
        for values in (speeds,end_speeds):
            self.assertGreater(min(values),9.9)
            self.assertLess(max(values),10.6)

    def test_stall_still_holds_last_server_pose_and_resumes_on_fresh_data(self):
        lua=LuaRuntime()
        lua.globals().M=lua.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Motion.lua').read_text())
        lua.execute('''
            local clock;local row={}
            for t=0,1000,100 do
                clock=M.syncClock(clock,t+50000,t+100)
                M.push(row,{x=t*.01,y=0,z=0,angle=0,vehicle=7},t+50000)
            end
            for now=1350,5000,10 do
                assert(M.pose(row,M.time(clock,now)).x==10,'packet loss invented movement')
            end
            M.push(row,{x=12,y=0,z=0,angle=0,vehicle=7},55000)
            assert(M.pose(row,M.time(clock,5100)).x==12)
        ''')

    def test_pages_share_capture_time_even_when_publication_and_delivery_are_delayed(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('''
            link(C,A,rope);link(A,B,chain);require('CVP_LinkWire').pageSize=1
            now=1000;snapshot=CVPMPServer.capture();now=1100
            CVPMPServer.sequence=CVPMPServer.sequence+1
            CVPMPServer.publish(player2,snapshot)
        ''')
        pages=[p for p in take(s,'packets') if p['who']=='friend' and p['name']=='state']
        self.assertEqual(len(pages),2)
        self.assertTrue(all(p['args']['sampledAt']==1000 for p in pages))
        c.execute('now=1200');n.receive(pages[0])
        c.execute('now=1300');n.receive(pages[1])
        c.execute('''
            assert(CVPMPClient.rows.A.samples[1].time==1000)
            assert(CVPMPClient.rows.B.samples[1].time==1000)
            now=1316;CVPMPClient.tick()
            local host=CVPMPClient.host
            for id,link in pairs(CVPMPClient.graph.links) do
                local points=assert(drawn[id]);local a=assert(host.sample(link.a));local b=assert(host.sample(link.b))
                assert(math.abs(points[1].x-a.x)<1e-6 and math.abs(points[#points].x-b.x)<1e-6,
                    'rope endpoints did not follow the displayed bodies')
            end
        ''')

    def test_mixed_capture_times_cannot_commit_partial_snapshot(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute("link(C,A,rope);link(A,B,chain);require('CVP_LinkWire').pageSize=1;now=1000;publish()")
        pages=[p for p in take(s,'packets') if p['who']=='friend' and p['name']=='state']
        before=c.globals().CVPMPClient.sequence
        n.receive(pages[0]);correct=pages[1]['args']['sampledAt']
        pages[1]['args']['sampledAt']=correct+1;n.receive(pages[1])
        self.assertEqual(c.globals().CVPMPClient.sequence,before)
        pages[1]['args']['sampledAt']=correct;n.receive(pages[1])
        self.assertEqual(c.globals().CVPMPClient.sequence,pages[1]['args']['sequence'])

    def test_invalid_or_missing_timestamp_is_rejected(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('link(C,A,rope);now=1000;publish()')
        page=next(p for p in take(s,'packets') if p['who']=='friend' and p['name']=='state')
        before=c.globals().CVPMPClient.sequence
        for invalid in (-1,.5,float('inf'),float('nan'),'1000'):
            page['args']['sampledAt']=invalid;n.receive(page)
            self.assertEqual(c.globals().CVPMPClient.sequence,before)
        del page['args']['sampledAt'];c.execute('now=1200');n.receive(page)
        self.assertEqual(c.globals().CVPMPClient.sequence,before)
        page['args']['sampledAt']=1000;n.receive(page)
        c.execute('now=1300;CVPMPClient.tick();assert(CVPMPClient.rows.A.body==body)')

    def test_server_restart_resets_clock_and_old_epoch_cannot_shift_it(self):
        n=Network();s=n.server;c=n.clients['friend']
        s.execute('link(C,A,rope);now=100000;publish()')
        old=next(p for p in take(s,'packets') if p['who']=='friend' and p['name']=='state')
        c.execute('now=1000');n.receive(old)
        s.execute("CVPMPServer.epoch='restarted-clock';now=500;publish()")
        new=next(p for p in take(s,'packets') if p['who']=='friend' and p['name']=='state')
        c.execute('now=1200');n.receive(new)
        c.execute("assert(require('CVP_Motion').time(CVPMPClient.motionClock,1200)==500)")
        n.receive(old)
        c.execute("assert(require('CVP_Motion').time(CVPMPClient.motionClock,1210)==510)")


if __name__=='__main__':unittest.main()
