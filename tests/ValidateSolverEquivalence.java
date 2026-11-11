package cvpworld;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.*;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.j2se.MathLib;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.stdlib.BaseLib;
import se.krka.kahlua.stdlib.StringLib;
import se.krka.kahlua.stdlib.TableLib;
import se.krka.kahlua.vm.*;

/**
 * Three-way solver equivalence oracle.
 *
 * <p>Compares the frozen base solver (renamed {@code TowingSolverBaseline} and compiled
 * beside the live class), the frozen Lua group module (loaded as module
 * {@code CVP_GroupConstraintsBaseline} in the same Kahlua VM) and the live
 * implementations. Java and Lua are driven through their public record contract this
 * tick only; no production source is edited.
 *
 * <p>Kept intentionally independent of the production solver internals (no direct
 * access to {@code State}/{@code Body} fields) so an optimization that renames or
 * removes internal state cannot make the oracle fail to compile; the observable
 * contract is what is compared.
 */
public class ValidateSolverEquivalence {
    static final double TOLERANCE=1e-13;
    static final String BASELINE_JAVA_SHA256="DC04B22E89B820BB18CBE0C261FF21CA4EEC1BA7E7A317616B7FB63F0D24EA87";
    static final String BASELINE_LUA_SHA256="7E3E20D9686912C4D5AF5781F3C31B7313FC60D17196DA4F51D1929BF68E571F";
    static final Path BASELINE_JAVA=Path.of("tests/fixtures/solver_baseline/TowingSolver.java");
    static final Path BASELINE_LUA=Path.of("tests/fixtures/solver_baseline/CVP_GroupConstraints.lua");
    static final Path CURRENT_JAVA=Path.of("CorpseProxyLab/source/cvpworld/TowingSolver.java");
    // Default is the shipped module. The override exists only for the harness self-test
    // (a deliberately diverging module must be reported as a failure); tests never set it.
    static final Path CURRENT_LUA=Path.of(System.getProperty(
        "cvp.liveLua","CorpseProxyLab/42/media/lua/shared/CVP_GroupConstraints.lua"));
    static final Path JAR=Path.of(System.getProperty("cvp.jar","CorpseProxyLab/42/media/java/CorpseProxyWorld.jar"));
    // The Python runner never disables this; the flag only exists for harness development
    // while production teammates are still editing the sources.
    static final boolean STRICT_JAR=!"disabled".equals(System.getProperty("cvp.jarCheck"));

    static KahluaThread thread;
    static KahluaTable env;
    static Platform platform;
    static long comparisons;
    static double maxError;
    static String context="<startup>";

    // Scenario matrix. Every body count / motion / contract case named by the task is present.
    static final String[] SCENARIOS={
        "rest-1","straight-1","turn-1",
        "rest-4","straight-4","turn-4","brake-4","reverse-4","slack-4","mass-4","reset-4",
        "straight-32","turn-32","brake-32","reverse-32","slack-32","mass-32",
        "obstacle-wall-32","obstacle-unloaded-32","obstacle-solid-32","obstacle-tree-32",
        "chains-1x32","chains-2x32","chains-4x32",
        "unload-replacement-32","topology-change-32","backend-switch-32","rollback-32",
    };
    // Java-only contract scenarios: the Lua module has no native state object to release/roll back.
    static final Set<String> LUA_SKIP=Set.of("reset-4","backend-switch-32","rollback-32");
    static final Set<String> JAVA_LUA_SKIP=Set.of("reset-4","backend-switch-32","rollback-32");

    // Record fields the live Java solver publishes (persistent mode defers history to release()).
    static final String[] JAVA_BODY_TICK={
        "x","y","angle","length","taut","blocked","ropeBlocked","loadMass","loadConnected",
        "ax","ay","spreadRemaining","pushX","pushY",
    };
    static final String[] JAVA_BODY_HISTORY={
        "vx","vy","angularVelocity","takeup","ropeConstraintReady",
    };
    static final String[] JAVA_BODY_ALL=concat(JAVA_BODY_TICK,JAVA_BODY_HISTORY);
    static final String[] JAVA_SNAPSHOT={
        "x","y","angle","length","taut","blocked","ropeBlocked","loadMass","loadConnected",
        "ax","ay","spreadRemaining","pushX","pushY",
    };
    static final String[] LUA_BODY={
        "x","y","angle","vx","vy","angularVelocity","length","taut","blocked","ropeBlocked",
        "loadMass","loadConnected","ax","ay","takeup","ropeConstraintReady","pushX","pushY",
        "spreadRemaining","physicalVX","physicalVY","physicalW","reaction","correctionStep",
        "fallbackDX","fallbackDY",
    };
    static final String[] JAVA_LUA_BODY={
        "x","y","angle","vx","vy","angularVelocity","length","taut","blocked","ropeBlocked",
        "loadMass","loadConnected","ax","ay","takeup","ropeConstraintReady","pushX","pushY",
        "spreadRemaining",
    };
    static final String[] JAVA_GROUP={
        "nativeUnconverged","nativeFallback","recoverySteps","solverResidual","solverIterations",
        "nativeObstruction","nativeGap","nativeGapX","nativeGapY","nativeGapZ",
    };
    static final String[] LUA_GROUP={
        "nativeUnconverged","nativeFallback","fallbackStep","takeupStep","recoveryStep",
        "solverResidual","solverIterations","nativeObstruction","nativeGap",
        "nativeGapX","nativeGapY","nativeGapZ",
    };
    static final String[] SHARED_GROUP={
        "nativeUnconverged","nativeFallback","solverResidual","solverIterations",
        "nativeObstruction","nativeGap","nativeGapX","nativeGapY","nativeGapZ",
    };
    // The single-body Lua path is the legacy inline solver: it publishes no group counters.
    static final String[] SHARED_GROUP_SINGLE={"nativeObstruction","nativeGap"};
    // Multi-substep aggregation differs by backend: Java keeps the maximum iteration
    // count and a sticky fallback flag across substeps, the Lua group table is per
    // substep. Only keys whose meaning is identical are compared across backends.
    static final String[] SHARED_GROUP_MULTI={
        "nativeUnconverged","nativeObstruction","nativeGap","nativeGapX","nativeGapY","nativeGapZ",
    };

    static String[] sharedGroupKeys(int steps){return steps==1?SHARED_GROUP:SHARED_GROUP_MULTI;}

    /**
     * Cross-backend group comparison. Iteration/residual counters only exist once the
     * Lua module entered its iteration loop for a substep: on an unloaded-cell gap it
     * returns early and leaves them nil while the native solver publishes its zero
     * initialiser. Compare them only when both backends actually produced a value.
     * Iteration counts are only comparable for a single substep (aggregation differs).
     */
    static void compareSharedGroup(String where,KahluaTable javaGroup,KahluaTable luaGroup,int steps){
        compareGroups(where,javaGroup,luaGroup,SHARED_GROUP_MULTI);
        Object javaResidual=javaGroup.rawget("solverResidual"),luaResidual=luaGroup.rawget("solverResidual");
        if(javaResidual!=null&&luaResidual!=null)
            compareValue(where+"/group/solverResidual",javaResidual,luaResidual);
        if(steps==1){
            Object javaIterations=javaGroup.rawget("solverIterations"),luaIterations=luaGroup.rawget("solverIterations");
            if(javaIterations!=null&&luaIterations!=null)
                compareValue(where+"/group/solverIterations",javaIterations,luaIterations);
        }
    }
    // Released persistent Java history exposes the same contract as the Lua records
    // except pushX/pushY, which only the legacy (non-persistent) API publishes.
    static final String[] PERSISTENT_ALIGNED={
        "x","y","angle","vx","vy","angularVelocity","length","taut","blocked","ropeBlocked",
        "loadMass","loadConnected","ax","ay","takeup","ropeConstraintReady","spreadRemaining",
    };
    // Persistent Java ticks do not publish history fields; they are compared after release().
    static final String[] PERSISTENT_BODY={
        "x","y","angle","length","taut","blocked","ropeBlocked","loadMass","loadConnected",
        "ax","ay","spreadRemaining",
    };

    public static void main(String[] args) throws Exception {
        long started=System.nanoTime();
        verifyHeader();
        initVm();
        backendSmoke();
        long mark=System.nanoTime();
        javaVsJava();
        System.out.println("PASS oracle 1/3 java-vs-java: old frozen Java vs live Java ("+seconds(mark)+")");
        mark=System.nanoTime();
        luaVsLua();
        System.out.println("PASS oracle 2/3 lua-vs-lua: old frozen Lua module vs live Lua module ("+seconds(mark)+")");
        mark=System.nanoTime();
        javaVsLua();
        System.out.println("PASS oracle 3/3 java-vs-lua: live Java vs live Lua ("+seconds(mark)+")");
        mark=System.nanoTime();
        scalingEvidence();
        System.out.println("PASS controlled scaling: identical 1/2/4 x 32-body chains ("+seconds(mark)+")");
        System.out.println("PASS solver equivalence: "+comparisons+" compared values, max absolute error="+maxError
            +", scenarios="+SCENARIOS.length+", elapsed="+seconds(started));
        System.out.println("oracleResult=PASS");
    }

    static String seconds(long started){return String.format(Locale.ROOT,"%.3fs",(System.nanoTime()-started)/1e9);}

    // ---------------------------------------------------------------- header / backend proof

    static void verifyHeader() throws Exception {
        String baselineJava=sha256(BASELINE_JAVA);
        String baselineLua=sha256(BASELINE_LUA);
        if(!baselineJava.equals(BASELINE_JAVA_SHA256))
            throw new AssertionError("frozen baseline Java changed: "+baselineJava+" != "+BASELINE_JAVA_SHA256);
        if(!baselineLua.equals(BASELINE_LUA_SHA256))
            throw new AssertionError("frozen baseline Lua changed: "+baselineLua+" != "+BASELINE_LUA_SHA256);
        if(!Files.isRegularFile(CURRENT_JAVA)) throw new AssertionError("missing live solver source: "+CURRENT_JAVA.toAbsolutePath());
        if(!Files.isRegularFile(CURRENT_LUA)) throw new AssertionError("missing live Lua group source: "+CURRENT_LUA.toAbsolutePath());
        if(!Files.isRegularFile(JAR)) throw new AssertionError("shipped solver JAR missing: "+JAR.toAbsolutePath());
        Class<?> live=loadClass("cvpworld.TowingSolver","live Java solver did not compile/load");
        Class<?> baseline=loadClass("cvpworld.TowingSolverBaseline","frozen Java baseline did not compile/load beside the live solver");
        byte[] compiledSolver=resource("cvpworld/TowingSolver.class");
        byte[] jarSolver;
        try(JarFile jar=new JarFile(JAR.toFile())) {
            JarEntry entry=jar.getJarEntry("cvpworld/TowingSolver.class");
            if(entry==null) throw new AssertionError("shipped JAR does not contain cvpworld/TowingSolver.class: "+JAR.toAbsolutePath());
            jarSolver=readAll(jar.getInputStream(entry));
        }
        String compiledSha=sha256(compiledSolver);
        String jarSha=sha256(jarSolver);
        String jarFileSha=sha256(JAR);
        String currentJavaSha=sha256(CURRENT_JAVA);
        String currentLuaSha=sha256(CURRENT_LUA);
        System.out.println("=== SOLVER EQUIVALENCE HEADER ===");
        System.out.println("oracle=three-way (old-java vs new-java, old-lua vs new-lua, new-java vs new-lua)");
        System.out.println("baselineJavaPath="+BASELINE_JAVA.toAbsolutePath());
        System.out.println("baselineJavaSha256="+baselineJava);
        System.out.println("baselineLuaPath="+BASELINE_LUA.toAbsolutePath());
        System.out.println("baselineLuaSha256="+baselineLua);
        System.out.println("currentJavaPath="+CURRENT_JAVA.toAbsolutePath());
        System.out.println("currentJavaSha256="+currentJavaSha);
        System.out.println("currentLuaPath="+CURRENT_LUA.toAbsolutePath());
        System.out.println("currentLuaSha256="+currentLuaSha);
        System.out.println("jarPath="+JAR.toAbsolutePath());
        System.out.println("jarFileSha256="+jarFileSha);
        System.out.println("jarTowingSolverClassSha256="+jarSha);
        System.out.println("compiledTowingSolverClassSha256="+compiledSha);
        System.out.println("jarClassMatchesCompiled="+(jarSha.equals(compiledSha)));
        System.out.println("jarClassCheck="+(STRICT_JAR?"enforced":"disabled-for-harness-development"));
        System.out.println("nativeClass=cvpworld.TowingSolver");
        System.out.println("nativeClassSource="+codeSource(live));
        System.out.println("baselineClass=cvpworld.TowingSolverBaseline");
        System.out.println("baselineClassSource="+codeSource(baseline));
        System.out.println("nativeSolverVersion="+TowingSolver.version());
        System.out.println("backend=in-process-java-native (+ kahlua Lua oracle in same JVM)");
        System.out.println("luaVm=kahlua "+KahluaThread.class.getPackage().getImplementationVersion());
        System.out.println("=== END SOLVER EQUIVALENCE HEADER ===");
        if(STRICT_JAR&&!jarSha.equals(compiledSha))
            throw new AssertionError("stale shipped JAR: cvpworld/TowingSolver.class in "+JAR.toAbsolutePath()
                +" does not match the source compiled for this oracle ("+jarSha+" != "+compiledSha
                +"); run tools/Project.ps1 -Action build and retry");
    }

    static Class<?> loadClass(String name,String failure) {
        try { return Class.forName(name); }
        catch(ClassNotFoundException error) { throw new AssertionError(failure+": "+name,error); }
    }

    static String codeSource(Class<?> type) {
        try {
            var source=type.getProtectionDomain().getCodeSource();
            return source==null||source.getLocation()==null?"<unknown>":source.getLocation().toString();
        } catch(RuntimeException error) { return "<unavailable: "+error+">"; }
    }

    static void backendSmoke() throws Exception {
        KahluaTable records=(KahluaTable)eval("return fixture(1,false,false)");
        TowingSolver.State state=TowingSolver.prepare(records);
        KahluaTable group=platform.newTable();
        double load=TowingSolver.solve(state,new SolverEnvironment(clearWorld()),group,2,1./120,1,.5,1.5,.5);
        if(!Double.isFinite(load)) throw new AssertionError("native backend returned non-finite load: "+load);
        double x=num((KahluaTable)records.rawget(1),"x",Double.NaN);
        if(!Double.isFinite(x)) throw new AssertionError("native backend did not publish a finite candidate pose");
        TowingSolver.release(state);
        comparisons++;
        System.out.println("nativeSmoke=ok load="+load+" x="+x);
    }

    // ---------------------------------------------------------------- Kahlua VM

    static Object eval(String code) throws Exception {
        Object[] result=thread.pcall(LuaCompiler.loadstring(code,"solver-equivalence",env),new Object[0]);
        if(!Boolean.TRUE.equals(result[0])){
            for(Object value:result) if(value instanceof Throwable failure) failure.printStackTrace(System.err);
            throw new AssertionError(context+": Lua error: "+Arrays.toString(result));
        }
        return result.length>1?result[1]:null;
    }

    static String evalFailure(String code) throws Exception {
        Object[] result=thread.pcall(LuaCompiler.loadstring(code,"solver-equivalence-error",env),new Object[0]);
        if(Boolean.TRUE.equals(result[0])) return null;
        return result.length>1?String.valueOf(result[1]):"<no error message>";
    }

    static void initVm() throws Exception {
        platform=J2SEPlatform.getInstance();
        env=platform.newTable();
        BaseLib.register(env);
        TableLib.register(platform,env);
        MathLib.register(platform,env);
        StringLib.register(platform,env);
        thread=new KahluaThread(platform,env);
        thread.debugOwnerThread=Thread.currentThread();
        zombie.Lua.LuaManager.env=env;
        zombie.Lua.LuaManager.thread=thread;
        zombie.Lua.LuaManager.debugthread=thread;
        eval("ipairs=table.ipairs;pairs=table.pairs;function assert(v,msg) if not v then error(msg or 'assert') end return v end;modules={};function require(n) return modules[n] or {} end");
        eval("function math.max(v,...) for i=1,select('#',...) do local n=select(i,...);if n>v then v=n end end return v end;function math.min(v,...) for i=1,select('#',...) do local n=select(i,...);if n<v then v=n end end return v end");
        KahluaTable modules=(KahluaTable)env.rawget("modules");
        for(String name:new String[]{"CVP_Rope","CVP_LinkObstacles","CVP_Geometry","CVP_Load","CVP_Core","CVP_GroupConstraints"}){
            Path source=name.equals("CVP_GroupConstraints")
                ?CURRENT_LUA
                :Path.of("CorpseProxyLab/42/media/lua/shared/"+name+".lua");
            modules.rawset(name,eval(Files.readString(source)));
        }
        // Same Kahlua VM, distinct module name: the frozen group solver runs beside the live one.
        modules.rawset("CVP_GroupConstraintsBaseline",eval(Files.readString(BASELINE_LUA)));
        eval("Rope=require 'CVP_Rope';O=require 'CVP_LinkObstacles';Geometry=require 'CVP_Geometry';"
            +"Load=require 'CVP_Load';Core=require 'CVP_Core';Group=require 'CVP_GroupConstraints';"
            +"GroupBaseline=require 'CVP_GroupConstraintsBaseline'");
        eval(FIXTURES_LUA);
    }

    static final String FIXTURES_LUA="""
        wall=false;tree=false;missing=false;solid=false;boom=false
        function getCell() return {getGridSquare=function(_,x,y,z)
            if missing and x==3 then return nil end
            return {x=x,y=y,isSolid=function() if boom then error('injected world query failure') end;return solid and x==3 end,isSolidTrans=function() return false end,
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
        function chains(count)
            local all={}
            for c=1,count do
                local rs=fixture(32,true,true);local oy=(c-1)*8
                for i,r in ipairs(rs) do r.y=r.y+oy end
                for i=1,#rs do all[#all+1]=rs[i] end
            end
            return all
        end
        function fourChains() return chains(4) end
        function luaSolveWith(groupModule,records,steps,h,startX,startY,rx,ry)
            local c=O.new();local contacts={};local total=0;local obstruction=nil;local gap=0;local group=nil
            for _,r in ipairs(records) do r.blocked=false;r.taut=false;r.ropeBlocked=nil end
            for step=1,steps do
                Rope.separate(records,contacts)
                local recovery=false;local fallbackStep=false;local takeupStep=false
                if #records>1 then
                    local result={};groupModule.step(records,c,startX+(rx-startX)*step/steps,startY+(ry-startY)*step/steps,h,result)
                    group=result
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
            return {total=total,nativeObstruction=obstruction,nativeGap=gap,group=group or {}}
        end
        """;

    // ---------------------------------------------------------------- small helpers

    static KahluaTable record(KahluaTable records,int index){return (KahluaTable)records.rawget(index);}
    static double num(KahluaTable table,String field,double fallback){
        Object value=table==null?null:table.rawget(field);
        return value instanceof Number?((Number)value).doubleValue():fallback;
    }
    static String str(double value){return Double.toString(value);}
    static void fail(String message){throw new AssertionError(message);}

    static final double[] DT={1./30,1./60,1./144,1./500,.1};
    record Plan(int steps,double h,double startX,double startY,double rootX,double rootY){}
    record Fixture(String expr,int bodies){}

    static Plan plan(KahluaTable records,String scenario,int tick){
        // Large groups only use the cheap dt pool: they already span all step counts.
        double dt=fixture(scenario).bodies()<=4?(tick==40?.5:DT[tick%5]):DT[tick%3];
        int steps=Math.max(1,(int)Math.ceil(dt*120-1e-9));
        double h=dt/steps;
        double[] target=target(scenario,tick);
        double startX=num(record(records,1),"ax",target[0]);
        double startY=num(record(records,1),"ay",target[1]);
        if(base(scenario).equals("chains")){
            // Chains 2..4 receive their target from sourceSample, which is static for the
            // whole tick. Disable the root interpolation so every chain sees the same input.
            startX=target[0];
            startY=target[1];
        }
        return new Plan(steps,h,startX,startY,target[0],target[1]);
    }

    static String base(String scenario){
        if(scenario.startsWith("chains-")) return "chains";
        return scenario.replaceAll("-(1|4|32)$","");
    }

    static Fixture fixture(String scenario){
        if(Set.of("rest-1","straight-1","turn-1").contains(scenario)) return new Fixture("fixture(1,false,false)",1);
        if(scenario.startsWith("chains-")){
            int chains=Integer.parseInt(scenario.substring("chains-".length(),scenario.indexOf('x')));
            return new Fixture("chains("+chains+")",chains*32);
        }
        int bodies=scenario.endsWith("-4")?4:32;
        return new Fixture("fixture("+bodies+",true,true)",bodies);
    }

    static int ticks(String scenario){
        int bodies=fixture(scenario).bodies();
        String base=base(scenario);
        if(bodies==1) return base.equals("rest")?50:70;
        if(base.equals("chains")) return 30;
        if(base.equals("rest")) return 40;
        if(base.equals("slack")) return bodies==4?70:50;
        if(base.startsWith("obstacle")) return 40;
        if(base.equals("unload-replacement")||base.equals("topology-change")
            ||base.equals("backend-switch")||base.equals("rollback")) return 40;
        return bodies==4?60:40;
    }

    static double[] target(String scenario,int tick){
        return switch(base(scenario)){
            case "rest" -> new double[]{1,.5};
            case "straight","mass","reset","unload-replacement","backend-switch","rollback","chains" -> new double[]{1+tick*.02,.5};
            case "turn","topology-change" -> new double[]{1+Math.sin(tick*.04)*3,.5+Math.sin(tick*.02)*1.5};
            case "brake" -> new double[]{1+Math.min(tick,40)*.02,.5};
            case "reverse" -> new double[]{1-tick*.015,.5};
            case "slack" -> new double[]{1+2*Math.sin(tick*.045),.5};
            case "obstacle-wall","obstacle-unloaded","obstacle-solid","obstacle-tree" -> new double[]{1+tick*.08,.5};
            default -> throw new IllegalArgumentException("no target for "+scenario);
        };
    }

    static void mutate(String scenario,int tick,KahluaTable records){
        String base=base(scenario);
        int count=records.len();
        // Repeated spread fields exercise the single-body recovery/fallback path.
        if(count==1){
            KahluaTable r=record(records,1);
            r.rawset("spreadSpeed",tick>=30&&tick<140?.2:0.);
            r.rawset("spreadRemaining",tick%3==2?null:Double.valueOf(tick%3==0?.001:0.));
            r.rawset("spreadOffset",tick%2==0?Double.valueOf(.1):null);
            r.rawset("spreadScale",.65);
            r.rawset("spreadPush",.6);
            r.rawset("spreadNX",Math.sin(tick*.01));
            r.rawset("spreadNY",Math.cos(tick*.01));
        }
        double[] target=target(scenario,tick);
        for(int index=1;index<=count;index++){
            KahluaTable r=record(records,index);
            KahluaTable source=(KahluaTable)r.rawget("sourceSample");
            if(base.equals("chains")){
                int chain=(index-1)/32;
                source.rawset("x",target[0]);
                source.rawset("y",target[1]+chain*8.);
            } else {
                source.rawset("x",target[0]);
                source.rawset("y",target[1]);
            }
            if(base.equals("topology-change")&&tick>=12&&tick<28&&index==17){
                // After the split the second chain root lives beside the first chain.
                source.rawset("x",target[0]-5.);
            }
        }
        if(base.equals("mass")){
            for(int index=1;index<=count;index++)
                record(records,index).rawset("mass",(double)(75+index+(tick%20<10?0:50)));
        }
        if(base.equals("unload-replacement")){
            record(records,count).rawset("z",tick>=12&&tick<21?1.:0.);
        }
        if(base.equals("topology-change")){
            if(tick==12){
                // Break the chain into two independent 16-body chains. Re-place the new
                // chain beside the first one so the re-link is a real topology change,
                // not a multi-metre tether stretch that would only exercise the fallback.
                double rootX=target[0]-5.,rootY=target[1];
                for(int index=17;index<=32;index++){
                    KahluaTable r=record(records,index);
                    r.rawset("parent",null);
                    r.rawset("x",rootX-(index-17)*.8);
                    r.rawset("y",rootY);
                    r.rawset("angle",0.);
                    relinked(r);
                }
            }
            if(tick==28){
                KahluaTable head=record(records,16);
                double headX=num(head,"x",target[0]),headY=num(head,"y",target[1]),headAngle=num(head,"angle",0);
                for(int index=17;index<=32;index++){
                    KahluaTable r=record(records,index);
                    r.rawset("parent",record(records,index-1));
                    r.rawset("x",headX-(index-16)*.8);
                    r.rawset("y",headY);
                    r.rawset("angle",headAngle);
                    relinked(r);
                }
            }
        }
        if(base.equals("reset")&&tick==20){
            for(int index=1;index<=count;index++){
                KahluaTable r=record(records,index);
                r.rawset("nativeResetMotion",true);
                r.rawset("nativeResetConstraint",true);
            }
        }
    }

    static boolean isObstacleScenario(String scenario){return base(scenario).startsWith("obstacle");}
    static boolean reprepare(String scenario,int tick){
        String base=base(scenario);
        return (base.equals("topology-change")&&(tick==12||tick==28))
            ||(base.equals("unload-replacement")&&tick==21);
    }
    /** A re-linked body starts without inherited solver history. */
    static void relinked(KahluaTable record){
        record.rawset("vx",0.);
        record.rawset("vy",0.);
        record.rawset("angularVelocity",0.);
        record.rawset("takeup",null);
        record.rawset("ropeConstraintReady",null);
    }
    static boolean backendSwitch(String scenario,int tick){
        return base(scenario).equals("backend-switch")&&(tick==15||tick==28);
    }
    static boolean rollbackTick(String scenario,int tick){
        return base(scenario).equals("rollback")&&tick==20;
    }

    static SolverEnvironment.World clearWorld(){
        return new SolverEnvironment.World(){
            public int flags(int x,int y,int z){return 0;}
            public boolean blocked(int x,int y,int z,int bx,int by){return false;}
        };
    }

    static SolverEnvironment.World javaWorld(String scenario,int tick){
        String base=base(scenario);
        int wall=base.equals("obstacle-wall")?1:0;
        int unloaded=base.equals("obstacle-unloaded")?1:0;
        int solid=base.equals("obstacle-solid")?1:0;
        int tree=base.equals("obstacle-tree")?1:0;
        return new SolverEnvironment.World(){
            public int flags(int x,int y,int z){return x==3?(unloaded|solid<<1|((tree!=0&&y==0)?4:0)):0;}
            public boolean blocked(int x,int y,int z,int bx,int by){return wall!=0&&((x<3)!=(bx<3));}
        };
    }

    static SolverEnvironment failingEnvironment(RuntimeException injected){
        return new SolverEnvironment(new SolverEnvironment.World(){
            public int flags(int x,int y,int z){throw injected;}
            public boolean blocked(int x,int y,int z,int bx,int by){throw injected;}
        });
    }

    static void setLuaObstacles(String scenario,int tick){
        String base=base(scenario);
        env.rawset("wall",base.equals("obstacle-wall"));
        env.rawset("missing",base.equals("obstacle-unloaded"));
        env.rawset("solid",base.equals("obstacle-solid"));
        env.rawset("tree",base.equals("obstacle-tree"));
    }

    // ---------------------------------------------------------------- comparison helpers

    static void compareNumber(String where,Object left,Object right){
        comparisons++;
        double a=((Number)left).doubleValue(),b=((Number)right).doubleValue();
        if(Double.isNaN(a)&&Double.isNaN(b)) return;
        double error=Math.abs(a-b);
        maxError=Math.max(maxError,error);
        if(!(error<TOLERANCE)) fail(where+": "+a+" != "+b+" error="+error);
    }

    static void compareValue(String where,Object left,Object right){
        if(left instanceof Number&&right instanceof Number){compareNumber(where,left,right);return;}
        comparisons++;
        if(Objects.equals(left,right)
            ||(left==null&&Boolean.FALSE.equals(right))
            ||(right==null&&Boolean.FALSE.equals(left))) return;
        fail(where+": "+left+" != "+right);
    }

    static void compareBodies(String where,KahluaTable left,KahluaTable right,String[] fields){
        int count=Math.min(left.len(),right.len());
        if(left.len()!=right.len()) fail(where+": record count "+left.len()+" != "+right.len());
        for(int index=1;index<=count;index++){
            KahluaTable a=record(left,index),b=record(right,index);
            for(String field:fields) compareValue(where+"/body="+index+"/"+field,a.rawget(field),b.rawget(field));
        }
    }

    static void compareGroups(String where,KahluaTable left,KahluaTable right,String[] fields){
        for(String field:fields) compareValue(where+"/group/"+field,left.rawget(field),right.rawget(field));
    }

    static Map<Integer,Object[]> snapshot(KahluaTable records,String[] fields){
        Map<Integer,Object[]> snapshot=new LinkedHashMap<>();
        for(int index=1;index<=records.len();index++){
            KahluaTable r=record(records,index);
            Object[] values=new Object[fields.length];
            for(int i=0;i<fields.length;i++) values[i]=r.rawget(fields[i]);
            snapshot.put(index,values);
        }
        return snapshot;
    }

    static void assertStable(String where,KahluaTable records,Map<Integer,Object[]> snapshot){
        String[] fields=JAVA_SNAPSHOT;
        for(Map.Entry<Integer,Object[]> entry:snapshot.entrySet()){
            KahluaTable r=record(records,entry.getKey());
            Object[] values=entry.getValue();
            for(int i=0;i<fields.length;i++)
                compareValue(where+"/body="+entry.getKey()+"/"+fields[i],values[i],r.rawget(fields[i]));
        }
    }

    static void checkResetsConsumed(String where,String scenario,int tick,KahluaTable left,KahluaTable right){
        if(!base(scenario).equals("reset")||tick<20) return;
        for(KahluaTable records:new KahluaTable[]{left,right})
            for(int index=1;index<=records.len();index++){
                KahluaTable r=record(records,index);
                if(r.rawget("nativeResetMotion")!=null||r.rawget("nativeResetConstraint")!=null)
                    fail(where+"/body="+index+": reset flag was not consumed");
            }
    }

    // ---------------------------------------------------------------- java backends

    interface JavaBackend {
        String name();
        Object prepare(KahluaTable records);
        void release(Object state);
        double persistent(Object state,SolverEnvironment environment,KahluaTable group,int steps,double h,
                          double startX,double startY,double rootX,double rootY);
        double legacy(Object state,SolverEnvironment environment,KahluaTable group,int steps,double h,
                      double startX,double startY,double rootX,double rootY);
    }

    static final JavaBackend OLD_JAVA=new JavaBackend(){
        public String name(){return "frozen-baseline-java";}
        public Object prepare(KahluaTable records){return TowingSolverBaseline.prepare(records);}
        public void release(Object state){TowingSolverBaseline.release((TowingSolverBaseline.State)state);}
        public double persistent(Object state,SolverEnvironment environment,KahluaTable group,int steps,double h,
                                 double startX,double startY,double rootX,double rootY){
            return TowingSolverBaseline.solvePersistent((TowingSolverBaseline.State)state,environment,group,steps,h,startX,startY,rootX,rootY);
        }
        public double legacy(Object state,SolverEnvironment environment,KahluaTable group,int steps,double h,
                             double startX,double startY,double rootX,double rootY){
            return TowingSolverBaseline.solve((TowingSolverBaseline.State)state,environment,group,steps,h,startX,startY,rootX,rootY);
        }
    };
    static final JavaBackend NEW_JAVA=new JavaBackend(){
        public String name(){return "live-java";}
        public Object prepare(KahluaTable records){return TowingSolver.prepare(records);}
        public void release(Object state){TowingSolver.release((TowingSolver.State)state);}
        public double persistent(Object state,SolverEnvironment environment,KahluaTable group,int steps,double h,
                                 double startX,double startY,double rootX,double rootY){
            return TowingSolver.solvePersistent((TowingSolver.State)state,environment,group,steps,h,startX,startY,rootX,rootY);
        }
        public double legacy(Object state,SolverEnvironment environment,KahluaTable group,int steps,double h,
                             double startX,double startY,double rootX,double rootY){
            return TowingSolver.solve((TowingSolver.State)state,environment,group,steps,h,startX,startY,rootX,rootY);
        }
    };

    // ---------------------------------------------------------------- oracle 1: old Java vs new Java

    static void javaVsJava() throws Exception {
        for(String scenario:SCENARIOS){
            Fixture fixture=fixture(scenario);
            KahluaTable a=(KahluaTable)eval("return "+fixture.expr);
            KahluaTable b=(KahluaTable)eval("return "+fixture.expr);
            Object stateA=OLD_JAVA.prepare(a);
            Object stateB=NEW_JAVA.prepare(b);
            String where="java-vs-java/"+scenario;
            System.out.println("oracle1 scenario="+scenario+" bodies="+fixture.bodies+" ticks="+ticks(scenario));
            long started=System.nanoTime();
            boolean obstructionObserved=false,gapObserved=false;
            for(int tick=0;tick<ticks(scenario);tick++){
                if(reprepare(scenario,tick)){
                    OLD_JAVA.release(stateA);
                    NEW_JAVA.release(stateB);
                }
                mutate(scenario,tick,a);
                mutate(scenario,tick,b);
                if(reprepare(scenario,tick)){
                    stateA=OLD_JAVA.prepare(a);
                    stateB=NEW_JAVA.prepare(b);
                }
                Plan step=plan(a,scenario,tick);
                if(rollbackTick(scenario,tick)){
                    Map<Integer,Object[]> snapshotA=snapshot(a,JAVA_SNAPSHOT);
                    Map<Integer,Object[]> snapshotB=snapshot(b,JAVA_SNAPSHOT);
                    IllegalStateException injectedA=new IllegalStateException("injected solver world read failure");
                    IllegalStateException injectedB=new IllegalStateException("injected solver world read failure");
                    try {
                        OLD_JAVA.persistent(stateA,failingEnvironment(injectedA),platform.newTable(),step.steps,step.h,
                            step.startX,step.startY,step.rootX,step.rootY);
                        fail(where+"/rollback: frozen baseline did not propagate the injected failure");
                    } catch(IllegalStateException failure){ if(failure!=injectedA) throw failure; }
                    try {
                        NEW_JAVA.persistent(stateB,failingEnvironment(injectedB),platform.newTable(),step.steps,step.h,
                            step.startX,step.startY,step.rootX,step.rootY);
                        fail(where+"/rollback: live solver did not propagate the injected failure");
                    } catch(IllegalStateException failure){ if(failure!=injectedB) throw failure; }
                    assertStable(where+"/rollback/frozen",a,snapshotA);
                    assertStable(where+"/rollback/live",b,snapshotB);
                    compareBodies(where+"/rollback/failed-tick",a,b,JAVA_BODY_ALL);
                    continue;
                }
                KahluaTable groupA=platform.newTable(),groupB=platform.newTable();
                double totalA,totalB;
                if(backendSwitch(scenario,tick)){
                    OLD_JAVA.release(stateA);
                    NEW_JAVA.release(stateB);
                    totalA=OLD_JAVA.legacy(stateA,new SolverEnvironment(javaWorld(scenario,tick)),groupA,
                        step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
                    totalB=NEW_JAVA.legacy(stateB,new SolverEnvironment(javaWorld(scenario,tick)),groupB,
                        step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
                } else {
                    totalA=OLD_JAVA.persistent(stateA,new SolverEnvironment(javaWorld(scenario,tick)),groupA,
                        step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
                    totalB=NEW_JAVA.persistent(stateB,new SolverEnvironment(javaWorld(scenario,tick)),groupB,
                        step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
                }
                String at=where+"/tick="+tick+"/steps="+step.steps;
                compareNumber(at+"/accumulated-load",totalA,totalB);
                compareGroups(at,groupA,groupB,JAVA_GROUP);
                checkResetsConsumed(at,scenario,tick,a,b);
                compareBodies(at,a,b,backendSwitch(scenario,tick)?JAVA_BODY_ALL:JAVA_BODY_TICK);
                if(isObstacleScenario(scenario)&&groupA.rawget("nativeObstruction")!=null) obstructionObserved=true;
                if(base(scenario).equals("unload-replacement")&&num(groupA,"nativeGap",0)>0) gapObserved=true;
            }
            if(isObstacleScenario(scenario)&&!obstructionObserved)
                fail(where+": obstacle never triggered; the scenario would only compare empty behaviour");
            if(base(scenario).equals("unload-replacement")&&!gapObserved)
                fail(where+": unloaded body gap never triggered");
            // release() publishes internal history, velocities and takeup; compare it too.
            OLD_JAVA.release(stateA);
            NEW_JAVA.release(stateB);
            compareBodies(where+"/release",a,b,JAVA_BODY_ALL);
            if(base(scenario).equals("chains")) chainsCheck(where+"/chains",a,fixture.bodies/32);
            System.out.println("oracle1 done scenario="+scenario+" ("+seconds(started)+")");
        }
    }

    /**
     * Identical chains must produce identical behaviour. Positions differ by the chain
     * offset, so only translation-invariant state is compared across chains.
     */
    static double chainsCheck(String where,KahluaTable records,int chains){
        int expected=chains*32;
        if(records.len()!=expected) fail(where+": expected "+expected+" records, got "+records.len());
        String[] invariant={"angle","vx","vy","angularVelocity","taut","blocked","loadMass","loadConnected","takeup","ropeConstraintReady","length"};
        double maxChainError=0;
        for(int chain=1;chain<chains;chain++)
            for(int local=1;local<=32;local++){
                KahluaTable first=record(records,local);
                KahluaTable other=record(records,chain*32+local);
                for(String field:invariant){
                    Object a=first.rawget(field),b=other.rawget(field);
                    double before=maxError;
                    compareValue(where+"/chain="+(chain+1)+"/body="+local+"/"+field,a,b);
                    maxChainError=Math.max(maxChainError,maxError-before);
                }
            }
        return maxChainError;
    }

    // ---------------------------------------------------------------- oracle 2: old Lua vs new Lua

    static void luaVsLua() throws Exception {
        for(String scenario:SCENARIOS){
            if(LUA_SKIP.contains(scenario)) continue;
            Fixture fixture=fixture(scenario);
            KahluaTable a=(KahluaTable)eval("return "+fixture.expr);
            KahluaTable b=(KahluaTable)eval("return "+fixture.expr);
            String where="lua-vs-lua/"+scenario;
            System.out.println("oracle2 scenario="+scenario+" bodies="+fixture.bodies+" ticks="+ticks(scenario));
            long started=System.nanoTime();
            for(int tick=0;tick<ticks(scenario);tick++){
                mutate(scenario,tick,a);
                mutate(scenario,tick,b);
                setLuaObstacles(scenario,tick);
                Plan step=plan(a,scenario,tick);
                context="lua-vs-lua/"+scenario+"/tick="+tick;
                String call=",records,"+step.steps+","+str(step.h)+","+str(step.startX)+","+str(step.startY)
                    +","+str(step.rootX)+","+str(step.rootY)+")";
                env.rawset("records",a);
                KahluaTable resultA=(KahluaTable)eval("return luaSolveWith(GroupBaseline"+call);
                env.rawset("records",b);
                KahluaTable resultB=(KahluaTable)eval("return luaSolveWith(Group"+call);
                String at=where+"/tick="+tick+"/steps="+step.steps;
                compareValue(at+"/accumulated-load",resultA.rawget("total"),resultB.rawget("total"));
                compareGroups(at,(KahluaTable)resultA.rawget("group"),(KahluaTable)resultB.rawget("group"),LUA_GROUP);
                compareBodies(at,a,b,LUA_BODY);
            }
            System.out.println("oracle2 done scenario="+scenario+" ("+seconds(started)+")");
        }
        luaFailureScenario();
    }

    /**
     * Exception contract: a world query failure inside the live/frozen group module must
     * leave the same partial record state behind. Neither module may publish a finished
     * step, and identical inputs must produce identical failure behaviour.
     */
    static void luaFailureScenario() throws Exception {
        KahluaTable a=(KahluaTable)eval("return fixture(4,true,true)");
        KahluaTable b=(KahluaTable)eval("return fixture(4,true,true)");
        for(KahluaTable records:new KahluaTable[]{a,b})
            for(int index=1;index<=4;index++){
                KahluaTable r=record(records,index);
                r.rawset("x",2.5);
                r.rawset("y",.5);
                r.rawset("vx",120.);
                r.rawset("angularVelocity",.2);
            }
        env.rawset("wall",false);
        env.rawset("missing",false);
        env.rawset("solid",false);
        env.rawset("tree",false);
        env.rawset("boom",true);
        String h=str(1./120);
        env.rawset("records",a);
        String failureA=evalFailure("return luaSolveWith(GroupBaseline,records,1,"+h+",4,.5,4,.5)");
        env.rawset("records",b);
        String failureB=evalFailure("return luaSolveWith(Group,records,1,"+h+",4,.5,4,.5)");
        env.rawset("boom",false);
        if(failureA==null) fail("lua-vs-lua/exception: injected world failure was not reached in the frozen module");
        if(failureB==null) fail("lua-vs-lua/exception: injected world failure was not reached in the live module");
        compareValue("lua-vs-lua/exception/message",failureA,failureB);
        compareBodies("lua-vs-lua/exception/partial-state",a,b,LUA_BODY);
        System.out.println("PASS lua exception contract: identical partial state and message ("+failureA+")");
    }

    // ---------------------------------------------------------------- oracle 3: new Java vs new Lua

    static void javaVsLua() throws Exception {
        for(String scenario:SCENARIOS){
            if(JAVA_LUA_SKIP.contains(scenario)) continue;
            Fixture fixture=fixture(scenario);
            KahluaTable javaRecords=(KahluaTable)eval("return "+fixture.expr);
            KahluaTable luaRecords=(KahluaTable)eval("return "+fixture.expr);
            Object state=NEW_JAVA.prepare(javaRecords);
            String where="java-vs-lua/"+scenario;
            System.out.println("oracle3 scenario="+scenario+" bodies="+fixture.bodies+" ticks="+ticks(scenario));
            long started=System.nanoTime();
            boolean obstructionObserved=false,gapObserved=false;
            for(int tick=0;tick<ticks(scenario);tick++){
                if(reprepare(scenario,tick)) NEW_JAVA.release(state);
                mutate(scenario,tick,javaRecords);
                mutate(scenario,tick,luaRecords);
                if(reprepare(scenario,tick)) state=NEW_JAVA.prepare(javaRecords);
                setLuaObstacles(scenario,tick);
                Plan step=plan(javaRecords,scenario,tick);
                context="java-vs-lua/"+scenario+"/tick="+tick;
                KahluaTable group=platform.newTable();
                double total=NEW_JAVA.legacy(state,new SolverEnvironment(javaWorld(scenario,tick)),group,
                    step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
                env.rawset("records",luaRecords);
                KahluaTable result=(KahluaTable)eval("return luaSolveWith(Group,records,"+step.steps+","
                    +str(step.h)+","+str(step.startX)+","+str(step.startY)+","+str(step.rootX)+","+str(step.rootY)+")");
                String at=where+"/tick="+tick+"/steps="+step.steps;
                compareValue(at+"/accumulated-load",total,result.rawget("total"));
                if(fixture.bodies==1){
                    // The legacy single-body Lua path publishes status on the result table.
                    compareValue(at+"/nativeGap",group.rawget("nativeGap"),result.rawget("nativeGap"));
                    compareValue(at+"/nativeObstruction",group.rawget("nativeObstruction"),result.rawget("nativeObstruction"));
                } else {
                    compareSharedGroup(at,group,(KahluaTable)result.rawget("group"),step.steps);
                }
                compareBodies(at,javaRecords,luaRecords,JAVA_LUA_BODY);
                if(isObstacleScenario(scenario)&&group.rawget("nativeObstruction")!=null) obstructionObserved=true;
                if(base(scenario).equals("unload-replacement")&&num(group,"nativeGap",0)>0) gapObserved=true;
            }
            if(isObstacleScenario(scenario)&&!obstructionObserved)
                fail(where+": obstacle never triggered in the java-vs-lua scenario");
            if(base(scenario).equals("unload-replacement")&&!gapObserved)
                fail(where+": unloaded body gap never triggered in the java-vs-lua scenario");
            System.out.println("oracle3 done scenario="+scenario+" ("+seconds(started)+")");
        }
        persistentParity();
    }

    /**
     * Production backend path: persistent Java state across ticks, with a one-tick switch
     * to the Lua backend (release + plain Lua step) and a failed solve that must roll the
     * Java history back to the last committed tick. The shipped Lua implementation is the
     * reference for the persistent record history.
     */
    static void persistentParity() throws Exception {
        KahluaTable javaRecords=(KahluaTable)eval("return fixture(32,true,true)");
        KahluaTable luaRecords=(KahluaTable)eval("return fixture(32,true,true)");
        Object state=NEW_JAVA.prepare(javaRecords);
        SolverEnvironment clear=new SolverEnvironment(clearWorld());
        String where="java-vs-lua/persistent-32";
        int ticks=50;
        for(int tick=0;tick<ticks;tick++){
            mutate("straight-32",tick,javaRecords);
            mutate("straight-32",tick,luaRecords);
            if(tick==20){
                // Reset contract: the native backend resets motion and re-takes up the constraint.
                for(int index=1;index<=javaRecords.len();index++){
                    KahluaTable r=record(javaRecords,index);
                    r.rawset("nativeResetMotion",true);
                    r.rawset("nativeResetConstraint",true);
                }
                for(int index=1;index<=luaRecords.len();index++){
                    KahluaTable r=record(luaRecords,index);
                    r.rawset("vx",0.);
                    r.rawset("vy",0.);
                    r.rawset("angularVelocity",0.);
                    r.rawset("ropeConstraintReady",null);
                }
            }
            Plan step=plan(javaRecords,"straight-32",tick);
            env.rawset("wall",false);
            env.rawset("missing",false);
            env.rawset("solid",false);
            env.rawset("tree",false);
            String at=where+"/tick="+tick+"/steps="+step.steps;
            context="java-vs-lua/persistent-32/tick="+tick;
            if(tick==10){
                // Backend switch to Lua for exactly one tick. Both record sets must be
                // aligned before the reference tick is evaluated.
                NEW_JAVA.release(state);
                compareBodies(at+"/released-before-switch",javaRecords,luaRecords,PERSISTENT_ALIGNED);
                env.rawset("records",javaRecords);
                KahluaTable switched=(KahluaTable)eval("return luaSolveWith(Group,records,"+step.steps+","
                    +str(step.h)+","+str(step.startX)+","+str(step.startY)+","+str(step.rootX)+","+str(step.rootY)+")");
                env.rawset("records",luaRecords);
                KahluaTable reference=(KahluaTable)eval("return luaSolveWith(Group,records,"+step.steps+","
                    +str(step.h)+","+str(step.startX)+","+str(step.startY)+","+str(step.rootX)+","+str(step.rootY)+")");
                compareValue(at+"/switch-load",switched.rawget("total"),reference.rawget("total"));
                compareSharedGroup(at+"/switch",(KahluaTable)switched.rawget("group"),(KahluaTable)reference.rawget("group"),step.steps);
                compareBodies(at+"/switch",javaRecords,luaRecords,PERSISTENT_ALIGNED);
                continue;
            }
            env.rawset("records",luaRecords);
            KahluaTable reference=(KahluaTable)eval("return luaSolveWith(Group,records,"+step.steps+","
                +str(step.h)+","+str(step.startX)+","+str(step.startY)+","+str(step.rootX)+","+str(step.rootY)+")");
            KahluaTable group=platform.newTable();
            double total=NEW_JAVA.persistent(state,clear,group,step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
            compareValue(at+"/accumulated-load",total,reference.rawget("total"));
            compareSharedGroup(at,group,(KahluaTable)reference.rawget("group"),step.steps);
            compareBodies(at,javaRecords,luaRecords,PERSISTENT_BODY);
            if(tick==20){
                for(int index=1;index<=javaRecords.len();index++){
                    KahluaTable r=record(javaRecords,index);
                    if(r.rawget("nativeResetMotion")!=null||r.rawget("nativeResetConstraint")!=null)
                        fail(at+"/body="+index+": reset flag was not consumed");
                }
            }
        }
        NEW_JAVA.release(state);
        compareBodies(where+"/release",javaRecords,luaRecords,PERSISTENT_ALIGNED);
        // Exception rollback: the failed tick must leave the record history of the previous tick.
        Map<Integer,Object[]> snapshot=snapshot(javaRecords,JAVA_SNAPSHOT);
        IllegalStateException injected=new IllegalStateException("injected solver world read failure");
        try {
            NEW_JAVA.persistent(state,failingEnvironment(injected),platform.newTable(),2,1./120,
                num(record(javaRecords,1),"ax",0),num(record(javaRecords,1),"ay",0),
                num(record(javaRecords,1),"ax",0)+.01,num(record(javaRecords,1),"ay",0));
            fail(where+"/rollback: live solver did not propagate the injected failure");
        } catch(IllegalStateException failure){ if(failure!=injected) throw failure; }
        assertStable(where+"/rollback",javaRecords,snapshot);
        compareBodies(where+"/rollback/released",javaRecords,luaRecords,PERSISTENT_ALIGNED);
        for(int tick=ticks;tick<ticks+10;tick++){
            mutate("straight-32",tick,javaRecords);
            mutate("straight-32",tick,luaRecords);
            Plan step=plan(javaRecords,"straight-32",tick);
            env.rawset("records",luaRecords);
            KahluaTable reference=(KahluaTable)eval("return luaSolveWith(Group,records,"+step.steps+","
                +str(step.h)+","+str(step.startX)+","+str(step.startY)+","+str(step.rootX)+","+str(step.rootY)+")");
            KahluaTable group=platform.newTable();
            double total=NEW_JAVA.persistent(state,clear,group,step.steps,step.h,step.startX,step.startY,step.rootX,step.rootY);
            String at=where+"/recovery-tick="+tick;
            compareValue(at+"/accumulated-load",total,reference.rawget("total"));
            compareSharedGroup(at,group,(KahluaTable)reference.rawget("group"),step.steps);
            compareBodies(at,javaRecords,luaRecords,PERSISTENT_BODY);
        }
        NEW_JAVA.release(state);
        compareBodies(where+"/final-release",javaRecords,luaRecords,PERSISTENT_ALIGNED);
        System.out.println("PASS persistent java-vs-lua: 60 persistent ticks, Lua backend switch, reset contract, rollback");
    }

    /**
     * Controlled-scaling evidence for optimisation stages: one, two and four identical
     * 32-body chains under exactly the same input, timed on the live native backend.
     * Also proves that identical chains stay bit-identical in translation-invariant state.
     */
    static void scalingEvidence() throws Exception {
        int chainCounts[]={1,2,4};
        int ticks=60,steps=2;
        double h=1./240;
        String[] names={"chains-1x32","chains-2x32","chains-4x32"};
        for(int index=0;index<names.length;index++){
            String name=names[index];
            KahluaTable records=(KahluaTable)eval("return "+fixture(name).expr);
            TowingSolver.State state=TowingSolver.prepare(records);
            SolverEnvironment environment=new SolverEnvironment(clearWorld());
            KahluaTable group=platform.newTable();
            long solveNanos=0;
            for(int tick=0;tick<ticks;tick++){
                mutate(name,tick,records);
                Plan step=plan(records,name,tick);
                long begin=System.nanoTime();
                TowingSolver.solvePersistent(state,environment,group,steps,h,step.startX,step.startY,step.rootX,step.rootY);
                solveNanos+=System.nanoTime()-begin;
            }
            TowingSolver.release(state);
            double maxChainError=chainsCheck("controlled-scaling/"+name,records,chainCounts[index]);
            double solveMillis=solveNanos/1e6;
            double perBodyPerTickMicros=solveNanos/1e3/(ticks*(double)fixture(name).bodies);
            System.out.println(String.format(Locale.ROOT,
                "SCALING chains=%d bodies=%d ticks=%d stepsPerTick=%d solveMs=%.3f perBodyPerTickUs=%.3f maxCrossChainError=%s",
                chainCounts[index],fixture(name).bodies,ticks,steps,solveMillis,perBodyPerTickMicros,
                Double.toString(maxChainError)));
            if(!(maxChainError<TOLERANCE))
                fail("controlled scaling: identical chains diverged by "+maxChainError+" for "+name);
        }
    }

    // ---------------------------------------------------------------- file / class helpers

    static String[] concat(String[] first,String[] second){
        String[] result=new String[first.length+second.length];
        System.arraycopy(first,0,result,0,first.length);
        System.arraycopy(second,0,result,first.length,second.length);
        return result;
    }

    static byte[] resource(String name) throws IOException {
        try(InputStream in=ValidateSolverEquivalence.class.getClassLoader().getResourceAsStream(name)){
            if(in==null) throw new AssertionError("compiled class resource missing from validator classpath: "+name);
            return readAll(in);
        }
    }

    static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        byte[] buffer=new byte[16384];
        for(int read;(read=in.read(buffer))>=0;) out.write(buffer,0,read);
        return out.toByteArray();
    }

    static String sha256(Path path) throws Exception {return sha256(Files.readAllBytes(path));}

    static String sha256(byte[] data) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        byte[] hash=digest.digest(data);
        StringBuilder text=new StringBuilder(hash.length*2);
        for(byte value:hash) text.append(String.format(Locale.ROOT,"%02X",value));
        return text.toString();
    }
}
