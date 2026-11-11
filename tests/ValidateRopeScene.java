package cvpworld;
import org.joml.Matrix4f;
import org.joml.Vector3f;
import zombie.core.skinnedmodel.model.ModelSlotRenderData;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;

public class ValidateRopeScene {
    private static void checkLoadedFaces(Object mesh, String file) throws Exception {
        var lines=Files.readAllLines(Path.of(file));
        int marker=lines.indexOf("# Number of Faces:");
        if(marker<0) throw new AssertionError("Missing face section: "+file);
        int count=Integer.parseInt(lines.get(marker+1).trim());
        if(count<=0) throw new AssertionError("Empty mesh: "+file);
        var expected=new ArrayList<Integer>();
        for(int i=0;i<count;i++) {
            String[] face=lines.get(marker+2+i).trim().split("\\s*,\\s*");
            if(face.length!=3) throw new AssertionError("Invalid triangle: "+file);
            for(String index:face) expected.add(Integer.parseInt(index));
        }
        var elements=mesh.getClass().getDeclaredField("elements");elements.setAccessible(true);
        if(!Arrays.equals((int[])elements.get(mesh),expected.stream().mapToInt(Integer::intValue).toArray()))
            throw new AssertionError("Native loader changed or truncated mesh triangles: "+file);
    }
    private static void near(Vector3f actual,Vector3f expected) {
        if(!actual.isFinite() || !expected.isFinite() || actual.distance(expected)>0.00002f) throw new AssertionError(actual+" != "+expected);
    }
    private static void segmentExtremes() {
        var random=new java.util.Random(6421);
        for(int i=0;i<2000;i++) {
            var a=new Vector3f(random.nextFloat()*20-10,random.nextFloat()*20-10,random.nextFloat()*20-10);
            var delta=switch(i%5) {
                case 0 -> new Vector3f();case 1 -> new Vector3f(0,5,0);case 2 -> new Vector3f(0,-5,0);
                case 3 -> new Vector3f(.00001f,-5,.00001f);
                default -> new Vector3f(random.nextFloat()*12-6,random.nextFloat()*12-6,random.nextFloat()*12-6);
            };
            var b=new Vector3f(a).add(delta);var matrix=new Matrix4f();float radius=i%2==0?.009f:.027f;
            RopeGeometry.segment(a,b,radius,matrix);
            if(!matrix.isFinite()) throw new AssertionError("nonfinite segment "+i);
            near(matrix.transformPosition(new Vector3f()),a);near(matrix.transformPosition(new Vector3f(0,1,0)),b);
            if(delta.length()>1e-6) {
                var side=matrix.transformDirection(new Vector3f(1,0,0));
                if(Math.abs(side.length()-radius)>.00001 || Math.abs(side.dot(delta.normalize()))>.00001)
                    throw new AssertionError("segment radius/orientation changed");
            }
        }
    }
    public static void main(String[] args) throws Exception {
        segmentExtremes();
        var slot=new ModelSlotRenderData();slot.x=6200.123f;slot.y=5280.456f;slot.z=0;slot.centerOfMassY=-0.42f;
        zombie.vehicles.BaseVehicle.centerOfMassMagic=0.7f;
        Vector3f camera=new Vector3f(6198,5283,0.2f);
        Matrix4f base=new Matrix4f().translation(-(slot.x-camera.x),(slot.z-camera.z)*RopeGeometry.STOREY+0.7f,-(slot.y-camera.y))
            .scale(-1,1,1).rotateY((float)Math.PI).translate(0,slot.centerOfMassY,0);
        for(int i=0;i<100;i++) {
            double x=6200+i*.002,y=5280-i*.02,z=.025;
            Vector3f iso=RopeGeometry.isoPoint(slot,x,y,z,new Vector3f());
            Vector3f scene=RopeGeometry.scenePoint(camera,x,y,z,new Vector3f());
            near(base.transformPosition(iso,new Vector3f()),scene);
            // A different render camera/vehicle prediction cannot move the free end:
            // inverse placement is consumed by the same snapshot placement.
            Matrix4f predicted=new Matrix4f().translation(.4f,0,-.2f).rotateY(i*.015f).mul(base);
            Vector3f local=new Matrix4f(predicted).invert().transformPosition(scene,new Vector3f());
            near(predicted.transformPosition(local),scene);
            Vector3f a=new Vector3f(0,.6f,0),b=new Vector3f((float)Math.sin(i),.025f,-4);
            Matrix4f segment=new Matrix4f();RopeGeometry.segment(a,b,.009f,segment);
            near(segment.transformPosition(new Vector3f(0,0,0)),a);
            near(segment.transformPosition(new Vector3f(0,1,0)),b);
        }
        zombie.core.skinnedmodel.model.ModelSlotRenderData.class.getDeclaredMethod("init",zombie.core.skinnedmodel.ModelManager.ModelSlot.class);
        var loader=zombie.core.skinnedmodel.model.ModelLoader.class.getDeclaredMethod("loadTxt",String.class,boolean.class,boolean.class,zombie.core.skinnedmodel.model.SkinningData.class);
        loader.setAccessible(true);
        Object mesh=loader.invoke(zombie.core.skinnedmodel.model.ModelLoader.instance,"CorpseProxyLab/42/media/models/CVPRopeSegment.txt",true,false,null);
        checkLoadedFaces(mesh,"CorpseProxyLab/42/media/models/CVPRopeSegment.txt");
        Object chain=loader.invoke(zombie.core.skinnedmodel.model.ModelLoader.instance,"CorpseProxyLab/42/media/models/CVPChainSegment.txt",true,false,null);
        checkLoadedFaces(chain,"CorpseProxyLab/42/media/models/CVPChainSegment.txt");
        System.out.println("PASS native scene coordinate basis, large-world precision, 100 camera/prediction transforms, pinned tube endpoints, patch binding");
    }
}
