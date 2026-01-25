"""
xIRS Update Server

Provides OTA update management for MIRS deployments.

Features:
- Version checking by channel (stable, beta, dev)
- Binary download serving
- Update statistics tracking
- Admin API for release management

Version: 1.0
Date: 2026-01-25
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.7 (P1-04)

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8080
"""

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Depends, Header
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# =============================================================================
# Configuration
# =============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path(os.environ.get('UPDATE_SERVER_DATA', './data'))
RELEASES_DIR = DATA_DIR / 'releases'
DB_PATH = DATA_DIR / 'updates.db'

# Admin API key (set via environment)
ADMIN_API_KEY = os.environ.get('UPDATE_SERVER_ADMIN_KEY', 'dev-admin-key')

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
RELEASES_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Database Setup
# =============================================================================

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema."""
    conn = get_db()
    cursor = conn.cursor()

    # Releases table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'stable',
            platform TEXT NOT NULL DEFAULT 'arm64',
            product TEXT NOT NULL DEFAULT 'mirs-hub',
            release_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            release_notes TEXT,
            download_url TEXT,
            filename TEXT,
            checksum TEXT,
            size_bytes INTEGER,
            breaking_changes BOOLEAN DEFAULT FALSE,
            min_version TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(version, channel, platform, product)
        )
    """)

    # Download statistics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS download_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER,
            client_version TEXT,
            client_ip TEXT,
            user_agent TEXT,
            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (release_id) REFERENCES releases(id)
        )
    """)

    # Update check statistics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS check_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            current_version TEXT,
            channel TEXT,
            platform TEXT,
            client_ip TEXT,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized")


# Initialize on startup
init_db()

# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="xIRS Update Server",
    description="OTA Update Management for MIRS",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Request/Response Models
# =============================================================================

class ReleaseInfo(BaseModel):
    """Release information."""
    version: str
    channel: str = "stable"
    platform: str = "arm64"
    product: str = "mirs-hub"
    release_date: Optional[str] = None
    release_notes: Optional[str] = None
    download_url: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    breaking_changes: bool = False
    min_version: Optional[str] = None


class CreateReleaseRequest(BaseModel):
    """Request to create a new release."""
    version: str
    channel: str = "stable"
    platform: str = "arm64"
    product: str = "mirs-hub"
    release_notes: Optional[str] = None
    breaking_changes: bool = False
    min_version: Optional[str] = None


class UpdateCheckResponse(BaseModel):
    """Response for update check."""
    available: bool
    version: str
    release_date: Optional[str] = None
    release_notes: Optional[str] = None
    download_url: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    breaking_changes: bool = False


# =============================================================================
# Helper Functions
# =============================================================================

def compare_versions(v1: str, v2: str) -> int:
    """Compare version strings. Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2."""
    def normalize(v):
        return [int(x) for x in v.replace('-', '.').split('.')[:3]]

    try:
        parts1 = normalize(v1)
        parts2 = normalize(v2)

        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0
            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1
        return 0
    except Exception:
        return 0


def calculate_checksum(filepath: Path) -> str:
    """Calculate SHA256 checksum."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_admin_key(x_api_key: str = Header(None)):
    """Verify admin API key."""
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# =============================================================================
# Public API Endpoints
# =============================================================================

@app.get("/")
async def root():
    """Server info."""
    return {
        "name": "xIRS Update Server",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/api/v1/updates/{channel}/latest", response_model=UpdateCheckResponse)
async def check_for_updates(
    channel: str,
    current_version: str = Query(..., description="Current installed version"),
    platform: str = Query("arm64", description="Platform architecture"),
    product: str = Query("mirs-hub", description="Product name")
):
    """
    Check for available updates.

    GET /api/v1/updates/stable/latest?current_version=2.4.0&platform=arm64

    Returns the latest version for the specified channel, or 204 if no update available.
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Log the check
        cursor.execute("""
            INSERT INTO check_stats (current_version, channel, platform)
            VALUES (?, ?, ?)
        """, (current_version, channel, platform))
        conn.commit()

        # Get latest release for channel
        cursor.execute("""
            SELECT * FROM releases
            WHERE channel = ? AND platform = ? AND product = ? AND is_active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
        """, (channel, platform, product))

        release = cursor.fetchone()

        if not release:
            return UpdateCheckResponse(
                available=False,
                version=current_version
            )

        latest_version = release['version']
        is_update_available = compare_versions(current_version, latest_version) < 0

        # Check minimum version requirement
        if release['min_version']:
            if compare_versions(current_version, release['min_version']) < 0:
                # Current version too old, need to update through intermediate versions
                pass  # Still show update as available

        return UpdateCheckResponse(
            available=is_update_available,
            version=latest_version,
            release_date=release['release_date'],
            release_notes=release['release_notes'],
            download_url=release['download_url'] or f"/api/v1/downloads/{release['filename']}",
            checksum=release['checksum'],
            size_bytes=release['size_bytes'],
            breaking_changes=bool(release['breaking_changes'])
        )

    finally:
        conn.close()


@app.get("/api/v1/updates/{channel}/all")
async def list_releases(
    channel: str,
    platform: str = Query("arm64"),
    product: str = Query("mirs-hub"),
    limit: int = Query(10, le=50)
):
    """
    List all releases for a channel.

    GET /api/v1/updates/stable/all?limit=10
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT version, release_date, release_notes, breaking_changes
            FROM releases
            WHERE channel = ? AND platform = ? AND product = ? AND is_active = TRUE
            ORDER BY created_at DESC
            LIMIT ?
        """, (channel, platform, product, limit))

        releases = [dict(row) for row in cursor.fetchall()]
        return {"releases": releases, "count": len(releases)}

    finally:
        conn.close()


@app.get("/api/v1/downloads/{filename}")
async def download_release(filename: str):
    """
    Download a release binary.

    GET /api/v1/downloads/mirs-hub-2.5.0-arm64
    """
    filepath = RELEASES_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Release not found")

    # Log download
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM releases WHERE filename = ?
    """, (filename,))
    release = cursor.fetchone()

    if release:
        cursor.execute("""
            INSERT INTO download_stats (release_id)
            VALUES (?)
        """, (release['id'],))
        conn.commit()

    conn.close()

    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        filename=filename
    )


# =============================================================================
# Admin API Endpoints
# =============================================================================

@app.post("/api/v1/admin/releases", dependencies=[Depends(verify_admin_key)])
async def create_release(request: CreateReleaseRequest):
    """
    Create a new release entry (admin only).

    POST /api/v1/admin/releases
    Headers: X-API-Key: <admin-key>
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO releases (version, channel, platform, product, release_notes, breaking_changes, min_version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            request.version,
            request.channel,
            request.platform,
            request.product,
            request.release_notes,
            request.breaking_changes,
            request.min_version
        ))
        conn.commit()

        return {
            "success": True,
            "release_id": cursor.lastrowid,
            "message": f"Release {request.version} created"
        }

    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Release already exists")
    finally:
        conn.close()


@app.post("/api/v1/admin/releases/{version}/upload", dependencies=[Depends(verify_admin_key)])
async def upload_release_binary(
    version: str,
    file: UploadFile = File(...),
    channel: str = Query("stable"),
    platform: str = Query("arm64"),
    product: str = Query("mirs-hub")
):
    """
    Upload a release binary (admin only).

    POST /api/v1/admin/releases/2.5.0/upload
    Headers: X-API-Key: <admin-key>
    Body: multipart/form-data with file
    """
    # Generate filename
    filename = f"{product}-{version}-{platform}"
    filepath = RELEASES_DIR / filename

    # Save file
    content = await file.read()
    with open(filepath, 'wb') as f:
        f.write(content)

    # Calculate checksum
    checksum = calculate_checksum(filepath)
    size_bytes = filepath.stat().st_size

    # Update database
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE releases
            SET filename = ?, checksum = ?, size_bytes = ?, download_url = ?
            WHERE version = ? AND channel = ? AND platform = ? AND product = ?
        """, (
            filename,
            checksum,
            size_bytes,
            f"/api/v1/downloads/{filename}",
            version,
            channel,
            platform,
            product
        ))

        if cursor.rowcount == 0:
            # Create release entry if not exists
            cursor.execute("""
                INSERT INTO releases (version, channel, platform, product, filename, checksum, size_bytes, download_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version, channel, platform, product,
                filename, checksum, size_bytes, f"/api/v1/downloads/{filename}"
            ))

        conn.commit()

        return {
            "success": True,
            "filename": filename,
            "checksum": checksum,
            "size_bytes": size_bytes
        }

    finally:
        conn.close()


@app.get("/api/v1/admin/stats", dependencies=[Depends(verify_admin_key)])
async def get_statistics():
    """
    Get update statistics (admin only).

    GET /api/v1/admin/stats
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Total releases
        cursor.execute("SELECT COUNT(*) as count FROM releases WHERE is_active = TRUE")
        total_releases = cursor.fetchone()['count']

        # Total downloads
        cursor.execute("SELECT COUNT(*) as count FROM download_stats")
        total_downloads = cursor.fetchone()['count']

        # Total checks
        cursor.execute("SELECT COUNT(*) as count FROM check_stats")
        total_checks = cursor.fetchone()['count']

        # Downloads by version
        cursor.execute("""
            SELECT r.version, COUNT(d.id) as downloads
            FROM releases r
            LEFT JOIN download_stats d ON r.id = d.release_id
            GROUP BY r.id
            ORDER BY downloads DESC
            LIMIT 10
        """)
        downloads_by_version = [dict(row) for row in cursor.fetchall()]

        # Recent checks by version
        cursor.execute("""
            SELECT current_version, COUNT(*) as count
            FROM check_stats
            WHERE checked_at > datetime('now', '-7 days')
            GROUP BY current_version
            ORDER BY count DESC
            LIMIT 10
        """)
        version_distribution = [dict(row) for row in cursor.fetchall()]

        return {
            "total_releases": total_releases,
            "total_downloads": total_downloads,
            "total_checks": total_checks,
            "downloads_by_version": downloads_by_version,
            "version_distribution": version_distribution
        }

    finally:
        conn.close()


@app.delete("/api/v1/admin/releases/{version}", dependencies=[Depends(verify_admin_key)])
async def deactivate_release(
    version: str,
    channel: str = Query("stable"),
    platform: str = Query("arm64"),
    product: str = Query("mirs-hub")
):
    """
    Deactivate a release (admin only).

    DELETE /api/v1/admin/releases/2.5.0?channel=stable
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE releases
            SET is_active = FALSE
            WHERE version = ? AND channel = ? AND platform = ? AND product = ?
        """, (version, channel, platform, product))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Release not found")

        return {"success": True, "message": f"Release {version} deactivated"}

    finally:
        conn.close()


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# =============================================================================
# Startup
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("xIRS Update Server starting...")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Releases directory: {RELEASES_DIR}")

    # Create sample release if none exist
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM releases")
    if cursor.fetchone()['count'] == 0:
        logger.info("Creating sample release...")
        cursor.execute("""
            INSERT INTO releases (version, channel, platform, product, release_notes)
            VALUES ('2.4.0', 'stable', 'arm64', 'mirs-hub', 'Initial release')
        """)
        conn.commit()
    conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
