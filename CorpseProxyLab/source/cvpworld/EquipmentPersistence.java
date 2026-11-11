package cvpworld;

import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.BufferOverflowException;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Queue;
import java.util.UUID;
import java.util.WeakHashMap;
import java.util.zip.CRC32;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import org.sqlite.SQLiteConfig;
import se.krka.kahlua.j2se.KahluaTableImpl;
import se.krka.kahlua.vm.KahluaTable;
import zombie.ChunkMapFilenames;
import zombie.GameWindow;
import zombie.Lua.LuaManager;
import zombie.ZomboidFileSystem;
import zombie.characters.IsoPlayer;
import zombie.core.Core;
import zombie.core.raknet.UdpConnection;
import zombie.core.znet.SteamUtils;
import zombie.iso.ChunkSaveWorker;
import zombie.iso.IsoChunk;
import zombie.iso.IsoGridSquare;
import zombie.iso.IsoWorld;
import zombie.iso.WorldStreamer;
import zombie.network.ClientChunkRequest;
import zombie.network.ChunkChecksum;
import zombie.network.GameClient;
import zombie.network.GameServer;
import zombie.network.ServerPlayersVehicles;
import zombie.savefile.PlayerDB;
import zombie.savefile.ServerPlayerDB;

/** B42.21 save barriers. Never writes player SQL or replaces native chunk serialization. */
@LuaClass(name="CVPEquipmentPersistence")
public final class EquipmentPersistence {
    static final int MAX_LEDGER=8*1024*1024;
    static final long TIMEOUT_NANOS=3_000_000_000L;
    private static final byte[] MAGIC="CVPEQ1".getBytes(StandardCharsets.US_ASCII);
    private static final String ACTOR="CVPEquipmentActor";
    private static final Map<KahluaTable,Boolean> pendingActors=new WeakHashMap<>();
    private static ByteBuffer ledgerBuffer=ByteBuffer.allocate(64*1024);
    private EquipmentPersistence() {}
    private static final java.util.concurrent.ExecutorService io=java.util.concurrent.Executors.newSingleThreadExecutor(r->{
        Thread t=new Thread(r,"CorpseTow-save");t.setDaemon(true);return t;
    });
    private static final Map<Object,Boolean> acknowledgements=java.util.Collections.synchronizedMap(new IdentityHashMap<>());
    public static void completed(Object task) { synchronized(acknowledgements) {
        if(acknowledgements.containsKey(task)) acknowledgements.put(task,true);
    } }
    public static final class SaveJob {
        final Path world; final long started=System.nanoTime();
        Probe completion,readback; Object task; Runnable accepted, rejected; Object value=Boolean.TRUE;
        java.util.concurrent.Future<Boolean> future; Exception failure; boolean done;
        SaveJob() throws IOException { world=saveDir(); }
    }
    static SaveJob checkpointJob(Object task,Probe completion,Probe readback) throws IOException {
        SaveJob job=new SaveJob();job.task=task;job.completion=completion;job.readback=readback;
        acknowledgements.put(task,false);return job;
    }
    public static int poll(SaveJob job) throws Exception {
        authority();
        if(!job.world.equals(saveDir())) { acknowledgements.remove(job.task);throw new IOException("save job belongs to another world"); }
        if(job.failure!=null) throw job.failure;
        if(job.done) return 1;
        try {
            if(job.future==null && (Boolean.TRUE.equals(acknowledgements.get(job.task)) || job.completion.saved()))
                job.future=io.submit(()->job.readback.saved());
            if(job.future!=null && job.future.isDone()) {
                if(job.future.get()) {
                    if(job.accepted!=null) job.accepted.run();job.done=true;acknowledgements.remove(job.task);return 1;
                }
                if(job.rejected!=null) job.rejected.run();
                job.future=null;
            }
            // Writes must finish, even after UI cancellation; never race an atomic replacement.
            if(job.completion!=null && System.nanoTime()-job.started>TIMEOUT_NANOS)
                throw new IOException("checkpoint outcome unknown; keep recovery record");
            return 0;
        } catch(Exception error) { if(job.future!=null && job.rejected!=null) job.rejected.run();acknowledgements.remove(job.task);job.failure=error;throw error; }
    }
    public static Object result(SaveJob job) throws Exception {
        if(poll(job)!=1) throw new IllegalStateException("save still pending");return job.value;
    }
    public static SaveJob writeAsync(KahluaTable data) throws Exception {
        authority();var clocks=SkeletonLifetime.readClocks(data);Path file=ledger();byte[] framed=frame(data);
        SaveJob job=new SaveJob();job.accepted=()->SkeletonLifetime.installClocks(clocks);
        job.future=io.submit(()->{writeFrame(file,framed,(a,b)->Files.move(a,b,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING));return true;});
        return job;
    }

    private static void authority() {
        if(GameClient.client || Core.getInstance().isNoSave()) throw new IllegalStateException("equipment persistence unavailable");
        Thread expected=GameServer.server?GameServer.mainThread:GameWindow.gameThread;
        if(expected==null || Thread.currentThread()!=expected) throw new IllegalStateException("equipment persistence requires game main thread");
    }
    private static Path saveDir() throws IOException {
        Path path=Path.of(ZomboidFileSystem.instance.getCurrentSaveDir()).toAbsolutePath().normalize();
        if(!Files.isDirectory(path)) throw new IOException("save directory unavailable");
        return path.toRealPath();
    }
    private static Path ledger() throws IOException { return saveDir().resolve("CVPEquipment.bin"); }
    static final class CorruptLedger extends IOException {
        CorruptLedger(String message) { super(message); }
    }
    // A ledger this build understands well enough to keep, but must not rewrite:
    // a newer world/format or schema. Callers report it, they never reset it.
    static final class UnsupportedLedger extends IOException {
        UnsupportedLedger(String message) { super(message); }
    }
    private static String describe(Throwable error) {
        String message=error.getMessage();
        return message==null || message.isBlank()?error.getClass().getSimpleName():message;
    }
    private static KahluaTable statusEnvelope(String status,KahluaTable data,String reason) {
        KahluaTable result=LuaManager.platform.newTable();
        result.rawset("status",status);
        if(data!=null) result.rawset("data",data);
        if(reason!=null) result.rawset("reason",reason);
        return result;
    }
    // Only an established corruption may replace the ledger. A failed backup or
    // replacement keeps the old file and reports an error; it is never "empty".
    private static KahluaTable recoveredEnvelope(Throwable corruption) {
        try {
            KahluaTable result=statusEnvelope("ok",resetInvalidStore(),null);
            result.rawset("recovered",true);
            result.rawset("reason",describe(corruption));
            return result;
        } catch(Exception failure) {
            return statusEnvelope("error",null,"equipment recovery failed: "+describe(failure));
        }
    }
    // Explicit read classification for Lua. Never throws and never returns nil:
    // missing means no journal, ok carries data, unsupported/error carry a reason.
    public static KahluaTable readEnvelope() {
        try {
            authority();KahluaTable data;
            try { data=readFile(ledger()); }
            catch(CorruptLedger corrupt) { return recoveredEnvelope(corrupt); }
            catch(UnsupportedLedger unsupported) { return statusEnvelope("unsupported",null,describe(unsupported)); }
            if(data==null) return statusEnvelope("missing",null,"equipment ledger missing");
            try { SkeletonLifetime.install(data); }
            catch(IllegalArgumentException corruptClock) {
                Object version=data.rawget("version");
                if(!Double.valueOf(2).equals(version) && !Double.valueOf(3).equals(version))
                    return statusEnvelope("unsupported",null,describe(corruptClock));
                return recoveredEnvelope(corruptClock);
            }
            return statusEnvelope("ok",data,null);
        } catch(CorruptLedger corrupt) { return recoveredEnvelope(corrupt); }
        catch(UnsupportedLedger unsupported) { return statusEnvelope("unsupported",null,describe(unsupported)); }
        catch(Exception error) { return statusEnvelope("error",null,describe(error)); }
    }
    public static KahluaTable read() throws Exception {
        authority();KahluaTable data;
        try { data=readFile(ledger()); }
        catch(CorruptLedger corrupt) { return resetInvalidStore(); }
        try { SkeletonLifetime.install(data); }
        catch(IllegalArgumentException corruptClock) {
            Object version=data==null?null:data.rawget("version");
            if(!Double.valueOf(2).equals(version) && !Double.valueOf(3).equals(version)) throw corruptClock;
            return resetInvalidStore();
        }
        return data;
    }
    // Called only after corruption is established. Keep the original bytes before
    // replacing the ledger; a failed backup/write leaves the old file in place.
    public static KahluaTable resetInvalidStore() throws Exception {
        authority();KahluaTable data=resetFile(ledger(),(a,b)->Files.move(a,b,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING));
        SkeletonLifetime.install(data);return data;
    }
    static KahluaTable resetFile(Path file,Replace replace) throws Exception {
        if(Files.isSymbolicLink(file) || !Files.isRegularFile(file)) throw new IOException("equipment recovery source unavailable");
        Path backup=file.resolveSibling(file.getFileName()+".recovery-"+UUID.randomUUID()+".bak");
        Files.copy(file,backup);
        try(FileChannel channel=FileChannel.open(backup,StandardOpenOption.WRITE)) { channel.force(true); }
        if(Files.mismatch(file,backup)!=-1) throw new IOException("equipment recovery backup mismatch");
        KahluaTable data=LuaManager.platform.newTable(),graph=LuaManager.platform.newTable();
        graph.rawset("version",1.0);graph.rawset("revision",0.0);graph.rawset("links",LuaManager.platform.newTable());
        data.rawset("version",3.0);data.rawset("rows",LuaManager.platform.newTable());data.rawset("graph",graph);
        // Persistent across saves: old chunks cannot re-import canceled alpha links.
        data.rawset("discardLegacy",true);
        writeFile(file,data,replace);
        System.out.println("[CVP] Damaged towing data reset; original saved to "+backup);
        return data;
    }
    public static boolean write(KahluaTable data) throws Exception {
        authority();var clocks=SkeletonLifetime.readClocks(data);
        writeFile(ledger(),data,(a,b)->Files.move(a,b,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING));
        SkeletonLifetime.installClocks(clocks);return true;
    }
    // Explicit synchronous write classification. Lua accepts only status
    // "confirmed"; every exception becomes a failed envelope so a nil result is
    // never mistaken for a successful, durable write.
    public static KahluaTable writeEnvelope(KahluaTable data) {
        try {
            return write(data)?statusEnvelope("confirmed",null,null)
                :statusEnvelope("failed",null,"equipment write not confirmed");
        } catch(Exception error) {
            return statusEnvelope("failed",null,describe(error));
        }
    }
    // ---- Installed-bridge compatibility probe -------------------------------
    // Every game/ZombieBuddy member the save barriers reach through reflection is
    // resolved here without performing a save. All missing members are collected
    // so the reason Lua receives names the exact incompatible piece, and the probe
    // never lets a LinkageError or reflection failure escape.
    private static final String[] CAPABILITY_GROUPS={
        "bridge","ledger","playerCheckpointMp","playerCheckpointSp",
        "squareCheckpointMp","squareCheckpointSp","skeletonLifetime","worldVersion"};
    private static void capabilityFailure(List<String> missing,Map<String,Boolean> features,String group,String detail) {
        missing.add(group+": "+detail);features.put(group,false);
    }
    private static String capabilitySignature(Class<?>... types) {
        StringBuilder text=new StringBuilder("(");
        for(int i=0;i<types.length;i++) { if(i>0) text.append(',');text.append(types[i]==null?"?":types[i].getName()); }
        return text.append(')').toString();
    }
    private static Class<?> capabilityClass(List<String> missing,Map<String,Boolean> features,String group,String name) {
        try { return Class.forName(name,false,EquipmentPersistence.class.getClassLoader()); }
        catch(Exception|LinkageError error) {
            capabilityFailure(missing,features,group,"missing class "+name+" ("+describe(error)+")");return null;
        }
    }
    private static Field capabilityField(List<String> missing,Map<String,Boolean> features,String group,Class<?> owner,String name) {
        if(owner==null) return null;
        try { Field value=owner.getDeclaredField(name);value.setAccessible(true);return value; }
        catch(Exception|LinkageError error) {
            capabilityFailure(missing,features,group,"missing field "+owner.getName()+"."+name+" ("+describe(error)+")");return null;
        }
    }
    private static void capabilityMethod(List<String> missing,Map<String,Boolean> features,String group,Class<?> owner,String name,Class<?>... types) {
        if(owner==null) return;
        try { owner.getDeclaredMethod(name,types).setAccessible(true); }
        catch(Exception|LinkageError error) {
            capabilityFailure(missing,features,group,"missing method "+owner.getName()+"."+name+capabilitySignature(types)+" ("+describe(error)+")");
        }
    }
    private static void capabilityConstructor(List<String> missing,Map<String,Boolean> features,String group,Class<?> owner,Class<?>... types) {
        if(owner==null) return;
        try { owner.getDeclaredConstructor(types).setAccessible(true); }
        catch(Exception|LinkageError error) {
            capabilityFailure(missing,features,group,"missing constructor "+owner.getName()+capabilitySignature(types)+" ("+describe(error)+")");
        }
    }
    static List<String> capabilityProblems(Map<String,Boolean> features) {
        List<String> missing=new ArrayList<>();
        // Lua-visible bridge entry points.
        Class<?> bridge=EquipmentPersistence.class;
        capabilityMethod(missing,features,"bridge",bridge,"read");
        capabilityMethod(missing,features,"bridge",bridge,"write",KahluaTable.class);
        capabilityMethod(missing,features,"bridge",bridge,"readEnvelope");
        capabilityMethod(missing,features,"bridge",bridge,"writeEnvelope",KahluaTable.class);
        capabilityMethod(missing,features,"bridge",bridge,"resetInvalidStore");
        capabilityMethod(missing,features,"bridge",bridge,"playerKey",IsoPlayer.class);
        capabilityMethod(missing,features,"bridge",bridge,"playerKeyAsync",IsoPlayer.class);
        capabilityMethod(missing,features,"bridge",bridge,"checkpointPlayer",IsoPlayer.class);
        capabilityMethod(missing,features,"bridge",bridge,"checkpointPlayerAsync",IsoPlayer.class);
        capabilityMethod(missing,features,"bridge",bridge,"checkpointSquare",IsoGridSquare.class);
        capabilityMethod(missing,features,"bridge",bridge,"checkpointSquareAsync",IsoGridSquare.class);
        // Ledger framing and the read/write helpers around the on-disk format.
        capabilityField(missing,features,"ledger",bridge,"MAGIC");
        capabilityMethod(missing,features,"ledger",bridge,"readFile",Path.class);
        capabilityMethod(missing,features,"ledger",bridge,"writeFile",Path.class,KahluaTable.class,Replace.class);
        // MP player checkpoint: ServerPlayersVehicles.instance.thread and the
        // NetworkCharacterData snapshot queued on ServerPlayerDB.charactersToSave.
        Class<?> vehicles=capabilityClass(missing,features,"playerCheckpointMp","zombie.network.ServerPlayersVehicles");
        Field instance=capabilityField(missing,features,"playerCheckpointMp",vehicles,"instance");
        Class<?> vehicleType=instance==null?null:instance.getType();
        capabilityField(missing,features,"playerCheckpointMp",vehicleType,"thread");
        Class<?> serverDB=capabilityClass(missing,features,"playerCheckpointMp","zombie.savefile.ServerPlayerDB");
        capabilityMethod(missing,features,"playerCheckpointMp",serverDB,"getInstance");
        capabilityMethod(missing,features,"playerCheckpointMp",serverDB,"isAvailable");
        capabilityField(missing,features,"playerCheckpointMp",serverDB,"charactersToSave");
        Class<?> networkData=capabilityClass(missing,features,"playerCheckpointMp","zombie.savefile.ServerPlayerDB$NetworkCharacterData");
        capabilityConstructor(missing,features,"playerCheckpointMp",networkData,IsoPlayer.class,int.class,UdpConnection.class);
        capabilityField(missing,features,"playerCheckpointMp",networkData,"buffer");
        capabilityField(missing,features,"playerCheckpointMp",networkData,"username");
        capabilityField(missing,features,"playerCheckpointMp",networkData,"steamid");
        // SP player checkpoint: PlayerDB queues and PlayerData's player snapshot.
        Class<?> playerDB=capabilityClass(missing,features,"playerCheckpointSp","zombie.savefile.PlayerDB");
        capabilityMethod(missing,features,"playerCheckpointSp",playerDB,"getInstance");
        capabilityMethod(missing,features,"playerCheckpointSp",playerDB,"isAvailable");
        capabilityField(missing,features,"playerCheckpointSp",playerDB,"toThread");
        capabilityField(missing,features,"playerCheckpointSp",playerDB,"fromThread");
        Class<?> playerData=capabilityClass(missing,features,"playerCheckpointSp","zombie.savefile.PlayerDB$PlayerData");
        capabilityConstructor(missing,features,"playerCheckpointSp",playerData);
        capabilityMethod(missing,features,"playerCheckpointSp",playerData,"set",IsoPlayer.class);
        capabilityField(missing,features,"playerCheckpointSp",playerData,"byteBuffer");
        Class<?> streamer=capabilityClass(missing,features,"playerCheckpointSp","zombie.iso.WorldStreamer");
        capabilityField(missing,features,"playerCheckpointSp",streamer,"instance");
        capabilityField(missing,features,"playerCheckpointSp",streamer,"worldStreamer");
        // MP square/chunk checkpoint: ServerCell.chunkLoader.threadSave queues a
        // SaveLoadedTask built from a ClientChunkRequest snapshot.
        Class<?> cell=capabilityClass(missing,features,"squareCheckpointMp","zombie.network.ServerMap$ServerCell");
        Field loader=capabilityField(missing,features,"squareCheckpointMp",cell,"chunkLoader");
        Class<?> loaderType=loader==null?null:loader.getType();
        Field threadSave=capabilityField(missing,features,"squareCheckpointMp",loaderType,"threadSave");
        Class<?> saveThread=threadSave==null?null:threadSave.getType();
        capabilityField(missing,features,"squareCheckpointMp",saveThread,"toThread");
        capabilityField(missing,features,"squareCheckpointMp",saveThread,"fromThread");
        Class<?> saveTask=capabilityClass(missing,features,"squareCheckpointMp","zombie.network.ServerChunkLoader$SaveLoadedTask");
        Class<?> request=capabilityClass(missing,features,"squareCheckpointMp","zombie.network.ClientChunkRequest");
        Class<?> requestChunk=capabilityClass(missing,features,"squareCheckpointMp","zombie.network.ClientChunkRequest$Chunk");
        capabilityConstructor(missing,features,"squareCheckpointMp",saveTask,loaderType,request,requestChunk);
        capabilityConstructor(missing,features,"squareCheckpointMp",request);
        capabilityMethod(missing,features,"squareCheckpointMp",request,"getChunk");
        capabilityMethod(missing,features,"squareCheckpointMp",request,"getByteBuffer",requestChunk);
        capabilityField(missing,features,"squareCheckpointMp",requestChunk,"wx");
        capabilityField(missing,features,"squareCheckpointMp",requestChunk,"wy");
        capabilityField(missing,features,"squareCheckpointMp",requestChunk,"bb");
        // SP square/chunk checkpoint: ChunkSaveWorker.toSaveQueue and QueuedSave.
        Class<?> queued=capabilityClass(missing,features,"squareCheckpointSp","zombie.iso.ChunkSaveWorker$QueuedSave");
        capabilityConstructor(missing,features,"squareCheckpointSp",queued,IsoChunk.class,boolean.class);
        capabilityMethod(missing,features,"squareCheckpointSp",queued,"allocBuffer");
        capabilityField(missing,features,"squareCheckpointSp",queued,"crc");
        capabilityField(missing,features,"squareCheckpointSp",queued,"byteBuffer");
        capabilityField(missing,features,"squareCheckpointSp",queued,"chunk");
        Class<?> chunkSaveWorker=capabilityClass(missing,features,"squareCheckpointSp","zombie.iso.ChunkSaveWorker");
        capabilityField(missing,features,"squareCheckpointSp",chunkSaveWorker,"instance");
        capabilityField(missing,features,"squareCheckpointSp",chunkSaveWorker,"toSaveQueue");
        // Skeleton removal-clock contract shared with the ledger.
        Class<?> skeleton=SkeletonLifetime.class;
        capabilityMethod(missing,features,"skeletonLifetime",skeleton,"install",KahluaTable.class);
        capabilityMethod(missing,features,"skeletonLifetime",skeleton,"installClocks",Map.class);
        capabilityMethod(missing,features,"skeletonLifetime",skeleton,"readClocks",KahluaTable.class);
        for(String group:CAPABILITY_GROUPS) features.putIfAbsent(group,true);
        return missing;
    }
    // Explicit, never-throwing capability classification for Lua. The Lua side
    // calls this once per runtime and fails closed before any read/write/reset.
    public static KahluaTable capabilities() {
        KahluaTable result;
        try { result=LuaManager.platform.newTable(); }
        catch(Exception|LinkageError error) { return null; }
        List<String> missing=new ArrayList<>();
        Map<String,Boolean> features=new java.util.LinkedHashMap<>();
        int worldVersion=0;
        try {
            missing.addAll(capabilityProblems(features));
            try { worldVersion=IsoWorld.getWorldVersion(); }
            catch(Exception|LinkageError error) {
                features.put("worldVersion",false);
                missing.add("worldVersion: missing IsoWorld.getWorldVersion() ("+describe(error)+")");
            }
            KahluaTable featureTable=LuaManager.platform.newTable();
            for(var entry:features.entrySet()) featureTable.rawset(entry.getKey(),entry.getValue());
            boolean ok=missing.isEmpty();
            result.rawset("ok",ok);
            result.rawset("status",ok?"ok":"incompatible");
            if(!ok) {
                result.rawset("reason",missing.get(0));
                KahluaTable every=LuaManager.platform.newTable();
                for(int i=0;i<missing.size();i++) every.rawset((double)(i+1),missing.get(i));
                result.rawset("missing",every);
            }
            result.rawset("ledgerFormat","CVPEQ1");
            result.rawset("worldVersion",(double)worldVersion);
            result.rawset("features",featureTable);
        } catch(Exception|LinkageError error) {
            try {
                result.rawset("ok",false);
                result.rawset("status","incompatible");
                result.rawset("reason","capability probe failed: "+describe(error));
                result.rawset("ledgerFormat","CVPEQ1");
                result.rawset("worldVersion",(double)worldVersion);
                result.rawset("features",LuaManager.platform.newTable());
            } catch(Exception|LinkageError ignored) {}
        }
        return result;
    }
    interface Replace { void move(Path from,Path to) throws Exception; }
    private static void validate(KahluaTable table,IdentityHashMap<KahluaTable,Boolean> path,int depth,int[] budget) {
        if(table==null || depth>32 || path.put(table,true)!=null) throw new IllegalArgumentException("invalid ledger table nesting");
        var it=table.iterator();
        while(it.advance()) {
            if(--budget[0]<0 || !KahluaTableImpl.canSave(it.getKey(),it.getValue())) throw new IllegalArgumentException("invalid ledger value or size");
            for(Object value:new Object[]{it.getKey(),it.getValue()})
                if(value instanceof String text && text.getBytes(StandardCharsets.UTF_8).length>32767)
                    throw new IllegalArgumentException("ledger string too large");
            if(it.getValue() instanceof KahluaTable child) validate(child,path,depth+1,budget);
        }
        path.remove(table);
    }
    static synchronized void writeFile(Path file,KahluaTable data,Replace replace) throws Exception {
        writeFrame(file,frame(data),replace);
    }
    private static synchronized byte[] frame(KahluaTable data) throws Exception {
        validate(data,new IdentityHashMap<>(),0,new int[]{65536});
        ByteBuffer buffer;
        while(true) {
            buffer=ledgerBuffer;buffer.clear();
            try { data.save(buffer);break; }
            catch(BufferOverflowException overflow) {
                if(buffer.capacity()>=MAX_LEDGER) throw overflow;
                ledgerBuffer=ByteBuffer.allocate(Math.min(MAX_LEDGER,buffer.capacity()*2));
            }
        }
        byte[] payload=Arrays.copyOf(buffer.array(),buffer.position());
        ByteBuffer framed=ByteBuffer.allocate(MAGIC.length+8+32+payload.length);
        framed.put(MAGIC).putInt(IsoWorld.getWorldVersion()).putInt(payload.length);
        framed.put(MessageDigest.getInstance("SHA-256").digest(payload)).put(payload).flip();
        return framed.array();
    }
    private static void writeFrame(Path file,byte[] bytes,Replace replace) throws Exception {
        ByteBuffer framed=ByteBuffer.wrap(bytes);
        Path stage=file.resolveSibling(file.getFileName()+".tmp");
        if(Files.isSymbolicLink(file) || Files.isSymbolicLink(stage)) throw new IOException("ledger symlink refused");
        try {
            try(FileChannel channel=FileChannel.open(stage,StandardOpenOption.CREATE,StandardOpenOption.TRUNCATE_EXISTING,StandardOpenOption.WRITE)) {
                while(framed.hasRemaining()) channel.write(framed);
                channel.force(true);
            }
            replace.move(stage,file);
        } finally { Files.deleteIfExists(stage); }
    }
    static KahluaTable readFile(Path file) throws Exception {
        if(Files.isSymbolicLink(file)) throw new IOException("ledger symlink refused");
        if(!Files.exists(file)) return null;
        long size=Files.size(file);int header=MAGIC.length+8+32;
        if(size<header || size>MAX_LEDGER+header) throw new CorruptLedger("invalid equipment ledger size");
        ByteBuffer buffer=ByteBuffer.wrap(Files.readAllBytes(file));byte[] magic=new byte[MAGIC.length];buffer.get(magic);
        if(!Arrays.equals(magic,MAGIC)) throw new UnsupportedLedger("unsupported equipment ledger format");
        if(buffer.getInt()!=IsoWorld.getWorldVersion()) throw new UnsupportedLedger("unsupported equipment ledger world version");
        int length=buffer.getInt();byte[] checksum=new byte[32];buffer.get(checksum);
        if(length!=buffer.remaining()) throw new CorruptLedger("truncated equipment ledger");
        byte[] payload=new byte[length];buffer.get(payload);
        if(!Arrays.equals(checksum,MessageDigest.getInstance("SHA-256").digest(payload))) throw new CorruptLedger("equipment ledger checksum mismatch");
        KahluaTable result=LuaManager.platform.newTable();ByteBuffer source=ByteBuffer.wrap(payload);
        try { result.load(source,IsoWorld.getWorldVersion()); }
        catch(RuntimeException malformed) { throw new CorruptLedger("invalid equipment ledger payload"); }
        if(source.hasRemaining()) throw new CorruptLedger("equipment ledger trailing data");
        try { validate(result,new IdentityHashMap<>(),0,new int[]{65536}); }
        catch(IllegalArgumentException malformed) { throw new CorruptLedger("invalid equipment ledger values"); }
        return result;
    }
    private static Object field(Object object,String name) throws Exception {
        Class<?> type=object instanceof Class<?> c?c:object.getClass();Field f=type.getDeclaredField(name);f.setAccessible(true);
        return f.get(object instanceof Class<?>?null:object);
    }
    private static void field(Object object,String name,Object value) throws Exception {
        Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);
    }
    private static Object create(String name,Class<?>[] types,Object... args) throws Exception {
        Constructor<?> c=Class.forName(name).getDeclaredConstructor(types);c.setAccessible(true);return c.newInstance(args);
    }
    private static Object call(Object target,String name,Class<?>[] types,Object... args) throws Exception {
        Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,args);
    }
    @SuppressWarnings("unchecked")
    private static Queue<Object> queue(Object owner,String name) throws Exception { return (Queue<Object>)field(owner,name); }
    private static byte[] bytes(ByteBuffer source) {
        ByteBuffer copy=source.duplicate();copy.position(0);byte[] result=new byte[copy.remaining()];copy.get(result);return result;
    }
    private static void worker(Thread thread) {
        if(thread==null || !thread.isAlive() || Thread.currentThread()==thread) throw new IllegalStateException("native save worker unavailable");
    }
    private static int slot(IsoPlayer player,UdpConnection connection) {
        if(connection==null) throw new IllegalArgumentException("player connection unavailable");
        for(int i=0;i<connection.players.length;i++) if(connection.players[i]==player) return i;
        throw new IllegalArgumentException("player is not owned by connection");
    }
    private static void localID(IsoPlayer player) {
        if(!PlayerDB.isAvailable()) throw new IllegalStateException("local player database unavailable");
        boolean local=false;for(IsoPlayer p:IsoPlayer.players) if(p==player) local=true;
        if(!local) throw new IllegalArgumentException("not a local player");
        // The native enqueue path allocates sqlId through PlayerDB's own used-ID registry.
        if(player.sqlId<1) PlayerDB.getInstance().saveLocalPlayersForce();
        if(player.sqlId<1) throw new IllegalStateException("local player identity unavailable");
    }
    interface Checkpoint { void run() throws Exception; }
    interface Probe { boolean saved() throws Exception; }
    static void awaitCheckpoint(Probe completed,Probe readback,String kind,long timeout) throws Exception {
        long start=System.nanoTime();Exception last=null;
        while(System.nanoTime()-start<timeout) {
            try { if(completed.saved() && readback.saved()) return; } catch(Exception error) { last=error; }
            // SP chunk saves synchronously request ancillary saves on this thread.
            // Native WorldStreamer.stop uses this same pump while waiting for its worker.
            if(!GameServer.server && Thread.currentThread()==GameWindow.gameThread) zombie.MainThread.busyWait();
            Thread.sleep(10);
        }
        throw new IOException(kind+" checkpoint outcome unknown; keep recovery record",last);
    }
    static String actorKey(KahluaTable data,String slot,Checkpoint checkpoint) throws Exception {
        Object value=data.rawget(ACTOR);
        if(value==null) { value=UUID.randomUUID().toString();data.rawset(ACTOR,value);pendingActors.put(data,true); }
        if(!(value instanceof String id) || !UUID.fromString(id).toString().equals(id)) throw new IllegalStateException("invalid equipment actor identity");
        if(pendingActors.containsKey(data)) { checkpoint.run();pendingActors.remove(data); }
        return slot+":"+id;
    }
    public static SaveJob playerKeyAsync(IsoPlayer player) throws Exception {
        authority();String key=playerKeyPrefix(player);if(key==null) return null;
        KahluaTable data=player.getModData();
        Object value=data.rawget(ACTOR);
        if(value==null) { value=UUID.randomUUID().toString();data.rawset(ACTOR,value);pendingActors.put(data,true); }
        if(!(value instanceof String id) || !UUID.fromString(id).toString().equals(id)) throw new IllegalStateException("invalid equipment actor identity");
        SaveJob job;
        if(pendingActors.containsKey(data)) { job=checkpointPlayerAsync(player);job.accepted=()->pendingActors.remove(data); }
        else { job=new SaveJob();job.done=true; }
        job.value=key+":"+id;return job;
    }
    public static String playerKey(IsoPlayer player) throws Exception {
        String key=playerKeyPrefix(player);if(key==null) return null;
        return actorKey(player.getModData(),key,()->checkpointPlayer(player));
    }
    private static String playerKeyPrefix(IsoPlayer player) throws Exception {
        authority();if(player==null) throw new IllegalArgumentException("player required");
        String key;
        if(GameServer.server) {
            UdpConnection connection=GameServer.getConnectionFromPlayer(player);
            // A disconnected owner is unavailable, not permission to reconstruct its inventory.
            if(connection==null) return null;
            int index=slot(player,connection);
            boolean steam=GameServer.coop && SteamUtils.isSteamModeEnabled();
            String owner=steam?connection.getIDStr():connection.getUserName();
            key="MP:"+(steam?"S":"U")+":"+Base64.getUrlEncoder().withoutPadding().encodeToString(owner.getBytes(StandardCharsets.UTF_8))+":"+index;
        } else { localID(player);key="SP:"+player.sqlId; }
        return key;
    }
    public static boolean checkpointPlayer(IsoPlayer player) throws Exception {
        SaveJob job=checkpointPlayerAsync(player);if(job==null) return false;
        try { awaitCheckpoint(job.completion,job.readback,"player",TIMEOUT_NANOS);return true; }
        finally { acknowledgements.remove(job.task); }
    }
    public static SaveJob checkpointPlayerAsync(IsoPlayer player) throws Exception {
        authority();if(player==null) throw new IllegalArgumentException("player required");
        Path database=saveDir().resolve("players.db");Object record;byte[] expected;String query;Object[] keys;
        Queue<Object> destination;Probe completed;Object marker=null;
        if(GameServer.server) {
            UdpConnection connection=GameServer.getConnectionFromPlayer(player);
            // A disconnected owner is unavailable, not permission to reconstruct its inventory.
            if(connection==null) return null;
            int index=slot(player,connection);
            if(!ServerPlayerDB.isAvailable()) throw new IllegalStateException("server player database unavailable");
            worker((Thread)field(ServerPlayersVehicles.instance,"thread"));
            record=create("zombie.savefile.ServerPlayerDB$NetworkCharacterData",new Class<?>[]{IsoPlayer.class,int.class,UdpConnection.class},player,index,connection);
            byte[] snapshot=(byte[])field(record,"buffer");
            if(snapshot==null || snapshot.length==0) throw new IOException("native player snapshot unavailable");
            expected=snapshot.clone();
            boolean steam=GameServer.coop && SteamUtils.isSteamModeEnabled();
            query="SELECT data,worldversion FROM networkPlayers WHERE "+(steam?"steamid":"username")+"=? AND world=? AND playerIndex=?";
            keys=new Object[]{field(record,steam?"steamid":"username"),Core.gameSaveWorld,index};
            destination=queue(ServerPlayerDB.getInstance(),"charactersToSave");
            // B42.21 private API: index < 0 returns before any SQL/side effects.
            // A marker polled by the sole worker proves every earlier save has finished.
            marker=create("zombie.savefile.ServerPlayerDB$NetworkCharacterData",new Class<?>[]{IsoPlayer.class,int.class,UdpConnection.class},player,-1,connection);
            Object barrier=marker;completed=()->!destination.contains(barrier);
        } else {
            worker(WorldStreamer.instance.worldStreamer);localID(player);
            record=create("zombie.savefile.PlayerDB$PlayerData",new Class<?>[]{});
            call(record,"set",new Class<?>[]{IsoPlayer.class},player);
            expected=bytes((ByteBuffer)field(record,"byteBuffer"));
            query="SELECT data,worldversion FROM localPlayers WHERE id=?";keys=new Object[]{player.sqlId};
            destination=queue(PlayerDB.getInstance(),"toThread");
            Queue<Object> finished=queue(PlayerDB.getInstance(),"fromThread");completed=()->finished.contains(record);
        }
        if(!Files.isRegularFile(database)) throw new IOException("player database file unavailable");
        int version=IsoWorld.getWorldVersion();
        SaveJob job=checkpointJob(record,completed,()->{
            SQLiteConfig config=new SQLiteConfig();config.setReadOnly(true);config.setBusyTimeout(50);
            try(Connection connection=DriverManager.getConnection("jdbc:sqlite:"+database,config.toProperties());
                PreparedStatement statement=connection.prepareStatement(query)) {
                for(int i=0;i<keys.length;i++) statement.setObject(i+1,keys[i]);
                try(var result=statement.executeQuery()) {
                    if(result.next() && result.getInt(2)==version && Arrays.equals(expected,result.getBytes(1))) {
                        if(result.next()) throw new IOException("ambiguous persisted player identity");return true;
                    }
                    return false;
                }
            }
        });
        destination.add(record);if(marker!=null) destination.add(marker);return job;
    }
    public static boolean checkpointSquare(IsoGridSquare square) throws Exception {
        SaveJob job=checkpointSquareAsync(square);
        try { awaitCheckpoint(job.completion,()->{
            try { boolean saved=job.readback.saved();if(!saved) job.rejected.run();return saved; }
            catch(Exception error) { job.rejected.run();throw error; }
        },"chunk",TIMEOUT_NANOS);return true; }
        finally { acknowledgements.remove(job.task); }
    }
    public static SaveJob checkpointSquareAsync(IsoGridSquare square) throws Exception {
        authority();if(square==null || square.getChunk()==null) throw new IllegalArgumentException("loaded square required");
        IsoChunk chunk=square.getChunk();byte[] expected;Object task;Queue<Object> destination;Probe completed;
        if(GameServer.server) {
            Object loader=field(Class.forName("zombie.network.ServerMap$ServerCell"),"chunkLoader");
            Object thread=field(loader,"threadSave");worker((Thread)thread);
            ClientChunkRequest request=new ClientChunkRequest();ClientChunkRequest.Chunk saved=request.getChunk();
            saved.wx=chunk.wx;saved.wy=chunk.wy;request.getByteBuffer(saved);chunk.SaveLoadedChunk(saved,new CRC32());
            ByteBuffer copy=saved.bb.duplicate();copy.flip();expected=bytes(copy);
            task=create("zombie.network.ServerChunkLoader$SaveLoadedTask",new Class<?>[]{loader.getClass(),ClientChunkRequest.class,ClientChunkRequest.Chunk.class},loader,request,saved);
            destination=queue(thread,"toThread");
            Queue<Object> finished=queue(thread,"fromThread");completed=()->finished.contains(task);
        } else {
            worker(WorldStreamer.instance.worldStreamer);
            task=create("zombie.iso.ChunkSaveWorker$QueuedSave",new Class<?>[]{IsoChunk.class,boolean.class},chunk,true);
            call(task,"allocBuffer",new Class<?>[]{});CRC32 crc=(CRC32)field(task,"crc");
            ByteBuffer saved=chunk.Save((ByteBuffer)field(task,"byteBuffer"),crc,true);field(task,"byteBuffer",saved);
            ByteBuffer copy=saved.duplicate();copy.flip();expected=bytes(copy);
            destination=queue(ChunkSaveWorker.instance,"toSaveQueue");
            // Native WriteQueuedSave clears chunk only after its write attempt and cleanup.
            completed=()->field(task,"chunk")==null;
        }
        Path file=ChunkMapFilenames.instance.getFilename(chunk.wx,chunk.wy).toPath().toAbsolutePath().normalize();
        if(!file.startsWith(saveDir())) throw new IOException("chunk outside current save");
        int wx=chunk.wx,wy=chunk.wy;
        SaveJob job=checkpointJob(task,completed,()->verifyChunkBytes(file,expected));
        job.rejected=()->ChunkChecksum.setChecksum(wx,wy,-1L);
        destination.add(task);return job;
    }
    // Called only after native completion. Both native writers cache the new CRC
    // before SafeWrite, so a failed write must not suppress the next recovery save.
    static boolean verifyChunkFile(Path file,byte[] expected,int wx,int wy) throws IOException {
        try {
            boolean matches=verifyChunkBytes(file,expected);
            if(!matches) ChunkChecksum.setChecksum(wx,wy,-1L);return matches;
        } catch(IOException error) { ChunkChecksum.setChecksum(wx,wy,-1L);throw error; }
    }
    private static boolean verifyChunkBytes(Path file,byte[] expected) throws IOException {
        if(Files.size(file)!=expected.length || !Arrays.equals(Files.readAllBytes(file),expected)) return false;
        try(FileChannel channel=FileChannel.open(file,StandardOpenOption.WRITE)) { channel.force(true); }
        return true;
    }
}
