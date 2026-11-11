package cvpbench;

import me.zed_0xff.zombie_buddy.Patch;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;
import zombie.iso.IsoWorld;
import org.lwjglx.opengl.Display;
import org.lwjgl.glfw.GLFW;
import zombie.network.GameClient;
import zombie.network.GameServer;

/** Measure completed buffer swaps, independently of the main-thread Lua loop. */
@LuaClass(name="PZTPresentedFrames")
@Patch(className="org.lwjglx.opengl.Display",methodName="swapBuffers")
public final class PresentedFrames {
    private static final long[] intervals=new long[200000];
    private static boolean active,overflow;
    private static long last;
    private static int size;
    private static int width,height,framebufferWidth,framebufferHeight;
    private static boolean fullscreen,borderless,displayValid;
    private static boolean background,lastFocused;
    private static int focusedFrames,focusChanges;
    public static boolean backgroundMode() { return Boolean.getBoolean("pztest.background"); }
    static void resetCapture() { size=0;last=0;overflow=false;displayValid=true;active=true;
        background=backgroundMode();focusedFrames=focusChanges=0; }
    public static synchronized boolean valid() { return displayValid; }
    public static synchronized void cancel() { active=false; }
    public static synchronized void begin() {
        if(GameClient.client || GameServer.server || IsoWorld.instance==null
                || !"PZT_VehicleLab".equals(IsoWorld.instance.getWorld()))
            throw new IllegalStateException("isolated proving ground required");
        resetCapture();
    }
    public static synchronized void swapped() {
        if(!active) return;
        long window=Display.getWindow();
        displayValid &= GLFW.glfwGetWindowAttrib(window,GLFW.GLFW_VISIBLE)==GLFW.GLFW_TRUE
            && GLFW.glfwGetWindowAttrib(window,GLFW.GLFW_ICONIFIED)==GLFW.GLFW_FALSE;
        captureFrame(System.nanoTime(),Display.getWidth(),Display.getHeight(),
            Display.getFramebufferWidth(),Display.getFramebufferHeight(),
            GLFW.glfwGetWindowAttrib(window,GLFW.GLFW_FOCUSED)==GLFW.GLFW_TRUE,
            Display.isFullscreen(),Display.isBorderlessWindow());
    }
    // Values come from the render thread, not options.ini or the Lua Core cache.
    static void captureFrame(long now,int w,int h,int fw,int fh,boolean focused,boolean full,boolean border) {
        if(last==0) { width=w;height=h;framebufferWidth=fw;framebufferHeight=fh;fullscreen=full;borderless=border; }
        displayValid &= w>0 && h>0 && fw>0 && fh>0 && w==width && h==height
            && fw==framebufferWidth && fh==framebufferHeight && full==fullscreen && border==borderless;
        if(last!=0) {
            if(size==intervals.length) { overflow=true;active=false;return; }
            intervals[size++]=now-last;
            if(focused) focusedFrames++;
            if(focused!=lastFocused) focusChanges++;
        }
        lastFocused=focused;
        last=now;
    }
    public static synchronized String finish() {
        active=false;
        if(overflow || size==0) throw new IllegalStateException("invalid buffer-swap capture");
        StringBuilder text=new StringBuilder("frame_ms,tick_ms,heap_mb,window_width,window_height,framebuffer_width,framebuffer_height,fullscreen,borderless,background_mode,focused_frames,focus_changes,display_valid\n");
        for(int i=0;i<size;i++) text.append(intervals[i]/1_000_000.0).append(",0,0,")
            .append(width).append(',').append(height).append(',').append(framebufferWidth).append(',').append(framebufferHeight)
            .append(',').append(fullscreen?1:0).append(',').append(borderless?1:0)
            .append(',').append(background?1:0).append(',').append(focusedFrames).append(',').append(focusChanges)
            .append(',').append(displayValid?1:0).append('\n');
        return text.toString();
    }
    @Patch.OnExit public static void afterSwap() { PresentedFrames.swapped(); }
}
