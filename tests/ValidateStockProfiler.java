import cvpbench.StockProfiler;
import zombie.GameProfiler;
import zombie.ZomboidFileSystem;
import zombie.debug.DebugOptions;
import zombie.iso.IsoCamera;
import java.nio.file.*;

/** Real engine recorder in an isolated JVM; no game, Bullet or display startup. */
public class ValidateStockProfiler {
    static void check(boolean ok,String why) { if(!ok) throw new AssertionError(why); }
    static void frame(int n,Runnable body) {
        IsoCamera.frameState.frameCount=n;
        var p=GameProfiler.getInstance();p.startFrame("test");
        try {
            if(p.isRunning()) {var area=p.start("stock-probe");body.run();p.end(area);}
            else body.run();
        } finally {p.endFrame();}
    }
    public static void main(String[] args) throws Exception {
        ZomboidFileSystem.instance.setCacheDir(args[0]);
        var option=DebugOptions.instance.gameProfilerEnabled;
        option.setValue(false);
        StockProfiler.begin();
        frame(10,()->StockProfiler.phase("sample"));
        frame(11,()->{});
        frame(12,()->StockProfiler.phase("brake"));
        frame(13,StockProfiler::tick);
        check(option.getValue(),"disabled before drain");
        frame(14,StockProfiler::tick);
        check(!option.getValue() && !StockProfiler.active(),"original false not restored");
        check(StockProfiler.first()==11 && StockProfiler.last()==12,"sample frame boundaries");
        try(var paths=Files.walk(Path.of(args[0],"Recording"))) {
            var files=paths.filter(Files::isRegularFile).toList();
            check(!files.isEmpty(),"no stock CSV");
            boolean last=false;
            for(var file:files) for(var line:Files.readAllLines(file))
                if(line.startsWith("12,")) last=true;
            check(last,"last sample frame missing from flushed CSV");
        }
        option.setValue(true);StockProfiler.begin();StockProfiler.stop();
        check(option.getValue(),"original true not restored");
        option.setValue(false);StockProfiler.begin();
        frame(20,()->StockProfiler.phase("sample"));
        frame(21,()->StockProfiler.phase("failed"));
        frame(22,StockProfiler::tick);frame(23,StockProfiler::tick);
        check(!option.getValue(),"failed trip leaked setting");
        StockProfiler.begin();StockProfiler.phase("sample");StockProfiler.restore();
        check(!option.getValue(),"emergency restore failed");
        StockProfiler.begin();StockProfiler.phase("sample");
        // Advance only the test controller deadline, never replace engine methods.
        var deadline=StockProfiler.class.getDeclaredField("deadline");deadline.setAccessible(true);
        deadline.setLong(null,System.nanoTime()-1);StockProfiler.tick();
        check(StockProfiler.expired() && !StockProfiler.active() && !option.getValue(),"watchdog leaked setting");
        System.out.println("PASS stock CSV last frame, sample range, original true/false, failed trip, emergency restore, watchdog");
    }
}
