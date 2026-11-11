package cvpbench;

import me.zed_0xff.zombie_buddy.Patch;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.characters.IsoPlayer;
import zombie.core.physics.CarController;
import zombie.iso.IsoWorld;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.vehicles.BaseVehicle;

/** Bounded pedal input for one explicitly armed local test driver. No transforms. */
@LuaClass(name="PZTDrivingInput")
@Patch(className="zombie.core.physics.CarController",methodName="updateControls")
public final class DrivingInput {
    private static BaseVehicle target;
    private static IsoPlayer driver;
    private static long deadline;
    private static boolean stopping;
    private static float startX, startY;
    private static float targetSpeed=8;

    public static void setTargetSpeed(float speed) {
        if(!Float.isFinite(speed) || speed<2 || speed>30)
            throw new IllegalArgumentException("test speed must be 2..30 km/h");
        targetSpeed=speed;
    }

    public static void begin(BaseVehicle vehicle, IsoPlayer player) {
        if (GameClient.client || GameServer.server || IsoWorld.instance==null
                || !"PZT_VehicleLab".equals(IsoWorld.instance.getWorld())
                || vehicle==null || player==null || !vehicle.isDriver(player))
            throw new IllegalStateException("local proving-ground driver required");
        target=vehicle;driver=player;stopping=false;
        startX=vehicle.getX();startY=vehicle.getY();
        deadline=System.nanoTime()+90_000_000_000L;
    }
    public static void stop() { stopping=true; }
    public static void release() {
        if(target!=null && Math.abs(target.getCurrentSpeedKmHour())>.2f) {
            stopping=true;return;
        }
        if(target!=null) target.getController().getClientControls().reset();
        target=null;driver=null;
    }
    @Patch.OnExit public static void pedals(@Patch.This CarController controller) {
        DrivingInput.applyPedals(controller);
    }
    // Advice is inlined into CarController; private state stays in this class.
    public static void applyPedals(CarController controller) {
        BaseVehicle vehicle=target;
        if(vehicle==null || controller.vehicleObject!=vehicle) return;
        var c=controller.getClientControls();
        if(GameClient.client || GameServer.server || !vehicle.isDriver(driver)
                || !"PZT_VehicleLab".equals(IsoWorld.instance.getWorld())) {
            c.reset();target=null;driver=null;return;
        }
        float dx=vehicle.getX()-startX,dy=vehicle.getY()-startY;
        if(System.nanoTime()>deadline || dx*dx+dy*dy>80*80) stopping=true;
        float speed=Math.abs(vehicle.getCurrentSpeedKmHour());
        c.steering=0;c.backward=false;c.shift=false;c.forceBrake=0;
        c.forward=!stopping && speed<targetSpeed;
        c.brake=stopping || speed>targetSpeed+2;
    }
}
