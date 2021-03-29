import os
from django.test.utils import override_settings
from sentry.testutils import TestCase
from sentry.web.frontend.generic import FOREVER_CACHE, NEVER_CACHE


class StaticMediaTest(TestCase):
    @override_settings(DEBUG=False)
    def test_basic(self):
        url = "/_static/sentry/js/ads.js"
        response = self.client.get(url)
        assert response.status_code == 200, response
        assert response["Cache-Control"] == NEVER_CACHE
        assert response["Vary"] == "Accept-Encoding"
        assert response["Access-Control-Allow-Origin"] == "*"
        "Content-Encoding" not in response

    @override_settings(DEBUG=False)
    def test_from_manifest(self):
        """
        manifest here refers to the webpack manifest for frontend assets
        """

        DIST_PATH = "src/sentry/static/sentry/dist"
        MANIFEST_PATH = f"{DIST_PATH}/manifest.json"
        APP_FILE = "app.f00f00.js"

        # Need to create a manifest file and `APP_FILE` in `DIST_PATH`
        # Otherwise this will 404
        with open(MANIFEST_PATH, "w") as manifest_fp:
            manifest_fp.write(f"""{{"app.js": "{APP_FILE}"}}""")

        try:
            open(f"{DIST_PATH}/{APP_FILE}", "a").close()
            url = "/_static/sentry/dist/app.js"

            response = self.client.get(url)
            assert response.status_code == 200, response
            assert response["Cache-Control"] == FOREVER_CACHE
            assert response["Vary"] == "Accept-Encoding"
            assert response["Access-Control-Allow-Origin"] == "*"
            "Content-Encoding" not in response

            # non-existant dist file
            response = self.client.get("/_static/sentry/dist/invalid.js")
            assert response.status_code == 404, response

            with override_settings(DEBUG=True):
                response = self.client.get(url)
                assert response.status_code == 200, response
                assert response["Cache-Control"] == NEVER_CACHE
                assert response["Vary"] == "Accept-Encoding"
                assert response["Access-Control-Allow-Origin"] == "*"

        finally:
            try:
                os.unlink(f"{DIST_PATH}/{APP_FILE}")
                os.unlink(MANIFEST_PATH)
            except Exception:
                pass

    @override_settings(DEBUG=False)
    def test_no_cors(self):
        url = "/_static/sentry/images/favicon.ico"
        response = self.client.get(url)
        assert response.status_code == 200, response
        assert response["Cache-Control"] == NEVER_CACHE
        assert response["Vary"] == "Accept-Encoding"
        assert "Access-Control-Allow-Origin" not in response
        "Content-Encoding" not in response

    def test_404(self):
        url = "/_static/sentry/app/thisfiledoesnotexistlol.js"
        response = self.client.get(url)
        assert response.status_code == 404, response

    def test_gzip(self):
        url = "/_static/sentry/js/ads.js"
        response = self.client.get(url, HTTP_ACCEPT_ENCODING="gzip,deflate")
        assert response.status_code == 200, response
        assert response["Vary"] == "Accept-Encoding"
        "Content-Encoding" not in response

        try:
            open("src/sentry/static/sentry/js/ads.js.gz", "a").close()

            # Not a gzip Accept-Encoding, so shouldn't serve gzipped file
            response = self.client.get(url, HTTP_ACCEPT_ENCODING="lol")
            assert response.status_code == 200, response
            assert response["Vary"] == "Accept-Encoding"
            "Content-Encoding" not in response

            response = self.client.get(url, HTTP_ACCEPT_ENCODING="gzip,deflate")
            assert response.status_code == 200, response
            assert response["Vary"] == "Accept-Encoding"
            assert response["Content-Encoding"] == "gzip"
        finally:
            try:
                os.unlink("src/sentry/static/sentry/js/ads.js.gz")
            except Exception:
                pass

    def test_file_not_found(self):
        url = "/_static/sentry/app/xxxxxxxxxxxxxxxxxxxxxxxx.js"
        response = self.client.get(url)
        assert response.status_code == 404, response

    def test_bad_access(self):
        url = "/_static/sentry/images/../../../../../etc/passwd"
        response = self.client.get(url)
        assert response.status_code == 404, response

    def test_directory(self):
        url = "/_static/sentry/images/"
        response = self.client.get(url)
        assert response.status_code == 404, response

        url = "/_static/sentry/images"
        response = self.client.get(url)
        assert response.status_code == 404, response
