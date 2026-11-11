package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.network.packets.vehicle.VehiclePhysicsPacket;
import zombie.core.raknet.UdpConnection;
@Patch(className="zombie.network.packets.vehicle.VehiclePhysicsPacket",methodName="processServer")
public class PatchVehicleMotion {
    @Patch.OnExit public static void exit(@Patch.This VehiclePhysicsPacket packet,
        @Patch.Argument(1) UdpConnection connection) { VehicleMotion.received(packet,connection); }
}
