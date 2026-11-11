package cvpworld;

import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import se.krka.kahlua.vm.KahluaTable;
import me.zed_0xff.zombie_buddy.Exposer.LuaClass;

/** Batch port of the existing Lua solver. Never moves game objects or owns items. */
@LuaClass(name="CVPSolverNative")
public final class TowingSolver {
    // Per-constraint convergence tolerance in world coordinates; keep Lua fallback in sync.
    private static final double CONSTRAINT_TOLERANCE=.005;
    static double n(KahluaTable t,String k,double fallback) {Object v=t.rawget(k);return v instanceof Number?((Number)v).doubleValue():fallback;}
    static boolean yes(KahluaTable t,String k) {Object v=t.rawget(k);return v!=null&&!Boolean.FALSE.equals(v);}
    static KahluaTable table(KahluaTable t,String k) {return (KahluaTable)t.rawget(k);}
    // Explicit floor-mod, shared with Lua: Java and Kahlua both use signed %.
    static double wrap(double a) {
        double shifted=a+Math.PI;
        return shifted-Math.floor(shifted/(2*Math.PI))*(2*Math.PI)-Math.PI;
    }
    static double sliding(double vx,double vy,double h){
        double speed=Math.sqrt(vx*vx+vy*vy);
        return speed>0?Math.max(0,1-9.81*.65*h/speed):0;
    }
    static double sq(double a) {return a*a;}
    public static String version(){return "1";}
    public static SolverEnvironment begin(){return SolverEnvironment.live();}
    public static void spread(KahluaTable bucket,boolean moving,double width,double speed) {
        BodySpacing.update(bucket,moving,width,speed);
    }
    public static String check(SolverEnvironment c,double ax,double ay,double az,double bx,double by,double bz,double max) {
        return c.check(ax,ay,az,bx,by,bz,max);
    }
    public static final class State {
        boolean persistent,unconverged,fallback,fallbackStep,takeupStep,correctionOnly,recoveryStep;int recoverySteps;
        final Body[] bodies;
        final List<int[]> contacts=new ArrayList<>();
        int contactCount;
        final boolean singleChain;
        // Substep results stay native; publish the final status with candidate poses.
        int gap;
        double gapX,gapY,gapZ,residual,threeH;int iterations;
        // Stage 2 scratch for the measured tether shared by the residual pair.
        // Rewritten before every use; no allocation and no lifetime past its call.
        double mD,mNx,mNy,mG,mGp,mUsed,mParentUsed;
        // Opt-in aggregated workload counters (group.solverCounters). Bounded
        // scalars only; increments are skipped entirely when disabled.
        boolean counters;int cSubsteps,cIterations,cConstraintCalls,cInnerSearch,cFallbacks;
        String obstruction;
        void contact(int i,int j){
            if(contactCount==contacts.size())contacts.add(new int[]{i,j});
            else {int[] pair=contacts.get(contactCount);pair[0]=i;pair[1]=j;}
            contactCount++;
        }
        State(KahluaTable records) {
            bodies=new Body[records.len()];var ids=new IdentityHashMap<KahluaTable,Integer>();
            for(int i=0;i<bodies.length;i++){KahluaTable t=(KahluaTable)records.rawget(i+1);bodies[i]=new Body(t);ids.put(t,i);}
            for(Body b:bodies){Integer p=ids.get(table(b.t,"parent"));b.parent=p==null?-1:p;}
            boolean same=true;
            for(int i=0;i<bodies.length;i++){
                Body b=bodies[i];b.chainRoot=b.parent<0?i:bodies[b.parent].chainRoot;
                if(b.chainRoot!=0)same=false;
            }
            singleChain=same;
        }
    }
    static final class Body {
        final KahluaTable t;final double[][] footprint;final double radius,fx,fy,pfx,pfy;int parent,chainRoot;
        double x,y,z,angle,vx,vy,ax,ay,takeup,length,height,pushX,pushY,mass,loadMass,maxGap,sx,sy,sz;
        double physicalVX,physicalVY,physicalW,fallbackDX,fallbackDY;boolean correctionStep;
        double tensionLambda,hardLambda,reaction,angularVelocity,px,py,pa,weight,inertia,limit,allowance;
        double spreadSpeed,spreadPush,spreadNX,spreadNY,spreadRemaining,spreadOffset,spreadScale;
        // Candidate-pose trig for cx/cy and child source reads. Kept apart from the
        // original-angle trig: a candidate turn must never invalidate the fixed
        // source geometry, and the fixed source geometry must not hide a turn.
        double paTrig=Double.NaN,cosPa,sinPa;
        void updatePaTrig(){if(paTrig!=pa){cosPa=Math.cos(pa);sinPa=Math.sin(pa);paTrig=pa;}}
        // Corrections change angles in-place; refresh lazily for either endpoint.
        double trigAngle=Double.NaN,cosAngle,sinAngle;
        void updateTrig(double angle){
            if(trigAngle!=angle){cosAngle=Math.cos(angle);sinAngle=Math.sin(angle);trigAngle=angle;}
        }
        // Stage 2 cache: values fixed for one substep's iterative solve. initSubstep
        // rebuilds them from the anchored source state; they never cross substeps.
        double oldFootX,oldFootY,oldDistance,substepWeight,parentInertia,alphaSoft,gammaSoft;
        double anchorVX,anchorVY,anchorSpeed;
        void initSubstep(){
            updateTrig(angle);
            oldFootX=x+cosAngle*fx-sinAngle*fy;oldFootY=y+sinAngle*fx+cosAngle*fy;
            oldDistance=Math.sqrt(sq(oldFootX-ax)+sq(oldFootY-ay));
        }
        final SolverEnvironment.Tile[] sweepFrom,sweepTo;
        boolean constraint,taut,blocked,failed,connected,elastic;String ropeBlocked;
        boolean initialized,savedConstraint,checkpointReady;
        double savedVX,savedVY,savedAngularVelocity,savedTakeup;
        int root,rank;boolean driven;
        Body(KahluaTable t) {
            this.t=t;fx=n(t,"attachLocalX",n(t,"footLocalX",-.65));fy=n(t,"attachLocalY",n(t,"footLocalY",0));
            radius=n(t,"footprintRadius",.87);KahluaTable fp=table(t,"footprint");
            footprint=new double[fp.len()][2];
            sweepFrom=new SolverEnvironment.Tile[footprint.length];sweepTo=new SolverEnvironment.Tile[footprint.length];
            for(int i=0;i<footprint.length;i++){var p=(KahluaTable)fp.rawget(i+1);footprint[i][0]=n(p,"x",0);footprint[i][1]=n(p,"y",0);}
            KahluaTable p=table(t,"sourcePose");pfx=p==null?0:n(p,"attachLocalX",n(p,"footLocalX",-.65));pfy=p==null?0:n(p,"attachLocalY",n(p,"footLocalY",0));
        }
        void resets() {
            if(yes(t,"nativeResetMotion")){vx=0;vy=0;angularVelocity=0;t.rawset("nativeResetMotion",null);}
            if(yes(t,"nativeResetConstraint")){constraint=false;t.rawset("nativeResetConstraint",null);}
        }
        void read(boolean persistent) {
            spreadSpeed=n(t,"spreadSpeed",0);spreadPush=n(t,"spreadPush",0);
            spreadNX=n(t,"spreadNX",0);spreadNY=n(t,"spreadNY",0);
            spreadRemaining=n(t,"spreadRemaining",Double.POSITIVE_INFINITY);
            spreadOffset=n(t,"spreadOffset",Double.NaN);spreadScale=n(t,"spreadScale",1);
            if(!persistent || !initialized) {
                angularVelocity=n(t,"angularVelocity",0);vx=n(t,"vx",0);vy=n(t,"vy",0);
                takeup=n(t,"takeup",Double.NaN);constraint=yes(t,"ropeConstraintReady");
            }
            if(persistent)resets();
            else {t.rawset("nativeResetMotion",null);t.rawset("nativeResetConstraint",null);}
            initialized=true;
            if(persistent){
                savedVX=vx;savedVY=vy;savedAngularVelocity=angularVelocity;savedTakeup=takeup;savedConstraint=constraint;
                checkpointReady=true;
            }
            x=n(t,"x",0);y=n(t,"y",0);z=n(t,"z",0);angle=n(t,"angle",0);
            ax=n(t,"ax",Double.NaN);ay=n(t,"ay",Double.NaN);
            length=n(t,"length",4);height=n(t,"anchorHeight",.25);
            mass=n(t,"mass",0);loadMass=n(t,"loadMass",0);maxGap=n(t,"maxGapSquared",100);
            failed=yes(t,"failed");elastic=yes(t,"nativeElastic");taut=false;blocked=false;ropeBlocked=null;
            var source=table(t,"sourceSample");if(source!=null){sx=n(source,"x",0);sy=n(source,"y",0);sz=n(source,"z",0);}
        }
        void writeHistory() {
            t.rawset("angularVelocity",angularVelocity);t.rawset("vx",vx);t.rawset("vy",vy);
            t.rawset("takeup",Double.isNaN(takeup)?null:takeup);t.rawset("ropeConstraintReady",constraint?true:null);
        }
        void read() {read(false);}
        void write(boolean persistent) {
            if(Double.isFinite(spreadRemaining))t.rawset("spreadRemaining",spreadRemaining);
            if(!persistent)writeHistory();
            t.rawset("x",x);t.rawset("y",y);t.rawset("angle",angle);
            t.rawset("ax",Double.isNaN(ax)?null:ax);t.rawset("ay",Double.isNaN(ay)?null:ay);
            t.rawset("taut",taut);t.rawset("blocked",blocked);t.rawset("ropeBlocked",ropeBlocked);
            t.rawset("loadMass",loadMass);t.rawset("loadConnected",connected);
            // Native substeps own contact forces. Lua's separate() recreates them
            // before using its solver; only the legacy API publishes these fields.
            if(!persistent){t.rawset("pushX",pushX);t.rawset("pushY",pushY);}
        }
        double footX(double px){updateTrig(angle);return px+cosAngle*fx-sinAngle*fy;}
        double footY(double py){updateTrig(angle);return py+sinAngle*fx+cosAngle*fy;}
    }
    public static State prepare(KahluaTable records) {return new State(records);}
    /** Publish history only when changing ownership/topology, never every successful tick. */
    public static void release(State s) {
        if(!s.persistent)return;
        for(Body b:s.bodies)if(b.initialized){b.resets();b.writeHistory();b.initialized=false;}
        s.persistent=false;
    }
    public static double solvePersistent(State s,SolverEnvironment environment,KahluaTable group,int steps,double h,
                                         double startX,double startY,double rootX,double rootY) {
        s.persistent=true;
        for(Body b:s.bodies)b.checkpointReady=false;
        try {return solveInternal(s,environment,group,steps,h,startX,startY,rootX,rootY);}
        catch(RuntimeException|Error failure) {
            // The candidate did not finish publishing. Restore history from before
            // calculation so Lua recovery never inherits a partially solved timestep.
            for(Body b:s.bodies)if(b.checkpointReady){
                b.vx=b.savedVX;b.vy=b.savedVY;b.angularVelocity=b.savedAngularVelocity;
                b.takeup=b.savedTakeup;b.constraint=b.savedConstraint;
            }
            release(s);throw failure;
        }
    }
    static void separate(State s) {
        s.contactCount=0;Body[] a=s.bodies;for(Body b:a){b.pushX=0;b.pushY=0;}
        if(s.singleChain)return;
        for(int i=0;i<a.length-1;i++)for(int j=i+1;j<a.length;j++) {
            Body u=a[i],v=a[j];if(u.chainRoot==v.chainRoot||u.failed||v.failed||Math.floor(u.z)!=Math.floor(v.z))continue;
            double dx=u.x-v.x,dy=u.y-v.y,d=Math.sqrt(dx*dx+dy*dy);
            if(d<1.1){s.contact(i,j);if(d<.001){dx=-Math.sin(u.angle);dy=Math.cos(u.angle);}else{dx/=d;dy/=d;}
                double force=45*(1.1-d);u.pushX+=dx*force;u.pushY+=dy*force;v.pushX-=dx*force;v.pushY-=dy*force;}
        }
        for(Body b:a){double f=Math.sqrt(b.pushX*b.pushX+b.pushY*b.pushY);if(f>60){b.pushX=b.pushX*60/f;b.pushY=b.pushY*60/f;}}
    }
    static double[] step(Body r,double ax,double ay,double az,double dt) {
        double x=r.x,y=r.y;if(dt<=0)return new double[]{x,y};
        int count=Math.max(1,(int)Math.ceil(dt*100-1e-9));double h=dt/count;
        double height=(az+r.height-r.z-.025)*3,reach=Math.sqrt(Math.max(.01,r.length*r.length-height*height));
        double stretched=r.length+Math.min(.25,r.length*.05);
        double allowance=r.elastic?Math.sqrt(Math.max(.01,stretched*stretched-height*height))-reach:0;
        double avx=(ax-r.ax)/dt,avy=(ay-r.ay)/dt;
        if(!r.constraint){r.takeup=Math.max(reach,Math.sqrt(sq(r.ax-r.footX(x))+sq(r.ay-r.footY(y))));r.constraint=true;}
        r.taut=false;r.reaction=0;
        for(int i=1;i<=count;i++) {
            double tx=r.ax+(ax-r.ax)*i/count,ty=r.ay+(ay-r.ay)*i/count,ox=x,oy=y;
            r.vx+=r.pushX*h;r.vy+=r.pushY*h;
            double friction=sliding(r.vx,r.vy,h);r.vx*=friction;r.vy*=friction;
            x+=r.vx*h;y+=r.vy*h;
            double dx=tx-r.footX(x),dy=ty-r.footY(y),d=Math.sqrt(dx*dx+dy*dy);
            r.correctionStep|=r.takeup>reach;
            r.takeup=Math.max(reach,(Double.isNaN(r.takeup)?reach:r.takeup)-2*h);
            boolean stepTaut=d>r.takeup;
            if(stepTaut) {
                double wanted=Math.atan2(ty-y,tx-x)-Math.atan2(r.fy,r.fx),delta=wrap(wanted-r.angle);
                r.angle+=Math.max(-3*h,Math.min(3*h,delta));dx=tx-r.footX(x);dy=ty-r.footY(y);d=Math.sqrt(dx*dx+dy*dy);
                if(d>r.takeup) {
                    double excess=d-r.takeup,pull=excess;
                    if(r.elastic){double relative=((avx-r.vx)*dx+(avy-r.vy)*dy)/d;
                        pull=Math.max(0,(180*h*h*excess+24*h*h*relative)/(1+24*h+180*h*h));
                        pull=Math.min(excess,Math.max(pull,excess-allowance));}
                    double travel=Math.sqrt(avx*avx+avy*avy);
                    if(travel>.02)r.reaction+=Math.max(0,r.mass)*pull/(h*h)*Math.max(0,(dx*avx+dy*avy)/(d*travel))/count;
                    double correction=pull/d;x+=dx*correction;y+=dy*correction;
                    dx*=1-correction;dy*=1-correction;d-=pull;

                }
                r.vx=(x-ox)/h;r.vy=(y-oy)/h;r.taut=true;
            }
            if(stepTaut&&r.spreadSpeed>0&&(x!=ox||y!=oy)){
                if(d>0){
                double travel=Math.sqrt(sq(x-ox)+sq(y-oy));
                double push=r.spreadPush;
                if(!Double.isNaN(r.spreadOffset)){
                    double remaining=r.spreadOffset+(tx-x)*r.spreadNX+(ty-y)*r.spreadNY;
                    push=remaining/r.spreadScale;r.spreadRemaining=Math.abs(remaining);
                }
                double shift=Math.max(-1,Math.min(1,push))*Math.min(travel,r.spreadSpeed*(h+2*travel));
                shift*=(-dy*r.spreadNX+dx*r.spreadNY)/d;
                // Bound the remaining correction, including inertial motion.
                shift=Math.max(-r.spreadRemaining,Math.min(r.spreadRemaining,shift));
                r.spreadRemaining=Math.max(0,r.spreadRemaining-Math.abs(shift));
                double scale=d/Math.sqrt(d*d+shift*shift);
                double sideX=(-dx-dy/d*shift)*scale+dx;
                double sideY=(-dy+dx/d*shift)*scale+dy;
                x+=sideX;y+=sideY;
                }
            }
        }
        r.ax=ax;r.ay=ay;return new double[]{x,y};
    }
    record Pose(double x,double y,double a,boolean blocked) {}
    static void pose(Body b,SolverEnvironment e,double x,double y,double a,SolverEnvironment.Tile[] cells) {
        double c=Math.cos(a),s=Math.sin(a);
        for(int i=0;i<cells.length;i++){var p=b.footprint[i];cells[i]=e.tile((int)Math.floor(x+c*p[0]-s*p[1]),(int)Math.floor(y+s*p[0]+c*p[1]),(int)Math.floor(b.z));}
    }
    static Pose sweep(Body b,SolverEnvironment e,double x,double y,double a,double bx,double by,double ba) {
        double da=wrap(ba-a),travel=Math.sqrt(sq(bx-x)+sq(by-y))+b.radius*Math.abs(da);
        int count=Math.max(1,(int)Math.ceil(travel/.15));var previous=b.sweepFrom;var cells=b.sweepTo;
        try {
        pose(b,e,x,y,a,previous);double lx=x,ly=y,la=a;
        for(int step=1;step<=count;step++) {
            double f=(double)step/count,px=x+(bx-x)*f,py=y+(by-y)*f,pa=a+da*f;pose(b,e,px,py,pa,cells);
            for(int i=0;i<cells.length;i++)if(!e.passage(previous[i],cells[i])||(i>=3&&!e.passage(cells[i-3],cells[i]))
                ||(i%3!=0&&!e.passage(cells[i-1],cells[i])))return new Pose(lx,ly,la,true);
            lx=px;ly=py;la=pa;var swap=previous;previous=cells;cells=swap;
        }
        return new Pose(lx,ly,la,false);
        } finally {
            // Buffers survive ticks, but references to a tick's world cache must not.
            java.util.Arrays.fill(b.sweepFrom,null);java.util.Arrays.fill(b.sweepTo,null);
        }
    }
    static double score(Pose p,double x,double y){return sq(x-p.x)+sq(y-p.y);}
    static Pose resolve(Body b,SolverEnvironment e,double tx,double ty,double angle,double old) {
        double turn=wrap(angle-old);
        if(Math.abs(tx-b.x)+Math.abs(ty-b.y)+Math.abs(turn)<.000001)return new Pose(b.x,b.y,old,false);
        int minX=(int)Math.floor(Math.min(b.x,tx)-b.radius),maxX=(int)Math.floor(Math.max(b.x,tx)+b.radius);
        int minY=(int)Math.floor(Math.min(b.y,ty)-b.radius),maxY=(int)Math.floor(Math.max(b.y,ty)+b.radius);
        if((maxX-minX+1)*(maxY-minY+1)<=64&&e.region(minX,maxX,minY,maxY,(int)Math.floor(b.z)))return new Pose(tx,ty,old+turn,false);
        Pose p=sweep(b,e,b.x,b.y,old,tx,ty,angle);if(!p.blocked)return p;
        if(Math.abs(turn)>.000001){Pose q=sweep(b,e,b.x,b.y,old,tx,ty,old);if(score(q,tx,ty)<score(p,tx,ty))p=q;}
        Pose s=sweep(b,e,p.x,p.y,p.a,tx,p.y,p.a),u=sweep(b,e,p.x,p.y,p.a,p.x,ty,p.a);
        if(score(s,tx,ty)<score(p,tx,ty))p=s;if(score(u,tx,ty)<score(p,tx,ty))p=u;
        return new Pose(p.x,p.y,p.a,true);
    }
    static int root(Body[] b,int i){while(b[i].root!=i){b[i].root=b[b[i].root].root;i=b[i].root;}return i;}
    static void join(Body[] b,int i,int j){i=root(b,i);j=root(b,j);if(i==j)return;if(b[i].rank<b[j].rank){int t=i;i=j;j=t;}b[j].root=i;if(b[i].rank==b[j].rank)b[i].rank++;}
    static void connect(State s) {
        Body[] a=s.bodies;
        if(s.contactCount==0){for(Body b:a)b.connected=b.taut&&!b.failed&&(b.parent<0||a[b.parent].connected);return;}
        for(int i=0;i<a.length;i++){a[i].root=i;a[i].rank=0;a[i].driven=false;}
        for(int i=0;i<a.length;i++){Body b=a[i];if(b.parent>=0&&b.taut&&!b.failed&&!a[b.parent].failed)join(a,i,b.parent);}
        for(int i=0;i<s.contactCount;i++){var pair=s.contacts.get(i);if(!a[pair[0]].failed&&!a[pair[1]].failed)join(a,pair[0],pair[1]);}
        for(int i=0;i<a.length;i++)if(a[i].parent<0&&a[i].taut&&!a[i].failed)a[root(a,i)].driven=true;
        for(int i=0;i<a.length;i++)a[i].connected=!a[i].failed&&a[root(a,i)].driven;
    }
    static double cx(Body b){b.updatePaTrig();return b.px+b.cosPa*b.fx-b.sinPa*b.fy;}
    static double cy(Body b){b.updatePaTrig();return b.py+b.sinPa*b.fx+b.cosPa*b.fy;}
    static double sx(Body b,int i,Body[] a,double rx){
        if(i==0)return rx;if(b.parent<0)return b.sx;Body p=a[b.parent];
        p.updatePaTrig();return p.px+p.cosPa*b.pfx-p.sinPa*b.pfy;
    }
    static double sy(Body b,int i,Body[] a,double ry){
        if(i==0)return ry;if(b.parent<0)return b.sy;Body p=a[b.parent];
        p.updatePaTrig();return p.py+p.sinPa*b.pfx+p.cosPa*b.pfy;
    }
    static double boundedTurn(double used,double requested,double threeH){
        return Math.max(-threeH,Math.min(threeH,used+requested))-used;
    }
    // Measures one tether's source/candidate geometry into solver scratch. The
    // residual sweep evaluates soft and hard from this single measurement because
    // neither read moves a pose; apply calls always re-measure because the
    // previous apply may have turned this body or its parent.
    static boolean measure(State s,Body b,Body p,int i,double rx,double ry){
        double x=sx(b,i,s.bodies,rx),y=sy(b,i,s.bodies,ry),fx=cx(b),fy=cy(b);
        double dx=fx-x,dy=fy-y,d=Math.sqrt(dx*dx+dy*dy);
        if(d<1e-9)return false;
        s.mD=d;s.mNx=dx/d;s.mNy=dy/d;
        s.mG=(fx-b.px)*s.mNy-(fy-b.py)*s.mNx;
        s.mGp=p==null?0:(x-p.px)*s.mNy-(y-p.py)*s.mNx;
        s.mUsed=wrap(b.pa-b.angle);s.mParentUsed=p==null?0:wrap(p.pa-p.angle);
        return true;
    }
    // Evaluates one tether from the measurement above. Positive lambda pulls
    // endpoints together. Its accumulated value cannot push.
    static double tetherSolve(State s,Body b,Body p,double h,boolean hard,boolean apply){
        double d=s.mD,nx=s.mNx,ny=s.mNy,g=s.mG,gp=s.mGp,used=s.mUsed,parentUsed=s.mParentUsed;
        double w=b.substepWeight,ip=b.parentInertia,threeH=s.threeH;
        double alpha=hard?0:b.alphaSoft,gamma=hard?0:b.gammaSoft;
        double lambda=hard?b.hardLambda:b.tensionLambda;
        // Damping measures change of tether length. Projecting endpoint travel
        // on the NEW normal falsely damps pure rotation at constant length.
        // d-oldDistance also has the normal derivative assumed by (1+gamma).
        double displacement=d-b.oldDistance;
        double residual=d-(hard?b.limit:b.takeup)+gamma*displacement-alpha*lambda;
        double amount=Math.max(-lambda,residual/((1+gamma)*(w+b.inertia*g*g+ip*gp*gp)+alpha));
        // Most steps do not hit the turn bounds: the linear solve is exact there.
        if(Math.abs(used-amount*b.inertia*g)>threeH||Math.abs(parentUsed+amount*ip*gp)>threeH){
            if(s.counters)s.cInnerSearch++;
            double low=Math.max(-lambda,Math.min(0,residual/((1+gamma)*w+alpha)));
            double high=Math.max(0,residual/((1+gamma)*w+alpha));
            for(int k=0;k<28;k++){
                double q=(low+high)*.5;
                double closure=w*q-g*boundedTurn(used,-q*b.inertia*g,threeH)+gp*boundedTurn(parentUsed,q*ip*gp,threeH);
                if((1+gamma)*closure+alpha*q<residual)low=q;else high=q;
            }
            amount=(low+high)*.5;
        }
        double turn=boundedTurn(used,-amount*b.inertia*g,threeH),pt=boundedTurn(parentUsed,amount*ip*gp,threeH);
        double error=Math.abs(w*amount-g*turn+gp*pt);
        if(!apply)return error;
        if(hard)b.hardLambda=Math.max(0,lambda+amount);else b.tensionLambda=Math.max(0,lambda+amount);
        b.px-=nx*amount*b.weight;b.py-=ny*amount*b.weight;b.pa+=turn;
        if(p!=null){p.px+=nx*amount*p.weight;p.py+=ny*amount*p.weight;p.pa+=pt;}
        else {
            // Anchored source and ax/ay are fixed for this substep: reuse them.
            double vx=b.anchorVX,vy=b.anchorVY,speed=b.anchorSpeed;
            if(speed>.02)b.reaction+=amount/(h*h)*Math.max(0,-(nx*vx+ny*vy)/speed);
        }
        return error;
    }
    static double tether(State s,int i,double rx,double ry,double h,boolean hard){
        Body b=s.bodies[i],p=b.parent<0?null:s.bodies[b.parent];
        if(hard&&b.allowance<=0)return 0;
        if(!measure(s,b,p,i,rx,ry))return 0;
        if(s.counters)s.cConstraintCalls++;
        return tetherSolve(s,b,p,h,hard,true);
    }
    /** Coupled reactions prevent internal contacts from driving kinematic parents. */
    static void coupled(State s,SolverEnvironment environment,double rx,double ry,double h){
        Body[] a=s.bodies;double friction=Math.exp(-4*h);
        s.threeH=3*h;
        s.gap=0;s.obstruction=null;s.fallbackStep=false;s.takeupStep=false;
        for(Body b:a){b.px=b.x;b.py=b.y;b.pa=b.angle;b.weight=1/Math.max(1,b.mass);
            b.inertia=2*b.weight/(b.radius*b.radius);b.tensionLambda=0;b.hardLambda=0;b.reaction=0;b.taut=false;b.blocked=false;b.ropeBlocked=null;}
        for(int i=0;i<a.length;i++){
            Body b=a[i];double x=sx(b,i,a,rx),y=sy(b,i,a,ry),z=b.parent<0?b.sz:a[b.parent].z+.025;
            if(Math.floor(z)!=Math.floor(b.z)||sq(x-b.x)+sq(y-b.y)>b.maxGap){
                s.gap=i+1;s.gapX=x;s.gapY=y;s.gapZ=z;return;
            }
            double height=(z+b.height-b.z-.025)*3,reach=Math.sqrt(Math.max(.01,b.length*b.length-height*height));
            if(Double.isNaN(b.ax))b.ax=x;if(Double.isNaN(b.ay))b.ay=y;
            double stretched=b.length+Math.min(.25,b.length*.05);
            b.allowance=b.elastic?Math.sqrt(Math.max(.01,stretched*stretched-height*height))-reach:0;
            if(!b.constraint){b.takeup=Math.max(reach,Math.sqrt(sq(x-cx(b))+sq(y-cy(b))));b.constraint=true;}
            boolean takingUp=b.takeup>reach;s.takeupStep|=takingUp;s.recoveryStep|=takingUp;
            b.takeup=Math.max(reach,(Double.isNaN(b.takeup)?reach:b.takeup)-2*h);b.limit=b.takeup+b.allowance;
            // Stage 2: anchors/poses are now final for this substep's iterative
            // solve. Rebuild the fixed geometry here; never carry it across steps.
            b.initSubstep();
            Body parent=b.parent<0?null:a[b.parent];
            b.substepWeight=b.weight+(parent==null?0:parent.weight);
            b.parentInertia=parent==null?0:parent.inertia;
            b.alphaSoft=b.allowance>0?b.substepWeight/(180*h*h):0;
            b.gammaSoft=b.alphaSoft>0?24/(180*h):0;
            if(b.parent<0){b.anchorVX=(x-b.ax)/h;b.anchorVY=(y-b.ay)/h;
                b.anchorSpeed=Math.sqrt(b.anchorVX*b.anchorVX+b.anchorVY*b.anchorVY);}
        }
        for(Body b:a){double vx=b.vx+b.pushX*h,vy=b.vy+b.pushY*h,slide=sliding(vx,vy,h);
            b.physicalVX=vx*slide;b.physicalVY=vy*slide;
            b.physicalW=Math.max(-3,Math.min(3,b.angularVelocity*friction));
            b.px+=b.physicalVX*h;b.py+=b.physicalVY*h;b.pa+=b.physicalW*h;}
        double tolerance=Math.min(CONSTRAINT_TOLERANCE*.5,.001*h);
        boolean converged=false;
        for(int iteration=0;iteration<256;iteration++){
            // Alternate sweep direction: a tail correction must propagate back
            // toward the root, not always wait for the next forward sweep.
            for(int j=0;j<a.length;j++){int i=iteration%2==0?j:a.length-1-j;
                tether(s,i,rx,ry,h,false);tether(s,i,rx,ry,h,true);}
            double error=0;
            // Inspect the final configuration, after every neighbour has moved.
            // Both reads see the same poses, so they share one measurement; the
            // soft and hard formulas stay separate and the max order is unchanged.
            for(int i=0;i<a.length;i++){
                Body b=a[i],p=b.parent<0?null:a[b.parent];
                if(!measure(s,b,p,i,rx,ry))continue;
                if(s.counters)s.cConstraintCalls++;
                double soft=tetherSolve(s,b,p,h,false,false);
                double hardError=0;
                if(b.allowance>0){
                    if(s.counters)s.cConstraintCalls++;
                    hardError=tetherSolve(s,b,p,h,true,false);
                }
                error=Math.max(error,Math.max(soft,hardError));
            }
            s.residual=error;s.iterations=Math.max(s.iterations,iteration+1);
            if(s.counters)s.cIterations++;
            if(error<tolerance){converged=true;break;}
        }
        if(!converged){
            if(s.counters)s.cFallbacks++;
            // Bounded degraded solve. Restore the free prediction, then project
            // outward in parent order; children cannot invalidate an earlier rope.
            s.fallback=true;s.fallbackStep=true;s.recoveryStep=true;
            for(Body b:a){
                b.px=b.x+b.physicalVX*h;b.py=b.y+b.physicalVY*h;
                b.pa=b.angle+b.physicalW*h;
                b.reaction=0;b.tensionLambda=0;b.hardLambda=0;
            }
            for(int i=0;i<a.length;i++){
                Body b=a[i];double x=sx(b,i,a,rx),y=sy(b,i,a,ry),dx=cx(b)-x,dy=cy(b)-y,d=Math.sqrt(dx*dx+dy*dy);
                double pull=Math.max(0,d-b.limit);
                if(pull>0){
                    double amount=pull/b.weight;b.hardLambda=amount;
                    b.px-=dx/d*pull;b.py-=dy/d*pull;
                    if(b.parent<0){double vx=(x-b.ax)/h,vy=(y-b.ay)/h,speed=Math.sqrt(vx*vx+vy*vy);
                        if(speed>.02)b.reaction=amount/(h*h)*Math.max(0,-(dx*vx+dy*vy)/(d*speed));}
                }
            }
        }
        for(Body b:a){b.taut=b.tensionLambda+b.hardLambda>0;b.reaction=Math.max(0,b.reaction);}
        // A stopped body remains at rest under a sub-threshold spring force.
        for(Body b:a){
            double dx=b.px-b.x,dy=b.py-b.y,limit=9.81*.65*h*h;
            if(b.physicalVX==0&&b.physicalVY==0&&dx*dx+dy*dy<limit*limit){b.px=b.x;b.py=b.y;}
        }
        for(int i=0;i<a.length;i++){
            Body b=a[i];Pose pose=resolve(b,environment,b.px,b.py,b.pa,b.angle);
            double x=sx(b,i,a,rx),y=sy(b,i,a,ry),z=b.parent<0?b.sz:a[b.parent].z+.025;
            String why=environment.check(x,y,z,cx(b),cy(b),b.z,b.length+6);
            if(pose.blocked||why!=null){s.obstruction=why!=null?why:SolverEnvironment.BLOCKED;
                for(Body r:a){r.vx=0;r.vy=0;r.angularVelocity=0;r.blocked=true;r.taut=false;}return;}
        }
        for(int i=0;i<a.length;i++){
            Body b=a[i];b.fallbackDX=b.px-b.x;b.fallbackDY=b.py-b.y;
            b.vx=(b.px-b.x)/h;b.vy=(b.py-b.y)/h;b.angularVelocity=wrap(b.pa-b.angle)/h;
            b.x=b.px;b.y=b.py;b.angle=b.pa;b.ax=sx(b,i,a,rx);b.ay=sy(b,i,a,ry);
        }
    }
    /** Publishes only candidate record fields; Lua validates and commits original bodies. */
    public static double solve(State s,SolverEnvironment environment,KahluaTable group,int steps,double h,
            double startX,double startY,double rootX,double rootY) {
        release(s);
        return solveInternal(s,environment,group,steps,h,startX,startY,rootX,rootY);
    }
    private static double solveInternal(State s,SolverEnvironment environment,KahluaTable group,int steps,double h,
            double startX,double startY,double rootX,double rootY) {
        s.gap=0;s.obstruction=null;s.unconverged=false;s.fallback=false;s.residual=0;s.iterations=0;s.correctionOnly=yes(group,"correctionOnly");s.recoverySteps=0;
        // Opt-in aggregated counters: increments are skipped when the caller does
        // not ask for them, and the published scalars stay bounded.
        s.counters=yes(group,"solverCounters");
        s.cSubsteps=s.cIterations=s.cConstraintCalls=s.cInnerSearch=s.cFallbacks=0;
        for(Body b:s.bodies)b.read(s.persistent);double accumulated=0;
        outer:for(int step=1;step<=steps;step++) {
            if(s.counters)s.cSubsteps++;
            separate(s);
            s.recoveryStep=s.correctionOnly;
            // The coupled predictor fills this scratch in its existing body pass.
            if(s.bodies.length==1){Body b=s.bodies[0];
                double vx=b.vx+b.pushX*h,vy=b.vy+b.pushY*h,slide=sliding(vx,vy,h);
                b.physicalVX=vx*slide;b.physicalVY=vy*slide;
                b.physicalW=Math.max(-3,Math.min(3,b.angularVelocity*Math.exp(-4*h)));
                b.correctionStep=false;
            }
            if(s.bodies.length>1){
                coupled(s,environment,startX+(rootX-startX)*step/steps,startY+(rootY-startY)*step/steps,h);
                if(s.gap>0||s.obstruction!=null||s.unconverged)break;
            } else {
            for(int i=0;i<s.bodies.length;i++) {
                Body r=s.bodies[i];double sx=r.sx,sy=r.sy,sz=r.sz;
                if(r.parent>=0){Body p=s.bodies[r.parent];sx=p.x+Math.cos(p.angle)*r.pfx-Math.sin(p.angle)*r.pfy;
                    sy=p.y+Math.sin(p.angle)*r.pfx+Math.cos(p.angle)*r.pfy;sz=p.z+.025;}
                if(i==0){sx=startX+(rootX-startX)*step/steps;sy=startY+(rootY-startY)*step/steps;}
                if(Math.floor(sz)!=Math.floor(r.z)||sq(sx-r.x)+sq(sy-r.y)>r.maxGap){s.gap=i+1;s.gapX=sx;s.gapY=sy;s.gapZ=sz;break outer;}
                if(Double.isNaN(r.ax))r.ax=sx;if(Double.isNaN(r.ay))r.ay=sy;
                double old=r.angle;double[] candidate=step(r,sx,sy,sz,h);Pose p=resolve(r,environment,candidate[0],candidate[1],r.angle,old);
                r.angle=p.a;r.blocked=p.blocked;
                r.ropeBlocked=environment.check(sx,sy,sz,r.footX(p.x),r.footY(p.y),r.z,r.length+6);
                double x=p.x,y=p.y;
                if(r.ropeBlocked!=null){x=r.x;y=r.y;r.angle=old;r.blocked=true;r.taut=false;}
                if(r.blocked){r.vx=0;r.vy=0;}r.x=x;r.y=y;
                if(r.ropeBlocked!=null){s.obstruction=r.ropeBlocked;break outer;}
                if(r.blocked&&r.taut){s.obstruction=SolverEnvironment.BLOCKED;break outer;}
                r.ax=sx;r.ay=sy;
            }
            }
            if(s.bodies.length==1)s.recoveryStep|=s.bodies[0].correctionStep;
            if(s.recoveryStep){
                s.recoverySteps++;
                for(Body b:s.bodies){
                    // Recovery must not restore a velocity rejected by collision.
                    b.vx=b.blocked?0:b.physicalVX;b.vy=b.blocked?0:b.physicalVY;
                    b.angularVelocity=b.blocked?0:b.physicalW;b.reaction=0;
                }
            }
            connect(s);
            double fallbackMass=Double.NaN;
            if(s.fallbackStep&&!s.correctionOnly&&!s.takeupStep){
                double dx=(rootX-startX)/steps,dy=(rootY-startY)/steps,distance2=dx*dx+dy*dy;
                if(distance2>sq(.02*h)){
                    // Work-equivalent sliding friction; no acceleration impulse
                    // is inferred from a nonconverged constraint solve.
                    fallbackMass=0;
                    for(Body b:s.bodies)if(b.connected){
                        double travel=(b.fallbackDX*dx+b.fallbackDY*dy)/distance2;
                        fallbackMass+=b.mass*Math.max(0,Math.min(1,travel));
                    }
                }
            }
            // Equivalent mass encodes resistance force in newtons / (g * mu).
            for(Body r:s.bodies){r.loadMass=r.parent<0?(!Double.isNaN(fallbackMass)?fallbackMass:r.reaction/(9.81*.65)):0;accumulated+=r.loadMass/steps;}
        }
        for(Body b:s.bodies)b.write(s.persistent);
        group.rawset("nativeUnconverged",s.unconverged);
        group.rawset("nativeFallback",s.fallback);group.rawset("recoverySteps",(double)s.recoverySteps);
        group.rawset("solverResidual",s.residual);group.rawset("solverIterations",(double)s.iterations);
        // Opt-in workload counters shared with the Lua backend. Nothing is
        // written when disabled, so the default group output is unchanged.
        if(s.counters){
            group.rawset("solverBackend",s.persistent?"java-persistent":"java-nonpersistent");
            group.rawset("solverSubsteps",(double)s.cSubsteps);
            group.rawset("solverConstraintCalls",(double)s.cConstraintCalls);
            group.rawset("solverIterationsTotal",(double)s.cIterations);
            // Match the Lua backend: fixed 28-sample search passes as work and
            // limit hits (search entries) as the count of entered searches.
            group.rawset("solverSearchEntries",(double)(28*s.cInnerSearch));
            group.rawset("solverFallbacks",(double)s.cFallbacks);
            group.rawset("solverLimitHits",(double)s.cInnerSearch);
            group.rawset("solverLimitRatio",s.cConstraintCalls>0?(double)s.cInnerSearch/s.cConstraintCalls:0.0);
        }
        group.rawset("nativeObstruction",s.obstruction);group.rawset("nativeGap",(double)s.gap);
        if(s.gap>0){group.rawset("nativeGapX",s.gapX);group.rawset("nativeGapY",s.gapY);group.rawset("nativeGapZ",s.gapZ);}
        return accumulated;
    }
}
