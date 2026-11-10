package cvpworld;

import jdk.jfr.Event;
import jdk.jfr.Label;
import jdk.jfr.Name;
import zombie.iso.objects.IsoDeadBody;

/** Opt-in JFR diagnostics. No filtering or modification of simulation/render poses. */
public final class PoseTrace {
    @Name("cvp.BodyPose") @Label("Corpse Tow body pose")
    public static final class Sample extends Event {
        public String stage;
        public int body;
        public long physicsMillis;
        public double x,y,z,angle;
        public double worldX,worldY,worldZ,worldAngle;
    }
    private static final jdk.jfr.EventType TYPE=jdk.jfr.EventType.getEventType(Sample.class);
    public static void sample(String stage,IsoDeadBody body,double x,double y,double z,double angle) {
        if(!TYPE.isEnabled())return;
        Sample s=new Sample();s.stage=stage;s.body=System.identityHashCode(body);
        s.physicsMillis=zombie.core.physics.WorldSimulation.instance.time;
        s.x=x;s.y=y;s.z=z;s.angle=angle;
        s.worldX=body.getX();s.worldY=body.getY();s.worldZ=body.getZ();s.worldAngle=body.getAngle();
        s.commit();
    }
}
