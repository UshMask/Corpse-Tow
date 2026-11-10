package cvpworld;

import org.joml.Matrix4f;
import org.lwjgl.opengl.GL11;
import zombie.IndieGL;
import zombie.core.PerformanceSettings;
import zombie.core.skinnedmodel.model.Model;
import zombie.core.skinnedmodel.model.VertexBufferObject;
import zombie.core.textures.Texture;
import zombie.debug.DebugOptions;

/** B42 static basicEffect path: shared setup, unchanged mesh draw per segment. */
final class StockRopeDraw {
    private static final java.lang.reflect.Field handle;
    static {
        try { handle=VertexBufferObject.class.getDeclaredField("handle");handle.setAccessible(true); }
        catch(ReflectiveOperationException e) { throw new ExceptionInInitializerError(e); }
    }
    static float targetDepth(float depth,float origin,boolean chunks) {
        return chunks?depth-(origin+1)/2+.5f:.5f;
    }
    static void draw(Model model,Texture texture,Matrix4f[] matrices,float[] red,float[] green,float[] blue,
            int count,float depth,boolean selected) throws IllegalAccessException {
        if(count==0) return;
        var vb=model.mesh.vb;
        // Preserve the native Draw guard; BeginDraw itself does not check readiness.
        if(vb==null || handle.get(vb)==null || DebugOptions.instance.debugDrawSkipVboDraw.getValue()) return;
        var shader=model.effect;
        IndieGL.glDefaultBlendFuncA();
        GL11.glDepthFunc(GL11.GL_LESS);GL11.glDepthMask(true);GL11.glDepthRange(0,1);
        GL11.glEnable(GL11.GL_DEPTH_TEST);GL11.glColor3f(1,1,1);
        // No model script, outline or animation palette: these are our static meshes.
        try {
            shader.Start();
            if(!texture.getTextureId().hasMipMaps()) GL11.glBlendFunc(GL11.GL_SRC_ALPHA,GL11.GL_ONE_MINUS_SRC_ALPHA);
            shader.setTexture(texture,"Texture",0);
            shader.setDepthBias(0);
            shader.setTargetDepth(targetDepth(depth,VertexBufferObject.getDepthValueAt(0,0,0),PerformanceSettings.fboRenderChunk));
            shader.setLightingAmount(1);shader.setHueShift(0);
            shader.setTint(1,selected?.85f:1,selected?.3f:1);shader.setAlpha(1);
            boolean unlit=DebugOptions.instance.fboRenderChunk.nolighting.getValue();
            for(int i=0;i<5;i++) shader.setLight(i,0,0,0,0,0,0,0,Float.NaN,0,0,0,null);
            boolean normals=vb.BeginDraw(shader);
            try {
                float previousR=0,previousG=0,previousB=0;
                for(int i=0;i<count;i++) {
                    float r=red[i],g=green[i],b=blue[i];
                    if(i==0 || (!unlit && (r!=previousR || g!=previousG || b!=previousB))) {
                        shader.setAmbient(unlit?1:r,unlit?1:g,unlit?1:b);
                        // Native drawer's angle is zero; preserve its light axis and arithmetic.
                        if(!unlit) shader.setLight(4,0,-2,5,r/4*1.5f,g/4*1.5f,b/4*1.5f,5000,Float.NaN,0,0,0,null);
                        previousR=r;previousG=g;previousB=b;
                    }
                    shader.setTransformMatrix(matrices[i],false);
                    vb.PushDrawCall();
                }
            } finally {vb.FinishDraw(shader,normals);}
        } finally {shader.End();}
    }
}
