package cvpworld;

import me.zed_0xff.zombie_buddy.Patch;
import zombie.Lua.LuaEventManager;
import zombie.network.GameClient;
import zombie.vehicles.BaseVehicle;

/** Permanent deletion only: chunk unloading must never release a tether. */
@Patch(className="zombie.vehicles.BaseVehicle",methodName="permanentlyRemove")
public class PatchVehicleRemoval {
    @Patch.OnExit public static void exit(@Patch.This BaseVehicle vehicle) {
        if (!GameClient.client) LuaEventManager.triggerEvent("OnCVPVehicleRemoved",vehicle);
    }
}
