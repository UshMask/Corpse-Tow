package cvprender;
import me.zed_0xff.zombie_buddy.Patch;
import viewpoint.core.Frame;
@Patch(className="viewpoint.models.Models",methodName="snapshot")
public class PatchFreeLinks {
    static { FreeLinks.install(); }
    @Patch.OnExit public static void exit(@Patch.Argument(0) Frame frame,@Patch.Argument(1) int player) { FreeLinks.capture(frame,player); }
}
