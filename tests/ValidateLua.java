package cvpworld;

import java.nio.file.Files;
import java.nio.file.Path;
import se.krka.kahlua.luaj.compiler.LuaCompiler;
import se.krka.kahlua.j2se.KahluaTableImpl;
import java.util.HashMap;

/** Compile shipped Lua with the game's compiler, not the model-test Lua VM. */
public class ValidateLua {
    public static void main(String[] args) throws Exception {
        int count = 0;
        // Quick Test uses -debug: its compiler records all locals per function
        // in a fixed array, including locals from scopes that have already ended.
        zombie.core.Core.debug = true;
        for (String root : new String[]{"CorpseProxyLab", "CorpseProxyViewpoint", "CVPAgent", "tools/pz-test/mod", "tools/quick-test", "tests/scenarios"}) {
            try (var files = Files.walk(Path.of(root))) {
                for (Path file : files.filter(p -> p.toString().endsWith(".lua")).sorted().toList()) {
                    try {
                        LuaCompiler.loadstring(Files.readString(file), file.toString(), new KahluaTableImpl(new HashMap<>()));
                    } catch (Exception error) {
                        throw new AssertionError("Game Lua compiler rejected " + file, error);
                    }
                    count++;
                }
            }
        }
        if (count == 0) throw new AssertionError("No shipped Lua files found");
        System.out.println("PASS game Lua compilation: " + count + " files");
        validateSaveJobs();
    }
    static void validateSaveJobs() throws Exception {
        var platform=se.krka.kahlua.j2se.J2SEPlatform.getInstance();
        var env=platform.newTable();env.rawset("_G",env);
        se.krka.kahlua.j2se.MathLib.register(platform,env);
        se.krka.kahlua.stdlib.OsLib.register(platform,env);
        se.krka.kahlua.stdlib.BaseLib.register(env);
        se.krka.kahlua.stdlib.CoroutineLib.register(platform,env);
        se.krka.kahlua.stdlib.StringLib.register(platform,env);
        se.krka.kahlua.stdlib.TableLib.register(platform,env);
        var thread=new se.krka.kahlua.vm.KahluaThread(platform,env);
        thread.debugOwnerThread=Thread.currentThread();
        zombie.Lua.LuaManager.env=env;zombie.Lua.LuaManager.thread=thread;zombie.Lua.LuaManager.debugthread=thread;
        env.rawset("DoLuaError",(se.krka.kahlua.vm.JavaFunction)(f,n)->0);
        thread.call(LuaCompiler.loadstring(Files.readString(Path.of(System.getProperty("cvp.game"),"stdlib.lua")),"stdlib",env),null,null,null);
        String module=Files.readString(Path.of("CorpseProxyLab/42/media/lua/shared/CVP_SaveJobs.lua"));
        String source="local Jobs=(function()\n"+module+"\nend)()\n"+"""
            local calls,replies=0,0
            CVPEquipmentPersistence={
                checkpointPlayerAsync=function() calls=calls+1;return {polls=0} end,
                writeAsync=function() calls=calls+1;return {polls=0} end,
                poll=function(t) t.polls=t.polls+1;return t.polls>=3 and 1 or 0 end,
                result=function() return true end}
            local job=Jobs.new(function()
                assert(Jobs.call('checkpointPlayer',{}))
                assert(Jobs.call('write',{}));return true,'saved'
            end,function(ok,result) assert(ok and result=='saved');replies=replies+1 end)
            assert(not Jobs.advance(job) and replies==0 and calls==1)
            for i=1,10 do Jobs.advance(job) end
            assert(job.done and replies==1 and calls==2)
            local cancelled=false
            job=Jobs.new(function()
                local ok,why=Jobs.call('checkpointPlayer',{});return ok,nil,why
            end,function(ok,_,why) assert(not ok and why=='cancelled');replies=replies+1 end,
            function() return cancelled and 'cancelled' end)
            assert(not Jobs.advance(job));cancelled=true
            for i=1,10 do Jobs.advance(job) end
            assert(replies==2 and calls==3)
            CVPEquipmentPersistence.poll=function() error('disk failure') end
            job=Jobs.new(function() return Jobs.call('write',{}) end,
                function(ok,why) assert(not ok and string.find(why,'disk failure'));replies=replies+1 end)
            Jobs.advance(job);assert(replies==3)
            for _,failure in ipairs({'ticket','poll','result'}) do
                CVPEquipmentPersistence.writeAsync=function() if failure~='ticket' then return {} end end
                CVPEquipmentPersistence.poll=function() if failure~='poll' then return 1 end end
                CVPEquipmentPersistence.result=function() if failure~='result' then return true end end
                local answered=0
                job=Jobs.new(function() return Jobs.call('write',{}) end,
                    function(ok,why) assert(not ok and why);answered=answered+1 end)
                assert(Jobs.advance(job) and job.done and answered==1)
                Jobs.advance(job);assert(answered==1)
            end

            return true
            """;
        Object[] result=thread.pcall(LuaCompiler.loadstring(source,"save-jobs",env),new Object[0]);
        if(result.length<2 || !Boolean.TRUE.equals(result[0]) || !Boolean.TRUE.equals(result[1]))
            throw new AssertionError("Kahlua save jobs: "+java.util.Arrays.toString(result));
        System.out.println("PASS game Kahlua save jobs: deferred checkpoints, write, cancellation, failure, exactly one callback");
    }

}
