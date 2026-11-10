package cvpworld;

import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.ArrayList;
import se.krka.kahlua.vm.KahluaTable;
import zombie.Lua.LuaManager;
import zombie.iso.IsoMovingObject;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.iso.IsoGridSquare;
import zombie.iso.objects.IsoDeadBody;

/** Keep the same owned bone transforms while native removal updates world bookkeeping. */
@LuaClass(name="CVPWorldNative")
public final class WorldBridge {
    private static final Field POSE;
    static {
        try {
            POSE=IsoDeadBody.class.getDeclaredField("diedBoneTransforms");
            POSE.setAccessible(true);
        } catch (ReflectiveOperationException e) { throw new ExceptionInInitializerError(e); }
    }
    /** Per-pass index hints, never cached membership decisions. */
    public static final class ReadPass {
        final IdentityHashMap<IsoGridSquare,IdentityHashMap<IsoMovingObject,Integer>> squares=new IdentityHashMap<>();
        boolean contains(IsoDeadBody body) {
            if(body==null || body.getSquare()==null) return false;
            IsoGridSquare square=body.getSquare();
            ArrayList<IsoMovingObject> objects=square.getStaticMovingObjects();
            var indices=squares.get(square);
            if(indices==null) {
                indices=new IdentityHashMap<>();
                for(int i=0;i<objects.size();i++) indices.put(objects.get(i),i);
                squares.put(square,indices);
            }
            Integer index=indices.get(body);
            if(index!=null && index<objects.size() && objects.get(index)==body) return true;
            // Removal/reordering/replacement can occur between groups. Validate
            // against the live list, including same-size edits; never trust size.
            int found=objects.indexOf(body);
            if(found<0) {indices.remove(body);return false;}
            indices.put(body,found);return true;
        }
    }
    public static ReadPass beginRead() { return new ReadPass(); }
    public static boolean contains(ReadPass pass,IsoDeadBody body) { return pass.contains(body); }
    /** One Lua/Java call for all raw poses of the next group, before calculation. */
    public static void readPoses(ReadPass pass,KahluaTable records) {
        int count=records.len();
        for(int i=1;i<=count;i++) {
            var record=(KahluaTable)records.rawget(i);
            var body=(IsoDeadBody)record.rawget("body");
            if(!pass.contains(body)) throw new IllegalStateException("world corpse missing before pose read");
            var pose=(KahluaTable)record.rawget("before");
            if(pose==null) {pose=LuaManager.platform.newTable();record.rawset("before",pose);}
            pose.rawset("x",(double)body.getX());pose.rawset("y",(double)body.getY());pose.rawset("z",(double)body.getZ());
            pose.rawset("angle",(double)body.getAngle());pose.rawset("square",body.getSquare());
        }
    }
    public static String version() { return "0.1.0"; }
    /** Shared Lua entry point, including rollback. A supplied before pose must
     * have been validated by the caller; otherwise read the current world pose. */
    public static void move(IsoDeadBody body,double x,double y,double z,IsoGridSquare square,
                            ReadPass pass,KahluaTable before,Boolean skipInvalidation) throws Throwable {
        var old=before==null?body.getSquare():(IsoGridSquare)before.rawget("square");
        double ox=before==null?body.getX():number(before,"x");
        double oy=before==null?body.getY():number(before,"y");
        double oz=before==null?body.getZ():number(before,"z");
        movePose(body,x,y,z,square,pass,old,ox,oy,oz,skipInvalidation);
    }
    /** MP playback only; Lua owns snapshot interpolation and server identities. */
    public static boolean placeClientPose(IsoDeadBody body,double x,double y,double z,double angle) throws Throwable {
        var square=zombie.iso.IsoWorld.instance.getCell().getGridSquare((int)Math.floor(x),(int)Math.floor(y),(int)Math.floor(z));
        if(square==null || !present(body,null) || body.isBeingGrappled()
                || body.getModData().rawget("CorpseTowingVehicleToken")!=null)return false;
        move(body,x,y,z,square,null,null,null);
        setAngle(body,(float)angle);return true;
    }
    /** Batch equivalent of Sim:apply's loop. The Lua journal owns group rollback,
     * including retries when the engine refuses to restore a previously moved body. */
    public static void applyPoses(KahluaTable records,KahluaTable pending,ReadPass pass,Boolean skipInvalidation) throws Throwable {
        var cell=zombie.iso.IsoWorld.instance.getCell();
        int count=records.len();
        for(int i=1;i<=count;i++) {
            var record=(KahluaTable)records.rawget(i);
            var before=(KahluaTable)record.rawget("before");
            var body=(IsoDeadBody)record.rawget("body");
            double ox=number(before,"x"),oy=number(before,"y"),oz=number(before,"z");
            var old=(IsoGridSquare)before.rawget("square");
            if(body.getX()!=ox || body.getY()!=oy || body.getZ()!=oz
                    || body.getAngle()!=number(before,"angle") || body.getSquare()!=old)
                throw new IllegalStateException("body changed before pose commit");
            // Include the failing body as well: setters/registration may fail midway.
            pending.rawset(i,record);
            double x=number(record,"x"),y=number(record,"y"),z=number(record,"z");
            PoseTrace.sample("candidate",body,x,y,z,number(record,"angle"));
            var square=cell.getGridSquare((int)Math.floor(x),(int)Math.floor(y),(int)Math.floor(z));
            movePose(body,x,y,z,square,pass,old,ox,oy,oz,skipInvalidation);
            setAngle(body,(float)number(record,"angle"));
            PoseTrace.sample("committed",body,x,y,z,number(record,"angle"));
        }
    }
    private static double number(KahluaTable table,String key) {
        return ((Number)table.rawget(key)).doubleValue();
    }
    private static boolean present(IsoDeadBody body,ReadPass pass) {
        return pass!=null?pass.contains(body):body.getSquare()!=null && body.getStaticMovingObjectIndex()>=0;
    }
    private static void position(IsoDeadBody body,double x,double y,double z,IsoGridSquare square) {
        body.setX((float)x);body.setY((float)y);body.setZ((float)z);
        body.setSquare(square);body.setCurrent(square);
    }
    /** Sole movement implementation: registration, local recovery and invalidation.
     * Do not add towing/ownership guards here: rollback must use this path too. */
    private static void movePose(IsoDeadBody body,double x,double y,double z,IsoGridSquare square,ReadPass pass,
                                 IsoGridSquare old,double ox,double oy,double oz,Boolean skipInvalidation) throws Throwable {
        if(!present(body,pass)) throw new IllegalStateException("world corpse missing");
        // Compare the original doubles before converting for the engine's float setters.
        if(old==square && ox==x && oy==y && oz==z) return;
        if(old!=square) {
            boolean network=zombie.network.GameClient.client || zombie.network.GameServer.server;
            try {
                removePreservingPose(old,body);
                position(body,x,y,z,square);square.addCorpse(body,network);
                if(!present(body,pass)) throw new IllegalStateException("destination did not register corpse");
            } catch(Throwable failure) {
                if(body.getStaticMovingObjectIndex()>=0 && body.getSquare()!=old)
                    removePreservingPose(body.getSquare(),body);
                position(body,ox,oy,oz,old);
                if(body.getStaticMovingObjectIndex()<0) old.addCorpse(body,network);
                throw failure;
            }
        } else position(body,x,y,z,square);
        if(old==square && skipInvalidation==null) skipInvalidation=DynamicCorpses.canSkipMoveInvalidation();
        if(old!=square || !Boolean.TRUE.equals(skipInvalidation)) body.invalidateRenderChunkLevel(2);
    }
    public static void setAngle(IsoDeadBody body,float angle) {
        float previous=body.getAngle();
        if(previous==angle) return;
        body.setForwardDirectionAngle(angle);
        if(atlasAngle(previous)!=atlasAngle(angle)) body.invalidateCorpse();
    }
    // B42 setForwardDirectionAngle leaves IsoDirection unchanged; getBodyKey uses this float bucket.
    // Keep the exact world angle; only skip invalidation of the same atlas key.
    private static int atlasAngle(float angle) {
        return (int)(zombie.core.math.PZMath.wrap(angle,0,6.2831855f)*57.295776f);
    }
    public static void applyVehicleResistance(zombie.vehicles.BaseVehicle vehicle,float amount) {
        VehicleImpulseBridge.resist(vehicle,amount);
    }
    public static void applyVehicleImpulse(zombie.vehicles.BaseVehicle vehicle,float x,float y,float z,
            float dx,float dy,float dz,float amount) {
        VehicleImpulseBridge.apply(vehicle,x,y,z,dx,dy,dz,amount);
    }
    public static void removePreservingPose(IsoGridSquare square,IsoDeadBody body) {
        if(square==null || body==null || body.getSquare()!=square || body.getStaticMovingObjectIndex()<0)
            throw new IllegalArgumentException("corpse must belong to the source square");
        // true suppresses RemoveCorpseFromMap: a square transition is not a death/despawn.
        preservePose(body,()->square.removeCorpse(body,
            zombie.network.GameClient.client || zombie.network.GameServer.server));
    }
    // Exercise success/exception paths with engine transforms without an OpenGL world.
    static void preservePose(IsoDeadBody body,Runnable removal) {
        try {
            Object pose=POSE.get(body);
            POSE.set(body,null);
            try { removal.run(); }
            finally { POSE.set(body,pose); }
        } catch (IllegalAccessException e) { throw new IllegalStateException("cannot preserve corpse pose",e); }
    }
}
