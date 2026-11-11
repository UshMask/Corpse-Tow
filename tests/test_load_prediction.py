"""Authoritative resistance replaces geometric client load prediction."""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path('CorpseProxyLab/42/media/lua/shared')

class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.l = LuaRuntime()
        self.l.execute("package.path='"+ROOT.as_posix()+"/?.lua;'..package.path")
        self.l.execute("P=require 'CVP_LoadPrediction';L=require 'CVP_Load'")

    def test_zero_load_or_time_does_not_read_vehicle_physics(self):
        self.l.execute('L.apply(nil,0,.05);L.apply(nil,75,0)')

    def test_server_force_wins_over_legacy_estimates_and_history(self):
        self.l.execute('''
            local old={owner=1,time=100,mass=2400,points={hitch={loadMass=2400}}}
            for _,mass in ipairs({0,75,2400,20,0}) do
                local row={owner=2,resistanceForceN=mass,loadEstimate={hitch={mass=9999,slack=0}}}
                for _,time in ipairs({0,50,1000,10}) do
                    local value,state=P.force(old,row,time,{hitch={x=1000,y=0,z=1}})
                    assert(value==mass and state==nil)
                    assert(row.resistanceForceN==mass and row.loadEstimate.hitch.mass==9999)
                    assert(old.mass==2400 and old.time==100)
                end
            end
        ''')

    def test_capture_removes_estimates_without_traversing_bodies(self):
        self.l.execute('''
            local forbidden=setmetatable({},{__index=function() error('body traversal') end})
            local estimate={hitch={mass=2400}}
            local loads={car={mass=75,loadEstimate=estimate},other={mass=0}}
            P.capture(forbidden,forbidden,loads)
            assert(loads.car.mass==75 and loads.other.mass==0)
            assert(not loads.car.loadEstimate and not loads.other.loadEstimate)
            assert(estimate.hitch.mass==2400,'previous snapshot was mutated')
        ''')

if __name__=='__main__':unittest.main()
