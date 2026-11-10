package cvpworld;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.lang.ref.WeakReference;
import java.util.regex.Pattern;
import zombie.iso.IsoCell;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.core.network.ByteBufferReader;
import zombie.iso.IsoWorld;
import zombie.iso.objects.IsoDeadBody;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.network.WorldItemTypes;
import zombie.network.id.ObjectIDType;

/** Native corpse identity and bounded, on-demand replication to clients missing a chunk object. */
@LuaClass(name="CVPNetwork")
public final class NetworkBridge {
    private static final int MAX_BYTES=524288;
    private static final Pattern ID=Pattern.compile("-?[0-9]{1,20}");
    private static final LinkedHashMap<String,WeakReference<IsoDeadBody>> cache=new LinkedHashMap<>();
    private static WeakReference<IsoCell> cacheCell=new WeakReference<>(null);
    private static void checkWorld() {
        var cell=IsoWorld.instance==null?null:IsoWorld.instance.currentCell;
        if(cacheCell.get()!=cell) { cache.clear();cacheCell=new WeakReference<>(cell); }
    }
    private static void remember(String key,IsoDeadBody body) {
        checkWorld();
        cache.put(key,new WeakReference<>(body));
        while(cache.size()>4096) cache.remove(cache.keySet().iterator().next());
    }
    public static String id(IsoDeadBody body) {
        // Never pass 64-bit IDs through Lua's double precision numbers.
        return Long.toString(body.getObjectIDAsLong());
    }
    public static ArrayList<IsoDeadBody> bodies() {
        var result=new ArrayList<IsoDeadBody>();
        for(var item:ObjectIDType.DeadBody.getObjects())
            if(item instanceof IsoDeadBody body && body.getSquare()!=null && body.getStaticMovingObjectIndex()>=0)
                result.add(body);
        return result;
    }
    public static IsoDeadBody find(String key) {
        checkWorld();
        if(key==null || !ID.matcher(key).matches()) return null;
        var reference=cache.get(key);
        var body=reference==null?null:reference.get();
        if(body!=null && key.equals(id(body)) && body.getObjectID().getObject()==body
            && body.getSquare()!=null && body.getStaticMovingObjectIndex()>=0) return body;
        cache.remove(key);
        for(var item:bodies()) if(key.equals(id(item))) {
            remember(key,item);return item;
        }
        return null;
    }
    public static String encode(IsoDeadBody body) throws Exception {
        if(!GameServer.server) throw new IllegalStateException("server replication only");
        ByteBuffer buffer=ByteBuffer.allocate(MAX_BYTES);
        body.save(buffer); // Engine format with type header; IOException must propagate.
        byte[] bytes=new byte[buffer.position()];buffer.flip();buffer.get(bytes);
        return Base64.getEncoder().encodeToString(bytes);
    }
    public static IsoDeadBody receive(String key,String payload) throws Exception {
        if(!GameClient.client || GameServer.server) throw new IllegalStateException("client replication only");
        var existing=find(key);if(existing!=null) return existing;
        var body=decode(key,payload);
        var square=IsoWorld.instance.currentCell.getGridSquare((int)Math.floor(body.getX()),(int)Math.floor(body.getY()),(int)Math.floor(body.getZ()));
        if(square==null) return null; // Let a later chunk load/request supply it. Never create a square.
        existing=find(key);if(existing!=null) return existing;
        body.setSquare(square);body.setCurrent(square);
        for(int i=0;i<body.getContainerCount();i++) {
            var container=body.getContainerByIndex(i);container.parent=body;container.sourceGrid=square;
        }
        square.addCorpse(body,true);
        remember(key,body);return body;
    }
    static IsoDeadBody decode(String key,String payload) throws Exception {
        if(payload==null || payload.length()>((MAX_BYTES+2)/3)*4) throw new IllegalArgumentException("corpse payload too large");
        var reader=new ByteBufferReader(ByteBuffer.wrap(Base64.getDecoder().decode(payload)));
        var object=WorldItemTypes.createFromBuffer(reader);
        if(!(object instanceof IsoDeadBody body)) throw new IllegalArgumentException("corpse expected");
        // loadFromRemoteBuffer also creates surrounding squares and swallows IO errors.
        // Decode the same native body payload without those world mutations.
        body.load(reader.bb,IsoWorld.WorldVersion,false);
        if(reader.bb.hasRemaining()) throw new IllegalArgumentException("trailing corpse bytes");
        if(!key.equals(id(body))) throw new IllegalArgumentException("corpse identity mismatch");
        return body;
    }
}
