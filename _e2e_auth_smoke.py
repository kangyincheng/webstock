"""端到端冒烟：注册 -> 登录 -> 新增自选股(写审计) -> 查历史/上次 -> 再登录看回显"""
from __future__ import annotations

import os
import sys
import uuid

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend'))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient

def main():
    # 可能用到 src/，加到 path
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), 'src'))
    if src not in sys.path:
        sys.path.insert(0, src)

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)

    u = f"e2e_{uuid.uuid4().hex[:8]}"
    pwd = "Test1234!@"

    # 1) 注册
    r = client.post('/api/auth/register', json={'username': u, 'password': pwd, 'email': f'{u}@test.local'})
    print('[REGISTER]', r.status_code, r.json())
    assert r.status_code == 200 and r.json().get('success'), r.text

    # 2) 登录（JSON body）
    r = client.post('/api/auth/login', json={'username': u, 'password': pwd})
    print('[LOGIN1]', r.status_code)
    assert r.status_code == 200 and r.json().get('success'), r.text
    payload = r.json()['data']
    tokens = payload.get('tokens') or payload
    tok = tokens['access_token']
    auth_headers = {'Authorization': f'Bearer {tok}'}
    print('  last_action@login1:', payload.get('last_action'))

    # 3) 加自选股（未登录也能加，但登录后加的属于 user）
    r = client.post('/api/favorites', json={
        'code': '600519', 'name': '贵州茅台', 'cost_price': 1680.0, 'quantity': 100,
        'note': '测试', 'event_date': '2030-12-31', 'event_type': '业绩预告',
    }, headers=auth_headers)
    print('[FAV_ADD]', r.status_code, r.json())
    assert r.status_code == 200 and r.json().get('success'), r.text

    # 4) 加一个错误的（比如重复字段缺失？这里我们做一个 bad-code 作为失败示例可选）
    # 跳过，直接查历史看有没有记录

    # 5) 查操作历史
    r = client.get('/api/audit/history', headers=auth_headers)
    print('[HISTORY]', r.status_code)
    body = r.json()
    print('  total:', body.get('data', {}).get('total'))
    for it in (body.get('data', {}) or {}).get('rows', [])[:3]:
        print('  -', it['created_at'], it['category'], it['action'], 'ok=', it['ok'])

    # 6) 查上次操作
    r = client.get('/api/audit/last', headers=auth_headers)
    print('[LAST]', r.status_code, r.json())
    assert r.json()['data']['last'], '应有上次操作记录'

    # 7) 重新登录（模拟用户"再次登录"），拿到响应里的 last_action / /me 里的 last_login
    r2 = client.post('/api/auth/login', json={'username': u, 'password': pwd})
    print('[LOGIN2]', r.status_code)
    assert r2.status_code == 200 and r2.json().get('success')
    payload2 = r2.json()['data']
    tokens2 = payload2.get('tokens') or payload2
    tok2 = tokens2['access_token']
    h2 = {'Authorization': f'Bearer {tok2}'}
    print('[LOGIN2.last_action 回显]', payload2.get('last_action'))
    assert payload2.get('last_action'), '再次登录响应就应该带回上次操作'
    meResp = client.get('/api/auth/me', headers=h2).json()['data']
    me = meResp.get('user') or meResp
    print('[ME] login_count=', me.get('login_count'), 'last_login_at=', me.get('last_login_at'),
          'me.last_action=', (meResp.get('last_action') or {}).get('action'))
    last = client.get('/api/audit/last', headers=h2).json()['data']['last']
    print('[LAST(relogin)] 上次操作 =', last['action'] if last else None, 'at', last['created_at'] if last else None)
    assert last, '重新登录后仍能看到上次操作记录'

    # 8) 自选股用户隔离：用另一个账号加一个，A 账号看不到 B 的
    u2 = f"e2e_{uuid.uuid4().hex[:8]}"
    client.post('/api/auth/register', json={'username': u2, 'password': pwd})
    r2l = client.post('/api/auth/login', json={'username': u2, 'password': pwd})
    tokens_u2 = (r2l.json()['data'].get('tokens') or r2l.json()['data'])
    tok_u2 = tokens_u2['access_token']
    client.post('/api/favorites', json={
        'code': '000001', 'name': '平安银行', 'cost_price': 10, 'quantity': 1000,
        'buy_price': 10,
        'note': '隔离测试', 'event_date': '2030-12-31', 'event_type': '业绩预告',
    }, headers={'Authorization': f'Bearer {tok_u2}'})
    list_u = client.get('/api/favorites', headers=auth_headers).json()['data']
    list_u2 = client.get('/api/favorites', headers={'Authorization': f'Bearer {tok_u2}'}).json()['data']
    codes_u = [x['code'] for x in list_u['rows']]
    codes_u2 = [x['code'] for x in list_u2['rows']]
    print('[隔离测试] u_rows=', list_u['rows'][:2], 'u2_rows=', list_u2['rows'][:2])
    print('[隔离测试] u_codes=', codes_u, 'u2_codes=', codes_u2)
    # u 有 600519，u2 有 000001，互不可见
    assert '600519' in codes_u, f'u 应有 600519，实际={codes_u}'
    assert '000001' in codes_u2, f'u2 应有 000001，实际={codes_u2}'
    assert '000001' not in codes_u and '600519' not in codes_u2, '自选股必须按用户隔离'

    print('\n✅ E2E smoke passed.')


if __name__ == '__main__':
    main()
