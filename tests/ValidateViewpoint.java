import java.lang.reflect.*;
public class ValidateViewpoint {
 public static void main(String[] args) throws Exception {
  Class<?> bridge=Class.forName("cvprender.Bridge");
  Method init=bridge.getDeclaredMethod("init");init.setAccessible(true);init.invoke(null);
  Class<?> frame=Class.forName("viewpoint.core.Frame",false,bridge.getClassLoader());
  Class<?> body=Class.forName("zombie.iso.objects.IsoDeadBody",false,bridge.getClassLoader());
  Class.forName("viewpoint.models.Corpses").getDeclaredMethod("pick",frame);
  Class.forName("viewpoint.game.WorldText",false,bridge.getClassLoader()).getDeclaredMethod("snapshot",frame,Class.forName("zombie.iso.IsoCell",false,bridge.getClassLoader()),int.class);
  Class.forName("viewpoint.models.CorpseCapture",false,bridge.getClassLoader()).getDeclaredMethod("draw",frame,body,Class.forName("viewpoint.models.CorpsePose"),float.class,int.class,boolean.class);
  bridge.getMethod("clear").invoke(null);
  var unsafeField=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
  Object corpse=((sun.misc.Unsafe)unsafeField.get(null)).allocateInstance(body);
  var tracked=bridge.getDeclaredField("bodies");tracked.setAccessible(true);
  var registry=(java.util.Map<?,?>)tracked.get(null);
  bridge.getMethod("track",body).invoke(null,corpse);Object key=registry.get(corpse);
  for(int i=0;i<32;i++) bridge.getMethod("track",body).invoke(null,corpse);
  if(registry.size()!=1 || registry.get(corpse)!=key) throw new AssertionError("motion identity changed on repeated tracking");
  bridge.getMethod("untrack",body).invoke(null,corpse);
  bridge.getMethod("track",body).invoke(null,corpse);
  if(registry.get(corpse)==key) throw new AssertionError("new registration inherited old motion history");
  bridge.getMethod("clear").invoke(null);
  Class.forName("viewpoint.models.Models").getDeclaredMethod("snapshot",frame,int.class);
  var motion=Class.forName("viewpoint.models.ModelMotion");
  var firstDraws=new viewpoint.render.ModelDraws();var secondDraws=new viewpoint.render.ModelDraws();
  var free=Class.forName("cvprender.FreeLinks");var follow=free.getDeclaredMethod("follow",viewpoint.render.ModelDraws.class,int.class,Object.class);follow.setAccessible(true);
  Object segmentKey=new Object();
  motion.getMethod("begin",viewpoint.render.ModelDraws.class).invoke(null,firstDraws);
  int first=firstDraws.add(null,null,null,new org.joml.Matrix4f().translation(1,2,3),-1,-1,0,3);
  follow.invoke(null,firstDraws,first,segmentKey);
  motion.getMethod("end",viewpoint.render.ModelDraws.class).invoke(null,firstDraws);
  motion.getMethod("begin",viewpoint.render.ModelDraws.class).invoke(null,secondDraws);
  int second=secondDraws.add(null,null,null,new org.joml.Matrix4f().translation(4,5,6),-1,-1,0,3);
  follow.invoke(null,secondDraws,second,segmentKey);
  if((secondDraws.flags(second)&viewpoint.render.ModelDraws.MOTION)==0) throw new AssertionError("free rope lacks native motion history");
  System.out.println("PASS free rope uses installed Viewpoint model-motion history and snapshot phase");
  // Exercise the actual installed projection: false is a valid third-person result.
  Object snapshot=frame.getConstructor().newInstance();
  Object scene=frame.getField("scene").get(snapshot);
  Object matrix=scene.getClass().getField("projection").get(scene);
  matrix.getClass().getMethod("setPerspective",float.class,float.class,float.class,float.class)
    .invoke(matrix,1.0f,16.0f/9.0f,0.05f,1000.0f);
  Object shot=frame.getField("cameraShot").get(snapshot);
  shot.getClass().getField("on").setBoolean(shot,true);
  shot.getClass().getField("fovY").setFloat(shot,1.0f);
  shot.getClass().getField("distance").setFloat(shot,5.0f);
  shot.getClass().getField("limit").setFloat(shot,100.0f);
  Field sf=bridge.getDeclaredField("screen");sf.setAccessible(true);Object screen=sf.get(null);
  Field setField=bridge.getDeclaredField("set");setField.setAccessible(true);Method set=(Method)setField.get(null);
  Object mode=set.invoke(screen,snapshot,null,1920.0f,1080.0f);
  if(!Boolean.FALSE.equals(mode)) throw new AssertionError("Expected third-person false return");
  Method update=bridge.getDeclaredMethod("updateProjection",frame,Class.forName("viewpoint.input.FreeCam$Place"),float.class,float.class);update.setAccessible(true);
  update.invoke(null,snapshot,null,1920.0f,1080.0f);
  Field ready=bridge.getDeclaredField("screenReady");ready.setAccessible(true);
  if(!ready.getBoolean(null)) throw new AssertionError("Third-person projection suppressed");
  Field pixelField=bridge.getDeclaredField("pixel");pixelField.setAccessible(true);Method pixel=(Method)pixelField.get(null);
  float[] xy=new float[2];boolean projected=false;
  for(int x=-10;x<=10 && !projected;x++) for(int y=-10;y<=10 && !projected;y++) {
   if(Boolean.TRUE.equals(pixel.invoke(screen,(float)x,(float)y,0.0f,0.0f,xy))) {
    projected=Float.isFinite(xy[0]) && Float.isFinite(xy[1]) && xy[0]>=0 && xy[0]<=1920 && xy[1]>=0 && xy[1]<=1080;
   }
  }
  if(!projected) throw new AssertionError("No finite visible projected point");
  shot.getClass().getField("on").setBoolean(shot,false);
  mode=set.invoke(screen,snapshot,null,1920.0f,1080.0f);
  if(!Boolean.TRUE.equals(mode)) throw new AssertionError("Expected first-person true return");
  update.invoke(null,snapshot,null,1920.0f,1080.0f);
  if(!ready.getBoolean(null)) throw new AssertionError("First-person projection suppressed");
  if(!"0.0.5".equals(bridge.getMethod("version").invoke(null))) throw new AssertionError("Wrong adapter version");
  Class<?> vehicleCapture=Class.forName("viewpoint.models.VehicleCapture");
  var nativePlaced=vehicleCapture.getDeclaredMethod("placed",frame,zombie.core.skinnedmodel.model.ModelSlotRenderData.class,zombie.vehicles.BaseVehicle.class);
  nativePlaced.setAccessible(true);var placement=vehicleCapture.getDeclaredField("place");placement.setAccessible(true);
  var calibrate=cvpworld.FreeRopeScene.class.getDeclaredMethod("calibrate",zombie.core.skinnedmodel.model.ModelSlotRenderData.class,org.joml.Vector3f.class,org.joml.Vector3f.class);calibrate.setAccessible(true);
  var pin=cvpworld.FreeRopeScene.class.getDeclaredMethod("placedAnchor",zombie.core.skinnedmodel.model.ModelSlotRenderData.class,org.joml.Vector3f.class,org.joml.Matrix4f.class,float.class,float.class,float.class,org.joml.Vector3d.class);pin.setAccessible(true);
  var shotFrame=(viewpoint.core.Frame)snapshot;shotFrame.camX=6198;shotFrame.camY=5203;shotFrame.camZ=.2f;
  shotFrame.scene.relief=null;
  var slot=new zombie.core.skinnedmodel.model.ModelSlotRenderData();slot.x=6200;slot.y=5200;slot.centerOfMassY=-.42f;
  zombie.vehicles.BaseVehicle.centerOfMassMagic=.7f;
  for(float z:new float[]{.04f,.25f,.6f}) {
   var local=new org.joml.Vector3f();var hitch=new org.joml.Vector3f(6200,5202,z);
   slot.vehicleTransform.identity().rotateY(.3f);calibrate.invoke(null,slot,hitch,local);
   nativePlaced.invoke(null,shotFrame,slot,null);
   var actualPlace=(org.joml.Matrix4f)placement.get(null);var out=new org.joml.Vector3d();
   pin.invoke(null,slot,local,actualPlace,shotFrame.camX,shotFrame.camY,shotFrame.camZ,out);
   if(out.distance(hitch.x,hitch.y,hitch.z)>.0001) throw new AssertionError("installed Viewpoint moved hitch: "+out);
  }
  vehicleCapture.getDeclaredMethod("placed",frame,Class.forName("zombie.core.skinnedmodel.model.ModelSlotRenderData"),Class.forName("zombie.vehicles.BaseVehicle"));
  vehicleCapture.getDeclaredField("place");
  Class<?> animator=Class.forName("zombie.core.skinnedmodel.animation.AnimationPlayer");
  Constructor<?> animatorCtor=animator.getDeclaredConstructor();animatorCtor.setAccessible(true);
  Object nativeAnimator=animatorCtor.newInstance();
  Method renderAngle=bridge.getDeclaredMethod("renderedAngle",float.class);renderAngle.setAccessible(true);
  for(float heading:new float[]{0f,1.2f,-3.9195163f,6.1f}) {
   animator.getMethod("setAngle",float.class).invoke(nativeAnimator,heading);
   float expected=(Float)animator.getMethod("getRenderedAngle").invoke(nativeAnimator);
   float actual=(Float)renderAngle.invoke(null,heading);
   if(Math.abs(actual-expected)>0.000001f) throw new AssertionError("Corpse pose diverges from native rendered heading");
  }
  System.out.println("PASS moving corpse heading matches native AnimationPlayer rendered angle");
  System.out.println("PASS first-person projection remains ready; explicit adapter version");
  System.out.println("PASS native third-person false return retains usable projection and finite screen coordinates");
  System.out.println("PASS installed Viewpoint reflection bindings, patch signatures, adapter initialization and clear");
 }
}
