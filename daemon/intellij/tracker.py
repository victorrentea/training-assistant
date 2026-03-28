"""IntelliJ project tracker — detect active project and branch via osascript + recentProjects.xml."""
import glob
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from daemon import log


def _get_intellij_window_title(timeout: float = 2.0) -> str | None:
    """Use osascript to get the title of the front IntelliJ window."""
    script = 'tell application "System Events" to tell process "idea" to get title of front window'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _find_recent_projects_xml() -> Path | None:
    """Find the most recent IntelliJ recentProjects.xml."""
    pattern = os.path.expanduser(
        "~/Library/Application Support/JetBrains/IntelliJIdea*/options/recentProjects.xml"
    )
    candidates = sorted(glob.glob(pattern), reverse=True)
    for path in candidates:
        p = Path(path)
        if p.exists():
            return p
    return None


def _lookup_project_path(project_name: str, xml_path: Path) -> str | None:
    """Look up project path in recentProjects.xml by project name (case-insensitive folder name match).
    Returns the path with highest activationTimestamp."""
    try:
        tree = ET.parse(xml_path)
        best_ts = -1
        best_path = None
        for entry in tree.findall(".//entry"):
            key = entry.get("key", "")
            folder_name = Path(key.replace("$USER_HOME$", str(Path.home()))).name
            if folder_name.lower() != project_name.lower():
                continue
            meta = entry.find(".//RecentProjectMetaInfo")
            if meta is None:
                continue
            ts_elem = meta.find('option[@name="activationTimestamp"]')
            ts = int(ts_elem.get("value", 0)) if ts_elem is not None else 0
            if ts > best_ts:
                best_ts = ts
                best_path = key.replace("$USER_HOME$", str(Path.home()))
        return best_path
    except Exception:
        return None


def probe_intellij_state(timeout: float = 2.0) -> dict | None:
    """Return {project_name, path, branch} for the active IntelliJ project, or None."""
    title = _get_intellij_window_title(timeout)
    if not title:
        return None

    # Extract project name: "kafka – WordsTopology.java [kafka-streams]" → "kafka"
    project_name = title.split(" – ")[0].split("[")[0].strip()
    if not project_name:
        return None

    xml_path = _find_recent_projects_xml()
    if not xml_path:
        return None

    project_path = _lookup_project_path(project_name, xml_path)
    if not project_path:
        return None

    # Get current branch
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
        branch = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        branch = ""

    return {
        "project": project_name,
        "path": project_path,
        "branch": branch or "unknown",
    }
