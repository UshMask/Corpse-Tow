package cvpworld;

import java.util.IdentityHashMap;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import se.krka.kahlua.vm.KahluaTable;
import zombie.characters.IsoGameCharacter;
import zombie.core.skinnedmodel.model.Model;
import zombie.iso.Vector3;
import zombie.scripting.ScriptManager;

/** Cosmetic hand pose only. Never equips, creates or transfers an inventory item. */
@LuaClass(name="CVPVisualAttachment")
public final class VisualAttachment {
    private record Held(String before,String model) {}
    private static final IdentityHashMap<IsoGameCharacter,Held> held=new IdentityHashMap<>();
    private static final ThreadLocal<org.lwjgl.util.vector.Matrix4f> handMatrix=
        ThreadLocal.withInitial(org.lwjgl.util.vector.Matrix4f::new);
    private static final ThreadLocal<Vector3> handPoint=ThreadLocal.withInitial(Vector3::new);
    private VisualAttachment() {}
    public static boolean hand(IsoGameCharacter player,KahluaTable out) {
        if(player==null || player.isDead() || player.getVehicle()!=null) return false;
        var anim=player.getAnimationPlayer();
        if(anim==null || anim.isBoneTransformsNeedFirstFrame()) return false;
        int bone=anim.getSkinningBoneIndex("Bip01_R_Hand",-1);
        if(bone<0) return false;
        var matrix=anim.getBoneModelTransform(bone,handMatrix.get());
        var p=handPoint.get();p.x=matrix.m03;p.y=matrix.m13;p.z=matrix.m23;
        Model.vectorToWorldCoords(player.getX(),player.getY(),player.getZ(),anim.getAngle(),p);
        if(!Float.isFinite(p.x)||!Float.isFinite(p.y)||!Float.isFinite(p.z)) return false;
        out.rawset("x",(double)p.x);out.rawset("y",(double)p.y);out.rawset("z",(double)p.z);
        return true;
    }
    public static void carry(IsoGameCharacter player,String material) {
        if(player==null) return;
        if(material==null || player.isDead() || player.getVehicle()!=null || !player.getCharacterActions().isEmpty()) {
            release(player);return;
        }
        var item=ScriptManager.instance.FindItem(material);String model=item==null?null:item.getStaticModel();
        if(model==null) {release(player);return;}
        Held old=held.get(player);
        if(old!=null && old.model.equals(model)) return;
        release(player);
        // Respect overrides owned by another action/mod and occupied hands.
        if(player.overridePrimaryHandModel!=null || player.forceNullOverride || player.getPrimaryHandItem()!=null) return;
        held.put(player,new Held(player.overridePrimaryHandModel,model));
        player.overridePrimaryHandModel=model;player.resetModelNextFrame();
    }
    public static void release(IsoGameCharacter player) {
        Held old=held.remove(player);
        if(old!=null && old.model.equals(player.overridePrimaryHandModel)) {
            player.overridePrimaryHandModel=old.before;player.resetModelNextFrame();
        }
    }
    public static void clear() {for(var p:held.keySet().toArray(IsoGameCharacter[]::new)) release(p);}
}
