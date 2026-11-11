package cvpworld;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.vm.*;

/** Test-only API benchmark, not a pure numerical-core or game-frame benchmark.
 * Each pass owns prepared state for its entire sequence and releases in finally.
 * API time includes Body.read, physics/world queries and publication (Body.write).
 * Input table updates, caller seed reads, checksum walks and lifecycle are separate.
 * Counters are disabled. Timer overhead is not subtracted. See runner for JVM forks.
 */
public final class BenchmarkTowingSolver {
    static final String[] NAMES={"single-rope","single-chain-gear","single-rope-wall",
        "single-chain-tree","single-rope-missing-cell","single-chain-solid",
        "chain32-straight","individual32-wall","chain32-weave","individual32-sinusoid",
        "chain32-jump-gap","individual32-failed-body","chain4","individual4","chain8",
        "individual8","four-groups-chain32","idle-no-call"};
    static final String[] BODY_FIELDS={"x","y","angle","vx","vy","angularVelocity","ax","ay",
        "takeup","ropeConstraintReady","taut","blocked","ropeBlocked","loadMass","loadConnected",
        "pushX","pushY","spreadRemaining"};
    static final String[] GROUP_FIELDS={"nativeGap","nativeObstruction","nativeUnconverged",
        "nativeFallback","solverResidual","solverIterations","recoverySteps"};
    static final long FNV_OFFSET=0xcbf29ce484222325L,FNV_PRIME=0x100000001b3L;
    static KahluaThread thread; static KahluaTable env; static J2SEPlatform platform;

    public static void main(String[] args) throws Exception {
        int warmup=2,repeats=4,ticks=6000,warmupTicks=3000,orderOffset=0;
        String jsonPath=null; int[] only=null;
        for(int i=0;i<args.length;i++)switch(args[i]) {
            case "--warmup" -> warmup=Integer.parseInt(args[++i]);
            case "--warmup-ticks" -> warmupTicks=Integer.parseInt(args[++i]);
            case "--ticks" -> ticks=Integer.parseInt(args[++i]);
            case "--repeats" -> repeats=Integer.parseInt(args[++i]);
            case "--order-offset" -> orderOffset=Integer.parseInt(args[++i]);
            case "--json" -> jsonPath=args[++i];
            case "--scenarios" -> only=Arrays.stream(args[++i].split(",")).mapToInt(Integer::parseInt).toArray();
            default -> throw new IllegalArgumentException("unknown argument: "+args[i]);
        }
        if(warmup<0||warmupTicks<1||ticks<1||repeats<1)throw new IllegalArgumentException("invalid run lengths");
        if(only!=null)for(int s:only)if(s<0||s>=NAMES.length)throw new IllegalArgumentException("invalid scenario "+s);
        setup(); List<Object> scenarios=new ArrayList<>(); boolean passed=true;
        for(int s=0;s<NAMES.length;s++) {
            if(only!=null&&!contains(only,s))continue;
            List<Object> modes=new ArrayList<>();
            for(boolean persistent:new boolean[]{false,true}) {
                if(s==17&&persistent)continue; // idle has no API and is not duplicated as a solver result
                for(int w=0;w<warmup;w++) {
                    boolean oldFirst=((w+orderOffset)&1)==0;
                    pass(s,oldFirst,persistent,warmupTicks);pass(s,!oldFirst,persistent,warmupTicks);
                }
                List<Object> pairs=new ArrayList<>();
                for(int rep=0;rep<repeats;rep++) {
                    boolean oldFirst=((rep+orderOffset)&1)==0;
                    Map<String,Object> first=pass(s,oldFirst,persistent,ticks),second=pass(s,!oldFirst,persistent,ticks);
                    Map<String,Object> old=oldFirst?first:second,now=oldFirst?second:first;
                    boolean match=Objects.equals(old.get("checksum"),now.get("checksum"))
                        &&Objects.equals(old.get("releasedChecksum"),now.get("releasedChecksum"));
                    passed&=match;
                    pairs.add(map("replica",rep,"order",oldFirst?"AB":"BA","baseline",old,"current",now,"checksumsMatch",match));
                }
                modes.add(map("api",s==17?"no-call":persistent?"solvePersistent":"solve","pairs",pairs));
            }
            scenarios.add(map("index",s,"name",NAMES[s],"groups",groups(s),"bodiesPerGroup",count(s),"modes",modes));
            System.out.println("BENCH scenario="+s+" name="+NAMES[s]+" complete");
        }
        // Run bridge microdiagnostics only AFTER all primary measurements in
        // this JVM, on different fixtures. Never subtract them from API timings.
        List<Object> bridges=new ArrayList<>();
        for(int s=0;s<NAMES.length-1;s++)if(only==null||contains(only,s)) {
            for(boolean persistent:new boolean[]{false,true}) {
                boolean oldFirst=(orderOffset&1)==0;
                var first=bridge(s,oldFirst,persistent,Math.min(ticks,1000));
                var second=bridge(s,!oldFirst,persistent,Math.min(ticks,1000));
                passed&=Objects.equals(first.get("checksum"),second.get("checksum"));
                bridges.add(map("index",s,"api",persistent?"solvePersistent":"solve",
                    "baseline",oldFirst?first:second,"current",oldFirst?second:first));
            }
        }
        Map<String,Object> result=map("schema",2,"harness","BenchmarkTowingSolver","javaVersion",System.getProperty("java.version"),
            "os",System.getProperty("os.name"),"arch",System.getProperty("os.arch"),
            "availableProcessors",Runtime.getRuntime().availableProcessors(),
            "currentVersion",TowingSolver.version(),"baselineVersion",TowingSolverBaseline.version(),
            "ticks",ticks,"warmup",warmup,"warmupTicks",warmupTicks,"repeats",repeats,"orderOffset",orderOffset,
            "checksumAlgorithm","FNV1a64 over per-tick return, published body/group values; full history again after release",
            "timingContract","API includes sync/read, physics, world queries, publication/write; excludes input updates, seed reads, checksums, prepare/release. No core decomposition. No timer subtraction.",
            "scenarios",scenarios,"bridgeDiagnostics",bridges,
            "bridgeContract","Separate initialized clone fixtures, after all primary measurements; repeated Body.read(mode) and Body.write(mode) only, no physics, no group publication, no input advancement. Not an additive API decomposition; never subtract.",
            "result",passed?"pass":"fail");
        if(jsonPath!=null)Files.writeString(Path.of(jsonPath),json(result),StandardCharsets.UTF_8);
        System.out.println("BENCH "+(passed?"PASS":"FAIL"));if(!passed)System.exit(1);
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
        eval("Geometry=require 'CVP_Geometry'");
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
    static int count(int s){return s==17?0:s<6?1:s==12||s==13?4:s==14||s==15?8:32;}
    static int groups(int s){return s==17?0:s==16?4:1;}
    static boolean chain(int s){return s%2==0;}
    static boolean elastic(int s){return s%3!=0;}
    static final class Inputs {
        final double rx,ry,h;final int steps;
        Inputs(int s,int tick) {
            // Bounded, deterministic long motion, not an ever-increasing root that
            // leaves normal fixtures permanently gap-blocked during long runs.
            double dt=tick%1200==40?.5:new double[]{1./30,1./60,1./144,1./500,.1}[tick%5];
            steps=Math.max(1,(int)Math.ceil(dt*120-1e-9));h=dt/steps;
            double x=1+3*Math.sin(tick*.006),y=.5+(s>=7?Math.sin(tick*.009):0);
            if(s==9)x=1+Math.sin(tick*.012)*3;
            if(s==10&&tick%1200>700)x+=200; // explicit gap/failure scene, not throughput proxy
            rx=x;ry=y;
        }
    }
    static void applyInputs(KahluaTable records,int s,int tick,Inputs in) {
        for(int i=1;i<=count(s);i++) {
            var b=(KahluaTable)records.rawget(i);var p=TowingSolver.table(b,"sourceSample");
            p.rawset("x",in.rx);p.rawset("y",in.ry);
            // The teleport is a gap-rejection control, not a 100 m dragging workload.
            // Teleport interpolation remains far beyond the 4 m cutoff: reject before sweeps.
            if(s==10)b.rawset("maxGapSquared",16.);
            if(s==11)b.rawset("failed",tick%1200>=800?true:null);
            if(count(s)==1) {
                b.rawset("spreadSpeed",tick%180>=30&&tick%180<140?.2:0.);
                b.rawset("spreadRemaining",tick%3==2?null:Double.valueOf(tick%3==0?.001:0.));
                b.rawset("spreadOffset",tick%2==0?Double.valueOf(.1):null);b.rawset("spreadScale",.65);
                b.rawset("spreadPush",.6);b.rawset("spreadNX",Math.sin(tick*.01));b.rawset("spreadNY",Math.cos(tick*.01));
            }
        }
    }
    static SolverEnvironment.World world(int s) {
        final boolean wall=s==2||s==7,tree=s==3,missing=s==4,solid=s==5;
        return new SolverEnvironment.World() {
            public int flags(int x,int y,int z){return (missing&&x==3?1:0)|(solid&&x==3?2:0)|(tree&&x==3&&y==0?4:0);}
            public boolean blocked(int x,int y,int z,int bx,int by){return wall&&((x<3)!=(bx<3));}
        };
    }
    static Map<String,Object> pass(int s,boolean baseline,boolean persistent,int ticks) throws Exception {
        int n=groups(s); KahluaTable[] records=new KahluaTable[n],tables=new KahluaTable[n];
        Object[] states=new Object[n];SolverEnvironment[] environments=new SolverEnvironment[n];
        // Precompute immutable caller inputs outside every timed region.
        Inputs[] inputs=new Inputs[ticks];for(int t=0;t<ticks;t++)inputs[t]=new Inputs(s,t);
        double[] sx=new double[n],sy=new double[n];
        long[] api=new long[ticks],updates=new long[ticks],seeds=new long[ticks],checksums=new long[ticks];
        long prepare=0,release=0,fixture=0,hash=FNV_OFFSET,releasedHash=FNV_OFFSET;
        long sumIterations=0; int gapTicks=0,obstructedTicks=0,unconvergedTicks=0,fallbackTicks=0,nonzeroLoadTicks=0;
        double maxResidual=0,maxLoad=0;
        try {
            for(int g=0;g<n;g++) {
                long a=System.nanoTime();
                records[g]=(KahluaTable)eval("return fixture("+count(s)+","+chain(s)+","+elastic(s)+")");
                tables[g]=platform.newTable();environments[g]=new SolverEnvironment(world(s));fixture+=System.nanoTime()-a;
                a=System.nanoTime();states[g]=baseline?TowingSolverBaseline.prepare(records[g]):TowingSolver.prepare(records[g]);
                prepare+=System.nanoTime()-a;
            }
            for(int t=0;t<ticks;t++) {
                Inputs in=inputs[t];long a=System.nanoTime();
                for(int g=0;g<n;g++)applyInputs(records[g],s,t,in);
                updates[t]=System.nanoTime()-a;a=System.nanoTime();
                for(int g=0;g<n;g++) {
                    var root=(KahluaTable)records[g].rawget(1);
                    sx[g]=TowingSolver.n(root,"ax",in.rx);sy[g]=TowingSolver.n(root,"ay",in.ry);
                }
                seeds[t]=System.nanoTime()-a;
                double load=0;a=System.nanoTime();
                for(int g=0;g<n;g++) {
                    if(baseline) {
                        var state=(TowingSolverBaseline.State)states[g];
                        load+=persistent?TowingSolverBaseline.solvePersistent(state,environments[g],tables[g],in.steps,in.h,sx[g],sy[g],in.rx,in.ry)
                            :TowingSolverBaseline.solve(state,environments[g],tables[g],in.steps,in.h,sx[g],sy[g],in.rx,in.ry);
                    } else {
                        var state=(TowingSolver.State)states[g];
                        load+=persistent?TowingSolver.solvePersistent(state,environments[g],tables[g],in.steps,in.h,sx[g],sy[g],in.rx,in.ry)
                            :TowingSolver.solve(state,environments[g],tables[g],in.steps,in.h,sx[g],sy[g],in.rx,in.ry);
                    }
                }
                api[t]=System.nanoTime()-a;a=System.nanoTime();hash=mixObject(hash,load);
                boolean gap=false,obstructed=false,unconverged=false,fallback=false;
                for(int g=0;g<n;g++) {
                    hash=hashRecords(hash,records[g],tables[g],count(s));
                    // Existing output only: diagnostics do not enable solverCounters
                    // or add instrumentation inside the timed API region.
                    KahluaTable table=tables[g];
                    sumIterations+=(long)TowingSolver.n(table,"solverIterations",0);
                    maxResidual=Math.max(maxResidual,TowingSolver.n(table,"solverResidual",0));
                    gap|=TowingSolver.n(table,"nativeGap",0)>0;
                    obstructed|=table.rawget("nativeObstruction")!=null;
                    unconverged|=Boolean.TRUE.equals(table.rawget("nativeUnconverged"));
                    fallback|=Boolean.TRUE.equals(table.rawget("nativeFallback"));
                }
                if(gap)gapTicks++;if(obstructed)obstructedTicks++;
                if(unconverged)unconvergedTicks++;if(fallback)fallbackTicks++;
                if(load!=0)nonzeroLoadTicks++;maxLoad=Math.max(maxLoad,Math.abs(load));
                checksums[t]=System.nanoTime()-a;
            }
        } finally {
            for(int g=0;g<n;g++)if(states[g]!=null) {
                long a=System.nanoTime();
                if(baseline)TowingSolverBaseline.release((TowingSolverBaseline.State)states[g]);
                else TowingSolver.release((TowingSolver.State)states[g]);
                release+=System.nanoTime()-a;
            }
        }
        for(int g=0;g<n;g++)releasedHash=hashRecords(releasedHash,records[g],tables[g],count(s));
        return map("apiNs",api,"inputUpdateNs",updates,"seedReadNs",seeds,"checksumNs",checksums,
            "fixtureNs",fixture,"prepareNs",prepare,"releaseNs",release,"checksum",String.format("%016x",hash),
            "releasedChecksum",String.format("%016x",releasedHash),"apiCalls",n*ticks,
            "diagnostics",map("sumSolverIterations",sumIterations,"maxResidual",maxResidual,"gapTicks",gapTicks,
                "obstructedTicks",obstructedTicks,"unconvergedTicks",unconvergedTicks,"fallbackTicks",fallbackTicks,
                "nonzeroLoadTicks",nonzeroLoadTicks,"maxAbsLoad",maxLoad));
    }
    static Map<String,Object> bridge(int s,boolean baseline,boolean persistent,int ticks) throws Exception {
        int n=groups(s);Object[] states=new Object[n];
        KahluaTable[] records=new KahluaTable[n],tables=new KahluaTable[n];
        long[] reads=new long[ticks],writes=new long[ticks];long hash=FNV_OFFSET;
        try {
            for(int g=0;g<n;g++) {
                records[g]=(KahluaTable)eval("return fixture("+count(s)+","+chain(s)+","+elastic(s)+")");
                tables[g]=platform.newTable();var environment=new SolverEnvironment(world(s));
                if(baseline) {
                    var state=TowingSolverBaseline.prepare(records[g]);states[g]=state;
                    if(persistent)TowingSolverBaseline.solvePersistent(state,environment,tables[g],1,1./120,1,.5,1,.5);
                    else TowingSolverBaseline.solve(state,environment,tables[g],1,1./120,1,.5,1,.5);
                } else {
                    var state=TowingSolver.prepare(records[g]);states[g]=state;
                    if(persistent)TowingSolver.solvePersistent(state,environment,tables[g],1,1./120,1,.5,1,.5);
                    else TowingSolver.solve(state,environment,tables[g],1,1./120,1,.5,1,.5);
                }
            }
            // Diagnostic-only loop warmup, distinct from primary solver warmup.
            for(int t=-200;t<ticks;t++) {
                long a=System.nanoTime();
                for(Object state:states) {
                    if(baseline)for(var body:((TowingSolverBaseline.State)state).bodies)body.read(persistent);
                    else for(var body:((TowingSolver.State)state).bodies)body.read(persistent);
                }
                long read=System.nanoTime()-a;a=System.nanoTime();
                for(Object state:states) {
                    if(baseline)for(var body:((TowingSolverBaseline.State)state).bodies)body.write(persistent);
                    else for(var body:((TowingSolver.State)state).bodies)body.write(persistent);
                }
                long write=System.nanoTime()-a;if(t>=0){reads[t]=read;writes[t]=write;}
            }
        } finally {
            for(Object state:states)if(state!=null) {
                if(baseline)TowingSolverBaseline.release((TowingSolverBaseline.State)state);
                else TowingSolver.release((TowingSolver.State)state);
            }
        }
        for(int g=0;g<n;g++)hash=hashRecords(hash,records[g],tables[g],count(s));
        return map("bodyReadNs",reads,"bodyPublicationNs",writes,"checksum",String.format("%016x",hash));
    }
    static long hashRecords(long hash,KahluaTable records,KahluaTable group,int count) {
        for(String f:GROUP_FIELDS)hash=mixObject(hash,group.rawget(f));
        for(int i=1;i<=count;i++) {
            var b=(KahluaTable)records.rawget(i);
            for(String f:BODY_FIELDS)hash=mixObject(hash,b.rawget(f));
        }
        return hash;
    }
    static long mixObject(long hash,Object value) {
        long bits=value==null?0x123456789abcdefL:value instanceof Number?Double.doubleToLongBits(((Number)value).doubleValue())
            :value instanceof Boolean?((Boolean)value?1:2):value.toString().hashCode();
        return (hash^bits)*FNV_PRIME;
    }
    static Map<String,Object> map(Object... values) {
        Map<String,Object> m=new LinkedHashMap<>();for(int i=0;i<values.length;i+=2)m.put((String)values[i],values[i+1]);return m;
    }
    static String json(Object value) {
        if(value==null)return "null";
        if(value instanceof String)return "\""+((String)value).replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r").replace("\t","\\t")+"\"";
        if(value instanceof Number||value instanceof Boolean)return value.toString();
        StringJoiner j;
        if(value instanceof Map<?,?>) {
            j=new StringJoiner(",","{","}");for(var e:((Map<?,?>)value).entrySet())j.add(json(e.getKey())+":"+json(e.getValue()));
        } else {
            j=new StringJoiner(",","[","]");
            if(value instanceof long[])for(long x:(long[])value)j.add(Long.toString(x));
            else for(Object x:(Iterable<?>)value)j.add(json(x));
        }
        return j.toString();
    }
}
