package cvpworld;

import java.lang.reflect.Field;
import java.util.ArrayList;
import org.joml.Vector3f;
import sun.misc.Unsafe;
import zombie.vehicles.BaseVehicle.Passenger;
import zombie.characters.IsoPlayer;
import zombie.core.raknet.UdpConnection;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.vehicles.BaseVehicle;
import zombie.vehicles.BaseVehicle.Authorization;

/** Engine API feasibility checks, not a Bullet simulation or live multiplayer test. */
public class ValidateVehicleAuthority {
    static Unsafe unsafe;

    static Field field(Class<?> type,String name) throws Exception {
        Field f=type.getDeclaredField(name);f.setAccessible(true);return f;
    }
    static BaseVehicle vehicle() throws Exception {
        BaseVehicle v=(BaseVehicle)unsafe.allocateInstance(BaseVehicle.class);
        field(BaseVehicle.class,"impulsesFromHitObjects").set(v,new ArrayList<>());
        // No CarController/world: setPhysicsActive returns before JNI. The queue
        // and authorization methods still run unchanged.
        v.setNetPlayerAuthorization(Authorization.Server,-1);
        v.setX(10);v.setY(20);v.setZ(0);
        return v;
    }
    static IsoPlayer player(int id) throws Exception {
        IsoPlayer p=(IsoPlayer)unsafe.allocateInstance(IsoPlayer.class);
        p.onlineId=(short)id;return p;
    }
    static ArrayList<?> queue(BaseVehicle v) throws Exception {
        return (ArrayList<?>)field(BaseVehicle.class,"impulsesFromHitObjects").get(v);
    }
    static Vector3f vector(Object impulse,String name) throws Exception {
        return (Vector3f)field(impulse.getClass(),name).get(impulse);
    }
    static void check(boolean value,String message) {
        if(!value) throw new AssertionError(message);
    }
    static void near(Vector3f value,float x,float y,float z) {
        check(value.distance(x,y,z)<0.0001f,"unexpected native vector: "+value);
    }
    static void push(BaseVehicle v,float sign) {
        WorldBridge.applyVehicleImpulse(v,9,22,.5f,sign*3,sign*4,0,100);
    }

    static void equivalentQueue() throws Exception {
        BaseVehicle original=vehicle(),quiet=vehicle();
        for(float sign:new float[]{1,-1}) {
            original.applyImpulseGeneric(9,22,.5f,sign*3,sign*4,2,100);
            WorldBridge.applyVehicleImpulse(quiet,9,22,.5f,sign*3,sign*4,2,100);
        }
        check(queue(original).size()==2 && queue(quiet).size()==2,"impulses must accumulate");
        for(int i=0;i<2;i++) {
            Object a=queue(original).get(i),b=queue(quiet).get(i);
            for(String name:new String[]{"impulse","relPos"})
                check(vector(a,name).equals(vector(b,name)),"bridge differs from engine: "+name);
        }
        GameServer.server=true;GameClient.client=false;
        original.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        quiet.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        // Reuse engine-pooled entries, including their native lifecycle flags.
        push(quiet,-1);near(vector(queue(quiet).get(0),"impulse"),-60,0,-80);
        quiet.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        check(queue(quiet).isEmpty(),"reused queue entry was not released");
        GameServer.server=false;
        System.out.println("PASS quiet bridge matches native vectors, accumulation and pooled reuse");
    }

    static void queueAndRoles() throws Exception {
        BaseVehicle a=vehicle(),b=vehicle();
        push(a,1);push(b,-1);
        Object first=queue(a).get(0),second=queue(b).get(0);
        near(vector(first,"impulse"),60,0,80);
        near(vector(second,"impulse"),-60,0,-80);
        near(vector(first,"relPos"),-1,.5f,2);
        near(new Vector3f(vector(first,"impulse")).add(vector(second,"impulse")),0,0,0);
        near(new Vector3f(vector(first,"relPos")).cross(vector(first,"impulse")),40,200,-30);
        System.out.println("PASS real impulse queue: opposite vectors, coordinate axes, attachment lever arm");

        for(boolean server:new boolean[]{false,true}) {
            GameServer.server=server;GameClient.client=!server;
            for(Authorization auth:Authorization.values()) {
                a.setNetPlayerAuthorization(auth,auth==Authorization.Server?-1:101);
                boolean expected=server?auth==Authorization.Server:
                    auth==Authorization.Local || auth==Authorization.LocalCollide;
                check(a.isLocalPhysicSim()==expected,"unexpected role: "+server+" / "+auth);
            }
        }
        GameClient.client=false;GameServer.server=true;
        a.setNetPlayerAuthorization(Authorization.Server,-1);
        check(a.isLocalPhysicSim(),"server-owned vehicle fixture");
        a.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        b.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        check(queue(a).isEmpty() && queue(b).isEmpty(),"server did not discard impulses");
        // This returns without loading Bullet JNI: the actual server branch
        // releases queued forces, even though isLocalPhysicSim() above is true.
        System.out.println("PASS real server discards queued forces even for Server authorization");

        GameServer.server=false;GameClient.client=false;
        a.setNetPlayerAuthorization(Authorization.Server,-1);
        check(!a.isLocalPhysicSim(),"SP must not rely on the multiplayer flag alone");
        GameClient.client=true;
        IsoPlayer.setInstance(player(101));
        GameClient.connection=(UdpConnection)unsafe.allocateInstance(UdpConnection.class);
        a.setNetPlayerAuthorization(Authorization.Local,101);
        check(a.hasAuthorization(GameClient.connection),"owner must pass native ID check");
        push(a,1);
        a.setNetPlayerAuthorization(Authorization.Remote,202);
        check(!a.isLocalPhysicSim() && !a.hasAuthorization(GameClient.connection),"handoff did not revoke owner");
        a.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        check(queue(a).isEmpty(),"force queued before handoff survived revocation");
        a.setNetPlayerAuthorization(Authorization.Local,202);
        check(a.isLocalPhysicSim() && !a.hasAuthorization(GameClient.connection),"flag and connection ID are distinct checks");
        push(a,1);a.applyAccumulatedImpulsesFromHitObjectsToPhysics();
        check(queue(a).isEmpty(),"mismatched owner received queued force");
        System.out.println("PASS native owner ID checks and queue discard after ownership change");
    }

    static void nativeTowingOwnership() throws Exception {
        GameClient.client=false;GameServer.server=true;
        BaseVehicle a=vehicle(),b=vehicle();
        Passenger first=new Passenger(),second=new Passenger();
        first.character=player(101);second.character=player(202);
        field(BaseVehicle.class,"passengers").set(a,new Passenger[]{first});
        field(BaseVehicle.class,"passengers").set(b,new Passenger[]{second});
        a.setNetPlayerAuthorization(Authorization.Local,101);
        b.setNetPlayerAuthorization(Authorization.Local,202);
        field(BaseVehicle.class,"vehicleTowing").set(a,b);
        field(BaseVehicle.class,"vehicleTowedBy").set(b,a);
        a.constraintChanged();b.constraintChanged();
        check(a.getNetPlayerId()==101 && b.getNetPlayerId()==101,
            "native towing ownership behavior changed: re-evaluate two-driver support");
        check(b.getDriver().getOnlineID()==202,"fixture must still have a second driver");
        first.character=null;a.constraintChanged();b.constraintChanged();
        check(a.getNetPlayerId()==-1 && b.getNetPlayerId()==-1,
            "native constraint no longer follows towing driver's absence");
        // Once disconnected, each car's own driver controls its authorization.
        first.character=player(101);
        field(BaseVehicle.class,"vehicleTowing").set(a,null);
        field(BaseVehicle.class,"vehicleTowedBy").set(b,null);
        a.constraintChanged();b.constraintChanged();
        check(a.getNetPlayerId()==101 && b.getNetPlayerId()==202,"independent owners did not return");
        System.out.println("PASS native constraint assigns both cars to towing driver, including two occupied cars");
    }

    static void acceptedMotionPackets() throws Exception {
        var physics=zombie.core.physics.WorldSimulation.instance;
        long savedTime=physics.time;
        try {
            physics.time=12340;
            check(VehicleMotion.localTime()==12340,"local motion used render time instead of physics time");
        } finally { physics.time=savedTime; }

        java.lang.invoke.MethodHandles.publicLookup().findStatic(VehicleMotion.class,"received",
            java.lang.invoke.MethodType.methodType(void.class,
                zombie.network.packets.vehicle.VehiclePhysicsPacket.class,UdpConnection.class));

        GameServer.server=true;GameClient.client=false;
        BaseVehicle v=vehicle();
        var script=new zombie.scripting.objects.VehicleScript();
        for(String name:new String[]{"trailer","trailerfront"}) {
            var attachment=new zombie.scripting.objects.ModelAttachment(name);
            attachment.getOffset().set(0,0,name.equals("trailer")?-2:2);
            script.addAttachment(attachment);
        }
        field(BaseVehicle.class,"script").set(v,script);
        var transform=new zombie.core.physics.Transform();transform.basis.identity();transform.origin.set(10,0,20);
        field(BaseVehicle.class,"jniTransform").set(v,transform);
        v.setX(10);v.setY(20);v.setZ(0);v.setNetPlayerAuthorization(Authorization.Local,101);
        UdpConnection owner=(UdpConnection)unsafe.allocateInstance(UdpConnection.class);
        field(UdpConnection.class,"players").set(owner,new IsoPlayer[]{player(101)});
        var packet=new zombie.network.packets.vehicle.VehiclePhysicsPacket();
        ((zombie.network.fields.vehicle.VehicleID)field(packet.getClass(),"vehicleId").get(packet)).set(v);
        Field time=field(zombie.vehicles.VehicleInterpolationData.class,"time");time.setLong(packet,100);
        check(VehicleMotion.sample(v)==null,"watch should await first accepted packet");
        PatchVehicleMotion.exit(packet,owner);var first=VehicleMotion.sample(v);
        check(first!=null && (double)first.rawget("time")==100,"accepted packet time missing");
        check((double)first.rawget("hitchY")==18 && (double)first.rawget("frontY")==22,"attachment frames wrong");
        v.setY(25);transform.origin.z=25;time.setLong(packet,90);PatchVehicleMotion.exit(packet,owner);
        check(VehicleMotion.sample(v)==first,"older packet replaced motion state");
        time.setLong(packet,200);PatchVehicleMotion.exit(packet,owner);
        check((double)first.rawget("hitchY")==18,"old frame mutated");
        check((double)VehicleMotion.sample(v).rawget("hitchY")==23,"new frame missing");
        v.setNetPlayerAuthorization(Authorization.Local,202);
        check(VehicleMotion.sample(v)==null,"old owner frame survived handoff");
        PatchVehicleMotion.exit(packet,owner);
        check(VehicleMotion.sample(v)==null,"unauthorized sender created a frame");
        field(UdpConnection.class,"players").set(owner,new IsoPlayer[]{player(202)});
        time.setLong(packet,50);PatchVehicleMotion.exit(packet,owner);
        check((double)VehicleMotion.sample(v).rawget("owner")==202,"new owner did not reset packet clock");
        VehicleMotion.forget(v);check(VehicleMotion.sample(v)==null,"released history survived");VehicleMotion.forget(v);
        System.out.println("PASS accepted motion timestamps, immutable anchors, handoff and rejected sender");
    }

    public static void main(String[] args) throws Exception {
        zombie.core.random.RandStandard.INSTANCE.init();
        unsafe=(Unsafe)field(Unsafe.class,"theUnsafe").get(null);
        boolean client=GameClient.client,server=GameServer.server;
        IsoPlayer previous=IsoPlayer.getInstance();UdpConnection connection=GameClient.connection;
        try { equivalentQueue();queueAndRoles();nativeTowingOwnership();acceptedMotionPackets(); }
        finally {
            GameClient.client=client;GameServer.server=server;
            GameClient.connection=connection;IsoPlayer.setInstance(previous);
        }
        System.out.println("LIMIT: no world, Bullet step, vehicle movement or network transport was run");
    }
}
