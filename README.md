# phpIPAM to NetBox Migration

```markdown
# phpIPAM → NetBox Migration Tool

A complete Python-based migration toolkit for transferring IPAM data from phpIPAM to NetBox.

## 📋 Overview

This project provides scripts to migrate:
- **Sections** → NetBox Sites
- **VLANs** → NetBox VLANs
- **Subnets/Prefixes** → NetBox Prefixes
- **IP Addresses** → NetBox IP Addresses
- **VRFs** → NetBox VRFs (if available)

Tested with:
- phpIPAM 1.5.x / 1.6.x
- NetBox 4.0+
- Ubuntu 22.04 / 24.04 LTS
- Python 3.10+

---

## 📁 Project Structure

```

phpipam-to-netbox/
├── install-migration-ubuntu.sh     # Setup script (installs Python, venv, dependencies)
├── create\_netbox\_sites.py          # Creates NetBox sites from phpIPAM sections
├── migrate\_phpipam\_to\_netbox.py    # Main migration script
├── section\_mapping.py              # Auto-generated section → site mapping
└── README.md

````

---

## ⚙️ Prerequisites

### phpIPAM Requirements
- API enabled in phpIPAM settings
- API application created with **Read** permissions
- API token generated

### NetBox Requirements
- NetBox 4.0+ installed and accessible
- API token with **Read/Write** permissions
- Empty or prepared NetBox instance recommended

### Migration Server Requirements
- Ubuntu 22.04+ (or compatible Linux)
- Network access to both phpIPAM and NetBox servers
- Python 3.10+ (installed by setup script)

---

## 🚀 Quick Start

### Step 1: Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/phpipam-to-netbox.git
cd phpipam-to-netbox
````

### Step 2: Run the Setup Script

```bash
chmod +x install-migration-ubuntu.sh
./install-migration-ubuntu.sh
```

This will:

*   Install Python 3 and required system packages
*   Create a virtual environment (`./venv`)
*   Install Python dependencies (`pynetbox`, `requests`, `python-slugify`)

### Step 3: Activate the Virtual Environment

```bash
source ./venv/bin/activate
```

Your prompt should change to: `(venv) user@server:~$`

### Step 4: Configure the Scripts

Edit each script and update the **CONFIGURATION** section:

```bash
nano create_netbox_sites.py
```

```python
# ─────────────────────────────────────────────
#          CONFIGURATION
# ─────────────────────────────────────────────
PHPIPAM = {
    'url':   "https://your-phpipam-server.com/api/your_app_id",
    'token': "your_phpipam_api_token",
}

NETBOX = {
    'url':   "https://your-netbox-server.com",
    'token': "your_netbox_api_token",
}

SSL_VERIFY = False  # Set True if using valid SSL certificates
DRY_RUN = True      # Set False to make actual changes
```

Repeat for `migrate_phpipam_to_netbox.py`.

### Step 5: Generate Section Mapping

```bash
curl -s -k -H "token: YOUR_PHPIPAM_TOKEN" \
  "https://your-phpipam-server.com/api/your_app_id/sections/" | \
  jq -r '
    "SECTION_MAPPING = {",
    (.data[] | "    \"\(.name)\": \"\(.name)\","),
    "}"
  ' > section_mapping.py
```

This creates a 1:1 mapping of phpIPAM sections to NetBox sites with the same names.

***

## 📖 Usage

### Execution Order

**Always run scripts in this order:**

| Order | Script                         | Purpose                                               |
| ----- | ------------------------------ | ----------------------------------------------------- |
| 1     | `create_netbox_sites.py`       | Creates sites in NetBox (must exist before migration) |
| 2     | `migrate_phpipam_to_netbox.py` | Migrates VLANs, Prefixes, IP Addresses                |

### Running the Migration

```bash
# Ensure virtual environment is active
source ./venv/bin/activate

# ────────────────────────────────────────────
# STEP 1: Create Sites (Dry Run)
# ────────────────────────────────────────────
python3 create_netbox_sites.py

# Review output, then edit script: DRY_RUN = False
nano create_netbox_sites.py

# Run for real
python3 create_netbox_sites.py

# ────────────────────────────────────────────
# STEP 2: Migrate Data (Dry Run)
# ────────────────────────────────────────────
python3 migrate_phpipam_to_netbox.py

# Review output, then edit script: DRY_RUN = False
nano migrate_phpipam_to_netbox.py

# Run for real
python3 migrate_phpipam_to_netbox.py

# ────────────────────────────────────────────
# STEP 3: Deactivate Virtual Environment
# ────────────────────────────────────────────
deactivate
```

***

## 🔧 Configuration Options

### Script Settings

| Setting          | Description                       | Default |
| ---------------- | --------------------------------- | ------- |
| `DRY_RUN`        | Preview changes without applying  | `True`  |
| `SSL_VERIFY`     | Verify SSL certificates           | `False` |
| `REQUEST_DELAY`  | Delay between API calls (seconds) | `0.05`  |
| `BATCH_SIZE`     | Progress log interval             | `100`   |
| `RETRY_ATTEMPTS` | Retries for failed requests       | `3`     |

### Section Mapping

Edit `section_mapping.py` to customize how phpIPAM sections map to NetBox sites:

```python
SECTION_MAPPING = {
    "Default": "Default",
    "Office Chicago": "Chicago HQ",  # Rename during migration
    "Data Center": "DC1 - Primary",
    "Old Network": None,             # None = import without site assignment
}
```

***

## 🔍 Troubleshooting

### phpIPAM API Returns 404

**Cause:** Apache mod\_rewrite not configured properly.

**Fix:**

```bash
# On phpIPAM server
sudo a2enmod rewrite

# Edit Apache config
sudo nano /etc/apache2/sites-enabled/your-site.conf

# Add inside <VirtualHost>:
<Directory /var/www/html>
    AllowOverride All
    Require all granted
</Directory>

sudo systemctl restart apache2
```

### "Site not found" Warnings

**Cause:** Sites don't exist in NetBox yet.

**Fix:** Run `create_netbox_sites.py` before the migration script.

### Connection Errors / Remote Disconnected

**Cause:** Too many API requests overwhelming NetBox.

**Fix (on NetBox server):**

```bash
# Edit NetBox configuration
sudo nano /opt/netbox/netbox/netbox/configuration.py

# Add:
RATE_LIMITING = {}

# Edit gunicorn config
sudo nano /opt/netbox/gunicorn.py

# Add:
timeout = 300

# Restart
sudo systemctl restart netbox netbox-rq
```

### SSL Certificate Errors

**Option 1:** Set `SSL_VERIFY = False` in scripts (for self-signed certs)

**Option 2:** Add CA certificates to Python:

```bash
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
python3 migrate_phpipam_to_netbox.py
```

### VRFs Not Found (404)

**Cause:** VRFs feature not enabled in phpIPAM.

**Fix:** Already handled - script skips VRFs if not available.

***

## 📊 Migration Estimates

| IP Addresses | Estimated Time |
| ------------ | -------------- |
| 1,000        | \~2 minutes    |
| 10,000       | \~15 minutes   |
| 50,000       | \~1 hour       |
| 100,000      | \~2 hours      |

*Times vary based on network latency and server performance.*

***

## 🛡️ Safety Features

*   **Dry Run Mode:** Preview all changes before applying
*   **Duplicate Detection:** Skips existing objects (safe to re-run)
*   **Error Handling:** Continues migration even if individual items fail
*   **Progress Logging:** Shows real-time progress for large migrations
*   **Retry Logic:** Automatically retries failed API calls

***

## 📝 Useful Commands

### Check phpIPAM Sections

```bash
curl -s -k -H "token: YOUR_TOKEN" \
  "https://phpipam.example.com/api/app_id/sections/" | jq '.data[].name'
```

### Check NetBox Sites

```bash
curl -s -k -H "Authorization: Token YOUR_TOKEN" \
  "https://netbox.example.com/api/dcim/sites/" | jq '.results[].name'
```

### Count IP Addresses in phpIPAM

```bash
curl -s -k -H "token: YOUR_TOKEN" \
  "https://phpipam.example.com/api/app_id/addresses/" | jq '.data | length'
```

### Virtual Environment Commands

```bash
source ./venv/bin/activate   # Activate
deactivate                   # Deactivate
```

***

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

***

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

***

## 🙏 Acknowledgments

*   [phpIPAM](https://phpipam.net/) - Source IPAM system
*   [NetBox](https://netbox.dev/) - Target IPAM system
*   [pynetbox](https://github.com/netbox-community/pynetbox) - NetBox Python API client

````

---

## Quick Copy-Paste Summary

Add this to the top of your README for quick reference:

```markdown
## ⚡ TL;DR

```bash
# Setup
chmod +x install-migration-ubuntu.sh && ./install-migration-ubuntu.sh

# Configure (edit tokens in both scripts)
nano create_netbox_sites.py
nano migrate_phpipam_to_netbox.py

# Run
source ./venv/bin/activate
python3 create_netbox_sites.py      # Create sites first
python3 migrate_phpipam_to_netbox.py # Then migrate data
deactivate
````

```
```
