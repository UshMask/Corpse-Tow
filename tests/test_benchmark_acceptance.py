from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime


def fixture():
    lua=LuaRuntime()
    lua.execute("""
        handlers={}; local A={register=function(name,fn) handlers[name]=fn end}
        local data={}; local inventory={getItemWithID=function(_,id) return returned and {id=id} end}
        player={getModData=function() return data end,getInventory=function() return inventory end}
        getPlayer=function() return player end
        isClient=function() return false end;isServer=isClient
        getWorld=function() return {getWorld=function() return 'CVP_QuickTest' end,getMap=function() return 'test' end} end
        save=function() saved=true end
        MainScreen={instance={quitToDesktop=function() closed=true end}}
        local vehicle={x=0,setForceBrake=function() end,setPhysicsActive=function() end,getX=function(self) return self.x end,getY=function() return 0 end}
        graph={links={}};bodies={};items={}
        local host={discover=function() end,vehicleKey=function() return 'car' end,
            vehicle=function() return vehicle end,body=function(e) return bodies[e.key] end,
            sample=function(e) return e end}
        CVPRuntime={authority={host=host,service={graph=graph}}}
        local function copy(v) if type(v)~='table' then return v end;local out={};for k,x in pairs(v) do out[k]=copy(x) end;return out end
        CVPBenchmark={reset=function() end,beside=function() end}
        function CVPBenchmark.setup(n)
            local B=CVPBenchmark;B.bodies={};B.links={};B.gear={};B.origin={x=0,y=0,z=0};B.carOrigin={x=0,y=0};B.vehicle=vehicle
            for i=1,n do
                local key='body'..i;local id='link'..i;local gear=100+i
                local body={x=i,index=0,getX=function(self) return self.x end,getY=function() return 0 end,
                    isZombie=function() return i%2==1 end,isPlayer=function() return false end,
                    getStaticMovingObjectIndex=function(self) return self.index end,getModData=function() return {CVPBodyKey=key} end}
                bodies[key]=body;B.bodies[i]=body;B.links[i]=id;B.gear[i]=gear
                items[id]={getID=function() return gear end}
                graph.links[id]={id=id,a={kind=i==1 and 'vehicle' or 'body',key=i==1 and 'car' or 'body'..(i-1),point='hitch'},
                    b={kind='body',key=key,point='feet'},equipment=id,material='Base.Rope',length=2}
            end
        end
        require=function(name)
            if name=='PZT_Control' then return A end
            if name=='CVP_LinkGraph' then return {copy=copy,capacityFor=function() return 12 end} end
            if name=='CVP_Equipment' then return {get=function(id) return items[id] end} end
        end
    """)
    lua.execute(Path('tests/scenarios/corpse-tow/CVP_Acceptance.lua').read_text())
    return lua


class AcceptanceTests(unittest.TestCase):
    def test_rebind_may_retension_but_must_not_exceed_original_rope_capacity(self):
        for length, success in ((3, True), (13, False)):
            lua=fixture()
            lua.globals().reboundLength=length
            lua.execute('''
                handlers['scene.prepare']('1');handlers['scene.adopt']()
                CVPBenchmark.vehicle.x=3;bodies.body1.x=bodies.body1.x+2
                saved=false;closed=false
                CVPBenchmark.beside=function(p,point)
                    assert(point~=CVPBenchmark.origin,'start square unloaded after driving')
                end
                function CVPRuntime.authority.service:command(p,c)
                    local row=self.graph.links[c.id]
                    if c.op=='release' then row.a={kind='ground'}
                    elseif c.op=='bind' then row.a=c.target;row.length=reboundLength
                    elseif c.op=='remove' then self.graph.links[c.id]=nil;returned=true end
                    return true
                end
                CVPBenchmark.clear=function() for _,b in pairs(bodies) do b.index=-1 end end
                passed,result=pcall(handlers['scene.verify'])
            ''')
            self.assertEqual(lua.globals().passed, success)
            if success:
                self.assertEqual(lua.globals().result['stage'], 'passed')
                self.assertTrue(lua.globals().saved and lua.globals().closed)
            else:
                self.assertIn('exceeds capacity', lua.globals().result)

    def test_mixed_body_types_are_checked_after_reload(self):
        lua=fixture()
        lua.execute('''
            getWorld=function() return {getWorld=function() return 'PZT_VehicleLab' end,
                getMap=function() return 'PZT_ProvingGround' end} end
            handlers['scene.prepare']('4');handlers['scene.adopt']()
            bodies.body2.isZombie=function() return true end
            local ok,why=pcall(handlers['scene.adopt'])
            assert(not ok and why:find('saved body type changed'))
        ''')

    def test_adopts_saved_scene_without_recreating_bodies(self):
        lua=fixture()
        lua.execute("handlers['scene.prepare']('4');assert(saved and closed);local body=bodies.body1;CVPBenchmark.bodies={};local r=handlers['scene.adopt']();assert(r.count==4);assert(CVPBenchmark.bodies[1]==body)")

    def test_missing_link_wrong_rope_and_duplicate_are_rejected(self):
        for damage in ("graph.links.link1=nil", "items.link1={getID=function() return 999 end}", "returned=true"):
            lua=fixture();lua.execute("handlers['scene.prepare']('1')")
            lua.execute(damage)
            lua.execute("local ok=pcall(handlers['scene.adopt']);assert(not ok)")

    def test_stationary_bodies_cannot_pass_towing(self):
        lua=fixture();lua.execute("handlers['scene.prepare']('4');handlers['scene.adopt']();local ok,why=pcall(handlers['scene.verify']);assert(not ok and why:find('not all bodies moved'))")
