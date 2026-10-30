#!/usr/bin/env python3
"""Publish a Thunderstore-style package zip to Hexium.gg or Thunderstore.io.

Both stores implement Thunderstore's experimental submission API, so the flow is the one
Thunderstore's own CLI (tcli 0.2.4) uses, endpoint for endpoint:

    1. POST /api/experimental/usermedia/initiate-upload/         -> uuid + presigned part URLs
    2. PUT  <presigned url> once per part                        -> the bytes (with Content-MD5)
    3. POST /api/experimental/usermedia/{uuid}/finish-upload/    -> marks the upload complete
    4. POST /api/experimental/submission/submit/                 -> the version goes live

The submit body mirrors tcli's PackageUploadMetadata: `categories` carries site-wide
categories (the "" key of [publish.categories]), `community_categories` carries the
per-community ones, `author_name` is the team/namespace the token belongs to.

Standard library only (Python 3.11+ for tomllib), so it runs on a CI box untouched.

Usage:
    HEXIUM_API_TOKEN=... python publish-hexium.py dist/publish.zip
    python publish-hexium.py dist/publish.zip --team YOUR_TEAM --categories "Open Source,Valheim 1.0"
    THUNDERSTORE_API_TOKEN=... python publish-hexium.py dist/publish.zip --repository https://thunderstore.io
    python publish-hexium.py dist/publish.zip --check-only   # no token, no upload
    python publish-hexium.py dist/publish.zip --dry-run      # full upload, then abort

The store is the URL: --repository (or [publish] repository in the config) decides which
token, which team variable and which config file apply, so the credential of the other
store is never picked up by mistake:

    Hexium        -> HEXIUM_API_TOKEN   / HEXIUM_TEAM   / hexium.toml
    Thunderstore  -> THUNDERSTORE_API_TOKEN / THUNDERSTORE_TEAM / thunderstore.toml

A Hexium token must be created on the team settings page (settings icon next to your
username -> team management page -> "create a new API token" at the bottom); a
Thunderstore token comes from account settings -> API tokens. A user/session token is
refused.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

DEFAULT_REPOSITORY = "https://hexium.gg"
DEFAULT_CONFIG = "hexium.toml"
THUNDERSTORE_CONFIG = "thunderstore.toml"
TOKEN_HINTS = {
    "hexium": (
        "create a fresh token on Hexium (sign in -> settings icon next to your username -> "
        "team management page -> 'create a new API token' at the bottom) and store it in the "
        "HEXIUM_API_TOKEN secret"
    ),
    "thunderstore": (
        "create a fresh token on Thunderstore (sign in -> account settings -> API tokens -> "
        "generate a new token) and store it in the THUNDERSTORE_API_TOKEN secret"
    ),
}
STORE_LABELS = {"hexium": "Hexium", "thunderstore": "Thunderstore"}
ICON_SIDE = 256
MAX_DESCRIPTION = 256
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TRANSIENT_STATUSES = {500, 502, 503, 504}


class PublishError(Exception):
    """Anything the operator needs to fix; reported as a single ERROR line."""


def log(message: str = "") -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------------------


def store_key(repository: str) -> str:
    """Which store a URL talks to: 'thunderstore', otherwise 'hexium'.

    Self-hosted Hexium instances and every other Thunderstore-compatible host therefore
    keep the Hexium credential names.
    """
    return "thunderstore" if "thunderstore" in (repository or "").lower() else "hexium"


def store_env_names(repository: str) -> tuple[str, str]:
    """(token, team) environment variables accepted for this store.

    Only the names of the store are read, so a credential belonging to the other store is
    never reused — that mistake fails with an opaque 401 instead of a clear message.
    """
    if store_key(repository) == "thunderstore":
        return "THUNDERSTORE_API_TOKEN", "THUNDERSTORE_TEAM"
    return "HEXIUM_API_TOKEN", "HEXIUM_TEAM"


def default_config_name(repository_hint: str) -> str:
    """Config file picked when --config is not given, decided by the URL hint."""
    if store_key(repository_hint) == "thunderstore":
        return THUNDERSTORE_CONFIG
    return DEFAULT_CONFIG


def resolve_config_path(repository_hint: str, explicit: str | None) -> str:
    """--config always wins; otherwise the hint picks the file, then any file present."""
    if explicit is not None:
        return explicit
    preferred = default_config_name(repository_hint)
    if os.path.isfile(preferred):
        return preferred
    if not repository_hint:  # no hint: fall back to the other store's file rather than nothing
        other = THUNDERSTORE_CONFIG if preferred == DEFAULT_CONFIG else DEFAULT_CONFIG
        if os.path.isfile(other):
            return other
    return preferred


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------


def http_request(
    url: str,
    *,
    method: str = "GET",
    body: object = None,
    token: str | None = None,
    scheme: str = "Bearer",
    headers: dict | None = None,
    timeout: float = 120,
    attempts: int = 3,
) -> tuple[int, str, dict]:
    """Perform one request, retrying transient failures.

    Returns (status, response text, response headers). HTTP errors are returned, not
    raised, so the caller can inspect the server's detail field.
    """
    if isinstance(body, (bytes, bytearray)):
        data: bytes = bytes(body)
        content_type = None
    elif body is None:
        data = None
        content_type = None
    else:
        data = json.dumps(body).encode("utf-8")
        content_type = "application/json"

    request_headers = {
        "Accept": "application/json",
        "User-Agent": "publish-hexium/1.0",
    }
    if content_type:
        request_headers["Content-Type"] = content_type
    if token:
        request_headers["Authorization"] = f"{scheme} {token}"
    if headers:
        request_headers.update(headers)

    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", "replace")
                return response.status, text, dict(response.headers)
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            if error.code in TRANSIENT_STATUSES and attempt < attempts:
                time.sleep(attempt * 2)
                continue
            return error.code, text, dict(error.headers or {})
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt < attempts:
                time.sleep(attempt * 2)
                continue
            raise PublishError(f"{method} {url} could not be reached: {error}") from error

    raise PublishError(f"{method} {url} failed after {attempts} attempts")


def error_detail(status: int, text: str) -> str:
    """Pull the useful sentence out of an error response."""
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("detail", "file", "non_field_errors"):
            if key in payload:
                value = payload[key]
                if isinstance(value, list):
                    value = "; ".join(str(item) for item in value)
                return f"{key}: {value}"
        return json.dumps(payload, ensure_ascii=False)
    if isinstance(payload, list):
        return json.dumps(payload, ensure_ascii=False)
    stripped = text.strip()
    return stripped[:600] if stripped else "(no response body)"


class Session:
    """Authenticated calls: picks an Authorization scheme once, then sticks to it."""

    def __init__(self, token: str, timeout: float, hint: str = ""):
        self.token = token
        self.timeout = timeout
        self.scheme = "Bearer"
        self._fell_back = False
        self.hint = hint

    def call(
        self,
        url: str,
        *,
        method: str = "POST",
        body: object = None,
        expected: tuple[int, ...] = (200, 201),
        step: str = "",
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict | list | None]:
        while True:
            status, text, _ = http_request(
                url,
                method=method,
                body=body,
                token=self.token,
                scheme=self.scheme,
                headers=headers,
                timeout=timeout if timeout is not None else self.timeout,
            )
            # Hexium answers "Authentication required." when it cannot map the credential
            # to an account; Thunderstore says the same with its own wording. One retry
            # with the other scheme covers both stores.
            if (
                status == 401
                and self.scheme == "Bearer"
                and not self._fell_back
                and ("Authentication required" in text or "Authentication credentials" in text)
            ):
                log("  (401 with 'Bearer', retrying with the 'Token' scheme)")
                self.scheme = "Token"
                self._fell_back = True
                continue
            break

        if status not in expected:
            where = f"{step}: " if step else ""
            message = f"{where}HTTP {status} from {url}\n{error_detail(status, text)}"
            if status == 401 and self.hint:
                message += f"\n{self.hint}."
            raise PublishError(message)

        if not text:
            return status, None
        try:
            return status, json.loads(text)
        except ValueError:
            return status, None


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


def load_config(path: str | None, explicit: bool) -> dict:
    """Read the store's TOML project file (tcli spelling), if there is one."""
    if not path:
        return {}
    if not os.path.isfile(path):
        if explicit:
            raise PublishError(f"config file not found: {path}")
        log(f"config: {path} not found (command line only)")
        return {}
    if tomllib is None:
        raise PublishError("reading the config needs Python 3.11+ (tomllib); pass options instead")
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    log(f"config: {path}")
    return data


def config_repository(config: dict) -> str | None:
    # tcli 0.2.x only ever reads [publish].repository; [general].repository is ignored by
    # tcli but accepted here, since older Hexium examples used that spelling.
    publish = config.get("publish") or {}
    general = config.get("general") or {}
    return publish.get("repository") or general.get("repository")


def config_categories(config: dict) -> dict[str, list[str]]:
    """Return {community: [categories]}; the "" key holds site-wide categories."""
    publish = config.get("publish") or {}
    raw = publish.get("categories")
    if isinstance(raw, list):  # tcli's array form means "site-wide categories"
        return {"": [str(item) for item in raw]}
    if isinstance(raw, dict):
        return {str(key): [str(item) for item in (value or [])] for key, value in raw.items()}
    return {}


def load_token(env_path: str | None, repository: str) -> tuple[str, str]:
    """Read the store's own token from the environment, then from the .env file."""
    name, _ = store_env_names(repository)
    value = os.environ.get(name, "").strip()
    if value:
        return value, f"environment variable {name}"
    if env_path and os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as handle:
            entries = {}
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                entries[key.strip()] = value.strip().strip('"').strip("'")
        if entries.get(name, "").strip():
            return entries[name].strip(), f"{env_path} ({name})"
    raise PublishError(
        f"no API token found in {name} (or {env_path or '.env'}); "
        f"{TOKEN_HINTS[store_key(repository)]}"
    )


# --------------------------------------------------------------------------------------
# Package validation
# --------------------------------------------------------------------------------------


def validate_package(zip_path: str, strict: bool) -> dict:
    """Check the archive against the stores' rules. Warnings only, unless --strict."""
    if not os.path.isfile(zip_path):
        raise PublishError(f"no such file: {zip_path}")

    warnings: list[str] = []
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as error:
        raise PublishError(f"{zip_path} is not a valid zip: {error}") from error

    with archive:
        names = archive.namelist()
        if "manifest.json" not in names:
            raise PublishError(
                "manifest.json must sit at the root of the archive "
                f"(found {len(names)} entries, first few: {names[:5]})"
            )
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except ValueError as error:
            raise PublishError(f"manifest.json is not valid JSON: {error}") from error
        if not isinstance(manifest, dict):
            raise PublishError("manifest.json must contain a JSON object")

        if "icon.png" not in names:
            warnings.append("icon.png is missing from the archive root")
        else:
            icon = archive.read("icon.png")
            if icon[:8] != PNG_SIGNATURE:
                warnings.append("icon.png is not a PNG")
            else:
                width, height = struct.unpack(">II", icon[16:24])
                if (width, height) != (ICON_SIDE, ICON_SIDE):
                    warnings.append(f"icon.png is {width}x{height}, {ICON_SIDE}x{ICON_SIDE} is required")

        if "README.md" not in names:
            warnings.append("README.md is missing from the archive root")

    name = str(manifest.get("name") or "")
    if not name or not name.isascii() or not all(char.isalnum() or char == "_" for char in name):
        warnings.append(f"manifest name must be ASCII letters, digits and underscores: {name!r}")

    description = str(manifest.get("description") or "")
    if len(description) > MAX_DESCRIPTION:
        warnings.append(f"description is {len(description)} characters, the limit is {MAX_DESCRIPTION}")

    version = str(manifest.get("version_number") or "")
    if not version:
        warnings.append("manifest.json has no version_number")

    for warning in warnings:
        log(f"  warning: {warning}")
    if warnings and strict:
        raise PublishError(f"{len(warnings)} package problem(s) reported, refused because of --strict")

    log(
        f"package: {name or '?'} {version or '?'} "
        f"({os.path.getsize(zip_path):,} bytes, {len(manifest.get('dependencies', []))} dependencies)"
    )
    return manifest


def check_categories(repository: str, communities: list[str], wanted: dict[str, list[str]], timeout: float) -> None:
    """Confirm every requested category still exists on each community."""
    for community in communities:
        names = wanted.get(community, [])
        if not names:
            continue
        url = f"{repository}/api/experimental/community/{community}/category/"
        try:
            status, text, _ = http_request(url, timeout=timeout, attempts=2)
        except PublishError as error:
            log(f"  warning: could not list {community} categories ({error}); skipping the check")
            continue
        if status != 200:
            log(f"  warning: {url} answered HTTP {status}; skipping the category check")
            continue
        try:
            results = json.loads(text).get("results", [])
        except (ValueError, AttributeError):
            log(f"  warning: unreadable category list from {url}; skipping the check")
            continue
        known = {entry.get("name") for entry in results}
        unknown = [category for category in names if category not in known]
        if unknown:
            sample = ", ".join(sorted(item for item in known if item)[:12])
            raise PublishError(
                f"unknown {community} categories: {', '.join(unknown)}; available: {sample}, ..."
            )
        log(f"  {community}: {len(names)} categories verified")


# --------------------------------------------------------------------------------------
# Upload + submit
# --------------------------------------------------------------------------------------


def upload_parts(session: Session, repository: str, zip_path: str, upload_urls: list[dict]) -> list[dict]:
    total = len(upload_urls)
    parts = []
    with open(zip_path, "rb") as handle:
        for entry in upload_urls:
            offset = int(entry["offset"])
            length = int(entry["length"])
            part_number = int(entry["part_number"])
            handle.seek(offset)
            chunk = handle.read(length)
            if len(chunk) != length:
                raise PublishError(f"could only read {len(chunk)} of {length} bytes for part {part_number}")

            digest = base64.b64encode(hashlib.md5(chunk).digest()).decode("ascii")
            status, text, headers = http_request(
                entry["url"],
                method="PUT",
                body=chunk,
                headers={"Content-Type": "application/octet-stream", "Content-MD5": digest},
                timeout=max(300, session.timeout),
            )
            if status not in (200, 204):
                raise PublishError(
                    f"part {part_number}/{total} upload failed: HTTP {status} {error_detail(status, text)}"
                )
            etag = headers.get("ETag") or headers.get("etag")
            if not etag:
                raise PublishError(f"part {part_number}/{total} returned no ETag")
            parts.append({"ETag": etag, "PartNumber": part_number})
            log(f"  part {part_number}/{total}: {length:,} bytes")
    return parts


def abort_upload(session: Session, repository: str, uuid: str) -> None:
    try:
        session.call(
            f"{repository}/api/experimental/usermedia/{uuid}/abort-upload/",
            expected=(200, 204, 404),
            step="aborting the upload",
        )
    except PublishError as error:
        log(f"  warning: could not abort upload {uuid}: {error}")


def resolve_communities(args: argparse.Namespace, config: dict) -> list[str]:
    """--communities overrides the config; both are comma-separated lists."""
    if args.communities:
        return [item.strip() for item in args.communities.split(",") if item.strip()]
    publish_config = config.get("publish") or {}
    return [str(item) for item in publish_config.get("communities") or []]


def publish(args: argparse.Namespace, config: dict, repository: str, token: str) -> None:
    communities = resolve_communities(args, config)
    if not communities:
        raise PublishError(
            "no community given: pass --communities or set [publish] communities in the config"
        )

    categories = config_categories(config)
    if args.categories:
        supplied = [item.strip() for item in args.categories.split(",") if item.strip()]
        categories = {key: value for key, value in categories.items() if key == ""}
        for community in communities:
            categories[community] = list(supplied)
    site_wide = categories.get("", [])
    per_community = {key: value for key, value in categories.items() if key}

    store = STORE_LABELS[store_key(repository)]
    _, team_env = store_env_names(repository)
    team = args.team or os.environ.get(team_env, "").strip() or (config.get("package") or {}).get("namespace")
    nsfw = args.nsfw or bool((config.get("package") or {}).get("containsNsfwContent"))

    log(f"repository: {repository}")
    log(f"communities: {', '.join(communities)}")
    if per_community:
        for key, value in per_community.items():
            log(f"categories[{key}]: {', '.join(value)}")
    if site_wide:
        log(f"site-wide categories: {', '.join(site_wide)}")
    log(f"team: {team or '(not set, the store will decide from the token)'}")

    if not args.skip_category_check:
        check_categories(repository, communities, per_community, args.timeout)

    session = Session(token, args.timeout, hint=TOKEN_HINTS[store_key(repository)])

    size = os.path.getsize(args.zip)
    filename = os.path.basename(args.zip)
    log(f"[1/4] initiating upload of {filename} ({size:,} bytes)")
    _, initiated = session.call(
        f"{repository}/api/experimental/usermedia/initiate-upload/",
        body={"filename": filename, "file_size_bytes": size},
        expected=(200, 201),
        step="initiating the upload",
    )
    try:
        uuid = initiated["user_media"]["uuid"]
        upload_urls = initiated["upload_urls"]
    except (KeyError, TypeError) as error:
        raise PublishError(f"unexpected initiate-upload response: {initiated!r}") from error
    log(f"  upload {uuid} in {len(upload_urls)} part(s)")

    try:
        log("[2/4] uploading parts")
        parts = upload_parts(session, repository, args.zip, upload_urls)

        log("[3/4] finalizing the upload")
        session.call(
            f"{repository}/api/experimental/usermedia/{uuid}/finish-upload/",
            body={"parts": parts},
            step="finishing the upload",
        )
    except PublishError:
        abort_upload(session, repository, uuid)
        raise

    if args.dry_run:
        log("[4/4] dry run: upload aborted, nothing submitted")
        abort_upload(session, repository, uuid)
        return

    payload: dict = {
        "categories": site_wide,
        "communities": communities,
        "community_categories": dict(per_community),
        "has_nsfw_content": nsfw,
        "upload_uuid": uuid,
    }
    extra = sorted(set(per_community) - set(communities))
    if extra:
        log(f"  warning: categories set for {', '.join(extra)} but those communities are not published")
    if team:
        payload["author_name"] = team

    log("[4/4] submitting the package")
    log(f"  payload: {json.dumps(payload, ensure_ascii=False)}")
    try:
        _, result = session.call(
            f"{repository}/api/experimental/submission/submit/",
            body=payload,
            expected=(200, 201, 202),
            step="submitting the package",
        )
    except PublishError as error:
        abort_upload(session, repository, uuid)
        message = str(error)
        if not team and ("author_name" in message or "author" in message):
            message += (
                f"\n{store} wants the publishing team: pass --team <namespace>, set {team_env}, "
                "or add [package] namespace to the config."
            )
        raise PublishError(message) from error

    if isinstance(result, dict):
        if result.get("hidden"):
            log("published (the listing is hidden until it passes review)")
        for entry in result.get("available_communities") or []:
            url = entry.get("url")
            if url:
                log(f"available at {url}")
        version = (result.get("package_version") or {}).get("download_url")
        if version:
            log(f"download: {version}")
        log("done")
    else:
        log("done (the server returned no body)")


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a package zip to Hexium.gg or Thunderstore.io (Thunderstore-compatible API).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The token is never printed and never passed on the command line.",
    )
    parser.add_argument("zip", help="the package to upload")
    parser.add_argument(
        "--config",
        default=None,
        help="project config (default: hexium.toml, or thunderstore.toml for thunderstore.io)",
    )
    parser.add_argument("--repository", help=f"store base URL (default: from config, else {DEFAULT_REPOSITORY})")
    parser.add_argument("--team", help="namespace the token belongs to (author_name)")
    parser.add_argument("--communities", help="comma-separated communities (default: from config)")
    parser.add_argument("--categories", help="comma-separated categories applied to every community")
    parser.add_argument("--nsfw", action="store_true", help="mark the package as NSFW")
    parser.add_argument("--check-only", action="store_true", help="validate the package and exit")
    parser.add_argument("--dry-run", action="store_true", help="upload, then abort instead of submitting")
    parser.add_argument("--strict", action="store_true", help="turn package warnings into errors")
    parser.add_argument("--skip-category-check", action="store_true", help="do not verify categories online")
    parser.add_argument("--env-file", default=".env", help="file holding the token (default: .env)")
    parser.add_argument("--timeout", type=float, default=120, help="per-request timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        hint = (args.repository or os.environ.get("HEXIUM_REPOSITORY", "").strip() or "").strip()
        config_path = resolve_config_path(hint, args.config)
        config = load_config(config_path, explicit=args.config is not None)
        validate_package(args.zip, args.strict)

        repository = (
            args.repository
            or os.environ.get("HEXIUM_REPOSITORY", "").strip()
            or config_repository(config)
            or DEFAULT_REPOSITORY
        ).rstrip("/")

        if args.check_only:
            communities = resolve_communities(args, config)
            categories = config_categories(config)
            if args.categories:
                supplied = [item.strip() for item in args.categories.split(",") if item.strip()]
                categories = {community: list(supplied) for community in communities}
            if communities and not args.skip_category_check:
                check_categories(repository, communities, categories, args.timeout)
            log("check only: nothing uploaded")
            return 0

        token, source = load_token(args.env_file, repository)
        log(f"token: loaded from {source} ({len(token)} chars, scheme resolved at runtime)")

        publish(args, config, repository, token)
        return 0
    except PublishError as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
