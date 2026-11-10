package cvpworld;

import java.lang.reflect.Field;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.core.PerformanceSettings;
import zombie.debug.DebugOptions;

/** Reuse B42's native world-corpse pass, never create a second renderer. */
@LuaClass(name="CVPDynamicCorpses")
public final class DynamicCorpses {
    private static final boolean enabled=Boolean.parseBoolean(System.getProperty("cvp.dynamicCorpses","true"));
    private static boolean inspected,unavailable;
    private static Field viewpoint;
    private DynamicCorpses() {}
    public static boolean canSkipMoveInvalidation() {
        if(!enabled || zombie.network.GameServer.server || !PerformanceSettings.fboRenderChunk
                || DebugOptions.instance.fboRenderChunk.corpsesInChunkTexture.getValue()) return false;
        // Detect the camera independently of our optional adapter: adapter failure must
        // never suppress Viewpoint's chunk mutation notifications.
        if(!inspected) {
            inspected=true;
            try {viewpoint=Class.forName("viewpoint.core.View",false,DynamicCorpses.class.getClassLoader()).getField("enabled");}
            catch(ClassNotFoundException absent) { }
            catch(ReflectiveOperationException | LinkageError failure) {unavailable=true;}
        }
        if(unavailable) return false;
        try {return viewpoint==null || !viewpoint.getBoolean(null);}
        catch(IllegalAccessException | LinkageError failure) {unavailable=true;return false;}
    }
}
