package cvpworld;

import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HexFormat;
import java.util.IdentityHashMap;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import se.krka.kahlua.j2se.KahluaTableImpl;
import se.krka.kahlua.vm.KahluaTable;
import zombie.inventory.InventoryItem;
import zombie.inventory.InventoryItemFactory;
import zombie.iso.IsoWorld;
import zombie.network.GameClient;
import zombie.world.WorldDictionary;

/** Native item snapshots only. This codec does not transfer ownership or persist a ledger. */
@LuaClass(name="CVPItemNative")
public final class ItemCodec {
    static final int MAX_BYTES=16384;
    static final int MAX_TEXT=22000;
    private static final String PREFIX="CVPITEM1";

    private ItemCodec() {}

    private static void authority() {
        if(GameClient.client) throw new IllegalStateException("item snapshots are authoritative SP/server only");
    }
    private static boolean material(String type) {
        return "Base.Rope".equals(type) || "Base.HeavyChain".equals(type) || "Base.HeavyChain_Hook".equals(type);
    }
    // Kahlua silently omits userdata/functions. Refuse instead of claiming a complete snapshot.
    private static void validateString(Object value) {
        if(value instanceof String text && text.length()>MAX_BYTES)
            throw new IllegalArgumentException("item string exceeds snapshot budget");
    }
    private static void validateData(KahluaTable table,IdentityHashMap<KahluaTable,Boolean> path,int depth,int[] remaining) {
        if(depth>32 || path.put(table,Boolean.TRUE)!=null) throw new IllegalArgumentException("cyclic or deeply nested item modData");
        var it=table.iterator();
        while(it.advance()) {
            if(--remaining[0]<0) throw new IllegalArgumentException("item modData exceeds snapshot budget");
            if(!KahluaTableImpl.canSave(it.getKey(),it.getValue()))
                throw new IllegalArgumentException("item modData is not natively serializable");
            validateString(it.getKey());validateString(it.getValue());
            if(it.getValue() instanceof KahluaTable nested) validateData(nested,path,depth+1,remaining);
        }
        path.remove(table);
    }
    public static String encode(InventoryItem item) throws Exception {
        authority();
        if(item==null || !material(item.getFullType()) || item.getRegistry_id()<0)
            throw new IllegalArgumentException("registered tether material required");
        validateString(item.getName());
        if(item.hasModData()) validateData(item.getModData(),new IdentityHashMap<>(),0,new int[]{MAX_BYTES});
        ByteBuffer buffer=ByteBuffer.allocate(MAX_BYTES);
        item.saveWithSize(buffer,false);
        byte[] bytes=new byte[buffer.position()];buffer.flip();buffer.get(bytes);
        return PREFIX+":"+IsoWorld.getWorldVersion()+":"+item.getID()+":"+item.getFullType()+":"
            +HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))+":"
            +Base64.getEncoder().encodeToString(bytes);
    }
    public static InventoryItem decode(String payload) throws Exception {
        return decode(payload,null);
    }
    // Headless tests supply an unowned native item because their ScriptManager is not bootstrapped.
    // The Lua API always resolves the real saved registry ID through the native item factory.
    static InventoryItem decode(String payload,InventoryItem target) throws Exception {
        authority();
        if(payload==null || payload.length()>MAX_TEXT) throw new IllegalArgumentException("item payload too large or missing");
        String[] fields=payload.split(":",6);
        if(fields.length!=6 || !PREFIX.equals(fields[0]) || !material(fields[3]) || !fields[4].matches("[0-9a-f]{64}"))
            throw new IllegalArgumentException("unsupported item snapshot");
        int worldVersion=Integer.parseInt(fields[1]),id=Integer.parseInt(fields[2]);
        if(worldVersion!=IsoWorld.getWorldVersion()) throw new IllegalArgumentException("item world version mismatch");
        if(fields[5].length()>((MAX_BYTES+2)/3)*4) throw new IllegalArgumentException("item payload too large");
        byte[] bytes=Base64.getDecoder().decode(fields[5]);
        if(bytes.length<11 || bytes.length>MAX_BYTES) throw new IllegalArgumentException("invalid item byte count");
        if(!fields[4].equals(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))))
            throw new IllegalArgumentException("item checksum mismatch");
        ByteBuffer buffer=ByteBuffer.wrap(bytes);
        if(buffer.getInt(0)!=bytes.length-4 || buffer.get(6)!=(byte)-1 || buffer.getInt(7)!=id)
            throw new IllegalArgumentException("item frame or identity mismatch");
        short registry=buffer.getShort(4);
        if(target==null) {
            if(!fields[3].equals(WorldDictionary.getItemTypeFromID(registry)))
                throw new IllegalArgumentException("item registry mismatch or unavailable");
        } else if(target.getContainer()!=null || target.getWorldItem()!=null || target.getRegistry_id()!=registry
            || !fields[3].equals(target.getFullType())) throw new IllegalArgumentException("invalid headless load target");
        InventoryItem item=target==null?InventoryItemFactory.CreateItem(registry):target;
        if(item==null) throw new IllegalArgumentException("native item factory unavailable");
        // loadItem swallows load exceptions and skips unexpected trailing bytes.
        // Read the same native frame directly so corruption must fail closed.
        buffer.position(7);item.load(buffer,worldVersion);
        if(item==null || buffer.hasRemaining() || item.getID()!=id || !fields[3].equals(item.getFullType())
            || item.getContainer()!=null || item.getWorldItem()!=null)
            throw new IllegalArgumentException("native item snapshot failed validation");
        return item;
    }
}
