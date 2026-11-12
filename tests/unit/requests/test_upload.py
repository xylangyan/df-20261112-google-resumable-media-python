# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import http.client
import io
import json
import pytest  # type: ignore
import tempfile
from unittest import mock

import requests.exceptions

from google.resumable_media import common
import google.resumable_media.requests.upload as upload_mod


URL_PREFIX = "https://www.googleapis.com/upload/storage/v1/b/{BUCKET}/o"
SIMPLE_URL = URL_PREFIX + "?uploadType=media&name={OBJECT}"
MULTIPART_URL = URL_PREFIX + "?uploadType=multipart"
RESUMABLE_URL = URL_PREFIX + "?uploadType=resumable"
ONE_MB = 1024 * 1024
BASIC_CONTENT = "text/plain"
JSON_TYPE = "application/json; charset=UTF-8"
JSON_TYPE_LINE = b"content-type: application/json; charset=UTF-8\r\n"
EXPECTED_TIMEOUT = (61, 60)
EXAMPLE_XML_UPLOAD_URL = "https://test-project.storage.googleapis.com/test-bucket"
EXAMPLE_XML_MPU_INITIATE_TEXT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<InitiateMultipartUploadResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Bucket>travel-maps</Bucket>
  <Key>paris.jpg</Key>
  <UploadId>{upload_id}</UploadId>
</InitiateMultipartUploadResult>
"""
UPLOAD_ID = "VXBsb2FkIElEIGZvciBlbHZpbmcncyBteS1tb3ZpZS5tMnRzIHVwbG9hZA"
PARTS = {1: "39a59594290b0f9a30662a56d695b71d", 2: "00000000290b0f9a30662a56d695b71d"}
FILE_DATA = b"testdata" * 128


@pytest.fixture(scope="session")
def filename():
    with tempfile.NamedTemporaryFile() as f:
        f.write(FILE_DATA)
        f.flush()
        yield f.name


class TestSimpleUpload(object):
    def test_transmit(self):
        data = b"I have got a lovely bunch of coconuts."
        content_type = BASIC_CONTENT
        upload = upload_mod.SimpleUpload(SIMPLE_URL)

        transport = mock.Mock(spec=["request"])
        transport.request.return_value = _make_response()
        assert not upload.finished
        ret_val = upload.transmit(transport, data, content_type)
        assert ret_val is transport.request.return_value
        upload_headers = {"content-type": content_type}
        transport.request.assert_called_once_with(
            "POST",
            SIMPLE_URL,
            data=data,
            headers=upload_headers,
            timeout=EXPECTED_TIMEOUT,
        )
        assert upload.finished

    def test_transmit_w_custom_timeout(self):
        data = b"I have got a lovely bunch of coconuts."
        content_type = BASIC_CONTENT
        upload = upload_mod.SimpleUpload(SIMPLE_URL)
        transport = mock.Mock(spec=["request"])
        transport.request.return_value = _make_response()

        upload.transmit(transport, data, content_type, timeout=12.6)

        expected_headers = {"content-type": content_type}
        transport.request.assert_called_once_with(
            "POST",
            SIMPLE_URL,
            data=data,
            headers=expected_headers,
            timeout=12.6,
        )


class TestMultipartUpload(object):
    @mock.patch("google.resumable_media._upload.get_boundary", return_value=b"==4==")
    def test_transmit(self, mock_get_boundary):
        data = b"Mock data here and there."
        metadata = {"Hey": "You", "Guys": "90909"}
        content_type = BASIC_CONTENT
        upload = upload_mod.MultipartUpload(MULTIPART_URL)

        transport = mock.Mock(spec=["request"])
        transport.request.return_value = _make_response()
        assert not upload.finished
        ret_val = upload.transmit(transport, data, metadata, content_type)
        assert ret_val is transport.request.return_value
        expected_payload = (
            b"--==4==\r\n"
            + JSON_TYPE_LINE
            + b"\r\n"
            + json.dumps(metadata).encode("utf-8")
            + b"\r\n"
            + b"--==4==\r\n"
            b"content-type: text/plain\r\n"
            b"\r\n"
            b"Mock data here and there.\r\n"
            b"--==4==--"
        )
        multipart_type = b'multipart/related; boundary="==4=="'
        upload_headers = {"content-type": multipart_type}
        transport.request.assert_called_once_with(
            "POST",
            MULTIPART_URL,
            data=expected_payload,
            headers=upload_headers,
            timeout=EXPECTED_TIMEOUT,
        )
        assert upload.finished
        mock_get_boundary.assert_called_once_with()

    @mock.patch("google.resumable_media._upload.get_boundary", return_value=b"==4==")
    def test_transmit_w_custom_timeout(self, mock_get_boundary):
        data = b"Mock data here and there."
        metadata = {"Hey": "You", "Guys": "90909"}
        content_type = BASIC_CONTENT
        upload = upload_mod.MultipartUpload(MULTIPART_URL)
        transport = mock.Mock(spec=["request"])
        transport.request.return_value = _make_response()

        upload.transmit(transport, data, metadata, content_type, timeout=12.6)

        expected_payload = b"".join(
            (
                b"--==4==\r\n",
                JSON_TYPE_LINE,
                b"\r\n",
                json.dumps(metadata).encode("utf-8"),
                b"\r\n",
                b"--==4==\r\n",
                b"content-type: text/plain\r\n",
                b"\r\n",
                b"Mock data here and there.\r\n",
                b"--==4==--",
            )
        )
        multipart_type = b'multipart/related; boundary="==4=="'
        upload_headers = {"content-type": multipart_type}

        transport.request.assert_called_once_with(
            "POST",
            MULTIPART_URL,
            data=expected_payload,
            headers=upload_headers,
            timeout=12.6,
        )
        assert upload.finished
        mock_get_boundary.assert_called_once_with()


class TestResumableUpload(object):
    def test_initiate(self):
        upload = upload_mod.ResumableUpload(RESUMABLE_URL, ONE_MB)
        data = b"Knock knock who is there"
        stream = io.BytesIO(data)
        metadata = {"name": "got-jokes.txt"}

        transport = mock.Mock(spec=["request"])
        location = ("http://test.invalid?upload_id=AACODBBBxuw9u3AA",)
        response_headers = {"location": location}
        post_response = _make_response(headers=response_headers)
        transport.request.return_value = post_response
        # Check resumable_url before.
        assert upload._resumable_url is None
        # Make request and check the return value (against the mock).
        total_bytes = 100
        assert total_bytes > len(data)
        response = upload.initiate(
            transport,
            stream,
            metadata,
            BASIC_CONTENT,
            total_bytes=total_bytes,
            stream_final=False,
        )
        assert response is transport.request.return_value
        # Check resumable_url after.
        assert upload._resumable_url == location
        # Make sure the mock was called as expected.
        json_bytes = b'{"name": "got-jokes.txt"}'
        expected_headers = {
            "content-type": JSON_TYPE,
            "x-upload-content-type": BASIC_CONTENT,
            "x-upload-content-length": "{:d}".format(total_bytes),
        }
        transport.request.assert_called_once_with(
            "POST",
            RESUMABLE_URL,
            data=json_bytes,
            headers=expected_headers,
            timeout=EXPECTED_TIMEOUT,
        )

    def test_initiate_w_custom_timeout(self):
        upload = upload_mod.ResumableUpload(RESUMABLE_URL, ONE_MB)
        data = b"Knock knock who is there"
        stream = io.BytesIO(data)
        metadata = {"name": "got-jokes.txt"}

        transport = mock.Mock(spec=["request"])
        location = ("http://test.invalid?upload_id=AACODBBBxuw9u3AA",)
        response_headers = {"location": location}
        post_response = _make_response(headers=response_headers)
        transport.request.return_value = post_response

        upload.initiate(
            transport,
            stream,
            metadata,
            BASIC_CONTENT,
            total_bytes=100,
            timeout=12.6,
        )

        # Make sure timeout was passed to the transport
        json_bytes = b'{"name": "got-jokes.txt"}'
        expected_headers = {
            "content-type": JSON_TYPE,
            "x-upload-content-type": BASIC_CONTENT,
            "x-upload-content-length": "{:d}".format(100),
        }
        transport.request.assert_called_once_with(
            "POST",
            RESUMABLE_URL,
            data=json_bytes,
            headers=expected_headers,
            timeout=12.6,
        )

    @staticmethod
    def _upload_in_flight(data, headers=None):
        upload = upload_mod.ResumableUpload(RESUMABLE_URL, ONE_MB, headers=headers)
        upload._stream = io.BytesIO(data)
        upload._content_type = BASIC_CONTENT
        upload._total_bytes = len(data)
        upload._resumable_url = "http://test.invalid?upload_id=not-none"
        return upload

    @staticmethod
    def _chunk_mock(status_code, response_headers):
        transport = mock.Mock(spec=["request"])
        put_response = _make_response(status_code=status_code, headers=response_headers)
        transport.request.return_value = put_response

        return transport

    def test_transmit_next_chunk(self):
        data = b"This time the data is official."
        upload = self._upload_in_flight(data)
        # Make a fake chunk size smaller than 256 KB.
        chunk_size = 10
        assert chunk_size < len(data)
        upload._chunk_size = chunk_size
        # Make a fake 308 response.
        response_headers = {"range": "bytes=0-{:d}".format(chunk_size - 1)}
        transport = self._chunk_mock(http.client.PERMANENT_REDIRECT, response_headers)
        # Check the state before the request.
        assert upload._bytes_uploaded == 0

        # Make request and check the return value (against the mock).
        response = upload.transmit_next_chunk(transport)
        assert response is transport.request.return_value
        # Check that the state has been updated.
        assert upload._bytes_uploaded == chunk_size
        # Make sure the mock was called as expected.
        payload = data[:chunk_size]
        content_range = "bytes 0-{:d}/{:d}".format(chunk_size - 1, len(data))
        expected_headers = {
            "content-range": content_range,
            "content-type": BASIC_CONTENT,
        }
        transport.request.assert_called_once_with(
            "PUT",
            upload.resumable_url,
            data=payload,
            headers=expected_headers,
            timeout=EXPECTED_TIMEOUT,
        )

    def test_transmit_next_chunk_w_custom_timeout(self):
        data = b"This time the data is official."
        upload = self._upload_in_flight(data)

        # Make a fake chunk size smaller than 256 KB.
        chunk_size = 10
        upload._chunk_size = chunk_size

        # Make a fake 308 response.
        response_headers = {"range": "bytes=0-{:d}".format(chunk_size - 1)}
        transport = self._chunk_mock(http.client.PERMANENT_REDIRECT, response_headers)

        # Make request and check the return value (against the mock).
        upload.transmit_next_chunk(transport, timeout=12.6)

        # Make sure timeout was passed to the transport
        payload = data[:chunk_size]
        content_range = "bytes 0-{:d}/{:d}".format(chunk_size - 1, len(data))
        expected_headers = {
            "content-range": content_range,
            "content-type": BASIC_CONTENT,
        }
        transport.request.assert_called_once_with(
            "PUT",
            upload.resumable_url,
            data=payload,
            headers=expected_headers,
            timeout=12.6,
        )

    def test_recover(self):
        upload = upload_mod.ResumableUpload(RESUMABLE_URL, ONE_MB)
        upload._invalid = True  # Make sure invalid.
        upload._stream = mock.Mock(spec=["seek", "seekable", "tell"])
        upload._stream.tell.return_value = 55556
        upload._stream.seekable.return_value = True
        upload._resumable_url = "http://test.invalid?upload_id=big-deal"

        end = 55555
        headers = {"range": "bytes=0-{:d}".format(end)}
        transport = self._chunk_mock(http.client.PERMANENT_REDIRECT, headers)

        ret_val = upload.recover(transport)
        assert ret_val is transport.request.return_value
        # Check the state of ``upload`` after.
        assert upload.bytes_uploaded == end + 1
        assert not upload.invalid
        upload._stream.seek.assert_called_once_with(end + 1)
        expected_headers = {"content-range": "bytes */*"}
        transport.request.assert_called_once_with(
            "PUT",
            upload.resumable_url,
            data=None,
            headers=expected_headers,
            timeout=EXPECTED_TIMEOUT,
        )

    def test_recover_and_resume_mid_chunk(self):
        # Simulate a proxy dropping the connection while forwarding a chunk:
        # the local stream has been read to the end of the chunk, but the
        # server only persisted the first half of it. After recover(), the
        # upload must resume from the next byte confirmed by the server.
        data = b"0123456789ABCDEFGHIJ"
        upload = upload_mod.ResumableUpload(
            RESUMABLE_URL, ONE_MB, checksum="md5"
        )
        upload._retry_strategy = common.RetryStrategy(max_retries=0)
        stream = io.BytesIO(data)

        resumable_url = "http://test.invalid?upload_id=mid-chunk"
        initiate_response = _make_response(headers={"location": resumable_url})
        transport = mock.Mock(spec=["request"])
        transport.request.return_value = initiate_response
        upload.initiate(transport, stream, {"name": "archive.tar"}, BASIC_CONTENT)
        assert upload.total_bytes == len(data)

        # The chunk request dies mid-flight. The payload was already read
        # from the stream, so the stream position is at the chunk end.
        transport.request.side_effect = requests.exceptions.ConnectionError(
            "proxy dropped the connection"
        )
        with pytest.raises(requests.exceptions.ConnectionError):
            upload.transmit_next_chunk(transport)
        assert stream.tell() == len(data)
        assert upload.bytes_uploaded == 0

        # The server confirms it received only the first half of the chunk.
        server_received = 10
        recover_response = _make_response(
            status_code=http.client.PERMANENT_REDIRECT,
            headers={"range": "bytes=0-{:d}".format(server_received - 1)},
        )
        transport.request.side_effect = None
        transport.request.return_value = recover_response
        upload.recover(transport)
        assert upload.bytes_uploaded == server_received
        assert stream.tell() == server_received
        assert not upload.invalid

        # The resumed upload sends only the bytes the server is missing.
        final_response = _make_response(
            metadata={"md5Hash": "FiHRzgCU/BVFuqMWd97ulA=="}
        )
        transport.request.return_value = final_response
        response = upload.transmit_next_chunk(transport)
        assert response is final_response
        assert upload.finished
        assert upload.bytes_uploaded == len(data)

        # Check every request actually sent: the failed chunk, the status
        # probe and the resumed chunk.
        expected_headers = {
            "content-range": "bytes 0-{:d}/{:d}".format(len(data) - 1, len(data)),
            "content-type": BASIC_CONTENT,
        }
        recover_headers = {"content-range": "bytes */*"}
        resumed_headers = {
            "content-range": "bytes {:d}-{:d}/{:d}".format(
                server_received, len(data) - 1, len(data)
            ),
            "content-type": BASIC_CONTENT,
        }
        assert transport.request.call_args_list == [
            mock.call(
                "POST",
                RESUMABLE_URL,
                data=b'{"name": "archive.tar"}',
                headers={
                    "content-type": JSON_TYPE,
                    "x-upload-content-type": BASIC_CONTENT,
                    "x-upload-content-length": "{:d}".format(len(data)),
                },
                timeout=EXPECTED_TIMEOUT,
            ),
            mock.call(
                "PUT",
                resumable_url,
                data=data,
                headers=expected_headers,
                timeout=EXPECTED_TIMEOUT,
            ),
            mock.call(
                "PUT",
                resumable_url,
                data=None,
                headers=recover_headers,
                timeout=EXPECTED_TIMEOUT,
            ),
            mock.call(
                "PUT",
                resumable_url,
                data=data[server_received:],
                headers=resumed_headers,
                timeout=EXPECTED_TIMEOUT,
            ),
        ]
        # The re-transmitted bytes must not be checksummed twice: the final
        # md5 covers the whole payload exactly once.
        assert upload._bytes_checksummed == len(data)


def test_mpu_container():
    container = upload_mod.XMLMPUContainer(EXAMPLE_XML_UPLOAD_URL, filename)

    response_text = EXAMPLE_XML_MPU_INITIATE_TEXT_TEMPLATE.format(upload_id=UPLOAD_ID)

    transport = mock.Mock(spec=["request"])
    transport.request.return_value = _make_response(text=response_text)
    container.initiate(transport, BASIC_CONTENT)
    assert container.upload_id == UPLOAD_ID

    for part, etag in PARTS.items():
        container.register_part(part, etag)

    assert container._parts == PARTS

    transport = mock.Mock(spec=["request"])
    transport.request.return_value = _make_response()
    container.finalize(transport)
    assert container.finished


def test_mpu_container_cancel():
    container = upload_mod.XMLMPUContainer(
        EXAMPLE_XML_UPLOAD_URL, filename, upload_id=UPLOAD_ID
    )

    transport = mock.Mock(spec=["request"])
    transport.request.return_value = _make_response(status_code=204)
    container.cancel(transport)


def test_mpu_part(filename):
    part = upload_mod.XMLMPUPart(EXAMPLE_XML_UPLOAD_URL, UPLOAD_ID, filename, 0, 128, 1)

    transport = mock.Mock(spec=["request"])
    transport.request.return_value = _make_response(headers={"etag": PARTS[1]})

    part.upload(transport)

    assert part.finished
    assert part.etag == PARTS[1]


def _make_response(status_code=http.client.OK, headers=None, text=None, metadata=None):
    headers = headers or {}
    return mock.Mock(
        headers=headers,
        status_code=status_code,
        text=text,
        json=mock.Mock(return_value=metadata),
        spec=["headers", "status_code", "text"],
    )
