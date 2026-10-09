"""Guide import APIs for fetching public static webpage text."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import ipaddress
import re
import socket
import time
from collections.abc import Mapping
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.dependencies import api_error, get_current_user
from app.models.user import User
from app.utils.logger import app_logger


router = APIRouter(prefix="/guide-import", tags=["攻略导入"])

MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 512 * 1024
MAX_EXTRACTED_TEXT_CHARS = 2400
GUIDE_FETCH_TIMEOUT_SECONDS = 6.0
HTTP_UNPROCESSABLE_CONTENT = 422
GUIDE_IMPORT_USER_AGENT = (
    "ZhiXingTravelPlanner/1.0 (+https://github.com/apearlinspring/langgraph-travel-planner)"
)
ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
)
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}


class GuideImportFetchRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=MAX_URL_LENGTH)


class GuideImportFetchResponse(BaseModel):
    status: str = "success"
    url: str
    final_url: str
    source_domain: str
    title: str = ""
    text: str
    truncated: bool = False
    message: str = ""


class GuideImportError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _FetchedResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    encoding: str | None = None


@dataclass(frozen=True)
class _ExtractedGuideText:
    title: str
    text: str
    truncated: bool


class _GuideHtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._text_parts: list[str] = []
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        name = tag.lower()
        if name in SKIP_TAGS:
            self._skip_depth += 1
            return
        if name == "title":
            self._in_title = True
            return
        if self._skip_depth:
            return
        if name in BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if name == "title":
            self._in_title = False
            return
        if self._skip_depth:
            return
        if name in BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip_depth:
            return
        self._text_parts.append(data)

    @property
    def title(self) -> str:
        return _normalize_text(" ".join(self._title_parts), single_line=True)[:160]

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self._text_parts))


def _normalize_text(value: str, *, single_line: bool = False) -> str:
    text = unescape(str(value or "")).replace("\xa0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    if single_line:
        return re.sub(r"\s+", " ", text).strip()
    lines = [line.strip() for line in text.splitlines()]
    collapsed = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def _header_value(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value or "")
    return ""


def _source_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _resolve_host_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_host_unreachable",
            "无法解析该网页域名，请确认链接是否正确。",
        ) from exc
    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        raw_address = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw_address))
        except ValueError:
            continue
    if not addresses:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_host_unreachable",
            "无法解析该网页域名，请确认链接是否正确。",
        )
    return addresses


def _ensure_public_ip(address: ipaddress._BaseAddress, *, hostname: str) -> None:
    if address.is_global:
        return
    raise GuideImportError(
        HTTP_UNPROCESSABLE_CONTENT,
        "guide_import_url_rejected",
        f"出于安全原因，不能抓取本机、内网或保留地址：{hostname}",
    )


def _normalize_and_validate_url(raw_url: str) -> str:
    text = str(raw_url or "").strip()
    if len(text) > MAX_URL_LENGTH:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_url_too_long",
            "网页链接过长，无法导入。",
        )
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_url_rejected",
            "只支持 http 或 https 开头的公开网页链接。",
        )
    if parsed.username or parsed.password:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_url_rejected",
            "链接中不能包含账号、密码或认证信息。",
        )
    if not parsed.hostname:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_url_rejected",
            "网页链接缺少有效域名。",
        )
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_url_rejected",
            "出于安全原因，不能抓取本机地址。",
        )
    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None
    if direct_ip is not None:
        _ensure_public_ip(direct_ip, hostname=hostname)
    else:
        for address in _resolve_host_ips(hostname):
            _ensure_public_ip(address, hostname=hostname)
    return parsed.geturl()


def _ensure_fetchable_response(response: _FetchedResponse) -> None:
    if response.status_code >= 400:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_fetch_failed",
            f"网页返回 HTTP {response.status_code}，暂时无法导入。",
        )
    content_type = _header_value(response.headers, "content-type").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_content_type_rejected",
            "该链接不是可解析的 HTML 或纯文本页面，暂不支持导入。",
        )


async def _fetch_url_once(client: httpx.AsyncClient, url: str) -> _FetchedResponse:
    headers = {
        "User-Agent": GUIDE_IMPORT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "Cache-Control": "no-cache",
    }
    async with client.stream(
        "GET",
        url,
        headers=headers,
        follow_redirects=False,
    ) as response:
        response_headers = dict(response.headers)
        if response.status_code in REDIRECT_STATUS_CODES:
            return _FetchedResponse(
                status_code=response.status_code,
                headers=response_headers,
                body=b"",
                encoding=response.encoding,
            )
        content_length = _header_value(response_headers, "content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > MAX_RESPONSE_BYTES:
                raise GuideImportError(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "guide_import_page_too_large",
                    "网页内容过大，暂时无法导入；可以复制关键攻略段落后粘贴。",
                )
        chunks: list[bytes] = []
        received = 0
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > MAX_RESPONSE_BYTES:
                raise GuideImportError(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "guide_import_page_too_large",
                    "网页内容过大，暂时无法导入；可以复制关键攻略段落后粘贴。",
                )
            chunks.append(chunk)
        return _FetchedResponse(
            status_code=response.status_code,
            headers=response_headers,
            body=b"".join(chunks),
            encoding=response.encoding,
        )


async def _download_public_page(raw_url: str) -> tuple[str, _FetchedResponse]:
    current_url = _normalize_and_validate_url(raw_url)
    timeout = httpx.Timeout(GUIDE_FETCH_TIMEOUT_SECONDS, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            response = await _fetch_url_once(client, current_url)
            if response.status_code not in REDIRECT_STATUS_CODES:
                _ensure_fetchable_response(response)
                return current_url, response
            if redirect_count >= MAX_REDIRECTS:
                raise GuideImportError(
                    HTTP_UNPROCESSABLE_CONTENT,
                    "guide_import_too_many_redirects",
                    "网页跳转次数过多，暂时无法导入。",
                )
            location = _header_value(response.headers, "location").strip()
            if not location:
                raise GuideImportError(
                    HTTP_UNPROCESSABLE_CONTENT,
                    "guide_import_redirect_invalid",
                    "网页跳转地址无效，暂时无法导入。",
                )
            current_url = _normalize_and_validate_url(urljoin(current_url, location))
    raise GuideImportError(
        HTTP_UNPROCESSABLE_CONTENT,
        "guide_import_fetch_failed",
        "网页暂时无法导入。",
    )


def _extract_guide_text(response: _FetchedResponse) -> _ExtractedGuideText:
    encoding = response.encoding or "utf-8"
    raw_text = response.body.decode(encoding, errors="replace")
    content_type = _header_value(response.headers, "content-type").split(";", 1)[0].strip().lower()
    if content_type == "text/plain":
        title = ""
        extracted = _normalize_text(raw_text)
    else:
        parser = _GuideHtmlTextExtractor()
        parser.feed(raw_text)
        parser.close()
        title = parser.title
        extracted = parser.text
    if len(extracted) < 20:
        raise GuideImportError(
            HTTP_UNPROCESSABLE_CONTENT,
            "guide_import_no_text",
            "网页中没有提取到足够的攻略文字；可以复制正文后粘贴导入。",
        )
    truncated = len(extracted) > MAX_EXTRACTED_TEXT_CHARS
    return _ExtractedGuideText(
        title=title,
        text=extracted[:MAX_EXTRACTED_TEXT_CHARS],
        truncated=truncated,
    )


@router.post("/fetch", response_model=GuideImportFetchResponse)
async def fetch_guide_import_page(
    data: GuideImportFetchRequest,
    user: User = Depends(get_current_user),
) -> GuideImportFetchResponse:
    """Fetch a public static guide page and return sanitized plain text."""

    started_at = time.perf_counter()
    try:
        final_url, response = await _download_public_page(data.url)
        extracted = _extract_guide_text(response)
    except GuideImportError as exc:
        raise api_error(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
        ) from exc
    except httpx.TimeoutException as exc:
        raise api_error(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            code="guide_import_timeout",
            message="网页响应超时，暂时无法导入；可以复制关键攻略段落后粘贴。",
        ) from exc
    except httpx.HTTPError as exc:
        app_logger.info(f"Guide import fetch failed: {exc}")
        raise api_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="guide_import_fetch_failed",
            message="网页抓取失败，暂时无法导入；可以复制关键攻略段落后粘贴。",
        ) from exc

    elapsed = round(time.perf_counter() - started_at, 3)
    app_logger.info(
        "Fetched guide import page: "
        f"user_id={user.id}, source_domain={_source_domain(final_url)}, "
        f"text_chars={len(extracted.text)}, elapsed_seconds={elapsed:.3f}"
    )
    return GuideImportFetchResponse(
        status="success",
        url=data.url.strip(),
        final_url=final_url,
        source_domain=_source_domain(final_url),
        title=extracted.title,
        text=extracted.text,
        truncated=extracted.truncated,
        message=(
            "已抓取网页正文；动态信息仍需核验。"
            if not extracted.truncated
            else "已抓取网页正文前半段；原文较长，动态信息仍需核验。"
        ),
    )
