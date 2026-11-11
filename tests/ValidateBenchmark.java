import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import se.krka.kahlua.j2se.J2SEPlatform;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.vm.KahluaThread;

/** Execute the dev adapter with the game's actual Lua VM, without launching PZ. */
public class ValidateBenchmark {
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args.length==0?".":args[0]);
        var square=zombie.iso.IsoGridSquare.class;
        if(!java.util.Set.class.isAssignableFrom(zombie.iso.IsoCell.class.getMethod("getVehicles").getReturnType()))
            throw new AssertionError("Update fixture for changed vehicle collection API");
        square.getMethod("createCorpse",boolean.class);
        square.getMethod("getDeadBodys");
        zombie.characters.IsoPlayer.class.getMethod("setCurrent",square);
        zombie.iso.objects.IsoDeadBody.class.getMethod("setSquare",square);
        zombie.inventory.ItemContainer.class.getMethod("getItemWithID",int.class);
        zombie.vehicles.BaseVehicle.class.getMethod("setPhysicsActive",boolean.class);
        zombie.vehicles.BaseVehicle.class.getMethod("getAttachmentWorldPos",String.class,org.joml.Vector3f.class);
        var platform=J2SEPlatform.getInstance();
        var env=platform.newEnvironment();
        zombie.Lua.LuaManager.env=env;
        var thread=new KahluaThread(platform,env);
        thread.debugOwnerThread=Thread.currentThread();
        zombie.Lua.LuaManager.thread=thread;
        zombie.Lua.LuaManager.debugthread=new KahluaThread(platform,env);
        zombie.Lua.LuaManager.debugthread.debugOwnerThread=Thread.currentThread();
        env.rawset("DoLuaError",(se.krka.kahlua.vm.JavaFunction)(frame,count)->0);
        String source=Files.readString(root.resolve("tests/fixtures/benchmark_fixture.lua"))+"\n"+
            "local function loadTestCore()\n"+Files.readString(root.resolve("tools/pz-test/mod/42/media/lua/shared/PZT_Control.lua"))+"\nend\nfunction require(name) assert(name=='PZT_Control');return PZTest or loadTestCore() end\n"+
            Files.readString(root.resolve("tests/scenarios/corpse-tow/CVP_Benchmark.lua"))+"\n"+"""
            local answer=send('r','reset');assert(answer:find('true'),answer)
            for _,n in ipairs({0,1,8,32,128,0}) do
                local answer=send('s'..n..'_'..now,'scene',n);assert(answer:find('true'),answer)
                assert(#CVPBenchmark.bodies==n)
            end
            assert(send('bad','scene',1.5):find('false'))
            assert(send('m','measure'):find('warming'))
            now=now+10000;render()
            for i=1,2000 do now=now+10;render() end
            assert(outputs['CVPBenchmark-m-frames.txt'])
            assert(outputs['CVPBenchmark-m-meta.txt'])
            assert(PZTest.lastResponse.result:find('done'))
            """;
        // Both compiler modes: the benchmark now runs without Lua debug.
        for(boolean debug:new boolean[]{true,false}) {
            zombie.core.Core.debug=debug;
            LuaCompiler.loadstring(Files.readString(root.resolve("tests/scenarios/corpse-tow/CVP_Drive.lua")),"driving-syntax",env);
            LuaCompiler.loadstring(Files.readString(root.resolve("tests/scenarios/corpse-tow/CVP_Performance.lua")),"performance-syntax",env);
        }
        var result=thread.pcall(LuaCompiler.loadstring(source,"benchmark-validation",env),new Object[0]);
        if(!Boolean.TRUE.equals(result[0])) {
            for(Object value:result) if(value instanceof Throwable error) error.printStackTrace();
            throw new AssertionError(Arrays.toString(result));
        }
        System.out.println("PASS benchmark lifecycle in game Kahlua VM and native API signatures");
    }
}
