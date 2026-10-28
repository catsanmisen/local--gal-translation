"""Keep a coherent dialogue block without rejecting kanji-only short dialogue."""
def reading_indices(texts,boxes):
    """Exclude attached reading annotations; keep their boxes for placement."""
    bounds=[(min(p[0] for p in b),min(p[1] for p in b),max(p[0] for p in b),max(p[1] for p in b)) for b in boxes]
    keep=[]
    for i,text in enumerate(texts):
        x,y,r,b=bounds[i];h=b-y;w=r-x
        kana=sum('\u3040'<=c<='\u30ff' for c in text)
        ruby=bool(text.strip()) and all(c.isspace() or '\u3040'<=c<='\u30ff' for c in text)
        # Misread logo readings also need much smaller, centred geometry.
        latin_reading=kana>=3 and kana>=.6*len(text.strip()) and not any(
            '\u3400'<=c<='\u9fff' or c in '「」『』〔〕（）()[]〉>\"' for c in text)
        reading=False
        for j,base in enumerate(texts):
            if i==j:continue
            xx,yy,rr,bb=bounds[j];bh=bb-yy;bw=rr-xx
            center_gap=(yy+bb-y-b)/2
            if ruby and any('\u3400'<=c<='\u9fff' for c in base) and h<bh*.95 and w<bw*.5 and x>=xx-bh*.2 and r<=rr+bh*.2 and .25*bh<=center_gap<=1.1*bh:
                reading=True;break
            if latin_reading and base.isascii() and sum(c.isalpha() for c in base)>=6 and 0<h<=.45*bh and w<=.5*bw and x>=xx and r<=rr and abs(x+r-xx-rr)<=.3*bw and 0<=yy-b<=.5*h:
                reading=True;break
        if not reading:keep.append(i)
    return keep

def reread_uncertain_rows(texts,scores,boxes,recognize):
    """One original-orientation reread, supported by a coherent upright block.

    The angle classifier can turn a short trailing row upside down even when
    its neighbouring body rows are upright. Do not change isolated short text,
    vertical columns, or accept another weak reading merely for scoring higher.
    """
    bounds=[(min(p[0] for p in b),min(p[1] for p in b),max(p[0] for p in b),max(p[1] for p in b)) for b in boxes]
    for i in sorted(range(len(texts)),key=lambda n:scores[n]):
        if scores[i]>=.85:break
        x,y,r,b=bounds[i];h=b-y
        if h<=0 or r-x<2*h:continue
        neighbours=sum(j!=i and scores[j]>=.9 and .55*h<=bb-yy<=1.6*h
            and rr-xx>=2*(bb-yy) and abs(xx-x)<=3*h and max(y-bb,yy-b,0)<=4*h
            for j,(xx,yy,rr,bb) in enumerate(bounds))
        if neighbours<2:continue
        new_texts=list(texts);new_scores=list(scores)
        for text,score in recognize([boxes[i]]):
            if isinstance(text,str) and text.strip() and '\n' not in text and .9<=score<=1 and score>=scores[i]+.1:
                new_texts[i]=text.strip();new_scores[i]=score
            break
        return new_texts,new_scores,boxes
    return texts,scores,boxes

def repair_quote_edges(texts,scores,boxes,recognize,width,height):
    """Reread tight quote edges once; never synthesize a missing bracket."""
    import math
    pairs={'(' : ')','（':'）','「':'」','『':'』','〔':'〕','[':']'}
    edge_chars='()（）「」『』〔〕[]〉>'
    if not texts or len(texts)!=len(scores) or len(texts)!=len(boxes):return texts,scores,boxes
    pending=[];expanded=[]
    for i,text in enumerate(texts):
        value=text.strip()
        if not value or (value[0] in pairs and value.endswith(pairs[value[0]])):continue
        if value[0] not in pairs and value[-1] not in edge_chars:continue
        x=min(p[0] for p in boxes[i]);y=min(p[1] for p in boxes[i]);r=max(p[0] for p in boxes[i]);b=max(p[1] for p in boxes[i]);padding=(b-y)*.4
        x=max(0,x-padding);r=min(width,r+padding);y=max(0,y-2);b=min(height,b+2)
        pending.append(i);expanded.append([[x,y],[r,y],[r,b],[x,b]])
        if len(pending)==8:break
    if not pending:return texts,scores,boxes
    new_texts=list(texts);new_scores=list(scores);new_boxes=list(boxes)
    for i,box,result in zip(pending,expanded,recognize(expanded)):
        if result is None:continue
        text,score=result
        if not isinstance(text,str) or not text.strip() or '\n' in text or not math.isfinite(score) or not scores[i]<=score<=1:continue
        text=text.strip();old=texts[i].strip()
        if text[0] in pairs and text.endswith(pairs[text[0]]) and text.strip(edge_chars).strip()==old.strip(edge_chars).strip():
            new_texts[i]=text;new_scores[i]=score;new_boxes[i]=box
    return new_texts,new_scores,new_boxes

def merge_line_fragments(texts,scores,boxes,recognize=None):
    """Join adjacent detections on one horizontal line before block filtering.

    Detection sometimes splits a long sentence into left/right fragments. The
    continuation must not be mistaken for a remote label or a new visual row.
    """
    if not texts or len(texts)!=len(boxes) or len(scores)!=len(texts):return texts,scores,boxes
    bounds=[(min(p[0] for p in b),min(p[1] for p in b),max(p[0] for p in b),max(p[1] for p in b)) for b in boxes]
    groups=[]
    for i in sorted(range(len(texts)),key=lambda n:(bounds[n][0],(bounds[n][1]+bounds[n][3])/2)):
        x,y,r,b=bounds[i];h=max(1,b-y);match=None
        for group in groups:
            gx,gy,gr,gb=group['bounds'];gh=max(1,gb-gy)
            gap=x-gr;overlap=min(b,gb)-max(y,gy)
            if r-x<h*.65 or gr-gx<gh*.65:continue # vertical columns
            overlap_limit=min(.2*min(r-x,gr-gx),1.25*min(h,gh))
            gap_limit=(4 if texts[group['indices'][-1]].rstrip().endswith(('…','・','.'))
                and texts[i].rstrip().endswith(('」','』','）')) else 3)*max(h,gh)
            if .65<=h/gh<=1.5 and abs((y+b)-(gy+gb))/2<=.35*min(h,gh) and overlap>=.65*min(h,gh) and -overlap_limit<=gap<=gap_limit:
                match=group;break
        if match is None:groups.append({'indices':[i],'bounds':(x,y,r,b)})
        else:
            match['indices'].append(i);gx,gy,gr,gb=match['bounds'];match['bounds']=(min(x,gx),min(y,gy),max(r,gr),max(b,gb))
    merged_texts=[];merged_scores=[];merged_boxes=[]
    groups=sorted(groups,key=lambda g:(g['bounds'][1],g['bounds'][0]))
    for group in groups:
        indices=sorted(group['indices'],key=lambda n:bounds[n][0]);x,y,r,b=group['bounds']
        merged_texts.append(''.join(texts[i] for i in indices))
        weights=[max(1,len(texts[i])) for i in indices]
        merged_scores.append(sum(scores[i]*w for i,w in zip(indices,weights))/sum(weights))
        merged_boxes.append([[x,y],[r,y],[r,b],[x,b]])
    repairs=[i for i,group in enumerate(groups) if len(group['indices'])>1][:8]
    if recognize is not None and repairs:
        import math
        for i,result in zip(repairs,recognize([merged_boxes[i] for i in repairs])):
            if result is None:continue
            text,score=result
            if isinstance(text,str) and text.strip() and '\n' not in text and math.isfinite(score) and .5<=score<=1:
                merged_texts[i]=text;merged_scores[i]=score
    return merged_texts,merged_scores,merged_boxes

def paired_quotes(text):
    # OCR often confuses the two closing corner-bracket shapes next to a cursor.
    # Only an unambiguous single outer quote can establish the intended pair.
    if '\n' in text:text='\n'.join(paired_quotes(row) for row in text.split('\n'))
    if text.startswith('[') and text.endswith('」') and not any(c in text[1:-1] for c in '[]「」『』'):
        return '「'+text[1:]
    if text.startswith('「') and text.endswith('』') and text.count('「')==1 and '『' not in text:
        return text[:-1]+'」'
    if text.startswith('『') and text.endswith('」') and text.count('『')==1 and '「' not in text:
        return text[:-1]+'』'
    return text

def numbered_pager(texts,boxes):
    """Recognize spaced 1..10 page cells before joined OCR mangles their digits."""
    if not texts or boxes is None or len(texts)!=len(boxes):return False
    cells=[]
    for text,box in zip(texts,boxes):
        value=text.strip()
        if not value.isdecimal() or len(value)>2 or not 1<=int(value)<=10:continue
        x=min(p[0] for p in box);r=max(p[0] for p in box)
        y=min(p[1] for p in box);b=max(p[1] for p in box);h=b-y
        if h>0 and r-x<=3*h:cells.append((int(value),(x+r)/2,(y+b)/2,h))
    for value,right,y,h in cells:
        if value!=10:continue
        row=sorted((c for c in cells if c[1]<=right and .65*h<=c[3]<=1.5*h
            and abs(c[2]-y)<=.5*min(h,c[3])),key=lambda c:c[1])
        if len(row)<6:continue
        first,left,_,_=row[0]
        if first==10:continue
        pitch=(right-left)/(10-first)
        if pitch<1.8*h:continue
        run=longest=1
        for a,b in zip(row,row[1:]):
            run=run+1 if b[0]==a[0]+1 else 1;longest=max(longest,run)
        if longest>=5 and all(a[0]<b[0] for a,b in zip(row,row[1:])) and all(
                abs(x-(left+(n-first)*pitch))<=.4*pitch for n,x,_,_ in row):return True
    return False

def dialogue_indices(texts, boxes):
    if not texts or len(texts)!=len(boxes):return list(range(len(texts)))
    bounds=[(min(p[0] for p in box),min(p[1] for p in box),
             max(p[0] for p in box),max(p[1] for p in box)) for box in boxes]
    def japanese(c):return '\u3040'<=c<='\u30ff' or '\u3400'<=c<='\u9fff'
    # Save/load previews form several separated text columns above a wide
    # numeric pager. Neither a number nor multiple columns alone is a menu.
    for n,text in enumerate(texts):
        digits=''.join(text.split());fx,fy,fr,fb=bounds[n]
        if len(digits)<8 or not digits.isdecimal():continue
        previews=[i for i,t in enumerate(texts) if bounds[i][3]<fy
            and bounds[i][2]-bounds[i][0]>=2*(bounds[i][3]-bounds[i][1]) and sum(japanese(c) for c in t)>=4]
        for i in previews:
            x,y,r,b=bounds[i];h=b-y
            row=sorted((j for j in previews if abs((bounds[j][1]+bounds[j][3])-(y+b))/2
                <=.5*min(h,bounds[j][3]-bounds[j][1])),key=lambda j:bounds[j][0])
            columns=[]
            for j in row:
                if not columns or bounds[j][0]-bounds[columns[-1]][2]>=2*max(h,bounds[j][3]-bounds[j][1]):columns.append(j)
            if len(columns)>=3 and fr-fx>1.25*max(bounds[j][2]-bounds[j][0] for j in columns):return []
    quoted=[i for i,t in enumerate(texts) if t.strip().startswith(('「','『','〔','['))
            and any(japanese(c) for c in t)]
    candidates=quoted or [i for i,t in enumerate(texts) if sum(japanese(c) for c in t)>=6]
    # No long line to establish layout: preserve short lines, including one kanji.
    if not candidates:return list(range(len(texts)))
    seed=max(candidates,key=lambda i:bounds[i][2]-bounds[i][0])
    left,top,right,bottom=bounds[seed];height=max(1,bottom-top)
    compatible=[]
    for i,(x,y,r,b) in enumerate(bounds):
        h=b-y
        if .55*height<=h<=1.6*height and abs(x-left)<=3*height:
            compatible.append(i)
    kept={seed}
    while True:
        connected={i for i in compatible if any(
            max(bounds[i][1]-bounds[j][3],bounds[j][1]-bounds[i][3],0)<=4*height
            for j in kept)}
        if connected<=kept:break
        kept.update(connected)
    return [i for i in range(len(texts)) if i in kept]
