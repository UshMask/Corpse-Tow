package cvpbench;

import zombie.debug.DebugOptions;
import zombie.iso.IsoCamera;

/** Uses stock frame probes; never starts/ends an engine frame itself. */
public final class StockProfiler {
    private static boolean active, previous, stopping;
    private static long deadline;
    private static int first=-1, last=-1;
    private static boolean expired;

    public static void begin() {
        if(active) throw new IllegalStateException("GameProfiler already armed");
        if(!zombie.GameProfiler.isValidThread()) throw new IllegalStateException("GameProfiler requires the game thread");
        previous=DebugOptions.instance.gameProfilerEnabled.getValue();
        first=last=-1; stopping=false; expired=false; active=true;
        deadline=System.nanoTime()+120_000_000_000L;
    }
    public static void phase(String phase) {
        if(!active) return;
        if("sample".equals(phase)) {
            DebugOptions.instance.gameProfilerEnabled.setValue(true);
            first=IsoCamera.frameState.frameCount+1; // First complete enabled frame.
        } else if("brake".equals(phase) || "failed".equals(phase)) stop();
    }
    public static void stop() {
        if(!active || stopping) return;
        if(first<0) { restore(); return; }
        last=IsoCamera.frameState.frameCount; stopping=true;
    }
    public static void tick() {
        if(!active) return;
        // Two observed frame advances cover camera frame-count update ordering.
        if(stopping && IsoCamera.frameState.frameCount-last>=2) restore();
        else if(System.nanoTime()>deadline) { expired=true; restore(); }
    }
    public static void restore() {
        if(!active) return;
        DebugOptions.instance.gameProfilerEnabled.setValue(previous);
        active=false;
    }
    public static boolean active() { return active; }
    public static boolean expired() { return expired; }
    public static int first() { return first; }
    public static int last() { return last; }
}
