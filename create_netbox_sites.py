#!/usr/bin/env python3
"""
Create NetBox sites from phpIPAM sections
Run this BEFORE the migration script
"""

import os
import re
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from pynetbox import api

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
PHPIPAM = {
    'url': "https://your-phpipam-server.com/api/your_app_id",
    'token': "your_phpipam_api_token",
}

NETBOX = {
    'url': "https://your-netbox-server.com",
    'token': "your_netbox_api_token",
}

SSL_VERIFY = False
DRY_RUN = False  # Set to False to actually create sites

# ─────────────────────────────────────────────
# Helper: Create a valid slug
# ─────────────────────────────────────────────
def make_slug(name):
    """Create a valid NetBox slug from a name"""
    # Convert to lowercase
    slug = name.lower()
    # Replace spaces and underscores with hyphens
    slug = slug.replace(" ", "-").replace("_", "-")
    # Remove invalid characters (keep only alphanumeric and hyphens)
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    # Ensure not empty
    if not slug:
        slug = "site"
    # Truncate to 50 chars (NetBox limit)
    return slug[:50]

# ─────────────────────────────────────────────
# Fetch sections from phpIPAM
# ─────────────────────────────────────────────
def get_phpipam_sections():
    headers = {"token": PHPIPAM['token']}
    url = f"{PHPIPAM['url']}/sections/"
    
    r = requests.get(url, headers=headers, verify=SSL_VERIFY, timeout=30)
    r.raise_for_status()
    data = r.json()
    
    if not data.get("success"):
        raise ValueError(f"phpIPAM error: {data.get('message')}")
    
    return data.get("data") or []

# ─────────────────────────────────────────────
# Create sites in NetBox
# ─────────────────────────────────────────────
def create_sites():
    sections = get_phpipam_sections()
    print(f"Found {len(sections)} sections in phpIPAM\n")
    
    nb = api(url=NETBOX['url'], token=NETBOX['token'])
    nb.http_session.verify = SSL_VERIFY
    
    created = 0
    skipped = 0
    errors = 0
    
    # Track slugs to avoid duplicates
    used_slugs = set()
    
    # Get existing sites
    existing_sites = {site.name: site for site in nb.dcim.sites.all()}
    
    for section in sections:
        name = section.get("name") if section else None
        if not name:
            print(f"  SKIP: Empty section name")
            skipped += 1
            continue
        
        name = str(name).strip()
        if not name:
            print(f"  SKIP: Empty section name after strip")
            skipped += 1
            continue
        
        # Check if site already exists
        if name in existing_sites:
            print(f"  SKIP: {name} (already exists)")
            skipped += 1
            continue
        
        # Create unique slug
        base_slug = make_slug(name)
        slug = base_slug
        counter = 1
        while slug in used_slugs:
            slug = f"{base_slug}-{counter}"[:50]
            counter += 1
        used_slugs.add(slug)
        
        # Get description safely
        description = ""
        if section.get("description"):
            description = str(section["description"])[:200]
        
        if DRY_RUN:
            print(f"  [DRY] Would create site: {name} (slug: {slug})")
            created += 1
            continue
        
        try:
            nb.dcim.sites.create(
                name=name[:100],  # NetBox name limit
                slug=slug,
                status="active",
                description=description or "Imported from phpIPAM"
            )
            print(f"  CREATE: {name}")
            created += 1
        except Exception as e:
            print(f"  ERROR: {name} - {e}")
            errors += 1
    
    print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Summary:")
    print(f"  Created: {created}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")

if __name__ == "__main__":
    print("=== Creating NetBox Sites from phpIPAM Sections ===\n")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}\n")
    create_sites()
