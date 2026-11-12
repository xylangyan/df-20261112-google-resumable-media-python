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

"""Support for downloading media from Google APIs."""

import urllib3.response  # type: ignore
import http

from google._async_resumable_media import _download
from google._async_resumable_media import _helpers
from google._async_resumable_media.requests import _request_helpers
from google.resumable_media import common
from google.resumable_media import _helpers as sync_helpers
from google.resumable_media.requests import download

_CHECKSUM_MISMATCH = download._CHECKSUM_MISMATCH
_MISSING_CHECKSUM = download._MISSING_CHECKSUM


class Download(_request_helpers.RequestsMixin, _download.Download):
    """Helper to manage downloading a resource from a Google API.

    "Slices" of the resource can be retrieved by specifying a range
    with ``start`` and / or ``end``. However, in typical usage, neither
    ``start`` nor ``end`` is expected to be provided.

    Args:
        media_url (str): The URL containing the media to be downloaded.
        stream (IO[bytes]): A write-able stream (i.e. file-like object) that
            the downloaded resource can be written to.
        start (int): The first byte in a range to be downloaded. If not
            provided, but ``end`` is provided, will download from the
            beginning to ``end`` of the media.
        end (int): The last byte in a range to be downloaded. If not
            provided, but ``start`` is provided, will download from the
            ``start`` to the end of the media.
        headers (Optional[Mapping[str, str]]): Extra headers that should
            be sent with the request, e.g. headers for encrypted data.
        checksum Optional([str]): The type of checksum to compute to verify
            the integrity of the object. The response headers must contain
            a checksum of the requested type. If the headers lack an
            appropriate checksum (for instance in the case of transcoded or
            ranged downloads where the remote service does not know the
            correct checksum) an INFO-level log will be emitted. Supported
            values are "md5", "crc32c" and None. The default is "md5".

    Attributes:
        media_url (str): The URL containing the media to be downloaded.
        start (Optional[int]): The first byte in a range to be downloaded.
        end (Optional[int]): The last byte in a range to be downloaded.
    """

    async def _write_to_stream(self, response):
        """Write response body to a write-able stream.

        .. note:

            This method assumes that the ``_stream`` attribute is set on the
            current download.

        Args:
            response (~requests.Response): The HTTP response object.

        Raises:
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
        """

        # `_get_expected_checksum()` may return None even if a checksum was
        # requested, in which case it will emit an info log _MISSING_CHECKSUM.
        # If an invalid checksum type is specified, this will raise ValueError.
        expected_checksum, checksum_object = sync_helpers._get_expected_checksum(
            response, self._get_headers, self.media_url, checksum_type=self.checksum
        )

        local_checksum_object = _add_decoder(response, checksum_object)

        async for chunk in response.content.iter_chunked(
            _request_helpers._SINGLE_GET_CHUNK_SIZE
        ):
            self._stream.write(chunk)
            local_checksum_object.update(chunk)

        # Don't validate the checksum for partial responses.
        if (
            expected_checksum is not None
            and response.status != http.client.PARTIAL_CONTENT
        ):
            actual_checksum = sync_helpers.prepare_checksum_digest(
                checksum_object.digest()
            )
            if actual_checksum != expected_checksum:
                msg = _CHECKSUM_MISMATCH.format(
                    self.media_url,
                    expected_checksum,
                    actual_checksum,
                    checksum_type=self.checksum.upper(),
                )
                raise common.DataCorruption(response, msg)

    async def consume(self, transport, timeout=_request_helpers._DEFAULT_TIMEOUT):
        """Consume the resource to be downloaded.

        If a ``stream`` is attached to this download, then the downloaded
        resource will be written to the stream.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, aiohttp.ClientTimeout]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.
                Can also be passed as an `aiohttp.ClientTimeout` object.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
            ValueError: If the current :class:`Download` has already
                finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        request_kwargs = {
            "data": payload,
            "headers": headers,
            "retry_strategy": self._retry_strategy,
            "timeout": timeout,
        }

        if self._stream is not None:
            request_kwargs["stream"] = True

        result = await _request_helpers.http_request(
            transport, method, url, **request_kwargs
        )

        self._process_response(result)

        if self._stream is not None:
            await self._write_to_stream(result)

        return result


class RawDownload(_request_helpers.RawRequestsMixin, _download.Download):
    """Helper to manage downloading a raw resource from a Google API.

    "Slices" of the resource can be retrieved by specifying a range
    with ``start`` and / or ``end``. However, in typical usage, neither
    ``start`` nor ``end`` is expected to be provided.

    Args:
        media_url (str): The URL containing the media to be downloaded.
        stream (IO[bytes]): A write-able stream (i.e. file-like object) that
            the downloaded resource can be written to.
        start (int): The first byte in a range to be downloaded. If not
            provided, but ``end`` is provided, will download from the
            beginning to ``end`` of the media.
        end (int): The last byte in a range to be downloaded. If not
            provided, but ``start`` is provided, will download from the
            ``start`` to the end of the media.
        headers (Optional[Mapping[str, str]]): Extra headers that should
            be sent with the request, e.g. headers for encrypted data.
        checksum Optional([str]): The type of checksum to compute to verify
            the integrity of the object. The response headers must contain
            a checksum of the requested type. If the headers lack an
            appropriate checksum (for instance in the case of transcoded or
            ranged downloads where the remote service does not know the
            correct checksum) an INFO-level log will be emitted. Supported
            values are "md5", "crc32c" and None. The default is "md5".

    Attributes:
        media_url (str): The URL containing the media to be downloaded.
        start (Optional[int]): The first byte in a range to be downloaded.
        end (Optional[int]): The last byte in a range to be downloaded.
    """

    async def _write_to_stream(self, response):
        """Write response body to a write-able stream.

        .. note:

            This method assumes that the ``_stream`` attribute is set on the
            current download.

        Args:
            response (~requests.Response): The HTTP response object.

        Raises:
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
        """

        # `_get_expected_checksum()` may return None even if a checksum was
        # requested, in which case it will emit an info log _MISSING_CHECKSUM.
        # If an invalid checksum type is specified, this will raise ValueError.
        expected_checksum, checksum_object = sync_helpers._get_expected_checksum(
            response, self._get_headers, self.media_url, checksum_type=self.checksum
        )

        async for chunk in response.content.iter_chunked(
            _request_helpers._SINGLE_GET_CHUNK_SIZE
        ):
            self._stream.write(chunk)
            checksum_object.update(chunk)

        # Don't validate the checksum for partial responses.
        if (
            expected_checksum is not None
            and response.status != http.client.PARTIAL_CONTENT
        ):
            actual_checksum = sync_helpers.prepare_checksum_digest(
                checksum_object.digest()
            )

            if actual_checksum != expected_checksum:
                msg = _CHECKSUM_MISMATCH.format(
                    self.media_url,
                    expected_checksum,
                    actual_checksum,
                    checksum_type=self.checksum.upper(),
                )
                raise common.DataCorruption(response, msg)

    async def consume(self, transport, timeout=_request_helpers._DEFAULT_TIMEOUT):
        """Consume the resource to be downloaded.

        If a ``stream`` is attached to this download, then the downloaded
        resource will be written to the stream.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, Tuple[float, float]]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.
                Can also be passed as a tuple (connect_timeout, read_timeout).
                See :meth:`requests.Session.request` documentation for details.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
            ValueError: If the current :class:`Download` has already
                finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = await _request_helpers.http_request(
            transport,
            method,
            url,
            data=payload,
            headers=headers,
            retry_strategy=self._retry_strategy,
        )

        self._process_response(result)

        if self._stream is not None:
            await self._write_to_stream(result)

        return result


class FileDownload(Download):
    """Async counterpart of :class:`download.FileDownload`.

    Downloads into an unpublished staging file next to ``destination`` and
    only publishes it (via :func:`os.replace`) once every segment has been
    received and the checksum matches the source. On cancellation,
    checksum failure, a missing expected checksum or a local write error,
    the staging file is discarded and ``destination`` is left untouched so
    an older snapshot remains readable.
    """

    def __init__(
        self,
        media_url,
        destination,
        start=None,
        end=None,
        headers=None,
        checksum="md5",
    ):
        super(FileDownload, self).__init__(
            media_url,
            stream=None,
            start=start,
            end=end,
            headers=headers,
            checksum=checksum,
        )
        self.destination = destination
        self.staging_path = None
        self._require_checksum = checksum is not None
        self._expected_checksum = None
        self._checksum_object = None
        self._published = False

    def _checksum_mismatch_error(self, response, message):
        return common.ChecksumMismatchError(response, message)

    def _write_chunk(self, chunk):
        try:
            self._stream.write(chunk)
        except OSError as exc:
            raise common.LocalWriteError(exc, path=self.staging_path) from exc

    async def _write_to_stream(self, response):
        expected_checksum, checksum_object = sync_helpers._get_expected_checksum(
            response, self._get_headers, self.media_url, checksum_type=self.checksum
        )
        self._expected_checksum = expected_checksum
        self._checksum_object = checksum_object

        if (
            self._require_checksum
            and expected_checksum is None
            and response.status != http.client.PARTIAL_CONTENT
        ):
            msg = _MISSING_CHECKSUM.format(
                self.media_url, checksum_type=self.checksum.upper()
            )
            raise common.MissingChecksum(response, msg)

        local_checksum_object = _add_decoder(response, checksum_object)
        async for chunk in response.content.iter_chunked(
            _request_helpers._SINGLE_GET_CHUNK_SIZE
        ):
            self._write_chunk(chunk)
            local_checksum_object.update(chunk)

        if (
            expected_checksum is not None
            and response.status != http.client.PARTIAL_CONTENT
        ):
            actual_checksum = sync_helpers.prepare_checksum_digest(
                checksum_object.digest()
            )
            if actual_checksum != expected_checksum:
                msg = _CHECKSUM_MISMATCH.format(
                    self.media_url,
                    expected_checksum,
                    actual_checksum,
                    checksum_type=self.checksum.upper(),
                )
                raise self._checksum_mismatch_error(response, msg)

    _open_staging_file = download.FileDownload._open_staging_file
    _publish = download.FileDownload._publish
    _discard_staging_file = download.FileDownload._discard_staging_file
    _verify_staging_file = download.FileDownload._verify_staging_file

    async def _consume_and_publish(self, do_consume):
        stream = self._open_staging_file()
        self._stream = stream
        close_error = None
        try:
            result = await do_consume()
            try:
                stream.flush()
            except OSError as exc:
                raise common.LocalWriteError(exc, path=self.staging_path)
        except BaseException:
            self._stream = None
            try:
                stream.close()
            except OSError:
                pass
            self._discard_staging_file()
            raise

        self._stream = None
        try:
            stream.close()
        except OSError as exc:
            close_error = exc

        if close_error is not None:
            self._discard_staging_file()
            raise common.LocalWriteError(close_error, path=self.staging_path)

        try:
            self._verify_staging_file(result)
            self._publish()
        except BaseException:
            self._discard_staging_file()
            raise
        self.staging_path = None
        return result

    async def consume(self, transport, timeout=_request_helpers._DEFAULT_TIMEOUT):
        async def do_consume():
            return await super(FileDownload, self).consume(
                transport, timeout=timeout
            )

        return await self._consume_and_publish(do_consume)


class RawFileDownload(RawDownload):
    """Raw variant of :class:`FileDownload`."""

    def __init__(
        self,
        media_url,
        destination,
        start=None,
        end=None,
        headers=None,
        checksum="md5",
    ):
        super(RawFileDownload, self).__init__(
            media_url,
            stream=None,
            start=start,
            end=end,
            headers=headers,
            checksum=checksum,
        )
        self.destination = destination
        self.staging_path = None
        self._require_checksum = checksum is not None
        self._expected_checksum = None
        self._checksum_object = None
        self._published = False

    _checksum_mismatch_error = FileDownload._checksum_mismatch_error
    _write_chunk = FileDownload._write_chunk
    _open_staging_file = FileDownload._open_staging_file
    _publish = FileDownload._publish
    _discard_staging_file = FileDownload._discard_staging_file
    _verify_staging_file = FileDownload._verify_staging_file
    _consume_and_publish = FileDownload._consume_and_publish

    async def _write_to_stream(self, response):
        expected_checksum, checksum_object = sync_helpers._get_expected_checksum(
            response, self._get_headers, self.media_url, checksum_type=self.checksum
        )
        self._expected_checksum = expected_checksum
        self._checksum_object = checksum_object

        if (
            self._require_checksum
            and expected_checksum is None
            and response.status != http.client.PARTIAL_CONTENT
        ):
            msg = _MISSING_CHECKSUM.format(
                self.media_url, checksum_type=self.checksum.upper()
            )
            raise common.MissingChecksum(response, msg)

        async for chunk in response.content.iter_chunked(
            _request_helpers._SINGLE_GET_CHUNK_SIZE
        ):
            self._write_chunk(chunk)
            checksum_object.update(chunk)

        if (
            expected_checksum is not None
            and response.status != http.client.PARTIAL_CONTENT
        ):
            actual_checksum = sync_helpers.prepare_checksum_digest(
                checksum_object.digest()
            )
            if actual_checksum != expected_checksum:
                msg = _CHECKSUM_MISMATCH.format(
                    self.media_url,
                    expected_checksum,
                    actual_checksum,
                    checksum_type=self.checksum.upper(),
                )
                raise self._checksum_mismatch_error(response, msg)

    async def consume(self, transport, timeout=_request_helpers._DEFAULT_TIMEOUT):
        async def do_consume():
            return await super(RawFileDownload, self).consume(
                transport, timeout=timeout
            )

        return await self._consume_and_publish(do_consume)


DownloadToFile = FileDownload
RawDownloadToFile = RawFileDownload


async def download_to_file(
    media_url,
    destination,
    transport,
    start=None,
    end=None,
    headers=None,
    checksum="md5",
    timeout=_request_helpers._DEFAULT_TIMEOUT,
):
    """Async convenience wrapper around :class:`FileDownload`."""
    download_obj = FileDownload(
        media_url,
        destination,
        start=start,
        end=end,
        headers=headers,
        checksum=checksum,
    )
    return await download_obj.consume(transport, timeout=timeout)


class ChunkedDownload(_request_helpers.RequestsMixin, _download.ChunkedDownload):
    """Download a resource in chunks from a Google API.

    Args:
        media_url (str): The URL containing the media to be downloaded.
        chunk_size (int): The number of bytes to be retrieved in each
            request.
        stream (IO[bytes]): A write-able stream (i.e. file-like object) that
            will be used to concatenate chunks of the resource as they are
            downloaded.
        start (int): The first byte in a range to be downloaded. If not
            provided, defaults to ``0``.
        end (int): The last byte in a range to be downloaded. If not
            provided, will download to the end of the media.
        headers (Optional[Mapping[str, str]]): Extra headers that should
            be sent with each request, e.g. headers for data encryption
            key headers.

    Attributes:
        media_url (str): The URL containing the media to be downloaded.
        start (Optional[int]): The first byte in a range to be downloaded.
        end (Optional[int]): The last byte in a range to be downloaded.
        chunk_size (int): The number of bytes to be retrieved in each request.

    Raises:
        ValueError: If ``start`` is negative.
    """

    async def consume_next_chunk(
        self, transport, timeout=_request_helpers._DEFAULT_TIMEOUT
    ):

        """
        Consume the next chunk of the resource to be downloaded.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, aiohttp.ClientTimeout]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.
                Can also be passed as an `aiohttp.ClientTimeout` object.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ValueError: If the current download has finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = await _request_helpers.http_request(
            transport,
            method,
            url,
            data=payload,
            headers=headers,
            retry_strategy=self._retry_strategy,
            timeout=timeout,
        )

        await self._process_response(result)
        return result


class RawChunkedDownload(_request_helpers.RawRequestsMixin, _download.ChunkedDownload):
    """Download a raw resource in chunks from a Google API.

    Args:
        media_url (str): The URL containing the media to be downloaded.
        chunk_size (int): The number of bytes to be retrieved in each
            request.
        stream (IO[bytes]): A write-able stream (i.e. file-like object) that
            will be used to concatenate chunks of the resource as they are
            downloaded.
        start (int): The first byte in a range to be downloaded. If not
            provided, defaults to ``0``.
        end (int): The last byte in a range to be downloaded. If not
            provided, will download to the end of the media.
        headers (Optional[Mapping[str, str]]): Extra headers that should
            be sent with each request, e.g. headers for data encryption
            key headers.

    Attributes:
        media_url (str): The URL containing the media to be downloaded.
        start (Optional[int]): The first byte in a range to be downloaded.
        end (Optional[int]): The last byte in a range to be downloaded.
        chunk_size (int): The number of bytes to be retrieved in each request.

    Raises:
        ValueError: If ``start`` is negative.
    """

    async def consume_next_chunk(
        self, transport, timeout=_request_helpers._DEFAULT_TIMEOUT
    ):
        """Consume the next chunk of the resource to be downloaded.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, aiohttp.ClientTimeout]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.
                Can also be passed as an `aiohttp.ClientTimeout` object.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ValueError: If the current download has finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = await _request_helpers.http_request(
            transport,
            method,
            url,
            data=payload,
            headers=headers,
            retry_strategy=self._retry_strategy,
            timeout=timeout,
        )
        await self._process_response(result)
        return result


def _add_decoder(response_raw, checksum):
    """Patch the ``_decoder`` on a ``urllib3`` response.

    This is so that we can intercept the compressed bytes before they are
    decoded.

    Only patches if the content encoding is ``gzip``.

    Args:
        response_raw (urllib3.response.HTTPResponse): The raw response for
            an HTTP request.
        checksum (object):
            A checksum which will be updated with compressed bytes.

    Returns:
        object: Either the original ``checksum`` if ``_decoder`` is not
        patched, or a ``_DoNothingHash`` if the decoder is patched, since the
        caller will no longer need to hash to decoded bytes.
    """

    encoding = response_raw.headers.get("content-encoding", "").lower()
    if encoding != "gzip":
        return checksum

    response_raw._decoder = _GzipDecoder(checksum)
    return _helpers._DoNothingHash()


class _GzipDecoder(urllib3.response.GzipDecoder):
    """Custom subclass of ``urllib3`` decoder for ``gzip``-ed bytes.

    Allows a checksum function to see the compressed bytes before they are
    decoded. This way the checksum of the compressed value can be computed.

    Args:
        checksum (object):
            A checksum which will be updated with compressed bytes.
    """

    def __init__(self, checksum):
        super(_GzipDecoder, self).__init__()
        self._checksum = checksum

    def decompress(self, data, max_length=-1):
        """Decompress the bytes.

        Args:
            data (bytes): The compressed bytes to be decompressed.
            max_length (int): Maximum number of bytes to return. -1 for no
                limit. Forwarded to the underlying decoder when supported.

        Returns:
            bytes: The decompressed bytes from ``data``.
        """
        self._checksum.update(data)
        try:
            return super(_GzipDecoder, self).decompress(data, max_length=max_length)
        except TypeError:
            return super(_GzipDecoder, self).decompress(data)
