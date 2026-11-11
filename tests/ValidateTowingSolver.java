package cvpworld;

import java.nio.file.*;
import java.util.*;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.vm.*;

/** Differential tests against shipped Lua, running in the actual game VM. */
public class ValidateTowingSolver {
    static KahluaThread thread;static KahluaTable env;static double maxError;static long comparisons;
    static Object eval(String code) throws Exception {
        Object[] r=thread.pcall(LuaCompiler.loadstring(code,"solver-parity",env),new Object[0]);
        if(!Boolean.TRUE.equals(r[0]))throw new AssertionError(Arrays.toString(r));return r.length>1?r[1]:null;
    }
    static void compare(KahluaTable a,KahluaTable b,String field) {
        Object x=a.rawget(field),y=b.rawget(field);comparisons++;
        if(x instanceof Number&&y instanceof Number) {
            double error=Math.abs(((Number)x).doubleValue()-((Number)y).doubleValue());maxError=Math.max(maxError,error);
            if(!(error<1e-13))throw new AssertionError(field+": "+x+" != "+y+" error="+error);
        } else if(!Objects.equals(x,y)&&!(x==null&&Boolean.FALSE.equals(y))&&!(y==null&&Boolean.FALSE.equals(x)))
            throw new AssertionError(field+": "+x+" != "+y);
    }
    static void persistentHistory(Platform platform) throws Exception {
        var records=(KahluaTable)eval("return fixture(1,false,true)");
        var reference=(KahluaTable)eval("return fixture(1,false,true)");
        var state=TowingSolver.prepare(records);var legacy=TowingSolver.prepare(reference);
        var group=platform.newTable();var expected=platform.newTable();
        SolverEnvironment.World empty=new SolverEnvironment.World(){
            public int flags(int x,int y,int z){return 0;}
            public boolean blocked(int x,int y,int z,int bx,int by){return false;}
        };
        var row=(KahluaTable)records.rawget(1);var ref=(KahluaTable)reference.rawget(1);
        for(int tick=0;tick<30;tick++) {
            if(tick==12) {
                row.rawset("nativeResetMotion",true);row.rawset("nativeResetConstraint",true);
                ref.rawset("vx",0.);ref.rawset("vy",0.);ref.rawset("angularVelocity",0.);
                ref.rawset("ropeConstraintReady",null);
            }
            double rx=1+tick*.02,ry=.5;
            double sx=TowingSolver.n(ref,"ax",rx),sy=TowingSolver.n(ref,"ay",ry);
            for(var r:new KahluaTable[]{row,ref}) {
                var source=TowingSolver.table(r,"sourceSample");source.rawset("x",rx);source.rawset("y",ry);
            }
            double wanted=TowingSolver.solve(legacy,new SolverEnvironment(empty),expected,2,1./120,sx,sy,rx,ry);
            // Run a real Lua timestep between persistent Java timesteps.
            double actual;
            if(tick==10) {
                TowingSolver.release(state);env.rawset("records",records);
                var result=(KahluaTable)eval("return luaSolve(records,2,"+(1./120)+","+sx+","+sy+","+rx+","+ry+")");
                actual=TowingSolver.n(result,"total",0);
            } else actual=TowingSolver.solvePersistent(state,new SolverEnvironment(empty),group,2,1./120,sx,sy,rx,ry);
            if(Math.abs(wanted-actual)>1e-13)throw new AssertionError("persistent load mismatch");
            for(String field:new String[]{"x","y","angle","ax","ay","taut","blocked","loadMass","loadConnected"})
                compare(ref,row,field);
            var b=state.bodies[0];
            if(tick!=10 && (Math.abs(b.vx-TowingSolver.n(ref,"vx",0))>1e-13
                || Math.abs(b.vy-TowingSolver.n(ref,"vy",0))>1e-13
                || Math.abs(b.angularVelocity-TowingSolver.n(ref,"angularVelocity",0))>1e-13))
                throw new AssertionError("persistent history mismatch");
            if(row.rawget("nativeResetMotion")!=null || row.rawget("nativeResetConstraint")!=null)
                throw new AssertionError("reset was not consumed");
        }
        var b=state.bodies[0];double vx=b.vx,vy=b.vy,av=b.angularVelocity,takeup=b.takeup;boolean constraint=b.constraint;
        var injected=new IllegalStateException("injected solver world read failure");
        SolverEnvironment.World failing=new SolverEnvironment.World(){
            public int flags(int x,int y,int z){throw injected;}
            public boolean blocked(int x,int y,int z,int bx,int by){throw injected;}
        };
        try {
            TowingSolver.solvePersistent(state,new SolverEnvironment(failing),group,1,1./120,b.ax,b.ay,b.ax+.01,b.ay);
            throw new AssertionError("solver failure was not reached");
        } catch(IllegalStateException failure) {if(failure!=injected)throw failure;}
        if(state.persistent || b.initialized || b.vx!=vx || b.vy!=vy || b.angularVelocity!=av
            || Double.compare(b.takeup,takeup)!=0 || b.constraint!=constraint)
            throw new AssertionError("failed solve did not restore and release history");
        for(String field:new String[]{"vx","vy","angularVelocity","takeup","ropeConstraintReady"})compare(ref,row,field);
        TowingSolver.release(state); // Releasing an already released state is harmless.
    }
    public static void main(String[] args) throws Exception {
        var platform=J2SEPlatform.getInstance();env=platform.newTable();
        se.krka.kahlua.stdlib.BaseLib.register(env);se.krka.kahlua.stdlib.TableLib.register(platform,env);
        se.krka.kahlua.j2se.MathLib.register(platform,env);se.krka.kahlua.stdlib.StringLib.register(platform,env);
        thread=new KahluaThread(platform,env);thread.debugOwnerThread=Thread.currentThread();
        zombie.Lua.LuaManager.env=env;zombie.Lua.LuaManager.thread=thread;zombie.Lua.LuaManager.debugthread=thread;
        eval("ipairs=table.ipairs;pairs=table.pairs;function assert(v,msg) if not v then error(msg or 'assert') end return v end;modules={};function require(n) return modules[n] or {} end");
        eval("function math.max(v,...) for i=1,select('#',...) do local n=select(i,...);if n>v then v=n end end return v end;function math.min(v,...) for i=1,select('#',...) do local n=select(i,...);if n<v then v=n end end return v end");
        var modules=(KahluaTable)env.rawget("modules");
        for(String name:new String[]{"CVP_Rope","CVP_LinkObstacles","CVP_Geometry","CVP_Load","CVP_Core","CVP_GroupConstraints"})
            modules.rawset(name,eval(Files.readString(Path.of("CorpseProxyLab/42/media/lua/shared/"+name+".lua"))));
        eval("Rope=require 'CVP_Rope';O=require 'CVP_LinkObstacles';Geometry=require 'CVP_Geometry';Load=require 'CVP_Load';Core=require 'CVP_Core';Group=require 'CVP_GroupConstraints'");
        env.rawset("Motion",eval(Files.readString(Path.of("CorpseProxyLab/42/media/lua/client/CVP_Motion.lua"))));
        eval("""
            local r={}
            Motion.push(r,{x=0,y=0,z=0,angle=math.pi-.1,vehicle=7},0)
            Motion.push(r,{x=1,y=0,z=0,angle=-math.pi+.1,vehicle=7},100)
            assert(math.abs(Motion.pose(r,Motion.delay+50).angle-math.pi)<1e-8,
                'snapshot interpolation takes a full revolution')
            """);
        eval("""
            wall=false;tree=false;missing=false;solid=false
            function getCell() return {getGridSquare=function(_,x,y,z)
                if missing and x==3 then return nil end
                return {x=x,y=y,isSolid=function() return solid and x==3 end,isSolidTrans=function() return false end,
                    TreatAsSolidFloor=function() return true end,HasTree=function() return tree and x==3 and y==0 end,
                    isBlockedTo=function(a,b) return wall and ((a.x<3)~=(b.x<3)) end}
            end} end
            function fixture(count,chain,elastic)
                local records={}
                for i=1,count do
                    local r={x=0.3-(chain and (i-1)*.8 or 0),y=.5+(chain and 0 or (i-1)*.03),z=0,angle=0,
                        vx=0,vy=0,angularVelocity=0,length=1.4,anchorHeight=0,footLocalX=-.65,footLocalY=0,headLocalX=.65,headLocalY=0,
                        attachLocalX=-.65,attachLocalY=0,mass=75+i,loadMass=0,maxGapSquared=10000,nativeElastic=elastic,
                        gear={getFullType=function() return elastic and 'Base.Rope' or 'Base.Chain' end},
                        sourceSample={x=1,y=.5,z=0},body={}}
                    r.connection={b={object=r.body}};Geometry.footprint(r,1.3,0,1.3)
                    if chain and i>1 then r.parent=records[i-1];r.sourcePose={attachLocalX=-.65,attachLocalY=0} end
                    records[i]=r
                end
                return records
            end
            function luaSolve(records,steps,h,startX,startY,rx,ry)
                local c=O.new();local contacts={};local total=0;local obstruction=nil;local gap=0
                for _,r in ipairs(records) do r.blocked=false;r.taut=false;r.ropeBlocked=nil end
                for step=1,steps do
                    Rope.separate(records,contacts)
                    local recovery=false;local fallbackStep=false;local takeupStep=false
                    if #records>1 then
                        local result={};Group.step(records,c,startX+(rx-startX)*step/steps,startY+(ry-startY)*step/steps,h,result)
                        gap=result.nativeGap;obstruction=result.nativeObstruction;recovery=result.recoveryStep
                        fallbackStep=result.fallbackStep;takeupStep=result.takeupStep
                    else
                    for i,r in ipairs(records) do
                        local vx,vy=r.vx+(r.pushX or 0)*h,r.vy+(r.pushY or 0)*h
                        local speed=math.sqrt(vx*vx+vy*vy)
                        local slide=speed>0 and math.max(0,1-9.81*.65*h/speed) or 0
                        r.physicalVX=vx*slide;r.physicalVY=vy*slide
                        r.physicalW=math.max(-3,math.min(3,(r.angularVelocity or 0)*math.exp(-4*h)))
                        r.correctionStep=false
                        local sx,sy,sz=r.sourceSample.x,r.sourceSample.y,r.sourceSample.z
                        if r.parent then local p=r.sourcePose;local b=r.parent;p.x=b.x;p.y=b.y;p.z=b.z;p.angle=b.angle;sx,sy,sz=Rope.feet(p) end
                        if i==1 then sx=startX+(rx-startX)*step/steps;sy=startY+(ry-startY)*step/steps end
                        if math.floor(sz)~=math.floor(r.z) or (sx-r.x)^2+(sy-r.y)^2>r.maxGapSquared then gap=i;break end
                        r.ax=r.ax or sx;r.ay=r.ay or sy;Core.advance(r,sx,sy,sz,h,c,true)
                        if r.ropeBlocked then obstruction=r.ropeBlocked;break end
                        if r.blocked and r.taut then obstruction=O.blocked;break end
                        r.ax=sx;r.ay=sy
                        recovery=recovery or r.correctionStep
                    end
                    end
                    if obstruction or gap>0 then break end
                    Load.connect(records,contacts)
                    local fallbackMass
                    if fallbackStep and not takeupStep then
                        local dx=(rx-startX)/steps;local dy=(ry-startY)/steps;local distance2=dx*dx+dy*dy
                        if distance2>(.02*h)^2 then
                            fallbackMass=0
                            for _,r in ipairs(records) do if r.loadConnected then
                                local travel=((r.fallbackDX or 0)*dx+(r.fallbackDY or 0)*dy)/distance2
                                fallbackMass=fallbackMass+r.mass*math.max(0,math.min(1,travel))
                            end end
                        end
                    end
                    for _,r in ipairs(records) do
                        if recovery then
                            r.vx=r.blocked and 0 or r.physicalVX;r.vy=r.blocked and 0 or r.physicalVY
                            r.angularVelocity=r.blocked and 0 or r.physicalW;r.reaction=0
                        end
                        r.loadMass=not r.parent and (fallbackMass or (r.reaction or 0)/(9.81*.65)) or 0
                        total=total+r.loadMass/steps
                    end
                end
                return {total=total,nativeObstruction=obstruction,nativeGap=gap}
            end
            """);
        eval("""
            -- A pull across the atan2 branch cut must turn the feet a little
            -- counterclockwise, not begin a full clockwise revolution.
            local r=fixture(1,false,false)[1]
            r.x=0;r.y=0;r.angle=math.pi-.01;r.ax=10;r.ay=.1
            local old=r.angle
            Rope.step(r,0,0,10,.1,1/120,0)
            assert(r.angle>old and r.angle-old<.0251,'branch-cut pull rotates the wrong way')
            -- Engine bodies return a canonical angle after committing the pose.
            -- Re-reading that angle must not restart a full turn every frame.
            local turn=0
            for tick=1,2400 do
                r.angle=r.angle-math.floor(r.angle/(2*math.pi))*(2*math.pi)
                local old=r.angle
                r.x,r.y=Rope.step(r,r.x,r.y,10+tick/120,.1,1/120,0)
                turn=turn+math.abs(Rope.wrapAngle(r.angle-old))
            end
            assert(turn<1,'sustained rotation during a straight pull: '..turn)
            """);
        persistentHistory(platform);
        for(int scenario=0;scenario<12;scenario++) {
            boolean wall=scenario==2||scenario==7,tree=scenario==3,missing=scenario==4,solid=scenario==5;
            env.rawset("wall",wall);env.rawset("tree",tree);env.rawset("missing",missing);env.rawset("solid",solid);
            SolverEnvironment.World world=new SolverEnvironment.World(){
                public int flags(int x,int y,int z){return (missing&&x==3?1:0)|(solid&&x==3?2:0)|(tree&&x==3&&y==0?4:0);}
                public boolean blocked(int x,int y,int z,int bx,int by){return wall&&((x<3)!=(bx<3));}
            };
            int count=scenario<6?1:32;boolean chain=scenario%2==0,elastic=scenario%3!=0;
            String fixture="fixture("+count+","+chain+","+elastic+")";
            KahluaTable lua=(KahluaTable)eval("return "+fixture),java=(KahluaTable)eval("return "+fixture);
            env.rawset("records",lua);var state=TowingSolver.prepare(java);KahluaTable group=platform.newTable();
            for(int tick=0;tick<180;tick++) {
                double dt=tick==40?.5:new double[]{1./30,1./60,1./144,1./500,.1}[tick%5];
                int steps=Math.max(1,(int)Math.ceil(dt*120-1e-9));double h=dt/steps;
                double rx=1+tick*.02,ry=.5+(scenario>=6?Math.sin(tick*.04):0);
                if(scenario==9)rx=1+Math.sin(tick*.04)*3;
                if(scenario==10&&tick>70)rx+=200;
                for(KahluaTable list:new KahluaTable[]{lua,java}) for(int i=1;i<=count;i++) {
                    var b=(KahluaTable)list.rawget(i);var p=TowingSolver.table(b,"sourceSample");p.rawset("x",rx);p.rawset("y",ry);
                    if(scenario==11&&tick==80)b.rawset("failed",true);
                    if(count==1){
                        b.rawset("spreadSpeed",tick>=30&&tick<140?.2:0.);
                        b.rawset("spreadRemaining",tick%3==2?null:Double.valueOf(tick%3==0?.001:0.));
                        b.rawset("spreadOffset",tick%2==0?Double.valueOf(.1):null);b.rawset("spreadScale",.65);
                        b.rawset("spreadPush",.6);b.rawset("spreadNX",Math.sin(tick*.01));b.rawset("spreadNY",Math.cos(tick*.01));
                    }
                }
                KahluaTable first=(KahluaTable)lua.rawget(1);double sx=TowingSolver.n(first,"ax",rx),sy=TowingSolver.n(first,"ay",ry);
                KahluaTable expected=(KahluaTable)eval("return luaSolve(records,"+steps+","+h+","+sx+","+sy+","+rx+","+ry+")");
                double total=TowingSolver.solve(state,new SolverEnvironment(world),group,steps,h,sx,sy,rx,ry);group.rawset("total",total);
                try {compare(expected,group,"total");compare(expected,group,"nativeGap");compare(expected,group,"nativeObstruction");}
                catch(AssertionError error){
                    for(int i=1;i<=count;i++){var a=(KahluaTable)lua.rawget(i);var b=(KahluaTable)java.rawget(i);
                        System.out.println(i+" x="+a.rawget("x")+"/"+b.rawget("x")+" y="+a.rawget("y")+"/"+b.rawget("y")+" taut="+a.rawget("taut")+"/"+b.rawget("taut")+" mass="+a.rawget("loadMass")+"/"+b.rawget("loadMass"));}
                    throw new AssertionError("scenario="+scenario+" tick="+tick+" steps="+steps+" maxError="+maxError+" gap="+expected.rawget("nativeGap")+"/"+group.rawget("nativeGap")+" obstacle="+expected.rawget("nativeObstruction")+"/"+group.rawget("nativeObstruction"),error);}
                for(int i=1;i<=count;i++)for(String field:new String[]{"x","y","angle","vx","vy","angularVelocity","ax","ay","takeup","taut","blocked","ropeBlocked","loadMass","pushX","pushY","spreadRemaining"})
                    try { compare((KahluaTable)lua.rawget(i),(KahluaTable)java.rawget(i),field); }
                    catch(AssertionError error){throw new AssertionError("scenario="+scenario+" tick="+tick+" body="+i+" field="+field,error);}
            }
            // Rays, corners, negative coordinates and floor changes against the Lua oracle.
            Random random=new Random(17);
            for(int i=0;i<150;i++) {
                double ax=random.nextDouble()*10-5,ay=random.nextDouble()*4-2,bx=random.nextDouble()*10-5,by=random.nextDouble()*4-2,bz=i%9==0?1:0;
                Object expected=eval("return O.check(O.new(),{x="+ax+",y="+ay+",z=0},{x="+bx+",y="+by+",z="+bz+"},20)");
                String actual=new SolverEnvironment(world).check(ax,ay,0,bx,by,bz,20);
                if(!Objects.equals(expected,actual))throw new AssertionError("ray mismatch");
            }
        }
        System.out.println("PASS Lua/Java parity: "+comparisons+" state checks, 2160 group steps, 1800 rays; max absolute error="+maxError);
        // Reused contact storage must not retain load paths after bodies separate.
        var contactState=TowingSolver.prepare((KahluaTable)eval("return fixture(2,false,true)"));
        for(var b:contactState.bodies)b.read();
        contactState.bodies[0].taut=true;
        TowingSolver.separate(contactState);TowingSolver.connect(contactState);
        if(!contactState.bodies[1].connected)throw new AssertionError("contact does not transmit load");
        contactState.bodies[1].x=20;
        TowingSolver.separate(contactState);TowingSolver.connect(contactState);
        if(contactState.bodies[1].connected)throw new AssertionError("stale contact transmits load after separation");
        contactState.bodies[1].x=contactState.bodies[0].x;
        TowingSolver.separate(contactState);TowingSolver.connect(contactState);
        if(!contactState.bodies[1].connected)throw new AssertionError("contact does not recover after separation");
        System.out.println("PASS contact load: touching, separated, touching again");
        var chainState=TowingSolver.prepare((KahluaTable)eval("return fixture(32,true,true)"));
        for(var b:chainState.bodies){b.read();b.x=0;b.y=0;b.pushX=9;b.pushY=9;}
        TowingSolver.separate(chainState);
        if(chainState.contactCount!=0)throw new AssertionError("internal chain contacts remain");
        for(var b:chainState.bodies)if(b.pushX!=0||b.pushY!=0)throw new AssertionError("internal chain force remains");
        // Independent contract: a blocked coupled step cannot partially move the chain.
        for(int obstacle=0;obstacle<4;obstacle++) {
            final int kind=obstacle;
            env.rawset("wall",kind==0);env.rawset("missing",kind==1);
            env.rawset("solid",kind==2);env.rawset("tree",kind==3);
            var world=new SolverEnvironment.World(){
                public int flags(int x,int y,int z){return x==3?((kind==1?1:0)|(kind==2?2:0)|(kind==3&&y==0?4:0)):0;}
                public boolean blocked(int x,int y,int z,int bx,int by){return kind==0&&((x<3)!=(bx<3));}
            };
            for(boolean nativeSolver:new boolean[]{false,true}) {
                var records=(KahluaTable)eval("local rs=fixture(32,true,true);for _,r in ipairs(rs) do r.x=2.5;r.y=.5;r.vx=120;r.angularVelocity=.2 end;return rs");
                KahluaTable result;
                if(nativeSolver){result=platform.newTable();TowingSolver.solve(TowingSolver.prepare(records),new SolverEnvironment(world),result,1,1./120,4,.5,4,.5);}
                else {env.rawset("records",records);result=(KahluaTable)eval("return luaSolve(records,1,1/120,4,.5,4,.5)");}
                if(result.rawget("nativeObstruction")==null)throw new AssertionError("obstacle ignored: "+kind+" native="+nativeSolver);
                for(int i=1;i<=32;i++) {
                    var b=(KahluaTable)records.rawget(i);
                    if(TowingSolver.n(b,"x",0)!=2.5||TowingSolver.n(b,"y",0)!=.5||TowingSolver.n(b,"angle",0)!=0
                        ||TowingSolver.n(b,"vx",0)!=0||TowingSolver.n(b,"vy",0)!=0||TowingSolver.n(b,"angularVelocity",0)!=0)
                        throw new AssertionError("blocked chain partially committed: "+kind+" body="+i+" native="+nativeSolver);
                }
            }
        }
        System.out.println("PASS atomic chain stop: wall, unloaded cell, solid tile, tree; Lua and Java");
        for(double spacing:new double[]{1.2,.25,0}) for(boolean jitter:new boolean[]{false,true}) {
            if(jitter && spacing<1)continue;
            env.rawset("spacing",spacing);
            var spaced=(KahluaTable)eval("""
                local rs=fixture(32,true,true)
                for i,r in ipairs(rs) do r.x=.75;r.y=3+(i-1)*spacing;r.length=i==1 and 3 or math.max(.25,spacing) end
                return rs
                """);
            var state=TowingSolver.prepare(spaced);var group=platform.newTable();
            var empty=new SolverEnvironment.World(){public int flags(int x,int y,int z){return 0;}public boolean blocked(int x,int y,int z,int bx,int by){return false;}};
            double lastY=0,maxStoppedSpeed=0,maxOrbit=0,maxDrift=0,maxFrameMove=0;double[] settledX=new double[32],settledY=new double[32],previousX=new double[32],previousY=new double[32];double[] orbit=new double[32],previousOrbit=new double[32];
            for(int tick=0;tick<3600;tick++) {
                double y=-Math.min(tick,1800)/60.;
                // A stopped vehicle can report small position fluctuations.
                if(jitter && tick>=1800)y+=.001*Math.sin((tick-1800)*.3);
                for(int i=1;i<=32;i++){var b=(KahluaTable)spaced.rawget(i);var p=TowingSolver.table(b,"sourceSample");p.rawset("x",0.);p.rawset("y",y);}
                TowingSolver.solve(state,new SolverEnvironment(empty),group,2,1./120,0,lastY,0,y);lastY=y;
                double speed=0;
                for(int i=1;i<=32;i++){var b=(KahluaTable)spaced.rawget(i);speed=Math.max(speed,Math.hypot(TowingSolver.n(b,"vx",0),TowingSolver.n(b,"vy",0)));}
                if(tick>=2400){
                    maxStoppedSpeed=Math.max(maxStoppedSpeed,speed);
                    for(int i=0;i<32;i++){var b=(KahluaTable)spaced.rawget(i+1);double angle=Math.atan2(TowingSolver.n(b,"y",0)-y,TowingSolver.n(b,"x",0));
                        double bx=TowingSolver.n(b,"x",0),by=TowingSolver.n(b,"y",0);
                        if(tick==2400){settledX[i]=bx;settledY[i]=by;}
                        else maxFrameMove=Math.max(maxFrameMove,Math.hypot(bx-previousX[i],by-previousY[i]));
                        maxDrift=Math.max(maxDrift,Math.hypot(bx-settledX[i],by-settledY[i]));previousX[i]=bx;previousY[i]=by;
                        if(!Double.isFinite(bx)||!Double.isFinite(by)||!Double.isFinite(speed))throw new AssertionError("nonfinite stopped pose");
                        if(tick>2400)orbit[i]+=TowingSolver.wrap(angle-previousOrbit[i]);previousOrbit[i]=angle;maxOrbit=Math.max(maxOrbit,Math.abs(orbit[i]));}
                }
                if(group.rawget("nativeObstruction")!=null || TowingSolver.n(group,"nativeGap",0)!=0)throw new AssertionError("dense fixture lost a link");
            }
            // Velocity is reconstructed from positional corrections at 120 Hz.
            // For a spaced chain, bound visible movement instead: <= solver tolerance
            // per 60 Hz frame and <= 5 cm excursion over the final 20 seconds.
            // Dense overlapping fixtures retain their separate relaxation contract.
            if((spacing>1 ? maxFrameMove>.005 || maxDrift>.05 : maxStoppedSpeed>.5) || maxOrbit>Math.PI/2)throw new AssertionError("stationary chain spins: spacing="+spacing+" speed="+maxStoppedSpeed+" orbit="+maxOrbit+" frameMove="+maxFrameMove+" drift="+maxDrift);
            System.out.println("PASS stopped 32-body chain: spacing="+spacing+" jitter="+jitter+" maxSpeed="+maxStoppedSpeed+" maxOrbit="+maxOrbit+" maxFrameMove="+maxFrameMove+" maxDrift="+maxDrift);
        }
    }
}
