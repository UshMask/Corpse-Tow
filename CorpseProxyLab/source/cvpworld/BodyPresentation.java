package cvpworld;

import java.util.IdentityHashMap;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.iso.objects.IsoDeadBody;
import se.krka.kahlua.vm.KahluaTable;

/** Draw-only translation. World positions, squares, angles and saves are untouched. */
@LuaClass(name="CVPBodyPresentation")
public final class BodyPresentation {
    private static final IdentityHashMap<IsoDeadBody,double[]> offsets=new IdentityHashMap<>();
    private static final ThreadLocal<double[]> scope=ThreadLocal.withInitial(()->new double[2]);
    public static String version(){return "1-shared-playback";}
    public static boolean stockSupported(){
        return !zombie.core.PerformanceSettings.fboRenderChunk
            || !zombie.debug.DebugOptions.instance.fboRenderChunk.corpsesInChunkTexture.getValue();
    }
    private static void set(IsoDeadBody body,double dx,double dy) {
        if(body==null)return;
        if(!Double.isFinite(dx)||!Double.isFinite(dy)||dx*dx+dy*dy>64) {offsets.remove(body);return;}
        double[] p=offsets.computeIfAbsent(body,b->new double[2]);p[0]=dx;p[1]=dy;
    }
    public static synchronized void update(KahluaTable records){
        int count=records.len();
        for(int i=1;i<=count;i++){
            var r=(KahluaTable)records.rawget(i);
            if(r.rawget("body") instanceof IsoDeadBody body){
                Object x=r.rawget("drawDX"),y=r.rawget("drawDY");
                set(body,x instanceof Number n?n.doubleValue():0,y instanceof Number n?n.doubleValue():0);
            }
        }
    }
    public static synchronized void remove(IsoDeadBody body){offsets.remove(body);}
    public static synchronized void clear(){offsets.clear();end();}
    public static synchronized void begin(IsoDeadBody body){
        double[] p=offsets.get(body),out=scope.get();out[0]=p==null?0:p[0];out[1]=p==null?0:p[1];
    }
    public static void end(){double[] p=scope.get();p[0]=0;p[1]=0;}
    public static float dx(){return (float)scope.get()[0];}
    public static float dy(){return (float)scope.get()[1];}
}
