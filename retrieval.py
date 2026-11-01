"""Bounded, explainable retrieval from TIKI's *local* memories, notes and tasks.

No embeddings subscription or API call. Explicit memory facts and authorized
notes remain separate records with source IDs; only relevant snippets go to AI.
"""
import math
import re
from collections import Counter
from . import store

STOP = set('a an the of to in on at for with from by about it is am are was were i me my you your we our can could would please tell explain what which who why when how do did have has this that these those and or but as be being been just later again now then hey tiki spots any some here there'.split())
SYNONYMS = {
    'board':'whiteboard','blackboard':'whiteboard','chalkboard':'whiteboard','boardwork':'whiteboard',
    'photo':'image','picture':'image','pic':'image','capture':'image','screenshot':'image','saw':'see','looked':'see',
    'study':'class','studying':'class','lesson':'class','lecture':'class',
    'todo':'task','reminder':'task','remind':'task',
    'build':'project','building':'project','prototype':'project',
    'dog':'dog','puppy':'dog',
}

def tokens(text):
    result=[]
    for term in re.findall(r"[\w']+", (text or '').casefold()):
        if len(term)<2 or term in STOP:
            continue
        # Simple English normalization; avoid requiring a large ML runtime.
        if term.endswith('ies') and len(term)>4: term=term[:-3]+'y'
        elif term.endswith('ing') and len(term)>6: term=term[:-3]
        elif term.endswith('ed') and len(term)>5: term=term[:-2]
        elif term.endswith('s') and len(term)>4 and not term.endswith('ss'): term=term[:-1]
        result.append(SYNONYMS.get(term,term))
    return result

def indexed_records():
    rows=[]
    for m in store.memories():
        rows.append({'kind':'memory','id':m['id'],'title':'Personal preference or fact',
                     'text':m['content'],'date':m['created_at'],'source':m.get('source','user')})
    for n in store.notes():
        rows.append({'kind':'note','id':n['id'],'title':n['title'],
                     'text':n['content'],'date':n['created_at'],
                     'photo_filename':n.get('photo_filename')})
    for r in store.reminders():
        if not r['done']:
            rows.append({'kind':'task','id':r['id'],'title':'Task',
                         'text':r['title'],'date':r['created_at'],'due_at':r.get('due_at')})
    # Every captured image is retained as searchable visual memory, even when
    # the user did not specifically request class notes at capture time.
    for c in store.captures():
        rows.append({'kind':'photo','id':c['id'],'title':'Captured glasses/phone photo',
                     'text':c['request_text'] + '\nObserved: ' + c['analysis'],
                     'date':c['created_at'], 'photo_filename':c['filename']})
    # Conversation recall uses actual previous USER messages, not AI-generated
    # statements (which can be mistaken or speculative).
    for message in store.history(160):
        if message['role'] == 'user' and len(message['content'].strip()) > 12:
            rows.append({'kind':'conversation','id':message['id'],
                         'title':'Earlier user conversation', 'text':message['content'],
                         'date':message['created_at']})
    return rows

def search(query, limit=7):
    docs=indexed_records()
    if not docs:
        return []
    query_terms=tokens(query)
    if not query_terms:
        return []
    counts=[Counter(tokens(row['title']+' '+row['text'])) for row in docs]
    N=len(docs)
    df=Counter(t for c in counts for t in c)
    lengths=[sum(c.values()) for c in counts]
    avgdl=sum(lengths)/N or 1.0
    scored=[]
    want_notes=any(w in query.casefold() for w in ('board','notes','photo','picture','captur','saw','image','read','concept','flashcard'))
    want_tasks=any(w in query.casefold() for w in ('task','remind','due','finish','todo','deadline'))
    for row, count, dl in zip(docs, counts, lengths):
        score=0.0
        for term in set(query_terms):
            tf=count[term]
            if tf:
                idf=math.log(1+(N-df[term]+0.5)/(df[term]+0.5))
                score+=idf*tf*2.2/(tf+1.2*(0.25+0.75*dl/avgdl))
        if not score:
            continue
        if row['kind'] in ('note','photo') and want_notes: score*=1.75
        if row['kind']=='task' and want_tasks: score*=1.25
        if row['kind']=='memory' and not (want_notes or want_tasks): score*=1.6
        if row['kind']=='conversation': score*=0.68
        scored.append((score,row))
    scored.sort(key=lambda x:(x[0],x[1]['date']),reverse=True)
    # Referential requests need the most recent actual visual note, even when its
    # full body lacks the literal word 'board'. Don't invent any note if absent.
    query_l=query.casefold()
    visual_deixis=want_notes and any(t in query_l for t in ('that board','this board','the board','that photo','last photo','my notes','second concept','first concept','what did you see','what did you photograph','what did you capture','last picture','last image'))
    chosen=[row for _,row in scored[:limit]]
    if visual_deixis:
        notes=[r for r in docs if r['kind'] in ('note','photo') and r.get('photo_filename')]
        notes.sort(key=lambda r:r['date'],reverse=True)
        if notes and notes[0] not in chosen:
            chosen.insert(0,notes[0]);chosen=chosen[:limit]
    # Stable IDs make clear which records supplied the answer.
    return [dict(item, label=f"{item['kind'].upper()}#{item['id']}") for item in chosen]

def safe_context(items, chars_per_note=3300):
    lines=[]
    for r in items:
        title=str(r['title'])[:160].replace('\n',' ')
        content=str(r['text'])[:chars_per_note].replace('\x00','')
        src=' (captured photo: '+r['photo_filename']+')' if r.get('photo_filename') else ''
        lines.append(f"[{r['label']}] {title}{src}\n{content}")
    return '\n\n'.join(lines)

def public_sources(items):
    return [{'kind':r['kind'],'id':r['id'],'label':r['label'],'title':r['title']} for r in items]
