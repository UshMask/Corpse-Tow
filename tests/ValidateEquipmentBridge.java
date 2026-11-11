package cvpworld;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Native bridge contract check: every reflected game member used by the save
 * barriers must resolve on the installed Project Zomboid build, and the explicit
 * read/write/capability entry points must exist in the shipped classes.
 */
public final class ValidateEquipmentBridge {
    private ValidateEquipmentBridge() {}

    public static void main(String[] args) throws Exception {
        Map<String,Boolean> features=new LinkedHashMap<>();
        List<String> missing=EquipmentPersistence.capabilityProblems(features);
        if(!missing.isEmpty()) throw new AssertionError("equipment bridge misses: "+missing);
        String[] groups={"bridge","ledger","playerCheckpointMp","playerCheckpointSp",
            "squareCheckpointMp","squareCheckpointSp","skeletonLifetime","worldVersion"};
        for(String group:groups) {
            if(!Boolean.TRUE.equals(features.get(group)))
                throw new AssertionError("equipment bridge group not available: "+group+" features="+features);
        }
        for(String name:new String[]{"readEnvelope","writeEnvelope","capabilities","read","write"}) {
            boolean found=false;
            for(Method method:EquipmentPersistence.class.getDeclaredMethods())
                if(method.getName().equals(name)) { found=true; break; }
            if(!found) throw new AssertionError("equipment bridge method missing: "+name);
        }
        System.out.println("PASS ValidateEquipmentBridge groups="+features);
    }
}
