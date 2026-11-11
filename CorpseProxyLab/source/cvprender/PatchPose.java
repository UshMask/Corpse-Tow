package cvprender;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.iso.objects.IsoDeadBody;
@Patch(className="viewpoint.models.CorpseCapture",methodName="draw")
public class PatchPose {
    @Patch.OnEnter public static void enter(@Patch.Argument(1) IsoDeadBody body,@Patch.Argument(2) Object pose){cvpworld.BodyPresentation.begin(body);Bridge.pose(body,pose);}
    @Patch.OnExit(onThrowable=Throwable.class) public static void exit(){cvpworld.BodyPresentation.end();}
}
