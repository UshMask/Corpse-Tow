package cvprender;
import cvpworld.BodyPresentation;
import org.joml.Matrix4f;
/** Viewpoint copies this scratch matrix into its frame; never mutate its writer. */
public final class BodyPlacement {
    private static final ThreadLocal<Matrix4f> scratch=ThreadLocal.withInitial(Matrix4f::new);
    public static Matrix4f shifted(Matrix4f matrix){
        float x=BodyPresentation.dx(),y=BodyPresentation.dy();
        if(x==0 && y==0)return matrix;
        return scratch.get().set(matrix).translateLocal(-x,0,-y);
    }
}
