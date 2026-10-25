<div align="center">

# ⚡ Odoo SCADA PLC Connector

### SCADA & Industrial IoT Integration Platform for **Odoo Community Edition**

![Odoo](https://img.shields.io/badge/Odoo-CE-875A7B?style=for-the-badge&logo=odoo&logoColor=white)
![License](https://img.shields.io/badge/license-LGPL--3-6B8E23?style=for-the-badge)
![IEC 62443](https://img.shields.io/badge/security-IEC%2062443%20Ready-E11D48?style=for-the-badge)

**Connect real factory machinery to Odoo — no code required.**

📖 **[Full Documentation (complete README)](scada_plc_connector/README.md)** → features, architecture, REST API, quick start, Driver SDK

</div>

---

## 📦 Repository Contents

| Folder | Description |
|--------|-------------|
| [`scada_plc_connector/`](scada_plc_connector/) | Odoo CE module — SCADA/PLC integration platform (full application, LGPL-3) |

## ⚡ At a Glance

- **Protocols**: Simulator & Modbus TCP (active) · OPC UA, Siemens S7, MQTT/Sparkplug B (phase 2)
- **Data flow**: `PLC → Edge Gateway → Odoo REST API → Historian + Rule Engine → MRP / Maintenance`
- **Features**: gateway management & SHA-256 API Keys, 8 data types with tag transformation, rule engine (hysteresis/debounce/minimum duration), alarm lifecycle, IEC 62443-style safe PLC writes with append-only audit, historian + aggregation, 4-level RBAC, built-in simulator with no physical PLC required.

## 🚀 Quick Install

```bash
git clone git@github.com:azazil-dev/odoo-scada-plc-connector.git
# place scada_plc_connector/ into your addons path, then install from the Odoo UI (Apps → SCADA PLC Connector)
```

## 🔗 Link for the Odoo Apps Store

```
ssh://git@github.com:azazil-dev/odoo-scada-plc-connector
```

## 📜 License

LGPL-3 · Author: **Arif N Ramadhan** · [NIITS](https://www.niits.id)

<div align="center">

[GitHub](https://github.com/azazil-dev/odoo-scada-plc-connector) · [GitLab](https://gitlab.com/sqlrif/odoo-scada-plc-connector)

</div>
