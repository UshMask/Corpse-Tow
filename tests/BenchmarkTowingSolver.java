package cvpworld;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.vm.*;

/**
 * Reproducible JVM benchmark and old-vs-new equivalence check for the native
 * towing solver. Run through tools/solver_bench.py, which compiles the current
 * CorpseProxyLab/source tree plus a renamed copy of the frozen baseline
 * (tests/fixtures/solver_baseline/TowingSolver.java -> TowingSolverBaseline)
 * and starts this class in the real game JVM.
 *
 * The scenario matrix and inputs intentionally mirror the scenario loop of
 * tests/ValidateTowingSolver.java (same fixtures, dt pattern, source motion,
 * world obstacles, spread inputs, failure injection) so this benchmark keeps
 * measuring the behaviour the parity validator covers.
 *
 * Timed region: only the solver calls. Fixture construction, Kahlua record
 * updates and checksum walking of the published records are excluded.
 * Checksums are FNV-1a 64 over the IEEE bit patterns of the accumulated load,
 * the published group physics fields and the published body fields per tick.
 * A failing checksum/bit comparison means the optimized solver is no longer
 * equivalent to the frozen baseline.
 */
public final class BenchmarkTowingSolver {
    static final int TICKS=180;
    static final String[] NAMES={
        "single-rope",
        "single-chain-gear",
        "single-rope-wall",
        "single-chain-tree",
        "single-rope-missing-cell",
        "single-chain-solid",
        "chain32-straight",
        "individual32-wall",
        "chain32-weave",
        "individual32-sinusoid",
        "chain32-jump-gap",
        "individual32-failed-body"};
    static final String[] BODY_FIELDS={
        "x","y","angle","vx","vy","angularVelocity","ax","ay","takeup","taut","blocked",
        "ropeBlocked","loadMass","loadConnected","pushX","pushY","spreadRemaining"};
    static final String[] GROUP_FIELDS={
        "nativeGap","nativeObstruction","nativeUnconverged","nativeFallback",
        "solverResidual","solverIterations","recoverySteps"};
    static final String[] COUNTER_FIELDS={
        "solverSubsteps","solverConstraintCalls","solverIterationsTotal",
        "solverSearchEntries","solverFallbacks","solverLimitHits"};
    static final long FNV_OFFSET=0xcbf29ce484222325L,FNV_PRIME=0x100000001b3L,PRESENT=0x9e3779b97f4a7c15L;

    static KahluaThread thread;static KahluaTable env;static J2SEPlatform platform;

    static final class ScenarioResult {
        int index,bodies,ticks,requestedSteps,bitDiffs;double maxAbsError;
        double[] baselineMs,currentMs;long baselineChecksum,currentChecksum;
        long counterSubsteps,counterIterations,counterCalls,counterSearchEntries,counterLimitHits,counterFallbacks;
        boolean countersPresent,countersChecksumMatch;String countersBackend="missing";
        String name(){return NAMES[index];}
        double baselineMin(){return min(baselineMs);}
        double currentMin(){return min(currentMs);}
        double speedup(){double b=baselineMin(),c=currentMin();return c>0?b/c:0;}
    }

    public static void main(String[] args) throws Exception {
        int warmup=1,repeats=3;String jsonPath=null;int[] only=null;
        for(int i=0;i<args.length;i++) {
            switch(args[i]) {
                case "--warmup" -> warmup=Integer.parseInt(args[++i]);
                case "--repeats" -> repeats=Integer.parseInt(args[++i]);
                case "--json" -> jsonPath=args[++i];
                case "--scenarios" -> {
                    String[] parts=args[++i].split(",");only=new int[parts.length];
                    for(int k=0;k<parts.length;k++)only[k]=Integer.parseInt(parts[k].trim());
                }
                default -> throw new IllegalArgumentException("unknown argument: "+args[i]);
            }
        }
        if(warmup<0||repeats<1)throw new IllegalArgumentException("warmup must be >=0 and repeats >=1");
        setup();
        String persistentBackend=persistentBackendProbe();
        List<ScenarioResult> results=new ArrayList<>();
        for(int s=0;s<NAMES.length;s++) {
            if(only!=null&&!contains(only,s))continue;
            results.add(measure(s,warmup,repeats));
        }
        for(ScenarioResult r:results)printResult(r);
        boolean pass=true;
        for(ScenarioResult r:results) {
            if(r.bitDiffs!=0||r.maxAbsError!=0.0||r.baselineChecksum!=r.currentChecksum
                ||!r.countersPresent||!r.countersChecksumMatch||r.currentMin()<=0)pass=false;
        }
        double baselineTotal=0,currentTotal=0;
        for(ScenarioResult r:results){baselineTotal+=r.baselineMin();currentTotal+=r.currentMin();}
        System.out.println(String.format(Locale.ROOT,
            "BENCH totals scenarios=%d baseline_min_ms=%.3f current_min_ms=%.3f speedup=%.3f persistent_backend=%s",
            results.size(),baselineTotal,currentTotal,currentTotal>0?baselineTotal/currentTotal:0,persistentBackend));
        String json=toJson(results,warmup,repeats,persistentBackend,pass);
        if(jsonPath!=null)Files.writeString(Path.of(jsonPath),json,StandardCharsets.UTF_8);
        System.out.println("BENCH "+(pass?"PASS":"FAIL"));
        if(!pass)System.exit(1);
    }

    static void setup() throws Exception {
        platform=J2SEPlatform.getInstance();env=platform.newTable();
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
        eval("""
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
            """);
    }
    static Object eval(String code) throws Exception {
        Object[] result=thread.pcall(LuaCompiler.loadstring(code,"solver-bench",env),new Object[0]);
        if(!Boolean.TRUE.equals(result[0]))throw new AssertionError(Arrays.toString(result));
        return result.length>1?result[1]:null;
    }
    static boolean contains(int[] values,int value){for(int v:values)if(v==value)return true;return false;}
    static int count(int scenario){return scenario<6?1:32;}
    static boolean chain(int scenario){return scenario%2==0;}
    static boolean elastic(int scenario){return scenario%3!=0;}

    /** Same inputs as the ValidateTowingSolver scenario loop. */
    static final class Inputs {
        final double dt,rx,ry,h;final int steps;
        Inputs(int scenario,int tick) {
            dt=tick==40?.5:new double[]{1./30,1./60,1./144,1./500,.1}[tick%5];
            steps=Math.max(1,(int)Math.ceil(dt*120-1e-9));h=dt/steps;
            double x=1+tick*.02,y=.5+(scenario>=6?Math.sin(tick*.04):0);
            if(scenario==9)x=1+Math.sin(tick*.04)*3;
            if(scenario==10&&tick>70)x+=200;
            rx=x;ry=y;
        }
    }
    static void applyInputs(KahluaTable records,int scenario,int tick,double rx,double ry) {
        int count=count(scenario);
        for(int i=1;i<=count;i++) {
            var b=(KahluaTable)records.rawget(i);var p=TowingSolver.table(b,"sourceSample");
            p.rawset("x",rx);p.rawset("y",ry);
            if(scenario==11&&tick==80)b.rawset("failed",true);
            if(count==1) {
                b.rawset("spreadSpeed",tick>=30&&tick<140?.2:0.);
                b.rawset("spreadRemaining",tick%3==2?null:Double.valueOf(tick%3==0?.001:0.));
                b.rawset("spreadOffset",tick%2==0?Double.valueOf(.1):null);b.rawset("spreadScale",.65);
                b.rawset("spreadPush",.6);b.rawset("spreadNX",Math.sin(tick*.01));b.rawset("spreadNY",Math.cos(tick*.01));
            }
        }
    }
    static KahluaTable fixture(int scenario) throws Exception {
        return (KahluaTable)eval("return fixture("+count(scenario)+","+chain(scenario)+","+elastic(scenario)+")");
    }
    static SolverEnvironment.World world(int scenario) {
        final boolean wall=scenario==2||scenario==7,tree=scenario==3,missing=scenario==4,solid=scenario==5;
        return new SolverEnvironment.World() {
            public int flags(int x,int y,int z){return (missing&&x==3?1:0)|(solid&&x==3?2:0)|(tree&&x==3&&y==0?4:0);}
            public boolean blocked(int x,int y,int z,int bx,int by){return wall&&((x<3)!=(bx<3));}
        };
    }
    static int requestedSteps(int scenario) {
        int total=0;
        for(int tick=0;tick<TICKS;tick++){Inputs in=new Inputs(scenario,tick);total+=in.steps;}
        return total;
    }
    static double seedX(KahluaTable records,double fallback){return TowingSolver.n((KahluaTable)records.rawget(1),"ax",fallback);}
    static double seedY(KahluaTable records,double fallback){return TowingSolver.n((KahluaTable)records.rawget(1),"ay",fallback);}

    static ScenarioResult measure(int scenario,int warmup,int repeats) throws Exception {
        ScenarioResult r=new ScenarioResult();
        r.index=scenario;r.bodies=count(scenario);r.ticks=TICKS;r.requestedSteps=requestedSteps(scenario);
        r.baselineMs=new double[repeats];r.currentMs=new double[repeats];
        for(int w=0;w<warmup;w++){pass(scenario,true,false);pass(scenario,false,false);}
        for(int rep=0;rep<repeats;rep++) {
            r.baselineMs[rep]=pass(scenario,true,false)/1e6;
            r.currentMs[rep]=pass(scenario,false,false)/1e6;
        }
        comparePass(scenario,r);
        countersPass(scenario,r);
        return r;
    }
    /** One solver pass; returns only the accumulated solver-call nanoseconds. */
    static long pass(int scenario,boolean baseline,boolean counters) throws Exception {
        SolverEnvironment.World world=world(scenario);
        KahluaTable records=fixture(scenario);
        Object state=baseline?TowingSolverBaseline.prepare(records):TowingSolver.prepare(records);
        KahluaTable group=platform.newTable();
        if(counters)group.rawset("solverCounters",true);
        long nanos=0;
        for(int tick=0;tick<TICKS;tick++) {
            Inputs in=new Inputs(scenario,tick);
            applyInputs(records,scenario,tick,in.rx,in.ry);
            double sx=seedX(records,in.rx),sy=seedY(records,in.ry);
            long a=System.nanoTime();
            if(baseline)TowingSolverBaseline.solve((TowingSolverBaseline.State)state,new SolverEnvironment(world),group,in.steps,in.h,sx,sy,in.rx,in.ry);
            else TowingSolver.solve((TowingSolver.State)state,new SolverEnvironment(world),group,in.steps,in.h,sx,sy,in.rx,in.ry);
            nanos+=System.nanoTime()-a;
        }
        return nanos;
    }
    /** Lock-step old/new pass: checksums, bit differences and max absolute error. */
    static void comparePass(int scenario,ScenarioResult r) throws Exception {
        SolverEnvironment.World world=world(scenario);
        int count=count(scenario);
        KahluaTable oldRecords=fixture(scenario),newRecords=fixture(scenario);
        var oldState=TowingSolverBaseline.prepare(oldRecords);var newState=TowingSolver.prepare(newRecords);
        KahluaTable oldGroup=platform.newTable(),newGroup=platform.newTable();
        long oldHash=FNV_OFFSET,newHash=FNV_OFFSET;
        for(int tick=0;tick<TICKS;tick++) {
            Inputs in=new Inputs(scenario,tick);
            applyInputs(oldRecords,scenario,tick,in.rx,in.ry);
            applyInputs(newRecords,scenario,tick,in.rx,in.ry);
            double sxOld=seedX(oldRecords,in.rx),syOld=seedY(oldRecords,in.ry);
            double sxNew=seedX(newRecords,in.rx),syNew=seedY(newRecords,in.ry);
            if(Double.doubleToLongBits(sxOld)!=Double.doubleToLongBits(sxNew)
                ||Double.doubleToLongBits(syOld)!=Double.doubleToLongBits(syNew))
                throw new AssertionError("seed mismatch scenario="+scenario+" tick="+tick);
            double totalOld=TowingSolverBaseline.solve(oldState,new SolverEnvironment(world),oldGroup,in.steps,in.h,sxOld,syOld,in.rx,in.ry);
            double totalNew=TowingSolver.solve(newState,new SolverEnvironment(world),newGroup,in.steps,in.h,sxNew,syNew,in.rx,in.ry);
            r.maxAbsError=Math.max(r.maxAbsError,Math.abs(totalOld-totalNew));
            if(Double.doubleToLongBits(totalOld)!=Double.doubleToLongBits(totalNew))r.bitDiffs++;
            oldHash=mixDouble(oldHash,totalOld);newHash=mixDouble(newHash,totalNew);
            for(String field:GROUP_FIELDS) {
                oldHash=mixObject(oldHash,oldGroup.rawget(field));
                newHash=mixObject(newHash,newGroup.rawget(field));
                compareObject(oldGroup,newGroup,field,scenario,tick,-1,r);
            }
            for(int i=1;i<=count;i++) {
                var a=(KahluaTable)oldRecords.rawget(i);var b=(KahluaTable)newRecords.rawget(i);
                for(String field:BODY_FIELDS) {
                    oldHash=mixObject(oldHash,a.rawget(field));
                    newHash=mixObject(newHash,b.rawget(field));
                    compareObject(a,b,field,scenario,tick,i,r);
                }
            }
        }
        r.baselineChecksum=oldHash;r.currentChecksum=newHash;
    }
    /** Current solver with counters enabled; also proves counters do not change output. */
    static void countersPass(int scenario,ScenarioResult r) throws Exception {
        SolverEnvironment.World world=world(scenario);
        int count=count(scenario);
        KahluaTable records=fixture(scenario);
        var state=TowingSolver.prepare(records);
        KahluaTable group=platform.newTable();group.rawset("solverCounters",true);
        long hash=FNV_OFFSET;
        for(int tick=0;tick<TICKS;tick++) {
            Inputs in=new Inputs(scenario,tick);
            applyInputs(records,scenario,tick,in.rx,in.ry);
            double sx=seedX(records,in.rx),sy=seedY(records,in.ry);
            double total=TowingSolver.solve(state,new SolverEnvironment(world),group,in.steps,in.h,sx,sy,in.rx,in.ry);
            hash=mixDouble(hash,total);
            for(String field:GROUP_FIELDS)hash=mixObject(hash,group.rawget(field));
            for(int i=1;i<=count;i++) {
                var b=(KahluaTable)records.rawget(i);
                for(String field:BODY_FIELDS)hash=mixObject(hash,b.rawget(field));
            }
            Object backend=group.rawget("solverBackend");
            if(backend instanceof String)r.countersBackend=(String)backend;
            r.counterSubsteps+=(long)TowingSolver.n(group,"solverSubsteps",-1);
            r.counterIterations+=(long)TowingSolver.n(group,"solverIterationsTotal",-1);
            r.counterCalls+=(long)TowingSolver.n(group,"solverConstraintCalls",-1);
            r.counterSearchEntries+=(long)TowingSolver.n(group,"solverSearchEntries",-1);
            r.counterLimitHits+=(long)TowingSolver.n(group,"solverLimitHits",-1);
            r.counterFallbacks+=(long)TowingSolver.n(group,"solverFallbacks",-1);
        }
        r.countersPresent=r.counterCalls>=0&&r.counterSubsteps>=0&&r.counterIterations>=0
            &&r.counterSearchEntries>=0&&r.counterLimitHits>=0&&r.counterFallbacks>=0;
        r.countersChecksumMatch=hash==r.currentChecksum;
    }
    static String persistentBackendProbe() throws Exception {
        SolverEnvironment.World world=world(0);
        KahluaTable records=fixture(0);
        var state=TowingSolver.prepare(records);
        KahluaTable group=platform.newTable();group.rawset("solverCounters",true);
        try {
            TowingSolver.solvePersistent(state,new SolverEnvironment(world),group,1,1./120,.3,.5,.3,.5);
        } finally {
            TowingSolver.release(state);
        }
        Object backend=group.rawget("solverBackend");
        return backend==null?"missing":backend.toString();
    }

    static void compareObject(KahluaTable a,KahluaTable b,String field,int scenario,int tick,int body,ScenarioResult r) {
        Object x=a.rawget(field),y=b.rawget(field);
        if(x instanceof Number&&y instanceof Number) {
            double dx=((Number)x).doubleValue(),dy=((Number)y).doubleValue();
            r.maxAbsError=Math.max(r.maxAbsError,Math.abs(dx-dy));
            if(Double.doubleToLongBits(dx)!=Double.doubleToLongBits(dy))r.bitDiffs++;
        } else if(!Objects.equals(x,y)&&!(x==null&&Boolean.FALSE.equals(y))&&!(y==null&&Boolean.FALSE.equals(x))) {
            r.bitDiffs++;
        }
    }
    static long mixDouble(long hash,double value){return mix(hash,Double.doubleToLongBits(value));}
    static long mixObject(long hash,Object value) {
        if(value==null)return mix(hash,PRESENT);
        if(value instanceof Number)return mixDouble(hash,((Number)value).doubleValue());
        if(value instanceof Boolean)return mix(hash,(Boolean)value?0x9e3779b97f4a7c15L:0x7f4a7c159e3779b9L);
        if(value instanceof String)return mix(hash,((String)value).hashCode());
        return mix(hash,value.toString().hashCode());
    }
    static long mix(long hash,long value){return (hash^value)*FNV_PRIME;}
    static double min(double[] values){double m=Double.POSITIVE_INFINITY;for(double v:values)m=Math.min(m,v);return m;}

    static void printResult(ScenarioResult r) {
        System.out.println(String.format(Locale.ROOT,
            "BENCH scenario=%d name=%s bodies=%d ticks=%d requested_steps=%d baseline_ms=%s current_ms=%s speedup=%.3f "
                +"baseline_checksum=0x%016x current_checksum=0x%016x bit_diffs=%d max_abs_error=%s "
                +"counters_substeps=%d counters_iterations=%d counters_calls=%d counters_search_entries=%d "
                +"counters_limit_hits=%d counters_fallbacks=%d counters_backend=%s counters_checksum_match=%s",
            r.index,r.name(),r.bodies,r.ticks,r.requestedSteps,Arrays.toString(r.baselineMs),Arrays.toString(r.currentMs),
            r.speedup(),r.baselineChecksum,r.currentChecksum,r.bitDiffs,Double.toString(r.maxAbsError),
            r.counterSubsteps,r.counterIterations,r.counterCalls,r.counterSearchEntries,r.counterLimitHits,
            r.counterFallbacks,r.countersBackend,r.countersChecksumMatch));
    }

    static String toJson(List<ScenarioResult> results,int warmup,int repeats,String persistentBackend,boolean pass) {
        StringBuilder sb=new StringBuilder(8192);
        sb.append('{');
        field(sb,"harness",true,"BenchmarkTowingSolver");
        raw(sb,"schema",false,"1");
        field(sb,"javaVersion",false,System.getProperty("java.version",""));
        field(sb,"javaRuntime",false,System.getProperty("java.runtime.version",""));
        field(sb,"os",false,System.getProperty("os.name",""));
        raw(sb,"warmup",false,Integer.toString(warmup));
        raw(sb,"repeats",false,Integer.toString(repeats));
        field(sb,"currentVersion",false,TowingSolver.version());
        field(sb,"baselineVersion",false,TowingSolverBaseline.version());
        field(sb,"checksumAlgorithm",false,"fnv1a64 over IEEE bits of accumulated load, group physics fields and published body fields per tick");
        sb.append(",\"backend\":{");
        field(sb,"currentTimed",true,"java-nonpersistent");
        field(sb,"currentPersistent",false,persistentBackend);
        field(sb,"baseline",false,"java");
        sb.append('}');
        sb.append(",\"scenarios\":[");
        for(int i=0;i<results.size();i++) {
            if(i>0)sb.append(',');
            ScenarioResult r=results.get(i);
            sb.append('{');
            raw(sb,"index",true,Integer.toString(r.index));
            field(sb,"name",false,r.name());
            raw(sb,"bodies",false,Integer.toString(r.bodies));
            raw(sb,"ticks",false,Integer.toString(r.ticks));
            raw(sb,"requestedSteps",false,Integer.toString(r.requestedSteps));
            raw(sb,"baselineMs",false,array(r.baselineMs));
            raw(sb,"currentMs",false,array(r.currentMs));
            field(sb,"baselineChecksum",false,String.format("0x%016x",r.baselineChecksum));
            field(sb,"currentChecksum",false,String.format("0x%016x",r.currentChecksum));
            raw(sb,"bitDiffs",false,Integer.toString(r.bitDiffs));
            raw(sb,"maxAbsError",false,Double.toString(r.maxAbsError));
            sb.append(",\"counters\":{");
            raw(sb,"substeps",true,Long.toString(r.counterSubsteps));
            raw(sb,"iterations",false,Long.toString(r.counterIterations));
            raw(sb,"constraintCalls",false,Long.toString(r.counterCalls));
            raw(sb,"searchEntries",false,Long.toString(r.counterSearchEntries));
            raw(sb,"limitHits",false,Long.toString(r.counterLimitHits));
            raw(sb,"fallbacks",false,Long.toString(r.counterFallbacks));
            field(sb,"backend",false,r.countersBackend);
            raw(sb,"checksumMatch",false,Boolean.toString(r.countersChecksumMatch));
            sb.append('}');
            sb.append('}');
        }
        sb.append(']');
        double baselineTotal=0,currentTotal=0;
        for(ScenarioResult r:results){baselineTotal+=r.baselineMin();currentTotal+=r.currentMin();}
        sb.append(",\"totals\":{");
        raw(sb,"baselineMinMs",true,Double.toString(round3(baselineTotal)));
        raw(sb,"currentMinMs",false,Double.toString(round3(currentTotal)));
        raw(sb,"speedup",false,Double.toString(currentTotal>0?round3(baselineTotal/currentTotal):0));
        sb.append('}');
        field(sb,"result",false,pass?"pass":"fail");
        sb.append('}');
        return sb.toString();
    }
    static void raw(StringBuilder sb,String name,boolean first,String value) {
        if(!first)sb.append(',');
        sb.append('"').append(name).append("\":").append(value);
    }    static void field(StringBuilder sb,String name,boolean first,String value) {
        if(!first)sb.append(',');
        sb.append('"').append(name).append("\":\"").append(escape(value)).append('"');
    }
    static String array(double[] values) {
        StringBuilder sb=new StringBuilder("[");
        for(int i=0;i<values.length;i++){if(i>0)sb.append(',');sb.append(Double.toString(round3(values[i])));}
        return sb.append(']').toString();
    }
    static double round3(double v){return Math.round(v*1000.0)/1000.0;}
    static String escape(String value){return value.replace("\\","\\\\").replace("\"","\\\"");}
}
