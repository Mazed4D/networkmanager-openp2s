__version__ = "0.1.0"

SERVICE_NAME = "org.freedesktop.NetworkManager.openp2s"

LIBEXEC_DIR = "/usr/lib/nm-openp2s"
OPENVPN_BINARY = f"{LIBEXEC_DIR}/openvpn"
HELPER_BINARY = f"{LIBEXEC_DIR}/bin/nm-openp2s-helper"

CA_PATH = "/etc/ssl/certs/DigiCert_Global_Root_G2.pem"

AZURE_USERNAME = "AzureAD"

AGENT_SOCKET = "nm-openp2s/agent.sock"
