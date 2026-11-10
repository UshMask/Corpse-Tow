package cvprender;
import me.zed_0xff.zombie_buddy.Patch;
@Patch(className="viewpoint.models.Corpses",methodName="pick")
public class PatchCorpses {
    @Patch.OnEnter public static void enter(){Bridge.list();}
}
