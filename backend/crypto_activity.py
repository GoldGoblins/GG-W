"""Read actual persisted events without scheduling work or manufacturing ticks."""
from backend import omni_assets as store

def snapshot():
    events=store.events(limit=80)
    return {'schema':'gg.space-activity.v1','events':events,'cursor':events[-1]['seq'] if events else 0}
