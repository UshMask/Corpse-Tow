package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.iso.fboRenderChunk.FBORenderCell;

/** Submit world geometry before native fog, including when fog itself is disabled. */
@Patch(className="zombie.iso.fboRenderChunk.FBORenderCell",methodName="renderFog")
public class PatchFreeRopeFog {
    @Patch.OnEnter public static void enter(@Patch.This FBORenderCell renderer) {
        FreeRopeScene.stock(renderer.cell);
    }
}
