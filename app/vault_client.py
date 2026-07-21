import os
import hvac


class VaultSecretsManager:
    def __init__(self):
        self.vault_url = os.getenv(
            "VAULT_ADDR", "http://vault.default.svc.cluster.local:8200"
        )
        self.role_name = os.getenv("VAULT_ROLE", "agent-role")
        self.token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        self.client = None

    def _login_kubernetes(self):
        """Authenticates with Vault using the local Kubernetes ServiceAccount token."""
        if not os.path.exists(self.token_path):
            raise FileNotFoundError(
                f"K8s ServiceAccount token not found at {self.token_path}. Ensure SA is mounted."
            )

        with open(self.token_path, "r") as f:
            jwt_token = f.read().strip()

        # Initialize Vault client
        self.client = hvac.Client(url=self.vault_url)

        # Login to Kubernetes auth mount
        response = self.client.auth.kubernetes.login(role=self.role_name, jwt=jwt_token)

        # Set retrieved client token
        self.client.token = response["auth"]["client_token"]

    def get_gemini_api_key(self) -> str:
        """Retrieves the Gemini API Key from Vault kv engine."""
        secrets = self.get_secrets()
        return secrets["api_key"]

    def get_secrets(self) -> dict:
        """Retrieves all credentials stored in the Vault 'gemini' secret."""
        # For local development / manual execution fallback
        dev_token = os.getenv("VAULT_DEV_TOKEN")
        if dev_token:
            self.client = hvac.Client(url=self.vault_url, token=dev_token)
        else:
            self._login_kubernetes()

        # Read KV v2 secret
        secret_response = self.client.secrets.kv.v2.read_secret_version(
            path="gemini", raise_on_deleted_version=True
        )

        # Extract and return secret data
        return secret_response["data"]["data"]
