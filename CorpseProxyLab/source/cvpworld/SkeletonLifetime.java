package cvpworld;

import java.util.IdentityHashMap;
import java.util.HashMap;
import java.util.Map;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import se.krka.kahlua.vm.KahluaTable;
import zombie.GameTime;
import zombie.SandboxOptions;
import zombie.Lua.LuaManager;
import zombie.iso.objects.IsoDeadBody;
import zombie.network.GameClient;

/** Persist only the removal clock. Never rejuvenate the corpse or stop rotting. */
@LuaClass(name="CVPSkeletonNative")
public final class SkeletonLifetime {
    private static final String KEY="CVPSkeletonRemoval";
    private static final IdentityHashMap<IsoDeadBody,Float> originals=new IdentityHashMap<>();
    private static boolean updating;
    private static Map<String,GraphClock> graphClocks=Map.of();
    private static String loadedSave;
    private static boolean unavailable;
    private static long retryAfter;
    record GraphClock(String epoch,double started,double at,double elapsed,boolean paused) {
        double elapsedAt(double now) { return elapsed+(paused?0:Math.max(0,now-at)); }
    }
    private SkeletonLifetime() {}
    public static String version() { return "2-graph-clocks"; }
    private static KahluaTable table(Object value) { return value instanceof KahluaTable t?t:null; }
    private static boolean key(Object value) { return value instanceof String s && !s.isEmpty() && s.length()<=256; }
    private static double number(Object value,double fallback) {
        return value instanceof Number n && Double.isFinite(n.doubleValue())?n.doubleValue():fallback;
    }
    static Map<String,GraphClock> readClocks(KahluaTable ledger) {
        Map<String,GraphClock> clocks=new HashMap<>();
        KahluaTable rows=ledger==null?null:table(ledger.rawget("bodyClocks"));
        if(ledger!=null && ledger.rawget("bodyClocks")!=null && rows==null) throw new IllegalArgumentException("invalid body clock map");
        if(rows!=null) {
            var it=rows.iterator();while(it.advance()) {
                KahluaTable row=table(it.getValue());
                if(!key(it.getKey()) || row==null || !key(row.rawget("epoch"))) throw new IllegalArgumentException("invalid body clock identity");
                double started=number(row.rawget("started"),Double.NaN),at=number(row.rawget("at"),Double.NaN),
                    elapsed=number(row.rawget("elapsed"),Double.NaN);
                if(!Double.isFinite(started) || !Double.isFinite(at) || at<started || !Double.isFinite(elapsed) || elapsed<0
                    || !(row.rawget("paused") instanceof Boolean paused)) throw new IllegalArgumentException("invalid body clock values");
                clocks.put((String)it.getKey(),new GraphClock((String)row.rawget("epoch"),started,at,elapsed,paused));
            }
        }
        return Map.copyOf(clocks);
    }
    static void install(KahluaTable ledger) { installClocks(readClocks(ledger)); }
    static void installClocks(Map<String,GraphClock> clocks) {
        graphClocks=clocks;loadedSave=zombie.ZomboidFileSystem.instance.getCurrentSaveDir();unavailable=false;retryAfter=0;
    }
    private static void ensureLedger() {
        if(GameClient.client) return;
        String save=zombie.ZomboidFileSystem.instance.getCurrentSaveDir();
        if(!save.equals(loadedSave)) {graphClocks=Map.of();loadedSave=null;unavailable=true;retryAfter=0;}
        if(loadedSave!=null && !unavailable || System.nanoTime()<retryAfter) return;
        try {EquipmentPersistence.read();}
        catch(Exception failure) {
            if(retryAfter==0) System.err.println("[CVP-Skeleton] removal clock pending equipment ledger: "+failure);
            loadedSave=save;unavailable=true;retryAfter=System.nanoTime()+5_000_000_000L;
        }
    }
    private static GraphClock graph(KahluaTable data) {
        Object key=data.rawget("CVPBodyKey");return key instanceof String s?graphClocks.get(s):null;
    }
    private static boolean bound(KahluaTable data,GraphClock clock) {
        if(data.rawget("CorpseTowingVehicleToken")!=null) return false;
        if(unavailable && key(data.rawget("CVPBodyKey"))) return true;
        return clock!=null?clock.paused:attached(data);
    }
    static boolean attached(KahluaTable data) {
        KahluaTable md=table(data.rawget("CVPTether"));
        if(md==null || Boolean.TRUE.equals(md.rawget("ended")) || data.rawget("CorpseTowingVehicleToken")!=null) return false;
        double version=number(md.rawget("version"),0);
        KahluaTable c=table(md.rawget("connection"));
        if((version!=2 && version!=3) || c==null || !key(c.rawget("id"))) return false;
        KahluaTable a=table(c.rawget("a")),b=table(c.rawget("b"));
        if(a==null || b==null || !"body".equals(b.rawget("kind")) || !key(b.rawget("key"))) return false;
        Object bodyKey=data.rawget("CVPBodyKey");
        if(bodyKey!=null && !bodyKey.equals(b.rawget("key"))) return false;
        return ("vehicle".equals(a.rawget("kind")) && key(a.rawget("key")))
            || ("body".equals(a.rawget("kind")) && key(a.rawget("key"))
                && key(md.rawget("rootVehicle")) && key(md.rawget("parentConnection")));
    }
    // The last persisted timestamp allows unloading/restarting without spending paused hours.
    static double clock(KahluaTable data,double now,double death,double lifetime,boolean skeleton,boolean bound) {
        return clock(data,now,death,lifetime,skeleton,bound,null);
    }
    static double clock(KahluaTable data,double now,double death,double lifetime,boolean skeleton,boolean bound,GraphClock graph) {
        if(!skeleton || !Double.isFinite(now) || !Double.isFinite(death) || lifetime<=0) return Double.NaN;
        KahluaTable row=table(data.rawget(KEY));
        if(row==null && !bound && graph==null) return Double.NaN;
        if(row==null || number(row.rawget("death"),Double.NaN)!=death) {
            row=LuaManager.platform.newTable();data.rawset(KEY,row);
            row.rawset("death",death);row.rawset("remaining",Math.max(0,lifetime-(now-death)));
            row.rawset("at",now);row.rawset("paused",bound);
            row.rawset("protected",bound || graph==null);
            // A newly observed skeleton receives no retroactive credit for the
            // time it was a fresh corpse, even if its graph existed earlier.
            if(graph!=null) {row.rawset("epoch",graph.epoch);row.rawset("elapsed",graph.elapsedAt(now));}
        }
        double remaining=Math.max(0,number(row.rawget("remaining"),0));
        if(graph!=null) {
            double elapsed=graph.elapsedAt(now);
            // A body-only graph has not earned a pause. Until the first paused
            // interval it must still use this pass's native removal threshold
            // (which can vary after an animal or a sandbox setting change).
            boolean natural=Boolean.FALSE.equals(row.rawget("protected")) && !bound
                && elapsed>=Math.max(0,now-graph.started)-1e-8;
            if(natural) remaining=Math.max(0,lifetime-(now-death));
            else if(graph.epoch.equals(row.rawget("epoch")))
                remaining=Math.max(0,remaining-Math.max(0,elapsed-number(row.rawget("elapsed"),elapsed)));
            else {
                // Import the 0.3 body clock up to graph enrollment, then spend
                // exactly the unpaused hours recorded while the body was absent.
                if(!Boolean.TRUE.equals(row.rawget("paused")))
                    remaining=Math.max(0,remaining-Math.max(0,graph.started-number(row.rawget("at"),graph.started)));
                remaining=Math.max(0,remaining-elapsed);
            }
            if(!natural) row.rawset("protected",true);
            row.rawset("epoch",graph.epoch);row.rawset("elapsed",elapsed);
        } else if(!Boolean.TRUE.equals(row.rawget("paused")))
            remaining=Math.max(0,remaining-Math.max(0,now-number(row.rawget("at"),now)));
        row.rawset("remaining",remaining);row.rawset("at",now);row.rawset("paused",bound);
        return remaining;
    }
    public static void sync(IsoDeadBody body) {
        if(GameClient.client || body==null || !body.isSkeleton()) return;
        ensureLedger();
        double hours=SandboxOptions.instance.hoursForCorpseRemoval.getValue();
        double now=GameTime.getInstance().getWorldAgeHours();
        var data=body.getModData();var graph=graph(data);
        clock(data,now,originals.getOrDefault(body,body.getDeathTime()),hours*4/3,true,bound(data,graph),graph);
    }
    public static boolean retire(IsoDeadBody body,String epoch) {
        if(GameClient.client || body==null) return false;
        ensureLedger();var row=graph(body.getModData());
        if(unavailable || row==null || row.paused || !row.epoch.equals(epoch)) return false;
        sync(body);return true;
    }
    public static void begin() { if(!GameClient.client) {ensureLedger();updating=true;} }
    public static void afterRotting(IsoDeadBody body,float now,float stageHours) {
        if(!updating || GameClient.client || !body.isSkeleton()) return;
        float death=originals.getOrDefault(body,body.getDeathTime());
        var graph=graph(body.getModData());boolean bound=bound(body.getModData(),graph);
        // Match updateBodies' actual comparison. Its stageHours can be hours/4
        // after an animal in the same pass, rather than the usual hours/3.
        float lifetime=(float)SandboxOptions.instance.hoursForCorpseRemoval.getValue()+stageHours;
        double remaining=clock(body.getModData(),now,death,lifetime,true,bound,graph);
        if(!Double.isFinite(remaining)) return;
        originals.putIfAbsent(body,death);
        // Only the vanilla removal comparison sees this effective age; finally restores history.
        double effective=now-lifetime+(bound?Math.max(remaining,.01):remaining);
        body.setDeathTime((float)effective);
        // At large world ages float rounding must still keep a held skeleton below expiry.
        if(bound && now-body.getDeathTime()>=lifetime)
            body.setDeathTime(Math.nextUp(body.getDeathTime()));
    }
    public static void finish() {
        try { for(var entry:originals.entrySet()) entry.getKey().setDeathTime(entry.getValue()); }
        finally { originals.clear();updating=false; }
    }
}
