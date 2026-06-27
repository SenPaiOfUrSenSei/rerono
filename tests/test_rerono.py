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
        self.assertTrue(should_block("https://www.youtube.com/shorts/hdhjsjh", rules))
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

    def test_youtube_shorts_api_blocking(self):
        from unittest.mock import MagicMock
        import tempfile
        import json
        
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
            json.dump({
                "rules": ["youtube.com/shorts"],
                "start_time": 0,
                "end_time": None
            }, tmp)
            tmp_path = tmp.name
            
        try:
            from rerono.blocker_addon import ReronoBlocker
            blocker = ReronoBlocker(tmp_path)
            
            # 1. Standard blocked page request
            flow = MagicMock()
            flow.request.pretty_url = "https://www.youtube.com/shorts"
            flow.request.method = "GET"
            flow.response = None
            blocker.request(flow)
            self.assertIsNotNone(flow.response)
            self.assertEqual(flow.response.status_code, 403)
            
            # 2. Allowed video request
            flow = MagicMock()
            flow.request.pretty_url = "https://www.youtube.com/watch?v=123"
            flow.request.method = "GET"
            flow.response = None
            blocker.request(flow)
            self.assertIsNone(flow.response)
            
            # 3. Background reel API request
            flow = MagicMock()
            flow.request.pretty_url = "https://www.youtube.com/youtubei/v1/reel/item_watch"
            flow.request.method = "POST"
            flow.response = None
            blocker.request(flow)
            self.assertIsNotNone(flow.response)
            self.assertEqual(flow.response.status_code, 403)
            
            # 4. Background browse API request with FEshorts payload
            flow = MagicMock()
            flow.request.pretty_url = "https://www.youtube.com/youtubei/v1/browse"
            flow.request.method = "POST"
            flow.request.get_text.return_value = '{"browseId": "FEshorts"}'
            flow.response = None
            blocker.request(flow)
            self.assertIsNotNone(flow.response)
            self.assertEqual(flow.response.status_code, 403)
            
            # 5. Background browse API request with other payload (allowed)
            flow = MagicMock()
            flow.request.pretty_url = "https://www.youtube.com/youtubei/v1/browse"
            flow.request.method = "POST"
            flow.request.get_text.return_value = '{"browseId": "FEwhat_to_watch"}'
            flow.request.headers = {}
            flow.response = None
            blocker.request(flow)
            self.assertIsNone(flow.response)

            # 6. Referer-based blocking for YouTube Shorts SPA navigation (on youtubei.googleapis.com)
            flow = MagicMock()
            flow.request.pretty_url = "https://youtubei.googleapis.com/youtubei/v1/player"
            flow.request.method = "POST"
            flow.request.headers = {"referer": "https://www.youtube.com/shorts/hdhjsjh", "accept": "application/json"}
            flow.response = None
            blocker.request(flow)
            self.assertIsNotNone(flow.response)
            self.assertEqual(flow.response.status_code, 403)
            self.assertEqual(flow.response.headers["Content-Type"], "text/plain")
            self.assertEqual(flow.response.content, b"Blocked by Rerono")
            
            # 7. Reel API endpoint on youtubei.googleapis.com direct blocking
            flow = MagicMock()
            flow.request.pretty_url = "https://youtubei.googleapis.com/youtubei/v1/reel/reel_item_watch"
            flow.request.method = "POST"
            flow.request.headers = {}
            flow.response = None
            blocker.request(flow)
            self.assertIsNotNone(flow.response)
            self.assertEqual(flow.response.status_code, 403)
            
        finally:
            os.unlink(tmp_path)

    def test_check_git_config_warning(self):
        from unittest.mock import patch, MagicMock
        from rerono.main import check_git_config_warning
        
        # Test case 1: Git warning is triggered
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "/home/user/.mitmproxy/mitmproxy-ca-cert.pem\n"
        
        with patch('subprocess.run', return_value=mock_res) as mock_run, \
             patch('builtins.print') as mock_print:
            check_git_config_warning()
            mock_run.assert_called_once_with(
                ["git", "config", "--global", "http.sslcainfo"],
                capture_output=True, text=True
            )
            # Verify print was called containing warning text
            mock_print.assert_any_call("\n⚠️  [Warning] Detected custom Git SSL configuration pointing to mitmproxy:")

        # Test case 2: No warning if output does not contain mitmproxy or rerono
        mock_res2 = MagicMock()
        mock_res2.returncode = 0
        mock_res2.stdout = "/some/other/path/cert.pem\n"
        with patch('subprocess.run', return_value=mock_res2), \
             patch('builtins.print') as mock_print:
            check_git_config_warning()
            mock_print.assert_not_called()

    def test_trust_ca_linux_firefox(self):
        from unittest.mock import patch, MagicMock
        from pathlib import Path
        import subprocess
        from rerono.main import trust_ca_linux_firefox
        
        # Test case 1: Firefox directory does not exist
        with patch('rerono.main.get_original_user_home', return_value=Path('/nonexistent_home')), \
             patch('pathlib.Path.exists', return_value=False):
            res = trust_ca_linux_firefox(Path('/path/to/pem'))
            self.assertFalse(res)
            
        # Test case 2: Firefox directory exists, certutil not found
        with patch('rerono.main.get_original_user_home', return_value=Path('/home/user')), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('subprocess.run', side_effect=FileNotFoundError):
            res = trust_ca_linux_firefox(Path('/path/to/pem'))
            self.assertFalse(res)
            
        # Test case 3: Success finding profiles and running certutil
        mock_cert9 = MagicMock()
        mock_cert9.parent = Path('/home/user/.mozilla/firefox/profile1')
        
        # Note: glob finds mock_cert9 when searching for **/cert9.db
        # We need Path.exists to return True for cert9.db, key4.db, pkcs11.txt when chowning
        original_exists = Path.exists
        def mock_exists(self_path):
            if "/home/user" in str(self_path):
                return True
            return original_exists(self_path)

        with patch('rerono.main.get_original_user_home', return_value=Path('/home/user')), \
             patch('pathlib.Path.exists', new=mock_exists), \
             patch('pathlib.Path.glob', return_value=[mock_cert9]), \
             patch('subprocess.run') as mock_run, \
             patch('rerono.main.chown_to_original_user') as mock_chown:
            res = trust_ca_linux_firefox(Path('/path/to/pem'))
            self.assertTrue(res)
            mock_run.assert_any_call(
                ["certutil", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            # chown is called for the 3 database files
            self.assertEqual(mock_chown.call_count, 3)

if __name__ == "__main__":
    unittest.main()
