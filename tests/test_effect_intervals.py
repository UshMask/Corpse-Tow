import unittest
from test_link_runtime import environment
from test_link_multiplayer import Network, take
from test_cosmetic_wear import visuals


class EffectIntervalTests(unittest.TestCase):
    def test_disabled_effects_skip_pose_reads_and_do_not_charge_old_travel(self):
        for server in (False, True):
            l=environment();l.globals().serverMode=server
            l.execute('''
                function isServer() return serverMode end
                local E=require 'CVP_Effects';local rules=SandboxVars.CorpseProxyLab
                local calls=0;local total=0
                require('CVP_Blood').committed=function(g)
                    calls=calls+1;total=total+g.records[1].effectDistance
                end
                for _,name in ipairs({'CVP_Abrasion','CVP_ClothingWear','CVP_CarcassWear','CVP_BodyWear'}) do
                    require(name).committed=function() error('disabled effect invoked') end
                end
                rules.CosmeticWear=false;rules.ClothingWear=false;rules.CarcassWear=false;rules.BodyWear=false
                local r={body=body,before={x=body:getX()-.25,y=body:getY(),z=body:getZ()}}
                local group={records={r}};E.committed(group,{},0)
                assert(r.effectTravel==.25)
                rules.BloodTrails=false;r.bloodDistance=.4;r.wearDistance=.2
                local x=body.getX;body.getX=function() error('disabled distance read') end
                E.committed(group,{},100);E.committed(group,{},1000)
                assert(r.effectTravel==0 and r.bloodDistance==0 and r.wearDistance==0 and calls==0)
                body.getX=x;rules.BloodTrails=true
                E.committed(group,{},2000)
                assert(calls==1 and total==.25,'disabled or pending distance leaked into enabled effect')
                -- Another consumer stays enabled while clothing is switched on.
                E.committed(group,{},2001);local clothing=0
                require('CVP_ClothingWear').committed=function(g) clothing=clothing+g.records[1].effectDistance end
                rules.ClothingWear=true;E.committed(group,{},3000)
                assert(clothing==.25,'new consumer charged shared travel from before enabling')
                intact(body)
            ''')

    def test_mass_refresh_is_immediate_staggered_and_never_over_one_second_late(self):
        l=environment();l.execute('''
            local L=require 'CVP_Load';local records={};local deadlines={};local calls=0
            local mass=L.mass;L.mass=function(...) calls=calls+1;return mass(...) end
            for i=1,32 do
                local r={body=body};records[i]=r;L.refresh(r,0)
                assert(r.mass>0 and r.nextMassRefresh>0 and r.nextMassRefresh<=1000)
                assert(not deadlines[r.nextMassRefresh]);deadlines[r.nextMassRefresh]=true
            end
            assert(calls==32)
            local old=records[1].mass;local weight=body.inv:getItems():get(0).getActualWeight
            body.inv:getItems():get(0).getActualWeight=function(s) return weight(s)+10 end
            for _,r in ipairs(records) do
                local before=calls;L.refresh(r,r.nextMassRefresh-1);assert(calls==before)
                local due=r.nextMassRefresh;L.refresh(r,due)
                assert(r.mass==old+10 and r.nextMassRefresh==due+1000)
                L.refresh(r,10000);assert(r.nextMassRefresh>10000 and r.nextMassRefresh<=11000)
            end
            intact(body)
        ''')

    def test_long_pause_preserves_stagger_without_catchup_burst(self):
        l=environment();l.execute('''
            local E=require 'CVP_Effects';local A=require 'CVP_Appearance'
            local calls={};local samples={}
            require('CVP_Blood').committed=function(g)
                for _,r in ipairs(g.records) do local b=r.body;calls[b]=(calls[b] or 0)+1 end
            end
            for _,name in ipairs({'CVP_Abrasion','CVP_ClothingWear','CVP_BodyWear'}) do
                require(name).committed=function() end
            end
            for _,b in ipairs({body,body2}) do
                samples[#samples+1]={body=b,before={x=b:getX(),y=b:getY(),z=b:getZ()}}
                A.capture(b,0)
            end
            local group={records=samples};E.committed(group,{},0)
            E.committed(group,{},10000)
            for _,b in ipairs({body,body2}) do A.capture(b,10000);assert(calls[b]==1) end
            -- Resume normal ticks after the stall: bodies separate again.
            E.committed(group,{},10150)
            assert(calls[body]==2 and calls[body2]==1)
            local first=A.capture(body,10150);local second=A.capture(body2,10150)
            assert(first.due>10600 and second.due<10500)
            intact(body);intact(body2)
        ''')

    def test_mp_lost_ack_repeats_data_and_failed_apply_retries(self):
        n=Network();s=n.server
        for l in [s,*n.clients.values()]: visuals(l)
        c=n.clients['friend']
        c.execute('body.getHumanVisual=function() return nil end')
        s.execute('root=link(C,A,rope);skin.blood=.8;publish()')
        for p in take(s,'packets'): n.receive(p)
        for client in n.clients.values(): take(client,'clientPackets') # Lost acknowledgements.
        s.execute('publish()');packets=take(s,'packets')
        rows=[r for p in packets if p['name']=='state' for r in p['args']['bodies'].values() if r['key']=='A']
        self.assertTrue(rows and all('cosmetic' in r and not r.get('appearanceOmitted') for r in rows))
        for p in packets: n.receive(p)
        n.pump()
        c.execute('''
            body.getHumanVisual=function() return skin end
            now=now+600;CVPMPClient.tick();assert(skin.blood>.79)
        ''')

    def test_staggered_effects_keep_committed_distance_and_ignore_teleport(self):
        l=environment()
        l.execute('''
            local Effects=require 'CVP_Effects'
            local samples={};local total={};local times={}
            require('CVP_Blood').committed=function(group)
                local r=group.records[1];local b=r.body
                total[b]=(total[b] or 0)+r.effectDistance
                times[b]=times[b] or {};table.insert(times[b],now)
            end
            for _,name in ipairs({'CVP_Abrasion','CVP_ClothingWear','CVP_BodyWear'}) do
                require(name).committed=function() end
            end
            for _,b in ipairs({body,body2}) do samples[#samples+1]={body=b} end
            for tick=0,40 do
                now=tick*50
                for _,r in ipairs(samples) do
                    r.before={x=r.body:getX()-(tick<20 and .1 or 0),y=r.body:getY(),z=r.body:getZ()}
                end
                Effects.committed({records=samples},{},now)
            end
            for _,b in ipairs({body,body2}) do
                assert(math.abs(total[b]-2)<1e-6)
                assert(#times[b]<=5)
                for i=2,#times[b] do assert(times[b][i]-times[b][i-1]>=500) end
            end
            assert(times[body][1]~=times[body2][1])
            local r=samples[1];r.before={x=body:getX()-20,y=body:getY(),z=body:getZ()}
            now=3000;Effects.committed({records={r}},{},now)
            assert(math.abs(total[body]-2)<1e-6);intact(body);intact(body2)
        ''')

    def test_mp_ack_omits_unchanged_appearance_and_recovers_missing_cache(self):
        n=Network();s=n.server
        for l in [s,*n.clients.values()]: visuals(l)
        s.execute('root=link(C,A,rope);for i=1,10 do wearStep(.5) end')
        n.publish() # Pumps the explicit client acknowledgement.
        s.execute('publish()');packets=take(s,'packets')
        rows=[r for p in packets if p['name']=='state' for r in p['args']['bodies'].values() if r['key']=='A']
        self.assertTrue(rows)
        self.assertTrue(all(r.get('appearanceOmitted') and 'cosmetic' not in r for r in rows))
        c=n.clients['friend'];c.execute('CVPMPClient.appearances={};skin.blood=0')
        for p in packets: n.receive(p)
        n.pump();n.publish()
        self.assertEqual(c.globals().skin.blood,s.globals().skin.blood)
        c.execute('''
            local wear=require 'CVP_Abrasion';local native=wear.apply;local calls=0
            wear.apply=function(...) calls=calls+1;return native(...) end
            for i=1,10 do now=now+16;CVPMPClient.tick() end
            assert(calls==0,'unchanged appearance reapplied on movement ticks')
        ''')
        s.execute('skin.blood=.8;now=now+1000')
        n.publish()
        self.assertGreater(c.globals().skin.blood,.79)


if __name__=='__main__': unittest.main()

