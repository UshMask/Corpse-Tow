package cvpworld;

import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import me.zed_0xff.zombie_buddy.PatchEngine;

/** Called by client Lua after approved mod JARs and Lua globals are available. */
@LuaClass(name="CVPViewpointLoader")
public final class OptionalViewpoint {
    private static boolean attempted;
    private OptionalViewpoint() {}

    public static synchronized void install() {
        if(attempted || zombie.network.GameServer.server) return;
        ClassLoader loader=OptionalViewpoint.class.getClassLoader();
        try { Class.forName("viewpoint.core.Frame",false,loader); }
        catch(ClassNotFoundException absent) { return; }
        attempted=true;
        // ZombieBuddy appends approved JARs at runtime; scan its registered JAR list.
        try { PatchEngine.applyPatches("cvprender",null); }
        catch(RuntimeException | LinkageError failure) {
            cvpworld.FreeRopeScene.setPerspective(()->false);
            System.err.println("[CVP-Viewpoint] optional adapter unavailable: "+failure);
        }
    }
}
