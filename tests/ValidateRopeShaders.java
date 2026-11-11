package cvpworld;

import java.nio.file.*;
import java.lang.reflect.*;
import org.joml.Matrix4f;
import org.joml.Vector3f;
import org.lwjgl.opengl.GL;
import static org.lwjgl.opengl.GL33.*;
import static org.lwjgl.glfw.GLFW.*;
import viewpoint.core.Frame;
import viewpoint.render.*;
import zombie.Lua.LuaManager;
import se.krka.kahlua.j2se.J2SEPlatform;

/** Numeric transform-feedback tests of installed vertex shaders in a hidden GL context. No game/UI. */
public class ValidateRopeShaders {
    static int feedback, vao;
    static int shader(String source,String varying) {
        int s=glCreateShader(GL_VERTEX_SHADER);glShaderSource(s,source);glCompileShader(s);
        if(glGetShaderi(s,GL_COMPILE_STATUS)==0) throw new AssertionError(glGetShaderInfoLog(s));
        int p=glCreateProgram();glAttachShader(p,s);
        glTransformFeedbackVaryings(p,new String[]{varying},GL_INTERLEAVED_ATTRIBS);glLinkProgram(p);
        if(glGetProgrami(p,GL_LINK_STATUS)==0) throw new AssertionError(glGetProgramInfoLog(p));
        glDeleteShader(s);return p;
    }
    static void matrix(int p,String name,Matrix4f m) {glUniformMatrix4fv(glGetUniformLocation(p,name),false,m.get(new float[16]));}
    static Vector3f vertex(int p,Vector3f v) {
        glVertexAttrib4f(0,v.x,v.y,v.z,1);glBindBufferBase(GL_TRANSFORM_FEEDBACK_BUFFER,0,feedback);
        glBeginTransformFeedback(GL_POINTS);glDrawArrays(GL_POINTS,0,1);glEndTransformFeedback();
        float[] out=new float[4];glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,feedback);glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER,0,out);
        int error=glGetError();if(error!=GL_NO_ERROR) throw new AssertionError("GL error "+error);
        var result=new Vector3f(out[0],out[1],out[2]);
        if(!result.isFinite()) throw new AssertionError("nonfinite shader result");return result;
    }
    static String viewpointShader() throws Exception {
        var type=Class.forName("viewpoint.platform.Shaders");var load=type.getDeclaredMethod("load",String.class);load.setAccessible(true);
        Object source=load.invoke(null,"model.vert");var text=source.getClass().getDeclaredField("text");text.setAccessible(true);
        return (String)text.get(source);
    }
    static int texture(int unit,int size,float[] values) {
        glActiveTexture(GL_TEXTURE0+unit);int t=glGenTextures();glBindTexture(GL_TEXTURE_2D,t);
        glTexImage2D(GL_TEXTURE_2D,0,GL_R32F,size,size,0,GL_RED,GL_FLOAT,values);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        return t;
    }
    static java.util.List<Vector3f> mesh(boolean chain) throws Exception {
        var lines=Files.readAllLines(Path.of("CorpseProxyLab/42/media/models/"+(chain?"CVPChainSegment":"CVPRopeSegment")+".txt"));
        var result=new java.util.ArrayList<Vector3f>();int count=Integer.parseInt(lines.get(11).trim());
        for(int i=0;i<count;i++) {
            String[] xyz=lines.get(12+i*3).split(",");
            result.add(new Vector3f(Float.parseFloat(xyz[0].trim()),Float.parseFloat(xyz[1].trim()),Float.parseFloat(xyz[2].trim())));
        }
        return result;
    }
    static void viewpoint(int program) throws Exception {
        var capture=Class.forName("viewpoint.models.VehicleCapture");
        var placed=capture.getDeclaredMethod("placed",Frame.class,zombie.core.skinnedmodel.model.ModelSlotRenderData.class,zombie.vehicles.BaseVehicle.class);placed.setAccessible(true);
        var placement=capture.getDeclaredField("place");placement.setAccessible(true);
        var unsafeField=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
        var vehicle=(zombie.vehicles.BaseVehicle)((sun.misc.Unsafe)unsafeField.get(null)).allocateInstance(zombie.vehicles.BaseVehicle.class);
        var script=new zombie.scripting.objects.VehicleScript();var attachment=new zombie.scripting.objects.ModelAttachment("trailer");script.addAttachment(attachment);
        attachment.getOffset().set(0,.25f,1);
        var wheelsField=zombie.scripting.objects.VehicleScript.class.getDeclaredField("wheels");wheelsField.setAccessible(true);
        @SuppressWarnings("unchecked") var wheels=(java.util.List<zombie.scripting.objects.VehicleScript.Wheel>)wheelsField.get(script);
        for(int x:new int[]{-1,1}) for(int z:new int[]{-1,1}) {
            var wheel=new zombie.scripting.objects.VehicleScript.Wheel();wheel.offset.set(x,0,z);wheels.add(wheel);
        }
        var scriptField=zombie.vehicles.BaseVehicle.class.getDeclaredField("script");scriptField.setAccessible(true);scriptField.set(vehicle,script);
        var physics=new zombie.core.physics.Transform();physics.basis.identity();physics.origin.set(5,0,5);
        var physicsField=zombie.vehicles.BaseVehicle.class.getDeclaredField("jniTransform");physicsField.setAccessible(true);physicsField.set(vehicle,physics);
        var slot=new zombie.core.skinnedmodel.model.ModelSlotRenderData();slot.object=vehicle;slot.x=5;slot.y=5;slot.centerOfMassY=-.7f;
        slot.vehicleTransform.identity();zombie.vehicles.BaseVehicle.centerOfMassMagic=.7f;
        Frame frame=new Frame();frame.camX=5;frame.camY=5;frame.camZ=.2f;
        viewpoint.core.View.enabled=true;
        var values=ModelDraws.class.getDeclaredField("values");values.setAccessible(true);
        int buffer=glGenBuffers(),drawTexture=glGenTextures();
        glUseProgram(program);matrix(program,"uViewProjection",new Matrix4f());
        glUniform1i(glGetUniformLocation(program,"uDraws"),0);glUniform1i(glGetUniformLocation(program,"uPalettes"),0);
        glUniform1i(glGetUniformLocation(program,"uRelief"),1);
        glUniform1i(glGetUniformLocation(program,"uReliefWalls"),2);
        glUniform1i(glGetUniformLocation(program,"uReliefWater"),3);
        glUniform1i(glGetUniformLocation(program,"uReliefFlow"),4);
        glUniform2f(glGetUniformLocation(program,"uReliefCamera"),frame.camX,frame.camY);
        glUniform1f(glGetUniformLocation(program,"uReliefScale"),1);
        int walls=texture(2,4,new float[16]),water=texture(3,4,new float[16]),flow=texture(4,4,new float[16]);
        glVertexAttribI1i(6,0);glVertexAttrib4f(2,0,0,0,0);glVertexAttrib4f(3,0,0,0,0);
        boolean detectedOld=false,tilted=false;
        for(boolean attached:new boolean[]{false,true}) for(boolean chain:new boolean[]{false,true}) for(boolean reliefOn:new boolean[]{false,true}) for(float ground:new float[]{-1,0,2}) for(float slope:new float[]{0,.05f,.4f}) for(boolean first:new boolean[]{true,false}) {
            var vertices=mesh(chain);
            float[] heights=new float[16];for(int y=0;y<4;y++) for(int x=0;x<4;x++) heights[y*4+x]=1+x*slope+y*slope/2;
            var grid=FarRelief.Field.of(4,4,heights,new float[16]);
            // Use exactly the quantized heights uploaded by the installed terrain API.
            for(int i=0;i<16;i++) heights[i]=grid.metres(i);
            frame.scene.relief=reliefOn?new FarRelief.Lift(grid,1,ground,frame.camX,frame.camY):null;frame.number++;
            int terrain=texture(1,4,heights);glUniform4f(glGetUniformLocation(program,"uReliefGrid"),4,4,reliefOn?1:0,ground);
            FreeRopeScene.clear();FreeRopeScene.update("shader",ValidateFreeRopeScene.settled(5,6,0,first),chain);
            if(attached) FreeRopeScene.vehicle("shader",vehicle,first);
            placed.invoke(null,frame,slot,vehicle);Matrix4f place=new Matrix4f((Matrix4f)placement.get(null));
            tilted|=Math.abs(place.m01())+Math.abs(place.m21())>.0001f;
            cvprender.Bridge.ropeVehicle(frame,slot,vehicle);
            if(!cvprender.Bridge.active()) throw new AssertionError("production Viewpoint bridge failed");
            var source=FreeRopeScene.snapshots().getFirst();var row=ValidateFreeRopeScene.rendered(source,true);
            Vector3f nativeHitch=attached?slot.vehicleTransform.transformPosition(anchorLocal(vehicle),new Vector3f()):new Vector3f();place.transformPosition(nativeHitch);
            int last=source.keys().length,end=first?0:last;
            for(int i=0;i<last;i++) {
                Matrix4f transform=new Matrix4f();FreeRopeScene.sceneSegment(row,i,frame.camX,frame.camY,frame.camZ,transform);
                ModelDraws draws=new ModelDraws();int at=draws.add(null,null,null,transform,-1,-1,0,ModelDraws.COLOUR|ModelDraws.SHADOW);
                glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_BUFFER,drawTexture);glBindBuffer(GL_TEXTURE_BUFFER,buffer);
                glBufferData(GL_TEXTURE_BUFFER,(float[])values.get(draws),GL_STREAM_DRAW);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,buffer);
                for(int n=0;n<2;n++) {
                    int point=i+n;Vector3f actual=vertex(program,new Vector3f(0,n,0));
                    if(attached && point==end) ValidateFreeRopeScene.near(actual,nativeHitch);
                    else if(!attached || point==(first?last:0)) {
                        int k=point*3;Vector3f expected=new Vector3f((float)(frame.camX-source.points()[k]),
                            (float)((source.points()[k+2]/3-frame.camZ)*RopeGeometry.STOREY)+(reliefOn?frame.scene.relief.scene(source.points()[k],source.points()[k+1]):0),
                            (float)(frame.camY-source.points()[k+1]));ValidateFreeRopeScene.near(actual,expected);
                    }
                }
                // Test the actual mesh, including its underside, after the installed
                // EACH_VERTEX shader. Endpoint-only checks missed buried slack.
                for(Vector3f v:vertices) {
                    Vector3f actual=vertex(program,v);
                    double groundY=-frame.camZ*RopeGeometry.STOREY+(reliefOn?frame.scene.relief.scene(frame.camX-actual.x,frame.camY-actual.z):0);
                    if(actual.y<groundY-.0001) throw new AssertionError("buried mesh: chain="+chain+" segment="+i+" y="+actual.y+" ground="+groundY);
                }
            }
            if(reliefOn && attached) {
                // Exercise the former path through the same real shader: its
                // hitch must diverge, not merely pass an algebraic assertion.
                FreeRopeScene.perspectiveVehicle(slot,place,frame.camX,frame.camY,frame.camZ,null);
                var old=ValidateFreeRopeScene.rendered(source,true);var transform=new Matrix4f();
                FreeRopeScene.sceneSegment(old,first?0:last-1,frame.camX,frame.camY,frame.camZ,transform);
                ModelDraws draws=new ModelDraws();draws.add(null,null,null,transform,-1,-1,0,3);
                glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_BUFFER,drawTexture);glBindBuffer(GL_TEXTURE_BUFFER,buffer);
                glBufferData(GL_TEXTURE_BUFFER,(float[])values.get(draws),GL_STREAM_DRAW);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,buffer);
                detectedOld|=vertex(program,new Vector3f(0,first?0:1,0)).distance(nativeHitch)>.1f;
            }
            if(attached) {
                // Move the live hitch away from the captured placement. Both early
                // exits must discard that placement, while retaining the free end.
                double[] unchanged=source.points().clone();
                float originalX=physics.origin.x;
                try {
                    physics.origin.x=originalX+3;
                    viewpoint.core.View.enabled=false;cvprender.FreeLinks.capture(frame,0);
                    liveEndpoints(source,vehicle,first);
                    viewpoint.core.View.enabled=true;cvprender.Bridge.ropeVehicle(frame,slot,vehicle);
                    var cell=zombie.iso.IsoWorld.instance.currentCell;
                    try {
                        physics.origin.x=originalX+6;
                        zombie.iso.IsoWorld.instance.currentCell=null;cvprender.FreeLinks.capture(frame,0);
                        liveEndpoints(source,vehicle,first);
                    } finally {zombie.iso.IsoWorld.instance.currentCell=cell;}
                    if(!java.util.Arrays.equals(unchanged,source.points()))
                        throw new AssertionError("fallback mutated queued source geometry");
                } finally {
                    physics.origin.x=originalX;viewpoint.core.View.enabled=true;
                    FreeRopeScene.endPerspective();
                }
            }
            glDeleteTextures(terrain);
        }
        if(!detectedOld) throw new AssertionError("terrain fixture did not distinguish double lifting");
        if(!tilted) throw new AssertionError("native VehicleTilt was not exercised");
        cvprender.Bridge.ropeVehicle(frame,slot,vehicle);
        var source=FreeRopeScene.snapshots().getFirst();
        double[] expected=ValidateFreeRopeScene.rendered(source,true).points().clone();
        var placedMethod=cvprender.Bridge.class.getDeclaredField("vehiclePlace");placedMethod.setAccessible(true);
        Object saved=placedMethod.get(null);
        try {
            // Inject an incompatible reflected value into the real capture boundary.
            placedMethod.set(null,Integer.class.getField("MAX_VALUE"));
            cvprender.Bridge.ropeVehicle(frame,slot,vehicle);
            if(!cvprender.Bridge.active() || FreeRopeScene.ready()) throw new AssertionError("rope capture failure disabled adapter or lacks cooldown");
        } finally {placedMethod.set(null,saved);}
        if(!FreeRopeScene.ready(System.nanoTime()+6_000_000_000L)) throw new AssertionError("rope capture did not retry");
        cvprender.Bridge.ropeVehicle(frame,slot,vehicle);
        var recovered=FreeRopeScene.snapshots().getFirst();
        if(!FreeRopeScene.ready() || recovered!=source) throw new AssertionError("rope capture lost its snapshot");
        double[] actual=ValidateFreeRopeScene.rendered(recovered,true).points();
        for(int i=0;i<expected.length;i++)
            if(!Double.isFinite(actual[i]) || Math.abs(actual[i]-expected[i])>.0001)
                throw new AssertionError("rope capture not restored at coordinate "+i);
        glDeleteBuffers(buffer);glDeleteTextures(drawTexture);glDeleteTextures(walls);glDeleteTextures(water);glDeleteTextures(flow);
        FreeRopeScene.clear();viewpoint.core.View.enabled=false;
        System.out.println("PASS 144 Viewpoint shader cases: attached/free rope and chain, signed relief, slopes, mesh clearance, endpoint stability, early exits and recovery");
    }
    static void liveEndpoints(FreeRopeScene.Snapshot source,zombie.vehicles.BaseVehicle vehicle,boolean first) {
        var row=ValidateFreeRopeScene.rendered(source,true);
        int last=source.keys().length;
        ValidateFreeRopeScene.near(ValidateFreeRopeScene.point(row,first?0:last),
            vehicle.getAttachmentWorldPos("trailer",new Vector3f()));
        ValidateFreeRopeScene.near(ValidateFreeRopeScene.point(row,first?last:0),
            ValidateFreeRopeScene.point(source,first?last:0));
    }
    static Vector3f anchorLocal(zombie.vehicles.BaseVehicle vehicle) throws Exception {
        var anchors=FreeRopeScene.class.getDeclaredField("vehicles");anchors.setAccessible(true);
        Object anchor=((Object[])((java.util.Map<?,?>)anchors.get(null)).get(vehicle))[0];
        var local=anchor.getClass().getDeclaredField("local");local.setAccessible(true);return new Vector3f((Vector3f)local.get(anchor));
    }
    public static void main(String[] args) throws Exception {
        if(!glfwInit()) throw new AssertionError("GLFW initialization failed");
        glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
        long window=glfwCreateWindow(32,32,"Corpse Tow numeric shader test",0,0);
        if(window==0) throw new AssertionError("Hidden GL context unavailable");
        try {
            glfwMakeContextCurrent(window);GL.createCapabilities();glEnable(GL_RASTERIZER_DISCARD);
            vao=glGenVertexArrays();glBindVertexArray(vao);feedback=glGenBuffers();glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,feedback);glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER,16,GL_STREAM_READ);
            LuaManager.platform=new J2SEPlatform();
            int iso=shader(Files.readString(Path.of(System.getProperty("cvp.game"),"media/shaders/basicEffect_static.vert")),"gl_Position");
            ValidateFreeRopeScene.shaderProjection=(camera,transform,v)->{
                glUseProgram(iso);glUniform1f(glGetUniformLocation(iso,"targetDepth"),.5f);matrix(iso,"ModelViewProjection",camera);matrix(iso,"transform",transform);return vertex(iso,v);
            };
            ValidateFreeRopeScene.depthProjection=(camera,transform,v,target)->{
                glUseProgram(iso);glUniform1f(glGetUniformLocation(iso,"targetDepth"),target);matrix(iso,"ModelViewProjection",camera);matrix(iso,"transform",transform);return vertex(iso,v);
            };
            var surface=new java.util.ArrayList<Vector3f>(mesh(false));surface.addAll(mesh(true));
            ValidateFreeRopeScene.surfaceVertices=surface;
            // The larger chain radius conservatively covers both mesh profiles.
            FreeRopeScene.update("iso",ValidateFreeRopeScene.points(6200,5200,.025),true);
            ValidateFreeRopeScene.nativeCamera(FreeRopeScene.snapshots().getFirst());
            System.out.println("PASS installed PZ static shader: unchanged projection, native terrain depth, mesh clearance, old occlusion reproduced, pan and both tile scales");
            int view=shader(viewpointShader(),"vPos");viewpoint(view);
            glDeleteProgram(iso);glDeleteProgram(view);glDeleteBuffers(feedback);glDeleteVertexArrays(vao);
        } finally {glfwDestroyWindow(window);glfwTerminate();}
    }
}
