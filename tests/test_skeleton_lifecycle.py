"""The shared core updates the native clock at successful attachment/detachment."""
import unittest
from test_core_lifecycle import environment

class SkeletonLifecycleTests(unittest.TestCase):
    def test_sp_and_server_notify_after_metadata_commits(self):
        for server in (False,True):
            with self.subTest(server=server):
                lua=environment(server)
                lua.execute('''
                    local calls={}
                    CVPSkeletonNative={sync=function(b)
                        calls[#calls+1]={body=b,attached=b:getModData().CVPTether~=nil}
                    end}
                    assert(attach())
                    assert(#calls==1 and calls[1].body==body and calls[1].attached)
                    assert(detach())
                    assert(#calls==2 and calls[2].body==body and not calls[2].attached)
                ''')

    def test_failed_equipment_return_keeps_pause_until_success(self):
        for server in (False,True):
            with self.subTest(server=server):
                lua=environment(server)
                lua.execute('''
                    local calls=0
                    CVPSkeletonNative={sync=function() calls=calls+1 end}
                    assert(attach() and calls==1)
                    local E=require 'CVP_Equipment';local release=E.release
                    E.release=function() return false,'test return failure' end
                    assert(not detach() and calls==1 and body.md.CVPTether)
                    E.release=release
                    assert(detach() and calls==2 and not body.md.CVPTether)
                ''')

if __name__=='__main__': unittest.main()
