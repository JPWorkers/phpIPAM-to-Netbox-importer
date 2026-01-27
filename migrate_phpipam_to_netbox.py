#!/usr/bin/env python3
"""
phpIPAM → NetBox Migration Script
Migrates Sections, VRFs, VLANs, Prefixes, and IP Addresses
"""

import os
import re
import sys
import time
import logging
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ipaddress import ip_network
from typing import Optional, Tuple, Dict, Any

from pynetbox import api
from pynetbox.core.query import RequestError

# Import your generated section mapping
from section_mapping import SECTION_MAPPING

# ────────────────────────────────────────────────
#          CONFIGURATION
# ────────────────────────────────────────────────
PHPIPAM = {
    'url':      "https://ipam.metrarr.com/api/migration",
    'token':    os.getenv("PHPIPAM_TOKEN") or "your_phpipam_token_here",
}

NETBOX = {
    'url':      "https://netbox.yourdomain.com",
    'token':    os.getenv("NETBOX_TOKEN") or "your_netbox_token_here",
}

DRY_RUN = True          # Set True to preview changes without applying
SSL_VERIFY = False       # Set True if using valid SSL certificates

SCOPE_TYPE = "dcim.site"

# Rate limiting settings
REQUEST_DELAY = 0.05     # Seconds between API calls
BATCH_SIZE = 100         # Progress log interval
RETRY_ATTEMPTS = 3       # Retries for failed requests
RETRY_DELAY = 5          # Seconds to wait after connection error

# ────────────────────────────────────────────────
# Logging setup
# ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ipam-migrator")

# ────────────────────────────────────────────────
# Global caches (populated at startup)
# ────────────────────────────────────────────────
SECTIONS_CACHE: Dict[str, str] = {}   # {section_id: section_name}
VRFS_CACHE: Dict[str, str] = {}       # {vrf_id: vrf_name}
VLANS_CACHE: Dict[str, int] = {}      # {phpipam_vlan_id: netbox_vlan_id}


# ────────────────────────────────────────────────
# Helper Functions
# ────────────────────────────────────────────────
def safe_str(value, default: str = "") -> str:
    """Safely convert value to string, return default if None"""
    if value is None:
        return default
    return str(value)


def make_slug(name: str) -> str:
    """Create a valid NetBox slug from a name"""
    if not name:
        return "default"
    slug = (name or "").lower()
    slug = slug.replace(" ", "-").replace("_", "-")
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug[:50] if slug else "default"


def phpipam_get(endpoint: str, required: bool = True) -> list:
    """Simple GET wrapper for phpIPAM API"""
    headers = {"token": PHPIPAM['token']}
    url = f"{PHPIPAM['url']}/{endpoint.lstrip('/')}"
    
    try:
        r = requests.get(url, headers=headers, verify=SSL_VERIFY, timeout=30)
        
        # Handle 404 gracefully for optional endpoints
        if r.status_code == 404:
            if required:
                r.raise_for_status()
            else:
                logger.info(f"Endpoint not found (skipping): {endpoint}")
                return []
        
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise ValueError(f"phpIPAM error: {data.get('message', 'Unknown error')}")
        result = data.get("data")
        return result if isinstance(result, list) else []
    except requests.exceptions.RequestException as e:
        if not required:
            return []
        logger.error(f"phpIPAM GET /{endpoint} failed: {e}")
        raise


def build_caches():
    """Pre-fetch sections and VRFs for lookups"""
    global SECTIONS_CACHE, VRFS_CACHE
    
    logger.info("Building lookup caches...")
    
    # Sections cache
    try:
        sections = phpipam_get("sections/", required=False)
        SECTIONS_CACHE = {str(s["id"]): s["name"] for s in sections if s.get("id")}
        logger.info(f"Cached {len(SECTIONS_CACHE)} sections")
    except Exception as e:
        logger.warning(f"Failed to cache sections: {e}")
        SECTIONS_CACHE = {}
    
    # VRFs cache (optional - may not exist)
    try:
        vrfs = phpipam_get("vrfs/", required=False)
        if vrfs:
            VRFS_CACHE = {str(v["vrfId"]): v["name"] for v in vrfs if v.get("vrfId")}
            logger.info(f"Cached {len(VRFS_CACHE)} VRFs")
        else:
            VRFS_CACHE = {}
            logger.info("No VRFs found in phpIPAM")
    except Exception as e:
        logger.warning(f"VRFs not available (this is OK if you don't use VRFs): {e}")
        VRFS_CACHE = {}


def get_section_name(section_id: Any) -> Optional[str]:
    """Resolve section ID to name using cache"""
    if not section_id:
        return None
    return SECTIONS_CACHE.get(str(section_id))


def get_vrf_name(vrf_id: Any) -> Optional[str]:
    """Resolve VRF ID to name using cache"""
    if not vrf_id:
        return None
    return VRFS_CACHE.get(str(vrf_id))


def get_or_create_vrf(nb, name: str, rd: str = "") -> Optional[int]:
    if not name:
        return None
    
    try:
        vrfs = list(nb.ipam.vrfs.filter(name=name))
        if vrfs:
            return vrfs[0].id
        
        if DRY_RUN:
            logger.info(f"[DRY] Would create VRF: {name}")
            return None
        
        vrf = nb.ipam.vrfs.create(name=name[:100], rd=rd or None)
        logger.info(f"Created VRF: {name}")
        return vrf.id
    except RequestError as e:
        logger.error(f"VRF '{name}' failed: {e}")
        return None


def get_scope_for_section(nb, section_name: str) -> Tuple[Optional[str], Optional[int]]:
    if not section_name:
        return None, None
    
    # If SECTION_MAPPING exists, use it; otherwise use section name directly
    if SECTION_MAPPING:
        site_name = SECTION_MAPPING.get(section_name)
    else:
        site_name = section_name
    
    if not site_name:
        return None, None
    
    try:
        sites = list(nb.dcim.sites.filter(name=site_name))
        if not sites:
            logger.warning(f"Site not found: {site_name}")
            return None, None
        return SCOPE_TYPE, sites[0].id
    except Exception as e:
        logger.error(f"Scope lookup failed: {e}")
        return None, None


# ────────────────────────────────────────────────
# Migration Functions
# ────────────────────────────────────────────────
def migrate_vrfs(nb):
    logger.info("Migrating VRFs...")
    try:
        vrfs = phpipam_get("vrfs/", required=False)
    except Exception as e:
        logger.warning(f"No VRFs found or VRF feature disabled in phpIPAM: {e}")
        return
    
    if not vrfs:
        logger.info("No VRFs to migrate")
        return
    
    for v in vrfs:
        name = v.get("name")
        if name:
            get_or_create_vrf(nb, name, safe_str(v.get("rd")))


def migrate_vlan_groups(nb):
    logger.info("Migrating VLAN Groups (L2 Domains)...")
    
    try:
        domains = phpipam_get("l2domains/", required=False)
    except Exception as e:
        logger.warning(f"L2 Domains not available: {e}")
        domains = []
    
    if not domains:
        logger.info("No VLAN Groups to migrate")
        return
    
    for d in domains:
        name = (d.get("name") or "").strip()
        if not name:
            continue
        
        existing = list(nb.ipam.vlan_groups.filter(name=name))
        if existing:
            logger.debug(f"VLAN Group exists: {name}")
            continue
        
        if DRY_RUN:
            logger.info(f"[DRY] Would create VLAN Group: {name}")
            continue
        
        try:
            nb.ipam.vlan_groups.create(
                name=name[:100],
                slug=make_slug(name),
                description=(d.get("description") or "")[:200]
            )
            logger.info(f"Created VLAN Group: {name}")
        except RequestError as e:
            logger.error(f"VLAN Group '{name}' failed: {e}")


def migrate_vlans(nb):
    global VLANS_CACHE
    logger.info("Migrating VLANs...")
    
    try:
        vlans = phpipam_get("vlans/", required=False)
    except Exception as e:
        logger.warning(f"VLANs not available: {e}")
        return
    
    if not vlans:
        logger.info("No VLANs to migrate")
        return
    
    try:
        domains_list = phpipam_get("l2domains/", required=False)
        domains = {str(d["id"]): d["name"] for d in domains_list if d.get("id")}
    except Exception:
        domains = {}
    
    for v in vlans:
        # Get VLAN number safely
        vid_raw = v.get("number") or v.get("vlanId") or v.get("id")
        if not vid_raw:
            logger.warning(f"Skipping VLAN with no ID: {v}")
            continue
        
        vid = int(vid_raw)
        name = (v.get("name") or f"vlan-{vid}").strip()
        phpipam_id = str(v.get("id", vid))
        
        group_id = None
        domain_id = str(v.get("domainId") or "")
        if domain_id and domain_id in domains:
            group_name = domains[domain_id]
            groups = list(nb.ipam.vlan_groups.filter(name=group_name))
            if groups:
                group_id = groups[0].id
        
        # Check existing
        existing = list(nb.ipam.vlans.filter(vid=vid, group_id=group_id))
        if existing:
            logger.debug(f"VLAN exists: {vid} ({name})")
            VLANS_CACHE[phpipam_id] = existing[0].id
            continue
        
        payload = {
            "vid": vid,
            "name": name[:64],
            "status": "active",
            "description": (v.get("description") or "")[:200],
        }
        if group_id:
            payload["group"] = group_id
        
        if DRY_RUN:
            logger.info(f"[DRY] Would create VLAN {vid} - {name}")
            continue
        
        try:
            created = nb.ipam.vlans.create(**payload)
            VLANS_CACHE[phpipam_id] = created.id
            logger.info(f"Created VLAN {vid} - {name}")
        except RequestError as e:
            logger.error(f"VLAN {vid} failed: {e}")


def migrate_prefixes(nb):
    logger.info("Migrating Prefixes (Subnets)...")
    
    try:
        subnets = phpipam_get("subnets/", required=False)
    except Exception as e:
        logger.warning(f"Subnets not available: {e}")
        return
    
    if not subnets:
        logger.info("No Prefixes to migrate")
        return
    
    # Sort by prefix length (broad → narrow)
    def get_prefix_len(s):
        try:
            return ip_network(f"{s['subnet']}/{s['mask']}", strict=False).prefixlen
        except:
            return 999
    
    subnets.sort(key=get_prefix_len)
    logger.info(f"Sorted {len(subnets)} subnets by prefix length")
    
    for s in subnets:
        subnet = s.get("subnet")
        mask = s.get("mask")
        if not subnet or not mask:
            continue
        
        prefix = f"{subnet}/{mask}"
        desc = (s.get("description") or "")[:200].strip()
        
        # Resolve section name
        section_id = s.get("sectionId")
        section_name = get_section_name(section_id)
        
        # Resolve VRF
        vrf_id_phpipam = s.get("vrfId")
        vrf_name = get_vrf_name(vrf_id_phpipam)
        vrf_id = get_or_create_vrf(nb, vrf_name) if vrf_name else None
        
        # Section → Scope mapping
        scope_type, scope_id = get_scope_for_section(nb, section_name)
        
        payload = {
            "prefix": prefix,
            "status": "active",
            "description": desc,
            "is_pool": s.get("isPool") == "1" or s.get("isFull") == "1",
            "mark_utilized": s.get("isFull") == "1",
        }
        
        if vrf_id:
            payload["vrf"] = vrf_id
        
        if scope_type and scope_id:
            payload["scope_type"] = scope_type
            payload["scope_id"] = scope_id
        
        # VLAN association
        vlan_id_phpipam = str(s.get("vlanId") or "")
        if vlan_id_phpipam and vlan_id_phpipam in VLANS_CACHE:
            payload["vlan"] = VLANS_CACHE[vlan_id_phpipam]
        
        try:
            existing = list(nb.ipam.prefixes.filter(prefix=prefix, vrf_id=vrf_id))
            if existing:
                logger.debug(f"Prefix exists: {prefix}")
                if not DRY_RUN:
                    existing[0].update(payload)
            elif DRY_RUN:
                logger.info(f"[DRY] Would create prefix: {prefix} (section: {section_name})")
            else:
                nb.ipam.prefixes.create(**payload)
                logger.info(f"Created prefix: {prefix}")
                
        except RequestError as e:
            logger.error(f"Prefix {prefix} failed: {e}")


def migrate_addresses(nb):
    """Migrate individual IP addresses with rate limiting and retries"""
    logger.info("Migrating IP Addresses...")
    
    try:
        addresses = phpipam_get("addresses/", required=False)
    except Exception as e:
        logger.warning(f"IP addresses not available: {e}")
        return
    
    if not addresses:
        logger.info("No IP addresses found, skipping...")
        return
    
    total = len(addresses)
    logger.info(f"Processing {total} IP addresses (this may take a while)...")
    
    created = 0
    skipped = 0
    errors = 0
    
    for i, addr in enumerate(addresses):
        # Progress update
        if i > 0 and i % BATCH_SIZE == 0:
            logger.info(f"  Progress: {i}/{total} ({(i/total)*100:.1f}%) - Created: {created}, Skipped: {skipped}, Errors: {errors}")
        
        ip = addr.get("ip")
        if not ip:
            continue
        
        mask = "32" if ":" not in ip else "128"
        address = f"{ip}/{mask}"
        
        vrf_id_phpipam = addr.get("vrfId")
        vrf_name = get_vrf_name(vrf_id_phpipam)
        vrf_id = get_or_create_vrf(nb, vrf_name) if vrf_name else None
        
        # Build payload with safe string handling
        description = (addr.get("description") or addr.get("hostname") or "")[:200]
        dns_name = (addr.get("hostname") or "")[:255]
        
        payload = {
            "address": address,
            "status": "active",
            "description": description,
            "dns_name": dns_name,
        }
        if vrf_id:
            payload["vrf"] = vrf_id
        
        # Retry logic
        for attempt in range(RETRY_ATTEMPTS):
            try:
                time.sleep(REQUEST_DELAY)
                
                existing = list(nb.ipam.ip_addresses.filter(address=ip, vrf_id=vrf_id))
                if existing:
                    skipped += 1
                    break
                
                if DRY_RUN:
                    created += 1
                    break
                
                nb.ipam.ip_addresses.create(**payload)
                created += 1
                break
                
            except Exception as e:
                if attempt < RETRY_ATTEMPTS - 1:
                    logger.warning(f"Retry {attempt + 1}/{RETRY_ATTEMPTS} for {address}: {e}")
                    time.sleep(RETRY_DELAY)
                else:
                    errors += 1
                    if errors <= 20:
                        logger.error(f"Failed after {RETRY_ATTEMPTS} attempts: {address} - {e}")
    
    logger.info(f"IP Addresses Complete: {created} created, {skipped} skipped, {errors} errors")


# ────────────────────────────────────────────────
# Main Entry Point
# ────────────────────────────────────────────────
def main():
    nb = api(url=NETBOX['url'], token=NETBOX['token'])
    nb.http_session.verify = SSL_VERIFY
    
    try:
        logger.info("=== Starting phpIPAM → NetBox migration ===")
        logger.info(f"Mode: {'DRY-RUN' if DRY_RUN else 'LIVE MIGRATION'}")
        
        # Build caches first
        build_caches()
        
        # Run migrations in order
        migrate_vrfs(nb)
        migrate_vlan_groups(nb)
        migrate_vlans(nb)
        migrate_prefixes(nb)
        migrate_addresses(nb)
        
        logger.info("=== Migration finished ===")
        
    except KeyboardInterrupt:
        logger.warning("Migration interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
