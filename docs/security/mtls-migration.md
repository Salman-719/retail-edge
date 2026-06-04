# mTLS Migration Path

## Current state (M4-S2)

The EEP ↔ Edge Agent gRPC channel uses:
- **TLS** — server presents a certificate signed by the private CA; edge devices verify via `ca.crt`
- **Shared secret** — edge agents send `AGENT_SECRET` as `x-agent-token` metadata; EEP validates with constant-time comparison

This eliminates plaintext channels and unauthenticated connections. The shared secret is a pragmatic first step; it does not provide per-device identity.

## mTLS target state

mTLS replaces the shared secret with per-device client certificates. Each edge device gets a unique certificate at commissioning, signed by the private CA. The `store_id` is embedded in the certificate CN and validated server-side — no separate token needed.

### Migration steps

1. **Generate per-device client certificates at commissioning**
   ```bash
   openssl genrsa -out client-${STORE_ID}.key 2048
   openssl req -new -key client-${STORE_ID}.key \
     -out client-${STORE_ID}.csr \
     -subj "/CN=store:${STORE_ID}"
   openssl x509 -req -days 365 \
     -in client-${STORE_ID}.csr \
     -CA ca.crt -CAkey ca.key -CAcreateserial \
     -out client-${STORE_ID}.crt
   ```
   Deploy `client-${STORE_ID}.crt` and `client-${STORE_ID}.key` to `/etc/retailvision/certs/` on the device.

2. **Update Edge Agent channel credentials** (`services/edge_agent/app/agent.py`)
   ```python
   def _load_channel_credentials() -> grpc.ChannelCredentials:
       with open(GRPC_CA_CERT_PATH, "rb") as f:
           ca_cert = f.read()
       with open(os.environ["GRPC_CLIENT_CERT_PATH"], "rb") as f:
           client_cert = f.read()
       with open(os.environ["GRPC_CLIENT_KEY_PATH"], "rb") as f:
           client_key = f.read()
       return grpc.ssl_channel_credentials(
           root_certificates=ca_cert,
           private_key=client_key,
           certificate_chain=client_cert,
       )
   ```

3. **Update EEP server to require client auth** (`services/eep/app/grpc_server/server.py`)
   ```python
   grpc.ssl_server_credentials(
       [(key, cert)],
       root_certificates=ca_cert_bytes,
       require_client_auth=True,
   )
   ```

4. **Extract `store_id` from cert CN in interceptor** (`services/eep/app/grpc_server/interceptor.py`)
   - Use `context.auth_context()` to retrieve the peer certificate
   - Parse CN from the Subject: `CN=store:{store_uuid}`
   - Validate that the `store_id` in the CN matches the `store_id` in the RPC payload
   - Reject mismatches with `PERMISSION_DENIED`

5. **Deprecate `AGENT_SECRET`**
   - Remove `x-agent-token` metadata from Edge Agent
   - Remove `AgentAuthInterceptor` token check from EEP
   - Remove `AGENT_SECRET` from Settings and env vars

### Why defer mTLS

- Requires a PKI rollout: per-device cert issuance, revocation (CRL/OCSP), renewal automation
- Commissioning workflow must be updated to generate and deploy client certs
- Shared secret achieves the primary security goal (no unauthenticated channels) with zero PKI infrastructure
