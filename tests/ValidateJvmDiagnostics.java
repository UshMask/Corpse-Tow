import java.nio.file.*;
import java.time.Duration;
import jdk.jfr.*;
import cvpbench.BenchmarkNative;

/** Diagnostic helper checks in a standalone JVM, without launching the game. */
public class ValidateJvmDiagnostics {
    static volatile double sink;
    public static void main(String[] args) throws Exception {
        var config=Configuration.create(Path.of(args[0]));
        if(!"0 ms".equals(config.getSettings().get("jdk.Compilation#threshold")))
            throw new AssertionError("short compilations hidden");
        if(!"1 s".equals(config.getSettings().get("jdk.ThreadCPULoad#period")))
            throw new AssertionError("thread CPU period");
        try(var recording=new Recording(config)) {
            recording.start();
            double before=BenchmarkNative.cpuNanos();
            for(int i=1;i<1000000;i++) sink+=Math.sqrt(i);
            double after=BenchmarkNative.cpuNanos();
            if(before>=0 && after<before) throw new AssertionError("CPU clock went backwards");
            if(before<0 && after!=-1) throw new AssertionError("unsupported CPU sentinel");
            Thread.sleep(1100);
            recording.stop();recording.dump(Path.of(args[1]));
        }
        System.out.println("PASS real JFR configuration, CPU clock and recording; no game launched");
    }
}
