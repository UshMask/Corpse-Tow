package cvpbench;

import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.iso.IsoWorld;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.vehicles.BaseVehicle;

/** Test-profile only. No OS input injection or server control. */
@LuaClass(name="CVPBenchmarkNative")
public final class BenchmarkNative {
    private static long ownerCheckAt;
    private static boolean ownerLost;
    public static boolean benchmarkOwnerLost() {
        long pid=Long.getLong("pztest.ownerPid",0L);
        if(pid==0) return false;
        long now=System.nanoTime();
        if(ownerLost || now-ownerCheckAt<1_000_000_000L) return ownerLost;
        ownerCheckAt=now;
        ownerLost=!ownerAlive(pid,Long.getLong("pztest.ownerStart",-1L));
        return ownerLost;
    }
    public static boolean ownerAlive(long pid,long started) {
        return ProcessHandle.of(pid).filter(ProcessHandle::isAlive)
            .flatMap(p->p.info().startInstant()).map(t->Math.abs(t.toEpochMilli()-started)<10).orElse(false);
    }
    // Initialized only by diagnostic profiling, never by ordinary FPS runs.
    private static final class CpuClock {
        static final java.lang.management.ThreadMXBean bean=java.lang.management.ManagementFactory.getThreadMXBean();
    }
    public static double cpuNanos() {
        return CpuClock.bean.isCurrentThreadCpuTimeSupported()?CpuClock.bean.getCurrentThreadCpuTime():-1;
    }
    private static final java.util.List<byte[]> fixtureBodies=new java.util.ArrayList<>();
    private static byte[] fixtureVehicle;
    private static byte[] canonicalVehicle;
    private static final java.util.List<byte[]> canonicalBodies=new java.util.ArrayList<>();
    private static BaseVehicle liveVehicle;
    private static byte[] playerVisual;
    private static final java.util.List<zombie.iso.objects.IsoDeadBody> liveBodies=new java.util.ArrayList<>();
    private static void fixtureGuard() {
        if(GameClient.client || GameServer.server || !"PZT_VehicleLab".equals(IsoWorld.instance.getWorld())
            || !"PZT_ProvingGround".equals(IsoWorld.instance.getMap()))
            throw new IllegalStateException("isolated proving ground required");
    }
    private static byte[] pack(zombie.iso.IsoObject object) throws java.io.IOException {
        var b=java.nio.ByteBuffer.allocate(4*1024*1024);
        object.save(b,false);
        return java.util.Arrays.copyOf(b.array(),b.position());
    }
    private static zombie.iso.IsoObject unpack(byte[] data) throws java.io.IOException {
        var b=java.nio.ByteBuffer.wrap(data);
        var object=zombie.iso.IsoObject.factoryFromFileInput(IsoWorld.instance.currentCell,b);
        if(object==null) throw new IllegalStateException("fixture cannot deserialize");
        object.load(b,IsoWorld.getWorldVersion(),false);
        if(b.hasRemaining()) throw new IllegalStateException("fixture format mismatch");
        // Vehicle loading is two-phase: load() reads parts, setScript() binds
        // their definitions (including whether GasTank is a fluid container).
        if(object instanceof BaseVehicle v) v.setScript();
        return object;
    }
    public static boolean captureSeriesVehicle(BaseVehicle v) throws java.io.IOException {
        fixtureGuard();
        if(fixtureVehicle!=null || v==null) throw new IllegalStateException("series already captured or vehicle missing");
        fixtureVehicle=pack(v);liveVehicle=v;
        var copy=(BaseVehicle)unpack(fixtureVehicle);copy.setSquare(v.getSquare());
        canonicalVehicle=pack(copy);
        if(v.getPartCount()!=copy.getPartCount() || !v.getScriptName().equals(copy.getScriptName()))
            throw new IllegalStateException("vehicle parts changed during load");
        for(int i=0;i<v.getPartCount();i++) {
            var a=v.getPartByIndex(i);var b=copy.getPartByIndex(i);
            if(!a.getId().equals(b.getId()) || a.getCondition()!=b.getCondition()
                || a.getContainerContentAmount()!=b.getContainerContentAmount())
                throw new IllegalStateException("vehicle condition changed during load: "+a.getId());
        }
        logNormalization(fixtureVehicle,canonicalVehicle,"vehicle");
        var buffer=java.nio.ByteBuffer.allocate(65536);
        zombie.characters.IsoPlayer.getInstance().getHumanVisual().save(buffer);
        playerVisual=java.util.Arrays.copyOf(buffer.array(),buffer.position());
        return true;
    }
    public static int captureSeriesBody(zombie.iso.objects.IsoDeadBody body) throws java.io.IOException {
        fixtureGuard();
        if(fixtureVehicle==null || fixtureBodies.size()>=32 || body.isPlayer()
            || !Boolean.TRUE.equals(body.getModData().rawget("PZTFixture")))
            throw new IllegalStateException("owned fixture body required");
        var data=pack(body);var copy=(zombie.iso.objects.IsoDeadBody)unpack(data);copy.setSquare(body.getSquare());
        if(copy.isZombie()!=body.isZombie() || copy.isPlayer()!=body.isPlayer())
            throw new IllegalStateException("body type changed during load");
        var a=java.nio.ByteBuffer.allocate(4*1024*1024);var b=java.nio.ByteBuffer.allocate(4*1024*1024);
        body.getHumanVisual().save(a);copy.getHumanVisual().save(b);
        verifyBytes(java.util.Arrays.copyOf(a.array(),a.position()),java.util.Arrays.copyOf(b.array(),b.position()),"body visual");
        a.clear();b.clear();body.getContainer().save(a);copy.getContainer().save(b);
        verifyBytes(java.util.Arrays.copyOf(a.array(),a.position()),java.util.Arrays.copyOf(b.array(),b.position()),"body inventory");
        var canonical=pack(copy);logNormalization(data,canonical,"body "+(fixtureBodies.size()+1));
        fixtureBodies.add(data);canonicalBodies.add(canonical);liveBodies.add(body);
        return fixtureBodies.size();
    }
    public static boolean ownedSeriesBody(boolean player,Object fixture,Object index,int count) {
        return !player && Boolean.TRUE.equals(fixture) && index instanceof Number
            && ((Number)index).doubleValue()>=1 && ((Number)index).doubleValue()<=count
            && ((Number)index).doubleValue()==((Number)index).intValue();
    }
    public static int clearSeriesObjects() {
        fixtureGuard();
        if(zombie.characters.IsoPlayer.getInstance().getVehicle()!=null)
            throw new IllegalStateException("driver must exit before reset");
        for(var body:liveBodies) if(body.getSquare()!=null && body.getStaticMovingObjectIndex()>=0)
            body.getSquare().removeCorpse(body,false);
        liveBodies.clear();
        if(liveVehicle!=null) { liveVehicle.permanentlyRemove();liveVehicle=null; }
        var chunks=new java.util.HashSet<zombie.iso.IsoChunk>();
        int squares=0;
        // Entire bounded driving corridor, including body tails and splat neighbours.
        for(int x=80;x<=160;x++) for(int y=120;y<=280;y++) {
            var q=IsoWorld.instance.currentCell.getGridSquare(x,y,0);
            if(q==null) continue;
            chunks.add(q.getChunk());squares++;
            for(int i=0;i<q.getObjects().size();i++) q.getObjects().get(i).cleanWallBlood();
            if(!q.getWorldObjects().isEmpty()) throw new IllegalStateException("unexpected dropped objects on track");
            // Streaming can replace the saved fixture's Java instances. Resolve only tagged
            // benchmark bodies here; stale liveBodies references cannot remove those copies.
            for(int i=q.getDeadBodys().size()-1;i>=0;i--) {
                var body=q.getDeadBodys().get(i);
                if(!ownedSeriesBody(body.isPlayer(),body.getModData().rawget("PZTFixture"),
                        body.getModData().rawget("PZTPerfIndex"),fixtureBodies.size()))
                    throw new IllegalStateException("unexpected body on track: x="+body.getX()+" y="+body.getY()+" player="+body.isPlayer()+" zombie="+body.isZombie()+" fixture="+body.getModData().rawget("PZTFixture")+" index="+body.getModData().rawget("PZTPerfIndex"));
                q.removeCorpse(body,false);
            }
        }
        for(var chunk:chunks) {chunk.floorBloodSplats.clear();chunk.floorBloodSplatsFade.clear();}
        if(!IsoWorld.instance.currentCell.getVehicles().isEmpty())
            throw new IllegalStateException("unexpected vehicle remains");
        try {
            var p=zombie.characters.IsoPlayer.getInstance();
            p.getHumanVisual().load(java.nio.ByteBuffer.wrap(playerVisual),IsoWorld.getWorldVersion());
            p.resetModelNextFrame();
        } catch(java.io.IOException e) {throw new IllegalStateException("player visual reset failed",e);}
        return squares;
    }
    public static BaseVehicle restoreSeriesVehicle() throws java.io.IOException {
        fixtureGuard();
        if(liveVehicle!=null || fixtureVehicle==null) throw new IllegalStateException("clear scene first");
        var v=(BaseVehicle)unpack(fixtureVehicle);
        var q=IsoWorld.instance.currentCell.getGridSquare((int)Math.floor(v.getX()),(int)Math.floor(v.getY()),0);
        if(q==null) throw new IllegalStateException("vehicle square unloaded");
        v.setSquare(q);
        verifyBytes(canonicalVehicle,pack(v),"vehicle");
        v.chunk=q.getChunk();v.chunk.vehicles.add(v);
        v.addToWorld();zombie.vehicles.VehiclesDB2.instance.addVehicle(v);
        v.setForceBrake();v.setPhysicsActive(false);liveVehicle=v;
        return v;
    }
    public static zombie.iso.objects.IsoDeadBody restoreSeriesBody(int index) throws java.io.IOException {
        fixtureGuard();
        if(index!=liveBodies.size()+1 || index>fixtureBodies.size()) throw new IllegalArgumentException("ordered fixture index required");
        var body=(zombie.iso.objects.IsoDeadBody)unpack(fixtureBodies.get(index-1));
        var q=IsoWorld.instance.currentCell.getGridSquare((int)Math.floor(body.getX()),(int)Math.floor(body.getY()),0);
        if(q==null) throw new IllegalStateException("body square unloaded");
        body.setSquare(q);
        verifyBytes(canonicalBodies.get(index-1),pack(body),"body "+index);
        q.addCorpse(body,false);liveBodies.add(body);
        return body;
    }
    private static void verifyBytes(byte[] expected,byte[] actual,String name) {
        if(!java.util.Arrays.equals(expected,actual)) throw new IllegalStateException(
            "fixture roundtrip differs: "+name+" at byte "+java.util.Arrays.mismatch(expected,actual));
    }
    private static void logNormalization(byte[] a,byte[] b,String name) {
        int first=java.util.Arrays.mismatch(a,b);
        if(first>=0) {
            int end=Math.min(Math.min(a.length,b.length),first+16);
            System.out.println("[PZTest] load normalization "+name+" bytes="+a.length+"/"+b.length+" first="+first
                +" saved="+java.util.HexFormat.of().formatHex(a,first,end)+" loaded="+java.util.HexFormat.of().formatHex(b,first,end));
        }
    }
    public static double milliseconds() { return System.nanoTime()/1_000_000.0; }
    public static int mapHeaderCount() { return zombie.iso.IsoLot.InfoHeaderNames.size(); }
    public static boolean testControlEnabled() {
        return Boolean.getBoolean("pztest.control") && !GameClient.client && !GameServer.server
            && IsoWorld.instance!=null && "PZT_VehicleLab".equals(IsoWorld.instance.getWorld())
            && "PZT_ProvingGround".equals(IsoWorld.instance.getMap());
    }
    public static boolean gameProfilerEnabled() { return zombie.debug.DebugOptions.instance.gameProfilerEnabled.getValue(); }
    public static void phase(String run,String phase) { JfrPhase.mark(run,phase); StockProfiler.phase(phase); }
    public static void gameProfiler(String command) {
        fixtureGuard();
        switch(command) {
            case "begin" -> StockProfiler.begin();
            case "stop" -> StockProfiler.stop();
            case "restore" -> StockProfiler.restore();
            default -> throw new IllegalArgumentException(command);
        }
    }
    public static void gameProfilerTick() { StockProfiler.tick(); }
    public static boolean gameProfilerActive() { return StockProfiler.active(); }
    public static boolean gameProfilerExpired() { return StockProfiler.expired(); }
    public static int gameProfilerFirst() { return StockProfiler.first(); }
    public static int gameProfilerLast() { return StockProfiler.last(); }
    public static double heapMB() {
        Runtime r=Runtime.getRuntime();return (r.totalMemory()-r.freeMemory())/1048576.0;
    }
    public static void moveVehicle(BaseVehicle vehicle, double dx, double dy) {
        if(GameClient.client || GameServer.server || (!"CVP_QuickTest".equals(IsoWorld.instance.getWorld()) && !"PZT_VehicleLab".equals(IsoWorld.instance.getWorld())))
            throw new IllegalStateException("isolated SP fixture required");
        if(vehicle==null || !Double.isFinite(dx) || !Double.isFinite(dy) || Math.abs(dx)+Math.abs(dy)>1)
            throw new IllegalArgumentException("bounded fixture step required");
        var t=BaseVehicle.allocTransform();
        try {
            vehicle.getWorldTransform(t);t.origin.x+=(float)dx;t.origin.z+=(float)dy;
            vehicle.setWorldTransform(t);
        } finally { BaseVehicle.releaseTransform(t); }
    }
}
