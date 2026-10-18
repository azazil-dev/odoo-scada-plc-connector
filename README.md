<div align="center">

# ⚡ Odoo SCADA PLC Connector

### SCADA & Industrial IoT Integration Platform for **Odoo 17 Community Edition**

![Odoo](https://img.shields.io/badge/Odoo-17%20CE-875A7B?style=for-the-badge&logo=odoo&logoColor=white)
![Version](https://img.shields.io/badge/version-17.0.1.0.0-0284C7?style=for-the-badge)
![License](https://img.shields.io/badge/license-LGPL--3-6B8E23?style=for-the-badge)
![IEC 62443](https://img.shields.io/badge/security-IEC%2062443%20Ready-E11D48?style=for-the-badge)

**Connect real factory machinery to Odoo — no code required.**

📖 **[Full Documentation (README lengkap)](scada_plc_connector/README.md)** → fitur, arsitektur, REST API, quick start, Driver SDK

</div>

---

## 📦 Isi Repositori

| Folder | Deskripsi |
|--------|-----------|
| [`scada_plc_connector/`](scada_plc_connector/) | Modul Odoo 17 CE — platform integrasi SCADA/PLC (aplikasi penuh, LGPL-3) |

## ⚡ Ringkas

- **Protokol**: Simulator & Modbus TCP (aktif) · OPC UA, Siemens S7, MQTT/Sparkplug B (fase 2)
- **Alur data**: `PLC → Edge Gateway → REST API Odoo → Historian + Rule Engine → MRP / Maintenance`
- **Fitur**: manajemen gateway & API Key SHA-256, tag 8 tipe data dengan transformasi, rule engine (histeresis/debounce/ durasi minimum), alarm lifecycle, penulisan PLC aman ala IEC 62443 dengan audit append-only, historian + agregasi, RBAC 4 level, simulator bawaan tanpa PLC fisik.

## 🚀 Instalasi Cepat

```bash
git clone -b 17.0 git@github.com:azazil-dev/odoo-scada-plc-connector.git
# tempatkan scada_plc_connector/ di addons path Anda, lalu install dari UI Odoo (Apps → SCADA PLC Connector)
```

## 🔗 Link untuk Odoo Apps Store

```
ssh://git@github.com/azazil-dev/odoo-scada-plc-connector#17.0
```

## 📜 License

LGPL-3 · Author: **Arif N Ramadhan** · [NIITS](https://www.niits.id)

<div align="center">

[GitHub](https://github.com/azazil-dev/odoo-scada-plc-connector) · [GitLab](https://gitlab.com/sqlrif/odoo-scada-plc-connector)

</div>
