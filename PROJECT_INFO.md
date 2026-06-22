# IBM Cloud VPC GPU Instance Manager - Project Information

## 📋 Project Overview

This project provides an automated solution for managing GPU-enabled Virtual Server Instances (VSI) in IBM Cloud VPC with multi-zone failover capability, snapshot-based recovery, and cost optimization through scheduled start/stop operations.

## 🎯 Key Features

- **Multi-Zone Failover**: Automatically tries alternative availability zones if resources are unavailable
- **Snapshot-Based Recovery**: Daily snapshots of boot and data volumes for disaster recovery
- **Cost Optimization**: Scheduled shutdown at 7:00 PM and startup at 7:00 AM
- **Cloud Object Storage Integration**: Persistent state management and logging
- **VPN Site-to-Site Support**: Dedicated subnet for VPN gateway with dynamic compute subnets
- **Fixed IP Assignment**: VSI configured with static IP (10.10.10.20)
- **Intelligent Resource Cleanup**: Proper order of resource deletion with timing controls

## 🏗️ Architecture

### Network Design
- **VPN Gateway Subnet**: 10.10.10.0/28 (fixed, protected)
- **Compute Subnet**: 10.10.10.16/28 (dynamic, created per zone)
- **VSI Fixed IP**: 10.10.10.20

### Multi-Zone Strategy
1. **Zone 1 (us-east-1)**: Primary zone
2. **Zone 2 (us-east-2)**: First failover
3. **Zone 3 (us-east-3)**: Second failover

### Resource Cleanup Order
1. Delete VSI instance (wait 30 seconds)
2. Delete compute subnet (wait 30 seconds)
3. Delete address prefix

## 📁 Project Structure

```
.
├── vsi_advanced_manager_cos.py    # Main orchestration script
├── cos_storage.py                  # Cloud Object Storage client
├── deploy_advanced.sh              # Deployment script (Podman/Docker)
├── setup_snapshots.sh              # Snapshot policy setup
├── cleanup_resources.sh            # Manual cleanup script
├── config.json.example             # Configuration template
├── Dockerfile                      # Container image definition
├── requirements.txt                # Python dependencies
├── .gitignore                      # Git exclusions
├── LICENSE                         # Apache 2.0 License
├── README.md                       # Main documentation
└── GUIA_DESPLIEGUE_PASO_A_PASO.md # Detailed Spanish guide
```

## 🚀 Quick Start

1. **Configure credentials**:
   ```bash
   cp config.json.example config.json
   # Edit config.json with your IBM Cloud credentials
   ```

2. **Deploy to Code Engine**:
   ```bash
   chmod +x deploy_advanced.sh
   ./deploy_advanced.sh
   ```

3. **Setup snapshot policies**:
   ```bash
   chmod +x setup_snapshots.sh
   ./setup_snapshots.sh
   ```

## 🔧 Configuration

Key configuration parameters in `config.json`:

- **IBM Cloud Credentials**: API key, region, resource group
- **VPC Settings**: VPC ID, security group, SSH key
- **Network Configuration**: VPN and compute subnet CIDRs
- **VSI Profile**: gx3-48x240x2l40s (L40S GPUs)
- **Snapshot IDs**: Boot and data volume snapshots
- **COS Settings**: Bucket name, endpoint, credentials

## 📊 Operational Flow

### Morning Startup (7:00 AM)
1. Check if VSI exists and is running
2. If not, attempt to create from snapshots in Zone 1
3. If Zone 1 fails, cleanup and try Zone 2
4. If Zone 2 fails, cleanup and try Zone 3
5. Save successful instance state to COS

### Evening Shutdown (7:00 PM)
1. Retrieve instance ID from COS
2. Stop the VSI instance
3. Update state in COS

### Daily Snapshot (6:30 PM)
1. Snapshot policy automatically captures volumes
2. New snapshot IDs must be updated in config.json

## 🛠️ Maintenance Tasks

### Update Snapshot IDs
After daily snapshots are created, update `config.json`:
```json
{
  "boot_volume_snapshot_id": "r006-new-snapshot-id",
  "data_volume_snapshot_id": "r006-new-snapshot-id"
}
```

### Manual Cleanup
If resources need manual cleanup:
```bash
chmod +x cleanup_resources.sh
./cleanup_resources.sh
```

### View Logs
Logs are stored in COS bucket under `logs/` prefix.

## 🔐 Security Considerations

- Never commit `config.json` with real credentials
- Use IBM Cloud IAM for access control
- Rotate API keys regularly
- Review security group rules periodically
- Enable VPC flow logs for network monitoring

## 📈 Cost Optimization

- **Daily Shutdown**: ~13 hours of savings per day
- **Multi-Zone Strategy**: Only pay for resources in active zone
- **Snapshot Storage**: Incremental snapshots reduce storage costs
- **Code Engine**: Pay only for job execution time

## 🐛 Troubleshooting

### VSI Fails to Start
- Check GPU availability in all zones
- Verify snapshot IDs are valid
- Review Code Engine job logs

### Network Connectivity Issues
- Verify VPN gateway is running
- Check security group rules
- Confirm subnet routing

### Snapshot Policy Not Working
- Verify IAM permissions
- Check snapshot policy schedule
- Review backup service logs

## 📚 Additional Resources

- [IBM Cloud VPC Documentation](https://cloud.ibm.com/docs/vpc)
- [Code Engine Documentation](https://cloud.ibm.com/docs/codeengine)
- [VPC Snapshots Documentation](https://cloud.ibm.com/docs/vpc?topic=vpc-snapshots-vpc-about)

## 📝 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## 👥 Support

For issues or questions:
1. Check the troubleshooting section in README.md
2. Review Code Engine job logs
3. Check COS logs for detailed execution history

## 🔄 Version History

- **v1.0.0** (2026-06-22): Initial release with multi-zone failover
  - Multi-zone failover capability
  - Snapshot-based recovery
  - COS integration for state management
  - Scheduled start/stop operations
  - VPN Site-to-Site support