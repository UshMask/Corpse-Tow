package cvpworld;

import java.nio.file.*;
import java.util.*;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.vm.*;

/** Run the unchanged Lua visual solver in PZ's real VM, then compare every point/velocity. */
public class ValidateRopeShape {
    static KahluaThread thread;static KahluaTable env;static long comparisons;static double maxError;
    static Object eval(String code) throws Exception {
        Object[] result=thread.pcall(LuaCompiler.loadstring(code,"rope-shape-parity",env),new Object[0]);
        if(!Boolean.TRUE.equals(result[0]))throw new AssertionError(Arrays.toString(result));
        return result.length>1?result[1]:null;
    }
    static void near(double a,double b,String label) {
        comparisons++;double error=Math.abs(a-b);maxError=Math.max(maxError,error);
        if(!(error<1e-8))throw new AssertionError(label+": "+a+" != "+b+" error="+error);
    }
    static double number(KahluaTable t,String key){return ((Number)t.rawget(key)).doubleValue();}
    static void compare(KahluaTable lua,RopeShape.State java,String context) {
        KahluaTable points=(KahluaTable)lua.rawget("ropePoints");
        if(points.len()!=java.points.length)throw new AssertionError("quality mismatch");
        for(int i=0;i<java.points.length;i++) {
            KahluaTable p=(KahluaTable)points.rawget(i+1);RopeShape.Point q=java.points[i];
            double[] actual={q.x,q.y,q.z,q.vx,q.vy,q.vz};String[] names={"x","y","z","vx","vy","vz"};
            for(int k=0;k<names.length;k++)near(number(p,names[k]),actual[k],context+" point="+i+" "+names[k]);
        }
        if(Boolean.TRUE.equals(lua.rawget("ropeSleeping"))!=java.sleeping)throw new AssertionError(context+" sleep changed");
        near(number(lua,"ropeQuiet"),java.quiet,"quiet");near(number(lua,"ropeStill"),java.still,"still");
        near(number(lua,"ropeShapeLength"),java.shapeLength,"length");
    }
    static void run(boolean chain,int segments,double dt,int scenario) throws Exception {
        eval("r={x=0,y=0,z=0,angle=0,slot=1,length=4,attachLocalX=0,attachLocalY=0,anchorHeight=0,endHeight=.04,ropeSegments="+segments+
            ",ropePasses="+(segments==8?4:8)+",gear={getFullType=function() return 'Base."+(chain?"Chain":"Rope")+"' end}};native={}");
        KahluaTable r=(KahluaTable)env.rawget("r"),nativeRecord=(KahluaTable)env.rawget("native");
        // Separate Lua and Java state; copy only scalar inputs, never solver output.
        for(int frame=0;frame<900;frame++) {
            double time=frame*dt,ax=0,ay=0,az=.3,bx=2,by=0,z=0,length=4,step=dt;
            if(scenario==1){ax=time*2;ay=Math.sin(time)*.7;bx=ax+2+Math.sin(time*2)*2.5;by=ay+Math.cos(time)*.2;}
            if(scenario==2){ax=6200+time*.5;ay=5200;bx=ax+2;by=ay;z=2;az=2.6+Math.sin(time)*.3;}
            if(scenario==3){
                ax=-20;ay=-15;bx=ax+2;by=ay;
                if(frame>=200&&frame<400)length=12;
                if(frame>=400&&frame<500)length=2;
                if(frame>=500){bx=ax+2+Math.sin(time);by=ay+Math.cos(time);}
                if(frame==200||frame==400||frame==600){segments=segments==8?16:8;r.rawset("ropeSegments",(double)segments);r.rawset("ropePasses",segments==8?4.0:8.0);}
                if(frame==300||frame==700){chain=!chain;eval("r.gear.getFullType=function() return 'Base."+(chain?"Chain":"Rope")+"' end");}
                if(frame%113==0)step=0;else if(frame%127==0)step=.8;else if(frame%131==0)step=-.01;
            }
            if(scenario==4){
                // Coincident endpoints, alternating seed side, nonzero foot offset/angle, then wake.
                r.rawset("slot",2.0);r.rawset("angle",.7);r.rawset("attachLocalX",-.65);r.rawset("attachLocalY",.12);
                bx=.65*Math.cos(.7)+.12*Math.sin(.7);by=.65*Math.sin(.7)-.12*Math.cos(.7);az=.04;
                if(frame>600){ax=(frame-600)*.005;az=.3;}
            }
            r.rawset("x",bx);r.rawset("y",by);r.rawset("z",z);r.rawset("length",length);
            for(String key:new String[]{"x","y","z","angle","slot","length","attachLocalX","attachLocalY","anchorHeight","endHeight","ropeSegments","ropePasses"})nativeRecord.rawset(key,r.rawget(key));
            env.rawset("ax",ax);env.rawset("ay",ay);env.rawset("az",az);env.rawset("dt",step);
            eval("Rope.shape(r,ax,ay,az,dt)");
            FreeRopeScene.shape("parity",nativeRecord,ax,ay,az,step,chain);
            RopeShape.State state=(RopeShape.State)nativeRecord.rawget("nativeShape");
            compare(r,state,"scenario="+scenario+" frame="+frame+" dt="+dt);
            var snapshot=FreeRopeScene.snapshots().getFirst();double[] saved=snapshot.points().clone();
            for(int i=0;i<state.points.length;i++) {
                near(saved[i*3],state.points[i].x,"published x");
                near(saved[i*3+1],state.points[i].y,"published y");
                near(saved[i*3+2],state.points[i].z,"published z");
            }
            // Queued render geometry must never alias the evolving solver.
            double originalX=state.points[0].x;state.points[0].x+=1;
            if(!Arrays.equals(saved,snapshot.points()))throw new AssertionError("mutable render snapshot");
            state.points[0].x=originalX;
            if(frame==850){FreeRopeScene.remove("parity");}
        }
        FreeRopeScene.clear();
    }
    public static void main(String[] args) throws Exception {
        var platform=J2SEPlatform.getInstance();env=platform.newTable();
        se.krka.kahlua.stdlib.BaseLib.register(env);se.krka.kahlua.stdlib.TableLib.register(platform,env);
        se.krka.kahlua.j2se.MathLib.register(platform,env);se.krka.kahlua.stdlib.StringLib.register(platform,env);
        thread=new KahluaThread(platform,env);thread.debugOwnerThread=Thread.currentThread();
        zombie.Lua.LuaManager.env=env;zombie.Lua.LuaManager.thread=thread;zombie.Lua.LuaManager.debugthread=thread;
        eval("ipairs=table.ipairs;pairs=table.pairs");
        eval("function math.max(v,...) for i=1,select('#',...) do local n=select(i,...);if n>v then v=n end end return v end;function math.min(v,...) for i=1,select('#',...) do local n=select(i,...);if n<v then v=n end end return v end");
        env.rawset("Rope",eval(Files.readString(Path.of("CorpseProxyLab/42/media/lua/shared/CVP_Rope.lua"))));
        for(boolean chain:new boolean[]{false,true})for(int segments:new int[]{8,16})
            for(double dt:new double[]{1.0/30,1.0/60,1.0/144,1.0/300})for(int scenario=0;scenario<5;scenario++)run(chain,segments,dt,scenario);
        System.out.println("PASS visual rope parity: comparisons="+comparisons+" maxError="+maxError+" (positions, velocities, sleep, length, quality, material, frame ownership)");
    }
}
