from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import quote, urlencode, urljoin

import requests
from atlassian import Confluence
from atlassian.errors import ApiError, ApiPermissionError

from pull_cli.errors import EXIT_AUTH, EXIT_IO, EXIT_SOURCE, EXIT_VALIDATION, PullError
from pull_cli.models import AttachmentRecord, CommentRecord, Config, PageRecord, PageSummary
from pull_cli.security import redact_value, sanitize_url


class DataCenterClient:
    deployment_type = "data_center"

    def __init__(self, config: Config, *, api: Confluence | None = None) -> None:
        if not config.base_url:
            raise PullError(
                code="ERR_VALIDATION_REQUIRED",
                message="A Confluence base URL is required.",
                exit_code=EXIT_VALIDATION,
                suggested_action="Set --base-url, PULL_URL, or CONFPUB_URL.",
            )
        self.base_url = config.base_url.rstrip("/")
        self.api_calls = 0
        self._api = api or self._build_api(config)

    def _build_api(self, config: Config) -> Confluence:
        kwargs = {
            "url": self.base_url,
            "verify_ssl": config.ssl_verify,
            "timeout": 30,
            "backoff_and_retry": True,
            "retry_status_codes": [429, 502, 503, 504],
            "max_backoff_retries": 3,
            "max_backoff_seconds": 8,
            "backoff_factor": 0.25,
            "backoff_jitter": 0,
        }
        kwargs.update(_auth_kwargs(config))
        return Confluence(**kwargs)

    def close(self) -> None:
        close = getattr(self._api, "close", None)
        if callable(close):
            close()

    def _absolute_url(self, value: str | None) -> str | None:
        if not value:
            return None
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith("/wiki/") and self.base_url.endswith("/wiki"):
            return urljoin(self.base_url.removesuffix("/wiki") + "/", value.lstrip("/"))
        return urljoin(self.base_url + "/", value.lstrip("/"))

    def _call(self, operation, *args, **kwargs):
        self.api_calls += 1
        try:
            return operation(*args, **kwargs)
        except requests.Timeout as exc:
            raise PullError(
                code="ERR_IO_TIMEOUT",
                message="Timed out while contacting Confluence.",
                exit_code=EXIT_IO,
                retryable=True,
                suggested_action="Retry the command or reduce scope.",
            ) from exc
        except (ApiPermissionError, requests.HTTPError) as exc:
            status = _status_code(exc)
            if status in {401, 403}:
                raise PullError(
                    code="ERR_AUTH_FORBIDDEN" if status == 403 else "ERR_AUTH_REQUIRED",
                    message="Confluence authentication failed or the page is not visible.",
                    exit_code=EXIT_AUTH,
                    suggested_action=(
                        "Check credentials and page permissions. For Confluence Data Center PATs, "
                        "retry with --auth bearer or pass --token without --user."
                    ),
                    details=_error_details(exc),
                ) from exc
            if status == 404:
                raise PullError(
                    code="ERR_SOURCE_PAGE_NOT_FOUND",
                    message="The requested Confluence page was not found.",
                    exit_code=EXIT_SOURCE,
                    details=_error_details(exc),
                ) from exc
            raise PullError(
                code="ERR_INTERNAL_API_RESPONSE",
                message=f"Confluence returned HTTP {status or 'error'}.",
                exit_code=EXIT_IO,
                retryable=status in {429, 502, 503, 504},
                details=_error_details(exc),
            ) from exc
        except ApiError as exc:
            raise PullError(
                code="ERR_INTERNAL_API_RESPONSE",
                message="Confluence API returned an error.",
                exit_code=EXIT_IO,
                details={"reason": str(exc)},
            ) from exc
        except requests.RequestException as exc:
            raise PullError(
                code="ERR_IO_CONNECTION",
                message="Could not contact Confluence.",
                exit_code=EXIT_IO,
                retryable=True,
                details={"reason": str(exc)},
            ) from exc

    def _get_paged(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        page_size: int = 100,
    ) -> Iterable[dict[str, object]]:
        start = 0
        while True:
            merged = {"limit": page_size, "start": start}
            if params:
                merged.update(params)
            data = self._call(self._api.get, path, params=merged)
            if not isinstance(data, dict):
                return
            results = data.get("results") or []
            for item in results:
                if isinstance(item, dict):
                    yield item
            if len(results) < page_size:
                break
            start += len(results)

    def get_page(self, page_id: str) -> PageRecord:
        expand = "body.view,body.export_view,body.storage,version,space,metadata.labels,_links,ancestors"
        data = self._call(self._api.get_page_by_id, page_id, expand=expand)
        return self._parse_page(data)

    def find_page(self, space: str, title: str) -> list[PageSummary]:
        path = "rest/api/content"
        params = {"spaceKey": space, "title": title, "type": "page", "expand": "space,_links"}
        return [self._parse_summary(item) for item in self._get_paged(path, params=params)]

    def get_children(self, page_id: str) -> list[PageSummary]:
        children = self._call(
            self._api.get_page_child_by_type,
            page_id=page_id,
            type="page",
            start=0,
            limit=100,
            expand="space,_links,ancestors",
        )
        if children is None:
            return []
        if isinstance(children, dict):
            children = children.get("results", [])
        return [self._parse_summary(item, parent_id=page_id) for item in children if isinstance(item, dict)]

    def get_descendants(self, page_id: str, depth: int | None = None) -> list[PageSummary]:
        path = f"rest/api/content/{page_id}/descendant/page"
        summaries = [self._parse_summary(item) for item in self._get_paged(path)]
        if depth is None:
            return summaries
        return [summary for summary in summaries if summary.depth <= depth]

    def list_attachments(self, page_id: str) -> list[AttachmentRecord]:
        attachments: list[AttachmentRecord] = []
        for item in self._get_paged(
            f"rest/api/content/{page_id}/child/attachment",
            params={"expand": "version,_links,extensions"},
            page_size=100,
        ):
            attachments.append(self._parse_attachment(item, page_id))
        return attachments

    def list_comments(self, page_id: str) -> list[CommentRecord]:
        comments: list[CommentRecord] = []
        seen: set[str] = set()
        for location in (None, "inline"):
            for item in self._get_comment_pages(page_id, location=location):
                comment = self._parse_comment(item, page_id, fallback_location=location or "footer")
                if not comment.comment_id or comment.comment_id in seen:
                    continue
                seen.add(comment.comment_id)
                comments.append(comment)
        return comments

    def download_attachment(self, attachment: AttachmentRecord) -> bytes:
        if not attachment.download_url:
            raise PullError(
                code="ERR_SOURCE_BODY_UNAVAILABLE",
                message=f"Attachment {attachment.filename} has no download URL.",
                exit_code=EXIT_SOURCE,
            )
        return self.download_url(attachment.download_url)

    def download_url(self, url: str) -> bytes:
        absolute = self._absolute_url(url) or url
        return self._call(self._api.get, absolute, not_json_response=True, absolute=True)

    def _get_comment_pages(self, page_id: str, *, location: str | None) -> Iterable[dict[str, object]]:
        start = 0
        page_size = 100
        while True:
            kwargs: dict[str, object] = {
                "content_id": page_id,
                "expand": "body.view,version,history,container,extensions.inlineProperties,extensions.resolution",
                "start": start,
                "limit": page_size,
                "depth": "all",
            }
            if location:
                kwargs["location"] = location
            data = self._call(self._api.get_page_comments, **kwargs)
            if not isinstance(data, dict):
                return
            results = data.get("results") or []
            for item in results:
                if isinstance(item, dict):
                    yield item
            if len(results) < page_size:
                break
            start += len(results)

    def _parse_summary(self, data: dict[str, object], *, parent_id: str | None = None) -> PageSummary:
        links = data.get("_links") if isinstance(data.get("_links"), dict) else {}
        ancestors = data.get("ancestors") if isinstance(data.get("ancestors"), list) else []
        parsed_parent = parent_id
        if not parsed_parent and ancestors:
            last = ancestors[-1]
            if isinstance(last, dict):
                parsed_parent = str(last.get("id") or "") or None
        space = data.get("space") if isinstance(data.get("space"), dict) else {}
        return PageSummary(
            page_id=str(data.get("id") or data.get("contentId") or ""),
            title=str(data.get("title") or "Untitled"),
            space_key=str(space.get("key") or data.get("spaceKey") or "") or None,
            url=self._absolute_url(str(links.get("webui") or "")) if links else None,
            parent_id=parsed_parent,
        )

    def _parse_page(self, data: dict[str, object]) -> PageRecord:
        summary = self._parse_summary(data)
        body = data.get("body") if isinstance(data.get("body"), dict) else {}
        version = data.get("version") if isinstance(data.get("version"), dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        labels_data = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
        labels = [
            str(item.get("name"))
            for item in labels_data.get("results", [])
            if isinstance(item, dict) and item.get("name")
        ]
        return PageRecord(
            page_id=summary.page_id,
            title=summary.title,
            space_key=summary.space_key,
            url=summary.url,
            parent_id=summary.parent_id,
            version=int(version["number"]) if isinstance(version.get("number"), int) else None,
            body_view=_body_value(body, "view"),
            body_export_view=_body_value(body, "export_view"),
            body_storage=_body_value(body, "storage"),
            labels=labels,
            raw=redact_value(data),
        )

    def _parse_attachment(self, data: dict[str, object], page_id: str) -> AttachmentRecord:
        links = data.get("_links") if isinstance(data.get("_links"), dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        media_type = str(metadata.get("mediaType") or data.get("mediaType") or "") or None
        extensions = data.get("extensions") if isinstance(data.get("extensions"), dict) else {}
        return AttachmentRecord(
            attachment_id=str(data.get("id") or ""),
            page_id=page_id,
            filename=str(data.get("title") or data.get("filename") or "attachment"),
            media_type=media_type,
            download_url=self._absolute_url(str(links.get("download") or "")) if links else None,
            web_url=self._absolute_url(str(links.get("webui") or "")) if links else None,
            file_size=int(extensions["fileSize"]) if isinstance(extensions.get("fileSize"), int) else None,
            raw=redact_value(data),
        )

    def _parse_comment(
        self, data: dict[str, object], page_id: str, *, fallback_location: str
    ) -> CommentRecord:
        body = data.get("body") if isinstance(data.get("body"), dict) else {}
        view = body.get("view") if isinstance(body.get("view"), dict) else {}
        version = data.get("version") if isinstance(data.get("version"), dict) else {}
        history = data.get("history") if isinstance(data.get("history"), dict) else {}
        extensions = data.get("extensions") if isinstance(data.get("extensions"), dict) else {}
        resolution = extensions.get("resolution") if isinstance(extensions.get("resolution"), dict) else {}
        parent = data.get("parent") if isinstance(data.get("parent"), dict) else {}
        return CommentRecord(
            comment_id=str(data.get("id") or ""),
            page_id=page_id,
            body_html=str(view.get("value") or ""),
            location=str(extensions.get("location") or fallback_location or "") or None,
            status=str(data.get("status") or "") or None,
            version=int(version["number"]) if isinstance(version.get("number"), int) else None,
            author=_person_display_name(history.get("createdBy")) or _person_display_name(version.get("by")),
            created_at=str(history.get("createdDate") or "") or None,
            updated_at=str(version.get("when") or "") or None,
            parent_id=str(parent.get("id") or data.get("parentId") or "") or None,
            resolution=_resolution_label(resolution),
            raw=redact_value(data),
        )


def _body_value(body: dict[str, object], name: str) -> str | None:
    value = body.get(name)
    if isinstance(value, dict) and isinstance(value.get("value"), str):
        return value["value"]
    return None


def _auth_kwargs(config: Config) -> dict[str, str]:
    if config.auth_mode == "basic":
        if not config.user or not config.token:
            raise PullError(
                code="ERR_VALIDATION_REQUIRED",
                message="Basic authentication requires both a user and token.",
                exit_code=EXIT_VALIDATION,
                suggested_action="Pass --user and --token, or use --auth bearer for PAT-only authentication.",
            )
        return {"username": config.user, "password": config.token}
    if config.auth_mode == "bearer":
        if not config.token:
            raise PullError(
                code="ERR_VALIDATION_REQUIRED",
                message="Bearer authentication requires a token.",
                exit_code=EXIT_VALIDATION,
                suggested_action="Pass --token, PULL_TOKEN, or CONFPUB_TOKEN.",
            )
        return {"token": config.token}
    if config.token and config.user:
        return {"username": config.user, "password": config.token}
    if config.token:
        return {"token": config.token}
    return {}


def _person_display_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return str(value.get("displayName") or value.get("publicName") or value.get("username") or "") or None


def _resolution_label(value: dict[str, object]) -> str | None:
    if not value:
        return None
    for key in ("status", "state"):
        if value.get(key):
            return str(value[key])
    if isinstance(value.get("resolved"), bool):
        return "resolved" if value["resolved"] else "unresolved"
    return None


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if response is not None:
        return getattr(response, "status_code", None)
    reason = getattr(exc, "reason", None)
    response = getattr(reason, "response", None)
    if response is not None:
        return getattr(response, "status_code", None)
    return None


def _error_details(exc: Exception) -> dict[str, object]:
    response = getattr(exc, "response", None) or getattr(getattr(exc, "reason", None), "response", None)
    details: dict[str, object] = {"reason": str(exc)}
    if response is not None:
        details["status_code"] = getattr(response, "status_code", None)
        request = getattr(response, "request", None)
        if request is not None:
            details["url"] = sanitize_url(str(getattr(request, "url", "")))
    return details


def query(params: dict[str, object]) -> str:
    return urlencode(params, doseq=True, quote_via=quote)
