# What is left of each model's limits, in the form the sidebar rings and the bars on the usage page show it.
# Loaded by backend/server.py into one shared namespace.
RING_ORDER = ('codex', 'claude', 'grok', 'antigravity', 'gemini')


def _left(window, snap, now):
    """Percent left in one limit. A limit whose reset time has passed is full again."""
    used = window.get('usedPercent')
    if not isinstance(used, (int, float)) or isinstance(used, bool): return None
    return 100.0 if not _window_open(window, snap, now) else round(max(0.0, min(100.0, 100 - used)), 1)


def usage_rings(store):
    """Lock held. One entry per model that is signed in or has been used: what is left of its limits, or None when it reports none (Grok, API keys)."""
    data = store.data; quota = data.get('quota') or {}; status = data.get('autoStatus') or {}; now = time.time()
    used = {(j.get('usage') or {}).get('provider') for j in data['jobs'] if isinstance(j.get('usage'), dict)}
    out = []
    for provider in RING_ORDER:
        snap = quota.get(provider) if isinstance(quota.get(provider), dict) else {}
        windows = [w for w in snap.get('windows') or [] if isinstance(w, dict)]
        if not windows and (status.get(provider) or {}).get('signedIn') is not True and provider not in used: continue
        if not P.spec(data, provider): continue
        rows = [dict(label=str(w.get('label') or ''), left=_left(w, snap, now), resetsAt=w.get('resetsAt')) for w in windows]
        rows = [r for r in rows if r['left'] is not None]
        main = [r for r in rows if 'gemini' in r['label'].lower()] or rows if provider == 'antigravity' else rows  # the ring follows the model Zook runs by default
        out.append(dict(id=provider, name=provider_label(provider).split('（')[0], left=min(r['left'] for r in main) if main else None, windows=rows, updatedAt=snap.get('updatedAt')))
    return out

