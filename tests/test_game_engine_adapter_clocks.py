import unittest
from backend.game_engine_adapter_clocks import AnimationRandom,PlacementClock

def facts():
    return {'idle_sequence':3,'sequences':[
        {'anim_id':7,'sequence_index':3,'duration_ms':1000,'looping':False,'frequency':100,'min_replay':2,'max_replay':2},
        {'anim_id':7,'sequence_index':5,'duration_ms':500,'looping':False,'frequency':32668,'min_replay':0,'max_replay':0},
        {'anim_id':2,'sequence_index':0,'duration_ms':100,'looping':True,'frequency':32768,'min_replay':1,'max_replay':1}]}

class Clocks(unittest.TestCase):
    def test_original_crt_draws(self):
        rng=AnimationRandom(1);self.assertEqual([rng.draw() for _ in range(6)],[41,18467,6334,26500,19169,15724])
    def test_zero_and_inverted_replay_still_consume_one_draw(self):
        rng=AnimationRandom(1);self.assertEqual(rng.replays(0,0),1);self.assertEqual(rng.draw(),18467)
        self.assertEqual(AnimationRandom(1).replays(2,1),2)
    def test_variation_rearm_keeps_global_attach_clock(self):
        rng=AnimationRandom(1);p=PlacementClock(facts(),10000,rng);p.tick(11999,rng)
        self.assertEqual(p.request(11999),{'anim_id':7,'sequence_index':3,'clock_ms':1999,'cursor_ms':1999,'repeat':True})
        p.tick(12000,rng);self.assertEqual(p.sequence['sequence_index'],5)
        self.assertEqual(p.request(12020)['clock_ms'],2020);self.assertEqual(p.request(12020)['cursor_ms'],20)
    def test_shared_random_dephases_instances_without_other_animation_ids(self):
        rng=AnimationRandom(1);p=PlacementClock(facts(),0,rng);q=PlacementClock(facts(),0,rng)
        self.assertEqual(p.sequence['sequence_index'],3);self.assertEqual(q.sequence['sequence_index'],5)
    def test_late_resume_rearms_once_at_current_clock(self):
        rng=AnimationRandom(1);p=PlacementClock(facts(),0,rng);p.tick(999999,rng)
        self.assertEqual(p.armed,999999);self.assertEqual(p.request(999999)['cursor_ms'],0)
    def test_globals_only_have_attach_epoch_without_sequence(self):
        p=PlacementClock({'sequences':[]},200,AnimationRandom(1));self.assertEqual(p.request(700),{'clock_ms':500,'cursor_ms':500,'repeat':True})
if __name__=='__main__':unittest.main()
