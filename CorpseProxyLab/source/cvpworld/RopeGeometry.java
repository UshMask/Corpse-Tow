package cvpworld;

import org.joml.Matrix4f;
import org.joml.Vector3f;
import zombie.core.skinnedmodel.model.ModelSlotRenderData;
import zombie.vehicles.BaseVehicle;

/** Coordinate conversion and segment transforms shared by native scene renderers. */
public final class RopeGeometry {
    public static final float STOREY=2.4494896f;
    private static final ThreadLocal<org.joml.Quaternionf> rotation=ThreadLocal.withInitial(org.joml.Quaternionf::new);
    private RopeGeometry() {}
    static Vector3f isoPoint(ModelSlotRenderData slot,double x,double y,double z,Vector3f out) {
        return out.set((float)(slot.x-x),(float)((z-slot.z)*STOREY-BaseVehicle.centerOfMassMagic-slot.centerOfMassY),(float)(y-slot.y));
    }
    static Vector3f scenePoint(Vector3f camera,double x,double y,double z,Vector3f out) {
        return out.set((float)(camera.x-x),(float)((z-camera.z)*STOREY),(float)(camera.y-y));
    }
    static void segment(Vector3f a,Vector3f b,float radius,Matrix4f out) {
        float x=b.x-a.x,y=b.y-a.y,z=b.z-a.z;
        float length=org.joml.Math.sqrt(org.joml.Math.fma(x,x,org.joml.Math.fma(y,y,z*z)));
        if(length<1e-6f) {out.translation(a).scale(0);return;}
        out.translation(a).rotate(rotation.get().rotationTo(0,1,0,x/length,y/length,z/length)).scale(radius,length,radius);
    }
}
