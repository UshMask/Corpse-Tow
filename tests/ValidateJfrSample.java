import java.nio.file.Path;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import jdk.jfr.Event;
import jdk.jfr.Name;
import jdk.jfr.Recording;
import jdk.jfr.consumer.RecordingFile;
import cvpbench.JfrPhase;

public class ValidateJfrSample {
    @Name("test.Work") public static class Work extends Event { public String label; }
    static void work(String label) { var e=new Work();e.label=label;e.commit(); }
    public static void main(String[] args) throws Exception {
        Path dir=Path.of(args[0]);Files.createDirectories(dir);
        Path full=dir.resolve("full.jfr"),sample=dir.resolve("sample.jfr");
        try(var r=new Recording(jdk.jfr.Configuration.getConfiguration("profile"))) {
            r.enable(Work.class);r.start();
            JfrPhase.mark("one","warmup");work("before");
            var crossing=new Work();crossing.label="crossing";crossing.begin();
            JfrPhase.mark("one","sample");Thread.sleep(20);work("inside");
            Thread.sleep(20);JfrPhase.mark("one","brake");
            crossing.end();crossing.commit();work("after");JfrPhase.mark("one","done");
            r.stop();r.dump(full);
        }
        byte[] original=Files.readAllBytes(full);
        JfrSample.main(new String[]{full.toString(),sample.toString()});
        List<String> labels=new ArrayList<>();
        for(var e:RecordingFile.readAllEvents(sample))
            if(e.getEventType().getName().equals("test.Work")) labels.add(e.getString("label"));
        if(!labels.equals(List.of("inside"))) throw new AssertionError(labels);
        if(!java.util.Arrays.equals(original,Files.readAllBytes(full))) throw new AssertionError("source modified");
        for(String defect:List.of("missing","duplicate","failed","mixed")) {
            Path bad=dir.resolve(defect+".jfr");
            try(var r=new Recording()) {
                r.enable(JfrPhase.Phase.class);r.start();JfrPhase.mark("one","sample");
                if(defect.equals("duplicate")) JfrPhase.mark("one","sample");
                if(!defect.equals("missing")) JfrPhase.mark("one","brake");
                JfrPhase.mark(defect.equals("mixed")?"two":"one",defect.equals("failed")?"failed":"done");
                r.stop();r.dump(bad);
            }
            Path out=dir.resolve(defect+"-trip.jfr");
            try { JfrSample.main(new String[]{bad.toString(),out.toString()});throw new AssertionError("accepted "+defect); }
            catch(IllegalStateException expected) {}
            if(Files.exists(out)) throw new AssertionError("published invalid sample");
        }
        System.out.println("PASS exact sample filtering, boundary exclusion, original preservation and invalid markers");
    }
}
