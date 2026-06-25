import os
import sys
import unittest

# Add src to the path so we can import rerono
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from rerono.blocker_addon import should_block
from rerono.main import parse_simple_yaml

class TestRerono(unittest.TestCase):
    def test_should_block_domains(self):
        rules = ["twitter.com", "tiktok.com"]
        
        # Exact domain match
        self.assertTrue(should_block("https://twitter.com", rules))
        self.assertTrue(should_block("http://tiktok.com/some/page", rules))
        
        # Subdomain match
        self.assertTrue(should_block("https://sub.twitter.com/path", rules))
        self.assertTrue(should_block("https://a.b.c.tiktok.com", rules))
        
        # Non-matching domains
        self.assertFalse(should_block("https://not-twitter.com", rules))
        self.assertFalse(should_block("https://twitter.company", rules))
        
    def test_should_block_paths(self):
        rules = ["youtube.com/shorts", "facebook.com/watch"]
        
        # Exact domain and path match
        self.assertTrue(should_block("https://youtube.com/shorts", rules))
        self.assertTrue(should_block("https://www.youtube.com/shorts?v=123", rules))
        self.assertTrue(should_block("http://facebook.com/watch/something", rules))
        
        # Domain matches, but path does not
        self.assertFalse(should_block("https://youtube.com/watch", rules))
        self.assertFalse(should_block("https://facebook.com/home", rules))
        
        # Path matches, but domain does not
        self.assertFalse(should_block("https://vimeo.com/shorts", rules))

    def test_parse_simple_yaml(self):
        yaml_content = """
        # Comments should be ignored
        default:
          - youtube.com/shorts
          - tiktok.com
        
        social:
          - facebook.com
          - twitter.com
          
        inline: - single-value.com
        """
        parsed = parse_simple_yaml(yaml_content)
        self.assertIn("default", parsed)
        self.assertIn("social", parsed)
        self.assertIn("inline", parsed)
        
        self.assertEqual(parsed["default"], ["youtube.com/shorts", "tiktok.com"])
        self.assertEqual(parsed["social"], ["facebook.com", "twitter.com"])
        self.assertEqual(parsed["inline"], ["single-value.com"])

if __name__ == "__main__":
    unittest.main()
