package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
import zombie.iso.objects.IsoDeadBody;
@Patch(className="zombie.iso.objects.IsoDeadBody",methodName="updateRotting")
public class PatchSkeletonRotting {
    @Patch.OnExit public static void exit(@Patch.This IsoDeadBody body,
            @Patch.Argument(0) float now,@Patch.Argument(1) float stageHours) {
        SkeletonLifetime.afterRotting(body,now,stageHours);
    }
}
