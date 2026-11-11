package cvpworld;
import java.lang.reflect.*;
import java.util.*;
import zombie.core.skinnedmodel.model.*;
import zombie.core.skinnedmodel.shader.Shader;
import zombie.core.opengl.ShaderProgram;
import zombie.core.textures.*;


import java.util.List;
import org.joml.Matrix4f;
import org.joml.Vector3f;
import org.joml.Vector3d;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.vm.KahluaTable;
import zombie.Lua.LuaManager;
import zombie.core.Core;
import java.lang.classfile.*;
import java.lang.classfile.instruction.InvokeInstruction;
import java.lang.classfile.instruction.FieldInstruction;
import java.lang.constant.*;
import java.lang.invoke.MethodHandles;

/** Exercise frame ownership, native binding and both 3D coordinate systems without GL. */
public class ValidateFreeRopeScene {
    // Test-owned snapshot convenience; both branches exercise production buffer paths.
    static FreeRopeScene.Snapshot rendered(FreeRopeScene.Snapshot row,boolean perspective) {
        double[] points=new double[row.points().length];
        if(perspective) {
            points=FreeRopeScene.perspectivePoints(row,points);
            if(points==row.points())return row;
        } else {
            var frame=FreeRopeScene.stockFrame(row);var point=frame==null?null:frame.resolve();
            if(point==null)return row;
            FreeRopeScene.pinInto(row,point,FreeRopeScene.vehicleFirst(row),points);
        }
        return new FreeRopeScene.Snapshot(row.id(),points,row.chain(),row.keys());
    }
    interface ShaderProjection { Vector3f project(Matrix4f camera,Matrix4f transform,Vector3f vertex); }
    static ShaderProjection shaderProjection;
    interface DepthProjection {Vector3f project(Matrix4f camera,Matrix4f transform,Vector3f vertex,float target);}
    static DepthProjection depthProjection;
    static java.util.List<Vector3f> surfaceVertices=java.util.List.of(new Vector3f(),new Vector3f(0,1,0));
    static void nativeAttachment() throws Exception {
        var field=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");field.setAccessible(true);
        var type=zombie.vehicles.BaseVehicle.class;
        var vehicle=(zombie.vehicles.BaseVehicle)((sun.misc.Unsafe)field.get(null)).allocateInstance(type);
        var script=new zombie.scripting.objects.VehicleScript();var attachment=new zombie.scripting.objects.ModelAttachment("trailer");script.addAttachment(attachment);
        var scriptField=type.getDeclaredField("script");scriptField.setAccessible(true);scriptField.set(vehicle,script);
        var transform=new zombie.core.physics.Transform();transform.basis.identity();transform.origin.set(6200,0,5200);
        var physics=type.getDeclaredField("jniTransform");physics.setAccessible(true);physics.set(vehicle,transform);
        var slot=new zombie.core.skinnedmodel.model.ModelSlotRenderData();slot.object=vehicle;slot.x=6200;slot.y=5200;
        for(float height:new float[]{.04f,.6f,1.1f}) {
            FreeRopeScene.clear();attachment.getOffset().set(0,height,2);
            slot.vehicleTransform.identity().rotateY(.7f);
            FreeRopeScene.update("height",points(6200,5200,.025),false);
            FreeRopeScene.vehicle("height",vehicle,true);captureReady(slot);
            var frame=ValidateFreeRopeScene.rendered(FreeRopeScene.snapshots().getFirst(),false);
            near(point(frame,0),vehicle.getAttachmentWorldPos("trailer",new Vector3f()));
        }
        // Simultaneous front/rear anchors must never share calibration or frame data.
        FreeRopeScene.clear();
        var front=new zombie.scripting.objects.ModelAttachment("trailerfront");
        front.getOffset().set(0,.8f,-3);script.addAttachment(front);
        for(String id:new String[]{"rear","front","front-second"}) {
            FreeRopeScene.update(id,points(6200,5200,.025),false);
            FreeRopeScene.vehicle(id,vehicle,true,id.equals("rear")?"hitch":"front");
        }
        captureReady(slot);
        FreeRopeScene.perspectiveVehicle(slot,null,0,0,0,null);
        for(var source:FreeRopeScene.snapshots()) {
            var expectedPoint=vehicle.getAttachmentWorldPos(source.id().equals("rear")?"trailer":"trailerfront",new Vector3f());
            near(point(ValidateFreeRopeScene.rendered(source,false),0),expectedPoint);
            near(point(ValidateFreeRopeScene.rendered(source,true),0),expectedPoint);
        }
        var savedFront=FreeRopeScene.stockFrame(FreeRopeScene.snapshots().get(1));
        var savedPoint=new Vector3d(savedFront.resolve());
        FreeRopeScene.remove("front");FreeRopeScene.remove("front-second");
        FreeRopeScene.beginStock();captureReady(slot);
        near(point(ValidateFreeRopeScene.rendered(FreeRopeScene.snapshots().getFirst(),false),0),
            vehicle.getAttachmentWorldPos("trailer",new Vector3f()));
        if(!savedFront.resolve().equals(savedPoint)) throw new AssertionError("removed front mutated queued frame");
        // A deferred slot must finish before the scene reads any of its anchors.
        FreeRopeScene.clear();slot.vehicleTransform.identity();
        for(int i=0;i<32;i++) {
            FreeRopeScene.update("async-"+i,points(6200,5200,.025),false);
            FreeRopeScene.vehicle("async-"+i,vehicle,i%2==0);
        }
        captureReady(slot);
        var original=ValidateFreeRopeScene.rendered(FreeRopeScene.snapshots().getFirst(),false);
        var expected=point(original,0);
        var draw=new zombie.core.textures.TextureDraw();draw.drawer=slot;
        for(int frame=0;frame<20;frame++) {
            FreeRopeScene.beginStock();
            var task=new java.util.concurrent.FutureTask<Void>(()->{slot.x+=.125f;return null;});
            draw.future=task;PatchRopeSnapshot.exit(draw);
            var pending=FreeRopeScene.stockFrame(FreeRopeScene.snapshots().getFirst());
            if(task.isDone() || draw.future!=task || pending.resolve()!=null)
                throw new AssertionError("producer waited or read unfinished slot");
            // Execute the actual engine completion method without running GL.
            new Thread(task,"test-delayed-vehicle-slot").start();
            var complete=zombie.core.textures.TextureDraw.class.getDeclaredMethod("GetFutureResultThrow");
            complete.setAccessible(true);complete.invoke(draw);
            expected.x+=.125f;
            for(var source:FreeRopeScene.snapshots()) {
                var pinned=ValidateFreeRopeScene.rendered(source,false);
                int end=Integer.parseInt(source.id().substring(6))%2==0?0:2;
                near(point(pinned,end),expected);
            }
            var saved=new Vector3d(pending.resolve());
            FreeRopeScene.beginStock();
            if(FreeRopeScene.stockFrame(FreeRopeScene.snapshots().getFirst())!=null)
                throw new AssertionError("another camera/frame inherited anchor");
            slot.x+=10;draw.drawer=null; // Simulate pooling after that frame.
            if(!saved.equals(pending.resolve())) throw new AssertionError("queued snapshot changed after reuse");
            slot.x-=10;draw.drawer=slot;
        }
        FreeRopeScene.clear();
        draw.future=new java.util.concurrent.CompletableFuture<>();
        FreeRopeScene.captureQueuedVehicle(draw); // No towing: must never join this incomplete task.
    }
    static void captureReady(zombie.core.skinnedmodel.model.ModelSlotRenderData slot) {
        var draw=new zombie.core.textures.TextureDraw();draw.drawer=slot;
        FreeRopeScene.captureQueuedVehicle(draw);
    }
    static KahluaTable points(double x,double y,double z) {
        var out=LuaManager.platform.newTable();
        for(int i=0;i<3;i++) {
            var p=LuaManager.platform.newTable();p.rawset("x",x-i);p.rawset("y",y+i*.4);p.rawset("z",z*3);
            out.rawset(i+1,p);
        }
        return out;
    }
    static void near(Vector3f a,Vector3f b) { if(!a.isFinite() || !b.isFinite() || a.distance(b)>.0001f) throw new AssertionError(a+" != "+b); }
    static zombie.iso.IsoGridSquare[] lightSequence;
    public static zombie.iso.IsoGridSquare preparedSquare(zombie.iso.IsoCell cell,FreeRopeScene.Snapshot row,int index) {
        return lightSequence[index];
    }
    static void preparedLighting() throws Exception {
        var uf=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");uf.setAccessible(true);var unsafe=(sun.misc.Unsafe)uf.get(null);
        var a=(zombie.iso.IsoGridSquare)unsafe.allocateInstance(zombie.iso.IsoGridSquare.class);
        var b=(zombie.iso.IsoGridSquare)unsafe.allocateInstance(zombie.iso.IsoGridSquare.class);
        var type=zombie.iso.IsoGridSquare.class;var lf=type.getDeclaredField("lighting");lf.setAccessible(true);
        var cf=type.getDeclaredField("lightInfo");cf.setAccessible(true);
        int[] reads={0,0};boolean[] visible={true,true};var api=zombie.iso.IsoGridSquare.ILighting.class;
        var colours=new ColorInfo[]{new ColorInfo(.2f,.4f,.6f,1),new ColorInfo(.7f,.8f,.9f,1)};
        int n=0;for(var square:new zombie.iso.IsoGridSquare[]{a,b}) {
            final int id=n++;
            var light=(zombie.iso.IsoGridSquare.ILighting)Proxy.newProxyInstance(api.getClassLoader(),new Class<?>[]{api},
                (proxy,method,args)->switch(method.getName()) {
                    case "bCanSee" -> { reads[id]++;yield visible[id]; }
                    case "bSeen","bCouldSee" -> false;
                    default -> throw new AssertionError(method);
                });
            lf.set(square,new zombie.iso.IsoGridSquare.ILighting[]{light,light});
            cf.set(square,new ColorInfo[]{colours[id],new ColorInfo(.1f,.1f,.1f,1)});
        }
        FreeRopeScene.clear();FreeRopeScene.update("light-test",settled(1,2,0,true),false);
        var row=FreeRopeScene.snapshots().getFirst();
        lightSequence=new zombie.iso.IsoGridSquare[row.keys().length];Arrays.fill(lightSequence,a);
        lightSequence[0]=null;lightSequence[3]=b;lightSequence[4]=b;lightSequence[6]=null;
        var drawer=Class.forName("cvpworld.FreeRopeScene$Drawer");var ctor=drawer.getDeclaredConstructor();ctor.setAccessible(true);var instance=ctor.newInstance();
        var file=ClassFile.of().parse(FreeRopeScene.class.getResourceAsStream("FreeRopeScene$Drawer.class").readAllBytes());
        var method=file.methods().stream().filter(m->m.methodName().equalsString("prepare")).findFirst().orElseThrow();
        var signature=MethodTypeDesc.ofDescriptor("(Lcvpworld/FreeRopeScene$Drawer;"+method.methodType().stringValue().substring(1));
        byte[] bytes=ClassFile.of().build(ClassDesc.of("cvpworld.PreparedLightProbe"),builder->builder.withMethodBody("run",signature,
            ClassFile.ACC_PUBLIC|ClassFile.ACC_STATIC,code->{for(var element:method.code().orElseThrow()) {
                if(element instanceof InvokeInstruction call && call.owner().asInternalName().equals("cvpworld/FreeRopeScene") && call.name().equalsString("square"))
                    code.invokestatic(ClassDesc.of("cvpworld.ValidateFreeRopeScene"),"preparedSquare",MethodTypeDesc.ofDescriptor(call.type().stringValue()));
                else code.with(element);
            }}));
        var recorded=MethodHandles.privateLookupIn(drawer,MethodHandles.lookup()).defineHiddenClass(bytes,true,MethodHandles.Lookup.ClassOption.NESTMATE).lookupClass();
        var prepare=recorded.getDeclaredMethods()[0];prepare.setAccessible(true);
        var count=drawer.getDeclaredField("count");count.setAccessible(true);var red=drawer.getDeclaredField("red");red.setAccessible(true);
        for(int pass=0;pass<4;pass++) {
            Arrays.fill(reads,0);visible[1]=pass!=1;int player=pass==2?1:0;
            colours[0].r=.2f+pass*.1f;
            prepare.invoke(null,instance,null,row,null,null,player,null);
            int drawn=0,runsA=0,runsB=0;zombie.iso.IsoGridSquare previous=null;
            for(var square:lightSequence) {
                if(square!=previous && square!=null) { if(square==a) runsA++;else runsB++; }previous=square;
                if(square==null || square==b && !visible[1]) continue;
                float expected=player==1?.1f:(square==a?colours[0].r:colours[1].r);
                if(((float[])red.get(instance))[drawn++]!=expected) throw new AssertionError("stale/per-segment light mismatch");
            }
            if(count.getInt(instance)!=drawn || reads[0]!=runsA || reads[1]!=runsB)
                throw new AssertionError("light not shared per consecutive square or visibility lost");
        }
        FreeRopeScene.clear();
        System.out.println("PASS prepared lighting: consecutive cells, null/hidden cells, return to cell, next frame/player and unchanged colours");
    }
    static void lighting() throws Exception {
        var f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);
        var square=(zombie.iso.IsoGridSquare)((sun.misc.Unsafe)f.get(null)).allocateInstance(zombie.iso.IsoGridSquare.class);
        boolean[] visible={true},seen={false},couldSee={false};
        var api=zombie.iso.IsoGridSquare.ILighting.class;
        var lighting=(zombie.iso.IsoGridSquare.ILighting)java.lang.reflect.Proxy.newProxyInstance(api.getClassLoader(),new Class<?>[]{api},
            (proxy,method,args)->{return switch(method.getName()) {
                case "bCanSee" -> visible[0];case "bSeen" -> seen[0];case "bCouldSee" -> couldSee[0];
                default -> throw new AssertionError(method);
            };});
        var field=zombie.iso.IsoGridSquare.class.getDeclaredField("lighting");field.setAccessible(true);field.set(square,new zombie.iso.IsoGridSquare.ILighting[]{lighting});
        var lights=new zombie.core.textures.ColorInfo[1];field=zombie.iso.IsoGridSquare.class.getDeclaredField("lightInfo");field.setAccessible(true);field.set(square,lights);
        if(FreeRopeScene.visibleLight(null,0)!=null || FreeRopeScene.visibleLight(square,0)!=null) throw new AssertionError("unloaded light accepted");
        if(FreeRopeScene.stockLight(null,0)!=null || FreeRopeScene.stockLight(square,0)!=null) throw new AssertionError("unloaded stock light accepted");
        lights[0]=new zombie.core.textures.ColorInfo(.2f,.4f,.6f,1);
        if(FreeRopeScene.visibleLight(square,0)!=lights[0]) throw new AssertionError("lighting did not recover next frame");
        visible[0]=false;
        if(FreeRopeScene.visibleLight(square,0)!=null) throw new AssertionError("hidden square drawn");
        for(boolean explored:new boolean[]{false,true}) for(boolean clear:new boolean[]{false,true}) {
            seen[0]=explored;couldSee[0]=clear;
            if((FreeRopeScene.visibleLight(square,0)!=null)!=(explored && clear)) throw new AssertionError("Viewpoint revealed blocked or unexplored ground");
            if((FreeRopeScene.stockLight(square,0)!=null)!=(explored && clear))
                throw new AssertionError("rear rope visibility must retain explored LOS, not reveal blocked/unseen ground");
        }
        for(int frame=0;frame<8;frame++) {
            visible[0]=(frame%2)==0;
            if(FreeRopeScene.stockLight(square,0)!=lights[0]) throw new AssertionError("turning driver clipped rope");
            if(FreeRopeScene.visibleLight(square,0)!=lights[0]) throw new AssertionError("Viewpoint turning driver clipped rope");
        }
        lights[0]=null;
        if(FreeRopeScene.stockLight(square,0)!=null) throw new AssertionError("missing rear light accepted");
        if(!FreeRopeScene.error().isEmpty()) throw new AssertionError("missing light disabled scene");
    }
    static KahluaTable settled(double x,double y,int level,boolean first) {
        var out=LuaManager.platform.newTable();
        for(int i=0;i<17;i++) {
            var p=LuaManager.platform.newTable();p.rawset("x",x-i*.12);p.rawset("y",y+i*.04);
            p.rawset("z",level*3+(i==(first?0:16)?.75:.075));out.rawset(i+1,p);
        }
        return out;
    }
    static void textMeshUV() throws Exception {
        var loader=zombie.core.skinnedmodel.model.ModelLoader.class;
        var load=loader.getDeclaredMethod("loadTxt",String.class,boolean.class,boolean.class,zombie.core.skinnedmodel.model.SkinningData.class);
        load.setAccessible(true);
        for(String name:new String[]{"CVPRopeSegment","CVPChainSegment","CVPKnot"}) {
            Object mesh=load.invoke(zombie.core.skinnedmodel.model.ModelLoader.instance,
                "CorpseProxyLab/42/media/models/"+name+".txt",true,false,null);
            var field=mesh.getClass().getDeclaredField("vertices");field.setAccessible(true);
            var vertices=(zombie.core.skinnedmodel.model.VertexBufferObject.VertexArray)field.get(mesh);
            var format=vertices.format;int stride=format.getStride();
            float u=vertices.getElementFloat(0,3,0),v=vertices.getElementFloat(0,3,1);
            FreeRopeScene.stockUV(format);FreeRopeScene.stockUV(format);
            if(format.indexOf(zombie.core.skinnedmodel.model.VertexBufferObject.VertexType.TextureCoordArray)!=2 ||
                format.getStride()!=stride || vertices.getElementFloat(0,2,0)!=u || vertices.getElementFloat(0,2,1)!=v)
                throw new AssertionError("stock shader UV mismatch: "+name);
        }
    }
    static FreeRopeScene.Snapshot pinned(FreeRopeScene.Snapshot row,Vector3d point,boolean first) {
        double[] points=new double[row.points().length];
        FreeRopeScene.pinInto(row,point,first,points);
        return new FreeRopeScene.Snapshot(row.id(),points,row.chain(),row.keys());
    }
    static void rigidKnot() {
        double[] p={1,2,.6, 1.03,2.03,.6, 1,2,.6};
        var row=new FreeRopeScene.Snapshot("binding:test:a",p,false,new Object[2]);
        var moved=pinned(row,new Vector3d(2,3,.4),true);
        for(int i=0;i<3;i++) {
            if(Math.abs(moved.points()[i*3]-p[i*3]-1)>1e-8 ||
               Math.abs(moved.points()[i*3+1]-p[i*3+1]-1)>1e-8 ||
               Math.abs(moved.points()[i*3+2]-p[i*3+2]-.6)>1e-8)
                throw new AssertionError("vehicle knot stretched");
        }
        if(p[0]!=1) throw new AssertionError("source knot mutated");
    }
    static void settledFloor() {
        for(boolean chain:new boolean[]{false,true}) for(boolean first:new boolean[]{false,true}) for(int level:new int[]{0,1,7}) {
            FreeRopeScene.clear();FreeRopeScene.update("settled",settled(6200,5200,level,first),chain);
            var source=FreeRopeScene.snapshots().getFirst();var before=source.points().clone();int end=first?0:16;
            var hitch=new Vector3d(source.points()[end*3]+.1,source.points()[end*3+1]-.2,level+.04);
            var row=pinned(source,hitch,first);
            near(point(row,end),new Vector3f((float)hitch.x,(float)hitch.y,(float)hitch.z));near(point(row,16-end),point(source,16-end));
            for(int i=1;i<16;i++) if(row.points()[i*3+2]<level*3+.075-1e-8)
                throw new AssertionError("pin buried settled node "+i+": "+row.points()[i*3+2]);
            if(!java.util.Arrays.equals(before,source.points()) || row.keys()!=source.keys()) throw new AssertionError("pin mutated source/motion keys");
        }
        FreeRopeScene.clear();
    }
    static Vector3f point(FreeRopeScene.Snapshot row,int index) {
        int i=index*3;return new Vector3f((float)row.points()[i],(float)row.points()[i+1],(float)(row.points()[i+2]/3));
    }
    static void nativeCamera(FreeRopeScene.Snapshot row) throws Exception {
        // Verify the reference against DrawVehicle itself: its only matrix
        // translation reads centerOfMassY, not centerOfMassMagic + centerOfMassY.
        var model=ClassFile.of().parse(zombie.core.skinnedmodel.model.Model.class.getResourceAsStream("Model.class").readAllBytes());
        var draw=model.methods().stream().filter(m->m.methodName().equalsString("DrawVehicle")).findFirst().orElseThrow();
        boolean center=false;int translations=0;
        for(var e:draw.code().orElseThrow()) {
            if(e instanceof FieldInstruction f) {
                if(f.name().equalsString("centerOfMassY")) center=true;
                if(f.name().equalsString("centerOfMassMagic")) throw new AssertionError("native vehicle offset contract changed");
            }
            if(e instanceof InvokeInstruction call && call.owner().asInternalName().equals("org/joml/Matrix4f") && call.name().equalsString("translate")) translations++;
        }
        if(!center || translations!=1) throw new AssertionError("native DrawVehicle placement changed; review oracle");
        // Run the installed engine's actual matrix instructions without its final
        // GL depth-range call. This oracle is independent of our placement matrix.
        var engine=ClassFile.of().parse(Core.class.getResourceAsStream("Core.class").readAllBytes());
        var push=engine.methods().stream().filter(m->m.methodName().equalsString("DoPushIsoStuff")).findFirst().orElseThrow();
        byte[] bytes=ClassFile.of().build(ClassDesc.of("cvpworld.NativeIsoOracle"),builder->
            builder.withMethodBody("push",MethodTypeDesc.ofDescriptor("(Lzombie/core/Core;FFFFZ)V"),ClassFile.ACC_PUBLIC|ClassFile.ACC_STATIC,code->{
                for(var e:push.code().orElseThrow()) {
                    if(e instanceof InvokeInstruction call && call.owner().asInternalName().equals("org/lwjgl/opengl/GL11")) {
                        if(!call.name().equalsString("glDepthRange") || !call.type().equalsString("(DD)V")) throw new AssertionError("unexpected GL call");
                        code.pop2().pop2();
                    } else code.with(e);
                }
            }));
        var oracle=MethodHandles.lookup().defineClass(bytes).getMethod("push",Core.class,float.class,float.class,float.class,float.class,boolean.class);
        Core core=Core.getInstance();core.floatParamMap.put(0,6198f);core.floatParamMap.put(1,5203f);core.floatParamMap.put(2,.2f);
        var state=zombie.core.SpriteRenderer.instance.getRenderingState();state.playerIndex=0;
        var camera=state.playerCamera[0];camera.offscreenWidth=1920;camera.offscreenHeight=1080;
        var offX=camera.getClass().getDeclaredField("tOffX");offX.setAccessible(true);
        var offY=camera.getClass().getDeclaredField("tOffY");offY.setAccessible(true);
        var slot=new zombie.core.skinnedmodel.model.ModelSlotRenderData();slot.x=6200;slot.y=5200;slot.z=0;slot.centerOfMassY=-.42f;
        zombie.vehicles.BaseVehicle.centerOfMassMagic=.7f;
        Class<?> oldCameraClass=Class.forName("zombie.core.skinnedmodel.model.IsoObjectModelDrawer$WorldModelCamera");
        var constructor=oldCameraClass.getDeclaredConstructor();constructor.setAccessible(true);
        var oldCamera=(zombie.core.opengl.IModelCamera)constructor.newInstance();
        var oldX=oldCameraClass.getDeclaredField("x");oldX.setAccessible(true);
        var oldY=oldCameraClass.getDeclaredField("y");oldY.setAccessible(true);
        var oldZ=oldCameraClass.getDeclaredField("z");oldZ.setAccessible(true);
        boolean reproduced=false,buriedOld=false;
        var tileScaleField=Core.class.getField("tileScale");
        boolean fixedTileScale=Modifier.isFinal(tileScaleField.getModifiers());
        int[] tileScales=fixedTileScale ? new int[]{tileScaleField.getInt(null)} : new int[]{1,2};
        for(int tile:tileScales) for(float pan:new float[]{0,32,-64}) {
            if(!fixedTileScale) tileScaleField.setInt(null,tile);
            offX.setFloat(camera,pan);offY.setFloat(camera,pan/2);
            camera.rightClickX=pan/3;camera.rightClickY=-pan/4;camera.deferedX=.1f;camera.deferedY=-.2f;
            oracle.invoke(null,core,slot.x,slot.y,slot.z,0f,true);
            var legacy=new Matrix4f(core.modelViewMatrixStack.peek()).translate(0,slot.centerOfMassY,0);
            var legacyProjection=new Matrix4f(core.projectionMatrixStack.peek());
            core.modelViewMatrixStack.pop();core.projectionMatrixStack.pop();
            float x=(float)row.points()[0],y=(float)row.points()[1],z=(float)(row.points()[2]/3);
            oracle.invoke(null,core,x,y,z,0f,true);
            var actual=new Matrix4f(core.modelViewMatrixStack.peek());
            FreeRopeScene.cameraOrigin(actual);
            var actualProjection=new Matrix4f(core.projectionMatrixStack.peek());
            core.modelViewMatrixStack.pop();core.projectionMatrixStack.pop();
            oldX.setFloat(oldCamera,x);oldY.setFloat(oldCamera,y);oldZ.setFloat(oldCamera,z);
            oldCamera.Begin();var oldView=new Matrix4f(core.modelViewMatrixStack.peek());oldCamera.End();
            var oldInverse=new Matrix4f().scale(-1.5f,1.5f,1.5f).rotateY((float)Math.PI).translate(0,-.48f,0).invert();
            for(int i=0;i<row.keys().length;i++) {
                Matrix4f segment=new Matrix4f();FreeRopeScene.objectSegment(row,i,x,y,z,segment);
                for(int end=0;end<2;end++) {
                    int at=(i+end)*3;
                    Vector3f expected=RopeGeometry.isoPoint(slot,row.points()[at],row.points()[at+1],row.points()[at+2]/3,new Vector3f());
                    if(shaderProjection!=null) near(shaderProjection.project(new Matrix4f(actualProjection).mul(actual),segment,new Vector3f(0,end,0)),
                        shaderProjection.project(new Matrix4f(legacyProjection).mul(legacy),new Matrix4f(),new Vector3f(expected)));
                    if(depthProjection!=null) {
                        var vp=new Matrix4f(actualProjection).mul(actual);
                        float origin=vp.transformPosition(new Vector3f()).z;
                        float base=zombie.iso.IsoDepthHelper.getSquareDepthData(6198,5203,x,y,z).depthStart;
                        float target=base-(origin+1)/2+.5f;
                        float result=(depthProjection.project(vp,segment,new Vector3f(0,end,0),target).z+1)/2;
                        float ground=zombie.iso.IsoDepthHelper.getSquareDepthData(6198,5203,(float)row.points()[at],(float)row.points()[at+1],0).depthStart;
                        if(result>=ground) throw new AssertionError("iso rope occluded by ground: "+result+" >= "+ground+" tile="+tile);
                        float oldOrigin=vp.transformPosition(new Vector3f(0,zombie.vehicles.BaseVehicle.centerOfMassMagic,0)).z;
                        float oldTarget=base-(oldOrigin+1)/2+.5f;
                        buriedOld|=(depthProjection.project(vp,segment,new Vector3f(0,end,0),oldTarget).z+1)/2>=ground;
                        if(end==0) {
                            var scene=new Matrix4f();FreeRopeScene.sceneSegment(row,i,x,y,z,scene);
                            for(var vertex:surfaceVertices) {
                                var world=scene.transformPosition(vertex,new Vector3f());
                                float floor=zombie.iso.IsoDepthHelper.getSquareDepthData(6198,5203,x-world.x,y-world.z,0).depthStart;
                                float depth=(depthProjection.project(vp,segment,vertex,target).z+1)/2;
                                if(depth>=floor) throw new AssertionError("iso mesh underside behind terrain: "+depth+" >= "+floor);
                            }
                        }
                    }
                    legacy.transformPosition(expected);
                    near(actual.transformPosition(segment.transformPosition(new Vector3f(0,end,0))),expected);
                    var oldSegment=new Matrix4f();FreeRopeScene.sceneSegment(row,i,x,y,z,oldSegment);oldSegment.mulLocal(oldInverse);
                    if(oldView.transformPosition(oldSegment.transformPosition(new Vector3f(0,end,0))).distance(expected)>.0001f) reproduced=true;
                }
            }
        }
        if(!reproduced) throw new AssertionError("old object camera pan regression was not reproduced");
        if(depthProjection!=null && !buriedOld) throw new AssertionError("old depth defect was not reproduced");
        offX.setFloat(camera,0);offY.setFloat(camera,0);
    }
    static void vehicleFrames(FreeRopeScene.Snapshot row) {
        var slot=new zombie.core.skinnedmodel.model.ModelSlotRenderData();
        slot.x=6200;slot.y=5200;slot.z=0;slot.centerOfMassY=-.42f;
        zombie.vehicles.BaseVehicle.centerOfMassMagic=.7f;
        Vector3f camera=new Vector3f(6198,5203,.2f),hitch=new Vector3f(6200,5202,.25f),local=new Vector3f();
        slot.vehicleTransform.identity().rotateY(.2f);
        FreeRopeScene.calibrate(slot,hitch,local);
        Vector3d rendered=new Vector3d();
        FreeRopeScene.placedAnchor(slot,local,null,0,0,0,rendered);near(new Vector3f((float)rendered.x,(float)rendered.y,(float)rendered.z),hitch);
        Matrix4f base=new Matrix4f().translation(camera.x-slot.x,(slot.z-camera.z)*RopeGeometry.STOREY+.7f,camera.y-slot.y)
            .scale(-1,1,1).rotateY((float)Math.PI).translate(0,slot.centerOfMassY,0);
        for(int i=0;i<100;i++) {
            slot.vehicleTransform.identity().rotateY(i*.015f);
            Matrix4f predicted=new Matrix4f().translation(.4f,.1f,-.2f).rotateX(i*.002f).mul(base);
            FreeRopeScene.placedAnchor(slot,local,predicted,camera.x,camera.y,camera.z,rendered);
            Vector3f expected=slot.vehicleTransform.transformPosition(local,new Vector3f());predicted.transformPosition(expected);
            near(new Vector3f((float)(camera.x-rendered.x),(float)((rendered.z-camera.z)*RopeGeometry.STOREY),(float)(camera.y-rendered.y)),expected);
            for(boolean first:new boolean[]{false,true}) {
                var pinned=pinned(row,rendered,first);int last=row.points().length/3-1;
                near(point(pinned,first?0:last),new Vector3f((float)rendered.x,(float)rendered.y,(float)rendered.z));
                near(point(pinned,first?last:0),point(row,first?last:0));
                if(pinned.keys()!=row.keys() || pinned.points()==row.points()) throw new AssertionError("pin changed frame ownership");
            }
        }
    }
    static void fogOrder() throws Exception {
        // Validate the installed engine contract, not a mock of its render sequence.
        var patch=PatchFreeRopeFog.class.getAnnotation(me.zed_0xff.zombie_buddy.Patch.class);
        var type=Class.forName(patch.className());
        type.getDeclaredMethod(patch.methodName(),int.class);
        if(!PatchFreeRopeFog.class.getDeclaredMethod("enter",type)
                .isAnnotationPresent(me.zed_0xff.zombie_buddy.Patch.OnEnter.class))
            throw new AssertionError("rope submission must precede fog's early returns");
        var model=java.lang.classfile.ClassFile.of().parse(type.getResourceAsStream("FBORenderCell.class").readAllBytes());
        boolean found=false;
        for(var method:model.methods()) if(method.code().isPresent()) {
            var calls=new java.util.ArrayList<String>();
            for(var instruction:method.code().get())
                if(instruction instanceof java.lang.classfile.instruction.InvokeInstruction call)
                    calls.add(call.name().stringValue());
            int fog=calls.indexOf("renderFog");
            if(fog>=0) {
                if(calls.indexOf("renderTranslucentObjects")<0 || calls.indexOf("renderTranslucentObjects")>=fog
                        || calls.lastIndexOf("renderFog")!=fog)
                    throw new AssertionError("engine world/fog order changed");
                found=true;
            }
        }
        if(!found) throw new AssertionError("engine no longer calls fog pass");
        FreeRopeScene.update("phase",points(0,0,0),false);
        int[] submissions={0};
        FreeRopeScene.setPerspective(()->{submissions[0]++;return true;});
        boolean previous=zombie.core.PerformanceSettings.fboRenderChunk;
        try {
            zombie.core.PerformanceSettings.fboRenderChunk=true;
            PatchFreeRopeFog.enter(zombie.iso.fboRenderChunk.FBORenderCell.instance);
            PatchFreeRopeScene.exit(null);
            if(submissions[0]!=1) throw new AssertionError("FBO missing or double submission");
            zombie.core.PerformanceSettings.fboRenderChunk=false;
            PatchFreeRopeScene.exit(null);
            if(submissions[0]!=2) throw new AssertionError("legacy fallback lost");
        } finally {
            zombie.core.PerformanceSettings.fboRenderChunk=previous;
            FreeRopeScene.setPerspective(()->false);FreeRopeScene.clear();
        }
    }
    public static void main(String[] args) throws Exception {
        fogOrder();
        LuaManager.platform=new J2SEPlatform();
        nativeAttachment();
        lighting();
        preparedLighting();
        settledFloor();rigidKnot();textMeshUV();
        ValidateStockRopeDraw.run();
        var mesh=new zombie.core.skinnedmodel.model.ModelMesh(new zombie.asset.AssetPath("cvp-test"),
            zombie.core.skinnedmodel.model.MeshAssetManager.instance,
            new zombie.core.skinnedmodel.model.ModelMesh.MeshAssetParams());
        mesh.transform=null;
        FreeRopeScene.ensureMeshTransform(mesh);
        if(!new Matrix4f().mul(mesh.transform).equals(new Matrix4f())) throw new AssertionError("missing mesh identity");
        var imported=new Matrix4f().translation(1,2,3);mesh.transform=imported;
        FreeRopeScene.ensureMeshTransform(mesh);
        if(mesh.transform!=imported) throw new AssertionError("imported transform overwritten");
        FreeRopeScene.clear();var input=points(6200,5200,.025);
        FreeRopeScene.update("ground-ground",input,false);
        List<FreeRopeScene.Snapshot> frame=FreeRopeScene.snapshots();var row=frame.getFirst();
        FreeRopeScene.update("ground-ground",points(6200,5200,.025),false);
        if(FreeRopeScene.snapshots().getFirst()!=row) throw new AssertionError("unchanged upload replaced snapshot");
        var bad=points(6210,5200,.025);
        ((KahluaTable)bad.rawget(bad.len())).rawset("z",Double.NaN);
        try {FreeRopeScene.update("ground-ground",bad,false);throw new AssertionError("accepted late NaN");}
        catch(IllegalArgumentException expected) {}
        if(FreeRopeScene.snapshots().getFirst()!=row || row.points()[0]!=6200)
            throw new AssertionError("failed update mutated published snapshot");
        var tail=points(6200,5200,.025);
        ((KahluaTable)tail.rawget(tail.len())).rawset("z",.9);
        FreeRopeScene.update("ground-ground",tail,false);
        var changed=FreeRopeScene.snapshots().getFirst();
        if(changed.points()[0]!=row.points()[0] || changed.points()[changed.points().length-1]!=.9
            || changed.keys()!=row.keys() || changed.points()==row.points()) throw new AssertionError("late change lost prefix or ownership");
        FreeRopeScene.update("ground-ground",tail,true);
        if(!FreeRopeScene.snapshots().getFirst().chain() || FreeRopeScene.snapshots().getFirst().keys()==changed.keys())
            throw new AssertionError("material change retained old motion keys");
        FreeRopeScene.update("ground-ground",points(6200,5200,.025),false);
        row=FreeRopeScene.snapshots().getFirst();
        ((KahluaTable)input.rawget(1)).rawset("x",0.0);
        if(frame.getFirst().points()[0]!=6200) throw new AssertionError("caller mutated frame points");
        FreeRopeScene.update("ground-ground",points(6210,5200,.025),false);
        var newer=FreeRopeScene.snapshots().getFirst();
        if(row.points()[0]!=6200 || newer.points()[0]!=6210 || row.keys()[0]!=newer.keys()[0])
            throw new AssertionError("frame ownership or stable motion key lost");
        vehicleFrames(row);
        nativeCamera(row);
        FreeRopeScene.fail(new IllegalStateException("injected transient renderer failure"));
        if(FreeRopeScene.ready()) throw new AssertionError("failed renderer retried every frame");
        if(!FreeRopeScene.ready(System.nanoTime()+6_000_000_000L) || !FreeRopeScene.error().isEmpty()) throw new AssertionError("renderer did not recover");
        if(FreeRopeScene.snapshots().getFirst()!=newer) throw new AssertionError("recovery changed rope snapshot or keys");
        FreeRopeScene.fail(new IllegalStateException("injected transient renderer failure"));
        if(FreeRopeScene.ready()) throw new AssertionError("repeated failure lacks cooldown");
        FreeRopeScene.clear();if(!FreeRopeScene.ready()) throw new AssertionError("world reset retained failure");
        for(boolean chain:new boolean[]{false,true}) for(float height:new float[]{.025f,1.025f,7.025f}) {
            FreeRopeScene.update("ground-ground",points(6200,5200,height),chain);row=FreeRopeScene.snapshots().getFirst();
            for(int i=0;i<2;i++) {
                Matrix4f scene=new Matrix4f(),stock=new Matrix4f();
                FreeRopeScene.sceneSegment(row,i,6199,5203,1.4f,scene);
                FreeRopeScene.objectSegment(row,i,6199,5203,1.4f,stock);
                stock.mulLocal(FreeRopeScene.nativeObjectPlacement());
                for(Vector3f local:new Vector3f[]{new Vector3f(),new Vector3f(0,1,0),new Vector3f(1,0,0)})
                    near(scene.transformPosition(local,new Vector3f()),stock.transformPosition(local,new Vector3f()));
                int a=i*3,b=(i+1)*3;
                near(scene.transformPosition(new Vector3f()),new Vector3f((float)(6199-row.points()[a]),
                    (float)((row.points()[a+2]/3-1.4f)*RopeGeometry.STOREY),(float)(5203-row.points()[a+1])));
                near(scene.transformPosition(new Vector3f(0,1,0)),new Vector3f((float)(6199-row.points()[b]),
                    (float)((row.points()[b+2]/3-1.4f)*RopeGeometry.STOREY),(float)(5203-row.points()[b+1])));
            }
        }
        int count=FreeRopeScene.count();
        var invalid=points(0,0,0);((KahluaTable)invalid.rawget(2)).rawset("x",Double.NaN);
        try {FreeRopeScene.update("invalid",invalid,false);throw new AssertionError("accepted NaN");}
        catch(IllegalArgumentException expected) {}
        if(FreeRopeScene.count()!=count) throw new AssertionError("invalid submission mutated scene");
        FreeRopeScene.remove("ground-ground");if(FreeRopeScene.count()!=0 || frame.getFirst().points()[0]!=6200)
            throw new AssertionError("cleanup invalidated queued snapshot");
        System.out.println("PASS free scene: immutable queued frames, stable motion keys, stock/Viewpoint matrices, cleanup and native bindings");
    }
public static class ValidateStockRopeDraw {
    static final Map<String,Object> state=new TreeMap<>();
    static final List<Map<String,Object>> draws=new ArrayList<>();
    static int starts,ends,failAt,begins,finishes,ambients,lights;static boolean normalFlag;static boolean mip;
    public static void Start(Shader s){starts++;}
    public static void End(Shader s){ends++;}
    public static ShaderProgram getShaderProgram(Shader s){return null;}
    public static String getName(ShaderProgram s){return "basicEffect_static";}
    public static boolean isReady(ModelMesh m){return true;}
    public static TextureID getTextureId(Texture t){return null;}
    public static boolean hasMipMaps(TextureID t){return mip;}
    public static void setTexture(Shader s,Texture t,String name,int unit){state.put("texture",t);}
    public static void setDepthBias(Shader s,float v){state.put("bias",v);}
    public static void setTargetDepth(Shader s,float v){state.put("depth",v);}
    public static void setLightingAmount(Shader s,float v){state.put("amount",v);}
    public static void setHueShift(Shader s,float v){state.put("hue",v);}
    public static void setAlpha(Shader s,float v){state.put("alpha",v);}
    public static void setTint(Shader s,float r,float g,float b){state.put("tint",List.of(r,g,b));}
    public static void setAmbient(Shader s,float r,float g,float b){ambients++;state.put("ambient",List.of(r,g,b));}
    public static void setLight(Shader s,int i,float x,float y,float z,float r,float g,float b,float radius,
            float angle,float ox,float oy,float oz,zombie.iso.IsoMovingObject object){
        lights++;state.put("light"+i,List.of(x,y,z,r,g,b,radius,angle,ox,oy,oz));
    }
    public static void setTransformMatrix(Shader s,Matrix4f m,boolean transpose){state.put("matrix",new Matrix4f(m));}
    public static float getDepthValueAt(float x,float y,float z){return .1234f;}
    public static void Draw(ModelMesh m,Shader s){
        if(failAt>0 && draws.size()+1==failAt) throw new IllegalStateException("injected draw failure");
        draws.add(new TreeMap<>(state));
    }
    public static boolean BeginDraw(VertexBufferObject vb,Shader s){begins++;return normalFlag;}
    public static void FinishDraw(VertexBufferObject vb,Shader s,boolean normals){
        if(normals!=normalFlag) throw new AssertionError("lost native cleanup flag");finishes++;
    }
    public static void PushDrawCall(VertexBufferObject vb){Draw(null,null);}
    public static void glDefaultBlendFuncA(){state.put("blend","default");}
    public static void glDepthFunc(int v){state.put("depthFunc",v);}
    public static void glDepthMask(boolean v){state.put("depthMask",v);}
    public static void glDepthRange(double a,double b){state.put("range",List.of(a,b));}
    public static void glEnable(int v){state.put("enable"+v,true);}
    public static void glColor3f(float r,float g,float b){state.put("colour",List.of(r,g,b));}
    public static void glBlendFunc(int a,int b){state.put("blend",List.of(a,b));}
    static Method instrument(Class<?> owner,String name,String descriptor) throws Exception {
        var file=ClassFile.of().parse(owner.getResourceAsStream(owner.getSimpleName()+".class").readAllBytes());
        var method=file.methods().stream().filter(m->m.methodName().equalsString(name)).findFirst().orElseThrow();
        String generated=owner.getPackageName()+".Recorded"+owner.getSimpleName();
        byte[] bytes=ClassFile.of().build(ClassDesc.of(generated),b->b.withMethodBody("run",
            MethodTypeDesc.ofDescriptor(descriptor),ClassFile.ACC_PUBLIC|ClassFile.ACC_STATIC,c->{
                for(var e:method.code().orElseThrow()) {
                    if(e instanceof InvokeInstruction call) {
                        String target=call.owner().asInternalName();
                        boolean redirect=target.equals("zombie/core/skinnedmodel/shader/Shader")
                            || target.equals("zombie/core/opengl/ShaderProgram")
                            || target.equals("org/lwjgl/opengl/GL11") || target.equals("zombie/IndieGL")
                            || target.equals("zombie/core/textures/Texture") || target.equals("zombie/core/textures/TextureID")
                            || target.equals("zombie/core/skinnedmodel/model/ModelMesh")
                            || target.equals("zombie/core/skinnedmodel/model/VertexBufferObject");
                        if(redirect) {
                            String desc=call.type().stringValue();
                            if(call.opcode()!=Opcode.INVOKESTATIC) desc="(L"+target+";"+desc.substring(1);
                            c.invokestatic(ClassDesc.of("cvpworld.ValidateFreeRopeScene$ValidateStockRopeDraw"),call.name().stringValue(),MethodTypeDesc.ofDescriptor(desc));
                            continue;
                        }
                    }
                    c.with(e);
                }
            }));
        var lookup=MethodHandles.privateLookupIn(owner,MethodHandles.lookup());
        return lookup.defineHiddenClass(bytes,true,MethodHandles.Lookup.ClassOption.NESTMATE).lookupClass().getDeclaredMethods()[0];
    }
    static void set(Object o,String name,Object value) throws Exception {
        var f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);
    }
    static void reset(){state.clear();draws.clear();starts=ends=failAt=begins=finishes=ambients=lights=0;}
    public static void run() throws Exception {
        var drawer=ClassFile.of().parse(FreeRopeScene.class.getResourceAsStream("FreeRopeScene$Drawer.class").readAllBytes());
        var render=drawer.methods().stream().filter(m->m.methodName().equalsString("render")).findFirst().orElseThrow();
        int batches=0;
        for(var e:render.code().orElseThrow()) if(e instanceof InvokeInstruction call) {
            if(call.owner().asInternalName().equals("cvpworld/StockRopeDraw") && call.name().equalsString("draw")) batches++;
            if(call.owner().asInternalName().equals("java/lang/reflect/Method") && call.name().equalsString("invoke"))
                throw new AssertionError("drawer still invokes full native render");
        }
        if(batches!=1) throw new AssertionError("batch renderer is not connected");
        var f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);var u=(sun.misc.Unsafe)f.get(null);
        var model=(Model)u.allocateInstance(Model.class);model.isStatic=true;
        var mesh=(ModelMesh)u.allocateInstance(ModelMesh.class);mesh.transform=new Matrix4f();set(model,"mesh",mesh);
        model.effect=(Shader)u.allocateInstance(Shader.class);
        mesh.vb=(VertexBufferObject)u.allocateInstance(VertexBufferObject.class);
        var handle=VertexBufferObject.class.getDeclaredField("handle");handle.setAccessible(true);
        handle.set(mesh.vb,u.allocateInstance(handle.getType()));
        var texture=(Texture)u.allocateInstance(Texture.class);
        var nativeDraw=new IsoObjectModelDrawer();set(nativeDraw,"model",model);set(nativeDraw,"texture",texture);
        var old=instrument(IsoObjectModelDrawer.class,"renderModel","(Lzombie/core/skinnedmodel/model/IsoObjectModelDrawer;Z)V");
        var batch=instrument(StockRopeDraw.class,"draw","(Lzombie/core/skinnedmodel/model/Model;Lzombie/core/textures/Texture;[Lorg/joml/Matrix4f;[F[F[FIFZ)V");
        Matrix4f[] matrices={new Matrix4f().translation(1,2,3),new Matrix4f().rotateY(.7f),new Matrix4f().scale(.3f,2,.1f)};
        float[] r={.1f,.1f,.9f},g={.2f,.2f,.8f},b={.3f,.3f,.7f};
        boolean chunks=zombie.core.PerformanceSettings.fboRenderChunk;boolean debug=Core.debug;
        var noLight=zombie.debug.DebugOptions.instance.fboRenderChunk.nolighting;boolean previous=noLight.getValue();
        try {
            Core.debug=true;
            for(boolean fbo:new boolean[]{false,true}) for(boolean unlit:new boolean[]{false,true})
            for(boolean selected:new boolean[]{false,true}) for(boolean mipmaps:new boolean[]{false,true}) {
                zombie.core.PerformanceSettings.fboRenderChunk=fbo;noLight.setValue(unlit);mip=mipmaps;normalFlag=mipmaps;
                reset();set(nativeDraw,"squareDepth",.31f);set(nativeDraw,"tintR",1f);
                set(nativeDraw,"tintG",selected?.85f:1f);set(nativeDraw,"tintB",selected?.3f:1f);
                for(int i=0;i<3;i++) {
                    set(nativeDraw,"transform",matrices[i]);set(nativeDraw,"ambientR",r[i]);set(nativeDraw,"ambientG",g[i]);set(nativeDraw,"ambientB",b[i]);
                    old.invoke(null,nativeDraw,false);
                }
                var expected=new ArrayList<>(draws);if(starts!=3 || ends!=3) throw new AssertionError("native oracle");
                reset();batch.invoke(null,model,texture,matrices,r,g,b,3,.31f,selected);
                if(begins!=1 || finishes!=1 || ambients!=(noLight.getValue()?1:2) || lights!=(noLight.getValue()?5:7) || starts!=1 || ends!=1 || !draws.equals(expected)) throw new AssertionError("batch differs: begins="+begins+" finishes="+finishes+" ambient="+ambients+" lights="+lights+" starts="+starts+" ends="+ends+" equal="+draws.equals(expected)+" unlit="+unlit);
                reset();failAt=2;
                try {batch.invoke(null,model,texture,matrices,r,g,b,3,.31f,selected);throw new AssertionError("failure not raised");}
                catch(InvocationTargetException error){if(!(error.getCause() instanceof IllegalStateException)) throw error;}
                if(begins!=1 || finishes!=1 || starts!=1 || ends!=1 || draws.size()!=1) throw new AssertionError("shader cleanup failed");
                reset();batch.invoke(null,model,texture,matrices,r,g,b,0,.31f,selected);
                if(starts!=0 || ends!=0 || !draws.isEmpty()) throw new AssertionError("empty batch touched shader");
            }
            var saved=handle.get(mesh.vb);
            handle.set(mesh.vb,null);reset();batch.invoke(null,model,texture,matrices,r,g,b,3,.31f,false);
            if(starts!=0 || begins!=0) throw new AssertionError("unready VBO drawn");
            handle.set(mesh.vb,saved);
            var skip=zombie.debug.DebugOptions.instance.debugDrawSkipVboDraw;boolean oldSkip=skip.getValue();
            try {skip.setValue(true);reset();batch.invoke(null,model,texture,matrices,r,g,b,3,.31f,false);
                if(skip.getValue() && (starts!=0 || begins!=0)) throw new AssertionError("debug skip ignored");
            } finally {skip.setValue(oldSkip);}
        } finally {Core.debug=debug;zombie.core.PerformanceSettings.fboRenderChunk=chunks;noLight.setValue(previous);}
        System.out.println("PASS batch/native draw equivalence: per-segment matrices/light/depth/blend, one shader pair, failure cleanup");
    }
}

}
