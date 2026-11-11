"""Container interference must not duplicate or reclaim another mod's tether item."""
import unittest

from test_core_lifecycle import environment


class TransferCompatibilityTests(unittest.TestCase):
    def test_source_refusal_or_redirection_never_reaches_destination(self):
        for redirected in (False, True):
            with self.subTest(redirected=redirected):
                lua = environment(False)
                lua.globals().redirected = redirected
                lua.execute('''
                    local core=require 'CVP_Core'
                    local other=container();local remove=storage.Remove
                    local adds=0;local add=body.inv.AddItem
                    body.inv.AddItem=function(s,item) adds=adds+1;return add(s,item) end
                    storage.Remove=function(s,item)
                        if redirected then remove(s,item);other:AddItem(item) end
                    end
                    assert(not core.transfer(rope,storage,body.inv))
                    assert(adds==0 and not body.inv:getItems():contains(rope))
                    assert(rope.owner==(redirected and other or storage))
                    assert(storage:getItems():contains(rope)==not redirected)
                ''')

    def test_stale_source_does_not_touch_either_container(self):
        lua = environment(False)
        lua.execute('''
            local other=container()
            other.Remove=function() error('must not remove from stale source') end
            body.inv.AddItem=function() error('must not add from stale source') end
            assert(not require('CVP_Core').transfer(rope,other,body.inv))
            assert(rope.owner==storage and storage:getItems():contains(rope))
        ''')

    def test_refused_detach_preserves_link_and_sends_no_inventory_updates(self):
        for server in (False, True):
            with self.subTest(server=server):
                lua = environment(server)
                lua.execute('''
                    assert(attach());local saved=body.md.CVPTether
                    local holder=CVPEquipmentRuntime.container
                    local remove=holder.Remove;local add=storage.AddItem
                    holder.Remove=function() end
                    local adds=0
                    storage.AddItem=function(s,item) adds=adds+1;return add(s,item) end
                    assert(not detach())
                    assert(adds==0 and #links()==1 and body.md.CVPTether==saved)
                    assert(rope.owner==CVPEquipmentRuntime.container and worldCount(body)==1)
                    if serverMode then assert(#containerPackets==1) end
                    holder.Remove=remove;storage.AddItem=add
                    assert(detach() and rope.owner==storage and #links()==0)
                    if serverMode then assert(#containerPackets==2) end
                ''')


if __name__ == '__main__':
    unittest.main()
