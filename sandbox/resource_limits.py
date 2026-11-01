from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ResourceLimits:
    cpu_quota: float = 1.0
    memory_mb: int = 512
    timeout_seconds: int = 60
    pids_limit: int = 256
    read_only: bool = True

    def docker_args(self) -> List[str]:
        return [
            "--cpus", str(self.cpu_quota),
            "--memory", f"{self.memory_mb}m",
            "--memory-swap", f"{self.memory_mb}m",
            "--pids-limit", str(self.pids_limit),
            "--read-only" if self.read_only else "--read-only=false",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=128m",
            "--network", "none",
        ]
