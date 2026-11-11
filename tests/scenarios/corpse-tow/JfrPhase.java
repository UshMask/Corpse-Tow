package cvpbench;

import jdk.jfr.Event;
import jdk.jfr.Label;
import jdk.jfr.Name;
import jdk.jfr.StackTrace;

/** A few scenario boundaries, never a per-frame event. */
public final class JfrPhase {
    @Name("corpseTow.Phase") @Label("Corpse Tow scenario phase") @StackTrace(false)
    public static final class Phase extends Event {
        public String run;
        public String phase;
    }
    public static void mark(String run,String phase) {
        Phase event=new Phase();
        if(!event.isEnabled()) return;
        event.run=run;event.phase=phase;event.commit();
    }
}
