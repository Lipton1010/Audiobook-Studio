import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import pipeline_text as pt


class VisualExtractionTests(unittest.TestCase):
    def test_fragmented_log_is_one_preserved_visual(self):
        source = """Before the console woke.
| Time | State |
| --- | --- |
| 05:12 | Ready |

[AV12]
05:14:24  Laboratory  Operative
| 05:15 | Running |
Afterward, she left."""
        blocks = pt.tag_blocks(source)
        visuals = [block for block in blocks if block["type"] == "visual"]
        self.assertEqual(len(visuals), 1)
        self.assertEqual(visuals[0]["visual_kind"], "structured log")
        self.assertIn("[AV12]", visuals[0]["text"])
        self.assertIn("05:14:24", visuals[0]["text"])
        self.assertEqual([block["text"] for block in blocks if block["type"] == "body"], [
            "Before the console woke.", "Afterward, she left.",
        ])

    def test_standalone_code_is_visual_and_prose_is_preserved(self):
        blocks = pt.tag_blocks("[AV12]\nShe crossed the room.")
        self.assertEqual(blocks[0], {
            "type": "visual", "text": "[AV12]", "visual_kind": "standalone code",
        })
        self.assertEqual(blocks[1], {"type": "body", "text": "She crossed the room."})

    def test_chart_indication_keeps_dialogue_and_heading_as_text(self):
        blocks = pt.tag_blocks("""CHAPTER TWO
\"Look at the chart,\" Mina said.
![Cooling curve](chart.png)
The crew waited.""")
        self.assertEqual([block["type"] for block in blocks], ["heading", "body", "visual", "body"])
        self.assertEqual(blocks[1]["text"], "\"Look at the chart,\" Mina said.")
        self.assertEqual(blocks[2]["visual_kind"], "image or diagram indication")
        self.assertIn("chart.png", blocks[2]["text"])

    def test_prose_starting_with_map_period_is_not_a_visual_caption(self):
        blocks = pt.tag_blocks("Map. It was the first thing she checked.\nMap 2. The evacuation route.")
        self.assertEqual([block["type"] for block in blocks], ["body", "visual"])
        self.assertEqual(blocks[0]["text"], "Map. It was the first thing she checked.")
        self.assertEqual(blocks[1]["visual_kind"], "image or diagram indication")

    def test_iteration_heading_and_quotation_are_not_consumed(self):
        blocks = pt.tag_blocks("""ITERATION ONE
\"[AV12] is only a label,\" she said.
[AV12]""")
        self.assertEqual([block["type"] for block in blocks], ["heading", "body", "visual"])

    def test_mixed_case_iteration_headings_receive_heading_cues(self):
        blocks = pt.tag_blocks("""# First Iteration
\"Iteration One is only a phrase,\" Mina said.
Iteration One""")
        self.assertEqual([block["type"] for block in blocks], ["heading", "body", "heading"])
        self.assertEqual([block["text"] for block in blocks if block["type"] == "heading"], [
            "First Iteration", "Iteration One",
        ])

    def test_path_a_visual_blocks_keep_provenance(self):
        blocks = pt._path_a_page_blocks([(0, 10, "[AV12]"), (0, 20, "A normal paragraph.")],
                                        "prose", 0.0, source_page=9)
        self.assertEqual(blocks[0], {
            "type": "visual", "text": "[AV12]", "visual_kind": "standalone code", "source_page": 9,
        })
        self.assertEqual(blocks[1]["type"], "body")

    def test_plain_and_partial_table_rows_are_one_visual_run(self):
        blocks = pt.tag_blocks("""Equipment Count Load
Pumps 12 17
Gates 4 9
| Valves | 1 | 80
The fence failed at dusk.""")
        self.assertEqual([block["type"] for block in blocks], ["visual", "body"])
        self.assertEqual(blocks[0]["visual_kind"], "plain-text table")
        self.assertIn("Pumps 12 17", blocks[0]["text"])

    def test_label_run_keeps_heading_quote_and_prose(self):
        labels = "\n".join(f"Node {index}" for index in range(15))
        blocks = pt.tag_blocks(f"""ITERATION ONE
\"Do not touch the diagram,\" Mina said.
{labels}
The generator restarted.""")
        self.assertEqual([block["type"] for block in blocks], [
            "heading", "body", "visual", "body",
        ])
        self.assertEqual(blocks[2]["visual_kind"], "diagram labels")

    def test_path_a_visual_line_does_not_swallow_following_prose(self):
        blocks = pt._path_a_page_blocks([
            (0, 10, "Chart: reactor state"),
            (0, 20, "Mina said the reactor was stable."),
        ], "prose", 0.0, source_page=4)
        self.assertEqual([block["type"] for block in blocks], ["visual", "body"])
        self.assertEqual(blocks[1]["text"], "Mina said the reactor was stable.")

    def test_path_a_numbered_colon_title_splits_from_body_as_heading(self):
        blocks = pt._path_a_page_blocks([
            (0, 10, "01: ARRIVAL"),
            (0, 20, "The expedition began at dawn."),
        ], "prose", 0.0, source_page=5)
        self.assertEqual([block["type"] for block in blocks], ["heading", "body"])
        self.assertEqual(blocks[0]["text"], "01: ARRIVAL")
        self.assertEqual(blocks[1]["text"], "The expedition began at dawn.")

    def test_numbered_colon_data_is_not_a_heading(self):
        blocks = pt.paragraphs_to_blocks(["01: sensor 12"], source_page=5)
        self.assertEqual(blocks[0]["type"], "body")

    def test_legacy_retag_preserves_prose_and_headings(self):
        retagged = pt.retag_legacy_visual_blocks([
            {"type": "heading", "text": "ITERATION ONE", "source_page": 1},
            {"type": "body", "text": "Pumps 12 17", "source_page": 1},
            {"type": "body", "text": "Gates 4 9", "source_page": 1},
            {"type": "body", "text": "Mina closed the door.", "source_page": 1},
            {"type": "table", "text": "A legacy marker.", "source_page": 1},
        ])
        self.assertEqual([block["type"] for block in retagged], [
            "heading", "visual", "visual", "body", "visual",
        ])

    def test_uncertain_repeated_ocr_is_preserved_for_review(self):
        raw = "\n".join(["Signal Alpha" if index % 2 else "Signal Beta" for index in range(20)])
        blocks = pt.tag_blocks(raw)
        self.assertEqual(blocks, [{
            "type": "visual", "text": raw, "visual_kind": "uncertain repeated OCR artwork",
        }])

    def test_html_table_is_visual_before_markup_filtering(self):
        raw = "<table><tr><td>12</td><td>17</td></tr></table>"
        self.assertEqual(pt.tag_blocks(raw), [{
            "type": "visual", "text": raw, "visual_kind": "HTML table",
        }])

    def test_long_random_table_rows_remain_raw_visual_content(self):
        raw = """1d3 Outcome
1 The crew searches the silent station until dawn and finds a sealed room.
2 The crew follows a broken signal through the flooded corridor at night.
3 The crew discovers a warning painted across the airlock door in red."""
        blocks = pt.tag_blocks(raw)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["visual_kind"], "random table")
        self.assertEqual(blocks[0]["text"], raw)

    def test_path_a_graphics_are_retained_without_invented_text(self):
        class Page:
            def get_images(self, full):
                return [(1,)]

            def get_drawings(self):
                return []

            def get_image_rects(self, xref):
                return []

        self.assertEqual(pt._page_graphic_blocks(Page(), 4), [{
            "type": "visual", "text": "", "visual_kind": "embedded image", "source_page": 4,
        }])

    def test_path_a_graphic_uses_page_geometry_before_following_prose(self):
        graphic = {"type": "visual", "text": "", "visual_kind": "embedded image", "source_page": 3}
        blocks = [{"type": "body", "text": "Before."}, {"type": "body", "text": "After."}]
        placed = pt._insert_page_graphics(
            blocks, [(20, graphic)], [(0, 10, "Before."), (0, 25, "After.")]
        )
        self.assertEqual([block["type"] for block in placed], ["body", "visual", "body"])

    def test_separate_vector_charts_keep_intervening_prose_in_order(self):
        class Page:
            def get_images(self, full):
                return []

            def get_drawings(self):
                return [{"rect": types.SimpleNamespace(y0=top, y1=bottom)}
                        for top, bottom in [(20, 40), (22, 38), (25, 36),
                                            (80, 100), (82, 98), (85, 96)]]

        graphics = pt._page_graphics(Page(), 3)
        self.assertEqual([y for y, block in graphics], [20, 80])
        blocks = [{"type": "body", "text": text} for text in ("Before.", "Between.", "After.")]
        placed = pt._insert_page_graphics(blocks, graphics, [
            (0, 10, "Before."), (0, 55, "Between."), (0, 110, "After."),
        ])
        self.assertEqual([block["text"] for block in placed], ["Before.", "", "Between.", "", "After."])

    def test_path_a_graphic_splits_body_at_its_line_boundary(self):
        graphic = {"type": "visual", "text": "", "visual_kind": "embedded image", "source_page": 3}
        blocks = [{"type": "body", "text": "She crossed the room and opened the door."}]
        placed = pt._insert_page_graphics(blocks, [(20, graphic)], [
            (0, 10, "She crossed the room"), (0, 25, "and opened the door."),
        ])
        self.assertEqual([block["text"] for block in placed if block["type"] == "body"], [
            "She crossed the room", "and opened the door.",
        ])
        self.assertEqual([block["type"] for block in placed], ["body", "visual", "body"])

    def test_repeated_lines_do_not_move_graphic_before_earlier_prose(self):
        graphic = {"type": "visual", "text": "", "visual_kind": "embedded image", "source_page": 3}
        blocks = [{"type": "body", "text": "Yes."}, {"type": "body", "text": "Yes."}]
        placed = pt._insert_page_graphics(blocks, [(20, graphic)], [
            (0, 10, "Yes."), (0, 30, "Yes."),
        ])
        self.assertEqual([block["type"] for block in placed], ["body", "visual", "body"])

    def test_path_a_multiple_graphics_keep_their_separate_positions(self):
        graphics = [
            (20, {"type": "visual", "text": "", "visual_kind": "embedded image", "source_page": 3}),
            (40, {"type": "visual", "text": "", "visual_kind": "vector graphic", "source_page": 3}),
        ]
        blocks = [{"type": "body", "text": "One two three."}]
        placed = pt._insert_page_graphics(blocks, graphics, [
            (0, 10, "One"), (0, 25, "two"), (0, 45, "three."),
        ])
        self.assertEqual([block["type"] for block in placed], [
            "body", "visual", "body", "visual", "body",
        ])

    def test_trailing_visual_keeps_cross_page_source_order(self):
        merged = pt.stitch_pages([
            [{"type": "body", "text": "A sentence that", "source_page": 1},
             {"type": "visual", "text": "", "visual_kind": "embedded image", "source_page": 1}],
            [{"type": "body", "text": "continues here.", "source_page": 2}],
        ])
        self.assertEqual([block["type"] for block in merged], ["body", "visual", "body"])
        self.assertEqual(merged[0]["text"], "A sentence that")
        self.assertEqual(merged[1]["type"], "visual")


if __name__ == "__main__":
    unittest.main()
