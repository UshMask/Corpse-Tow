package cvpworld;

import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import sun.misc.Unsafe;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.j2se.KahluaTableImpl;
import se.krka.kahlua.vm.KahluaTable;
import zombie.Lua.LuaManager;
import zombie.inventory.InventoryItem;
import zombie.inventory.ItemContainer;
import zombie.inventory.types.ComboItem;
import zombie.iso.IsoWorld;
import zombie.iso.objects.IsoDeadBody;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.core.skinnedmodel.animation.TwistableBoneTransform;
import zombie.util.Pool;
import zombie.world.moddata.GlobalModData;

public class ValidateWorld {
    public static void main(String[] args) throws Exception {
        Field unsafeField=Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
        IsoDeadBody body=(IsoDeadBody)((Unsafe)unsafeField.get(null)).allocateInstance(IsoDeadBody.class);
        Field poseField=IsoDeadBody.class.getDeclaredField("diedBoneTransforms");poseField.setAccessible(true);
        TwistableBoneTransform[] pose=TwistableBoneTransform.allocArray(2);
        pose[0].twist=0.37f;pose[1].blendWeight=0.83f;poseField.set(body,pose);
        Runnable release=()->{
            try {poseField.set(body,Pool.tryRelease(body.getDiedBoneTransforms()));}
            catch(IllegalAccessException e) {throw new RuntimeException(e);}
        };
        for(int i=0;i<10;i++) {
            WorldBridge.preservePose(body,release);
            if(body.getDiedBoneTransforms()!=pose || pose[0].isFree() || pose[1].isFree()
                || pose[0].twist!=0.37f || pose[1].blendWeight!=0.83f)
                throw new AssertionError("native pose was released or modified");
        }
        try {WorldBridge.preservePose(body,()->{release.run();throw new IllegalStateException("injected");});}
        catch(IllegalStateException e) {if(!"injected".equals(e.getMessage())) throw e;}
        if(body.getDiedBoneTransforms()!=pose || pose[0].isFree()) throw new AssertionError("exception lost pose");
        release.run();
        if(body.getDiedBoneTransforms()!=null || !pose[0].isFree()) throw new AssertionError("destructor model did not release pose");
        WorldBridge.preservePose(body,release);
        if(body.getDiedBoneTransforms()!=null) throw new AssertionError("null pose changed");
        System.out.println("PASS native pooled bone identity/values, repeated moves, exception restoration and null pose");
        validateReadPass((Unsafe)unsafeField.get(null));
        validateAngle((Unsafe)unsafeField.get(null));
        validateItems();
        validatePersistence();
        validateAsyncPersistence();
        validateCosmeticPersistence();
        validateClothingPersistence();
    }
    static void validateAngle(Unsafe unsafe) throws Exception {
        var body=(IsoDeadBody)unsafe.allocateInstance(IsoDeadBody.class);
        var direction=IsoDeadBody.class.getDeclaredField("forwardDirection");direction.setAccessible(true);
        direction.set(body,new zombie.iso.Vector2());
        body.setDir(zombie.iso.IsoDirections.N);
        var atlas=IsoDeadBody.class.getDeclaredField("atlasTex");atlas.setAccessible(true);
        Object image=unsafe.allocateInstance(atlas.getType());
        boolean chunks=zombie.core.PerformanceSettings.fboRenderChunk;
        zombie.core.PerformanceSettings.fboRenderChunk=false;
        try {
            body.setForwardDirectionAngle(.1f);atlas.set(body,image);
            double computed=.1;
            if((double)body.getAngle()==computed) throw new AssertionError("fixture needs double/float mismatch");
            for(int i=0;i<100;i++) WorldBridge.setAngle(body,(float)computed);
            if(atlas.get(body)!=image) throw new AssertionError("unchanged float angle invalidated");
            float changed=Math.nextUp(body.getAngle());
            WorldBridge.setAngle(body,changed);
            if(body.getAngle()!=changed || atlas.get(body)!=image) throw new AssertionError("same atlas key invalidated or exact angle lost");
            atlas.set(body,image);WorldBridge.setAngle(body,.1f);
            if(body.getAngle()!=.1f || atlas.get(body)!=image) throw new AssertionError("same-key rollback angle lost");
            var params=new zombie.core.skinnedmodel.DeadBodyAtlas.BodyParams();
            params.baseVisual=new zombie.core.skinnedmodel.visual.HumanVisual(null) {
                public String getHairModel() { return ""; }
                public String getBeardModel() { return ""; }
                public String getSkinTexture() { return "MaleBody01"; }
                public zombie.core.ImmutableColor getSkinColor() { return zombie.core.ImmutableColor.white; }
                public zombie.core.ImmutableColor getHairColor() { return zombie.core.ImmutableColor.white; }
                public zombie.core.ImmutableColor getBeardColor() { return zombie.core.ImmutableColor.white; }
            };
            params.animSetName="zombie";params.stateName="onground";
            var key=zombie.core.skinnedmodel.DeadBodyAtlas.class.getDeclaredMethod("getBodyKey",params.getClass());
            key.setAccessible(true);
            // Compare against the engine's real key, including degree boundaries,
            // wrap, negative headings and rollback. No duplicated bucket formula in tests.
            float[] angles={.1f,Math.nextUp(.1f),.11f,.12f,.1f,-.001f,0f,.001f,
                6.2831855f,6.2831855f+.001f,-6.2831855f,12.566371f,
                (float)Math.toRadians(22.49),(float)Math.toRadians(22.51),
                (float)Math.toRadians(89.99),(float)Math.toRadians(90.01)};
            for(float from:angles) for(float to:angles) {
                body.setForwardDirectionAngle(from);
                params.angle=from;params.dir=body.getForwardIsoDirection();
                Object oldKey=key.invoke(zombie.core.skinnedmodel.DeadBodyAtlas.instance,params);
                body.setForwardDirectionAngle(to);
                params.angle=to;params.dir=body.getForwardIsoDirection();
                Object newKey=key.invoke(zombie.core.skinnedmodel.DeadBodyAtlas.instance,params);
                if(oldKey==null || newKey==null || oldKey.equals("bogus") || newKey.equals("bogus"))
                    throw new AssertionError("atlas fixture did not produce a real key: "+oldKey+" / "+newKey+", dir="+params.dir);
                body.setForwardDirectionAngle(from);atlas.set(body,image);
                WorldBridge.setAngle(body,to);
                if(body.getAngle()!=to || (atlas.get(body)==image)!=oldKey.equals(newKey))
                    throw new AssertionError("atlas key/angle mismatch: "+from+" -> "+to);
            }
        } finally {zombie.core.PerformanceSettings.fboRenderChunk=chunks;}
        System.out.println("PASS exact world angles and native atlas-key invalidation including direction, wrap and rollback");
    }
    static zombie.iso.IsoGridSquare readSquare(Unsafe unsafe) throws Exception {
        var square=(zombie.iso.IsoGridSquare)unsafe.allocateInstance(zombie.iso.IsoGridSquare.class);
        var objects=zombie.iso.IsoGridSquare.class.getDeclaredField("staticMovingObjects");objects.setAccessible(true);
        objects.set(square,new java.util.ArrayList<zombie.iso.IsoMovingObject>());return square;
    }
    static void validateReadPass(Unsafe unsafe) throws Exception {
        LuaManager.platform=new J2SEPlatform();
        var square=readSquare(unsafe);
        IsoDeadBody[] bodies=new IsoDeadBody[32];
        Field angle=IsoDeadBody.class.getDeclaredField("angle");angle.setAccessible(true);
        KahluaTable records=LuaManager.platform.newTable();
        for(int i=0;i<32;i++) {
            var b=(IsoDeadBody)unsafe.allocateInstance(IsoDeadBody.class);b.setSquare(square);b.setX(i);b.setY(2);angle.setFloat(b,.25f);
            bodies[i]=b;square.getStaticMovingObjects().add(b);
            var r=LuaManager.platform.newTable();r.rawset("body",b);records.rawset(i+1,r);
        }
        var pass=WorldBridge.beginRead();WorldBridge.readPoses(pass,records);
        if(pass.squares.size()!=1 || pass.squares.get(square).size()!=32) throw new AssertionError("one common square index required");
        var first=(KahluaTable)((KahluaTable)records.rawget(1)).rawget("before");
        bodies[0].setX(1.25f);WorldBridge.readPoses(pass,records);
        if(first!=((KahluaTable)records.rawget(1)).rawget("before") || !Double.valueOf(1.25).equals(first.rawget("x")))
            throw new AssertionError("pose read reused stale coordinates or replaced destination");
        java.util.Collections.reverse(square.getStaticMovingObjects());
        for(var b:bodies) if(!WorldBridge.contains(pass,b)) throw new AssertionError("reordered member lost");
        square.getStaticMovingObjects().set(square.getStaticMovingObjects().indexOf(bodies[0]),bodies[1]);
        if(WorldBridge.contains(pass,bodies[0])) throw new AssertionError("same-size list replacement accepted stale membership");
        try {WorldBridge.readPoses(pass,records);throw new AssertionError("missing body accepted");}
        catch(IllegalStateException expected) { }
        if(bodies[0].getX()!=1.25f) throw new AssertionError("read mutated body");
        var other=readSquare(unsafe);
        bodies[0].setSquare(other);
        if(WorldBridge.contains(pass,bodies[0])) throw new AssertionError("unregistered destination accepted");
        other.getStaticMovingObjects().add(bodies[0]);if(!WorldBridge.contains(pass,bodies[0])) throw new AssertionError("new destination missing");
        bodies[0].setSquare(null);if(WorldBridge.contains(pass,bodies[0])) throw new AssertionError("unloaded body accepted");
        System.out.println("PASS grouped pose reads, shared square index, reorder/replacement/unload and live destination validation");
    }
    // Real item serialization with only the texture-asset bootstrap bypassed.
    static class HeadlessClothing extends zombie.inventory.types.Clothing {
        HeadlessClothing() { super("Base","Shirt","Shirt","Item_Shirt",null,null); }
        public zombie.core.skinnedmodel.visual.ItemVisual getVisual() { return visual; }
        public void synchWithVisual() { }
        void initVisual() { visual=new zombie.core.skinnedmodel.visual.ItemVisual(); }
    }
    static HeadlessClothing clothing() throws Exception {
        var c=new HeadlessClothing();c.setScriptItem(new zombie.scripting.objects.Item());
        Field field=InventoryItem.class.getDeclaredField("registryId");field.setAccessible(true);field.setShort(c,(short)123);
        c.initVisual();return c;
    }
    static void validateClothingPersistence() throws Exception {
        for(int condition:new int[]{7,0}) {
        var source=clothing();source.setID(600);source.setCondition(condition);
        var part=zombie.characterTextures.BloodBodyPartType.Torso_Upper;
        source.getVisual().setHole(part);source.getModData().rawset("CVPTowWear",true);
        ByteBuffer data=ByteBuffer.allocate(65536);source.saveWithSize(data,false);data.flip();data.position(7);
        var restored=clothing();restored.load(data,IsoWorld.getWorldVersion());
        if(restored.getID()!=600 || restored.getCondition()!=condition || restored.getVisual().getHole(part)==0
            || !Boolean.TRUE.equals(restored.getModData().rawget("CVPTowWear")))
            throw new AssertionError("clothing wear lost during native save/load");
        if(condition==0 && !restored.isBroken()) throw new AssertionError("broken clothing flag lost");
        }
        System.out.println("PASS native clothing condition/hole/identity/modData persistence");
    }
    static void validateCosmeticPersistence() throws Exception {
        var part=zombie.characterTextures.BloodBodyPartType.Torso_Upper;
        var source=new zombie.core.skinnedmodel.visual.HumanVisual(null);
        source.setBlood(part,.65f);source.setDirt(part,.75f);
        ByteBuffer data=ByteBuffer.allocate(65536);
        source.save(data);data.flip();
        var restored=new zombie.core.skinnedmodel.visual.HumanVisual(null);
        restored.load(data,IsoWorld.getWorldVersion());
        if(source.getBlood(part)!=restored.getBlood(part) || source.getDirt(part)!=restored.getDirt(part))
            throw new AssertionError("skin overlays lost during native save/load");
        System.out.println("PASS native skin blood/dirt persistence");
    }
    interface Checked { void run() throws Exception; }
    static void rejects(Checked action) throws Exception {
        try { action.run(); } catch(Exception expected) { return; }
        throw new AssertionError("invalid item snapshot accepted");
    }
    static void rejectsMessage(String message,Checked action) throws Exception {
        try { action.run(); } catch(IllegalArgumentException expected) {
            if(message.equals(expected.getMessage())) return;
            throw expected;
        }
        throw new AssertionError("snapshot validation budget did not reject input");
    }
    static ComboItem item(String type,short registry) throws Exception {
        var item=new ComboItem("Base",type,type,"Item_Rope");
        item.setScriptItem(new zombie.scripting.objects.Item());
        // Test-only registry identity. A real ScriptManager/WorldDictionary needs game bootstrap.
        Field field=InventoryItem.class.getDeclaredField("registryId");field.setAccessible(true);field.setShort(item,registry);
        return item;
    }
    static String withBytes(String payload,byte[] bytes) throws Exception {
        String[] fields=payload.split(":",6);
        return String.join(":",Arrays.copyOf(fields,4))+":"
            +HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))+":"
            +Base64.getEncoder().encodeToString(bytes);
    }
    static String persisted(String payload) throws Exception {
        String name="CVPItemCodecValidation";
        var global=GlobalModData.instance;
        if(global.exists(name)) throw new AssertionError("test table already exists");
        var table=global.getOrCreate(name);table.rawset("payload",payload);table.rawset("revision",1.0);
        ByteBuffer buffer=ByteBuffer.allocate(ItemCodec.MAX_TEXT+1024);table.save(buffer);
        var file=Files.createTempFile("cvp-item-codec-",".bin");
        try {
            Files.write(file,Arrays.copyOf(buffer.array(),buffer.position()));
            var restored=LuaManager.platform.newTable();
            var saved=ByteBuffer.wrap(Files.readAllBytes(file));restored.load(saved,IsoWorld.getWorldVersion());
            if(saved.hasRemaining()) throw new AssertionError("table serialization left trailing bytes");
            global.add(name,restored);
            if(!Double.valueOf(1).equals(global.get(name).rawget("revision"))) throw new AssertionError("table revision lost");
            return (String)global.get(name).rawget("payload");
        } finally { global.remove(name);Files.deleteIfExists(file); }
    }
    static void validateItems() throws Exception {
        zombie.core.random.RandStandard.INSTANCE.init();GameServer.server=true;
        LuaManager.platform=new J2SEPlatform();LuaManager.env=LuaManager.platform.newTable();
        int sequence=0;
        for(String type:new String[]{"Rope","HeavyChain","HeavyChain_Hook"}) {
            short registry=(short)(100+sequence++);
            var original=item(type,registry);original.setID(1234567+sequence);
            original.setConditionMax(10);original.setConditionNoSound(7);
            original.setName("Named "+type);original.setCustomName(true);original.setFavorite(true,false);
            original.setActualWeight(2.75f);original.setCustomWeight(true);
            var nested=LuaManager.platform.newTable();nested.rawset("number",42.0);nested.rawset("flag",true);
            original.getModData().rawset("personal",nested);original.getModData().rawset("text","keepsake");
            var source=new ItemContainer();source.AddItem(original);
            String payload=ItemCodec.encode(original);
            if(!payload.equals(persisted(payload))) throw new AssertionError("GlobalModData table changed payload");
            for(int i=0;i<3;i++) {
                var restored=ItemCodec.decode(payload,item(type,registry));
                var data=(KahluaTable)restored.getModData().rawget("personal");
                if(restored==original || restored.getID()!=original.getID() || restored.getCondition()!=7
                    || !original.getFullType().equals(restored.getFullType()) || !original.getName().equals(restored.getName())
                    || !restored.isCustomName() || !restored.isFavorite() || !restored.isCustomWeight()
                    || restored.getActualWeight()!=2.75f || !"keepsake".equals(restored.getModData().rawget("text"))
                    || !Double.valueOf(42).equals(data.rawget("number")) || !Boolean.TRUE.equals(data.rawget("flag"))
                    || restored.getContainer()!=null || restored.getWorldItem()!=null)
                    throw new AssertionError("native material state or detached ownership lost: "+type);
            }
            if(source.getItems().size()!=1 || source.getItems().get(0)!=original || original.getContainer()!=source
                || !payload.equals(ItemCodec.encode(original))) throw new AssertionError("codec mutated source item");
            byte[] bytes=Base64.getDecoder().decode(payload.substring(payload.lastIndexOf(':')+1));
            rejects(()->ItemCodec.decode(null));
            rejects(()->ItemCodec.decode("CVPITEM2"+payload.substring(8),item(type,registry)));
            rejects(()->ItemCodec.decode(payload.replace(":"+IsoWorld.getWorldVersion()+":",":0:"),item(type,registry)));
            rejects(()->ItemCodec.decode(payload.replace(":"+original.getID()+":",":5:"),item(type,registry)));
            rejects(()->ItemCodec.decode(payload.replace(":Base."+type+":",":Base.Pen:"),item(type,registry)));
            rejects(()->ItemCodec.decode(payload.substring(0,payload.lastIndexOf(':')+1)+"!bad!",item(type,registry)));
            byte[] changed=bytes.clone();changed[changed.length-1]^=1;
            rejects(()->ItemCodec.decode(payload.substring(0,payload.lastIndexOf(':')+1)
                +Base64.getEncoder().encodeToString(changed),item(type,registry)));
            rejects(()->ItemCodec.decode(withBytes(payload,Arrays.copyOf(bytes,bytes.length-1)),item(type,registry)));
            byte[] trailing=Arrays.copyOf(bytes,bytes.length+1);ByteBuffer.wrap(trailing).putInt(trailing.length-4);
            rejects(()->ItemCodec.decode(withBytes(payload,trailing),item(type,registry)));
            rejects(()->ItemCodec.decode(withBytes(payload,new byte[ItemCodec.MAX_BYTES+1]),item(type,registry)));
            rejects(()->ItemCodec.decode("x".repeat(ItemCodec.MAX_TEXT+1)));
            rejects(()->ItemCodec.decode(payload,original)); // Never overwrite an owned item, even in the test seam.
            original.getModData().rawset("unsupported",original);
            if(KahluaTableImpl.canSave("unsupported",original)) throw new AssertionError("unexpected userdata serialization support");
            rejects(()->ItemCodec.encode(original));original.getModData().rawset("unsupported",null);
            original.getModData().rawset("cycle",original.getModData());
            rejects(()->ItemCodec.encode(original));original.getModData().rawset("cycle",null);
            original.getModData().rawset("large","x".repeat(ItemCodec.MAX_BYTES));
            rejects(()->ItemCodec.encode(original));original.getModData().rawset("large",null);
            original.getModData().rawset("large","x".repeat(ItemCodec.MAX_BYTES+1));
            rejectsMessage("item string exceeds snapshot budget",()->ItemCodec.encode(original));
            original.getModData().rawset("large",null);
            // Only 21 allocated tables, but recursive serialization expands their shared branches.
            KahluaTable shared=LuaManager.platform.newTable();shared.rawset("leaf",true);
            for(int i=0;i<20;i++) {
                KahluaTable parent=LuaManager.platform.newTable();parent.rawset("left",shared);parent.rawset("right",shared);shared=parent;
            }
            original.getModData().rawset("shared",shared);
            rejectsMessage("item modData exceeds snapshot budget",()->ItemCodec.encode(original));
            original.getModData().rawset("shared",null);
            GameClient.client=true;
            try { rejects(()->ItemCodec.encode(original));rejects(()->ItemCodec.decode(payload,item(type,registry))); }
            finally { GameClient.client=false; }
        }
        rejects(()->ItemCodec.encode(item("Pen",(short)103)));
        rejects(()->ItemCodec.encode(item("Rope",(short)-1)));
        System.out.println("PASS native item codec: three materials, ID/name/condition/favorite/custom weight/nested modData, GlobalModData table/file roundtrip, malformed/oversized data and role guards");
        System.out.println("Scope: supplied native load targets; no script-factory bootstrap, live ownership transfer, global_mod_data.bin transaction or crash recovery");
    }
    static void validateAsyncPersistence() throws Exception {
        var fs=zombie.ZomboidFileSystem.instance;var core=zombie.core.Core.getInstance();
        String cache=fs.getCacheDir(),world=zombie.core.Core.gameSaveWorld;
        boolean server=GameServer.server,client=GameClient.client,noSave=core.isNoSave();
        Thread main=GameServer.mainThread;
        var directory=Files.createTempDirectory("cvp-async-save-");
        try {
            fs.setCacheDir(directory.toString());zombie.core.Core.gameSaveWorld="async";
            GameServer.server=true;GameClient.client=false;GameServer.mainThread=Thread.currentThread();core.setNoSave(false);
            var save=java.nio.file.Path.of(fs.getCurrentSaveDir());Files.createDirectories(save);
            var unsafeField=Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
            var unsafe=(Unsafe)unsafeField.get(null);
            var offline=(zombie.characters.IsoPlayer)unsafe.allocateInstance(zombie.characters.IsoPlayer.class);
            if(EquipmentPersistence.playerKeyAsync(offline)!=null || EquipmentPersistence.playerKey(offline)!=null
                    || EquipmentPersistence.checkpointPlayerAsync(offline)!=null || EquipmentPersistence.checkpointPlayer(offline))
                throw new AssertionError("disconnected owner must stay unavailable without a save job");
            var data=LuaManager.platform.newTable();data.rawset("version",1.0);data.rawset("rows",LuaManager.platform.newTable());
            data.rawset("marker","before");var write=EquipmentPersistence.writeAsync(data);data.rawset("marker","after");
            finishJob(write);
            if(!"before".equals(EquipmentPersistence.readFile(save.resolve("CVPEquipment.bin")).rawget("marker")))
                throw new AssertionError("worker observed mutable Lua data");
            Object task=new Object();var started=new java.util.concurrent.CountDownLatch(1);
            var release=new java.util.concurrent.CountDownLatch(1);Thread game=Thread.currentThread();int[] accepted={0};
            var job=EquipmentPersistence.checkpointJob(task,()->false,()->{
                if(Thread.currentThread()==game) throw new AssertionError("readback blocked game thread");
                started.countDown();if(!release.await(2,java.util.concurrent.TimeUnit.SECONDS)) throw new AssertionError("reader not released");return true;
            });
            job.accepted=()->{if(Thread.currentThread()!=game) throw new AssertionError("accept off game thread");accepted[0]++;};
            if(EquipmentPersistence.poll(job)!=0 || started.getCount()!=1) throw new AssertionError("readback before native acknowledgement");
            EquipmentPersistence.completed(task);
            if(EquipmentPersistence.poll(job)!=0) throw new AssertionError("readback completed while blocked");
            if(!started.await(1,java.util.concurrent.TimeUnit.SECONDS)) throw new AssertionError("reader not started");
            // Completion latch survives draining/releasing the engine's original save task.
            if(EquipmentPersistence.poll(job)!=0) throw new AssertionError("pending reader ignored");
            release.countDown();finishJob(job);EquipmentPersistence.result(job);
            if(accepted[0]!=1) throw new AssertionError("duplicate save completion");
            int[] rejected={0};var bad=new EquipmentPersistence.SaveJob();
            bad.future=java.util.concurrent.CompletableFuture.failedFuture(new java.io.IOException("injected disk failure"));
            bad.rejected=()->rejected[0]++;
            rejects(()->EquipmentPersistence.poll(bad));rejects(()->EquipmentPersistence.poll(bad));
            if(rejected[0]!=1) throw new AssertionError("repeated failure side effects");
            // A failed atomic write cannot destroy the previous ledger.
            byte[] previous=Files.readAllBytes(save.resolve("CVPEquipment.bin"));
            var temporary=save.resolve("CVPEquipment.bin.tmp");Files.createDirectory(temporary);Files.writeString(temporary.resolve("occupied"),"keep");
            var failed=EquipmentPersistence.writeAsync(data);rejects(()->finishJob(failed));
            if(!Arrays.equals(previous,Files.readAllBytes(save.resolve("CVPEquipment.bin")))) throw new AssertionError("failed write replaced ledger");
            zombie.core.Core.gameSaveWorld="different";Files.createDirectories(java.nio.file.Path.of(fs.getCurrentSaveDir()));
            rejects(()->EquipmentPersistence.result(write));
            // Verify names/signatures of the two completion hooks against this engine build.
            zombie.savefile.PlayerDB.class.getDeclaredMethod("releasePlayerData",Class.forName("zombie.savefile.PlayerDB$PlayerData"));
            Class.forName("zombie.network.ServerChunkLoader$SaveLoadedTask").getDeclaredMethod("release");
        } finally {
            fs.setCacheDir(cache);zombie.core.Core.gameSaveWorld=world;GameServer.mainThread=main;
            GameServer.server=server;GameClient.client=client;core.setNoSave(noSave);
            try(var files=Files.walk(directory)) { for(var file:files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(file); }
        }
        System.out.println("PASS asynchronous persistence: immutable bytes, deferred native ack/readback, main-thread acceptance, duplicate poll, write failure, world guard");
    }
    static void finishJob(EquipmentPersistence.SaveJob job) throws Exception {
        long deadline=System.nanoTime()+2_000_000_000L;
        while(EquipmentPersistence.poll(job)==0) {
            if(System.nanoTime()>deadline) throw new AssertionError("save did not finish");Thread.sleep(1);
        }
    }
    static void validatePersistence() throws Exception {
        var directory=Files.createTempDirectory("cvp-equipment-ledger-");var file=directory.resolve("CVPEquipment.bin");
        EquipmentPersistence.Replace replace=(a,b)->Files.move(a,b,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        try {
            if(EquipmentPersistence.readFile(file)!=null) throw new AssertionError("absent ledger was manufactured");
            var data=LuaManager.platform.newTable();var rows=LuaManager.platform.newTable();var row=LuaManager.platform.newTable();
            row.rawset("state","held");row.rawset("payload","native payload");row.rawset("id",42.0);
            rows.rawset("key",row);data.rawset("rows",rows);data.rawset("version",1.0);
            EquipmentPersistence.writeFile(file,data,replace);byte[] original=Files.readAllBytes(file);
            var large=LuaManager.platform.newTable();
            for(int i=0;i<10;i++) large.rawset("row"+i,"x".repeat(20000));
            EquipmentPersistence.writeFile(file,large,replace);
            if(!"x".repeat(20000).equals(EquipmentPersistence.readFile(file).rawget("row9")))
                throw new AssertionError("grown ledger buffer lost data");
            EquipmentPersistence.writeFile(file,data,replace);
            if(!Arrays.equals(original,Files.readAllBytes(file))) throw new AssertionError("reused ledger buffer retained trailing bytes");
            var restored=EquipmentPersistence.readFile(file);var restoredRow=(KahluaTable)((KahluaTable)restored.rawget("rows")).rawget("key");
            if(!"native payload".equals(restoredRow.rawget("payload")) || !Double.valueOf(42).equals(restoredRow.rawget("id")))
                throw new AssertionError("ledger state lost");
            row.rawset("state","returning");
            rejects(()->EquipmentPersistence.writeFile(file,data,(a,b)->{throw new java.io.IOException("injected replace failure");}));
            if(!Arrays.equals(original,Files.readAllBytes(file)) || Files.exists(directory.resolve("CVPEquipment.bin.tmp")))
                throw new AssertionError("failed replace changed prior ledger or left temporary file");
            EquipmentPersistence.writeFile(file,data,replace);
            restored=EquipmentPersistence.readFile(file);restoredRow=(KahluaTable)((KahluaTable)restored.rawget("rows")).rawget("key");
            if(!"returning".equals(restoredRow.rawget("state"))) throw new AssertionError("replacement not persisted");
            byte[] valid=Files.readAllBytes(file);byte[] changed=valid.clone();changed[changed.length-1]^=1;
            Files.write(file,changed);rejects(()->EquipmentPersistence.readFile(file));
            Files.write(file,Arrays.copyOf(valid,valid.length-1));rejects(()->EquipmentPersistence.readFile(file));
            Files.write(file,Arrays.copyOf(valid,7));rejects(()->EquipmentPersistence.readFile(file));
            Files.write(file,valid);
            data.rawset("unsupported",new Object());rejects(()->EquipmentPersistence.writeFile(file,data,replace));data.rawset("unsupported",null);
            data.rawset("cycle",data);rejects(()->EquipmentPersistence.writeFile(file,data,replace));data.rawset("cycle",null);
            data.rawset("oversized","x".repeat(32768));rejects(()->EquipmentPersistence.writeFile(file,data,replace));data.rawset("oversized",null);
            if(!Arrays.equals(valid,Files.readAllBytes(file))) throw new AssertionError("validation failure overwrote prior ledger");
            // Store-3 keeps free endpoints and item claims in the same native
            // atomic file, including coordinates when no car/chunk is loaded.
            var graph=LuaManager.platform.newTable();var links=LuaManager.platform.newTable();
            var link=LuaManager.platform.newTable();var a=LuaManager.platform.newTable();var b=LuaManager.platform.newTable();
            graph.rawset("version",1.0);graph.rawset("revision",7.0);graph.rawset("links",links);
            links.rawset("connection",link);link.rawset("id","connection");link.rawset("revision",3.0);
            link.rawset("equipment","key");link.rawset("material","Base.Rope");link.rawset("owner","actor");link.rawset("length",5.75);
            a.rawset("kind","body");a.rawset("key","corpse");a.rawset("point","feet");
            a.rawset("x",6200.125);a.rawset("y",5200.5);a.rawset("z",0.025);
            b.rawset("kind","held");b.rawset("holder","actor");
            b.rawset("x",6203.75);b.rawset("y",5200.5);b.rawset("z",0.025);
            link.rawset("a",a);link.rawset("b",b);data.rawset("graph",graph);data.rawset("version",3.0);
            row.rawset("state","held");EquipmentPersistence.writeFile(file,data,replace);
            var copy=EquipmentPersistence.readFile(file);
            var savedGraph=(KahluaTable)copy.rawget("graph");
            var savedLink=(KahluaTable)((KahluaTable)savedGraph.rawget("links")).rawget("connection");
            var savedEnd=(KahluaTable)savedLink.rawget("b");
            if(!Double.valueOf(3).equals(copy.rawget("version")) || !Double.valueOf(7).equals(savedGraph.rawget("revision"))
                || !Double.valueOf(5.75).equals(savedLink.rawget("length")) || !"key".equals(savedLink.rawget("equipment"))
                || !"held".equals(savedEnd.rawget("kind")) || !"actor".equals(savedEnd.rawget("holder"))
                || !Double.valueOf(6203.75).equals(savedEnd.rawget("x")))
                throw new AssertionError("free endpoint or equipment binding lost on native reload");
            byte[] beforeGraphEdit=Files.readAllBytes(file);b.rawset("kind","ground");b.rawset("holder",null);
            rejects(()->EquipmentPersistence.writeFile(file,data,(from,to)->{throw new java.io.IOException("graph commit failed");}));
            if(!Arrays.equals(beforeGraphEdit,Files.readAllBytes(file))) throw new AssertionError("failed endpoint edit changed graph/equipment file");
            System.out.println("PASS native free-end graph: store-3 snapshot, exact endpoint coordinates/holder/length/equipment, atomic edit failure");
        } finally { Files.deleteIfExists(file);Files.deleteIfExists(directory.resolve("CVPEquipment.bin.tmp"));Files.deleteIfExists(directory); }
        var first=LuaManager.platform.newTable();int[] calls={0};
        rejects(()->EquipmentPersistence.actorKey(first,"MP:U:slot:0",()->{calls[0]++;throw new java.io.IOException("unknown");}));
        Object generation=first.rawget("CVPEquipmentActor");
        String key=EquipmentPersistence.actorKey(first,"MP:U:slot:0",()->calls[0]++);
        if(calls[0]!=2 || !generation.equals(first.rawget("CVPEquipmentActor"))) throw new AssertionError("unconfirmed actor not retried");
        if(!key.equals(EquipmentPersistence.actorKey(first,"MP:U:slot:0",()->{throw new AssertionError("repeated actor save");}))) throw new AssertionError("actor key changed");
        var loaded=LuaManager.platform.newTable();loaded.rawset("CVPEquipmentActor",generation);
        if(!key.equals(EquipmentPersistence.actorKey(loaded,"MP:U:slot:0",()->{throw new AssertionError("loaded actor resaved");}))) throw new AssertionError("loaded actor changed");
        if(key.equals(EquipmentPersistence.actorKey(LuaManager.platform.newTable(),"MP:U:slot:0",()->{}))) throw new AssertionError("new character reused prior actor identity");
        // Matching old bytes must not acknowledge a snapshot still behind an older queued write.
        int[] phase={0},reads={0};String[] disk={"new"};
        EquipmentPersistence.awaitCheckpoint(()->{
            phase[0]++;
            if(phase[0]==2) disk[0]="old";
            if(phase[0]==3) disk[0]="new";
            return phase[0]>=3;
        },()->{reads[0]++;return disk[0].equals("new");},"fixture",200_000_000L);
        if(phase[0]!=3 || reads[0]!=1) throw new AssertionError("old matching disk state acknowledged before queued completion");
        try {
            EquipmentPersistence.awaitCheckpoint(()->false,()->{throw new AssertionError("readback before completion");},"fixture",20_000_000L);
            throw new AssertionError("uncompleted save accepted");
        } catch(java.io.IOException expected) {
            if(!expected.getMessage().contains("outcome unknown")) throw expected;
        }
        validateLedgerRecovery();
        validateNativeMainQueuePump();
        validateNativeChunkChecksumRecovery();
        System.out.println("PASS equipment ledger: native table roundtrip, atomic replacement failure preserves prior file, checksum/truncation/value rejection; actor generations/retry; completion-before-readback race and unknown timeout");
        System.out.println("Scope: isolated file and completion fixtures; native player/chunk queue barriers require live runtime validation");
    }
    static void validateLedgerRecovery() throws Exception {
        var directory=Files.createTempDirectory("cvp-ledger-recovery-");var file=directory.resolve("CVPEquipment.bin");
        EquipmentPersistence.Replace replace=(a,b)->Files.move(a,b,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        try {
            byte[] damaged={1,2,3};Files.write(file,damaged);
            try { EquipmentPersistence.readFile(file);throw new AssertionError("corruption accepted"); }
            catch(EquipmentPersistence.CorruptLedger expected) {}
            rejects(()->EquipmentPersistence.resetFile(file,(a,b)->{throw new java.io.IOException("replace denied");}));
            if(!Arrays.equals(damaged,Files.readAllBytes(file))) throw new AssertionError("failed reset lost source");
            EquipmentPersistence.resetFile(file,replace);
            var restored=EquipmentPersistence.readFile(file);
            if(!Boolean.TRUE.equals(restored.rawget("discardLegacy")) || !Double.valueOf(3).equals(restored.rawget("version"))
                || !((KahluaTable)restored.rawget("rows")).isEmpty()
                || !((KahluaTable)((KahluaTable)restored.rawget("graph")).rawget("links")).isEmpty())
                throw new AssertionError("recovery marker/empty graph not durable");
            try(var paths=Files.list(directory)) {
                var backups=paths.filter(p->p.toString().endsWith(".bak")).toList();
                if(backups.size()!=2) throw new AssertionError("missing recovery backup");
                for(var backup:backups) if(!Arrays.equals(damaged,Files.readAllBytes(backup))) throw new AssertionError("backup bytes differ");
            }
            byte[] healthy=Files.readAllBytes(file);healthy[6]^=1;Files.write(file,healthy);
            try { EquipmentPersistence.readFile(file);throw new AssertionError("future world version accepted"); }
            catch(EquipmentPersistence.CorruptLedger wrong) { throw new AssertionError("unsupported world marked corrupt",wrong); }
            catch(java.io.IOException expected) {}
            if(!Arrays.equals(healthy,Files.readAllBytes(file))) throw new AssertionError("read changed unsupported file");
        } finally {
            try(var paths=Files.list(directory)) { for(var path:paths.toList()) Files.delete(path); }
            Files.delete(directory);
        }
        System.out.println("PASS recovery: byte-exact backup, failed replace preserves source, durable reset marker, unsupported version remains untouched");
    }
    static void validateNativeMainQueuePump() throws Exception {
        Field initialized=zombie.MainThread.class.getDeclaredField("isInitialized");initialized.setAccessible(true);
        boolean previousInitialized=initialized.getBoolean(null),previousServer=GameServer.server;
        Thread previousMain=zombie.MainThread.mainThread,previousGame=zombie.GameWindow.gameThread;
        var callback=new java.util.concurrent.atomic.AtomicBoolean();
        var finished=new java.util.concurrent.atomic.AtomicBoolean();
        var failure=new java.util.concurrent.atomic.AtomicReference<Throwable>();
        Thread main=Thread.currentThread();
        Thread worker=new Thread(()->{
            try {
                zombie.MainThread.invokeOnMainThread(()->{
                    if(Thread.currentThread()!=main) throw new AssertionError("native callback ran off main thread");
                    callback.set(true);
                });
                finished.set(true);
            } catch(Throwable error) { failure.set(error); }
        },"CVP-native-main-queue-fixture");
        worker.setDaemon(true);
        try {
            initialized.setBoolean(null,true);zombie.MainThread.mainThread=main;zombie.GameWindow.gameThread=main;
            GameServer.server=true;worker.start();
            rejects(()->EquipmentPersistence.awaitCheckpoint(finished::get,()->true,"server-guard",30_000_000L));
            if(callback.get()) throw new AssertionError("server wait pumped SP main queue");
            GameServer.server=false;
            EquipmentPersistence.awaitCheckpoint(finished::get,()->true,"native-main-queue",1_000_000_000L);
            worker.join(1000);
            if(!callback.get() || !finished.get() || failure.get()!=null) throw new AssertionError("native synchronous queue not serviced",failure.get());
        } finally {
            GameServer.server=false;zombie.MainThread.busyWait();worker.join(1000);
            initialized.setBoolean(null,previousInitialized);zombie.MainThread.mainThread=previousMain;
            zombie.GameWindow.gameThread=previousGame;GameServer.server=previousServer;
        }
        System.out.println("PASS native synchronous MainThread queue serviced during SP checkpoint wait; server guard does not pump it");
    }
    static void validateNativeChunkChecksumRecovery() throws Exception {
        var directory=Files.createTempDirectory("cvp-chunk-readback-");var file=directory.resolve("map_fixture.bin");
        int wx=123,wy=456;long original=zombie.network.ChunkChecksum.getChecksumIfExists(wx,wy);
        byte[] expected={1,2,3,4};long cached=123456789L;
        try {
            Files.write(file,expected);zombie.network.ChunkChecksum.setChecksum(wx,wy,cached);
            if(!EquipmentPersistence.verifyChunkFile(file,expected,wx,wy)
                || zombie.network.ChunkChecksum.getChecksumIfExists(wx,wy)!=cached)
                throw new AssertionError("matching chunk readback invalidated native checksum");
            Files.write(file,new byte[]{1,2,9,4});
            rejects(()->EquipmentPersistence.awaitCheckpoint(()->false,
                ()->EquipmentPersistence.verifyChunkFile(file,expected,wx,wy),"pending-chunk",20_000_000L));
            if(zombie.network.ChunkChecksum.getChecksumIfExists(wx,wy)!=cached)
                throw new AssertionError("pending chunk timeout invalidated native checksum");
            if(EquipmentPersistence.verifyChunkFile(file,expected,wx,wy)
                || zombie.network.ChunkChecksum.getChecksumIfExists(wx,wy)!=-1L)
                throw new AssertionError("completed mismatching chunk kept stale native checksum");
            Files.write(file,expected);zombie.network.ChunkChecksum.setChecksum(wx,wy,cached);
            EquipmentPersistence.awaitCheckpoint(()->true,
                ()->EquipmentPersistence.verifyChunkFile(file,expected,wx,wy),"retry-chunk",100_000_000L);
            if(zombie.network.ChunkChecksum.getChecksumIfExists(wx,wy)!=cached)
                throw new AssertionError("successful retry invalidated native checksum");
            Files.delete(file);
            rejects(()->EquipmentPersistence.verifyChunkFile(file,expected,wx,wy));
            if(zombie.network.ChunkChecksum.getChecksumIfExists(wx,wy)!=-1L)
                throw new AssertionError("missing completed chunk kept stale native checksum");
        } finally {
            zombie.network.ChunkChecksum.setChecksum(wx,wy,original);Files.deleteIfExists(file);Files.deleteIfExists(directory);
        }
        System.out.println("PASS native chunk checksum: completed mismatch/missing file invalidates cache, pending timeout preserves it, matching retry acknowledges file");
    }
}
