# IBM Cloud VPC GPU Instance Manager with Multi-Zone Failover

Automated management system for GPU-enabled Virtual Server Instances (VSI) in IBM Cloud VPC with intelligent multi-zone failover, snapshot-based recovery, and cost optimization through scheduled start/stop operations.

[![IBM Cloud](https://img.shields.io/badge/IBM%20Cloud-VPC-blue)](https://cloud.ibm.com/vpc-ext)
[![Python](https://img.shields.io/badge/Python-3.11-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## 🎯 Features

- **🔄 Multi-Zone Failover**: Automatic retry across 3 availability zones (us-east-1, us-east-2, us-east-3)
- **📸 Snapshot Recovery**: Boot and data volumes restored from daily snapshots
- **💰 Cost Optimization**: Scheduled start (7 AM) and stop (7 PM) operations
- **🌐 Fixed IP**: Consistent IP address (10.10.10.20) across zones
- **🔐 VPN Integration**: Site-to-Site VPN connectivity with dedicated subnet
- **☁️ State Persistence**: Cloud Object Storage (COS) for state and logs
- **🤖 Automated Cleanup**: Intelligent resource cleanup on failure
- **📊 Comprehensive Logging**: Detailed execution logs in COS

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    IBM Cloud VPC (us-east)                   │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Zone 1     │  │   Zone 2     │  │   Zone 3     │      │
│  │  us-east-1   │  │  us-east-2   │  │  us-east-3   │      │
│  │              │  │              │  │              │      │
│  │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │      │
│  │ │GPU VSI   │ │  │ │GPU VSI   │ │  │ │GPU VSI   │ │      │
│  │ │10.10.10  │ │  │ │10.10.10  │ │  │ │10.10.10  │ │      │
│  │ │  .20     │ │  │ │  .20     │ │  │ │  .20     │ │      │
│  │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         VPN Gateway (Dedicated Subnet)                  │ │
│  │              10.10.10.0/28                              │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Code Engine     │
                    │  (Cron Jobs)     │
                    │  - 7:00 AM Start │
                    │  - 7:00 PM Stop  │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Cloud Object    │
                    │  Storage (COS)   │
                    │  - State         │
                    │  - Logs          │
                    └──────────────────┘
```

## 📋 Prerequisites

- IBM Cloud account with permissions for:
  - VPC Infrastructure
  - Code Engine
  - Cloud Object Storage
  - Container Registry
- IBM Cloud CLI with plugins:
  - `vpc-infrastructure`
  - `code-engine`
  - `container-registry`
- Docker or Podman installed
- Python 3.11+ (for local testing)

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd <repository-name>
```

### 2. Configure Environment

```bash
# Set IBM Cloud API Key
export IBM_CLOUD_API_KEY="your-api-key"

# Set COS Instance ID (optional but recommended)
export COS_INSTANCE_ID="your-cos-instance-id"

# Configure snapshots
./setup_snapshots.sh
```

### 3. Update Configuration

Edit `config.json` with your VPC details:

```json
{
  "vpc": {
    "id": "your-vpc-id",
    "name": "your-vpc-name"
  },
  "vsi_ip": "10.10.10.20",
  "vsi_profile": "gx3-48x240x2l40s",
  "resource_group_id": "your-resource-group-id",
  "ssh_key_ids": ["your-ssh-key-id"],
  "security_group_ids": ["your-security-group-id"]
}
```

### 4. Deploy

```bash
# Make scripts executable
chmod +x deploy_advanced.sh setup_snapshots.sh cleanup_resources.sh

# Deploy to IBM Cloud Code Engine
./deploy_advanced.sh
```

## 📁 Project Structure

```
.
├── vsi_advanced_manager_cos.py  # Main VSI management script
├── cos_storage.py               # Cloud Object Storage client
├── deploy_advanced.sh           # Deployment script
├── setup_snapshots.sh           # Snapshot configuration
├── cleanup_resources.sh         # Resource cleanup utility
├── config.json                  # Configuration file
├── Dockerfile                   # Container image
├── requirements.txt             # Python dependencies
├── .gitignore                   # Git ignore rules
├── README.md                    # This file
└── GUIA_DESPLIEGUE_PASO_A_PASO.md  # Detailed deployment guide (Spanish)
```

## 🔧 Configuration

### Network Configuration

The system uses two separate networks:

1. **VPN Gateway Subnet** (Protected)
   - CIDR: `10.10.10.0/28`
   - Zone: `us-east-1` (fixed)
   - **Never deleted**

2. **Compute Subnet** (Dynamic)
   - CIDR: `10.10.10.16/28`
   - Zone: Any available (us-east-1, us-east-2, us-east-3)
   - VSI IP: `10.10.10.20` (fixed)
   - Created/deleted based on availability

### Snapshot Configuration

Configure snapshot IDs using the interactive script:

```bash
./setup_snapshots.sh
```

This will:
1. List available snapshots
2. Prompt for boot and data volume snapshot IDs
3. Update Code Engine secrets

## 🔄 Failover Logic

When a VSI fails to start in a zone:

1. **Detect Failure**: Monitor instance status for up to 10 minutes
2. **Wait Period**: 30 seconds before cleanup
3. **Delete Instance**: Remove failed instance (30s wait)
4. **Delete Subnet**: Remove subnet (2s wait)
5. **Delete Address Prefix**: Remove address prefix (1s wait)
6. **Retry Next Zone**: Attempt creation in next available zone

Total cleanup time per failed zone: ~63 seconds

## 📊 Monitoring

### View Job Runs

```bash
# List all job runs
ibmcloud ce jobrun list

# View logs
ibmcloud ce jobrun logs --name <jobrun-name>

# Follow logs in real-time
ibmcloud ce jobrun logs --follow --job tunal-smart-start
```

### Check VSI Status

```bash
# List instances
ibmcloud is instances

# Get instance details
ibmcloud is instance <instance-id>

# Check network interfaces
ibmcloud is instance-network-interfaces <instance-id>
```

### COS State

```bash
# View saved state
ibmcloud cos object-get \
  --bucket tunal-automation \
  --key state/vsi_state.json \
  --region us-east

# List execution logs
ibmcloud cos objects \
  --bucket tunal-automation \
  --prefix logs/execution/ \
  --region us-east
```

## 🛠️ Maintenance

### Update Snapshots

When new snapshots are available:

```bash
./setup_snapshots.sh
```

### Clean Up Resources

To manually clean up compute resources (protects VPN subnet):

```bash
./cleanup_resources.sh
```

### Redeploy

After code changes:

```bash
./deploy_advanced.sh
```

## 🐛 Troubleshooting

### VSI Fails to Start

1. Check logs: `ibmcloud ce jobrun logs --job tunal-smart-start --tail 200`
2. Verify snapshots exist: `ibmcloud is snapshots`
3. Check zone capacity: `ibmcloud is instance-profiles gx3-48x240x2l40s`

### Network Issues

1. Verify address prefixes: `ibmcloud is vpc-address-prefixes <vpc-id>`
2. Check subnets: `ibmcloud is subnets`
3. Verify VPN: `ibmcloud is vpn-gateways`

### COS Issues

1. Verify bucket: `ibmcloud cos buckets --region us-east`
2. Check contents: `ibmcloud cos objects --bucket tunal-automation --region us-east`

## 💰 Cost Optimization

- **Estimated Savings**: ~50% vs 24/7 operation
- **Active Hours**: 12 hours/day (7 AM - 7 PM)
- **Snapshots**: Incremental backups (low cost)
- **Code Engine**: Pay-per-use (cron jobs)

## 🔐 Security

- **Secrets**: Stored in Code Engine secrets
- **API Keys**: Never in source code
- **COS**: Private bucket with restricted access
- **VPN**: Site-to-Site for secure connectivity
- **Network**: Isolated subnets with security groups

## 📝 Important Notes

1. **VPN Subnet**: The subnet `10.10.10.0/28` is for VPN Gateway and must **NEVER** be deleted
2. **Fixed IP**: VSI always gets IP `10.10.10.20` regardless of zone
3. **Cleanup Order**: Always delete in order: Instance → Subnet → Address Prefix
4. **Resource Group**: All resources created in specified resource group
5. **Snapshots**: Must be updated manually when IDs change

## 📄 License

Apache License 2.0 - See [LICENSE](LICENSE) file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

For issues or questions:
1. Check logs in Code Engine
2. Verify state in COS
3. Consult IBM Cloud VPC documentation
4. Open an issue in this repository

## 🙏 Acknowledgments

- IBM Cloud VPC team for the infrastructure
- IBM Cloud Code Engine for serverless execution
- IBM Cloud Object Storage for state persistence

---

**Version**: 2.0  
**Last Updated**: June 2026  
**Status**: Production Ready ✅