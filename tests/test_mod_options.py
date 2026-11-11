"""Personal display preferences must not change authority or saved links."""
from pathlib import Path
import unittest
from test_link_client import client
from test_link_multiplayer import Network


class ModOptionsTests(unittest.TestCase):
    def test_mp_clients_render_different_quality_from_same_server_state(self):
        n=Network();n.server.execute('root=link(C,A,rope)');n.publish()
        for quality,c in enumerate(n.clients.values(),1):
            c.globals().quality=quality
            c.execute('''
                PZAPI={ModOptions={getOptions=function() return {getOption=function(_,key)
                    return {getValue=function() return key=='RopeQuality' and quality or true end}
                end} end}}
                now=now+16;CVPMPClient.tick()
                local count=0
                for _,points in pairs(drawn) do count=count+1;assert(#points==(quality==2 and 9 or 17)) end
                assert(count==1)
            ''')
        n.server.execute("assert(S.graph.links[root] and require('CVP_Equipment').get(S.graph.links[root].equipment)==rope)")

    def test_display_toggle_clears_and_restores_render_without_touching_graph(self):
        l=client()
        l.execute('''
            package.preload['PZAPI/ModOptions']=function()
                PZAPI={ModOptions={}}
                function PZAPI.ModOptions:getOptions() return self.options end
                function PZAPI.ModOptions:create()
                    local o={values={}}
                    function o:addTickBox(id,label,value)
                        self.values[id]={value=value,getValue=function(s) return s.value end}
                    end
                    function o:addDescription() end
                    function o:addTitle() end
                    function o:addComboBox(id)
                        local row={selected=1,values={}}
                        function row:addItem(label) self.values[#self.values+1]=label end
                        function row:getValue() return self.selected end
                        self.values[id]=row;return row
                    end
                    function o:addButton(id,label,tooltip,callback)
                        self.values[id]={onclick=callback}
                    end
                    function o:getOption(id) return self.values[id] end
                    self.options=o;return o
                end
            end
        ''')
        l.execute(Path('CorpseProxyLab/42/media/lua/client/CVP_Options.lua').read_text())
        l.execute('''
            local id=link(C,A,rope);tick();local revision=S.graph.revision
            local view=require('CVP_LinkPresentation').new(H)
            view:update(S.graph,H.samples(S.graph),.05);assert(drawn[id])
            local options=PZAPI.ModOptions:getOptions('CorpseProxyLab')
            local length=S.graph.links[id].length;local x,y=body.x,body.y
            assert(#drawn[id]==17)
            options:getOption('RopeQuality').selected=2
            view:update(S.graph,H.samples(S.graph),.05);assert(#drawn[id]==9)
            local points=drawn[id]
            local ends=H.samples(S.graph)[id]
            assert(math.abs(points[1].x-ends.a.x)<1e-8 and math.abs(points[9].x-ends.b.x)<1e-8)
            for _,p in ipairs(points) do assert(p.z>=require('CVP_Rope').floorHeight*3-1e-8) end
            options:getOption('RopeQuality').selected=1
            view:update(S.graph,H.samples(S.graph),.05);assert(#drawn[id]==17)
            assert(S.graph.links[id].length==length and body.x==x and body.y==y)
            options:getOption('PreferredMaterial').selected=2
            assert(require('CVP_Menu').material(player)=='Base.HeavyChain')
            assert(require('CVP_Menu').material(player,false,{['Base.Rope']=true})=='Base.Rope')
            assert(options:getOption('PreferredMaterial'):getValue()==2)
            options:getOption('ShowRopes').value=false
            view:update(S.graph,H.samples(S.graph),.05);assert(not drawn[id])
            assert(S.graph.revision==revision and S.graph.links[id]);intact(body)
            options:getOption('ShowRopes').value=true
            view:update(S.graph,H.samples(S.graph),.05);assert(drawn[id])
            options:getOption('ShowHighlights').value=false
            local opt={};require('CVP_Menu').highlight(opt,{body},nil,false,{})
            assert(not opt.onHighlight and S.graph.revision==revision)
        ''')


if __name__=='__main__': unittest.main()
