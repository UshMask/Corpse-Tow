package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
@Patch(className="zombie.savefile.PlayerDB",methodName="releasePlayerData")
public class PatchPlayerSaveAck {
 @Patch.OnEnter public static void enter(@Patch.Argument(0) Object task) { EquipmentPersistence.completed(task); }
}
