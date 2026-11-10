package cvprender;
import me.zed_0xff.zombie_buddy.Patch;
import org.joml.Matrix4f;

public final class PatchBodyPlacement {
    @Patch(className="viewpoint.render.ModelDraws",methodName="add")
    public static class Draw {
        @Patch.OnEnter public static void enter(@Patch.Argument(value=3,readOnly=false) Matrix4f matrix){matrix=BodyPlacement.shifted(matrix);}
    }
    @Patch(className="viewpoint.render.ModelDraws",methodName="bounds",strictMatch=true)
    public static class Sphere {
        @Patch.OnEnter public static void enter(@Patch.Argument(0) int index,
                @Patch.Argument(value=1,readOnly=false) float x,@Patch.Argument(2) float y,
                @Patch.Argument(value=3,readOnly=false) float z,@Patch.Argument(4) float radius){
            x-=cvpworld.BodyPresentation.dx();z-=cvpworld.BodyPresentation.dy();
        }
    }
}
