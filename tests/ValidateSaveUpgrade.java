package cvpworld;

import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.vm.KahluaTable;
import zombie.Lua.LuaManager;
import zombie.ZomboidFileSystem;
import zombie.core.Core;
import zombie.inventory.InventoryItem;
import zombie.inventory.ItemContainer;
import zombie.inventory.types.ComboItem;
import zombie.iso.IsoWorld;
import zombie.network.GameClient;
import zombie.network.GameServer;

/** Genuine old item bytes + explicitly synthetic ledger framing, not a live save migration. */
public final class ValidateSaveUpgrade {
    private ValidateSaveUpgrade() {}
    interface Checked { void run() throws Exception; }
    static void require(boolean ok,String message) { if(!ok) throw new AssertionError(message); }
    static void rejects(Class<? extends Exception> type,Checked action) throws Exception {
        try { action.run(); }
        catch(Exception error) { if(type.isInstance(error)) return;throw error; }
        throw new AssertionError("invalid upgrade input accepted: "+type.getSimpleName());
    }
    static KahluaTable table(Object... pairs) {
        KahluaTable result=LuaManager.platform.newTable();
        for(int i=0;i<pairs.length;i+=2) result.rawset(pairs[i],pairs[i+1]);
        return result;
    }
    static ComboItem target(String type,short registry) throws Exception {
        var item=new ComboItem("Base",type,type,"Item_Rope");item.setScriptItem(new zombie.scripting.objects.Item());
        // Test seam only; public decode still validates the real saved WorldDictionary and factory.
        Field field=InventoryItem.class.getDeclaredField("registryId");field.setAccessible(true);field.setShort(item,registry);
        return item;
    }
    static short registry(String payload) { return ByteBuffer.wrap(bytes(payload)).getShort(4); }
    static byte[] bytes(String payload) { return Base64.getDecoder().decode(payload.split(":",6)[5]); }
    static String version(String payload,int version) {
        String[] f=payload.split(":",6);f[1]=Integer.toString(version);return String.join(":",f);
    }
    static String withBytes(String payload,byte[] bytes) throws Exception {
        String[] f=payload.split(":",6);f[4]=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        f[5]=Base64.getEncoder().encodeToString(bytes);return String.join(":",f);
    }
    static void itemTests(String genuine) throws Exception {
        require(genuine.startsWith("CVPITEM1:249:286250744:Base.Rope:"),"wrong historical fixture");
        require(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes(genuine)))
            .equals("ff231ee960e3c6eaa9d6c98cfe720be9b93ce58f5ad36fbf384e6a6ddf24f09b"),"genuine fixture bytes changed");
        short registry=registry(genuine);
        var old=ItemCodec.decode(genuine,target("Rope",registry));
        require(old.getID()==286250744 && old.getFullType().equals("Base.Rope") && old.getCondition()==10
            && old.getContainer()==null && old.getWorldItem()==null,"old native item state/ownership changed");
        String rewritten=ItemCodec.encode(old);
        require(rewritten.startsWith("CVPITEM1:"+IsoWorld.getWorldVersion()+":"),"new item write did not use current version");
        for(int i=0;i<3;i++) {
            var copy=ItemCodec.decode(rewritten,target("Rope",registry));
            require(copy.getID()==old.getID() && copy.getFullType().equals(old.getFullType())
                && copy.getCondition()==old.getCondition() && copy.getName().equals(old.getName())
                && copy.getActualWeight()==old.getActualWeight() && copy.isFavorite()==old.isFavorite()
                && copy.getContainer()==null && copy.getWorldItem()==null,"rewritten native item state lost");
            rewritten=ItemCodec.encode(copy);
        }
        for(int v:new int[]{-1,0,248,250,252,Integer.MAX_VALUE})
            rejects(IllegalArgumentException.class,()->ItemCodec.decode(version(genuine,v),target("Rope",registry)));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode("CVPITEM2"+genuine.substring(8),target("Rope",registry)));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(genuine.replace(":Base.Rope:",":Base.Pen:"),target("Rope",registry)));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(genuine.replace(":286250744:",":286250745:"),target("Rope",registry)));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(genuine.substring(0,genuine.lastIndexOf(':')+1)+"!bad!",target("Rope",registry)));
        byte[] corrupted=bytes(genuine);corrupted[corrupted.length-1]^=1;
        String[] f=genuine.split(":",6);f[5]=Base64.getEncoder().encodeToString(corrupted);
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(String.join(":",f),target("Rope",registry)));
        byte[] malformed=bytes(genuine);ByteBuffer.wrap(malformed).putInt(malformed.length+1);
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(withBytes(genuine,malformed),target("Rope",registry)));
        byte[] marker=bytes(genuine);marker[6]=0;
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(withBytes(genuine,marker),target("Rope",registry)));
        byte[] truncated=Arrays.copyOf(bytes(genuine),bytes(genuine).length-1);ByteBuffer.wrap(truncated).putInt(truncated.length-4);
        rejects(Exception.class,()->ItemCodec.decode(withBytes(genuine,truncated),target("Rope",registry)));
        byte[] trailing=Arrays.copyOf(bytes(genuine),bytes(genuine).length+1);ByteBuffer.wrap(trailing).putInt(trailing.length-4);
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(withBytes(genuine,trailing),target("Rope",registry)));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(withBytes(genuine,new byte[ItemCodec.MAX_BYTES+1]),target("Rope",registry)));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(genuine,target("Rope",(short)(registry+1))));
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(genuine,target("HeavyChain",registry)));
        var owned=target("Rope",registry);var container=new ItemContainer();container.AddItem(owned);
        rejects(IllegalArgumentException.class,()->ItemCodec.decode(genuine,owned));
        require(owned.getContainer()==container && container.getItems().size()==1,"rejected decode changed source ownership");
        // Without dictionary bootstrap, public decode must not bypass registry checks.
        rejects(Exception.class,()->ItemCodec.decode(genuine));
        GameClient.client=true;
        try { rejects(IllegalStateException.class,()->ItemCodec.decode(genuine,target("Rope",registry))); }
        finally { GameClient.client=false; }
        System.out.println("PASS genuine249 native item -> current encode/reload; version/hash/frame/identity/type/registry/ownership/authority guards");
    }
    // SYNTHETIC ledger: current Kahlua encoding under an explicit249 header. Not historical game bytes.
    static byte[] syntheticFrame(KahluaTable data,int worldVersion) throws Exception {
        ByteBuffer payload=ByteBuffer.allocate(65536);data.save(payload);
        byte[] bytes=Arrays.copyOf(payload.array(),payload.position());
        return ByteBuffer.allocate(46+bytes.length).put("CVPEQ1".getBytes(StandardCharsets.US_ASCII))
            .putInt(worldVersion).putInt(bytes.length).put(MessageDigest.getInstance("SHA-256").digest(bytes)).put(bytes).array();
    }
    static void corrupt(Path file,byte[] data) throws Exception {
        Files.write(file,data);rejects(EquipmentPersistence.CorruptLedger.class,()->EquipmentPersistence.readFile(file));
        require(Arrays.equals(data,Files.readAllBytes(file)),"readFile changed rejected file");
    }
    static void ledgerTests(Path directory,String genuine) throws Exception {
        var fs=ZomboidFileSystem.instance;var core=Core.getInstance();
        String cache=fs.getCacheDir(),world=Core.gameSaveWorld;Thread main=GameServer.mainThread;
        boolean noSave=core.isNoSave();
        try {
            fs.setCacheDir(directory.toString());Core.gameSaveWorld="synthetic-upgrade";
            GameServer.mainThread=Thread.currentThread();core.setNoSave(false);
            Path save=Path.of(fs.getCurrentSaveDir()).toAbsolutePath().normalize();
            require(save.startsWith(directory),"isolated save escaped test scope");Files.createDirectories(save);
            var data=table("version",3.0,"rows",table("synthetic",table("payload",genuine)),
                "graph",table("version",1.0,"revision",7.0,"links",table()),"marker","synthetic249",
                "bodyClocks",table("synthetic-body",table("epoch","synthetic-epoch","started",10.0,"at",20.0,"elapsed",5.0,"paused",true)));
            byte[] old=syntheticFrame(data,249);Path original=directory.resolve("synthetic249.original.bin");Files.write(original,old);
            Path file=save.resolve("CVPEquipment.bin");Files.copy(original,file);
            var envelope=EquipmentPersistence.readEnvelope();
            require("ok".equals(envelope.rawget("status")) && envelope.rawget("recovered")==null,"old ledger not accepted normally");
            require(Arrays.equals(old,Files.readAllBytes(file)),"read rewrote historical header");
            Path backup=file.resolveSibling("CVPEquipment.bin.world-249."
                +HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(old))+".bak");
            require(Arrays.equals(old,Files.readAllBytes(backup)),"upgrade backup is not original bytes");
            EquipmentPersistence.readFile(file);
            try(var files=Files.list(save)) {
                require(files.filter(p->p.getFileName().toString().endsWith(".bak")).count()==1,"repeat read created another backup");
            }
            // Backup failures must block the read, never classify the valid old
            // ledger as corrupt or reset it to an empty graph.
            Files.delete(backup);Files.createDirectory(backup);
            var blocked=EquipmentPersistence.readEnvelope();
            require("error".equals(blocked.rawget("status")) && blocked.rawget("recovered")==null,"backup failure reset ledger");
            require(Arrays.equals(old,Files.readAllBytes(file)),"backup failure changed ledger");
            Files.delete(backup);Files.write(backup,new byte[]{1,2,3});
            blocked=EquipmentPersistence.readEnvelope();
            require("error".equals(blocked.rawget("status")),"mismatched backup accepted");
            require(Arrays.equals(new byte[]{1,2,3},Files.readAllBytes(backup)),"existing backup overwritten");
            require(Arrays.equals(old,Files.readAllBytes(file)),"backup mismatch changed ledger");
            Files.delete(backup);EquipmentPersistence.readFile(file);
            rejects(java.io.IOException.class,()->EquipmentPersistence.writeFile(file,(KahluaTable)envelope.rawget("data"),
                (from,to)->{throw new java.io.IOException("injected upgrade write failure");}));
            require(Arrays.equals(old,Files.readAllBytes(file)) && Arrays.equals(old,Files.readAllBytes(backup)),"failed write lost old frame");
            var loaded=(KahluaTable)envelope.rawget("data");
            require("synthetic249".equals(loaded.rawget("marker")) && Double.valueOf(3).equals(loaded.rawget("version")),"ledger payload/schema lost");
            var graph=(KahluaTable)loaded.rawget("graph");require(Double.valueOf(7).equals(graph.rawget("revision")),"graph revision lost");
            require("confirmed".equals(EquipmentPersistence.writeEnvelope(loaded).rawget("status")),"rewrite not confirmed");
            require(ByteBuffer.wrap(Files.readAllBytes(file)).getInt(6)==IsoWorld.getWorldVersion(),"ledger rewrite did not use current version");
            require(Arrays.equals(old,Files.readAllBytes(backup)),"rewrite lost old-version backup");
            var reloaded=EquipmentPersistence.readFile(file);var row=(KahluaTable)((KahluaTable)reloaded.rawget("rows")).rawget("synthetic");
            require(genuine.equals(row.rawget("payload")),"ledger rewrite mutated stored item payload");
            ItemCodec.decode((String)row.rawget("payload"),target("Rope",registry(genuine)));
            require(Arrays.equals(old,Files.readAllBytes(original)),"synthetic source changed");
            for(int v:new int[]{-1,0,248,250,252,Integer.MAX_VALUE}) {
                byte[] unsupported=syntheticFrame(data,v);Files.write(file,unsupported);
                var rejected=EquipmentPersistence.readEnvelope();
                require("unsupported".equals(rejected.rawget("status")) && rejected.rawget("recovered")==null,"unknown version recovered/reset");
                require(Arrays.equals(unsupported,Files.readAllBytes(file)),"unknown-version source changed");
            }
            byte[] magic=old.clone();magic[0]^=1;Files.write(file,magic);
            rejects(EquipmentPersistence.UnsupportedLedger.class,()->EquipmentPersistence.readFile(file));
            corrupt(file,Arrays.copyOf(old,45));corrupt(file,Arrays.copyOf(old,old.length-1));
            byte[] checksum=old.clone();checksum[14]^=1;corrupt(file,checksum);
            byte[] length=old.clone();ByteBuffer.wrap(length).putInt(10,old.length);corrupt(file,length);
            byte[] trailing=Arrays.copyOf(old,old.length+1);ByteBuffer.wrap(trailing).putInt(10,trailing.length-46);
            byte[] digest=MessageDigest.getInstance("SHA-256").digest(Arrays.copyOfRange(trailing,46,trailing.length));
            System.arraycopy(digest,0,trailing,14,digest.length);corrupt(file,trailing);
            byte[] malformed=old.clone();Arrays.fill(malformed,46,malformed.length,(byte)0xff);
            digest=MessageDigest.getInstance("SHA-256").digest(Arrays.copyOfRange(malformed,46,malformed.length));
            System.arraycopy(digest,0,malformed,14,digest.length);corrupt(file,malformed);
            require(Arrays.equals(old,Files.readAllBytes(original)),"source changed after rejection tests");
            System.out.println("PASS SYNTHETIC249 ledger read -> rewrite current -> reload; immutable original; unknown/future/corrupt/truncated/trailing rejected");
        } finally {
            fs.setCacheDir(cache);Core.gameSaveWorld=world;GameServer.mainThread=main;core.setNoSave(noSave);SkeletonLifetime.install(null);
        }
    }
    static void same(Object expected,Object actual) {
        if(expected instanceof KahluaTable a && actual instanceof KahluaTable b) {
            var it=a.iterator();int count=0,other=0;
            while(it.advance()) {count++;same(it.getValue(),b.rawget(it.getKey()));}
            it=b.iterator();while(it.advance())other++;
            require(count==other,"table entry count changed");
        } else require(java.util.Objects.equals(expected,actual),"saved value changed");
    }
    // Optional genuine full ledger. Only a copy in the isolated test directory is
    // rewritten; its graph and every nested item payload must survive unchanged.
    static void historicalLedger(Path directory,Path original) throws Exception {
        byte[] before=Files.readAllBytes(original);
        require(ByteBuffer.wrap(before).getInt(6)==249,"historical ledger must be249");
        Path file=directory.resolve("CVPEquipment.bin");Files.copy(original,file);
        KahluaTable data=EquipmentPersistence.readFile(file);
        require(Arrays.equals(before,Files.readAllBytes(file)),"historical read changed clone");
        Path backup=file.resolveSibling("CVPEquipment.bin.world-249."
            +HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(before))+".bak");
        require(Arrays.equals(before,Files.readAllBytes(backup)),"historical backup changed bytes");
        int count=decodeItems(data);
        EquipmentPersistence.writeFile(file,data,(a,b)->Files.move(a,b,
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING));
        require(ByteBuffer.wrap(Files.readAllBytes(file)).getInt(6)==251,"historical clone not saved current");
        same(data,EquipmentPersistence.readFile(file));
        require(Arrays.equals(before,Files.readAllBytes(original)),"historical original changed");
        require(Arrays.equals(before,Files.readAllBytes(backup)),"historical backup changed after write");
        System.out.println("PASS genuine ledger SHA256="+HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(before))
            +" bytes="+before.length+" decodedItems="+count+" graphAndAllValuesEqual=true backupExact=true originalUnchanged=true");
    }
    static int decodeItems(KahluaTable data) throws Exception {
        int count=0;var it=data.iterator();
        while(it.advance()) {
            if(it.getValue() instanceof KahluaTable child) count+=decodeItems(child);
            else if(it.getValue() instanceof String value && value.startsWith("CVPITEM1:")) {
                String[] fields=value.split(":",6);
                InventoryItem item=ItemCodec.decode(value,target(fields[3].substring(5),registry(value)));
                require(item.getID()==Integer.parseInt(fields[2]) && item.getContainer()==null && item.getWorldItem()==null,
                    "historical item identity/ownership changed");count++;
            }
        }
        return count;
    }
    public static void main(String[] args) throws Exception {
        require(IsoWorld.getWorldVersion()==251,"upgrade proof is pinned to installed251; review native compatibility before widening");
        LuaManager.platform=new J2SEPlatform();LuaManager.env=table();zombie.core.random.RandStandard.INSTANCE.init();GameServer.server=true;GameClient.client=false;
        Path fixture=Path.of(args.length==0?"tests/fixtures/save_upgrade/rope-249.txt":args[0]);byte[] original=Files.readAllBytes(fixture);
        String genuine=new String(original,StandardCharsets.UTF_8).strip();itemTests(genuine);
        Path home=Path.of(System.getProperty("user.home")).toRealPath();Path directory=Files.createTempDirectory(home,"cvp-save-upgrade-").toRealPath();
        require(directory.startsWith(home) && !directory.equals(home),"unsafe test directory");
        try {
            ledgerTests(directory,genuine);
            for(int i=1;i<args.length;i++) historicalLedger(Files.createDirectory(directory.resolve("historical-"+i)),Path.of(args[i]));
            require(Arrays.equals(original,Files.readAllBytes(fixture)),"genuine fixture changed");
        }
        finally {
            // Only the verified fresh temporary directory is removed; never an input save.
            try(var files=Files.walk(directory)) {for(Path file:files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(file);}
        }
        System.out.println("PASS ValidateSaveUpgrade; no real WorldDictionary/factory bootstrap, live transfer or full SP/MP migration claim");
    }
}
