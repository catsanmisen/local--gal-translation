"""Additive global preferences; legacy theme-only rows need no rewrite."""
DEFAULTS={'theme':'dark','model_mode':'auto','gpu_reserve_mib':2048,'wallpaper_relief':True}
RESERVES=(2048,1536,1024)

def preferences(current=None,delta=None):
    if current is not None and not isinstance(current,dict):raise ValueError('保存的设置不是对象。')
    if delta is not None and (not isinstance(delta,dict) or not delta or set(delta)-set(DEFAULTS)):
        raise ValueError('设置字段不正确。')
    value={**DEFAULTS,**(current or {}),**(delta or {})}
    if value['theme'] not in ('dark','light','system'):raise ValueError('主题值不正确。')
    if value['model_mode'] not in ('auto','cpu','gpu'):raise ValueError('模型设备必须为自动、CPU 或 GPU。')
    if type(value['gpu_reserve_mib']) is not int or value['gpu_reserve_mib'] not in RESERVES:
        raise ValueError('显存预留必须为 2048、1536 或 1024 MiB。')
    if type(value['wallpaper_relief']) is not bool:raise ValueError('自动壁纸释放必须为布尔值。')
    return value
