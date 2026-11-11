import java.util.function.BooleanSupplier;
import me.zed_0xff.zombie_buddy.PatchEngine;

public class ValidateOptionalViewpoint {
    public static void premain(String args,java.lang.instrument.Instrumentation instrumentation) throws Exception {
        // Exercise the real PatchEngine in an isolated validator JVM, without starting a game.
        var field=Class.forName("me.zed_0xff.zombie_buddy.Loader").getDeclaredField("g_instrumentation");
        field.setAccessible(true);field.set(null,instrumentation);
    }
    public static void main(String[] args) throws Exception {
        boolean absent=args[0].equals("absent");
        if(absent) {
            try { Class.forName("viewpoint.core.Frame");throw new AssertionError("Viewpoint leaked into absent test"); }
            catch(ClassNotFoundException expected) {}
        }
        var loader=ValidateOptionalViewpoint.class.getClassLoader();
        var known=Class.forName("me.zed_0xff.zombie_buddy.Loader").getDeclaredField("g_known_jars");known.setAccessible(true);
        @SuppressWarnings("unchecked") var jars=(java.util.Set<java.nio.file.Path>)known.get(null);
        jars.add(java.nio.file.Path.of(cvpworld.OptionalViewpoint.class.getProtectionDomain().getCodeSource().getLocation().toURI()));
        var bootstrap=PatchEngine.collectPatches("cvpworld",loader);
        if(bootstrap.contains(cvpworld.OptionalViewpoint.class)
            || !cvpworld.OptionalViewpoint.class.isAnnotationPresent(me.zed_0xff.zombie_buddy.Exposer.LuaClass.class))
            throw new AssertionError("loader must use the supported Lua API, not a forbidden Exposer patch");
        if(absent) {
            cvpworld.OptionalViewpoint.install();cvpworld.OptionalViewpoint.install();
            var attempted=cvpworld.OptionalViewpoint.class.getDeclaredField("attempted");attempted.setAccessible(true);
            if(attempted.getBoolean(null)) throw new AssertionError("absent Viewpoint consumed installation attempt");
            var perspective=cvpworld.FreeRopeScene.class.getDeclaredField("perspective");perspective.setAccessible(true);
            if(((BooleanSupplier)perspective.get(null)).getAsBoolean()) throw new AssertionError("stock ropes disabled");
        } else {
            zombie.network.GameServer.server=true;
            cvpworld.OptionalViewpoint.install();
            var attempted=cvpworld.OptionalViewpoint.class.getDeclaredField("attempted");attempted.setAccessible(true);
            if(attempted.getBoolean(null)) throw new AssertionError("adapter activated on dedicated server");
            zombie.network.GameServer.server=false;
            cvpworld.OptionalViewpoint.install();
            if(!attempted.getBoolean(null)) throw new AssertionError("available Viewpoint not installed");
            cvpworld.OptionalViewpoint.install();
            // Applied advice must run: a normal WorldText snapshot now reaches Bridge.camera.
            viewpoint.core.View.enabled=true;
            var frame=new viewpoint.core.Frame();
            var worldText=Class.forName("viewpoint.game.WorldText").getDeclaredMethod("snapshot",viewpoint.core.Frame.class,zombie.iso.IsoCell.class,int.class);
            worldText.setAccessible(true);
            int before=cvprender.Bridge.cameraCount();
            var unsafeField=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
            var cell=(zombie.iso.IsoCell)((sun.misc.Unsafe)unsafeField.get(null)).allocateInstance(zombie.iso.IsoCell.class);
            var objects=zombie.iso.IsoCell.class.getDeclaredField("objectList");objects.setAccessible(true);objects.set(cell,new java.util.HashSet<>());
            var statics=zombie.iso.IsoCell.class.getDeclaredField("staticUpdaterObjectList");statics.setAccessible(true);statics.set(cell,new java.util.ArrayList<>());
            worldText.invoke(null,frame,cell,0);
            if(cvprender.Bridge.cameraCount()!=before+1)
                throw new AssertionError("late Viewpoint advice missing or installed twice");
        }
        System.out.println("PASS optional Viewpoint: "+args[0]);
    }
}
