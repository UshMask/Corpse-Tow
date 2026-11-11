package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
@Patch(className="zombie.iso.objects.IsoDeadBody",methodName="updateBodies")
public class PatchSkeletonUpdate {
    @Patch.OnEnter public static void enter() { SkeletonLifetime.begin(); }
    @Patch.OnExit(onThrowable=Throwable.class) public static void exit() { SkeletonLifetime.finish(); }
}
