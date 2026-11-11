package cvpbench;
/** Headless checks of the same capture path used by the render-thread hook. */
public final class ValidatePresentedFrames {
    public static void main(String[] args) {
        for(boolean background:new boolean[]{false,true}) {
        System.setProperty("pztest.background",Boolean.toString(background));
        for(int change=0;change<7;change++) {
            PresentedFrames.resetCapture();
            PresentedFrames.captureFrame(1_000_000L,1280,720,2560,1440,!background,false,false);
            PresentedFrames.captureFrame(2_000_000L,change==1?1920:1280,720,change==6?0:change==2?1280:2560,1440,change==3?background:!background,change==4,change==5);
            PresentedFrames.captureFrame(3_000_000L,1280,720,2560,1440,!background,false,false);
            if(PresentedFrames.valid() != (change==0 || change==3)) throw new AssertionError("live validity");
            String[] rows=PresentedFrames.finish().split("\\n");
            if(change==3 && !rows[1].endsWith(",1,2,1")) throw new AssertionError("focus change not recorded");
            if(rows.length!=3 || !rows[0].contains("framebuffer_width")) throw new AssertionError("missing frame geometry");
            for(int i=1;i<rows.length;i++) if(!rows[i].endsWith((change==0 || change==3)?",1":",0"))
                throw new AssertionError("invalid geometry/mode or rejected focus change: "+change);
        }
        }
        System.clearProperty("pztest.background");
        BackgroundWindow.beforeShow(0); // Ordinary launches must not call GLFW.
        if(BackgroundWindow.Focus.skip()) throw new AssertionError("ordinary focus suppressed");
        System.setProperty("pztest.background","true");
        if(!BackgroundWindow.Focus.skip()) throw new AssertionError("benchmark focus not suppressed");
        System.clearProperty("pztest.background");
        System.out.println("PASS native frame capture: dimensions, DPI framebuffer, resize, focus, fullscreen and borderless transitions");
    }
}
