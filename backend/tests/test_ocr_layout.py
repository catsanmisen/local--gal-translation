from pathlib import Path
import sys
import unittest
import ocr_layout
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ocr_layout import dialogue_indices,paired_quotes,merge_line_fragments,repair_quote_edges

def box(x,y,w,h=28):return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]

class LayoutTests(unittest.TestCase):
    def test_small_attached_kana_reading_above_latin_logo_is_not_body(self):
        bounds=[box(528,348,206,26),box(314,380,653,77)]
        for reading in ['ぱりおしょう！-','ぱｈおしょう！-','ぱりおしょう！']:
            self.assertEqual(ocr_layout.reading_indices([reading,"FHLEOFTOLOIE'T"],bounds),[1])

    def test_latin_reading_rule_preserves_real_short_or_quoted_and_detached_text(self):
        bounds=[box(528,348,206,26),box(314,380,653,77)]
        for source in [['はい', 'PALEONTOLOGY'],['「ありがとう」','PALEONTOLOGY'],['〔ありがとう〕','PALEONTOLOGY'],['ありがとう〉','PALEONTOLOGY'],['明日は晴れ','PALEONTOLOGY'],['ありがとう','Englishのせりふ']]:
            self.assertEqual(ocr_layout.reading_indices(source,bounds),[0,1])
        for other in [box(314,380,653,26),box(900,380,653,77),box(314,600,653,77),box(314,200,653,77)]:
            self.assertEqual(ocr_layout.reading_indices(['ありがとう','PALEONTOLOGY'],[bounds[0],other]),[0,1])
        self.assertEqual(ocr_layout.reading_indices(['ありがとう'],[bounds[0]]),[0])

    def test_existing_kanji_ruby_filter_remains_geometric(self):
        self.assertEqual(ocr_layout.reading_indices(['たかこ','貴子'],[box(12,0,30,12),box(10,13,80,28)]),[1])

    def test_low_confidence_upright_tail_is_reread_once_in_its_original_orientation(self):
        seen=[];texts=['期待してるんだ。','そんな気持ちで。','-とと']
        bounds=[box(65,8,1144,38),box(46,59,1166,36),box(50,115,103,28)]
        def recognize(regions):seen.extend(regions);return [('いって',.9975)]
        result=ocr_layout.reread_uncertain_rows(texts,[.96447,.99921,.72918],bounds,recognize)
        self.assertEqual(result[0],texts[:2]+['いって']);self.assertEqual(result[1][-1],.9975)
        self.assertEqual(len(seen),1);self.assertEqual(seen[0],bounds[-1])

    def test_uncertain_reread_preserves_single_short_dialogue_and_vertical_text(self):
        def unexpected(_):self.fail('no coherent upright neighbours for a reread')
        for texts,scores,bounds in [(['約束'],[.7],[box(0,0,60)]),
                (['明日','約束','本当'],[.99,.99,.7],[box(0,0,60),box(0,50,60),box(0,800,60)]),
                (['長い本文。','別の本文。','縦書き'],[.99,.99,.7],[box(0,0,200),box(0,50,200),box(0,100,25,120)])]:
            self.assertEqual(ocr_layout.reread_uncertain_rows(texts,scores,bounds,unexpected)[0],texts)

    def test_uncertain_reread_does_not_accept_empty_or_weak_replacements_or_unbounded_work(self):
        texts=['本文一。','本文二。','短句','別句'];bounds=[box(0,i*50,200) for i in range(4)]
        for replacement in [('',.99),('別文',.75),('別文',float('nan'))]:
            calls=[]
            def recognize(regions):calls.append(regions);return [replacement]
            result=ocr_layout.reread_uncertain_rows(texts,[.99,.99,.7,.75],bounds,recognize)
            self.assertEqual(result[0],texts);self.assertEqual(len(calls),1);self.assertEqual(len(calls[0]),1)

    def test_observed_parenthesis_crop_is_reread_without_changing_body(self):
        original='どん、どん、どん、どん、どん、どん〉';seen=[]
        def recognize(boxes):seen.extend(boxes);return [('（どん、どん、どん、どん、どん、どん）',.97095)]
        text,scores,boxes=repair_quote_edges([original],[.96473],[box(64,7,611,39)],recognize,1280,219)
        self.assertEqual(text,['（どん、どん、どん、どん、どん、どん）'])
        self.assertEqual(scores,[.97095]);self.assertEqual(boxes,seen)
        self.assertLess(boxes[0][0][0],64);self.assertGreater(boxes[0][1][0],675)
    def test_complete_quotes_and_ordinary_dialogue_skip_edge_recognition(self):
        def unexpected(boxes):self.fail('no extra OCR for already complete text')
        source=['「約束」','（明日）','今日は晴れ。']
        self.assertEqual(repair_quote_edges(source,[1]*3,[box(0,0,100)]*3,unexpected,200,100)[0],source)
    def test_quote_reread_refuses_changed_tokens_body_and_lower_confidence(self):
        original='%s、%d〉'
        for candidate,score in [('（%d、%s）',.99),('（%s）',.99),('（%s、%d）',.8),('（%s、%d）',float('nan'))]:
            result=repair_quote_edges([original],[.95],[box(0,0,95)],lambda _: [(candidate,score)],100,50)
            self.assertEqual(result[0],[original])
    def test_edge_reread_is_bounded_and_clipped_to_actual_image(self):
        seen=[]
        def recognize(boxes):seen.extend(boxes);return [('（明日）',1)]*len(boxes)
        result=repair_quote_edges(['明日)']*10,[.9]*10,[box(0,0,100,50)]*10,recognize,100,50)
        self.assertEqual(len(seen),8);self.assertEqual(result[0][-2:],['明日)']*2)
        self.assertTrue(all(0<=x<=100 and 0<=y<=50 for b in seen for x,y in b))
    def test_same_line_continuation_survives_dialogue_filter(self):
        texts=['「はあっ、はあっ、はあっ、に','はあっ、はあっ、はあっ、はぁつ」']
        merged,scores,boxes=merge_line_fragments(texts,[.94,.92],[box(33,12,458,44),box(466,13,550,43)])
        self.assertEqual(merged,[''.join(texts)])
        self.assertEqual(dialogue_indices(merged,boxes),[0])
        self.assertAlmostEqual(boxes[0][1][0],1016)
        self.assertTrue(.92<=scores[0]<=.94)
    def test_adjacent_fragments_keep_rows_and_spatial_reading_order(self):
        merged,_,_=merge_line_fragments(['明日。','から','「今日','また'],[1]*4,
            [box(10,60,70),box(118,20,65),box(10,20,90),box(95,60,60)])
        self.assertEqual(merged,['「今日から','明日。また'])
    def test_distant_same_height_decoration_is_not_merged(self):
        merged,_,boxes=merge_line_fragments(['「ここにいる。','看板'],[1,1],[box(10,10,200),box(650,10,60)])
        self.assertEqual(merged,['「ここにいる。','看板'])
        self.assertEqual(dialogue_indices(merged,boxes),[0])
    def test_observed_ellipsis_gap_keeps_the_closing_dialogue_fragment(self):
        texts=['〔恐いけど、みんなの気持ちに気づいたから。みん','な、ごめん！','あたし、勘違いしてたんだ・','ビめん」']
        bounds=[box(65,8,1114,37),box(47,62,218,31),box(279,60,415,33),box(816,60,109,34)]
        merged,_,boxes=merge_line_fragments(texts,[.98,.99,.98,.67],bounds)
        self.assertEqual(merged,[texts[0],''.join(texts[1:])])
        self.assertEqual(dialogue_indices(merged,boxes),[0,1])
    def test_ellipsis_gap_does_not_attach_unquoted_labels_or_distant_columns(self):
        for source,bounds in [(['本文・','看板'],[box(0,0,200),box(300,0,60)]),
                (['本文。','看板」'],[box(0,0,200),box(300,0,60)]),
                (['本文・','後半」'],[box(0,0,200),box(600,0,100)])]:
            with self.subTest(source=source):self.assertEqual(merge_line_fragments(source,[1,1],bounds)[0],source)
    def test_slightly_higher_right_fragment_still_joins_left_to_right(self):
        merged,_,_=merge_line_fragments(['後半。','前半'],[1,1],[box(110,8,80),box(10,10,90)])
        self.assertEqual(merged,['前半後半。'])
    def test_ruby_and_vertical_columns_are_not_joined(self):
        texts=['本文','ふりがな','一列目','二列目']
        merged,_,_=merge_line_fragments(texts,[1]*4,[box(10,50,80,30),box(100,48,40,12),box(10,130,25,120),box(50,130,25,120)])
        self.assertCountEqual(merged,texts)
    def test_overlapping_duplicate_detections_are_not_concatenated(self):
        merged,_,_=merge_line_fragments(['同じ台詞。','同じ台詞。'],[1,1],[box(10,10,140),box(12,10,140)])
        self.assertEqual(merged,['同じ台詞。','同じ台詞。'])
    def test_joined_recognition_replaces_overlap_damage_without_adding_newline(self):
        merged,scores,_=merge_line_fragments(['「前半に','後半」'],[.8,.9],[box(10,10,100),box(94,11,110)],lambda boxes:[('「前半後半」',.95)])
        self.assertEqual(merged,['「前半後半」']);self.assertEqual(scores,[.95])
    def test_failed_or_low_confidence_joined_reading_preserves_detected_text(self):
        for reading in ('',None,'不可靠'):
            merged,_,_=merge_line_fragments(['前半','後半'],[.8,.9],[box(10,10,100),box(114,10,100)],lambda boxes:[(reading,.1)])
            self.assertEqual(merged,['前半後半'])
    def test_joined_reading_has_one_bounded_batch(self):
        calls=[];texts=[];boxes=[]
        for row in range(12):texts+=['前','後'];boxes+=[box(10,row*60,80),box(100,row*60,80)]
        def recognize(bounds):calls.append(len(bounds));return [('前後',.9)]*len(bounds)
        merged,_,_=merge_line_fragments(texts,[.9]*24,boxes,recognize)
        self.assertEqual(calls,[8]);self.assertEqual(len(merged),12)
    def test_outer_quote_shape_fluctuation_keeps_one_consistent_line(self):
        self.assertEqual(paired_quotes('「ここが新しい家よ』'),'「ここが新しい家よ」')
        self.assertEqual(paired_quotes('『明日」'),'『明日』')
    def test_observed_square_opening_with_single_corner_closer_keeps_quote_pair(self):
        self.assertEqual(paired_quotes('[あたしも……あたしも、そうだったんだ！」'),
            '「あたしも……あたしも、そうだったんだ！」')
        self.assertEqual(paired_quotes('[あたしも……\nそうだったんだ！」'),
            '「あたしも……\nそうだったんだ！」')
    def test_square_opening_repair_preserves_balanced_nested_and_unclosed_text(self):
        for text in ('[選択肢]','[まだ続く','[外側「内側」','[選択肢]と聞いた」','[前[後」','[あたしも……\nあたしも、そうだったんだ！'):
            with self.subTest(text=text):self.assertEqual(paired_quotes(text),text)
    def test_nested_quotes_and_kanji_short_lines_are_not_rewritten(self):
        for text in ('「『明日』と聞いた』','力','「名前」','ここに』'):
            self.assertEqual(paired_quotes(text),text)
    def test_accumulated_quote_and_wrapped_quote_both_keep_consistent_pairing(self):
        self.assertEqual(paired_quotes('「ここが新しい家よ』\nと、母が言った。'),'「ここが新しい家よ」\nと、母が言った。')
        self.assertEqual(paired_quotes('「山を降りたと\nころにある家よ』'),'「山を降りたと\nころにある家よ」')
    def test_remote_background_label_is_not_dialogue(self):
        self.assertEqual(dialogue_indices(['その年、私の家族は引越しをした。','カ'],
            [box(20,20,400),box(740,510,35,45)]),[0])
    def test_numbered_preview_grid_is_not_a_dialogue_block(self):
        texts=['One of a kind','One of a kind','エピローグ',
            '[あれ？被ってきたんだ？」','……まー、そうなんだけどさ。',
            'だから、風景的に夏と違う所は','あまりない。それでも秋だって思う','2３4５6７1８10']
        bounds=[box(46,6,116,18),box(407,5,116,19),box(767,6,97,18),
            box(56,28,251,21),box(417,26,264,24),box(778,29,283,18),
            box(768,53,305,18),box(543,132,456,28)]
        self.assertEqual(dialogue_indices(texts,bounds),[])
    def test_sparse_save_page_is_identified_before_digit_fragments_are_joined(self):
        texts=['-','3','4','５','６','７','Ｂ','10',',']
        bounds=[box(494,136,12,19),box(600,136,19,20),box(642,136,58,21),
            box(702,137,23,18),box(756,137,23,18),box(803,137,28,18),
            box(864,137,19,18),box(963,135,36,23),box(1032,129,39,37)]
        self.assertTrue(ocr_layout.numbered_pager(texts,bounds))
    def test_ordinary_numbers_are_not_a_spaced_page_selector(self):
        for texts,bounds in [(['1234567890'],[box(0,0,400)]),
                (['3','4','5','6','7'],[box(i*54,0,20,20) for i in range(5)]),
                (['3','4','5','6','7','10'],[box(0,i*54,20,20) for i in range(6)]),
                (['3','4','5','6','7','10'],[box(i*22,0,20,20) for i in range(6)]),
                (['3','4','5','6','7','10'],[box(i*54,0,20,20) for i in range(6)]),
                (['3','7','5','4','6','10'],[box(i*54,0,20,20) for i in range(6)])]:
            with self.subTest(texts=texts,bounds=bounds):self.assertFalse(ocr_layout.numbered_pager(texts,bounds))
    def test_numbers_or_columns_alone_do_not_make_dialogue_a_preview_grid(self):
        text=['最初の台詞。','次の台詞。','別の台詞。']
        columns=[box(20,20,200),box(300,20,200),box(580,20,200)]
        for texts,bounds in [(text,columns),
                (['電話番号です。','1234567890'],[box(20,20,200),box(20,90,320)]),
                (text+['12'],columns+[box(200,90,400)]),
                (text+['1234567890'],columns+[box(200,90,200)]),
                (text+['1234567890'],columns+[box(200,0,400)]),
                (text+['1234567890'],[box(20,i*50,200) for i in range(4)])]:
            with self.subTest(texts=texts,bounds=bounds):self.assertTrue(dialogue_indices(texts,bounds))
    def test_short_kanji_and_multiline_body_survive(self):
        self.assertEqual(dialogue_indices(['昔からよく覚えている。','力','約束'],
            [box(20,20,300),box(20,92,28),box(20,164,56)]),[0,1,2])
    def test_all_short_lines_are_preserved(self):
        self.assertEqual(dialogue_indices(['明日','力'],[box(500,20,56),box(20,250,28)]),[0,1])
    def test_quoted_short_dialogue_excludes_remote_decoration(self):
        self.assertEqual(dialogue_indices(['「いつの？」','カ','喫茶店の看板文字'],
            [box(20,20,100),box(740,510,35,45),box(650,470,230,16)]),[0])
    def test_short_quote_and_its_adjacent_kanji_row_are_retained(self):
        self.assertEqual(dialogue_indices(['「明日」','約束','看板'],
            [box(20,20,100),box(20,55,56),box(680,440,56)]),[0,1])
    def test_wrapped_rows_and_paragraphs_form_one_block(self):
        self.assertEqual(dialogue_indices(['昔からよく覚えている長い台詞。','それでもここにいる。','明日'],
            [box(20,20,500),box(40,55,300),box(20,127,56)]),[0,1,2])
