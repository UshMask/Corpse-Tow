"""Tick-local environment reuse without weakening body/path collision contracts."""
import unittest
from test_link_simulation import environment
from test_link_obstacles import WORLD


class EnvironmentCacheTests(unittest.TestCase):
    def test_region_boundaries_do_not_import_an_outside_wall(self):
        l=environment();l.execute(WORLD);l.execute('''
            wallX=2;local c=O.new()
            assert(O.bodyRegion(c,0,1,0,1,0))
            assert(not O.bodyRegion(c,0,2,0,1,0))
            assert(O.bodyRegion(c,0,1,0,1,0),'wider blocked region poisoned narrower clear region')
            wallX=nil;assert(O.bodyRegion(O.new(),0,2,0,1,0),'new tick retained closed wall')
        ''')

    def test_overlapping_regions_match_all_directed_neighbours(self):
        l=environment();l.execute(WORLD);l.execute('''
            local function reference(c,l,r,t,b,z)
                for x=l,r do for y=t,b do
                    local a=O.bodyTile(c,x,y,z);if not a.clear then return false end
                    for nx=math.max(l,x-1),math.min(r,x+1) do
                        for ny=math.max(t,y-1),math.min(b,y+1) do
                            if not O.bodyEdge(c,a,O.bodyTile(c,nx,ny,z)) then return false end
                        end
                    end
                end end
                return true
            end
            for _,wall in ipairs({-1,0,2,100}) do
                wallX=wall;local c=O.new()
                for x=-2,2 do for y=-1,1 do for width=0,3 do for height=0,3 do
                    assert(O.bodyRegion(c,x,x+width,y,y+height,0)==reference(c,x,x+width,y,y+height,0))
                end end end end
            end
        ''')

    def test_body_and_path_reuse_directed_edges_in_both_orders(self):
        for path_first in (True, False):
            l = environment(); l.execute(WORLD); l.globals().pathFirst = path_first
            l.execute('''
                local c=O.new();local a=O.bodyTile(c,0,0,0);local b=O.bodyTile(c,1,0,0)
                if pathFirst then assert(not O.check(c,pos(.5),pos(1.5)))
                else assert(O.bodyEdge(c,a,b) and O.bodyEdge(c,b,a)) end
                local calls=nativeQueries
                assert(O.bodyEdge(c,a,b) and O.bodyEdge(c,b,a))
                assert(not O.check(c,pos(.5),pos(1.5)))
                assert(nativeQueries==calls,'path and footprint repeated the same native edge query')
            ''')

    def test_path_still_blocks_if_only_reverse_edge_is_blocked(self):
        l = environment(); l.execute(WORLD); l.execute('''
            local c=O.new();local a=O.bodyTile(c,0,0,0);local b=O.bodyTile(c,1,0,0)
            a.q.isBlockedTo=function() return false end
            b.q.isBlockedTo=function() return true end
            assert(O.bodyEdge(c,a,b) and not O.bodyEdge(c,b,a))
            assert(O.check(c,pos(.5),pos(1.5))==O.blocked)
            assert(O.check(c,pos(1.5),pos(.5))==O.blocked)
        ''')

    def test_paths_and_bodies_share_tiles_but_keep_tree_rules(self):
        l = environment(); l.execute(WORLD); l.execute('''
            local c=O.new();assert(not O.check(c,pos(.5),pos(2.5)))
            local reads=tileQueries
            local q=cell:getGridSquare(1,0,0);q.HasTree=function() return true end
            reads=tileQueries
            assert(not O.bodyTile(c,1,0,0).clear)
            assert(tileQueries==reads)
            assert(not O.check(c,pos(.5),pos(2.5)))
        ''')

    def test_directed_edges_cached_without_conflating_reverse_direction(self):
        l = environment(); l.execute(WORLD); l.execute('''
            local c=O.new();local a=O.bodyTile(c,0,0,0);local b=O.bodyTile(c,1,0,0)
            a.q.isBlockedTo=function() nativeQueries=nativeQueries+1;return true end
            b.q.isBlockedTo=function() nativeQueries=nativeQueries+1;return false end
            assert(not O.bodyEdge(c,a,b) and O.bodyEdge(c,b,a))
            local calls=nativeQueries
            for i=1,32 do assert(not O.bodyEdge(c,a,b) and O.bodyEdge(c,b,a)) end
            assert(nativeQueries==calls)
        ''')

    def test_same_xy_different_floor_and_new_tick_do_not_reuse_stale_cells(self):
        l = environment(); l.execute(WORLD); l.execute('''
            local c=O.new();local a=O.bodyTile(c,0,0,0);local b=O.bodyTile(c,0,0,1)
            assert(a~=b and a.clear and b.clear)
            missingX=0
            assert(not O.bodyTile(O.new(),0,0,0).clear)
            missingX=nil;solidX=0
            assert(not O.bodyTile(O.new(),0,0,0).clear)
            solidX=nil;assert(O.bodyTile(O.new(),0,0,0).clear)
        ''')


if __name__ == '__main__':
    unittest.main()
