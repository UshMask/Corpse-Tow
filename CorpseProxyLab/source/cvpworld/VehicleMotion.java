package cvpworld;

import java.lang.reflect.Field;
import java.util.WeakHashMap;
import org.joml.Vector3f;
import se.krka.kahlua.vm.KahluaTable;
import zombie.Lua.LuaManager;
import zombie.core.raknet.UdpConnection;
import zombie.network.GameServer;
import zombie.network.packets.vehicle.VehiclePhysicsPacket;
import zombie.vehicles.BaseVehicle;
import zombie.vehicles.VehicleInterpolationData;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;

/** Read-only observation of accepted vehicle packets; only watched towing vehicles. */
@LuaClass(name="CVPVehicleMotion")
public final class VehicleMotion {
    private static final WeakHashMap<BaseVehicle,KahluaTable> frames=new WeakHashMap<>();
    private static final Field TIME;
    static {
        try { TIME=VehicleInterpolationData.class.getDeclaredField("time");TIME.setAccessible(true); }
        catch(ReflectiveOperationException e){throw new ExceptionInInitializerError(e);}
    }
    /** Clock of the physics transforms read by the game thread; not render time. */
    public static long localTime() { return zombie.core.physics.WorldSimulation.instance.time; }
    public static KahluaTable sample(BaseVehicle vehicle) {
        if(!frames.containsKey(vehicle))frames.put(vehicle,null);
        KahluaTable frame=frames.get(vehicle);
        if(frame!=null && ((Number)frame.rawget("owner")).intValue()!=vehicle.getNetPlayerId()) {
            frames.put(vehicle,null);return null;
        }
        return frame;
    }
    public static void forget(BaseVehicle vehicle){frames.remove(vehicle);}
    // Advice is inlined into the engine packet class, outside cvpworld.
    public static void received(VehiclePhysicsPacket packet,UdpConnection connection) {
        BaseVehicle v=packet.getVehicle();
        if(!GameServer.server || v==null || !frames.containsKey(v) || !v.hasAuthorization(connection))return;
        try {
            long time=TIME.getLong(packet);KahluaTable previous=frames.get(v);
            if(previous!=null && ((Number)previous.rawget("owner")).intValue()==v.getNetPlayerId()
                && time<=((Number)previous.rawget("time")).longValue())return;
            KahluaTable row=LuaManager.platform.newTable();
            row.rawset("time",(double)time);row.rawset("owner",(double)v.getNetPlayerId());
            row.rawset("z",(double)v.getZ()+.25);
            Vector3f velocity=new Vector3f();packet.getVelocity(velocity);
            row.rawset("speed",Math.sqrt(velocity.x*velocity.x+velocity.z*velocity.z));
            point(row,v,"hitch","trailer",-1);point(row,v,"front","trailerfront",1);
            frames.put(v,row);
        } catch(IllegalAccessException e){throw new IllegalStateException("vehicle packet time unavailable",e);}
    }
    private static void point(KahluaTable row,BaseVehicle v,String key,String attachment,int sign) {
        Vector3f point=new Vector3f();
        if(v.attachmentExist(attachment))v.getAttachmentWorldPos(attachment,point);
        else v.getWorldPos(0,0,sign*v.getScript().getExtents().z/2,point);
        row.rawset(key+"X",(double)point.x);row.rawset(key+"Y",(double)point.y);
    }
}
