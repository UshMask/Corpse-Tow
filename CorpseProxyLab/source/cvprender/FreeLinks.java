package cvprender;

import cvpworld.FreeRopeScene;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.util.ArrayList;
import org.joml.Matrix4f;
import viewpoint.core.Frame;
import viewpoint.core.View;
import viewpoint.light.OwnedLight;
import viewpoint.render.ModelDraws;
import zombie.iso.IsoWorld;

/** Submit real meshes before ModelMotion.end, including unattached ground ropes. */
public final class FreeLinks {
    private static final Matrix4f transform=new Matrix4f();
    // Same synchronous capture ownership as transform. Viewpoint retains matrices,
    // copied by ModelDraws.add, not these temporary coordinates or this list.
    private static final double[] pinnedPoints=new double[33*3];
    private static final ArrayList<FreeRopeScene.Snapshot> rows=new ArrayList<>();
    private static final MethodHandle motion;
    static {
        try {
            var method=Class.forName("viewpoint.models.ModelMotion").getDeclaredMethod("follow",ModelDraws.class,int.class,Object.class,int.class);
            method.setAccessible(true);motion=MethodHandles.lookup().unreflect(method);
        } catch(ReflectiveOperationException e) {throw new ExceptionInInitializerError(e);}
    }
    private FreeLinks() {}
    public static void install() { FreeRopeScene.setPerspective(()->View.enabled); }
    static void follow(ModelDraws draws,int at,Object key) throws Throwable { motion.invokeExact(draws,at,key,0); }
    public static void capture(Frame frame,int player) {
        try {
            if(!View.enabled || FreeRopeScene.count()==0 || !FreeRopeScene.ready()) return;
            var cell=IsoWorld.instance.currentCell;if(cell==null) return;
            ModelDraws draws=frame.scene.models;
            FreeRopeScene.copySnapshots(rows);
            for(int rowIndex=0;rowIndex<rows.size();rowIndex++) {
                var row=rows.get(rowIndex);
                double[] points=FreeRopeScene.perspectivePoints(row,pinnedPoints);
                if(points==null) continue;
                if(!FreeRopeScene.nearby(row,points,frame.camX,frame.camY)) continue;
                var model=FreeRopeScene.model(row);if(model==null) continue;
                var texture=FreeRopeScene.texture(row.chain());
                boolean selected=FreeRopeScene.highlighted(row.id(),player);
                zombie.iso.IsoGridSquare previous=null;
                zombie.core.textures.ColorInfo light=null;
                int rgb=-1;float sky=0;
                for(int i=0;i<row.keys().length;i++) {
                    var square=FreeRopeScene.square(cell,points,i);
                    if(i==0 || square!=previous) {
                        light=FreeRopeScene.visibleLight(square,player);previous=square;
                        if(light!=null) {
                            rgb=OwnedLight.modelLightAt(square.x,square.y,square.z);
                            sky=OwnedLight.modelSky(square.x,square.y,square.z,square.isOutside()&&!square.haveRoof);
                        }
                    }
                    if(light==null) continue;
                    FreeRopeScene.sceneSegment(row,points,i,frame.camX,frame.camY,frame.camZ,transform);
                    int at=draws.add(model.mesh,null,texture,transform,-1,-1,0,ModelDraws.COLOUR|ModelDraws.SHADOW);
                    if(at<0) continue;
                    follow(draws,at,row.keys()[i]);
                    draws.material(at,1,selected?.85f:1,selected?.3f:1,1);
                    draws.light(at,rgb<0?light.r:(rgb&255)/255f,rgb<0?light.g:((rgb>>8)&255)/255f,
                        rgb<0?light.b:((rgb>>16)&255)/255f,
                        sky);
                    draws.bounds(at,transform,model.mesh.minXyz,model.mesh.maxXyz,1);
                }
            }
        } catch(Throwable failure) { FreeRopeScene.fail(failure); }
        finally {rows.clear();FreeRopeScene.endPerspective();}
    }
}
