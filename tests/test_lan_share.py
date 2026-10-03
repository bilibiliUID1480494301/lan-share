"""Unit tests for lan-share (stdlib only, no network access beyond localhost)."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from lan_share import ShareHandler, ShareServer


def multipart_body(files):
    """Build a multipart/form-data body. files = [(field, filename, bytes), ...]"""
    boundary = "----lansharetestboundary42"
    out = []
    for field, filename, data in files:
        out.append(f"--{boundary}\r\n".encode())
        out.append(
            (
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
        )
        out.append(data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


class ServerTestCase(unittest.TestCase):
    def start_server(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        server = ShareServer(("127.0.0.1", 0), ShareHandler, root=self.root, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        return server

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def post(self, path, data, headers):
        req = urllib.request.Request(
            self.base + path, data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


class ListingAndDownloadTests(ServerTestCase):
    def test_lists_files_in_directory(self):
        self.start_server()
        (self.root / "hello.txt").write_text("hi there")
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"hello.txt", body)

    def test_downloads_exact_bytes(self):
        self.start_server()
        payload = bytes(range(256)) * 4
        (self.root / "blob.bin").write_bytes(payload)
        status, body = self.get("/blob.bin")
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)

    def test_subdirectory_browsing(self):
        self.start_server()
        sub = self.root / "docs"
        sub.mkdir()
        (sub / "a.txt").write_text("A")
        status, body = self.get("/docs/")
        self.assertEqual(status, 200)
        self.assertIn(b"a.txt", body)

    def test_missing_file_returns_404(self):
        self.start_server()
        status, _ = self.get("/nope.txt")
        self.assertEqual(status, 404)

    def test_path_traversal_is_blocked(self):
        self.start_server()
        secret = self.root.parent / "secret-should-not-leak.txt"
        secret.write_text("TOP SECRET")
        self.addCleanup(lambda: secret.unlink(missing_ok=True))
        for path in (
            "/../secret-should-not-leak.txt",
            "/..%2fsecret-should-not-leak.txt",
            "/%2e%2e/secret-should-not-leak.txt",
        ):
            status, body = self.get(path)
            self.assertIn(status, (403, 404), path)
            self.assertNotIn(b"TOP SECRET", body)


class UploadTests(ServerTestCase):
    def upload(self, filename, data, **server_kw):
        body, ctype = multipart_body([("file", filename, data)])
        return self.post(
            "/upload", body, {"Content-Type": ctype, "Accept": "application/json"}
        )

    def test_upload_saves_and_lists(self):
        self.start_server()
        status, resp = self.upload("notes.txt", b"hello upload")
        self.assertEqual(status, 200)
        saved = json.loads(resp)["saved"][0]
        self.assertEqual(saved["name"], "notes.txt")
        self.assertEqual(saved["size"], len(b"hello upload"))
        self.assertEqual((self.root / "notes.txt").read_text(), "hello upload")
        _, listing = self.get("/")
        self.assertIn(b"notes.txt", listing)

    def test_duplicate_name_gets_suffix(self):
        self.start_server()
        self.upload("doc.txt", b"v1")
        _, resp = self.upload("doc.txt", b"v2")
        name = json.loads(resp)["saved"][0]["name"]
        self.assertEqual(name, "doc (1).txt")
        self.assertEqual((self.root / "doc (1).txt").read_bytes(), b"v2")

    def test_unsafe_filename_is_sanitized(self):
        self.start_server()
        _, resp = self.upload("..\\..\\evil<>.txt", b"x")
        name = json.loads(resp)["saved"][0]["name"]
        self.assertNotIn("..", name)
        self.assertNotIn("<", name)
        self.assertEqual((self.root / name).read_bytes(), b"x")

    def test_oversized_upload_rejected(self):
        self.start_server(max_mb=1)
        big = b"x" * (1024 * 1024 + 1)
        status, _ = self.upload("big.bin", big)
        self.assertEqual(status, 413)

    def test_read_only_rejects_upload(self):
        self.start_server(read_only=True)
        status, _ = self.upload("x.txt", b"x")
        self.assertEqual(status, 403)

    def test_malformed_body_rejected(self):
        self.start_server()
        status, _ = self.post(
            "/upload",
            b"not multipart",
            {"Content-Type": "text/plain", "Accept": "application/json"},
        )
        self.assertEqual(status, 400)

    def test_browser_upload_redirects_to_listing(self):
        self.start_server()
        body, ctype = multipart_body([("file", "r.txt", b"r")])
        req = urllib.request.Request(
            self.base + "/upload",
            data=body,
            headers={"Content-Type": ctype},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # follows the 303
            self.assertEqual(resp.status, 200)
            self.assertIn(b"r.txt", resp.read())


class TokenTests(ServerTestCase):
    def test_token_required(self):
        self.start_server(token="s3cret")
        self.assertEqual(self.get("/")[0], 401)
        self.assertEqual(self.get("/?token=s3cret")[0], 200)
        self.assertEqual(self.get("/?token=wrong")[0], 401)

    def test_upload_also_needs_token(self):
        self.start_server(token="s3cret")
        body, ctype = multipart_body([("file", "t.txt", b"t")])
        ok = self.post(
            "/upload?token=s3cret",
            body,
            {"Content-Type": ctype, "Accept": "application/json"},
        )
        self.assertEqual(ok[0], 200)
        denied = self.post(
            "/upload", body, {"Content-Type": ctype, "Accept": "application/json"}
        )
        self.assertEqual(denied[0], 401)


if __name__ == "__main__":
    unittest.main()
