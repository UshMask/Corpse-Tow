package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.iso.objects.IsoDeadBody;
import zombie.core.textures.ColorInfo;
import zombie.core.opengl.Shader;

public final class PatchBodyPresentation {
    @Patch(className="zombie.iso.objects.IsoDeadBody",methodName="render",strictMatch=true)
    public static class Draw {
        @Patch.OnEnter public static void enter(@Patch.This IsoDeadBody body,
                @Patch.Argument(value=0,readOnly=false) float x,@Patch.Argument(value=1,readOnly=false) float y,
                @Patch.Argument(2) float z,@Patch.Argument(3) ColorInfo light,
                @Patch.Argument(4) boolean a,@Patch.Argument(5) boolean b,@Patch.Argument(6) Shader shader) {
            BodyPresentation.begin(body);x+=BodyPresentation.dx();y+=BodyPresentation.dy();
        }
        @Patch.OnExit(onThrowable=Throwable.class) public static void exit(){BodyPresentation.end();}
    }
    @Patch(className="zombie.iso.objects.IsoDeadBody",methodName="isMouseOver",strictMatch=true)
    public static class Mouse {
        @Patch.OnEnter public static void enter(@Patch.This IsoDeadBody body,
                @Patch.Argument(value=0,readOnly=false) float x,@Patch.Argument(value=1,readOnly=false) float y){
            BodyPresentation.begin(body);
            float dx=BodyPresentation.dx(),dy=BodyPresentation.dy();
            x-=zombie.iso.IsoUtils.XToScreen(dx,dy,0,0);
            y-=zombie.iso.IsoUtils.YToScreen(dx,dy,0,0);
        }
        @Patch.OnExit(onThrowable=Throwable.class) public static void exit(){BodyPresentation.end();}
    }
    @Patch(className="zombie.iso.objects.IsoDeadBody",methodName="renderShadow",strictMatch=true)
    public static class ShadowScope {
        @Patch.OnEnter public static void enter(@Patch.This IsoDeadBody body){BodyPresentation.begin(body);}
        @Patch.OnExit(onThrowable=Throwable.class) public static void exit(){BodyPresentation.end();}
    }
    @Patch(className="zombie.iso.objects.IsoDeadBody",methodName="renderShadow",strictMatch=true)
    public static class Shadow {
        @Patch.OnEnter public static void enter(
                @Patch.Argument(value=0,readOnly=false) float x,@Patch.Argument(value=1,readOnly=false) float y,
                @Patch.Argument(2) float z,@Patch.Argument(3) org.joml.Vector3f direction,
                @Patch.Argument(4) float width,@Patch.Argument(5) float length,@Patch.Argument(6) float alpha,
                @Patch.Argument(7) ColorInfo light,@Patch.Argument(8) float angle,@Patch.Argument(9) boolean indoor) {
            x+=BodyPresentation.dx();y+=BodyPresentation.dy();
        }
    }
}
