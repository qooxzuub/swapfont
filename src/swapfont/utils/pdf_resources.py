# src/swapfont/utils/pdf_resources.py
import logging
from typing import Any, Optional, Set

import pikepdf

logger = logging.getLogger(__name__)


def find_resource_recursive(
    pdf: pikepdf.Pdf, resource_type: str, resource_name: str
) -> Optional[Any]:
    """
    Searches for a specific resource (e.g. a Font named '/F1') across all pages
    and their nested XObjects.
    """
    visited_xobjects: Set[int] = set()

    for page in pdf.pages:
        result = _search_container(page, resource_type, resource_name, visited_xobjects)
        if result:
            return result
    return None


def _search_container(
    container: Any, resource_type: str, target_name: str, visited: Set[int]
) -> Optional[Any]:
    """Recursively searches a container (Page or XObject). resource_type is e.g., '/Font'"""
    if "/Resources" not in container:
        return None

    resources = container.Resources
    return (
        _check_immediate_resources(resource_type, resources, target_name)
        or _next_xobject_match(resource_type, resources, target_name, visited)
        or None
    )


def _check_immediate_resources(resource_type, resources, target_name):
    # Check immediate resources
    # resource_type is e.g. "/Font"
    if resource_type in resources:
        target_key = target_name if target_name.startswith("/") else "/" + target_name
        if target_key in resources[resource_type]:
            return resources[resource_type][target_key]
    return None


def _next_xobject_match(resource_type, resources, target_name, visited):
    if "/XObject" in resources:
        for _, xobj in resources["/XObject"].items():
            if not isinstance(xobj, pikepdf.Object) or xobj.objgen in visited:
                continue
            visited.add(xobj.objgen)

            if xobj.get("/Subtype") == "/Form":
                return _search_container(xobj, resource_type, target_name, visited)

    return None
