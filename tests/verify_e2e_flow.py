import requests
import time

base = 'http://127.0.0.1:8000'
sid = 'e2e_test_' + str(int(time.time()))

# 1. Broad return request
requests.post(base + '/api/chat', json={'message': 'I want to return the things that I ordered', 'session_id': sid})

# 2. Select item 1
requests.post(base + '/api/chat', json={'message': '1', 'session_id': sid})

# 3. Select reason 2 (Defective)
requests.post(base + '/api/chat', json={'message': '2', 'session_id': sid})

# 4. Select refund method 1 (Bank card)
requests.post(base + '/api/chat', json={'message': '1', 'session_id': sid})

# 5. Approve
r5 = requests.post(base + '/api/chat', json={'message': 'yes return the product', 'session_id': sid})
data = r5.json()
print('Return created payload:', data.get('return_created'))
ret_id = data['return_created']['return_id']
print('Created Return ID:', ret_id)

# Check refunds immediately
ref_now = requests.get(base + '/api/refunds?customer_id=CUS-001').json()
item_now = [r for r in ref_now['refunds'] if r['return_id'] == ret_id][0]
print('Immediate Status:', item_now['status'], 'Step:', item_now['step'], 'Refund status:', item_now['refund']['status'])

# Poll every 1.5s for 6.5 seconds to observe staged progression
for i in range(1, 5):
    time.sleep(1.5)
    ref_poll = requests.get(base + '/api/refunds?customer_id=CUS-001').json()
    item_poll = [r for r in ref_poll['refunds'] if r['return_id'] == ret_id][0]
    p_stat = item_poll['pickup']['status'] if item_poll['pickup'] else 'None'
    r_stat = item_poll['refund']['status'] if item_poll['refund'] else 'None'
    print(f'At t={i*1.5:.1f}s -> Step: {item_poll["step"]} (Pickup: {p_stat}, Refund: {r_stat})')
