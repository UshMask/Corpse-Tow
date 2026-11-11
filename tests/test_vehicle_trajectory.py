"""Confirmed packet trajectory and time-integrated load; no running game."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path('CorpseProxyLab/42/media/lua/shared')

class VehicleTrajectoryTests(unittest.TestCase):
    def test_local_stall_retains_unconsumed_physics_interval(self):
        l=self.runtime();l.execute('''
            local clock=0
            CVPVehicleMotion.localTime=function() return clock end
            CVPVehicleMotion.sample=function() error('local vehicle must not read packets') end
            T.sample(tracks,vehicle,'hitch',{x=0,y=0,z=.25},0,.01,true,0)
            clock=309
            local n=T.sample(tracks,vehicle,'hitch',{x=6.18,y=0,z=.25},309,.30,true,.009)
            assert(math.abs(n.hitchX-6)<1e-9,'stall advanced hitch past consumed physics time')
            clock=319
            n=T.sample(tracks,vehicle,'hitch',{x=6.38,y=0,z=.25},319,.01,true,.009)
            assert(math.abs(n.hitchX-6.2)<1e-9,'next tick compensated for a skipped remainder')
        ''')

    def test_local_physics_clock_stop_and_restart_do_not_use_packet_clock(self):
        l=self.runtime();l.execute('''
            local clock=0
            CVPVehicleMotion.localTime=function() return clock end
            CVPVehicleMotion.sample=function() error('SP must not read network packets') end
            local function localSample(time,x,now)
                clock=time
                return T.sample(tracks,vehicle,'hitch',{x=x,y=0,z=.25},now,.016,true,.004)
            end
            localSample(0,0,0);localSample(10,.2,16);localSample(30,.6,33)
            local r=localSample(60,1.2,66)
            assert(math.abs(r.hitchX-1.12)<1e-8,'render timestamp distorted physical velocity')
            for time=100,1000,100 do
                r=localSample(time,1.2,time)
                assert(r.hitchX<=1.2,'stationary car extrapolated')
            end
            r=localSample(0,100,1100)
            assert(r.hitchX==100,'old trajectory survived physics clock restart')
        ''')

    def runtime(self):
        l=LuaRuntime();l.globals().T=l.execute((ROOT/'CVP_VehicleTrajectory.lua').read_text())
        l.execute("""
            vehicle={owner=1,getCurrentSpeedKmHour=function() return 72 end,
                getNetPlayerId=function(s) return s.owner end}
            tracks={};reads=0;packet=nil
            CVPVehicleMotion={sample=function() reads=reads+1;return packet end}
            function send(time,x)
                packet={time=time,owner=vehicle.owner,speed=20,z=.25,hitchX=x,hitchY=0,frontX=x+4,frontY=0}
            end
            function sample(now,point)
                return T.sample(tracks,vehicle,point or 'hitch',{x=0,y=0,z=.25},now,.05)
            end
        """);return l

    def test_shared_input_time_not_polling_or_packet_arrival_time(self):
        l=self.runtime();l.execute("""
            send(0,0);sample(0);send(150,3);sample(180);send(300,6)
            local a=sample(330);local b=sample(330)
            assert(a==b and math.abs(a.hitchX-3.6)<1e-8 and reads==3)
            local front=sample(330,'front');assert(reads==3 and math.abs(front.hitchX-a.hitchX-4)<1e-8)
            local old=a.x
            local c=sample(350);assert(math.abs(c.hitchX-4)<1e-8)
            assert(c.x==old)
        """)

    def test_stationary_packets_and_missing_packets_do_not_extrapolate(self):
        l=self.runtime();l.execute("""
            send(0,0);sample(0);send(150,3);sample(150)
            send(300,3);local r=sample(300)
            assert(r.packetTime==300)
            for now=350,3000,50 do r=sample(now);assert(r.hitchX==3) end
        """)

    def test_handoff_discards_previous_timeline(self):
        l=self.runtime();l.execute("""
            send(0,0);sample(0);send(150,3);local old=sample(150)
            vehicle.owner=2;send(20,10);local current=sample(200)
            assert(current~=old and current.owner==2 and current.hitchX==10)
        """)

    def test_new_packet_history_reanchors_clock_after_forward_time_step(self):
        l=self.runtime();l.execute("""
            send(0,0);sample(0);send(150,3);sample(150)
            -- The engine resynchronizes its physics clock after loading/joining.
            send(10000,6);sample(500);send(10150,9);sample(650)
            local r=sample(800)
            assert(math.abs(r.hitchX-9)<1e-8, 'new history stuck in the future')
            assert(sample(3000).hitchX==9, 'missing packets must not extrapolate')
        """)

class LoadWindowTests(unittest.TestCase):
    def setUp(self):
        self.l=LuaRuntime();self.l.globals().W=self.l.execute((ROOT/'CVP_LoadWindow.lua').read_text())
        self.l.execute('w=W.new();v={owner=1,getNetPlayerId=function(s) return s.owner end}')

    def test_time_weighting_including_zero_ticks_and_read_only_capture(self):
        self.l.execute("""
            W.add(w,{},.05,1,true);W.add(w,{[v]=100},.025,1,true);W.add(w,{[v]=200},.025,1,true)
            assert(math.abs(W.force(w,v,999)-75)<1e-8)
            assert(math.abs(W.force(w,v,999)-75)<1e-8)
            W.clear(w);assert(W.force(w,v,20)==20)
        """)

    def test_detach_failure_and_owner_change_drop_old_load(self):
        self.l.execute("""
            W.add(w,{[v]=100},.1,1,true);W.add(w,{},.1,2,true);assert(W.force(w,v,0)==0)
            W.add(w,{[v]=100},.1,2,true);v.owner=2;assert(W.force(w,v,0)==0)
            W.add(w,{[v]=30},.1,2,true);assert(math.abs(W.force(w,v,0)-30)<1e-8)
            W.add(w,{},.1,2,false);assert(W.force(w,v,0)==0)
        """)

class MotionPipelineTests(unittest.TestCase):
    def test_snapshot_contains_committed_anchor_not_latest_vehicle_pose(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server;s.execute('root=link(C,A,rope)');n.publish()
        for _ in range(12):n.tick(.6)
        s.execute("""
            local r=R.simulation.records[root];local snapshot=CVPMPServer.capture()
            assert(math.abs(snapshot.bodies.A.source.x-r.ax)<1e-8)
            assert(math.abs(snapshot.bodies.A.source.x-H.sample(C).x)>.1)
            assert(snapshot.sampledAt==R.simulation.sampledAt)
        """)

    def test_body_recovery_request_does_not_consume_load_window(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server;s.execute('root=link(C,A,rope)');n.publish()
        s.execute("""
            local server=CVPMPServer;local W=require 'CVP_LinkWire'
            local window=require 'CVP_LoadWindow'
            window.add(server.loadWindow,{[car]=100},.1,S.graph.revision,true)
            local snapshot=server.capture();local row=snapshot.bodies.A
            beside(A);local peer=server.peers[player];peer.nextBody=0
            server.command(W.module,'body',player,{protocol=W.version,epoch=server.epoch,
                session=peer.session,key='A',token=row.token})
            assert(server.loadWindow.seconds==.1 and window.force(server.loadWindow,car,0)==100)
        """)

    def test_client_rejects_previous_owner_load_and_expires_without_new_snapshot(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server;c=n.clients['owner'];s.execute('root=link(C,A,rope)');n.publish()
        c.execute("""
            physicsOwner=true;car.getNetPlayerId=function() return 2 end
            local before=#impulses;now=now+50;CVPMPClient.tick();assert(#impulses==before)
        """)
        s.execute('car.getNetPlayerId=function() return 2 end')
        for _ in range(40): n.tick(.05)
        c.execute('assert(#impulses>0);local before=#impulses;now=now+1100;CVPMPClient.tick();assert(#impulses==before)')
