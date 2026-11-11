package cvpworld;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;
import org.joml.Vector3f;
import zombie.vehicles.BaseVehicle;

/** B42 applyImpulseGeneric queue contract, without its unconditional diagnostic. */
final class VehicleImpulseBridge {
    private static final Field QUEUE, IMPULSE, POSITION;
    private static final Method ALLOC;
    static {
        try {
            Class<?> type=Class.forName("zombie.vehicles.BaseVehicle$VehicleImpulse");
            QUEUE=field(BaseVehicle.class,"impulsesFromHitObjects");
            IMPULSE=field(type,"impulse");POSITION=field(type,"relPos");
            ALLOC=type.getDeclaredMethod("alloc");ALLOC.setAccessible(true);
        } catch (ReflectiveOperationException e) { throw new ExceptionInInitializerError(e); }
    }
    private static Field field(Class<?> type,String name) throws ReflectiveOperationException {
        Field f=type.getDeclaredField(name);f.setAccessible(true);return f;
    }
    /** Budget against pending braking impulses, including other queue producers. */
    @SuppressWarnings("unchecked")
    static void resist(BaseVehicle vehicle,float amount) {
        if(!(amount>0)||!Float.isFinite(amount))return;
        try {
            Vector3f velocity=vehicle.getLinearVelocity(new Vector3f());
            float speed=(float)Math.hypot(velocity.x,velocity.z);
            List<Object> queue=(List<Object>)QUEUE.get(vehicle);
            if(speed<.02f)return;
            float queuedBraking=0;
            for(Object queued:queue){
                Vector3f impulse=(Vector3f)IMPULSE.get(queued);
                queuedBraking+=Math.max(0,-(impulse.x*velocity.x+impulse.z*velocity.z)/speed);
            }
            // Native queue units deliver 0.3 Ns each. Include all queued braking
            // before reserving at most half the current momentum for this batch.
            float capped=Math.min(amount,Math.max(0,vehicle.getMass()*speed*.5f/.3f-queuedBraking));
            if(capped<=0)return;
            Object entry=ALLOC.invoke(null);
            ((Vector3f)IMPULSE.get(entry)).set(-velocity.x,0,-velocity.z).mul(capped/speed);
            ((Vector3f)POSITION.get(entry)).zero();
            queue.add(entry);
            vehicle.setPhysicsActive(true);
        } catch(ReflectiveOperationException e){throw new IllegalStateException("incompatible vehicle impulse queue",e);}
    }
    @SuppressWarnings("unchecked")
    static void apply(BaseVehicle vehicle,float x,float y,float z,float dx,float dy,float dz,float amount) {
        try {
            Object entry=ALLOC.invoke(null);
            ((Vector3f)IMPULSE.get(entry)).set(dx,dz,dy).normalize().mul(amount);
            ((Vector3f)POSITION.get(entry)).set(x-vehicle.getX(),z-vehicle.getZ(),y-vehicle.getY());
            ((List<Object>)QUEUE.get(vehicle)).add(entry);
            vehicle.setPhysicsActive(true);
        } catch (ReflectiveOperationException e) { throw new IllegalStateException("incompatible vehicle impulse queue",e); }
    }
}
