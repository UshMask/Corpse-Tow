package cvprender;
import me.zed_0xff.zombie_buddy.Patch;
import viewpoint.core.Frame;
@Patch(className="viewpoint.game.WorldText",methodName="snapshot")
public class PatchCamera {
    @Patch.OnExit public static void exit(@Patch.Argument(0) Frame frame,@Patch.Argument(2) int player){Bridge.camera(frame,player);}
}
