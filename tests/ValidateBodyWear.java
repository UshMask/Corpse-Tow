package cvpworld;

import java.lang.reflect.Field;
import zombie.Lua.LuaManager;
import zombie.iso.IsoCell;
import zombie.iso.objects.IsoDeadBody;
import zombie.core.skinnedmodel.visual.HumanVisual;
import zombie.network.GameClient;

public class ValidateBodyWear {
    public static void main(String[] args) throws Exception {
        zombie.core.random.RandStandard.INSTANCE.init();
        LuaManager.platform=new se.krka.kahlua.j2se.J2SEPlatform();LuaManager.env=LuaManager.platform.newTable();
        IsoDeadBody body=new IsoDeadBody((IsoCell)null);
        Field visual=IsoDeadBody.class.getDeclaredField("baseVisual");visual.setAccessible(true);visual.set(body,new HumanVisual(body));
        body.setContainer(new zombie.inventory.ItemContainer());
        body.getModData().rawset("CVPBodyKey","persistent-cargo");
        body.setDeathTime(123.5f);
        Field zombie=IsoDeadBody.class.getDeclaredField("wasZombie");zombie.setAccessible(true);zombie.setBoolean(body,true);
        if(body.isSkeleton()) throw new AssertionError("fresh body expected");
        var unsafeField=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
        var unsafe=(sun.misc.Unsafe)unsafeField.get(null);
        body.getContainer().getItems().add((zombie.inventory.InventoryItem)unsafe.allocateInstance(zombie.inventory.InventoryItem.class));
        if(body.getContainer().getItems().isEmpty()) throw new AssertionError("loot fixture is empty");
        BodyWearNative.becomeSkeleton(body);
        if(!body.isSkeleton() || !body.getContainer().getItems().isEmpty()
            || body.getWornItems().size()!=0 || body.getAttachedItems().size()!=0
            || body.getDeathTime()!=123.5f || !"persistent-cargo".equals(body.getModData().rawget("CVPBodyKey")))
            throw new AssertionError("vanilla skeleton transition changed identity or failed to clear contents");
        BodyWearNative.becomeSkeleton(body);
        GameClient.client=true;
        boolean denied=false;try { BodyWearNative.skeleton(body); } catch(IllegalArgumentException expected) {denied=true;}
        if(!denied) throw new AssertionError("client permitted wear");
        GameClient.client=false;zombie.setBoolean(body,false);denied=false;
        try { BodyWearNative.remove(body,null); } catch(IllegalArgumentException expected) {denied=true;}
        if(!denied) throw new AssertionError("player corpse permitted wear");
        System.out.println("PASS vanilla skeleton transition, identity preservation, authority and player protection");
    }
}
