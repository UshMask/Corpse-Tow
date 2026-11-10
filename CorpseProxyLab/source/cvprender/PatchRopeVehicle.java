package cvprender;
import me.zed_0xff.zombie_buddy.Patch;
import viewpoint.core.Frame;
import zombie.core.skinnedmodel.model.ModelSlotRenderData;
import zombie.vehicles.BaseVehicle;
@Patch(className="viewpoint.models.VehicleCapture",methodName="placed")
public class PatchRopeVehicle {
    @Patch.OnExit public static void exit(@Patch.Argument(0) Frame frame,@Patch.Argument(1) ModelSlotRenderData slot,@Patch.Argument(2) BaseVehicle vehicle) {
        Bridge.ropeVehicle(frame,slot,vehicle);
    }
}
