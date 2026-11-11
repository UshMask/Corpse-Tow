package cvpworld;

import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import se.krka.kahlua.vm.KahluaTable;
import se.krka.kahlua.j2se.J2SEPlatform;
import zombie.Lua.LuaManager;
import zombie.iso.IsoCell;
import zombie.iso.IsoWorld;
import zombie.iso.objects.IsoDeadBody;
import zombie.core.skinnedmodel.visual.HumanVisual;
import zombie.network.GameClient;
import zombie.network.GameServer;

public class ValidateSkeletonLifetime {
    static KahluaTable table(Object... values) {
        KahluaTable t=LuaManager.platform.newTable();
        for(int i=0;i<values.length;i+=2) t.rawset(values[i],values[i+1]);
        return t;
    }
    static void equal(double actual,double expected) {
        if(Math.abs(actual-expected)>1e-5) throw new AssertionError(actual+" != "+expected);
    }
    static KahluaTable reload(KahluaTable data) throws Exception {
        ByteBuffer buffer=ByteBuffer.allocate(16384);data.save(buffer);buffer.flip();
        KahluaTable copy=LuaManager.platform.newTable();copy.load(buffer,IsoWorld.getWorldVersion());return copy;
    }
    static void graphClocks() throws Exception {
        KahluaTable data=table();
        equal(SkeletonLifetime.clock(data,90,0,120,true,true),30); // Released 0.3 clock.
        var detached=new SkeletonLifetime.GraphClock("epoch",100,110,0,false);
        data=reload(data);
        equal(SkeletonLifetime.clock(data,125,0,120,true,false,detached),15);
        var rebound=new SkeletonLifetime.GraphClock("epoch",100,130,20,true);
        equal(SkeletonLifetime.clock(data,1000,0,120,true,true,rebound),10);
        data=reload(data);
        equal(SkeletonLifetime.clock(data,1020,0,120,true,false,
            new SkeletonLifetime.GraphClock("epoch",100,1010,20,false)),0);
        data=table();var loose=new SkeletonLifetime.GraphClock("loose",80,80,0,false);
        equal(SkeletonLifetime.clock(data,90,0,120,true,false,loose),30);
        equal(SkeletonLifetime.clock(data,95,0,112.5,true,false,loose),17.5);
        equal(SkeletonLifetime.clock(data,96,0,120,true,false,loose),24);
        equal(SkeletonLifetime.clock(data,1000,0,120,true,true,
            new SkeletonLifetime.GraphClock("loose",80,110,30,true)),10);
        data=table();var fresh=new SkeletonLifetime.GraphClock("fresh",80,80,0,true);
        if(!Double.isNaN(SkeletonLifetime.clock(data,90,0,240,false,true,fresh)) || !data.isEmpty())
            throw new AssertionError("fresh graph body gained a removal timer");
        equal(SkeletonLifetime.clock(data,180,0,240,true,true,fresh),60);
        // Retirement returns to the ordinary body clock; a later enrollment
        // starts a new epoch without resetting age or using an old counter.
        equal(SkeletonLifetime.clock(data,200,0,240,true,false,
            new SkeletonLifetime.GraphClock("fresh",80,190,0,false)),50);
        equal(SkeletonLifetime.clock(data,210,0,240,true,false),40);
        equal(SkeletonLifetime.clock(data,1000,0,240,true,true,
            new SkeletonLifetime.GraphClock("new",220,220,0,true)),30);
        System.out.println("PASS graph skeleton clocks: legacy migration, unloaded detach/reattach, exact elapsed time, fresh bodies and new epochs");
    }
    static void ledgerBootstrap(IsoDeadBody body) throws Exception {
        var fs=zombie.ZomboidFileSystem.instance;var core=zombie.core.Core.getInstance();
        String previousCache=fs.getCacheDir(),previousWorld=zombie.core.Core.gameSaveWorld;
        Thread previousThread=GameServer.mainThread;boolean previousNoSave=core.isNoSave();
        Path home=Path.of(System.getProperty("user.home")).toRealPath();
        Path directory=Files.createTempDirectory(home,"skeleton-clock-").toRealPath();
        if(!directory.startsWith(home) || directory.equals(home)) throw new AssertionError("invalid isolated directory");
        try {
            fs.setCacheDir(directory.toString());zombie.core.Core.gameSaveWorld="first";
            GameServer.mainThread=Thread.currentThread();core.setNoSave(false);
            Path world=Path.of(fs.getCurrentSaveDir()).toAbsolutePath().normalize();
            if(!world.startsWith(directory.toAbsolutePath().normalize())) throw new AssertionError("test escaped isolated home");
            Files.createDirectories(world);
            var row=table("epoch","durable","started",90.0,"at",90.0,"elapsed",0.0,"paused",true);
            var ledger=table("version",3.0,"rows",table(),"bodyClocks",table("body",row));
            EquipmentPersistence.write(ledger);
            body.getModData().rawset("CVPTether",null);body.getModData().rawset("CVPSkeletonRemoval",null);
            PatchSkeletonUpdate.enter();
            try {PatchSkeletonRotting.exit(body,90,30);equal(90-body.getDeathTime(),90);}
            finally {PatchSkeletonUpdate.exit();}
            KahluaTable saved=reload(body.getModData());
            if(SkeletonLifetime.retire(body,"durable")) throw new AssertionError("rooted clock retired");
            byte[] before=Files.readAllBytes(world.resolve("CVPEquipment.bin"));row.rawset("paused","invalid");
            try {EquipmentPersistence.write(ledger);throw new AssertionError("invalid clock written");}
            catch(IllegalArgumentException expected) {}
            if(!Arrays.equals(before,Files.readAllBytes(world.resolve("CVPEquipment.bin")))) throw new AssertionError("clock validation changed committed ledger");
            // The root was detached while this chunk was absent. Write only the
            // durable file, clear the native cache, and run the actual hooks.
            row.rawset("paused",false);row.rawset("at",100.0);
            EquipmentPersistence.writeFile(world.resolve("CVPEquipment.bin"),ledger,
                (a,b)->Files.move(a,b,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING));
            var loaded=SkeletonLifetime.class.getDeclaredField("loadedSave");loaded.setAccessible(true);loaded.set(null,null);
            body.getModData().rawset("CVPSkeletonRemoval",saved.rawget("CVPSkeletonRemoval"));
            PatchSkeletonUpdate.enter();
            try {PatchSkeletonRotting.exit(body,110,30);equal(110-body.getDeathTime(),100);}
            finally {PatchSkeletonUpdate.exit();}
            equal(body.getDeathTime(),0);
            if(SkeletonLifetime.retire(body,"wrong")) throw new AssertionError("wrong epoch acknowledged");
            if(!SkeletonLifetime.retire(body,"durable")) throw new AssertionError("unbound clock not acknowledged");
            zombie.core.Core.gameSaveWorld="second";world=Path.of(fs.getCurrentSaveDir());Files.createDirectories(world);
            body.getModData().rawset("CVPSkeletonRemoval",null);
            PatchSkeletonUpdate.enter();
            try {PatchSkeletonRotting.exit(body,200,30);equal(body.getDeathTime(),0);}
            finally {PatchSkeletonUpdate.exit();}
            if(body.getModData().rawget("CVPSkeletonRemoval")!=null) throw new AssertionError("clock leaked into another world");
            System.out.println("PASS native graph clock bootstrap before Lua, atomic clock validation, retirement and world isolation");
        } finally {
            fs.setCacheDir(previousCache);zombie.core.Core.gameSaveWorld=previousWorld;GameServer.mainThread=previousThread;core.setNoSave(previousNoSave);
            SkeletonLifetime.install(null);
            try(var files=Files.walk(directory)) {for(Path path:files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);}
        }
    }
    public static void main(String[] args) throws Exception {
        LuaManager.platform=new J2SEPlatform();LuaManager.env=table();
        zombie.core.random.RandStandard.INSTANCE.init();GameServer.server=true;
        zombie.ZomboidFileSystem.instance.base.set(new java.io.File(System.getProperty("user.home")));
        zombie.SandboxOptions.instance.hoursForCorpseRemoval.setValue(90);
        SkeletonLifetime.install(null);
        graphClocks();
        KahluaTable data=table();
        if(!Double.isNaN(SkeletonLifetime.clock(data,90,0,120,false,true)) || !data.isEmpty())
            throw new AssertionError("fresh corpse age changed");
        if(!Double.isNaN(SkeletonLifetime.clock(data,90,0,120,true,false)) || !data.isEmpty())
            throw new AssertionError("unbound skeleton changed");
        equal(SkeletonLifetime.clock(data,90,0,120,true,true),30);
        data=reload(data); // unloaded/reloaded after 1000 world hours: still 30 left
        equal(SkeletonLifetime.clock(data,1090,0,120,true,true),30);
        equal(SkeletonLifetime.clock(data,1100,0,120,true,false),30);
        data=reload(data);
        equal(SkeletonLifetime.clock(data,1110,0,120,true,false),20);
        equal(SkeletonLifetime.clock(data,1115,0,120,true,true),15);
        equal(SkeletonLifetime.clock(data,2115,0,120,true,false),15);
        equal(SkeletonLifetime.clock(data,2130,0,120,true,false),0);
        equal(SkeletonLifetime.clock(data,2120,0,120,true,false),0); // clock rewind never adds time
        System.out.println("PASS skeleton clock: pause, native serialization, unload, detach, reattach, expiry");

        KahluaTable a=table("kind","vehicle","key","car");
        KahluaTable md=table("version",3.0,"connection",table("id","link","a",a,"b",table("kind","body","key","body")));
        data=table("CVPTether",md,"CVPBodyKey","body");
        if(!SkeletonLifetime.attached(data)) throw new AssertionError("root not held");
        a.rawset("kind","body");a.rawset("key","parent");
        if(SkeletonLifetime.attached(data)) throw new AssertionError("unrooted chain held");
        md.rawset("parentConnection","parent-link");md.rawset("rootVehicle","car");
        if(!SkeletonLifetime.attached(data)) throw new AssertionError("rooted child not held");
        data.rawset("CorpseTowingVehicleToken","other");
        if(SkeletonLifetime.attached(data)) throw new AssertionError("foreign owner held");
        data.rawset("CorpseTowingVehicleToken",null);
        data.rawset("CVPBodyKey","replacement");
        if(SkeletonLifetime.attached(data)) throw new AssertionError("stale marker held");
        data.rawset("CVPBodyKey","body");

        IsoDeadBody body=new IsoDeadBody((IsoCell)null);
        Field visual=IsoDeadBody.class.getDeclaredField("baseVisual");visual.setAccessible(true);visual.set(body,new HumanVisual(body));
        Field skeleton=IsoDeadBody.class.getDeclaredField("wasSkeleton");skeleton.setAccessible(true);skeleton.setBoolean(body,true);
        body.getModData().rawset("CVPTether",md);body.getModData().rawset("CVPBodyKey","body");body.setDeathTime(0);
        PatchSkeletonUpdate.enter();
        try {
            PatchSkeletonRotting.exit(body,90,30);
            equal(90-body.getDeathTime(),90);
            PatchSkeletonRotting.exit(body,1090,30);
            if(1090-body.getDeathTime()>=120) throw new AssertionError("held skeleton expired");
        } finally { PatchSkeletonUpdate.exit(); }
        equal(body.getDeathTime(),0);
        body.getModData().rawset("CVPTether",null);
        PatchSkeletonUpdate.enter();
        try { PatchSkeletonRotting.exit(body,1100,30);equal(1100-body.getDeathTime(),90); }
        finally { PatchSkeletonUpdate.exit(); }
        PatchSkeletonUpdate.enter();
        try { PatchSkeletonRotting.exit(body,1130,30);equal(1130-body.getDeathTime(),120); }
        finally { PatchSkeletonUpdate.exit(); }
        equal(body.getDeathTime(),0);
        GameClient.client=true;PatchSkeletonUpdate.enter();PatchSkeletonRotting.exit(body,5000,30);PatchSkeletonUpdate.exit();
        equal(body.getDeathTime(),0);GameClient.client=false;
        body.getModData().rawset("CVPSkeletonRemoval",null);
        body.getModData().rawset("CVPTether",md);
        PatchSkeletonUpdate.enter();
        try {
            PatchSkeletonRotting.exit(body,90,22.5f);
            equal(((KahluaTable)body.getModData().rawget("CVPSkeletonRemoval")).rawget("remaining") instanceof Number n?n.doubleValue():-1,22.5);
            PatchSkeletonRotting.exit(body,10000000,22.5f);
            if(10000000-body.getDeathTime()>=112.5f) throw new AssertionError("held skeleton expired at large world age");
        } finally { PatchSkeletonUpdate.exit(); }
        equal(body.getDeathTime(),0);
        System.out.println("PASS native skeleton hooks: engine expiry comparison, death date restored, MP client ignored");
        ledgerBootstrap(body);
    }
}
