package cvpworld;

import java.lang.classfile.ClassFile;
import java.lang.classfile.instruction.InvokeInstruction;
import zombie.core.Core;
import zombie.core.PerformanceSettings;
import zombie.debug.DebugOptions;
import zombie.iso.fboRenderChunk.FBORenderCell;
import zombie.iso.objects.IsoDeadBody;

/** Checks the installed engine's native uncached path, without starting a game. */
public class ValidateDynamicCorpses {
    static void check(boolean value,String why) {if(!value) throw new AssertionError(why);}
    public static void main(String[] args) throws Exception {
        if(args[0].equals("disabled")) {
            check(!DynamicCorpses.canSkipMoveInvalidation(),"explicit false must disable prototype");
            System.out.println("PASS dynamic corpse prototype explicitly disabled");return;
        }
        zombie.core.random.RandStandard.INSTANCE.init();
        zombie.core.random.RandStandard.INSTANCE.init();
        boolean present=args[0].equals("present");
        var option=DebugOptions.instance.fboRenderChunk.corpsesInChunkTexture;
        check(!option.getDefaultValue() && option.isDebugOnly(),"B42 default corpse rendering changed");
        Core.debug=false;option.setValue(true);PerformanceSettings.fboRenderChunk=true;
        check(!option.getValue(),"non-debug must use native default");
        java.lang.reflect.Field camera=null;
        if(present) {camera=Class.forName("viewpoint.core.View").getField("enabled");camera.setBoolean(null,false);}
        check(DynamicCorpses.canSkipMoveInvalidation(),"native world rendering not detected");
        for(int i=0;i<3;i++) {
            if(present) {
                camera.setBoolean(null,true);check(!DynamicCorpses.canSkipMoveInvalidation(),"Viewpoint lost invalidation");
                camera.setBoolean(null,false);check(DynamicCorpses.canSkipMoveInvalidation(),"return to isometry");
            }
            Core.debug=true;check(!DynamicCorpses.canSkipMoveInvalidation(),"baked mode lost invalidation");
            option.setValue(false);check(DynamicCorpses.canSkipMoveInvalidation(),"native uncached mode");
            PerformanceSettings.fboRenderChunk=false;check(!DynamicCorpses.canSkipMoveInvalidation(),"unsupported renderer");
            PerformanceSettings.fboRenderChunk=true;
            zombie.network.GameServer.server=true;check(!DynamicCorpses.canSkipMoveInvalidation(),"server fallback");
            zombie.network.GameServer.server=false;zombie.network.GameClient.client=true;
            check(DynamicCorpses.canSkipMoveInvalidation(),"MP client world rendering");
            zombie.network.GameClient.client=false;Core.debug=false;option.setValue(true);
        }
        var cell=ClassFile.of().parse(FBORenderCell.class.getResourceAsStream("FBORenderCell.class").readAllBytes());
        boolean beforeFog=false,livePosition=false;
        for(var method:cell.methods()) if(method.code().isPresent()) {
            int at=0,world=-1,fog=-1;var calls=new java.util.HashSet<String>();
            for(var element:method.code().get()) if(element instanceof InvokeInstruction call) {
                calls.add(call.name().stringValue());
                if(call.name().equalsString("renderCorpsesInWorld")) world=at;
                if(call.name().equalsString("renderFog")) fog=at;
                at++;
            }
            if(world>=0 && fog>world) beforeFog=true;
            if(method.methodName().equalsString("renderCorpses"))
                livePosition=calls.containsAll(java.util.List.of("getX","getY","getZ","getLightInfo","shouldRenderSquare","render"));
        }
        check(beforeFog && livePosition,"native per-frame position/light/fog contract changed");
        var body=ClassFile.of().parse(IsoDeadBody.class.getResourceAsStream("IsoDeadBody.class").readAllBytes());
        boolean atlas=false;
        for(var method:body.methods()) if(method.methodName().equalsString("render") && method.code().isPresent())
            for(var element:method.code().get()) if(element instanceof InvokeInstruction call && call.name().equalsString("getBodyTexture")) atlas=true;
        check(atlas,"native atlas renderer unavailable");
        System.out.println("PASS native world corpse rendering: actual B42 default, camera/cache transitions, SP/MP guards, live position/light and pre-fog stage; Viewpoint="+present);
    }
}
