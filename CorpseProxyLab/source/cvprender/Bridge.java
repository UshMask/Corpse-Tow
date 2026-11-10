package cvprender;

import java.lang.reflect.*;
import java.util.IdentityHashMap;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import viewpoint.core.Frame;
import viewpoint.core.View;
import viewpoint.input.FreeCam;
import viewpoint.input.Look;
import viewpoint.platform.LiveSettings;
import viewpoint.models.Corpses;
import zombie.iso.IsoCamera;
import zombie.iso.objects.IsoDeadBody;

/** Render-only registration. Never inserts corpses into world or inventory lists. */
@LuaClass(name="CVPViewpoint")
public final class Bridge {
    static { FreeLinks.install(); }
    private static final IdentityHashMap<IsoDeadBody,Object> bodies=new IdentityHashMap<>();
    private static Object screen;
    private static Method set,pixel;
    private static Field angle;
    private static final float[] point=new float[2];
    private static boolean failed,screenReady;
    private static boolean announced;
    private static int submitted,poses,cameraFrames;
    private static Field vehiclePlace;
    public static String version() { return "0.0.5"; }
    public static void ropeVehicle(Frame frame,zombie.core.skinnedmodel.model.ModelSlotRenderData slot,zombie.vehicles.BaseVehicle vehicle) {
        if(!active() || !cvpworld.FreeRopeScene.ready() || cvpworld.FreeRopeScene.count()==0) return;
        try {
            if(vehiclePlace==null) {
                Class<?> type=Class.forName("viewpoint.models.VehicleCapture");
                vehiclePlace=type.getDeclaredField("place");vehiclePlace.setAccessible(true);
            }
            // Called after Viewpoint's own placement. Use exactly the matrix
            // consumed by the vehicle draw, without running tilt/prediction twice.
            cvpworld.FreeRopeScene.perspectiveVehicle(slot,(org.joml.Matrix4f)vehiclePlace.get(null),frame.camX,frame.camY,frame.camZ,
                frame.scene.relief==null?null:frame.scene.relief::scene);
        } catch(Throwable e) { cvpworld.FreeRopeScene.fail(e); }
    }
    public static synchronized boolean projectionReady() { return screenReady && active(); }
    public static synchronized int trackedCount() { return bodies.size(); }
    public static synchronized int submittedCount() { return submitted; }
    public static synchronized int poseCount() { return poses; }
    public static synchronized int cameraCount() { return cameraFrames; }
    public static float lookYaw() { return Look.yaw; }
    public static float lookPitch() { return Look.pitch; }
    private static LiveSettings.Toggle thirdSetting(boolean seated) {
        try {
            Field field=Class.forName("viewpoint.camera.CameraSettings").getDeclaredField(seated?"SEATED":"ON_FOOT");
            field.setAccessible(true);return (LiveSettings.Toggle)field.get(null);
        } catch(ReflectiveOperationException e) {throw new IllegalStateException("Viewpoint camera settings unavailable",e);}
    }
    public static boolean thirdPreference(boolean seated) { return thirdSetting(seated).get(); }
    /** Local debug controls used by CVPAgent; never called by normal towing. */
    public static void testCamera(boolean third,float yaw,float pitch) {
        if(!zombie.core.Core.debug || zombie.network.GameClient.client || zombie.network.GameServer.server)
            throw new IllegalStateException("single-player debug mode required");
        if(!Float.isFinite(yaw) || !Float.isFinite(pitch) || Math.abs(pitch)>1.4f)
            throw new IllegalArgumentException("finite yaw and pitch in [-1.4,1.4] required");
        var player=zombie.characters.IsoPlayer.getInstance();
        if(player==null) throw new IllegalStateException("local player required");
        thirdSetting(player.getVehicle()!=null).set(third);
        Look.yaw=Look.wrap(yaw);Look.pitch=pitch;Look.hold(Look.yaw,pitch);
    }
    private static void init() throws Exception {
        if(screen!=null) return;
        Class<?> type=Class.forName("viewpoint.game.WorldToScreen");
        Constructor<?> ctor=type.getDeclaredConstructor();ctor.setAccessible(true);
        set=type.getDeclaredMethod("set",Frame.class,FreeCam.Place.class,float.class,float.class);set.setAccessible(true);
        pixel=type.getDeclaredMethod("pixel",float.class,float.class,float.class,float.class,float[].class);pixel.setAccessible(true);
        angle=Class.forName("viewpoint.models.CorpsePose").getDeclaredField("angle");angle.setAccessible(true);
        screen=ctor.newInstance();
    }
    public static boolean active() { return View.enabled && !failed; }
    public static synchronized void track(IsoDeadBody body) {
        if(body!=null && !failed && !bodies.containsKey(body)) bodies.put(body,new Object());
    }
    public static synchronized void untrack(IsoDeadBody body) { bodies.remove(body); }
    public static synchronized void clear() { bodies.clear();screenReady=false; }
    public static synchronized void list() {
        submitted=0;
        if(!active()) return;
        try {
            init();
            for(var entry:bodies.entrySet()) {
                IsoDeadBody body=entry.getKey();
                if(body.getSquare()!=null && body.getStaticMovingObjectIndex()<0) {
                    Corpses.listed(body,entry.getValue(),1.0f,true);
                    submitted++;
                }
            }
            if(!bodies.isEmpty() && !announced) {announced=true;System.out.println("[CVP-Viewpoint] render-only corpses submitted");}
        } catch(Throwable e) { fail(e); }
    }
    public static synchronized void pose(IsoDeadBody body,Object pose) {
        if(!active() || !bodies.containsKey(body)) return;
        try {
            init();angle.setFloat(pose,renderedAngle(body.getAngle()));
            cvpworld.PoseTrace.sample("viewpoint",body,body.getX(),body.getY(),body.getZ(),angle.getFloat(pose));
            poses++;
        } catch(Throwable e) {fail(e);}
    }
    private static float renderedAngle(float heading) {
        // CorpsePose stores AnimationPlayer.getRenderedAngle(), not the world heading.
        // Preserve the native quarter-turn when updating a moving corpse's cached pose.
        return heading+(float)(Math.PI/2.0);
    }
    public static synchronized void camera(Frame frame,int player) {
        screenReady=false;
        if(!active() || player!=0) return;
        try {
            init();
            updateProjection(frame,FreeCam.active?FreeCam.place:null,(float)IsoCamera.getScreenWidth(player),(float)IsoCamera.getScreenHeight(player));
            cameraFrames++;
        } catch(Throwable e) {fail(e);}
    }
    private static void updateProjection(Frame frame,FreeCam.Place place,float width,float height) throws Exception {
        // WorldToScreen.set returns first-person mode, NOT projection validity.
        // Third-person and free-camera return false with a valid matrix.
        set.invoke(screen,frame,place,width,height);
        screenReady=true;
    }
    public static synchronized boolean project(float x,float y,float z) {
        if(!active() || !screenReady) return false;
        try {return (Boolean)pixel.invoke(screen,x,y,z,0.0f,point);} catch(Throwable e) {fail(e);return false;}
    }
    public static float screenX() { return point[0]; }
    public static float screenY() { return point[1]; }
    private static void fail(Throwable e) {
        if(!failed) {System.out.println("[CVP-Viewpoint] adapter disabled: "+e);e.printStackTrace();}
        failed=true;screenReady=false;bodies.clear();
    }
}
