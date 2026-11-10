package cvpworld;

import java.nio.ByteBuffer;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.core.network.ByteBufferReader;
import zombie.core.properties.IsoObjectChange;
import zombie.iso.IsoGridSquare;
import zombie.iso.objects.IsoDeadBody;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.network.PacketTypes;
import zombie.network.packets.INetworkPacket;

/** Authority-only transitions using the same skeleton and removal paths as vanilla. */
@LuaClass(name="CVPBodyWearNative")
public final class BodyWearNative {
    private static void allowed(IsoDeadBody body) {
        if(GameClient.client || body==null || !body.isZombie() || body.isPlayer())
            throw new IllegalArgumentException("zombie corpse on authority required");
    }
    static void becomeSkeleton(IsoDeadBody body) {
        ByteBuffer buffer=ByteBuffer.allocate(4);buffer.putInt(1);buffer.flip();
        body.loadChange(IsoObjectChange.BECOME_SKELETON,new ByteBufferReader(buffer));
    }
    public static boolean skeleton(IsoDeadBody body) throws Exception {
        allowed(body);
        if(body.getSquare()==null || body.getStaticMovingObjectIndex()<0) return false;
        if(!body.isSkeleton()) {
            becomeSkeleton(body);
        }
        if(GameServer.server) body.sendObjectChange(IsoObjectChange.BECOME_SKELETON);
        return EquipmentPersistence.checkpointSquare(body.getSquare());
    }
    public static boolean remove(IsoDeadBody body,IsoGridSquare square) throws Exception {
        allowed(body);
        if(square==null) return false;
        if(body.getStaticMovingObjectIndex()>=0) {
            if(body.getSquare()!=square) return false;
            if(GameServer.server) INetworkPacket.sendToAll(PacketTypes.PacketType.RemoveCorpseFromMap,body);
            body.removeFromWorld();body.removeFromSquare();
        }
        return EquipmentPersistence.checkpointSquare(square);
    }
}
