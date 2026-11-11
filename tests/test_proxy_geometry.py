"""Behavior checks run explicitly, never as an import side effect."""
import unittest


class ProxyGeometryTests(unittest.TestCase):
    def test_hitch_collision_and_attachment_geometry(self):
        """Geometry behaviour with native-style endpoints and discrete tile/wall fixtures."""
        from pathlib import Path
        import sys
        from lupa.lua51 import LuaRuntime
        L = LuaRuntime()
        root = Path('CorpseProxyLab/42/media/lua/shared')
        L.execute("package.path = ... .. '/?.lua;' .. package.path", root.as_posix())
        L.globals().Geometry = L.execute((root/'CVP_Geometry.lua').read_text())
        L.globals().Rope = L.execute((root/'CVP_Rope.lua').read_text())
        L.execute('''
        function vector() return {x=function(s) return s.xx end,y=function(s) return s.yy end} end
        Vector3f={new=vector};Vector2f={new=vector}
        local car={getZ=function() return 2 end,attachmentExist=function() return true end,
         getAttachmentWorldPos=function(_,name,p) assert(name=='trailer');p.xx=10;p.yy=20;return p end,
         getWorldPos=function(_,x,y,z,p) assert(z==-2);p.xx=11;p.yy=22 end,
         getScript=function() return {getExtents=function() return {z=function() return 4 end} end} end}
        local x,y,z=Geometry.anchor(car);assert(x==10 and y==20 and z==2,'prefer native hitch')
        car.attachmentExist=function() return false end
        x,y,z=Geometry.anchor(car);assert(x==11 and y==22 and z==2,'no hitch fallback')
        car.attachmentExist=function() error('unsupported mod vehicle') end
        x,y=Geometry.anchor(car);assert(x==11 and y==22,'optional hitch failure fallback')
        print('PASS native hitch, no-hitch and failed optional API fallbacks')

        function record(angle,front)
         local sign=front and -1 or 1
         local b={getX=function() return 10 end,getY=function() return 20 end,getAngle=function() return angle end}
         b.getGrabLegsPosition=function(_,p) p.xx=10+sign*0.9*math.cos(angle);p.yy=20+sign*0.9*math.sin(angle);return p end
         b.getGrabHeadPosition=function(_,p) p.xx=10-sign*0.9*math.cos(angle);p.yy=20-sign*0.9*math.sin(angle);return p end
         local r={body=b,x=10,y=20,z=0,angle=angle,vx=0,vy=0,ax=13,ay=20,length=4}
         Geometry.capture(r);return r
        end
        for _,front in ipairs({true,false}) do
         local r=record(1.2,front);local p=r.body:getGrabLegsPosition(vector())
         local fx,fy=Rope.feet(r);assert(math.abs(fx-p:x())<1e-6 and math.abs(fy-p:y())<1e-6,'native feet mismatch')
         for i=1,100 do r.x,r.y=Rope.step(r,r.x,r.y,13+i*0.1,20,0.05) end
         fx,fy=Rope.feet(r)
         assert(fx>r.x+0.89 and math.abs(fy-r.y)<0.05,'feet must face pull for either pose')
        end
        for _,front in ipairs({true,false}) do
         for _,angle in ipairs({0,1.2,math.pi,-2.5}) do
          local r=record(angle,front)
          for _,side in ipairs({-1,1}) do
           local car={getZ=function() return 0 end,attachmentExist=function() return true end,
            getAttachmentWorldPos=function(_,name,p)
             p.xx=10+side*3*math.cos(angle);p.yy=20+side*3*math.sin(angle);return p
            end}
           local expected=(side==(front and -1 or 1)) and 'feet' or 'neck'
           assert(Geometry.nearestPoint(r.body,car)==expected,'nearest native endpoint for rotated front/back pose')
          end
         end
        end
        print('PASS automatic nearest endpoint across rotated front/back poses')
        print('PASS face-up/down endpoints and feet-first orientation after a turn')
        for _,front in ipairs({true,false}) do
         local r=record(1.2,front);r.point='neck';Geometry.capture(r)
         local radius=r.footprintRadius
         for i=1,160 do r.x,r.y=Rope.step(r,r.x,r.y,13+i*0.1,20,0.05) end
         local x,y=Rope.feet(r)
         assert(x>r.x+0.7 and math.abs(y-r.y)<0.06,'neck endpoint must face the taut rope for both death poses')
         assert(r.footprintRadius==radius,'neck attachment must retain full-body collisions')
        end
        print('PASS face-up/down neck endpoints follow tension with unchanged full-body footprint')

        tiles={};mode='open';reads=0
        function getCell() return {getGridSquare=function(_,x,y,z)
         reads=reads+1
         if mode=='unloaded' and x>=3 then return nil end
         local key=x..':'..y
         if not tiles[key] then
          local q={x=x,y=y}
          q.isSolid=function() return mode=='solid' and x>=3 end
          q.isSolidTrans=function() return false end
          q.HasTree=function() return mode=='tree' and x>=3 end
          q.TreatAsSolidFloor=function() return not (mode=='floor' and x>=3) end
          q.isBlockedTo=function(_,b)
           if mode=='wall' then return (x<3)~=(b.x<3) end
           if mode=='corner' then return (x<3)~=(b.x<3) or (y<3)~=(b.y<3) end
           return false
          end
          tiles[key]=q
         end
         return tiles[key]
        end} end
        function testRecord(x,y,angle)
         local r=record(angle or 0,false);r.x=x;r.y=y;return r
        end
        for _,kind in ipairs({'solid','tree','wall','unloaded','floor'}) do
         mode=kind
         local r=testRecord(1.5,1.5)
         local x,y,a,blocked=Geometry.resolve(r,4.5,2.5,0,0)
         assert(blocked and x<2.11 and y>2.49,'footprint should stop before edge, slide along it: '..kind..' '..x..','..y)
         assert(x>=r.x,'no recovery teleport')
        end
        mode='wall';local r=testRecord(1.5,1.5)
        local x,y,a,blocked=Geometry.resolve(r,2.5,1.5,0,0)
        assert(blocked and x<2.11,'head crosses wall before center')
        r=testRecord(2.5,1.5,math.pi/2)
        x,y,a,blocked=Geometry.resolve(r,2.5,1.5,0,math.pi/2)
        assert(blocked and a>0.8,'rotation alone must not sweep head through wall')
        mode='corner';r=testRecord(1.5,1.5)
        x,y,a,blocked=Geometry.resolve(r,4.5,4.5,0,0)
        assert(blocked and x<2.11 and y<2.79,'no diagonal corner tunnelling')
        mode='open';r=testRecord(1.5,1.5)
        x,y,a,blocked=Geometry.resolve(r,4.5,2.5,0.3,0)
        assert(not blocked and x==4.5 and y==2.5 and math.abs(a-0.3)<1e-6,'free movement unchanged')
        reads=0;Geometry.resolve(r,r.x,r.y,r.angle,r.angle);assert(reads==0,'stationary body must not scan footprint')
        print('PASS swept length/width, rotation, solid/tree/wall/floor/unloaded limits, sliding, corners, stationary fast path')
        local O=require 'CVP_LinkObstacles'
        mode='open';local cache=O.new();r=testRecord(1.5,1.5)
        Geometry.resolve(r,2,1.6,.4,0,cache);local count=reads
        for i=1,32 do Geometry.resolve(r,2,1.6,.4,0,cache) end
        assert(reads==count,'shared bodies must reuse native tile reads')
        mode='wall';cache=O.new();r=testRecord(1.1,1.5)
        Geometry.resolve(r,1.2,1.6,.4,0,cache)
        local x,y,a,blocked=Geometry.resolve(r,4.5,1.6,.4,0,cache)
        assert(blocked,'expanded bounds must not reuse a smaller clear proof')
        mode='open';cache=O.new();r=testRecord(1.5,1.5)
        Geometry.resolve(r,2.5,1.6,.4,0,cache)
        mode='wall'
        x,y,a,blocked=Geometry.resolve(r,2.5,1.6,.4,0,O.new())
        assert(blocked,'same bounds in a new tick must observe a newly closed wall')
        for _,kind in ipairs({'tree','wall','unloaded','floor','solid','corner'}) do
         mode=kind
         local x,y,a,blocked=Geometry.resolve(r,4.5,4.5,.4,0,O.new())
         assert(blocked,'next tick must observe changed environment: '..kind)
        end
        mode='open'
        local x,y,a,blocked=Geometry.resolve(r,4.5,4.5,.4,0,O.new())
        assert(not blocked and x==4.5 and y==4.5,'opened environment resumes next tick')
        ''')


if __name__ == '__main__':
    unittest.main()
