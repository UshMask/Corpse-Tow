import unittest
from pathlib import Path
from test_link_simulation import environment
from test_animal_towing import ANIMAL
from lua_fixture import copy_packet

class CarcassWearTests(unittest.TestCase):
    def env(self):
        l=environment();l.execute(ANIMAL+'''
            W=require 'CVP_CarcassWear';r={body=body,effectDistance=0};g={records={r}}
            body.md.parts=true;body.md.meatRatio=1.2;body.md.deathAge=17;body.md.animalRotStage=1
            sent=0;body.transmitModData=function() sent=sent+1 end
            function travel(n) r.effectDistance=n;W.committed(g) end
        ''');return l

    def test_grace_cap_inventory_age_and_disabled(self):
        l=self.env();l.execute('''
            travel(100);assert(body.md.meatRatio==1.2 and sent==0)
            travel(100);assert(math.abs(body.md.meatRatio-1.188)<1e-9 and sent==1)
            travel(100000);assert(math.abs(body.md.meatRatio-1.08)<1e-9 and sent==2)
            travel(100000);assert(sent==2)
            assert(body.md.deathAge==17 and body.md.animalRotStage==1);intact(body)
            SandboxVars.CorpseProxyLab.CarcassWear=false;travel(1000);assert(sent==2)
        ''')

    def test_saved_progress_client_guard_and_rates(self):
        l=self.env();l.execute('travel(150)');saved=copy_packet(l.globals().body.md)
        restored=self.env();restored.globals().saved=restored.table_from(saved,recursive=True)
        restored.execute('''
            body.md=saved;travel(50);assert(math.abs(body.md.meatRatio-1.188)<1e-9)
            isClient=function() return true end;travel(1000);assert(sent==1)
            isClient=function() return false end
            SandboxVars.CorpseProxyLab.CarcassWearRate=3;travel(50);assert(body.md.CVPCarcassWear.steps==2)
            body.md.meatRatio=.6;travel(50);assert(body.md.meatRatio<.6)
            body.md.parts=nil;local ratio=body.md.meatRatio;travel(500);assert(body.md.meatRatio==ratio)
        ''')

    def test_vanilla_butchering_reads_reduced_ratio(self):
        path=Path('E:/SteamLibrary/steamapps/common/ProjectZomboid/media/lua/shared/Definitions/animal/ButcheringUtil.lua')
        if not path.exists(): self.skipTest('installed vanilla Lua unavailable')
        l=self.env();l.execute(path.read_text(encoding='utf-8-sig'))
        l.execute('''
            Perks={Butchering=1};player.getPerkLevel=function() return 0 end
            body.getAnimalSize=function() return 1 end
            AnimalAvatarDefinition={};AnimalPartsDefinitions={meat={Meat=true}}
            instanceItem=function() return {class='Food'} end
            local oldInstance=instanceof;instanceof=function(o,c) return c=='Food' or oldInstance(o,c) end
            ZombRand=function(a,b) capturedMin=a;capturedMax=b;return math.floor(a) end
            ButcheringUtil.giveMeatModified=function(_,n,_,ratio) outputRatio=ratio;return '' end
            body.md.deathAge=0;body.md.animalRotStage=0
            ButcheringUtil.addAnimalPart({item='Meat',minNb=20,maxNb=30},player,body,false)
            local baseline=capturedMin
            travel(1100)
            ButcheringUtil.addAnimalPart({item='Meat',minNb=20,maxNb=30},player,body,false)
            assert(math.abs(capturedMin/baseline-.9)<1e-9 and math.abs(outputRatio-1.08)<1e-9)
        ''')

    def test_settings_sp_only(self):
        from test_live_settings import settings
        l=self.env();l.globals().settingsMenuSource=Path('CorpseProxyLab/42/media/lua/client/CVP_SettingsMenu.lua').read_text(encoding='utf-8-sig');settings(l);l.execute('''
            nativeRules.CarcassWear=true;nativeRules.CarcassWearRate=2
            assert(Settings.set('CarcassWear',false));assert(Settings.set('CarcassWearRate',1))
            assert(not Settings.set('CarcassWearRate',4))
            isClient=function() return true end
            assert(not Settings.set('CarcassWear',true))
        ''')

    def test_mp_effects_only_authority_writes_and_transmits(self):
        from test_link_multiplayer import Network
        n=Network();s=n.server
        for l in (s,*n.clients.values()):
            l.execute(ANIMAL+'''
                body.md.parts=true;body.md.meatRatio=1
                sent=0;body.transmitModData=function() sent=sent+1 end
                local W=require 'CVP_CarcassWear'
                W.committed({records={{body=body,effectDistance=200}}})
            ''')
        s.execute('assert(sent==1 and body.md.meatRatio==.99)')
        for c in n.clients.values():
            c.execute('assert(sent==0 and body.md.meatRatio==1 and not body.md.CVPCarcassWear)')
            c.globals().nativeData=c.table_from(copy_packet(s.globals().body.md),recursive=True)
            c.execute('body.md=nativeData;assert(body.md.meatRatio==.99)')
