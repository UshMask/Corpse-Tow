"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class RopeMotionStabilityTests(unittest.TestCase):
    def test_moving_reference_frame_preserves_curve(self):
        """A moving reference frame must not inject energy into the cosmetic tether."""
        from pathlib import Path
        import sys
        from lupa.lua51 import LuaRuntime

        lua = LuaRuntime()
        lua.globals().Rope = lua.execute(Path('CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua').read_text())
        lua.execute('''
        for _,fps in ipairs({30,60,120}) do
            local r={x=2,y=0,z=0,angle=0,length=4,slot=1}
            for i=1,600 do Rope.shape(r,0,0,0,1/60) end
            local reference={}
            for i,p in ipairs(r.ropePoints) do reference[i]={x=p.x,y=p.y,z=p.z} end
            local maxDrift,maxLift=0,0
            for frame=1,fps*4 do
                local time=frame/fps
                -- Translation, braking and reverse; both attachments move together.
                local offset= time<2 and time*8 or 16-(time-2)*3
                r.x=2+offset;r.y=-offset*.5
                Rope.shape(r,offset,-offset*.5,0,1/fps)
                for i,p in ipairs(r.ropePoints) do
                    local q=reference[i]
                    maxDrift=math.max(maxDrift,math.sqrt((p.x-offset-q.x)^2+(p.y+offset*.5-q.y)^2+(p.z-q.z)^2))
                    maxLift=math.max(maxLift,p.z-q.z)
                end
            end
            print('translation fps/drift/lift',fps,maxDrift,maxLift)
            assert(maxDrift<0.08,'translation injected cosmetic rope motion')
            assert(maxLift<0.03,'grounded rope launched upwards')
        end
        ''')


if __name__ == '__main__':
    unittest.main()
