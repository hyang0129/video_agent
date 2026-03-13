"""Dev TLS certificate generation using trustme.

Generates a self-signed CA + server cert for local HTTPS development.
For production, point MCP_CERT_FILE / MCP_KEY_FILE at real CA-issued certs.
"""

from __future__ import annotations

from pathlib import Path


def generate_dev_cert(cert_path: Path, key_path: Path) -> None:
    """Write a self-signed server cert + key to cert_path / key_path.

    Also writes ca.pem into the same directory so clients can trust it
    with MCP_CA_BUNDLE=certs/ca.pem.
    """
    import trustme

    ca = trustme.CA()
    server_cert = ca.issue_cert("localhost", "127.0.0.1")
    ca_pem_path = cert_path.parent / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_pem_path))
    server_cert.private_key_pem.write_to_path(str(key_path))
    server_cert.cert_chain_pems[0].write_to_path(str(cert_path))
