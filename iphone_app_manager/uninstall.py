"""Sequential bulk uninstall and post-uninstall verification.

Runs on a worker thread, one app at a time (never in parallel). Stops issuing commands
as soon as the iPhone becomes unavailable (disconnected, locked, not trusted, timed out);
the remaining apps are reported as "not attempted". Nothing is retried automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence

from .device import UninstallFailure, removal_block_reason
from .models import AppInfo


class Outcome(Enum):
    REMOVED = "removed"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"     # reported as removed, but it could not be confirmed


@dataclass(frozen=True)
class UninstallResult:
    app: AppInfo
    outcome: Outcome
    message: str = ""


class Uninstaller(Protocol):
    def uninstall_app(self, bundle_id: str) -> None: ...


# progress(event, index, total, app, result) - event is "start" or "done"
ProgressCallback = Callable[[str, int, int, AppInfo, Optional[UninstallResult]], None]


def run_uninstall_batch(service: Uninstaller, apps: Sequence[AppInfo],
                        progress: ProgressCallback) -> list[UninstallResult]:
    results: list[UninstallResult] = []
    total = len(apps)
    stop_reason: Optional[str] = None
    for index, app in enumerate(apps):
        if stop_reason is not None:
            result = UninstallResult(app, Outcome.NOT_ATTEMPTED, stop_reason)
        elif (reason := removal_block_reason(app)) is not None:
            result = UninstallResult(app, Outcome.BLOCKED, reason)
        else:
            progress("start", index, total, app, None)
            try:
                service.uninstall_app(app.bundle_id)
                result = UninstallResult(app, Outcome.REMOVED)
            except UninstallFailure as failure:
                result = UninstallResult(app, Outcome.FAILED, failure.message)
                if failure.fatal:
                    stop_reason = f"Not attempted — {failure.message}"
            except Exception as exc:  # unexpected: report, never count as success
                result = UninstallResult(app, Outcome.FAILED, f"Unexpected error: {exc}")
        results.append(result)
        progress("done", index, total, app, result)
    return results


def verify_results(results: Sequence[UninstallResult], present_ids: set[str],
                   offloaded_listing_ok: bool = True) -> list[UninstallResult]:
    """Cross-check reported outcomes against freshly reloaded data.

    ``present_ids`` must contain every app still on the iPhone: installed apps, offloaded apps
    (iOS's ShowPlaceholders listing) and Home Screen placeholders. An offloaded app can only be
    confirmed as removed when the offloaded-app listing itself was read successfully.
    """
    verified = []
    for r in results:
        still_there = r.app.bundle_id in present_ids
        unconfirmable = r.app.offloaded and not offloaded_listing_ok
        if r.outcome is Outcome.REMOVED and still_there:
            r = UninstallResult(r.app, Outcome.FAILED, "Still on the iPhone after uninstalling")
        elif r.outcome is Outcome.REMOVED and unconfirmable:
            r = UninstallResult(r.app, Outcome.UNVERIFIED,
                                "Removal reported, but the offloaded-app list couldn't be read to confirm it")
        elif r.outcome is Outcome.FAILED and not still_there and not unconfirmable:
            r = UninstallResult(r.app, Outcome.REMOVED,
                                "Removed (confirmed by the refreshed app list, although an error was reported)")
        verified.append(r)
    return verified


def count(results: Sequence[UninstallResult], outcome: Outcome) -> int:
    return sum(1 for r in results if r.outcome is outcome)
