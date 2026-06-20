"""Tests for OnlyOffice integration routes."""

import tempfile
import uuid
import os
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb
import routes.document_routes as droutes
from core.database import Document, DocumentVersion
import src.office_onlyoffice as oo

_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_ENGINE = create_engine(
    f"sqlite:///{_TMPDB.name}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
cdb.Base.metadata.create_all(_ENGINE)
_TS = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False)
droutes.SessionLocal = _TS


def _req(user="tester"):
    return SimpleNamespace(
        state=SimpleNamespace(current_user=user),
        client=SimpleNamespace(host="127.0.0.1"),
        base_url="http://localhost:7000"
    )


def _endpoint(method, path):
    mock_upload = MagicMock()
    router = droutes.setup_document_routes(MagicMock(), mock_upload)
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r.endpoint, mock_upload
    raise RuntimeError(f"{method} {path} not found")


@pytest.fixture(autouse=True)
def setup_env():
    with patch.dict(os.environ, {
        "ONLYOFFICE_URL": "http://onlyoffice-server",
        "ONLYOFFICE_JWT_SECRET": "testsecret",
        "ODYSSEUS_API_BASE": "http://localhost:7000"
    }):
        yield


def test_onlyoffice_config():
    db = _TS()
    try:
        doc_id = str(uuid.uuid4())
        upload_id = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4.docx"
        content = f'<!-- onlyoffice_source upload_id="{upload_id}" filename="test.docx" -->\nSome text here.'
        
        doc = Document(
            id=doc_id,
            title="test",
            language="markdown",
            current_content=content,
            version_count=1,
            owner="tester"
        )
        db.add(doc)
        db.commit()

        endpoint, _ = _endpoint("GET", "/api/document/{doc_id}/onlyoffice-config")
        
        # Mock auth
        with patch("routes.document_routes.get_current_user", return_value="tester"):
            import asyncio
            config = asyncio.run(endpoint(doc_id, _req()))
            
            assert config["documentType"] == "word"
            assert config["document"]["title"] == "test.docx"
            assert config["document"]["key"] == f"{doc_id}_1"
            assert "token" in config
            assert config["api_js_url"] == "http://onlyoffice-server/web-apps/apps/api/documents/api.js"
    finally:
        db.close()


def test_onlyoffice_download():
    db = _TS()
    try:
        doc_id = str(uuid.uuid4())
        upload_id = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4.docx"
        content = f'<!-- onlyoffice_source upload_id="{upload_id}" filename="test.docx" -->\nSome text here.'
        
        doc = Document(
            id=doc_id,
            title="test",
            language="markdown",
            current_content=content,
            version_count=1,
            owner="tester"
        )
        db.add(doc)
        db.commit()

        # Generate valid token
        token_payload = {
            "doc_id": doc_id,
            "upload_id": upload_id,
            "filename": "test.docx",
            "user_id": "tester"
        }
        token = oo.sign_payload(token_payload)

        endpoint, _ = _endpoint("GET", "/api/document/{doc_id}/onlyoffice-download")
        
        # Mock _locate_current_user_upload to return a fake file path
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
            tf.write(b"fake docx content")
            fake_path = tf.name

        try:
            with patch("routes.document_routes._locate_current_user_upload", return_value=fake_path):
                import asyncio
                response = asyncio.run(endpoint(doc_id, token, _req()))
                assert response.path == fake_path
                assert response.filename == "test.docx"
        finally:
            if os.path.exists(fake_path):
                os.remove(fake_path)
    finally:
        db.close()


def test_onlyoffice_callback():
    db = _TS()
    try:
        doc_id = str(uuid.uuid4())
        upload_id = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4.docx"
        content = f'<!-- onlyoffice_source upload_id="{upload_id}" filename="test.docx" -->\nOriginal text.'
        
        doc = Document(
            id=doc_id,
            title="test",
            language="markdown",
            current_content=content,
            version_count=1,
            owner="tester"
        )
        db.add(doc)
        db.commit()

        token_payload = {
            "doc_id": doc_id,
            "upload_id": upload_id,
            "filename": "test.docx",
            "user_id": "tester"
        }
        token = oo.sign_payload(token_payload)

        endpoint, _ = _endpoint("POST", "/api/document/{doc_id}/onlyoffice-callback")

        # Fake request context with body and query token
        req_mock = MagicMock()
        async def mock_json():
            return {
                "status": 2,
                "url": "http://onlyoffice-server/download/newfile.docx",
                "key": f"{doc_id}_1"
            }
        req_mock.json = mock_json
        req_mock.query_params = {"token": token}
        req_mock.headers = {}

        # Mock download response
        class FakeResponse:
            status_code = 200
            content = b"edited docx bytes"

        # Mock dependencies
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
            tf.write(b"original docx bytes")
            fake_path = tf.name

        try:
            with patch("routes.document_routes._locate_current_user_upload", return_value=fake_path), \
                 patch("httpx.AsyncClient.get", return_value=FakeResponse()), \
                 patch("src.markitdown_runtime.convert_to_markdown", return_value="Updated text."):
                
                import asyncio
                res = asyncio.run(endpoint(doc_id, req_mock))
                
                assert res == {"error": 0}
                
                # Check file updated
                with open(fake_path, "rb") as f:
                    assert f.read() == b"edited docx bytes"
                
                # Check DB updated
                db.close()
                db = _TS()
                updated_doc = db.query(Document).filter(Document.id == doc_id).first()
                assert "Updated text." in updated_doc.current_content
                assert updated_doc.version_count == 2
                
                # Check version added
                ver = db.query(DocumentVersion).filter(
                    DocumentVersion.document_id == doc_id,
                    DocumentVersion.version_number == 2
                ).first()
                assert ver is not None
                assert "Updated text." in ver.content
        finally:
            if os.path.exists(fake_path):
                os.remove(fake_path)
    finally:
        db.close()
        try:
            if os.path.exists(_TMPDB.name):
                os.remove(_TMPDB.name)
        except OSError:
            pass
