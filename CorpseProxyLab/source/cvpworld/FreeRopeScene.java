package cvpworld;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.function.BooleanSupplier;
import java.util.function.DoubleBinaryOperator;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import org.joml.Matrix4f;
import org.joml.Vector3f;
import org.joml.Vector3d;
import org.lwjgl.opengl.GL11;
import se.krka.kahlua.vm.KahluaTable;
import zombie.core.SpriteRenderer;
import zombie.core.Core;
import zombie.core.opengl.IModelCamera;
import zombie.core.skinnedmodel.ModelManager;
import zombie.core.skinnedmodel.model.Model;
import zombie.core.skinnedmodel.model.ModelSlotRenderData;
import zombie.core.textures.Texture;
import zombie.core.textures.TextureDraw;
import zombie.iso.IsoCamera;
import zombie.iso.IsoCell;
import zombie.iso.IsoDepthHelper;
import zombie.iso.IsoGridSquare;
import zombie.vehicles.BaseVehicle;

/** Render-only world geometry: no vehicle, inventory item or world object carrier. */
@LuaClass(name="CVPFreeRopeScene")
public final class FreeRopeScene {
    private static final LinkedHashMap<String,Snapshot> links=new LinkedHashMap<>();
    private static final java.util.HashMap<String,Integer> highlights=new java.util.HashMap<>();
    public static void highlight(String id,int player,boolean enabled) {
        if(id==null || player<0 || player>3) return;
        int mask=highlights.getOrDefault(id,0),bit=1<<player;
        mask=enabled?mask|bit:mask&~bit;
        if(mask==0) highlights.remove(id);else highlights.put(id,mask);
    }
    public static boolean highlighted(String id,int player) {
        return (highlights.getOrDefault(id,0)&(1<<player))!=0;
    }
    private static final LinkedHashMap<String,VehicleEnd> vehicleEnds=new LinkedHashMap<>();
    private static final IdentityHashMap<BaseVehicle,VehicleAnchor[]> vehicles=new IdentityHashMap<>();
    private static final IdentityHashMap<VehicleAnchor,StockFrame> stockFrames=new IdentityHashMap<>();
    private static final ArrayBlockingQueue<Drawer> pool=new ArrayBlockingQueue<>(256);
    private static final ArrayBlockingQueue<ArrayList<Snapshot>> captureLists=new ArrayBlockingQueue<>(4);
    private static final Model[] models=new Model[3];
    private static final Texture[] textures=new Texture[2];
    private static volatile String error="";
    private static String reportedError="";
    private static volatile long retryAt;
    private static final long RETRY_NANOS=5_000_000_000L;
    private static long captures,segments;
    private static BooleanSupplier perspective=()->false;
    // Vehicle-style camera used by 0.3.0: unlike WorldModelCamera it includes
    // PlayerCamera.tOffX/tOffY. Cancel only its local Z reflection, not its pan.
    private static final Matrix4f objectPlacement=new Matrix4f().scale(-1,1,1).rotateY((float)Math.PI);
    private static final Matrix4f objectInverse=new Matrix4f(objectPlacement).invert();
    private static final ThreadLocal<Vector3f[]> scratch=ThreadLocal.withInitial(()->new Vector3f[]{new Vector3f(),new Vector3f()});
    public record Snapshot(String id,double[] points,boolean chain,Object[] keys) {}
    private record VehicleEnd(BaseVehicle vehicle,VehicleAnchor anchor,boolean first) {}
    private static final class VehicleAnchor {
        final boolean front;
        VehicleAnchor(boolean front) {this.front=front;}
        final Vector3f local=new Vector3f();
        final Vector3f live=new Vector3f();
        final Vector3d view=new Vector3d();
        StockCalibration stockCalibration=new StockCalibration();
        int users;boolean calibrated,viewReady;
    }
    private FreeRopeScene() {}
    public static String version() { return "1-free-endpoints"; }
    public static String error() { return error; }
    public static int count() { return links.size(); }
    public static long captures() { return captures; }
    public static long segments() { return segments; }
    public static void setPerspective(BooleanSupplier active) { perspective=active; }
    /** One Lua call per curve; no per-point Lua tables or mutable render snapshots. */
    public static void shape(String id,KahluaTable record,double ax,double ay,double az,double dt,boolean chain) {
        if(zombie.network.GameServer.server) return;
        if(id==null || id.isEmpty() || id.length()>256) throw new IllegalArgumentException("valid connection ID required");
        RopeShape.State state=RopeShape.advance(record,ax,ay,az,dt,chain);
        Snapshot old=links.get(id);
        double[] xyz=old!=null && old.points.length==state.points.length*3 && old.chain==chain?null:new double[state.points.length*3];
        for(int i=0;i<state.points.length;i++) {
            RopeShape.Point p=state.points[i];int at=i*3;
            if(!Double.isFinite(p.x+p.y+p.z) || Math.max(Math.abs(p.x),Math.max(Math.abs(p.y),Math.abs(p.z)))>=10000000)
                throw new IllegalArgumentException("finite world point required");
            if(xyz==null && (old.points[at]!=p.x || old.points[at+1]!=p.y || old.points[at+2]!=p.z)) {
                xyz=new double[state.points.length*3];
                // Only the unchanged prefix needs copying; this loop writes the rest.
                System.arraycopy(old.points,0,xyz,0,at);
            }
            if(xyz!=null){xyz[at]=p.x;xyz[at+1]=p.y;xyz[at+2]=p.z;}
        }
        publish(id,xyz,chain,old);
    }
    /** Move both ends together between shape steps. No integration or history
     * feedback: the cosmetic solver retains its own independent shape state. */
    public static void endpoints(String id,double ax,double ay,double az,double bx,double by,double bz) {
        Snapshot row=links.get(id);if(row==null)return;
        if(!Double.isFinite(ax+ay+az+bx+by+bz))throw new IllegalArgumentException("finite endpoints required");
        double[] p=row.points;int last=p.length-3;
        double dx=ax-p[0],dy=ay-p[1],dz=az*3-p[2];
        double ex=bx-p[last],ey=by-p[last+1],ez=bz*3-p[last+2];
        if(dx==0&&dy==0&&dz==0&&ex==0&&ey==0&&ez==0)return;
        double[] out=new double[p.length];double floor=Math.floor(Math.min(az,bz))*3+.075;
        for(int i=0;i<=last;i+=3){
            double t=(double)i/last;
            out[i]=p[i]+dx*(1-t)+ex*t;out[i+1]=p[i+1]+dy*(1-t)+ey*t;
            out[i+2]=p[i+2]+dz*(1-t)+ez*t;
            if(i>0&&i<last)out[i+2]=Math.max(floor,out[i+2]);
        }
        publish(id,out,row.chain,row);
    }
    public static void update(String id,KahluaTable points,boolean chain) {
        if(zombie.network.GameServer.server) return;
        int length=points==null?0:points.len();
        if(id==null || id.isEmpty() || id.length()>256 || length<2 || length>33)
            throw new IllegalArgumentException("valid connection ID and 2..33 rope points required");
        int size=length*3;
        Snapshot old=links.get(id);
        double[] xyz=old!=null && old.points.length==size && old.chain==chain?null:new double[size];
        for(int i=0;i<size/3;i++) {
            if(!(points.rawget(i+1) instanceof KahluaTable point)) throw new IllegalArgumentException("rope point required");
            for(int axis=0;axis<3;axis++) {
                Object value=point.rawget(axis==0?"x":axis==1?"y":"z");
                if(!(value instanceof Number n) || !Double.isFinite(n.doubleValue()) || Math.abs(n.doubleValue())>=10000000)
                    throw new IllegalArgumentException("finite world point required");
                int at=i*3+axis;double coordinate=n.doubleValue();
                // Queued frames retain old.points. Never write into that array,
                // and publish only after every incoming coordinate is validated.
                if(xyz==null && old.points[at]!=coordinate) {
                    xyz=new double[size];
                    System.arraycopy(old.points,0,xyz,0,at);
                }
                if(xyz!=null) xyz[at]=coordinate;
            }
        }
        publish(id,xyz,chain,old);
    }
    /** Called only after the complete geometry has passed its input validation. */
    private static void publish(String id,double[] xyz,boolean chain,Snapshot old) {
        if(xyz==null)return;
        int count=xyz.length/3-1;
        Object[] keys=old!=null && old.keys.length==count && old.chain==chain?old.keys:new Object[count];
        if(keys[0]==null) for(int i=0;i<count;i++) keys[i]=new Object();
        links.put(id,new Snapshot(id,xyz,chain,keys));
    }
    public static void vehicle(String id,BaseVehicle vehicle,boolean first) {
        vehicle(id,vehicle,first,"hitch");
    }
    public static void vehicle(String id,BaseVehicle vehicle,boolean first,String point) {
        boolean front="front".equals(point);
        VehicleEnd old=vehicleEnds.get(id);
        if(old!=null && old.vehicle==vehicle && old.first==first && old.anchor.front==front) return;
        forgetVehicle(id);
        if(vehicle==null || !links.containsKey(id)) return;
        VehicleAnchor[] anchors=vehicles.computeIfAbsent(vehicle,v->new VehicleAnchor[2]);
        int side=front?1:0;
        if(anchors[side]==null) anchors[side]=new VehicleAnchor(front);
        VehicleAnchor anchor=anchors[side];anchor.users++;
        vehicleEnds.put(id,new VehicleEnd(vehicle,anchor,first));
    }
    private static void forgetVehicle(String id) {
        VehicleEnd old=vehicleEnds.remove(id);
        if(old!=null && --old.anchor.users==0) {
            VehicleAnchor[] anchors=vehicles.get(old.vehicle);anchors[old.anchor.front?1:0]=null;
            if(anchors[0]==null && anchors[1]==null) vehicles.remove(old.vehicle);
        }
    }
    public static void remove(String id) { links.remove(id);highlights.remove(id);forgetVehicle(id); }
    public static synchronized void clear() {
        links.clear();highlights.clear();VisualAttachment.clear();vehicleEnds.clear();vehicles.clear();stockFrames.clear();error="";reportedError="";retryAt=0;
    }
    public static boolean ready() { return error.isEmpty() || ready(System.nanoTime()); }
    static synchronized boolean ready(long now) {
        if(error.isEmpty()) return true;
        if(now-retryAt<0) return false;
        // Keep graph snapshots and motion keys. Reacquire native assets only on
        // a bounded retry, never once per failing frame.
        java.util.Arrays.fill(models,null);java.util.Arrays.fill(textures,null);pool.clear();
        for(var anchors:vehicles.values()) for(var anchor:anchors) if(anchor!=null) {anchor.calibrated=false;anchor.stockCalibration=new StockCalibration();anchor.viewReady=false;}
        error="";return true;
    }
    public static void beginStock() { stockFrames.clear(); }
    public static void endPerspective() { for(var anchors:vehicles.values()) for(var anchor:anchors) if(anchor!=null) anchor.viewReady=false; }
    static void calibrate(ModelSlotRenderData slot,Vector3f point,Vector3f local) {
        RopeGeometry.isoPoint(slot,point.x,point.y,point.z,local);
        new Matrix4f(slot.vehicleTransform).invert().transformPosition(local);
    }
    private static Vector3f attachment(BaseVehicle vehicle,VehicleAnchor anchor) {
        return attachment(vehicle,anchor,new Vector3f());
    }
    private static Vector3f attachment(BaseVehicle vehicle,VehicleAnchor anchor,Vector3f point) {
        String name=anchor.front?"trailerfront":"trailer";
        if(!vehicle.attachmentExist(name) || vehicle.getAttachmentWorldPos(name,point)==null) {
            vehicle.getWorldPos(0,0,(anchor.front?1:-1)*vehicle.getScript().getExtents().z/2,point);
            point.z=vehicle.getZ()+.25f;
        }
        return point;
    }
    static void placedAnchor(ModelSlotRenderData slot,Vector3f local,Matrix4f place,
                             float cx,float cy,float cz,Vector3d out) {
        Vector3f point=scratch.get()[0];slot.vehicleTransform.transformPosition(local,point);
        // Keep camera-relative precision when translating back through large map coordinates.
        if(place==null) out.set((double)slot.x-point.x,(double)slot.y+point.z,
            slot.z+((double)point.y+BaseVehicle.centerOfMassMagic+slot.centerOfMassY)/RopeGeometry.STOREY);
        else {place.transformPosition(point);out.set((double)cx-point.x,(double)cy-point.z,cz+(double)point.y/RopeGeometry.STOREY);}
    }
    // Calibration belongs to the render thread. Each queued frame retains its own
    // reference, so retries/removal on the producer cannot mutate an older frame.
    private static final class StockCalibration {
        final Vector3f local=new Vector3f();boolean ready;
    }
    static final class StockFrame {
        final TextureDraw draw;final ModelSlotRenderData slot;
        final Vector3f hitch;final StockCalibration calibration;
        private Vector3d point;
        StockFrame(TextureDraw draw,ModelSlotRenderData slot,Vector3f hitch,StockCalibration calibration) {
            this.draw=draw;this.slot=slot;this.hitch=hitch;this.calibration=calibration;
        }
        Vector3d resolve() {
            if(point!=null) return point;
            // TextureDraw.run has joined/cleared its own future before our draw.
            // Never wait here, nor read a slot which the engine has already pooled.
            if(draw.future!=null || draw.drawer!=slot) return null;
            if(slot.renderToTexture) return null;
            if(!calibration.ready) {calibrate(slot,hitch,calibration.local);calibration.ready=true;}
            point=new Vector3d();placedAnchor(slot,calibration.local,null,0,0,0,point);
            return point;
        }
    }
    public static void captureQueuedVehicle(TextureDraw draw) {
        if(zombie.network.GameServer.server || vehicles.isEmpty() || !ready()
                || !(draw.drawer instanceof ModelSlotRenderData slot)
                || !(slot.object instanceof BaseVehicle vehicle)) return;
        VehicleAnchor[] anchors=vehicles.get(vehicle);if(anchors==null) return;
        try {
            for(var anchor:anchors) if(anchor!=null)
                stockFrames.put(anchor,new StockFrame(draw,slot,attachment(vehicle,anchor),anchor.stockCalibration));
        } catch(Throwable failure) {fail(failure);}
    }
    static StockFrame stockFrame(Snapshot row) {
        VehicleEnd end=vehicleEnds.get(row.id);return end==null?null:stockFrames.get(end.anchor);
    }
    public static void perspectiveVehicle(ModelSlotRenderData slot,Matrix4f place,float cx,float cy,float cz,
                                          DoubleBinaryOperator terrain) {
        if(vehicles.isEmpty() || !ready()) return;
        if(slot.renderToTexture || !(slot.object instanceof BaseVehicle vehicle)) return;
        VehicleAnchor[] anchors=vehicles.get(vehicle);if(anchors==null) return;
        try {for(var anchor:anchors) if(anchor!=null) {
            if(!anchor.calibrated) {
                calibrate(slot,attachment(vehicle,anchor),anchor.local);anchor.calibrated=true;
            }
            placedAnchor(slot,anchor.local,place,cx,cy,cz,anchor.view);
            // VehicleTilt has already placed the hitch on the relief. FreeLinks
            // uses EACH_VERTEX: its shader will lift it again. Remove just that
            // lift at the final (tilted/predicted) XY; retain vehicle tilt/motion.
            if(terrain!=null) anchor.view.z-=terrain.applyAsDouble(anchor.view.x,anchor.view.y)/RopeGeometry.STOREY;
            anchor.viewReady=true;
        }} catch(Throwable failure) {fail(failure);}
    }
    static boolean vehicleFirst(Snapshot row) {
        VehicleEnd end=vehicleEnds.get(row.id);return end!=null && end.first;
    }
    /** Writes only to caller-owned storage; queued source geometry is never changed. */
    static void pinInto(Snapshot row,Vector3d point,boolean first,double[] out) {
        double[] p=row.points;int end=first?0:p.length-3;
        double dx=point.x-p[end],dy=point.y-p[end+1],dz=point.z*3-p[end+2];
        // Lua constrains the settled curve before native hitch correction. A
        // downward correction must not undo that contact. The opposite endpoint
        // identifies the support storey (points use three metres per storey).
        double floor=Math.floor(row.points[(first?p.length-3:0)+2]/3)*3+.025*3;
        boolean binding=row.id.startsWith("binding:");
        for(int i=0;i<p.length/3;i++) {
            double weight=(double)i/(p.length/3-1);if(first) weight=1-weight;
            // A closed decorative knot moves rigidly with its vehicle anchor.
            if(binding) weight=1;
            out[3*i]=p[3*i]+dx*weight;out[3*i+1]=p[3*i+1]+dy*weight;out[3*i+2]=p[3*i+2]+dz*weight;
            if(!binding && i>0 && i<p.length/3-1) out[3*i+2]=Math.max(floor,out[3*i+2]);
        }
    }
    /** Borrowed coordinates for synchronous capture only; do not retain or mutate them.
     * The caller owns scratch, with capacity for at least row.points.length doubles. */
    public static double[] perspectivePoints(Snapshot row,double[] scratch) {
        VehicleEnd end=vehicleEnds.get(row.id);
        if(end==null) return row.points;
        if(!end.anchor.viewReady) {
            // Culling or a not-yet-ready vehicle model must not restore the
            // hitch from an older rope snapshot. Read the current attachment
            // once per vehicle/attachment/capture, shared by rope and knot.
            // This is physical world space: the relief shader adds its lift.
            Vector3f live=attachment(end.vehicle,end.anchor,end.anchor.live);
            if(!Float.isFinite(live.x)||!Float.isFinite(live.y)||!Float.isFinite(live.z))return null;
            end.anchor.view.set(live.x,live.y,live.z);
            end.anchor.viewReady=true;
        }
        pinInto(row,end.anchor.view,end.first,scratch);
        return scratch;
    }
    // Snapshots retain their own immutable-by-convention arrays across frame queues.
    public static List<Snapshot> snapshots() { return new ArrayList<>(links.values()); }
    public static void copySnapshots(List<Snapshot> out) {
        out.clear();
        // addAll(Collection) may allocate an intermediate array even with spare capacity.
        for(Snapshot row:links.values()) out.add(row);
    }
    public static boolean knot(Snapshot row) { return row.id.startsWith("binding:") && row.points.length==6; }
    public static Model model(Snapshot row) { return model(row.chain,knot(row)); }
    public static Model model(boolean chain) { return model(chain,false); }
    private static Model model(boolean chain,boolean knot) {
        int i=knot?2:chain?1:0;
        if(models[i]==null) models[i]=ModelManager.instance.loadStaticModel(knot?"CVPKnot":chain?"CVPChainSegment":"CVPRopeSegment",null,"basicEffect");
        Model model=models[i];
        if(model==null || !model.isReady() || model.mesh==null || !model.mesh.isReady() || model.effect==null) return null;
        ensureMeshTransform(model.mesh);
        stockUV(model.mesh.vb);
        return model;
    }
    private static final Field vertexFormat=Native.field(zombie.core.skinnedmodel.model.VertexBufferObject.class,"vertexFormat");
    static void stockUV(zombie.core.skinnedmodel.model.VertexBufferObject vb) {
        if(vb==null) return;
        try { stockUV((zombie.core.skinnedmodel.model.VertexBufferObject.VertexFormat)vertexFormat.get(vb)); }
        catch(IllegalAccessException e) {throw new IllegalStateException(e);}
    }
    static void stockUV(zombie.core.skinnedmodel.model.VertexBufferObject.VertexFormat format) {
        var type=zombie.core.skinnedmodel.model.VertexBufferObject.VertexType.TextureCoordArray;
        int uv=format.indexOf(type);if(uv==2) return;
        if(uv!=3) throw new IllegalStateException("Unexpected tether UV layout");
        // TXT loader inserts a tangent at slot 2; basicEffect_static expects UV there.
        // Swap descriptors only, keeping GPU byte offsets and stride intact.
        var a=format.getElement(2);var b=format.getElement(3);
        var oldType=a.type;int oldSize=a.byteSize,oldOffset=a.byteOffset;
        a.type=b.type;a.byteSize=b.byteSize;a.byteOffset=b.byteOffset;
        b.type=oldType;b.byteSize=oldSize;b.byteOffset=oldOffset;
    }
    // Text meshes have no imported transform. B42's object drawer nevertheless
    // multiplies it after drawing, even with attachment debugging disabled.
    static void ensureMeshTransform(zombie.core.skinnedmodel.model.ModelMesh mesh) {
        if(mesh.transform==null) mesh.transform=new Matrix4f();
    }
    public static Texture texture(boolean chain) {
        int i=chain?1:0;
        
        if(textures[i]==null) textures[i]=Texture.getSharedTexture(chain?"media/textures/WorldItems/Hook_Chain_Forged.png":"media/textures/WorldItems/Rope.png");
        return textures[i]!=null?textures[i]:Texture.getWhite();
    }
    public static float radius(boolean chain) { return chain?.027f:.009f; }
    public static void sceneSegment(Snapshot row,int index,float x,float y,float z,Matrix4f out) {
        sceneSegment(row,row.points,index,x,y,z,out);
    }
    public static void sceneSegment(Snapshot row,double[] p,int index,float x,float y,float z,Matrix4f out) {
        int i=index*3;
        Vector3f[] temp=scratch.get();
        Vector3f a=temp[0].set((float)(x-p[i]),(float)((p[i+2]/3-z)*RopeGeometry.STOREY),(float)(y-p[i+1]));
        Vector3f b=temp[1].set((float)(x-p[i+3]),(float)((p[i+5]/3-z)*RopeGeometry.STOREY),(float)(y-p[i+4]));
        RopeGeometry.segment(a,b,knot(row)?.03f:radius(row.chain),out);
    }
    static void objectSegment(Snapshot row,int index,float x,float y,float z,Matrix4f out) {
        sceneSegment(row,index,x,y,z,out);
        out.mulLocal(objectInverse);
    }
    static void cameraOrigin(Matrix4f view) {
        // Keep the same screen positions, but put the vehicle-origin correction
        // in the camera. Native renderModel calibrates targetDepth at camera (0,0,0):
        // leaving this in the mesh alone places ground-level vertices behind terrain.
        view.translate(0,-BaseVehicle.centerOfMassMagic,0);
    }
    static Matrix4f nativeObjectPlacement() { return new Matrix4f(objectPlacement); }
    public static IsoGridSquare square(IsoCell cell,Snapshot row,int index) {
        return square(cell,row.points,index);
    }
    public static IsoGridSquare square(IsoCell cell,double[] p,int index) {
        int i=index*3;
        return cell.getGridSquare((int)Math.floor((p[i]+p[i+3])*.5),(int)Math.floor((p[i+1]+p[i+4])*.5),
            (int)Math.floor((p[i+2]+p[i+5])/6));
    }
    public static boolean nearby(Snapshot row,float x,float y) {
        return nearby(row,row.points,x,y);
    }
    public static boolean nearby(Snapshot row,double[] p,float x,float y) {
        int length=row.points.length; // Scratch capacity may exceed the active geometry.
        double mx=(p[0]+p[length-3])*.5,my=(p[1]+p[length-2])*.5;
        return (mx-x)*(mx-x)+(my-y)*(my-y)<=96*96;
    }
    public static zombie.core.textures.ColorInfo visibleLight(IsoGridSquare square,int player) {
        // Streaming/lighting can lag behind square visibility for a frame.
        // Skip only that segment; incomplete lighting is not a renderer failure.
        return stockLight(square,player);
    }
    static zombie.core.textures.ColorInfo stockLight(IsoGridSquare square,int player) {
        // CanSee includes the player's facing cone. A world rope on explored,
        // unobstructed ground must not disappear segment-by-segment behind a driver.
        // Reuse cached LOS and native dimmed light; never reveal unseen/blocked tiles.
        return square!=null && (square.isCanSee(player) || square.isSeen(player) && square.isCouldSee(player))
            ?square.getLightInfo(player):null;
    }
    public static void stock(IsoCell cell) {
        if(zombie.network.GameServer.server || links.isEmpty() || perspective.getAsBoolean() || !ready()) return;
        var rows=captureLists.poll();if(rows==null)rows=new ArrayList<Snapshot>();
        try {
            int player=IsoCamera.frameState.playerIndex;
            copySnapshots(rows);
            for(Snapshot source:rows) {
                Snapshot row=source;
                if(!nearby(row,IsoCamera.frameState.camCharacterX,IsoCamera.frameState.camCharacterY)) continue;
                Model model=model(row);if(model==null) continue;
                VehicleEnd end=vehicleEnds.get(row.id);
                StockFrame frame=stockFrame(row);
                if(end!=null && frame==null) continue;
                Drawer drawer=pool.poll();if(drawer==null) drawer=new Drawer();
                boolean queued=false;
                try {
                    drawer.prepare(cell,row,model,texture(row.chain),player,frame);
                    drawer.first=vehicleFirst(row);
                    if(drawer.count>0) {
                        SpriteRenderer.instance.drawGeneric(drawer);queued=true;
                        captures++;segments+=drawer.count;
                    }
                } finally {if(!queued)drawer.postRender();}
            }
        } catch(Throwable failure) { fail(failure); }
        finally {rows.clear();captureLists.offer(rows);}
    }
    public static synchronized void fail(Throwable failure) {
        if(!error.isEmpty()) return;
        error=failure.toString();retryAt=System.nanoTime()+RETRY_NANOS;
        if(!error.equals(reportedError)) {
            reportedError=error;System.err.println("[CVP-FreeRopeScene] retry in 5 s: "+error);failure.printStackTrace();
        }
    }
    /** One native world camera per link, with pooled immutable frame matrices. */
    private static final class Drawer extends TextureDraw.GenericDrawer {
        Model model;Texture texture;boolean selected;
        final StockCamera camera=new StockCamera();
        final Matrix4f[] matrices=new Matrix4f[32];
        final float[] red=new float[32],green=new float[32],blue=new float[32];
        float depth;
        int count;
        final int[] indices=new int[32];
        // Render-thread scratch belongs to this drawer until postRender returns it.
        // Capacity covers every supported quality; only source.points.length is used.
        double[] pinnedPoints;
        Snapshot source;StockFrame frame;boolean first;
        Drawer() {}
        void prepare(IsoCell cell,Snapshot row,Model model,Texture texture,int player,StockFrame frame) throws Exception {
            source=row;this.frame=frame;
            double[] p=row.points;float x=(float)p[0],y=(float)p[1],z=(float)(p[2]/3);count=0;
            camera.x=x;camera.y=y;camera.z=z;
            this.model=model;this.texture=texture;selected=highlighted(row.id,player);
            depth=IsoDepthHelper.getSquareDepthData((int)Math.floor(IsoCamera.frameState.camCharacterX),
                (int)Math.floor(IsoCamera.frameState.camCharacterY),x,y,z).depthStart;
            IsoGridSquare previousSquare=null;
            zombie.core.textures.ColorInfo light=null;
            for(int i=0;i<row.keys.length;i++) {
                IsoGridSquare square=square(cell,row,i);
                // Consecutive segments share light only within this player's current preparation.
                if(square!=previousSquare) { previousSquare=square;light=stockLight(square,player); }
                if(light==null) continue;
                if(matrices[count]==null) matrices[count]=new Matrix4f();
                indices[count]=i;
                // Vehicle anchors resolve on the render thread from this queued frame.
                if(frame==null) objectSegment(row,i,x,y,z,matrices[count]);
                red[count]=light.r;green[count]=light.g;blue[count]=light.b;count++;
            }
        }
        @Override public void render() {
            boolean begun=false;
            GL11.glPushAttrib(GL11.GL_ALL_ATTRIB_BITS);GL11.glPushClientAttrib(-1);
            try {
                if(frame!=null) {
                    Vector3d point=frame.resolve();
                    // Missing/failed native command: omit this frame, never jump
                    // to unrelated raw coordinates or use another frame's anchor.
                    if(point==null) return;
                    if(pinnedPoints==null) pinnedPoints=new double[33*3];
                    pinInto(source,point,first,pinnedPoints);
                    for(int i=0;i<count;i++) {
                        sceneSegment(source,pinnedPoints,indices[i],camera.x,camera.y,camera.z,matrices[i]);
                        matrices[i].mulLocal(objectInverse);
                    }
                }
                camera.Begin();begun=true;
                StockRopeDraw.draw(model,texture,matrices,red,green,blue,count,depth,selected);
            } catch(Throwable failure) {fail(failure);}
            finally {
                try {if(begun) camera.End();}
                finally {
                    GL11.glPopClientAttrib();GL11.glPopAttrib();
                    Texture.lastTextureID=-1;SpriteRenderer.ringBuffer.restoreBoundTextures=true;SpriteRenderer.ringBuffer.restoreVbos=true;
                }
            }
        }
        @Override public void postRender() { count=0;source=null;frame=null;model=null;texture=null;pool.offer(this); }
    }
    static final class StockCamera implements IModelCamera {
        float x,y,z;
        @Override public void Begin() { Core.getInstance().DoPushIsoStuff(x,y,z,0,true);cameraOrigin(Core.getInstance().modelViewMatrixStack.peek()); }
        @Override public void End() { Core.getInstance().DoPopIsoStuff(); }
    }
    static final class Native {
        static Field field(Class<?> type,String name) {
            try {Field f=type.getDeclaredField(name);f.setAccessible(true);return f;}
            catch(ReflectiveOperationException e) {throw new ExceptionInInitializerError(e);}
        }
    }
}
