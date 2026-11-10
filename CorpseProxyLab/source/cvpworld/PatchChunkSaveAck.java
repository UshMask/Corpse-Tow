package cvpworld;
import me.zed_0xff.zombie_buddy.Patch;
@Patch(className="zombie.network.ServerChunkLoader$SaveLoadedTask",methodName="release")
public class PatchChunkSaveAck {
 @Patch.OnEnter public static void enter(@Patch.This Object task) { EquipmentPersistence.completed(task); }
}
