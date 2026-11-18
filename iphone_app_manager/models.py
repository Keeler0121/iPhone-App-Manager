"""Plain data objects shared between the device layer and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AppInfo:
    """One app on the iPhone (installed, or offloaded with only its Home Screen entry left)."""

    bundle_id: str
    name: str
    version: str
    build: str = ""
    app_type: str = ""
    min_os: str = ""
    device_family: tuple[int, ...] = field(default_factory=tuple)
    is_app_clip: bool = False
    signer: str = ""
    # True only when iOS itself marks the app IsDemotedApp=True (ShowPlaceholders listing).
    offloaded: bool = False

    @property
    def status(self) -> str:
        return "Offloaded" if self.offloaded else "Installed"


@dataclass(frozen=True)
class AppSize:
    """Storage reported by iOS for one app (bytes)."""

    app_bytes: int        # StaticDiskUsage - the app itself ("App Size" in Settings)
    data_bytes: int       # DynamicDiskUsage - the app's own documents & data container

    @property
    def total_bytes(self) -> int:
        return self.app_bytes + self.data_bytes


@dataclass(frozen=True)
class DeviceStorage:
    """Overall storage from lockdown's com.apple.disk_usage domain (bytes)."""

    capacity: int          # TotalDiskCapacity (the advertised size, e.g. 128 GB)
    free_now: int          # AmountDataAvailable (free right now; excludes space iOS could reclaim)
    data_capacity: int = 0
    system_capacity: int = 0

    @property
    def used(self) -> int:
        return self.capacity - self.free_now


@dataclass(frozen=True)
class DeviceInfo:
    """Basic, non-personal details about the connected iPhone."""

    name: str
    ios_version: str
    storage: Optional[DeviceStorage] = None
