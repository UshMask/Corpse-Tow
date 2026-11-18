package cvpworld;

import java.lang.reflect.Field;
import me.zed_0xff.zombie_buddy.Exposer;
import se.krka.kahlua.converter.KahluaConverterManager;
import se.krka.kahlua.vm.JavaFunction;
import se.krka.kahlua.vm.KahluaTable;
import zombie.Lua.LuaManager;
import zombie.iso.IsoCell;
import zombie.iso.IsoGridSquare;
import zombie.iso.objects.IsoDeadBody;
import zombie.core.skinnedmodel.visual.HumanVisual;
import zombie.network.GameClient;

public class ValidateBodyWear {
    public static void main(String[] args) throws Exception {
        zombie.core.random.RandStandard.INSTANCE.init();
        LuaManager.platform=new se.krka.kahlua.j2se.J2SEPlatform();LuaManager.env=LuaManager.platform.newTable();
        LuaManager.exposer=new LuaManager.Exposer(new KahluaConverterManager(),LuaManager.platform,LuaManager.env);
        String name=BodyWearNative.class.getAnnotation(Exposer.LuaClass.class).name();
        Exposer.exposeClass(BodyWearNative.class,name);
        if(!(LuaManager.env.rawget(name) instanceof KahluaTable bridge))
            throw new AssertionError("missing Lua body-wear bridge");
        for(String method:new String[]{"skeleton","remove","skeletonTransition","removeTransition"})
            if(!(bridge.rawget(method) instanceof JavaFunction)) throw new AssertionError("missing Lua method "+method);

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
        var square=new IsoGridSquare(null,null,0,0,0);
        body.setSquare(square);square.getStaticMovingObjects().add(body);
        // This fixture has no chunk or save worker, so only the mutation API can succeed.
        if(!BodyWearNative.skeletonTransition(body)) throw new AssertionError("transition failed");
        if(!body.isSkeleton() || !body.getContainer().getItems().isEmpty()
            || body.getWornItems().size()!=0 || body.getAttachedItems().size()!=0
            || body.getDeathTime()!=123.5f || !"persistent-cargo".equals(body.getModData().rawget("CVPBodyKey")))
            throw new AssertionError("vanilla skeleton transition changed identity or failed to clear contents");
        if(!BodyWearNative.skeletonTransition(body)) throw new AssertionError("transition replay failed");
        square.getStaticMovingObjects().remove(body);
        if(!BodyWearNative.removeTransition(body,square)) throw new AssertionError("detached removal replay failed");
        GameClient.client=true;
        boolean denied=false;try { BodyWearNative.skeletonTransition(body); } catch(IllegalArgumentException expected) {denied=true;}
        if(!denied) throw new AssertionError("client permitted wear");
        GameClient.client=false;zombie.setBoolean(body,false);denied=false;
        try { BodyWearNative.removeTransition(body,null); } catch(IllegalArgumentException expected) {denied=true;}
        if(!denied) throw new AssertionError("player corpse permitted wear");
        System.out.println("PASS ZombieBuddy Lua API, vanilla skeleton mutation, idempotent replay, authority and player protection");
    }
}
