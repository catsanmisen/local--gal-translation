"""Offline RapidOCR CPU JSON worker, launched only by OcrService."""
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import socket
import sys
import time
import warnings
from ocr_layout import dialogue_indices,paired_quotes,merge_line_fragments,repair_quote_edges,reread_uncertain_rows,numbered_pager,reading_indices

ROOT=Path(__file__).resolve().parents[2]

def main():
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    # This worker has no network role. Any implicit library download must fail visibly.
    def offline(*args,**kwargs):raise OSError('OCR 运行时禁止网络下载')
    socket.socket.connect=offline;socket.socket.connect_ex=offline
    engine=None
    for line in sys.stdin:
        rid=None
        try:
            request=json.loads(line);rid=request['id'];raw=base64.b64decode(request['png'],validate=True)
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height>2_000_000 or image.width<1 or image.height<1:raise ValueError('识别区域超过200万像素。')
                image=image.convert('RGB')
                # Small old-game glyphs benefit from CPU-only 2x interpolation.
                if image.height<160 and image.width<=1000:image=image.resize((image.width*2,image.height*2),Image.Resampling.BICUBIC)
                import numpy as np
                pixels=np.asarray(image)
            started=time.monotonic()
            with redirect_stdout(sys.stderr):
                if engine is None:
                    from rapidocr import RapidOCR,OCRVersion,ModelType
                    f=ROOT/'backend/vendor/ocr'
                    engine=RapidOCR(params={'Global.log_level':'error','Global.text_score':.5,
                        'EngineConfig.onnxruntime.use_cuda':False,'EngineConfig.onnxruntime.use_dml':False,
                        'EngineConfig.onnxruntime.intra_op_num_threads':2,'EngineConfig.onnxruntime.inter_op_num_threads':1,
                        'Det.ocr_version':OCRVersion.PPOCRV4,'Det.model_type':ModelType.MOBILE,'Det.model_path':str(f/'ch_PP-OCRv4_det_mobile.onnx'),
                        'Cls.ocr_version':OCRVersion.PPOCRV4,'Cls.model_type':ModelType.MOBILE,'Cls.model_path':str(f/'ch_ppocr_mobile_v2.0_cls_mobile.onnx'),
                        'Rec.ocr_version':OCRVersion.PPOCRV4,'Rec.model_type':ModelType.MOBILE,'Rec.lang_type':'japan','Rec.model_path':str(f/'japan_PP-OCRv4_rec_mobile.onnx')})
                result=engine(pixels)
            texts=[] if result.txts is None else list(result.txts)
            scores=[] if result.scores is None else [float(n) for n in result.scores]
            boxes=None if result.boxes is None else np.asarray(result.boxes)
            all_boxes=boxes
            raw_text='\n'.join(texts)
            is_menu=False
            if boxes is not None and len(boxes)==len(texts):
                is_menu=numbered_pager(texts,boxes)
                keep=reading_indices(texts,boxes)
                texts=[texts[i] for i in keep];scores=[scores[i] for i in keep];boxes=boxes[keep]
                extra_recognition_used=False
                def recognize_joined(joined_boxes):
                    nonlocal extra_recognition_used
                    # All layout repairs share this capture's one extra batch.
                    if extra_recognition_used:return []
                    extra_recognition_used=True
                    crops=[]
                    for joined in joined_boxes:
                        lo=np.floor(np.asarray(joined).min(axis=0)).astype(int);hi=np.ceil(np.asarray(joined).max(axis=0)).astype(int)
                        x,y=max(0,lo[0]),max(0,lo[1]);r,b=min(pixels.shape[1],hi[0]),min(pixels.shape[0],hi[1])
                        crops.append(pixels[y:b,x:r].copy())
                    # One bounded CPU recognition batch; no second detection or
                    # language-model inference. Reading the joined crop avoids
                    # duplicated/mangled characters at overlapping split edges.
                    with redirect_stdout(sys.stderr):joined=engine.recognize_txt(crops)
                    if joined.txts is None or joined.scores is None:return []
                    return [(str(t),float(s)) for t,s in zip(joined.txts,joined.scores)]
                texts,scores,merged=merge_line_fragments(texts,scores,boxes,recognize_joined)
                boxes=np.asarray(merged)
                body=[] if is_menu else dialogue_indices(texts,boxes)
                # Geometry separates remote background labels from the dialogue block.
                # Keep nearby ruby bounds for subtitle avoidance, not remote decoration.
                if len(body)<len(texts):
                    main_boxes=boxes[body]
                    if body:
                        lo=main_boxes.reshape(-1,2).min(axis=0);hi=main_boxes.reshape(-1,2).max(axis=0)
                        margin=max(1,float((main_boxes.max(axis=1)-main_boxes.min(axis=1))[:,1].max()))
                        all_boxes=np.asarray([b for b in all_boxes if b[:,0].max()>=lo[0]-margin and b[:,0].min()<=hi[0]+margin and b[:,1].max()>=lo[1]-margin and b[:,1].min()<=hi[1]+margin])
                    else:all_boxes=None;is_menu=True
                    texts=[texts[i] for i in body];scores=[scores[i] for i in body];boxes=boxes[body]
                texts,scores,repaired=reread_uncertain_rows(texts,scores,boxes,recognize_joined)
                boxes=np.asarray(repaired)
                texts,scores,repaired=repair_quote_edges(texts,scores,boxes,recognize_joined,pixels.shape[1],pixels.shape[0])
                boxes=np.asarray(repaired)
                if len(boxes):all_boxes=np.concatenate([all_boxes,boxes])
            response={'id':rid,'text':paired_quotes('\n'.join(texts)),'scores':scores,'ocr_ms':round((time.monotonic()-started)*1000,2)}
            if is_menu:response['is_menu']=True
            if boxes is not None and len(boxes):
                low=boxes.min(axis=1);high=boxes.max(axis=1)
                response['text_regions']=[{'x':float(lo[0]/pixels.shape[1]),'y':float(lo[1]/pixels.shape[0]),'width':float((hi[0]-lo[0])/pixels.shape[1]),'height':float((hi[1]-lo[1])/pixels.shape[0])} for lo,hi in zip(low,high)]
            if raw_text!=response['text']:response['raw_text']=raw_text
            if all_boxes is not None and len(all_boxes):
                # Include reading annotations for placement, even when they are not dialogue.
                points=all_boxes.reshape(-1,2)
                low=np.maximum(points.min(axis=0),0);high=np.minimum(points.max(axis=0),[pixels.shape[1],pixels.shape[0]])
                response['text_bounds']={'x':float(low[0]/pixels.shape[1]),'y':float(low[1]/pixels.shape[0]),
                    'width':float((high[0]-low[0])/pixels.shape[1]),'height':float((high[1]-low[1])/pixels.shape[0])}
        except Exception as e:response={'id':rid,'error':str(e)[:300]}
        sys.stdout.write(json.dumps(response,ensure_ascii=False)+'\n');sys.stdout.flush()

if __name__=='__main__':main()
