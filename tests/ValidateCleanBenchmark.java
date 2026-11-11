import cvpbench.BenchmarkNative;
import zombie.iso.IsoWorld;
import zombie.network.GameClient;
import zombie.network.GameServer;

/** Isolated JVM permission check; never starts a game. */
public class ValidateCleanBenchmark {
    static void check(boolean expected) {
        if(BenchmarkNative.testControlEnabled()!=expected) throw new AssertionError("control permission");
    }
    public static void main(String[] args) throws Exception {
        if(args.length>0) { Thread.sleep(30000);return; }
        var child=new ProcessBuilder(System.getProperty("java.home")+"/bin/java.exe","-cp",
            System.getProperty("java.class.path"),"ValidateCleanBenchmark","child").start();
        try {
            long childStart=child.info().startInstant().orElseThrow().toEpochMilli();
            if(!BenchmarkNative.ownerAlive(child.pid(),childStart)) throw new AssertionError("live child");
            child.destroyForcibly().waitFor();
            if(BenchmarkNative.ownerAlive(child.pid(),childStart)) throw new AssertionError("terminated owner");
        } finally { if(child.isAlive()) child.destroyForcibly().waitFor(); }

        if(!BenchmarkNative.ownedSeriesBody(false,true,32.0,32)
            || BenchmarkNative.ownedSeriesBody(true,true,1.0,32)
            || BenchmarkNative.ownedSeriesBody(false,false,1.0,32)
            || BenchmarkNative.ownedSeriesBody(false,true,33.0,32)
            || BenchmarkNative.ownedSeriesBody(false,true,1.5,32)) throw new AssertionError("fixture cleanup ownership");
        long pid=ProcessHandle.current().pid();
        long start=ProcessHandle.current().info().startInstant().orElseThrow().toEpochMilli();
        if(!BenchmarkNative.ownerAlive(pid,start) || BenchmarkNative.ownerAlive(pid,start-1000)
            || BenchmarkNative.ownerAlive(Long.MAX_VALUE,start)) throw new AssertionError("owner identity");
        zombie.core.random.RandStandard.INSTANCE.init();
        IsoWorld.instance.setWorld("PZT_VehicleLab");IsoWorld.instance.setMap("PZT_ProvingGround");
        System.clearProperty("pztest.control");check(false);
        System.setProperty("pztest.control","true");check(true);
        GameClient.client=true;check(false);GameClient.client=false;
        GameServer.server=true;check(false);GameServer.server=false;
        IsoWorld.instance.setWorld("UserSave");check(false);
        IsoWorld.instance.setWorld("PZT_VehicleLab");IsoWorld.instance.setMap("Muldraugh, KY");check(false);
        System.out.println("PASS clean bridge: explicit opt-in, isolated world/map, SP only");
    }
}
