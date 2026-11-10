package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.iso.IsoCell;
@Patch(className="zombie.iso.IsoCell",methodName="render")
public class PatchFreeRopeScene {
    @Patch.OnEnter public static void enter() { FreeRopeScene.beginStock(); }
    @Patch.OnExit public static void exit(@Patch.This IsoCell cell) {
        // FBO submits ropes before its weather pass; retain the legacy renderer path.
        if (!zombie.core.PerformanceSettings.fboRenderChunk) FreeRopeScene.stock(cell);
    }
}
