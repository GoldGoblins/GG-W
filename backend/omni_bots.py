"""Canonical-asset paper books, reusing the existing six strategy engines."""
import re
from urllib.parse import urlencode
from backend import omni_assets as store,omni_rpc,crypto_market,crypto_paper


def _mapping(asset_id):
    with store.db() as db: row=db.execute('SELECT pair,provider FROM bot_markets WHERE asset_id=?',(asset_id,)).fetchone()
    if not row: return None
    pair=row['pair']; crypto_market.register_public_pair(pair); crypto_paper.PAIRS.add(pair)
    return pair


def bind(asset_id,pair):
    store.asset(asset_id)
    if not isinstance(pair,str) or not re.fullmatch(r'[A-Z0-9]{1,20}USDT',pair): raise ValueError('OMNI_MARKET_PAIR')
    # A ticker alone cannot prove which on-chain token an exchange represents.
    # The user explicitly chooses this mapping; label that boundary in the UI.
    if pair not in {'SOLUSDT','KASUSDT'}:
        result=omni_rpc._json('https://api.binance.com/api/v3/exchangeInfo?'+urlencode({'symbol':pair}))
        symbols=result.get('symbols') if isinstance(result,dict) else None
        if not isinstance(symbols,list) or len(symbols)!=1 or symbols[0].get('symbol')!=pair or symbols[0].get('status')!='TRADING' or symbols[0].get('quoteAsset')!='USDT' or symbols[0].get('isSpotTradingAllowed') is not True:
            raise ValueError('OMNI_SPOT_MARKET_UNAVAILABLE')
    with store.db(True) as db:
        old=db.execute('SELECT pair FROM bot_markets WHERE asset_id=?',(asset_id,)).fetchone()
        if old and old['pair']!=pair: raise ValueError('OMNI_MARKET_ALREADY_BOUND')
        db.execute('INSERT OR IGNORE INTO bot_markets VALUES(?,?,?)',(asset_id,pair,'USER_CONFIRMED_MAPPING'))
    _mapping(asset_id);store.event('bots','MARKET_BOUND',asset_id,pair+' · användarvald prisreferens · paper')


def snapshot(asset_id):
    pair=_mapping(asset_id)
    if not pair:return {'state':'MARKET_MAPPING_REQUIRED','accounts':[]}
    with crypto_paper.asset_scope(asset_id): result=crypto_paper.snapshot(pair)
    result.update(state='PAPER_MANUAL_STEPS',asset_id=asset_id,pair=pair,mapping='USER_CONFIRMED_MAPPING')
    return result


def enabled(asset_id,book,value):
    if type(value) is not bool: raise ValueError('OMNI_BOT_TOGGLE')
    pair=_mapping(asset_id)
    if not pair:raise ValueError('OMNI_MARKET_MAPPING_REQUIRED')
    with crypto_paper.asset_scope(asset_id): crypto_paper.set_enabled(pair,book,value)
    store.event('bots','ENABLED' if value else 'PAUSED',asset_id,book+' · steg körs endast när du startar analys')


def reset(asset_id,book):
    pair=_mapping(asset_id)
    if not pair:raise ValueError('OMNI_MARKET_MAPPING_REQUIRED')
    with crypto_paper.asset_scope(asset_id): crypto_paper.reset(pair,book)
    store.event('bots','RESET',asset_id,book+' · nytt paperkonto')


def step(asset_id):
    pair=_mapping(asset_id)
    if not pair:raise ValueError('OMNI_MARKET_MAPPING_REQUIRED')
    try:
        frames=crypto_market.recent_frames(pair)
        with crypto_paper.asset_scope(asset_id):
            result=crypto_paper.advance(pair,frames)
            after=crypto_paper.snapshot(pair)
        closes=frames['1h']['closes']; direction='UP' if closes[-1]>closes[-2] else 'DOWN' if closes[-1]<closes[-2] else 'FLAT'
        store.event('market',direction,asset_id,pair+' · stängd timstapel · '+str(closes[-1])+' USDT')
        for account in after['accounts']:
            store.event('bots',account['status'],asset_id,account['book']+' · '+str(account.get('equity_quote','—'))+' USDT · paper')
        return result
    except Exception:
        store.event('bots','STEP_FAILED',asset_id,pair+' · analys misslyckades; ingen riktig order skickad')
        raise
