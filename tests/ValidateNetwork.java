package cvpworld;

import java.lang.reflect.Field;
import zombie.Lua.LuaManager;
import zombie.iso.IsoCell;
import zombie.iso.objects.IsoDeadBody;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.network.id.ObjectID;
import zombie.core.skinnedmodel.visual.HumanVisual;
import se.krka.kahlua.vm.KahluaTable;

/** Actual Build 42 native save/load bytes, without a GL window or fake Lua serializer. */
public class ValidateNetwork {
    static KahluaTable table(Object... fields) {
        var result=LuaManager.platform.newTable();
        for(int i=0;i<fields.length;i+=2) result.rawset(fields[i],fields[i+1]);
        return result;
    }
    interface Checked { void run() throws Exception; }
    static void rejects(Checked operation) throws Exception {
        try { operation.run(); } catch(Exception expected) { return; }
        throw new AssertionError("invalid operation accepted");
    }
    public static void main(String[] args) throws Exception {
        zombie.core.random.RandStandard.INSTANCE.init();GameServer.server=true;
        LuaManager.platform=new se.krka.kahlua.j2se.J2SEPlatform();LuaManager.env=LuaManager.platform.newTable();
        var body=new IsoDeadBody((IsoCell)null);
        Field visual=IsoDeadBody.class.getDeclaredField("baseVisual");visual.setAccessible(true);visual.set(body,new HumanVisual(body));
        body.setContainer(new zombie.inventory.ItemContainer());
        if(body.isZombie() || body.isAnimal()) throw new AssertionError("human corpse fixture expected");
        // Set fixture state without registering a world updater in this headless test.
        Field reanimate=IsoDeadBody.class.getDeclaredField("reanimateTime");
        reanimate.setAccessible(true);reanimate.setFloat(body,42.5f);
        Field id=ObjectID.class.getDeclaredField("id");id.setAccessible(true);id.setLong(body.getObjectID(),9007199254740993L);
        body.setX(10.5f);body.setY(20.75f);body.setZ(0);body.setForwardDirectionAngle(1.2f);
        body.getModData().rawset("CVPTestMarker","original corpse");
        var tether=table("version",1.0,"vehicle","old-vehicle","gearID",42.0,
            "gearType","Base.Rope","slot",8.0,"length",5.55,"extension","keep legacy data");
        body.getModData().rawset("CVPTether",tether);
        if(!NetworkBridge.id(body).equals("9007199254740993")) throw new AssertionError("64-bit ID formatter rounded");
        // This engine build persists corpse IDs as short; use its valid native range for save/load.
        id.setLong(body.getObjectID(),12345L);
        String key=NetworkBridge.id(body),payload=NetworkBridge.encode(body);
        var copy=NetworkBridge.decode(key,payload);
        if(copy==body || !NetworkBridge.id(copy).equals(key) || copy.getX()!=body.getX() || copy.getY()!=body.getY()
            || Math.abs(copy.getAngle()-body.getAngle())>0.0001f
            || !"original corpse".equals(copy.getModData().rawget("CVPTestMarker")))
            throw new AssertionError("native corpse serialization lost identity, pose, coordinates or metadata");
        if(copy.getStaticMovingObjectIndex()>=0) throw new AssertionError("decode registered body before world validation");
        if(copy.isZombie() || copy.isAnimal() || copy.getReanimateTime()!=body.getReanimateTime())
            throw new AssertionError("human corpse type or reanimation data lost");
        var legacy=(KahluaTable)copy.getModData().rawget("CVPTether");
        if(!Double.valueOf(1).equals(legacy.rawget("version")) || legacy.rawget("connection")!=null
            || legacy.rawget("point")!=null || !"keep legacy data".equals(legacy.rawget("extension")))
            throw new AssertionError("legacy tether data changed during native serialization");
        // Cache is strictly bounded on every insert and holds no strong corpse reference.
        var remember=NetworkBridge.class.getDeclaredMethod("remember",String.class,IsoDeadBody.class);
        remember.setAccessible(true);
        var field=NetworkBridge.class.getDeclaredField("cache");field.setAccessible(true);
        var cache=(java.util.Map<?,?>)field.get(null);
        for(int i=0;i<4100;i++) remember.invoke(null,Integer.toString(i),body);
        if(cache.size()!=4096 || cache.containsKey("0")) throw new AssertionError("cache limit/eviction failed");
        for(var ref:cache.values()) if(!(ref instanceof java.lang.ref.WeakReference<?>))
            throw new AssertionError("cache retains strong corpse references");
        ((java.lang.ref.WeakReference<?>)cache.get("4099")).clear();
        if(NetworkBridge.find("4099")!=null || cache.containsKey("4099"))
            throw new AssertionError("cleared reference was not discarded");
        // A loaded cell replacement is the native world boundary, including reconnects.
        var world=zombie.iso.IsoWorld.instance;
        var oldCell=world.currentCell;
        try {
            world.currentCell=new IsoCell(1,1);
            NetworkBridge.find("invalid");
            if(!cache.isEmpty()) throw new AssertionError("cache survived cell replacement");
            remember.invoke(null,key,body);
            world.currentCell=null;NetworkBridge.find("invalid");
            if(!cache.isEmpty()) throw new AssertionError("cache survived cell unload");
        } finally { world.currentCell=oldCell; }
        String bodyKey=LuaManager.GlobalObject.getRandomUUID();
        String connectionID=LuaManager.GlobalObject.getRandomUUID();
        if(bodyKey.equals(connectionID)) throw new AssertionError("UUID generator repeated identity");
        body.getModData().rawset("CVPBodyKey",bodyKey);
        tether.rawset("connection",table("version",1.0,"id",connectionID,
            "a",table("kind","vehicle","key","old-vehicle","point","hitch"),
            "b",table("kind","body","key",bodyKey,"point","feet")));
        tether.rawset("version",2.0);
        tether.rawset("vehicle",null);
        tether.rawset("point",null);
        var extended=NetworkBridge.decode(key,NetworkBridge.encode(body));
        var extendedTether=(KahluaTable)extended.getModData().rawget("CVPTether");
        var connection=(KahluaTable)extendedTether.rawget("connection");
        var from=(KahluaTable)connection.rawget("a");
        var to=(KahluaTable)connection.rawget("b");
        if(!connectionID.equals(connection.rawget("id")) || !bodyKey.equals(extended.getModData().rawget("CVPBodyKey"))
            || !"vehicle".equals(from.rawget("kind")) || !"old-vehicle".equals(from.rawget("key"))
            || !"hitch".equals(from.rawget("point")) || !"body".equals(to.rawget("kind"))
            || !bodyKey.equals(to.rawget("key")) || !"feet".equals(to.rawget("point"))
            || !Double.valueOf(2.0).equals(extendedTether.rawget("version"))
            || extendedTether.rawget("vehicle")!=null || extendedTether.rawget("point")!=null
            || !"keep legacy data".equals(extendedTether.rawget("extension"))
            || !Double.valueOf(5.55).equals(extendedTether.rawget("length")))
            throw new AssertionError("connection identity/endpoints or legacy fields lost in native bytes");
        rejects(()->NetworkBridge.decode("2",payload));
        rejects(()->NetworkBridge.decode(key,"!bad base64!"));
        rejects(()->NetworkBridge.decode(key,"x".repeat(800000)));
        rejects(()->NetworkBridge.receive(key,payload)); // server cannot spawn client copies
        GameServer.server=false;GameClient.client=true;
        rejects(()->NetworkBridge.encode(body)); // client cannot supply authoritative body bytes
        System.out.println("PASS actual engine corpse serialization, legacy tether, UUID connection/endpoints, 64-bit identity, pose/metadata, malformed payloads and role guards");
    }
}
