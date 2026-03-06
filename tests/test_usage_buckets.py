import unittest


from ai_dev.models import UsageBuckets


class TestUsageBuckets(unittest.TestCase):
    def test_token_properties(self) -> None:
        usage = UsageBuckets(input_tokens=10, output_tokens=5, cache_write_tokens=7, cache_read_tokens=100)
        self.assertEqual(usage.incremental_tokens, 15)
        self.assertEqual(usage.cache_tokens, 107)
        self.assertEqual(usage.effective_tokens, 122)
        # Backwards-compatible alias
        self.assertEqual(usage.total_tokens, 122)


if __name__ == "__main__":
    unittest.main()

