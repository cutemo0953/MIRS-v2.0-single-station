"""
Hybrid Logical Clock (HLC) Implementation for MIRS

HLC combines physical time with a logical counter to provide:
- Causal ordering of events across distributed nodes
- Bounded clock skew tolerance
- Monotonically increasing timestamps

Format: "{physical_ms}.{logical_counter}.{node_id}"
Example: "1737856800000.5.BORP-DNO-01"

Reference: Logical Physical Clocks (Kulkarni et al., 2014)
Version: 1.0
Date: 2026-01-25
"""

import time
import threading
from typing import Tuple, Optional


def parse_hlc(hlc_str: str) -> Tuple[int, int, str]:
    """
    Parse HLC string into components.

    Args:
        hlc_str: HLC string in format "physical.logical.node_id"

    Returns:
        Tuple of (physical_time_ms, logical_counter, node_id)
    """
    parts = hlc_str.split(".", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid HLC format: {hlc_str}")
    return int(parts[0]), int(parts[1]), parts[2]


def format_hlc(physical: int, logical: int, node_id: str) -> str:
    """Format HLC components into string."""
    return f"{physical}.{logical}.{node_id}"


class HybridLogicalClock:
    """
    Thread-safe Hybrid Logical Clock implementation.

    Usage:
        hlc = HybridLogicalClock("BORP-DNO-01")
        ts = hlc.now()  # Generate timestamp for local event
        ts = hlc.receive(remote_ts)  # Update on receiving remote event
    """

    def __init__(self, node_id: str):
        """
        Initialize HLC with node identifier.

        Args:
            node_id: Unique identifier for this node (e.g., station_id)
        """
        self.node_id = node_id
        self._physical = 0
        self._logical = 0
        self._lock = threading.Lock()

    @property
    def physical(self) -> int:
        """Current physical time component."""
        return self._physical

    @property
    def logical(self) -> int:
        """Current logical counter."""
        return self._logical

    def _wall_time_ms(self) -> int:
        """Get current wall-clock time in milliseconds."""
        return int(time.time() * 1000)

    def now(self) -> str:
        """
        Generate HLC timestamp for a local event.

        This should be called when creating a new event locally.
        Guarantees monotonically increasing timestamps.

        Returns:
            HLC timestamp string
        """
        with self._lock:
            wall = self._wall_time_ms()

            if wall > self._physical:
                # Wall clock has advanced - reset logical counter
                self._physical = wall
                self._logical = 0
            else:
                # Wall clock hasn't advanced - increment logical
                self._logical += 1

            return format_hlc(self._physical, self._logical, self.node_id)

    def receive(self, remote_hlc: str) -> str:
        """
        Update clock upon receiving a remote event.

        This should be called when processing an event from another node.
        Ensures the local clock is at least as advanced as the remote clock.

        Args:
            remote_hlc: HLC timestamp from remote event

        Returns:
            New HLC timestamp that happened-after the remote event
        """
        r_phys, r_log, _ = parse_hlc(remote_hlc)

        with self._lock:
            wall = self._wall_time_ms()

            if wall > max(self._physical, r_phys):
                # Wall clock is most recent - use it
                self._physical = wall
                self._logical = 0
            elif self._physical == r_phys:
                # Same physical time - increment logical
                self._logical = max(self._logical, r_log) + 1
            elif r_phys > self._physical:
                # Remote is ahead - catch up
                self._physical = r_phys
                self._logical = r_log + 1
            else:
                # Local is ahead - just increment
                self._logical += 1

            return format_hlc(self._physical, self._logical, self.node_id)

    def update(self, remote_hlc: Optional[str] = None) -> str:
        """
        Convenience method that calls now() or receive() as appropriate.

        Args:
            remote_hlc: Optional remote HLC timestamp

        Returns:
            New HLC timestamp
        """
        if remote_hlc:
            return self.receive(remote_hlc)
        return self.now()

    def current(self) -> str:
        """
        Get current HLC value without advancing the clock.

        Returns:
            Current HLC timestamp (does not increment)
        """
        with self._lock:
            return format_hlc(self._physical, self._logical, self.node_id)

    @staticmethod
    def compare(hlc1: str, hlc2: str) -> int:
        """
        Compare two HLC timestamps.

        Args:
            hlc1: First HLC timestamp
            hlc2: Second HLC timestamp

        Returns:
            -1 if hlc1 < hlc2
             0 if hlc1 == hlc2
             1 if hlc1 > hlc2
        """
        p1, l1, n1 = parse_hlc(hlc1)
        p2, l2, n2 = parse_hlc(hlc2)

        # Compare physical first
        if p1 != p2:
            return -1 if p1 < p2 else 1

        # Then logical
        if l1 != l2:
            return -1 if l1 < l2 else 1

        # Same HLC value - compare node_id for deterministic ordering
        if n1 != n2:
            return -1 if n1 < n2 else 1

        return 0

    @staticmethod
    def is_concurrent(hlc1: str, hlc2: str) -> bool:
        """
        Check if two events are concurrent (neither happened-before the other).

        In HLC, events are concurrent if they have the same physical time
        but different logical counters from different nodes.

        Args:
            hlc1: First HLC timestamp
            hlc2: Second HLC timestamp

        Returns:
            True if events are potentially concurrent
        """
        p1, l1, n1 = parse_hlc(hlc1)
        p2, l2, n2 = parse_hlc(hlc2)

        # Same physical time, different nodes = potentially concurrent
        if p1 == p2 and n1 != n2:
            return True

        return False

    @staticmethod
    def happened_before(hlc1: str, hlc2: str) -> bool:
        """
        Check if hlc1 happened-before hlc2.

        Args:
            hlc1: First HLC timestamp
            hlc2: Second HLC timestamp

        Returns:
            True if hlc1 definitely happened before hlc2
        """
        return HybridLogicalClock.compare(hlc1, hlc2) < 0


# Global HLC instance (initialized on first use)
_global_hlc: Optional[HybridLogicalClock] = None
_global_lock = threading.Lock()


def get_hlc(node_id: Optional[str] = None) -> HybridLogicalClock:
    """
    Get or create the global HLC instance.

    Args:
        node_id: Node identifier (required on first call)

    Returns:
        Global HybridLogicalClock instance
    """
    global _global_hlc

    with _global_lock:
        if _global_hlc is None:
            if node_id is None:
                raise ValueError("node_id required for first HLC initialization")
            _global_hlc = HybridLogicalClock(node_id)
        return _global_hlc


def hlc_now(node_id: Optional[str] = None) -> str:
    """
    Convenience function to get current HLC timestamp.

    Args:
        node_id: Node identifier (required on first call)

    Returns:
        HLC timestamp string
    """
    return get_hlc(node_id).now()


def hlc_receive(remote_hlc: str, node_id: Optional[str] = None) -> str:
    """
    Convenience function to update HLC on receiving remote event.

    Args:
        remote_hlc: Remote HLC timestamp
        node_id: Node identifier (required on first call)

    Returns:
        New HLC timestamp
    """
    return get_hlc(node_id).receive(remote_hlc)
