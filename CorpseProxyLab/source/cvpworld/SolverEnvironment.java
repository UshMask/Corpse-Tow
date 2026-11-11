package cvpworld;

import java.util.HashMap;
import java.util.Map;
import zombie.iso.IsoGridSquare;
import zombie.iso.IsoWorld;

/** Directed cell queries, scoped to one synchronous authority tick. */
public final class SolverEnvironment {
    public static final String BLOCKED="IGUI_CVP_LinkBlocked", UNLOADED="IGUI_CVP_LinkPathUnloaded";
    public interface World {
        int flags(int x,int y,int z); // 1 absent, 2 solid/no floor, 4 tree
        boolean blocked(int x,int y,int z,int bx,int by);
    }
    record Key(int x,int y,int z) {}
    static final class Tile {
        final Key key; final String why; final boolean clear;
        final Map<Tile,Boolean> edges=new HashMap<>();
        Tile(Key k,int flags) {key=k;why=(flags&1)!=0?UNLOADED:(flags&2)!=0?BLOCKED:null;clear=why==null&&(flags&4)==0;}
    }
    final World world;
    final Map<Key,Tile> tiles=new HashMap<>();
    final Map<String,Boolean> regions=new HashMap<>();
    public SolverEnvironment(World world) {this.world=world;}
    public static SolverEnvironment live() {
        var cell=IsoWorld.instance.getCell();
        if(cell==null) throw new IllegalStateException("solver requires loaded world");
        return new SolverEnvironment(new World() {
            final Map<Key,IsoGridSquare> cells=new HashMap<>();
            IsoGridSquare square(int x,int y,int z) {
                Key k=new Key(x,y,z);
                var square=cells.get(k);
                if(square==null && !cells.containsKey(k)) {
                    square=cell.getGridSquare(x,y,z);cells.put(k,square);
                }
                return square;
            }
            public int flags(int x,int y,int z) {
                var q=square(x,y,z);if(q==null)return 1;
                return (q.isSolid()||q.isSolidTrans()||!q.TreatAsSolidFloor()?2:0)|(q.HasTree()?4:0);
            }
            public boolean blocked(int x,int y,int z,int bx,int by) {return square(x,y,z).isBlockedTo(square(bx,by,z));}
        });
    }
    Tile tile(int x,int y,int z) {Key k=new Key(x,y,z);return tiles.computeIfAbsent(k,v->new Tile(v,world.flags(x,y,z)));}
    boolean blocked(Tile a,Tile b) {return a.edges.computeIfAbsent(b,v->world.blocked(a.key.x,a.key.y,a.key.z,b.key.x,b.key.y));}
    boolean bodyEdge(Tile a,Tile b) {return a.clear&&b.clear&&(a==b||!blocked(a,b));}
    boolean passage(Tile a,Tile b) {
        if(!bodyEdge(a,b))return false;
        if(a.key.x!=b.key.x&&a.key.y!=b.key.y) {
            Tile h=tile(b.key.x,a.key.y,a.key.z),v=tile(a.key.x,b.key.y,a.key.z);
            return (bodyEdge(a,h)&&bodyEdge(h,b))||(bodyEdge(a,v)&&bodyEdge(v,b));
        }
        return true;
    }
    boolean region(int minX,int maxX,int minY,int maxY,int z) {
        String key=minX+":"+maxX+":"+minY+":"+maxY+":"+z;
        Boolean found=regions.get(key);if(found!=null)return found;
        boolean clear=true;
        outer:for(int x=minX;x<=maxX;x++)for(int y=minY;y<=maxY;y++) {
            Tile a=tile(x,y,z);if(!a.clear){clear=false;break outer;}
            for(int dx=x>minX?-1:0;dx<=(x<maxX?1:0);dx++)for(int dy=y>minY?-1:0;dy<=(y<maxY?1:0);dy++)
                if((dx!=0||dy!=0)&&!bodyEdge(a,tile(x+dx,y+dy,z))){clear=false;break outer;}
        }
        regions.put(key,clear);return clear;
    }
    String edge(int x,int y,int nx,int ny,int z) {
        Tile a=tile(x,y,z),b=tile(nx,ny,z);
        if(a.why!=null)return a.why;if(b.why!=null)return b.why;
        return blocked(a,b)||blocked(b,a)?BLOCKED:null;
    }
    public String check(double ax,double ay,double az,double bx,double by,double bz,double maxDistance) {
        if(Math.floor(az)!=Math.floor(bz))return BLOCKED;
        int x=(int)Math.floor(ax),y=(int)Math.floor(ay),z=(int)Math.floor(az),tx=(int)Math.floor(bx),ty=(int)Math.floor(by);
        String why=tile(x,y,z).why;if(why!=null)return why;
        int budget=Double.isNaN(maxDistance)?96:Math.max(96,(int)Math.ceil(maxDistance*Math.sqrt(2))+2);
        if(Math.abs(tx-x)+Math.abs(ty-y)>budget)return BLOCKED;
        // Exact supercover trace. The Lua rectangle fast proof is an optimization,
        // not an additional collision rule; cached directed edges are shared here.
        double dx=bx-ax,dy=by-ay;int sx=dx<0?-1:1,sy=dy<0?-1:1;
        double ix=dx==0?Double.POSITIVE_INFINITY:1/Math.abs(dx),iy=dy==0?Double.POSITIVE_INFINITY:1/Math.abs(dy);
        double mx=dx==0?Double.POSITIVE_INFINITY:(dx<0?ax-x:x+1-ax)*ix;
        double my=dy==0?Double.POSITIVE_INFINITY:(dy<0?ay-y:y+1-ay)*iy;
        for(int i=0;i<=budget;i++) {
            if(x==tx&&y==ty)return null;
            if(Math.abs(mx-my)<1e-9) {
                why=edge(x,y,x+sx,y,z);
                if(why==null)why=edge(x,y,x,y+sy,z);
                if(why==null)why=edge(x+sx,y,x+sx,y+sy,z);
                if(why==null)why=edge(x,y+sy,x+sx,y+sy,z);
                x+=sx;y+=sy;mx+=ix;my+=iy;
            } else if(mx<my){why=edge(x,y,x+sx,y,z);x+=sx;mx+=ix;}
            else {why=edge(x,y,x,y+sy,z);y+=sy;my+=iy;}
            if(why!=null)return why;
        }
        return BLOCKED;
    }
}
