import unittest

from app.vibevoice_units import choose_repair_unit, parent_quality, repair_units


def parent(text, index=3, heading=False):
    value = {"index": index, "identity": "parent-identity", "text": text}
    if heading:
        value["heading"] = text
    return value


class VibeVoiceUnitsTests(unittest.TestCase):
    def test_sentence_policy_keeps_long_sentences_and_original_words(self):
        text = ' '.join(['A quiet road'] * 24) + ' leads into New York. Then we went home.'
        units = repair_units(parent(text), target_words=40, max_words=55,
                             boundary_policy='sentences_v4', max_chars=1000)
        self.assertEqual([u['text'] for u in units], [text.removesuffix(' Then we went home.'), 'Then we went home.'])
        self.assertGreater(len(units[0]['text'].split()), 55)
        self.assertEqual(' '.join(u['text'] for u in units), text)
        legacy = repair_units(parent(text), target_words=40, max_words=55)
        self.assertTrue(all(len(u['text'].split()) <= 55 for u in legacy))

    def test_sentence_policy_packs_to_character_limit_without_splitting(self):
        text = 'The remarkable visitor arrived. Another remarkable visitor departed.'
        units = repair_units(parent(text), target_words=75, max_words=100,
                             boundary_policy='sentences_v4', max_chars=40)
        self.assertEqual([u['text'] for u in units], ['The remarkable visitor arrived.', 'Another remarkable visitor departed.'])
        long_text = ' '.join(['unbroken'] * 200) + '.'
        units = repair_units(parent(long_text), boundary_policy='sentences_v4', max_chars=1000)
        self.assertEqual([u['text'] for u in units], [long_text])

    def test_sentence_policy_recognizes_notes_and_splits_long_lists_at_semicolons(self):
        from app.vibevoice_units import _sentence_parts, repair_limits
        self.assertEqual(_sentence_parts('They left.⁷ Then we stayed.* Another day.', 'sentences_v4'),
                         ['They left.⁷', 'Then we stayed.*', 'Another day.'])
        text = 'Alice Example; Robert F. Smith; ' * 40 + 'Zoe Last.'
        units = repair_units(parent(text), target_words=75, max_words=100,
                             boundary_policy='sentences_v4', max_chars=1000)
        self.assertEqual(' '.join(u['text'] for u in units), text)
        self.assertTrue(all(u['text'].endswith((';', '.')) for u in units))
        self.assertTrue(all(len(u['text']) <= 1000 for u in units))
        limits = repair_limits(parent(text), {'backend':'drama3', 'unit_boundary_policy':'sentences_v4',
            'drama3_unit_limits':{'target_words':75,'max_words':100}, 'drama3_list_max_words':35})
        self.assertEqual((limits['target_words'],limits['max_words']), (75,100))

    def test_sentence_preserving_passages_keep_oversize_paragraphs_and_continuations(self):
        from app.vibevoice_plan import pack_passages
        beginning = ' '.join(['quiet'] * 450) + ' New'
        blocks = [{'text': beginning, 'source_page': 1},
                  {'text': 'York was silent.', 'source_page': 2}, {'text': 'We left.', 'source_page': 2}]
        passages = pack_passages(blocks, preserve_sentences=True)
        self.assertEqual(passages[0]['text'], beginning + ' York was silent.')
        self.assertEqual(passages[0]['source_pages'], [1, 2])
        self.assertEqual(passages[1]['text'], 'We left.')

    def test_caption_boundaries_are_opt_in_and_keep_credit_words(self):
        from app.vibevoice_units import _sentence_parts
        text = 'The story ends. (Author collection) This is the house. (They rebuilt it.) Another scene begins.'
        self.assertEqual(_sentence_parts(text,'captions_v3'), [
            'The story ends.', '(Author collection) This is the house.', '(They rebuilt it.)', 'Another scene begins.'])
        self.assertEqual(_sentence_parts(text,'initials_v2'), [text])
        source=parent(text)
        units=repair_units(source,target_words=1,max_words=10,boundary_policy='captions_v3')
        self.assertEqual(' '.join(u['text'] for u in units),text)
        self.assertTrue(any('Author collection' in u['text'] for u in units))

    def test_passage_repair_budget_changes_only_the_named_passage(self):
        from app.vibevoice_units import repair_limits
        source = parent('One short sentence. Another short sentence. Last short sentence.')
        other = dict(source, identity='untouched-parent')
        config = {'backend':'drama3', 'drama3_unit_limits':{'target_words':40,'max_words':55},
                  'drama3_passage_unit_limits':{source['identity']:{'target_words':3,'max_words':4}}}
        repaired = repair_units(source, **repair_limits(source,config))
        untouched = repair_units(other, **repair_limits(other,config))
        self.assertEqual(len(repaired),3)
        self.assertEqual(len(untouched),1)
        self.assertEqual(' '.join(u['text'] for u in repaired),source['text'])
        self.assertEqual(repair_limits(source,dict(config,backend='vibevoice')), {})

    def test_initials_titles_and_real_clock_sentence_ends(self):
        from app.vibevoice_units import _sentence_parts
        for name in ('Dr. Evan I. Mercer', 'O. T. Arden', 'J. R. R. Vale', 'Ms. Ada K. Reed'):
            text = name + ' arrived. Tomorrow we leave.'
            self.assertEqual(_sentence_parts(text), [name + ' arrived.', 'Tomorrow we leave.'])
        self.assertEqual(_sentence_parts('We left at 9 p.m. Tomorrow is free.'),
                         ['We left at 9 p.m.', 'Tomorrow is free.'])
        self.assertEqual(_sentence_parts('We left at 9 a.m. and came home.'),
                         ['We left at 9 a.m. and came home.'])
        self.assertEqual(_sentence_parts('The door is ajar. Now leave.'), ['The door is ajar.', 'Now leave.'])
        self.assertEqual(_sentence_parts('So did I. Tomorrow we leave.'), ['So did I.', 'Tomorrow we leave.'])

    def test_preserves_normalized_prose_and_compatible_fields(self):
        text = "  First sentence.\nSecond sentence!  Third sentence? "
        source = parent(text)
        units = repair_units(source, target_words=2, max_words=10)
        self.assertEqual(" ".join(unit["text"] for unit in units), "First sentence. Second sentence! Third sentence?")
        self.assertEqual([unit["index"] for unit in units], [30000, 30001, 30002])
        self.assertTrue(all(unit["speaker_text"] == "Speaker 0: " + unit["text"] for unit in units))
        self.assertTrue(all(unit["parent_index"] == 3 for unit in units))

    def test_dialogue_and_common_abbreviation_stay_in_source_order(self):
        text = 'Dr. Vale said, "Wait here." Then she left. The value was 3.14. "Do not follow," he called.'
        units = repair_units(parent(text), target_words=4, max_words=8)
        self.assertEqual(" ".join(unit["text"] for unit in units), text)
        self.assertEqual(units[0]["text"], 'Dr. Vale said, "Wait here."')

    def test_oversize_sentence_uses_existing_safe_splitter(self):
        text = " ".join(f"word{index}" for index in range(181))
        units = repair_units(parent(text), target_words=120, max_words=180)
        self.assertEqual([len(unit["text"].split()) for unit in units], [180, 1])
        self.assertEqual(" ".join(unit["text"] for unit in units), text)

    def test_headings_remain_whole(self):
        text = "A Heading With More Than Three Words"
        units = repair_units(parent(text, heading=True), target_words=2, max_words=3)
        self.assertEqual([unit["text"] for unit in units], [text])

    def test_unit_identity_changes_with_parent_text_or_ordinal(self):
        text = "Same words. Same words."
        units = repair_units(parent(text), target_words=2, max_words=2)
        changed_parent = dict(parent(text)); changed_parent["identity"] = "other-parent"
        changed_text = repair_units(parent("Changed words. Same words."), target_words=2, max_words=2)[0]["identity"]
        self.assertNotEqual(units[0]["identity"], units[1]["identity"])
        self.assertNotEqual(units[0]["identity"], repair_units(changed_parent, target_words=2, max_words=2)[0]["identity"])
        self.assertNotEqual(units[0]["identity"], changed_text)

    def test_parent_gate_uses_concatenated_unit_transcripts(self):
        source = parent("one two three four five six. seven eight nine ten eleven twelve.")
        units = repair_units(source, target_words=6, max_words=12)
        reports = [{"unit_index": unit["unit_index"], "transcript": unit["text"]} for unit in units]
        reports[0]["transcript"] = "one two"
        result = parent_quality(source, reports)
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(result["missing_words"], 4)


    def test_parent_quality_uses_explicit_validated_unit_manifest(self):
        source = parent("one two. three four. five six. seven eight.")
        units = repair_units(source, target_words=2, max_words=2)
        reports = [{"unit_index": unit["unit_index"], "transcript": unit["text"]} for unit in units]
        self.assertTrue(parent_quality(source, reports, units)["ok"])
        stale = [dict(unit) for unit in units]
        stale[0]["identity"] = "wrong"
        with self.assertRaisesRegex(ValueError, "identity"):
            parent_quality(source, reports, stale)

    def test_choose_repair_unit_prefers_largest_then_first(self):
        units = repair_units(parent("one two. three four. five six."), target_words=2, max_words=2)
        reports = [
            {"unit_index": 0, "transcript": units[0]["text"], "missing_words": 1, "inserted_words": 1, "differences": [{}]},
            {"unit_index": 1, "transcript": units[1]["text"], "missing_words": 3, "inserted_words": 0, "differences": [{}]},
            {"unit_index": 2, "transcript": units[2]["text"], "missing_words": 3, "inserted_words": 0, "differences": [{}]},
        ]
        self.assertEqual(choose_repair_unit(units, reports)["unit_index"], 1)
        self.assertEqual(choose_repair_unit(units, reports, exclude={1})["unit_index"], 2)
        with self.assertRaisesRegex(ValueError, "no repairable"):
            choose_repair_unit(units, reports, exclude={0, 1, 2})
        for report in reports:
            report.update(missing_words=0, inserted_words=0, differences=[])
        with self.assertRaisesRegex(ValueError, "no repairable"):
            choose_repair_unit(units, reports)


if __name__ == "__main__":
    unittest.main()
