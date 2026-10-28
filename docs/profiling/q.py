import sqlite3,sys
db=sqlite3.connect('/private/tmp/claude-501/-Users-nick-Documents-hack/d776d94d-0a42-45e0-9cc4-4f938b944ec0/scratchpad/p.db')
for q in open(sys.argv[1]).read().split(';\n'):
    q=q.strip()
    if not q: continue
    if q.startswith('--'):
        print('#',q.split('\n')[0][2:]); q='\n'.join(q.split('\n')[1:])
    try:
        rows=db.execute(q).fetchall()
        for r in rows[:int(sys.argv[2]) if len(sys.argv)>2 else 40]: print('  ',r)
    except Exception as e: print('ERR',e,q[:80])
