package cvpworld;

import se.krka.kahlua.vm.KahluaTable;

/** Cosmetic CVP_Rope.shape v4, with the same arithmetic/order and persistent numeric state.
 * Never moves a world object. Points belong to this writer, not to queued render frames. */
final class RopeShape {
    static final class Point {
        final double fraction;
        Point(double fraction) {this.fraction=fraction;}
        double x,y,z,vx,vy,vz,ox,oy,oz;
    }
    static final class State {
        Point[] points;
        boolean sleeping;
        double quiet,still,shapeLength=Double.NaN;
        boolean rotationReady;
        long angleBits;
        double cosine,sine;
    }
    static double n(KahluaTable r,String key,double fallback) {
        Object value=r.rawget(key);return value instanceof Number v?v.doubleValue():fallback;
    }
    static double n(KahluaTable r,String key,String fallbackKey,double fallback) {
        Object value=r.rawget(key);return value instanceof Number v?v.doubleValue():n(r,fallbackKey,fallback);
    }
    static double distance(double ax,double ay,double az,double bx,double by,double bz) {
        double x=ax-bx,y=ay-by,z=az-bz;return Math.sqrt(x*x+y*y+z*z);
    }
    static double common(double u,double v) {
        if(u*v<=0)return 0;return u>0?Math.min(u,v):Math.max(u,v);
    }
    static double curve(State s,double[] baseline,double nx,double ny,double bend,double[] offsets,boolean write) {
        double lx=baseline[0],ly=baseline[1],lz=baseline[2],total=0;
        for(int i=0;i<offsets.length;i++) {
            int at=i*3;
            double offset=offsets[i]*bend;
            double x=baseline[at]+nx*offset,y=baseline[at+1]+ny*offset,z=baseline[at+2];
            if(!write&&i>0)total+=distance(lx,ly,lz,x,y,z);
            if(write){Point p=new Point((double)i/(offsets.length-1));p.x=x;p.y=y;p.z=z;s.points[i]=p;}
            lx=x;ly=y;lz=z;
        }
        return total;
    }
    static void seed(State s,int segments,double angle,int slot,double length,boolean elastic,
                     double ax,double ay,double az,double bx,double by,double bz) {
        double dx=bx-ax,dy=by-ay,horizontal=Math.sqrt(dx*dx+dy*dy);
        double nx=-Math.sin(angle),ny=Math.cos(angle);
        if(horizontal>.001){nx=-dy/horizontal;ny=dx/horizontal;}
        if(slot%2==0){nx=-nx;ny=-ny;}
        // The search changes only bend. Evaluate the identical basis once per seed.
        double[] offsets=new double[segments+1];
        double[] baseline=new double[(segments+1)*3];
        for(int i=0;i<=segments;i++) {
            double t=(double)i/segments;int at=i*3;
            baseline[at]=ax+(bx-ax)*t;baseline[at+1]=ay+(by-ay)*t;baseline[at+2]=az+(bz-az)*t;
            offsets[i]=elastic?(Math.sin(2*Math.PI*t)*.75+Math.sin(Math.PI*t)*.25):Math.sin(Math.PI*t);
        }
        double low=0,high=Math.max(length,distance(ax,ay,az,bx,by,bz)),target=high;
        for(int i=0;i<18;i++) {
            double mid=(low+high)/2;
            if(curve(s,baseline,nx,ny,mid,offsets,false)>target)high=mid;else low=mid;
        }
        s.points=new Point[segments+1];
        curve(s,baseline,nx,ny,(low+high)/2,offsets,true);
        s.sleeping=false;s.quiet=0;s.still=0;
    }
    static State advance(KahluaTable r,double ax,double ay,double az,double dt,boolean chain) {
        Object previous=r.rawget("nativeShape");
        State s=previous instanceof State old?old:new State();
        double x=n(r,"x",0),y=n(r,"y",0),z=n(r,"z",0),angle=n(r,"angle",0);
        double fx=n(r,"attachLocalX","footLocalX",-.65),fy=n(r,"attachLocalY","footLocalY",0);
        long angleBits=Double.doubleToRawLongBits(angle);
        // Preserve signed zero as well as angle changes when reusing the rotation.
        if(!s.rotationReady||s.angleBits!=angleBits) {
            s.cosine=Math.cos(angle);s.sine=Math.sin(angle);
            s.angleBits=angleBits;s.rotationReady=true;
        }
        double c=s.cosine,sn=s.sine;
        double bx=x+c*fx-sn*fy,by=y+sn*fx+c*fy,bz=(z+n(r,"endHeight",.025))*3;
        az=(az+n(r,"anchorHeight",.25))*3;
        double length=n(r,"length",4),floor=(z+.025)*3;
        int segments=(int)n(r,"ropeSegments",16),passes=(int)n(r,"ropePasses",8);
        if(segments<1||segments>32||passes<1||passes>8)throw new IllegalArgumentException("invalid cosmetic rope quality");
        if(!Double.isFinite(ax+ay+az+bx+by+bz+length+dt)||length<0)
            throw new IllegalArgumentException("finite cosmetic rope parameters required");
        if(s.points==null||s.points.length!=segments+1)
            seed(s,segments,angle,(int)n(r,"slot",1),length,!chain,ax,ay,az,bx,by,bz);
        if(previous!=s)r.rawset("nativeShape",s);
        step(s,ax,ay,az,bx,by,bz,length,floor,dt,passes,!chain);
        if(Boolean.TRUE.equals(r.rawget("grounded"))){
            for(Point point:s.points){point.z=floor;point.vz=0;}
        }
        return s;
    }
    static void step(State s,double ax,double ay,double az,double bx,double by,double bz,
                     double length,double floor,double dt,int passes,boolean elastic) {
        Point[] points=s.points;int n=points.length-1;Point first=points[0],last=points[n];
        double mx=common(ax-first.x,bx-last.x),my=common(ay-first.y,by-last.y);
        if(mx!=0||my!=0)for(Point p:points){p.x+=mx;p.y+=my;}
        double moved=distance(ax,ay,az,first.x,first.y,first.z)+distance(bx,by,bz,last.x,last.y,last.z);
        if(s.sleeping&&moved<.00000001&&s.shapeLength==length)return;
        if(s.shapeLength!=length){s.still=0;s.quiet=0;s.sleeping=false;}
        s.shapeLength=length;
        if(moved>=.0001){s.sleeping=false;s.quiet=0;s.still=0;}
        double h=Math.max(0,Math.min(dt,1.0/30));
        s.still+=h;
        double sx=first.x,sy=first.y,sz=first.z,ex=last.x,ey=last.y,ez=last.z;
        if(distance(ax,ay,az,bx,by,bz)>=length-.01) {
            double decayDt=Math.max(0,Math.min(dt,.1)),keep=elastic?Math.exp(-18*decayDt):0,straighten=.9*decayDt;
            double residual=0,spanX=bx-ax,spanY=by-ay,spanZ=bz-az,oldX=ex-sx,oldY=ey-sy,oldZ=ez-sz;
            for(int i=0;i<=n;i++) {
                Point p=points[i];double t=p.fraction;
                double x=ax+spanX*t,y=ay+spanY*t,z=az+spanZ*t;
                double dx=p.x-(sx+oldX*t),dy=p.y-(sy+oldY*t),dz=p.z-(sz+oldZ*t),blend=keep;
                if(elastic){double bend=Math.sqrt(dx*dx+dy*dy+dz*dz);if(bend>0)blend=Math.max(blend,1-straighten/bend);}
                dx*=blend;dy*=blend;dz*=blend;residual=Math.max(residual,dx*dx+dy*dy+dz*dz);
                p.vx=0;p.vy=0;p.vz=0;p.x=x+dx;p.y=y+dy;p.z=Math.max(floor,z+dz);
            }
            s.sleeping=moved<.0001&&residual<.00000001;return;
        }
        if(h==0)return;
        double damping=Math.exp(-12*h),gravity=9.81*h,mz=common(az-sz,bz-ez);
        first.x=sx+(ax-sx);first.y=sy+(ay-sy);first.z=sz+(az-sz);
        last.x=ex+(bx-ex);last.y=ey+(by-ey);last.z=ez+(bz-ez);
        for(int i=1;i<n;i++) {
            Point p=points[i];p.z=Math.max(floor,p.z+mz);
            p.ox=p.x;p.oy=p.y;p.oz=p.z;
            p.x+=p.vx*damping*h;p.y+=p.vy*damping*h;p.z=Math.max(floor,p.z+(p.vz*damping-gravity)*h);
        }
        double rest=Math.max(length,distance(first.x,first.y,first.z,last.x,last.y,last.z))/n;
        for(int pass=1;pass<=passes;pass++) {
            boolean reverse=pass%2==0;
            int direction=reverse?-1:1,end=reverse?-1:n;
            for(int i=reverse?n-1:0;i!=end;i+=direction) {
                Point p=points[i],q=points[i+1];
                double dx=q.x-p.x,dy=q.y-p.y,dz=q.z-p.z,d=Math.sqrt(dx*dx+dy*dy+dz*dz);
                if(d>.000001) {
                    int wp=i==0?0:1,wq=i==n-1?0:1;double error=(d-rest)/(d*(wp+wq));
                    p.x+=dx*error*wp;p.y+=dy*error*wp;p.z=Math.max(floor,p.z+dz*error*wp);
                    q.x-=dx*error*wq;q.y-=dy*error*wq;q.z=Math.max(floor,q.z-dz*error*wq);
                }
            }
        }
        double maxSpeed2=0;
        for(int i=1;i<n;i++) {
            Point p=points[i];p.vx=(p.x-p.ox)/h;p.vy=(p.y-p.oy)/h;p.vz=(p.z-p.oz)/h;
            double speed2=p.vx*p.vx+p.vy*p.vy+p.vz*p.vz,speed=Math.sqrt(speed2);
            if(speed>35){
                p.vx=p.vx*35/speed;p.vy=p.vy*35/speed;p.vz=p.vz*35/speed;
                speed2=p.vx*p.vx+p.vy*p.vy+p.vz*p.vz;
            }
            maxSpeed2=Math.max(maxSpeed2,speed2);
        }
        s.quiet=moved<.0001&&maxSpeed2<.0004?s.quiet+h:0;
        if(s.quiet>.5||s.still>1.5&&maxSpeed2<.01){s.sleeping=true;for(Point p:points){p.vx=0;p.vy=0;p.vz=0;}}
    }
}
