import cvpbench.SkipLogos;
import zombie.gameStates.TISLogoState;
public class ValidateSkipLogos {
    public static void main(String[] args) throws Exception {
        // No graphics initialization: allocate a state to exercise only the patch fields.
        var f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);
        var unsafe=(sun.misc.Unsafe)f.get(null);
        var state=(TISLogoState)unsafe.allocateInstance(TISLogoState.class);
        state.stage=1;state.alpha=.5f;
        System.clearProperty("pztest.autoStart");SkipLogos.enter(state);
        if(state.stage!=1) throw new AssertionError("ordinary launch changed");
        System.setProperty("pztest.autoStart","true");SkipLogos.enter(state);
        if(state.stage!=3 || state.alpha!=.5f) throw new AssertionError("stock transition not preserved");
        System.out.println("PASS opt-in logo skip preserves stock fade state");
    }
}
