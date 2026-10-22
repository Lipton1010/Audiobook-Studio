import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import vibevoice_quality as quality
from app.vibevoice_quality import assess, numbered_heading_assessment, words


class VibeVoiceQualityTests(unittest.TestCase):
    def test_notation_equivalence_preserves_adjacent_meaning_at_production_threshold(self):
        for expected, heard in (
            ('Tea & coffee cost 98% of the budget.', 'Tea and coffee cost 98 percent of the budget.'),
            ('It was 8½ inches at 3 p.m.', 'It was eight and a half inches at three pm.'),
            ('They re-entered the lovers\' room.', "They reentered the lover's room."),
            ('He co-starred in A.D. 90.', 'He costarred in AD ninety.'),
        ):
            report = quality.assess_narration(expected, heard)
            self.assertEqual((report['missing_words'], report['inserted_words']), (0, 0), report)
            self.assertFalse(report.get('review_required'), report)
        for expected, heard in (
            ('Tea & coffee arrived.', 'Tea or coffee arrived.'),
            ('The share was 98%.', 'The share was 89 percent.'),
            ('The rod was 8½ inches.', 'The rod was eight and a quarter inches.'),
            ('The lovers arrived.', 'The lover arrived.'),
            ('a m', 'am'), ('record.p.m.', 'record.pm'),
        ):
            report = quality.assess_narration(expected, heard, major_words=1)
            self.assertFalse(report['ok'], (expected, heard, report))

    def test_short_critical_differences_require_listening_without_automatic_repair(self):
        for expected, heard in (
            ('She did not leave.', 'She did leave.'),
            ('On June 21 she left.', 'On June 24 she left.'),
            ('The witness stopped. Experts agreed.', 'The witness stopped.'),
            ('He walked in front', 'He walked in front of the body'),
            ('He left for Mexico.', 'He left from Mexico.'),
            ('She was ready.', 'He was ready.'),
        ):
            report = quality.unit_assessment({'text': expected}, {'transcript': heard})
            self.assertFalse(report['ok'], (expected, heard, report))
            self.assertTrue(report['review_required'], report)
            self.assertTrue(report['review_reasons'], report)
        report = quality.unit_assessment({'text': 'They visited Ballantyne yesterday.'},
                                         {'transcript': 'They visited Ballantine yesterday.'})
        self.assertTrue(report['ok'], report)
        self.assertFalse(report.get('review_required'), report)

    def test_narration_recognizes_calendar_years_without_changing_quantities(self):
        for expected, heard in (
            ('On September 15, 1966, she arrived.', 'On September fifteenth nineteen sixty six she arrived.'),
            ('On July 2, 1963, she arrived.', 'On July 2nd, 1963, she arrived.'),
            ('She visited. 1959, she married.', 'She visited. 1959. She married.'),
            ('In 1906 she arrived.', 'In nineteen oh six she arrived.'),
            ('During 2006 she arrived.', 'During two thousand six she arrived.'),
            ('By 2012 she arrived.', 'By twenty twelve she arrived.'),
            ('By 2012 she arrived.', 'By two thousand twelve she arrived.'),
            ('She drove a nineteen fifty-seven Chevrolet.', 'She drove a 1957 Chevrolet.'),
            ('In the 1960s she travelled.', 'In the nineteen sixties she travelled.'),
            ('They counted 1,966 tickets.', 'They counted one thousand nine hundred sixty six tickets.'),
            ('They counted 1966 tickets.', 'They counted one thousand nine hundred sixty six tickets.'),
        ):
            report = quality.assess_narration(expected, heard, major_words=1)
            self.assertTrue(report['ok'], (expected, heard, report))

    def test_narration_preserves_changed_dates_values_negation_and_year_style(self):
        for expected, heard in (
            ('On September 15, 1966, she arrived.', 'On September sixteenth nineteen sixty six she arrived.'),
            ('In 1966 she arrived.', 'In nineteen sixty seven she arrived.'),
            ('In 1966 she did not arrive.', 'In nineteen sixty six she did arrive.'),
            ('In 1966 she arrived.', 'In nineteen sixty six nineteen sixty six she arrived.'),
            ('In the 1960s she travelled.', 'In the nineteen seventies she travelled.'),
            ('They counted 1966 tickets.', 'They counted nineteen sixty six tickets.'),
            ('She drove a nineteen fifty-seven Chevrolet.', 'She drove a 1958 Chevrolet.'),
        ):
            self.assertFalse(quality.assess_narration(expected, heard, major_words=1)['ok'], (expected, heard))
        self.assertFalse(quality.assess_narration('In 1966 she arrived.',
                                                'In one thousand nine hundred sixty six she arrived.')['ok'])
        self.assertFalse(quality.assess_narration('In nineteen sixty-six she arrived.',
                                                'In one thousand nine hundred sixty six she arrived.')['ok'])
        self.assertTrue(quality.assess_narration('In 1966 she arrived.', 'In 1966 she arrived.')['ok'])
        self.assertNotIn('year_style_mismatches', quality.assess_narration('She visited. 1959, she married.', 'She visited. 1959 she married.'))

    def test_unambiguous_contractions_do_not_exhaust_word_error_budget(self):
        for contraction, expansion in quality._CONTRACTIONS.items():
            for left, right in ((contraction, ' '.join(expansion)), (' '.join(expansion), contraction)):
                report = assess(left, right, major_words=1)
                self.assertTrue(report['ok'], report)
                self.assertEqual((report['missing_words'], report['inserted_words']), (0, 0))
        report = assess("Why do you think I am going? I am trying to help.",
                        "Why do you think I'm going? I'm trying to help.")
        self.assertEqual((report['missing_words'], report['inserted_words']), (0, 0))

    def test_contractions_preserve_real_errors_ambiguous_forms_and_identifiers(self):
        for source, heard in (
            ("I am here", "I'm not here"), ("I am ready", "I'm late"),
            ("I am here", "I here"), ("I am am here", "I'm here"),
            ("I am", "I'm one two three four five"),
            ("he is here", "he's here"), ("I would go", "I'd go"),
            ("I'm_id", "I am_id"), ("I, am here", "I'm here"),
        ):
            self.assertFalse(assess(source, heard, major_words=1)['ok'], (source, heard))

    def test_homophones_do_not_count_as_word_errors_or_review_differences(self):
        pairs = (
            ("Be here to see their new son.", "Bee hear two sea they're knew sun."),
            ("You know you're right, it's plain.", "You no your write, its plane."),
            ("Wait for one whole week.", "Weight four won hole weak."),
        )
        for expected, heard in pairs:
            for source, transcript in ((expected, heard), (heard, expected)):
                report = assess(source, transcript, major_words=1)
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["differences"], [])
                self.assertEqual((report["missing_words"], report["inserted_words"]), (0, 0))

    def test_homophones_do_not_hide_adjacent_changes_or_extra_occurrences(self):
        for expected, heard, missing, inserted in (
            ("Be calm here.", "Bee loud here.", 1, 1),
            ("Be here.", "Bee bee here.", 0, 1),
            ("Be be here.", "Bee here.", 1, 0),
            ("Be here.", "Bee strange extra speech here.", 0, 3),
            ("be_id", "bee_id", 1, 1),
            ("Be", "been", 1, 1),
            ("read", "red", 1, 1),
        ):
            report = assess(expected, heard, major_words=1)
            self.assertFalse(report["ok"], report)
            self.assertEqual((report["missing_words"], report["inserted_words"]),
                             (missing, inserted), report)

    def test_spelling_and_possessive_spacing_do_not_exhaust_coverage_budget(self):
        for expected, heard in (("The honourable adviser favoured the behaviour.",
                                 "The honorable advisor favored the behavior."),
                                ("The fisherman's neighbour laboured for ever.",
                                 "The fisher man's neighbor labored forever."),
                                ("Rest awhile beside the worker's coloured coat.",
                                 "Rest a while beside the worker's colored coat.")):
            for left, right in ((expected, heard), (heard, expected)):
                report = assess(left, right, major_words=1)
                self.assertTrue(report["ok"], report)
                self.assertEqual((report["missing_words"], report["inserted_words"]), (0, 0))
        for expected, heard in (("fisherman's", "fisher mans"), ("fisherman's", "fisher man"),
                                ("honourable_id", "honorable_id"), ("laboured", "labor"),
                                ("Cooke", "Cook"), ("forever", "for, ever"),
                                ("honour one two three four five", "honor")):
            self.assertFalse(assess(expected, heard, major_words=1)["ok"], (expected, heard))

    def test_observed_degree_and_page_citation_formatting(self):
        for source, heard in (("M.A.", "MA"), ("Ph.D.", "PhD"), ("PH.D.", "PHD"),
                              ("(p. 84)", "(p84)"), ("p.50", "p50"),
                              ("pp. 123", "pp123"), ("p. eighty-four", "p84")):
            for expected, transcript in ((source, heard), (heard, source)):
                report = assess(expected, transcript, major_words=1)
                self.assertTrue(report["ok"], (expected, transcript, report))
                self.assertEqual((report["missing_words"], report["inserted_words"]), (0, 0))
                self.assertTrue(report["differences"][0]["orthographic_equivalent"])

    def test_formatting_keeps_names_values_and_identifiers_distinct(self):
        for source, heard in (("M.A.", "ma"), ("M.A.", "MB"), ("Ph.D.", "PhT"),
                              ("M.A._id", "MA_id"), ("record.M.A.", "record.MA"),
                              ("p. 84", "p85"), ("pp. 84", "p84"),
                              ("p. 84", "p084"), ("p. 84", "p84.2"),
                              ("p. 84", "p84/2"), ("p. 84", "p84-85"),
                              ("p. 84_id", "p84_id"), ("record.p.84", "record.p84"),
                              ("p.84.name", "p84.name"), ("p 84", "p84"),
                              ("Okara", "Okora"), ("Hamlyn", "Hamlin")):
            report = assess(source, heard, major_words=1)
            self.assertFalse(report["ok"], (source, heard, report))

    def test_formatting_does_not_accept_missing_citations_or_other_words(self):
        self.assertFalse(assess("M.A. one two three four five", "MA")["ok"])
        self.assertFalse(assess("Ph.D.", "PhD one two three four five")["ok"])
        self.assertFalse(assess("See p. 84", "See", major_words=1)["ok"])
        report = assess("M.A. and Ph.D. by Okara", "MA and PhD by Okora", major_words=1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing_words"], 1)

    def test_favourite_and_ordinals_do_not_count_as_lost_words(self):
        for source, heard in (("My favourite century is the twentieth.", "My favorite century is the 20th."),
                              ("mid-twentieth century", "mid-20th century"),
                              ("first second third eleventh twelfth thirteenth twenty first one hundredth",
                               "1st 2nd 3rd 11th 12th 13th 21st 100th")):
            report = assess(source, heard)
            self.assertEqual((report["missing_words"], report["inserted_words"]), (0, 0))
        for heard in ("21th", "020th", "20st", "x20th", "20th_x", "-20th", "1.20th"):
            self.assertTrue(assess("twentieth", heard)["differences"], heard)
        self.assertTrue(assess("twentieth", "twenty")["differences"])
        self.assertTrue(assess("favourite_id", "favorite_id")["missing_words"])
        self.assertFalse(assess("favourite one two three four five", "favorite")["ok"])
        self.assertFalse(assess("favourite", "favorite one two three four five")["ok"])

    def test_single_word_difference_is_recorded_but_not_a_failure(self):
        report = assess("Synthetic words stay here", "Synthetic word stay here")
        self.assertTrue(report["ok"])
        self.assertTrue(report["differences"])

    def test_large_missing_passage_fails(self):
        report = assess("one two three four five six seven eight", "one two")
        self.assertFalse(report["ok"])
        self.assertEqual(report["major"][0]["kind"], "delete")

    def test_large_nonsource_insertion_fails(self):
        report = assess("one two", "one two three four five six seven eight")
        self.assertFalse(report["ok"])
        self.assertEqual(report["major"][0]["kind"], "insert")

    def test_separated_small_omissions_fail_in_aggregate(self):
        report = assess("one two gap three four gap five six gap", "one gap three gap five gap", major_words=3)
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing_words"], 3)

    def test_unsigned_integer_notation_is_semantically_equivalent(self):
        expected = "zero nineteen twenty one hundred five nine hundred ninety nine one thousand one million one billion one trillion"
        heard = "0 19 20 100 5 999 1,000 1,000,000 1000000000 1000000000000"
        self.assertTrue(assess(expected, heard)["ok"])

    def test_integer_equivalence_fixes_grouped_hundreds_without_relaxing_gate(self):
        expected = "one hundred surveyor's seven hundred marker"
        heard = "100 surveyor 700 marker"
        result = assess(expected, heard)
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing_words"], 1)
        self.assertEqual(result["inserted_words"], 1)

    def test_conservative_compound_spacing_equivalence(self):
        for expected, heard in (("A fernlike pattern.", "A fern like pattern."),
                                ("Sea grass moves.", "Seagrass moves."),
                                ("A fernlike pattern.", "A fern-like pattern."),
                                ("A fern-like pattern.", "A fernlike pattern.")):
            result = assess(expected, heard)
            self.assertTrue(result["ok"], (expected, heard))
            self.assertEqual((result["missing_words"], result["inserted_words"]), (0, 0))
            self.assertTrue(result["differences"][0]["orthographic_equivalent"])

    def test_compound_spacing_rejects_meaning_and_punctuation_changes(self):
        for expected, heard in (("therapist", "the rapist"), ("nowhere", "now here"),
                                ("manslaughter", "mans laughter"), ("fernlike", "fern, like"),
                                ("fernlike", "fern. like"),
                                ("fernlike", "fern"), ("fernlike", "fern like extra")):
            result = assess(expected, heard)
            self.assertTrue(result["differences"], (expected, heard))
            self.assertFalse(any(item.get("orthographic_equivalent") for item in result["differences"]),
                             (expected, heard))

    def test_existing_hyphen_and_number_normalization_remain_equivalent(self):
        self.assertTrue(assess("twenty-one fern-like", "21 fern like")["ok"])

    def test_acknowledgment_spelling_variants_are_exact_one_word_equivalents(self):
        for expected, heard in (
            ("Acknowledgment", "acknowledgement"),
            ("acknowledgement", "ACKNOWLEDGMENT"),
            ("Acknowledgments", "acknowledgements"),
            ("acknowledgements", "ACKNOWLEDGMENTS"),
        ):
            result = assess(expected, heard)
            self.assertTrue(result["ok"], (expected, heard))
            self.assertTrue(result["differences"][0]["orthographic_equivalent"])

    def test_acknowledgment_variants_do_not_hide_real_or_identifier_differences(self):
        adjacent = assess("Acknowledgments Cooke", "acknowledgements Cook")
        self.assertEqual((adjacent["missing_words"], adjacent["inserted_words"]), (2, 2))
        self.assertFalse(any(item.get("orthographic_equivalent") for item in adjacent["differences"]))
        singular_plural = assess("acknowledgment", "acknowledgements")
        self.assertTrue(singular_plural["differences"])
        self.assertFalse(any(item.get("orthographic_equivalent") for item in singular_plural["differences"]))
        identifier = assess("acknowledgment_id", "acknowledgement_id")
        self.assertFalse(any(item.get("orthographic_equivalent") for item in identifier["differences"]))

    def test_acknowledgment_variants_do_not_relax_real_coverage_gate_or_names(self):
        five_missing = assess("acknowledgments one two three four five", "acknowledgements")
        self.assertFalse(five_missing["ok"])
        five_inserted = assess("acknowledgment", "acknowledgement one two three four five")
        self.assertFalse(five_inserted["ok"])
        names = assess("Cooke Ann Marks it's", "Cook Anne Mark's it")
        self.assertTrue(names["differences"])
        self.assertFalse(any(item.get("orthographic_equivalent") for item in names["differences"]))

    def test_numbered_heading_requires_number_and_exact_title_but_accepts_spoken_number_forms(self):
        for heard in ("01: INITIATION", "one Initiation", "zero one Initiation", "1 Initiation"):
            result = numbered_heading_assessment("01: INITIATION", heard)
            self.assertTrue(result["ok"], heard)
            self.assertIn("normalized_heading_assessment", result)
        self.assertFalse(numbered_heading_assessment("03: IMMOLATION", "three Immersion")["ok"])
        self.assertFalse(numbered_heading_assessment("03: IMMOLATION", "Immolation")["ok"])
        self.assertFalse(numbered_heading_assessment("03: IMMOLATION", "three Immolation extra")["ok"])
        self.assertTrue(numbered_heading_assessment("03: ACKNOWLEDGMENTS", "three acknowledgements")["ok"])
        for heard in ("009: NINE", "nine Nine", "zero zero nine Nine"):
            self.assertTrue(numbered_heading_assessment("009: NINE", heard)["ok"], heard)
        for heard in ("zero nine nine Ninety Nine", "zero ninety nine Ninety Nine"):
            self.assertTrue(numbered_heading_assessment("099: NINETY NINE", heard)["ok"], heard)

    def test_distinct_signed_decimal_fraction_and_leading_zero_forms_remain_different(self):
        for expected, heard in (("one hundred", "101"), ("minus one hundred", "-100"),
                                ("three fourteen", "3.14"), ("one two", "1/2"), ("one", "01"),
                                ("one thousand five", "1,000.5"), ("one thousand two", "1,000/2"),
                                ("minus one thousand", "-1,000"), ("five", ".5"), ("one hundred", "+100")):
            self.assertTrue(assess(expected, heard)["differences"], (expected, heard))
        self.assertEqual(words("R2D2"), ["r2d2"])

    def test_server_reuses_one_model_for_two_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            requests = [
                {"audio": str(root / "one.wav"), "expected": "one two", "report": str(root / "one.json"), "major_words": 5},
                {"audio": str(root / "two.wav"), "expected": "three four", "report": str(root / "two.json"), "major_words": 5},
            ]
            output = io.StringIO()
            model = object()
            with mock.patch.object(quality, "load_model", return_value=model) as load, \
                 mock.patch.object(quality, "transcribe_with_model", side_effect=["one two", "three four"]) as transcribe, \
                 mock.patch("sys.stdin", io.StringIO("".join(json.dumps(item) + "\n" for item in requests))), \
                 mock.patch("sys.stdout", output):
                quality.serve("synthetic-model")

            replies = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(replies[0], {"ready": True})
            self.assertEqual([reply["ok"] for reply in replies[1:]], [True, True])
            load.assert_called_once_with("synthetic-model")
            self.assertEqual(transcribe.call_count, 2)
            self.assertTrue((root / "one.json").exists())
            self.assertTrue((root / "two.json").exists())


if __name__ == "__main__":
    unittest.main()
