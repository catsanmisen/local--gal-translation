"""Field-scoped profile updates; validate the complete result before any write."""
from copy import deepcopy
from engine import ClientError
from game_session import validate_game

def merge_profile(existing, body):
    if not isinstance(body,dict) or set(body)-{'id','name','prefs','game'}:
        raise ClientError('INVALID_PROFILE','配置更新含不支持的字段。')
    if existing is None:raise ClientError('INVALID_PROFILE','要更新的游戏配置不存在。',404)
    result=deepcopy(existing)
    if 'name' in body:result['name']=body['name']
    if 'prefs' in body:
        delta=body['prefs']
        if not isinstance(delta,dict) or set(delta)-{'font','opacity','mode','source_kind'}:
            raise ClientError('INVALID_PROFILE','显示更新字段不正确。')
        prefs=result.setdefault('prefs',{})
        for key,value in delta.items():
            if value is None:prefs.pop(key,None)
            else:prefs[key]=value
    if 'game' in body:
        delta=body['game']
        allowed={'executable','input_mode','region','dialogue_box','special_region','hide_input','anchor','hook','auto_recovery','enabled','hotkeys','subtitle_placement'}
        if not isinstance(delta,dict) or set(delta)-allowed:raise ClientError('INVALID_PROFILE','游戏更新字段不正确。')
        game=result.setdefault('game',{})
        for key,value in delta.items():
            if value is None:
                if key not in {'dialogue_box','special_region','hook'}:raise ClientError('INVALID_PROFILE','此游戏字段不能清除。')
                game.pop(key,None)
            elif key in {'hotkeys','anchor'} and isinstance(value,dict):game[key]={**game.get(key,{}),**value}
            else:game[key]=value
        validate_game(game)
    # Return only writable fields. Glossary/history are never patch targets.
    return {k:result[k] for k in ('id','name','prefs','game') if k in result}
