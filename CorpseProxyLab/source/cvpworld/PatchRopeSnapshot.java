package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.core.textures.TextureDraw;
@Patch(className="zombie.core.textures.TextureDraw",methodName="drawModel")
public class PatchRopeSnapshot {
    @Patch.OnExit public static void exit(@Patch.Argument(0) TextureDraw draw) {
        FreeRopeScene.captureQueuedVehicle(draw);
    }
}
