"""Shared external LLM input configuration."""

from benchmark_generate.simai.bootstrap import SIMAI_ROOT

AICB_ROOT = SIMAI_ROOT / "inputs" / "aicb-workload"
TOPO_ROOT = SIMAI_ROOT / "inputs" / "topologies"
TOPOLOGIES = {
    "alibaba_hpn_16g": ("AlibabaHPN_16g_8gps_DualToR_DualPlane_200Gbps_A100", "production", 200.0),
    "spectrum_x_16g": ("Spectrum-X_16g_8gps_400Gbps_H100", "production", 400.0),
    "dcn_dual_tor_64g": ("DCN+DualToR_64g_8gps_200Gbps_A100", "production", 200.0),
    "cassini_24g": ("Cassini_24g_l1-6_l2-4_l3-3_400Gbps_A100", "experimental", 400.0),
    "cassini_64g": ("Cassini_64g_l1-16_l2-14_l3-12_400Gbps_A100", "experimental", 400.0),
    "hermod_32g": ("Hermod_32g_4server_2nic_4sn3700_100Gbps_A100", "experimental", 100.0),
}
TOPOLOGY_CAPACITIES = {
    "alibaba_hpn_16g": 16, "spectrum_x_16g": 16, "dcn_dual_tor_64g": 64,
    "cassini_24g": 24, "cassini_64g": 64, "hermod_32g": 32,
}

__all__ = ["AICB_ROOT", "TOPO_ROOT", "TOPOLOGIES", "TOPOLOGY_CAPACITIES", "SIMAI_ROOT"]
