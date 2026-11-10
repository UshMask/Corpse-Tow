package cvpworld;

import java.util.Arrays;
import java.util.Comparator;
import se.krka.kahlua.vm.KahluaTable;

/** Numeric part of CVP_BodySpread. Does not move bodies or choose fleet membership. */
final class BodySpacing {
    private static final class Row {
        final KahluaTable table;
        String id;
        double x,y,z,ax,ay,side,push,remaining,speed,offset,scale,sum;
        boolean anchored,failed;
        int first,count;
        Row(KahluaTable table){this.table=table;}
        void read() {
            x=number(table,"x");y=number(table,"y");z=number(table,"z");
            Object a=table.rawget("ax"),b=table.rawget("ay");
            boolean hasA=a!=null&&!Boolean.FALSE.equals(a),hasB=b!=null&&!Boolean.FALSE.equals(b);
            ax=hasA?((Number)a).doubleValue():x;ay=hasB?((Number)b).doubleValue():y;
            anchored=hasA&&hasB;failed=TowingSolver.yes(table,"failed");
            id=(String)((KahluaTable)table.rawget("link")).rawget("id");
            push=0;remaining=0;speed=0;
        }
    }
    private static final class State {
        final Row[] rows,blocks;
        State(KahluaTable records) {
            rows=new Row[records.len()];blocks=new Row[rows.length];
            for(int i=0;i<rows.length;i++)rows[i]=new Row((KahluaTable)records.rawget(i+1));
        }
        boolean matches(KahluaTable records) {
            if(records.len()!=rows.length)return false;
            for(int i=0;i<rows.length;i++)if(records.rawget(i+1)!=rows[i].table)return false;
            return true;
        }
    }
    private static final Comparator<Row> ORDER=(a,b)->a.side==b.side?a.id.compareTo(b.id):a.side<b.side?-1:1;
    private static double number(KahluaTable table,String key){return ((Number)table.rawget(key)).doubleValue();}
    static void update(KahluaTable bucket,boolean moving,double width,double speed) {
        var records=(KahluaTable)bucket.rawget("records");
        int size=records.len();
        // Reset directly: inactive buckets need neither cached rows nor identity checks.
        if(!moving || size<=1) {
            for(int i=1;i<=size;i++) {
                var row=(KahluaTable)records.rawget(i);
                row.rawset("spreadSpeed",0.);row.rawset("spreadPush",0.);row.rawset("spreadRemaining",0.);
            }
            return;
        }
        Object previousState=bucket.rawget("nativeSpread");
        State s=previousState instanceof State old && old.matches(records)?old:new State(records);
        if(previousState!=s)bucket.rawset("nativeSpread",s);
        Row[] rows=s.rows;
        // Cache storage only: poses, anchors and failure flags remain live inputs.
        double dx=0,dy=0;
        for(Row r:rows){r.read();dx=dx+r.ax-r.x;dy=dy+r.ay-r.y;}
        double distance=Math.sqrt(dx*dx+dy*dy);
        double nx,ny;
        if(distance>.001){nx=-dy/distance;ny=dx/distance;}
        else {
            double angle=number((KahluaTable)bucket.rawget("reference"),"angle");
            nx=-Math.sin(angle);ny=Math.cos(angle);
        }
        Row previous=null;boolean ordered=true;
        for(Row r:rows){
            r.side=r.x*nx+r.y*ny;
            if(previous!=null && ORDER.compare(previous,r)>0)ordered=false;
            previous=r;
        }
        if(!ordered){
            Arrays.sort(rows,ORDER);
            // Preserve next tick's summation order and the Lua fallback's row order.
            for(int i=0;i<size;i++)records.rawset(i+1,rows[i].table);
        }
        int top=0,first=0;
        for(int i=0;i<size;i++) {
            Row r=rows[i];s.blocks[top++]=r;r.first=i;r.count=1;r.sum=r.side-(i-first)*width;
            while(top>1){
                Row a=s.blocks[top-2],b=s.blocks[top-1];
                if(a.sum/a.count<=b.sum/b.count)break;
                a.sum=a.sum+b.sum;a.count=a.count+b.count;s.blocks[--top]=null;
            }
            Row b=i+1<size?rows[i+1]:null;
            boolean joined=b!=null && !r.failed && !b.failed && Math.floor(r.z)==Math.floor(b.z)
                && Math.abs((b.x-r.x)*ny-(b.y-r.y)*nx)<1.3;
            if(!joined){
                double scale=width;
                for(int k=0;k<top;k++){
                    Row block=s.blocks[k];int count=block.count;
                    if(count>1){
                        int start=block.first,last=start+count-1;
                        double target=block.sum/count+(start-first)*width;
                        scale=Math.max(Math.max(scale,rows[start].side-target),target+(count-1)*width-rows[last].side);
                        for(int j=start;j<=last;j++){
                            Row row=rows[j];double delta=target+(j-start)*width-row.side;
                            row.push=delta;row.remaining=Math.abs(delta);row.speed=speed;
                        }
                    }
                    s.blocks[k]=null;
                }
                for(int j=first;j<=i;j++){
                    Row row=rows[j];row.offset=row.side+row.push-row.ax*nx-row.ay*ny;
                    row.scale=scale;row.push=row.push/scale;
                }
                top=0;first=i+1;
            }
        }
        for(Row r:rows){
            // Side is scratch for this algorithm; the Lua fallback recomputes it.
            r.table.rawset("spreadNX",nx);r.table.rawset("spreadNY",ny);
            r.table.rawset("spreadPush",r.push);r.table.rawset("spreadRemaining",r.remaining);r.table.rawset("spreadSpeed",r.speed);
            r.table.rawset("spreadOffset",r.anchored?r.offset:null);r.table.rawset("spreadScale",r.scale);
        }
    }
}
