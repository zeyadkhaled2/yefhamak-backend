import unittest

from app.services.knowledge import chunk_text, source_footer, terms


class KnowledgeTests(unittest.TestCase):
    def test_arabic_normalization_and_cross_language_care(self):
        self.assertIn('wash', terms('إزاي أغسل الهودي؟'))
        self.assertIn('قطن', terms('cotton material'))
        self.assertEqual(terms('عِنَايَة'), terms('عناية'))

    def test_chunk_boundaries_and_limits(self):
        chunks = chunk_text('first paragraph\n\n' + 'cotton ' * 300)
        self.assertEqual(chunks[0], 'first paragraph')
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual(' '.join(chunks).count('cotton'), 300)
        for text in ['', ' ' * 10, 'a' * 100_001, 'b' * 1001]:
            with self.assertRaises(ValueError):
                chunk_text(text)

    def test_source_references_deduplicated_and_empty_safe(self):
        match = {'source': 'care.md', 'title': 'Care guide'}
        self.assertEqual(source_footer([]), '')
        self.assertEqual(source_footer([match, match]).count('care.md'), 1)

    def test_stopword_query(self):
        self.assertFalse(terms('the and for'))
