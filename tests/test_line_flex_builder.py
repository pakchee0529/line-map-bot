import unittest

from line_flex_builder import MAX_CAROUSEL_BUBBLES, build_flex_payload


def sample_card(index=1):
    return {
        "status": "found",
        "title": f"木ノ原{index}",
        "rows": [{"label": "採用地点", "value": f"木ノ原{index}"}],
        "primary_url": f"https://example.com/map/{index}",
        "preview_url": f"https://example.com/preview/{index}.png",
    }


class LineFlexBuilderTest(unittest.TestCase):
    def test_builds_image_backed_bubble(self):
        payload = build_flex_payload(
            {
                "plain_text": "木ノ原40E1S3～40E1S4",
                "cards": [
                    {
                        **sample_card(),
                        "status": "corrected",
                        "primary_label": "2点地図・地番図を開く",
                    }
                ],
            }
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["contents"]["type"], "bubble")
        self.assertEqual(payload["contents"]["hero"]["type"], "image")
        self.assertEqual(
            payload["contents"]["footer"]["contents"][0]["action"]["label"],
            "2点地図・地番図を開く",
        )

    def test_limits_carousel_to_line_maximum(self):
        payload = build_flex_payload(
            {
                "plain_text": "multi",
                "cards": [sample_card(index) for index in range(20)],
            }
        )
        self.assertEqual(payload["contents"]["type"], "carousel")
        self.assertEqual(
            len(payload["contents"]["contents"]),
            MAX_CAROUSEL_BUBBLES,
        )

    def test_non_https_actions_are_not_rendered(self):
        payload = build_flex_payload(
            {
                "plain_text": "unsafe",
                "cards": [
                    {
                        **sample_card(),
                        "primary_url": "http://example.com/map",
                        "preview_url": "javascript:alert(1)",
                        "suggestion_text": "木ノ原40",
                    }
                ],
            }
        )
        self.assertNotIn("hero", payload["contents"])
        action = payload["contents"]["footer"]["contents"][0]["action"]
        self.assertEqual(action["type"], "message")


if __name__ == "__main__":
    unittest.main()
