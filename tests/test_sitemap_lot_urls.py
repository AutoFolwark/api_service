import gzip
from datetime import datetime, timezone
from email.utils import format_datetime
from types import SimpleNamespace

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_problem.handler import add_exception_handler, new_exception_handler

from aws_lambda_functions.sitemap_generator_lambda_handler import (
    URLSET_FOOTER,
    SitemapChunkWriter,
    _content_type,
    _effective_lastmod,
    _lot_entry,
    _w3c_datetime,
)
from config import settings
from routers.v1 import sitemaps
from services.lot_urls import lot_path, lot_slug


def test_slugs_match_frontend_lot_url():
    cases = [
        (
            (2019, "Citroën", "C4", "VF7"),
            "2019-Citroen-C4-VF7",
        ),
        (
            (2018, "Mercedes-Benz", "C 300 4MATIC", "WDD"),
            "2018-Mercedes-Benz-C-300-4MATIC-WDD",
        ),
        (
            (2020, "Range Rover/Sport", "HSE", "SAL"),
            "2020-Range-Rover-Sport-HSE-SAL",
        ),
        (
            (2017, "C.300_x", "(AMG)", "X&Y"),
            "2017-C-300-x-AMG-X-Y",
        ),
        (
            (2016, "Škoda", "Fabia", "TMB"),
            "2016-Skoda-Fabia-TMB",
        ),
        ((None, None, None, None), "lot"),
        ((0, "", "A", None), "A"),
        ((2021, "łódź", "groß", "ABC"), "2021-odz-gro-ABC"),
    ]
    for parts, expected in cases:
        assert lot_slug(*parts) == expected


def test_lot_path_matches_frontend_canonical_path():
    assert (
        lot_path("55443322", "Copart", 1, 2019, "Citroën", "C4", "VF7")
        == "/lot/copart/55443322/2019-Citroen-C4-VF7"
    )
    assert lot_path("00123", "iaai", 2, None, None, None, None) == "/lot/iaai/123/lot"


def test_lot_path_falls_back_to_numeric_site():
    assert lot_path("9", None, 2, 2020, "Ford", "F-150", None) == (
        "/lot/iaai/9/2020-Ford-F-150"
    )
    assert lot_path("9", "  ", 1, None, None, None, None) == "/lot/copart/9/lot"


def test_lot_path_skips_rows_the_frontend_cannot_canonicalize():
    assert lot_path("ABC123", "copart", 1, 2020, "Ford", "F-150", None) is None
    assert lot_path(None, "copart", 1, 2020, "Ford", "F-150", None) is None
    assert lot_path("9", None, 3, 2020, "Ford", "F-150", None) is None
    assert lot_path("9", "all", 1, 2020, "Ford", "F-150", None) is None
    assert lot_path("9", None, 99, 2020, "Ford", "F-150", None) is None


def test_sitemap_languages_follow_the_frontend():
    assert settings.SITEMAP_LANGUAGES == ("en", "pl", "uk", "cs", "de", "sl")


def test_future_lastmod_is_clamped_to_generation_time():
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        lot_id="42",
        base_site="copart",
        site=1,
        year=2020,
        make="Ford",
        model="F-150",
        vin="1FT",
        updated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )

    entry, lastmod = _lot_entry(row, now)

    assert lastmod == now
    assert entry.startswith("/lot/copart/42/2020-Ford-F-150-1FT</loc>")
    assert "<lastmod>2026-11-17T12:00:00Z</lastmod>" in entry
    assert _w3c_datetime(datetime(2024, 5, 1)) == "2024-05-01T00:00:00Z"
    assert _effective_lastmod(None, now) is None


def test_chunk_rolls_over_on_url_count_and_stays_valid_gzip():
    entry = b"<url><loc>https://bidmax.eu/en/lot/copart/1/lot</loc></url>\n"
    writer = SitemapChunkWriter("en", max_urls=2, max_bytes=10**9)
    assert writer.add(entry, None) is None
    assert writer.add(entry, datetime(2024, 1, 1, tzinfo=timezone.utc)) is None
    finished = writer.add(entry, datetime(2024, 6, 1, tzinfo=timezone.utc))

    assert finished is not None
    assert finished.url_count == 2
    assert finished.lastmod == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert finished.name == "sitemap-lots-en-1.xml.gz"
    xml = gzip.decompress(finished.data.read())
    assert xml.startswith(b"<?xml")
    assert xml.count(b"<url>") == 2
    assert xml.endswith(URLSET_FOOTER)

    last = writer.finish()
    assert last is not None
    assert last.url_count == 1
    assert last.lastmod == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert [chunk.name for chunk in writer.chunks] == [
        "sitemap-lots-en-1.xml.gz",
        "sitemap-lots-en-2.xml.gz",
    ]
    assert _content_type(finished.name) == "application/gzip"
    assert _content_type("sitemap-index.xml") == "application/xml"


def test_chunk_rolls_over_on_uncompressed_size():
    entry = b"<url><loc>https://bidmax.eu/en/lot/copart/1/lot</loc></url>\n"
    probe = SitemapChunkWriter("en", max_urls=100, max_bytes=10**9)
    probe.add(entry, None)
    limit = probe._current.uncompressed_size + len(entry) - 1

    writer = SitemapChunkWriter("en", max_urls=100, max_bytes=limit)
    assert writer.add(entry, None) is None
    finished = writer.add(entry, None)

    assert finished is not None
    assert finished.url_count == 1
    assert finished.uncompressed_size - len(URLSET_FOOTER) <= limit
    assert writer.finish().url_count == 1
    assert len(writer.chunks) == 2


class _Body:
    def __init__(self, data: bytes):
        self._data = data
        self.closed = False

    def iter_chunks(self, chunk_size: int = 1024):
        for start in range(0, len(self._data), chunk_size):
            yield self._data[start : start + chunk_size]

    def close(self):
        self.closed = True


class _S3:
    def __init__(self, objects: dict):
        self.objects = objects
        self.gets: list[str] = []

    def head_object(self, Bucket, Key):
        assert Bucket == settings.SITEMAP_BUCKET
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
            )
        item = self.objects[Key]
        return {
            "ETag": item["etag"],
            "LastModified": item["last_modified"],
            "ContentLength": len(item["body"]),
        }

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        item = self.objects[Key]
        return {"Body": _Body(item["body"])}


def _client(store: _S3, monkeypatch) -> TestClient:
    monkeypatch.setattr(sitemaps, "_s3_client", lambda: store)
    app = FastAPI()
    add_exception_handler(app, new_exception_handler())
    app.include_router(sitemaps.sitemaps_router, prefix="/public/v1/sitemaps")
    return TestClient(app)


def test_sitemap_route_streams_the_object_from_the_site(monkeypatch):
    modified = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    body = b"<sitemapindex></sitemapindex>"
    store = _S3(
        {
            f"{settings.SITEMAP_PREFIX}sitemap-index.xml": {
                "etag": '"abc"',
                "last_modified": modified,
                "body": body,
            }
        }
    )

    response = _client(store, monkeypatch).get("/public/v1/sitemaps/sitemap-index.xml")

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["etag"] == '"abc"'
    assert response.headers["last-modified"] == format_datetime(modified, usegmt=True)
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert store.gets == [f"{settings.SITEMAP_PREFIX}sitemap-index.xml"]


def test_sitemap_route_returns_304_without_downloading_the_body(monkeypatch):
    modified = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    key = f"{settings.SITEMAP_PREFIX}sitemap-lots-en-1.xml.gz"
    store = _S3(
        {key: {"etag": '"abc"', "last_modified": modified, "body": b"gzip-bytes"}}
    )
    client = _client(store, monkeypatch)

    not_modified = client.get(
        "/public/v1/sitemaps/sitemap-lots-en-1.xml.gz",
        headers={"If-None-Match": 'W/"abc"'},
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert store.gets == []

    stale_validator = client.get(
        "/public/v1/sitemaps/sitemap-lots-en-1.xml.gz",
        headers={
            "If-None-Match": '"other"',
            "If-Modified-Since": format_datetime(modified, usegmt=True),
        },
    )
    assert stale_validator.status_code == 200
    assert stale_validator.headers["content-type"].startswith("application/gzip")
    assert stale_validator.content == b"gzip-bytes"

    fresh = client.get(
        "/public/v1/sitemaps/sitemap-lots-en-1.xml.gz",
        headers={"If-Modified-Since": format_datetime(modified, usegmt=True)},
    )
    assert fresh.status_code == 304
    assert store.gets == [key]


def test_sitemap_route_404s_for_missing_or_invalid_paths(monkeypatch):
    store = _S3({})
    client = _client(store, monkeypatch)

    missing = client.get("/public/v1/sitemaps/sitemap-index.xml")
    invalid = client.get("/public/v1/sitemaps/not-a-sitemap.txt")

    assert missing.status_code == 404
    assert invalid.status_code == 404
    assert store.gets == []
    assert sitemaps._is_valid_sitemap_path("static_sitemaps/../secret.xml") is False
